import json
from pathlib import Path

from qbu_crawler import config


def _row_dict(row):
    return dict(row) if row is not None else None


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table):
    if not _table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _decode_payload(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _artifact_map(conn, run_id):
    if not _table_exists(conn, "report_artifacts"):
        return {}
    rows = conn.execute(
        "SELECT * FROM report_artifacts WHERE run_id=? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    artifacts = {}
    for row in rows:
        item = _row_dict(row)
        artifacts[item.get("artifact_type") or f"artifact_{item.get('id')}"] = {
            "path": item.get("path"),
            "hash": item.get("hash"),
            "bytes": item.get("bytes"),
            "template_version": item.get("template_version"),
            "generator_version": item.get("generator_version"),
            "created_at": item.get("created_at"),
        }
    return artifacts


def _workflow_notifications(conn, run_id):
    if not _table_exists(conn, "notification_outbox"):
        return []
    rows = conn.execute(
        "SELECT * FROM notification_outbox ORDER BY id ASC",
    ).fetchall()
    result = []
    for row in rows:
        item = _row_dict(row)
        payload = _decode_payload(item.get("payload"))
        if int(payload.get("run_id") or 0) != int(run_id):
            continue
        if not str(item.get("kind") or "").startswith("workflow_"):
            continue
        item["payload"] = payload
        result.append(item)
    return result


def _email_delivered(notifications):
    for item in notifications:
        if item.get("kind") == "workflow_full_report":
            payload = item.get("payload") or {}
            return payload.get("email_status") == "success"
    return False


def _delivery(run, artifacts, notifications):
    statuses = [item.get("status") for item in notifications]
    deadletters = [item for item in notifications if item.get("status") == "deadletter"]
    pending = [item for item in notifications if item.get("status") in {"pending", "claimed", "failed"}]
    sent = [item for item in notifications if item.get("status") == "sent"]
    report_generated = bool(
        artifacts.get("xlsx")
        or artifacts.get("html_attachment")
        or artifacts.get("email_body")
        or (run or {}).get("excel_path")
    )
    workflow_delivered = bool(notifications) and len(sent) == len(notifications) and not deadletters and not pending
    last_errors = [
        item.get("last_error")
        for item in deadletters
        if item.get("last_error")
    ]
    return {
        "report_generated": report_generated,
        "email_delivered": _email_delivered(notifications),
        "workflow_notification_delivered": workflow_delivered,
        "deadletter_count": len(deadletters),
        "pending_count": len(pending),
        "sent_count": len(sent),
        "internal_status": (run or {}).get("report_phase") or (run or {}).get("status") or "unknown",
        "last_errors": last_errors[:5],
        "notification_statuses": statuses,
    }


def build_report_manifest(conn, run_id):
    run = None
    if _table_exists(conn, "workflow_runs"):
        run = _row_dict(conn.execute(
            "SELECT * FROM workflow_runs WHERE id=?",
            (run_id,),
        ).fetchone())
    artifacts = _artifact_map(conn, run_id)
    notifications = _workflow_notifications(conn, run_id)
    return {
        "run_id": run_id,
        "logical_date": (run or {}).get("logical_date"),
        "artifacts": artifacts,
        "delivery": _delivery(run, artifacts, notifications),
    }


def _resolve_analytics_path(path):
    if not path:
        return None
    raw = Path(path)
    if raw.is_file():
        return raw
    candidate = Path(config.REPORT_DIR) / raw
    if candidate.is_file():
        return candidate
    return raw


def update_analytics_delivery_from_db(conn, run_id, analytics_path=None):
    if analytics_path is None and _table_exists(conn, "workflow_runs"):
        if "analytics_path" not in _table_columns(conn, "workflow_runs"):
            return None
        row = conn.execute(
            "SELECT analytics_path FROM workflow_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        analytics_path = row["analytics_path"] if row and hasattr(row, "keys") else (row[0] if row else None)
    path = _resolve_analytics_path(analytics_path)
    if path is None or not path.is_file():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = build_report_manifest(conn, run_id)
    data["report_manifest"] = manifest
    data["delivery"] = manifest["delivery"]
    contract = data.setdefault("report_user_contract", {})
    contract["delivery"] = manifest["delivery"]
    try:
        from qbu_crawler.server.report_contract import validate_report_user_contract
        warnings = list(contract.get("validation_warnings") or [])
        for warning in validate_report_user_contract(contract):
            if warning not in warnings:
                warnings.append(warning)
        contract["validation_warnings"] = warnings
    except Exception:
        pass
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return manifest
