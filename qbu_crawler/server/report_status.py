import json


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _table_columns(conn, table):
    if not _table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _row_dict(cursor, row):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    names = [item[0] for item in cursor.description]
    return dict(zip(names, row))


def _decode_payload(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _workflow_notifications(conn, run_id):
    if not _table_exists(conn, "notification_outbox"):
        return []
    cur = conn.execute("SELECT * FROM notification_outbox ORDER BY id ASC")
    result = []
    for row in cur.fetchall():
        item = _row_dict(cur, row)
        payload = _decode_payload(item.get("payload"))
        if int(payload.get("run_id") or 0) != int(run_id):
            continue
        if not str(item.get("kind") or "").startswith("workflow_"):
            continue
        item["payload"] = payload
        result.append(item)
    return result


def _artifact_generated(conn, run):
    if (run or {}).get("excel_path") or (run or {}).get("analytics_path") or (run or {}).get("pdf_path"):
        return True
    if not _table_exists(conn, "report_artifacts"):
        return False
    return conn.execute(
        "SELECT 1 FROM report_artifacts WHERE run_id=? LIMIT 1",
        (run["id"],),
    ).fetchone() is not None


def derive_email_delivery_status(full_report_email=None, payload=None):
    if full_report_email:
        if full_report_email.get("success") is True:
            return "sent"
        if full_report_email.get("success") is False:
            return "failed"
    payload = payload or {}
    value = payload.get("email_status")
    if value == "success":
        return "sent"
    if value in {"failed", "skipped"}:
        return value
    return "unknown"


def derive_workflow_notification_status(notifications):
    notifications = notifications or []
    statuses = [item.get("status") for item in notifications]
    deadletters = [item for item in notifications if item.get("status") == "deadletter"]
    pending = [item for item in notifications if item.get("status") in {"pending", "claimed", "failed"}]
    sent = [item for item in notifications if item.get("status") in {"sent", "delivered"}]
    last_errors = [
        item.get("last_error")
        for item in notifications
        if item.get("last_error")
    ]
    if deadletters:
        status = "deadletter"
    elif notifications and len(sent) == len(notifications):
        status = "sent"
    elif sent and (pending or len(sent) < len(notifications)):
        status = "partial"
    elif pending:
        status = "pending"
    else:
        status = "unknown"
    return {
        "workflow_notification_status": status,
        "delivery_last_error": last_errors[0] if last_errors else None,
        "deadletter_count": len(deadletters),
        "pending_count": len(pending),
        "sent_count": len(sent),
        "notification_statuses": statuses,
    }


def sync_workflow_report_status(conn, run_id):
    from qbu_crawler.server.migrations import migration_0012_report_status_columns as mig0012

    cols = _table_columns(conn, "workflow_runs")
    if "report_generation_status" not in cols:
        mig0012.up(conn)

    cur = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,))
    run = _row_dict(cur, cur.fetchone())
    if not run:
        return {}

    notifications = _workflow_notifications(conn, run_id)
    workflow_status = derive_workflow_notification_status(notifications)
    email_status = "unknown"
    for item in notifications:
        if item.get("kind") == "workflow_full_report":
            email_status = derive_email_delivery_status(payload=item.get("payload") or {})
            break

    report_status = run.get("report_generation_status") or "unknown"
    if _artifact_generated(conn, run):
        report_status = "generated"
    elif run.get("status") == "needs_attention" and run.get("error"):
        report_status = "failed"

    updates = {
        "report_generation_status": report_status,
        "workflow_notification_status": workflow_status["workflow_notification_status"],
        "delivery_checked_at": "CURRENT_TIMESTAMP",
    }
    if email_status != "unknown":
        updates["email_delivery_status"] = email_status
    elif run.get("email_delivery_status"):
        updates["email_delivery_status"] = run.get("email_delivery_status")
    if workflow_status.get("delivery_last_error"):
        updates["delivery_last_error"] = workflow_status["delivery_last_error"]

    assignments = []
    values = []
    for key, value in updates.items():
        if key == "delivery_checked_at" and value == "CURRENT_TIMESTAMP":
            assignments.append("delivery_checked_at=CURRENT_TIMESTAMP")
            continue
        assignments.append(f"{key}=?")
        values.append(value)
    conn.execute(
        f"UPDATE workflow_runs SET {', '.join(assignments)} WHERE id=?",
        [*values, run_id],
    )
    conn.commit()

    cur = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,))
    row = _row_dict(cur, cur.fetchone()) or {}
    return {
        "report_generation_status": row.get("report_generation_status"),
        "email_delivery_status": row.get("email_delivery_status"),
        "workflow_notification_status": row.get("workflow_notification_status"),
        "delivery_last_error": row.get("delivery_last_error"),
        "delivery_checked_at": row.get("delivery_checked_at"),
    }
