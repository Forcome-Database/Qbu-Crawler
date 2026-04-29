import json
import logging
import sqlite3

log = logging.getLogger(__name__)

UP_SQL = [
    "ALTER TABLE workflow_runs ADD COLUMN report_generation_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE workflow_runs ADD COLUMN email_delivery_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE workflow_runs ADD COLUMN workflow_notification_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE workflow_runs ADD COLUMN delivery_last_error TEXT",
    "ALTER TABLE workflow_runs ADD COLUMN delivery_checked_at TEXT",
]

DOWN_SQL = [
    "ALTER TABLE workflow_runs DROP COLUMN report_generation_status",
    "ALTER TABLE workflow_runs DROP COLUMN email_delivery_status",
    "ALTER TABLE workflow_runs DROP COLUMN workflow_notification_status",
    "ALTER TABLE workflow_runs DROP COLUMN delivery_last_error",
    "ALTER TABLE workflow_runs DROP COLUMN delivery_checked_at",
]


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _table_columns(conn, table):
    if not _table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _decode_payload(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _row_dict(cursor, row):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    names = [item[0] for item in cursor.description]
    return dict(zip(names, row))


def _artifact_generated(conn, run):
    if run.get("excel_path") or run.get("analytics_path") or run.get("pdf_path"):
        return True
    if not _table_exists(conn, "report_artifacts"):
        return False
    return conn.execute(
        "SELECT 1 FROM report_artifacts WHERE run_id=? LIMIT 1",
        (run["id"],),
    ).fetchone() is not None


def _workflow_notifications(conn, run_id):
    if not _table_exists(conn, "notification_outbox"):
        return []
    cur = conn.execute("SELECT * FROM notification_outbox ORDER BY id ASC")
    rows = []
    for row in cur.fetchall():
        item = _row_dict(cur, row)
        payload = _decode_payload(item.get("payload"))
        if int(payload.get("run_id") or 0) != int(run_id):
            continue
        if not str(item.get("kind") or "").startswith("workflow_"):
            continue
        item["payload"] = payload
        rows.append(item)
    return rows


def _email_status(notifications):
    for item in notifications:
        if item.get("kind") != "workflow_full_report":
            continue
        value = (item.get("payload") or {}).get("email_status")
        if value == "success":
            return "sent"
        if value == "failed":
            return "failed"
        if value == "skipped":
            return "skipped"
    return "unknown"


def _notification_status(notifications):
    if not notifications:
        return {"workflow_notification_status": "unknown", "delivery_last_error": None}
    statuses = {item.get("status") for item in notifications}
    errors = [item.get("last_error") for item in notifications if item.get("last_error")]
    if "deadletter" in statuses:
        return {"workflow_notification_status": "deadletter", "delivery_last_error": errors[0] if errors else None}
    delivered = {"sent", "delivered"}
    if statuses and statuses <= delivered:
        return {"workflow_notification_status": "sent", "delivery_last_error": None}
    if statuses & delivered:
        return {"workflow_notification_status": "partial", "delivery_last_error": errors[0] if errors else None}
    return {"workflow_notification_status": "pending", "delivery_last_error": errors[0] if errors else None}


def up(conn):
    cur = conn.cursor()
    for sql in UP_SQL:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError as exc:
            if "duplicate column" in str(exc).lower():
                continue
            raise
    conn.commit()


def backfill(conn, force=False):
    if not _table_exists(conn, "workflow_runs"):
        return
    cols = _table_columns(conn, "workflow_runs")
    required = {
        "report_generation_status",
        "email_delivery_status",
        "workflow_notification_status",
        "delivery_last_error",
        "delivery_checked_at",
    }
    if not required <= cols:
        up(conn)

    cur = conn.execute("SELECT * FROM workflow_runs ORDER BY id ASC")
    rows = [_row_dict(cur, row) for row in cur.fetchall()]
    for run in rows:
        updates = {}
        if force or run.get("report_generation_status") in (None, "unknown"):
            if _artifact_generated(conn, run):
                updates["report_generation_status"] = "generated"
            elif run.get("status") == "needs_attention" and run.get("error"):
                updates["report_generation_status"] = "failed"
        notifications = _workflow_notifications(conn, run["id"])
        if force or run.get("email_delivery_status") in (None, "unknown"):
            email_status = _email_status(notifications)
            if email_status != "unknown":
                updates["email_delivery_status"] = email_status
        notification_status = _notification_status(notifications)
        if force or run.get("workflow_notification_status") in (None, "unknown"):
            if notification_status["workflow_notification_status"] != "unknown":
                updates["workflow_notification_status"] = notification_status["workflow_notification_status"]
        if notification_status.get("delivery_last_error") and (force or not run.get("delivery_last_error")):
            updates["delivery_last_error"] = notification_status["delivery_last_error"]
        if (
            notification_status["workflow_notification_status"] == "deadletter"
            and run.get("report_phase") == "full_sent"
        ):
            updates["report_phase"] = "full_sent_local"
        if not updates:
            continue
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE workflow_runs SET {assignments}, delivery_checked_at=CURRENT_TIMESTAMP WHERE id=?",
            [*updates.values(), run["id"]],
        )
    conn.commit()


def down(conn):
    cur = conn.cursor()
    for sql in DOWN_SQL:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError as exc:
            log.warning("migration_0012 down() skipped: %s - %s", sql, exc)
            continue
    conn.commit()
