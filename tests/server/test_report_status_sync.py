import json
import sqlite3

from qbu_crawler import models
from qbu_crawler.server.report_contract import validate_report_user_contract
from qbu_crawler.server.report_status import derive_workflow_notification_status


def test_update_workflow_report_status_persists_columns(tmp_path, monkeypatch):
    from qbu_crawler import config

    db = tmp_path / "status.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()
    run = models.create_workflow_run({
        "workflow_type": "daily",
        "status": "reporting",
        "logical_date": "2026-04-28",
        "trigger_key": "daily:2026-04-28",
    })

    models.update_workflow_report_status(
        run["id"],
        report_generation_status="generated",
        email_delivery_status="sent",
        workflow_notification_status="deadletter",
        delivery_last_error="bridge returned HTTP 401",
    )

    loaded = models.get_workflow_run(run["id"])
    assert loaded["report_generation_status"] == "generated"
    assert loaded["email_delivery_status"] == "sent"
    assert loaded["workflow_notification_status"] == "deadletter"
    assert loaded["delivery_last_error"] == "bridge returned HTTP 401"


def test_derive_workflow_notification_status_deadletter_wins():
    status = derive_workflow_notification_status([
        {"kind": "workflow_started", "status": "sent"},
        {"kind": "workflow_full_report", "status": "deadletter", "last_error": "401"},
    ])

    assert status["workflow_notification_status"] == "deadletter"
    assert status["delivery_last_error"] == "401"


def test_validate_contract_allows_full_sent_local_deadletter_downgrade():
    warnings = validate_report_user_contract({
        "delivery": {
            "workflow_notification_delivered": False,
            "deadletter_count": 2,
            "internal_status": "full_sent_local",
        },
        "executive_slots": [],
        "executive_bullets": [],
        "action_priorities": [],
        "issue_diagnostics": [],
    })

    assert not any("delivery conflict" in item for item in warnings)


def test_sync_workflow_report_status_derives_deadletter_from_db():
    from qbu_crawler.server.report_status import sync_workflow_report_status

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            status TEXT,
            report_phase TEXT,
            logical_date TEXT,
            excel_path TEXT,
            analytics_path TEXT,
            pdf_path TEXT,
            report_generation_status TEXT NOT NULL DEFAULT 'unknown',
            email_delivery_status TEXT NOT NULL DEFAULT 'unknown',
            workflow_notification_status TEXT NOT NULL DEFAULT 'unknown',
            delivery_last_error TEXT,
            delivery_checked_at TEXT
        );
        CREATE TABLE report_artifacts (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            artifact_type TEXT,
            path TEXT
        );
        CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY,
            kind TEXT,
            status TEXT,
            payload TEXT,
            last_error TEXT
        );
        INSERT INTO workflow_runs VALUES (
            1, 'completed', 'full_sent_local', '2026-04-28',
            'report.xlsx', 'analytics.json', NULL,
            'generated', 'sent', 'pending', NULL, NULL
        );
    """)
    conn.execute(
        "INSERT INTO notification_outbox (kind, status, payload, last_error) "
        "VALUES ('workflow_full_report', 'deadletter', ?, 'bridge returned HTTP 401')",
        (json.dumps({"run_id": 1, "email_status": "success"}),),
    )

    status = sync_workflow_report_status(conn, 1)

    row = conn.execute("SELECT * FROM workflow_runs WHERE id=1").fetchone()
    assert status["workflow_notification_status"] == "deadletter"
    assert row["workflow_notification_status"] == "deadletter"
    assert "bridge returned HTTP 401" in row["delivery_last_error"]


def test_deadletter_downgrade_updates_db_status():
    from qbu_crawler.server.notifier import downgrade_report_phase_on_deadletter

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            status TEXT,
            report_phase TEXT,
            logical_date TEXT,
            analytics_path TEXT,
            excel_path TEXT,
            pdf_path TEXT,
            report_generation_status TEXT NOT NULL DEFAULT 'unknown',
            email_delivery_status TEXT NOT NULL DEFAULT 'unknown',
            workflow_notification_status TEXT NOT NULL DEFAULT 'unknown',
            delivery_last_error TEXT,
            delivery_checked_at TEXT
        );
        CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY,
            kind TEXT,
            status TEXT,
            payload TEXT,
            last_error TEXT
        );
        INSERT INTO workflow_runs VALUES (
            1, 'completed', 'full_sent', '2026-04-28',
            NULL, 'report.xlsx', NULL,
            'generated', 'sent', 'pending', NULL, NULL
        );
    """)
    conn.execute(
        "INSERT INTO notification_outbox (kind, status, payload, last_error) "
        "VALUES ('workflow_full_report', 'deadletter', ?, 'bridge returned HTTP 401')",
        (json.dumps({"run_id": 1, "email_status": "success"}),),
    )

    changed = downgrade_report_phase_on_deadletter(conn, 1)

    row = conn.execute("SELECT * FROM workflow_runs WHERE id=1").fetchone()
    assert changed is True
    assert row["report_phase"] == "full_sent_local"
    assert row["workflow_notification_status"] == "deadletter"
    assert "bridge returned HTTP 401" in row["delivery_last_error"]


def test_notifier_deadletter_syncs_workflow_status(tmp_path, monkeypatch):
    from qbu_crawler import config
    from qbu_crawler.server.notifier import NotificationDeliveryError, NotifierWorker

    class FailingSender:
        def send(self, notification):
            raise NotificationDeliveryError("bridge returned HTTP 401", retryable=False, http_status=401)

    db = tmp_path / "notifier.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()
    run = models.create_workflow_run({
        "workflow_type": "daily",
        "status": "completed",
        "report_phase": "full_sent",
        "logical_date": "2026-04-28",
        "trigger_key": "daily:2026-04-28",
        "excel_path": "report.xlsx",
    })
    models.update_workflow_report_status(
        run["id"],
        report_generation_status="generated",
        email_delivery_status="sent",
        workflow_notification_status="pending",
    )
    models.enqueue_notification({
        "kind": "workflow_full_report",
        "target": "ops",
        "payload": {"run_id": run["id"], "email_status": "success"},
        "dedupe_key": "workflow:1:full-report",
        "payload_hash": "abc",
    })

    NotifierWorker(FailingSender(), max_attempts=1).process_once(now="2026-04-28T10:00:00")

    loaded = models.get_workflow_run(run["id"])
    assert loaded["workflow_notification_status"] == "deadletter"
    assert "bridge returned HTTP 401" in loaded["delivery_last_error"]


def test_notifier_sent_syncs_workflow_status(tmp_path, monkeypatch):
    from qbu_crawler import config
    from qbu_crawler.server.notifier import NotifierWorker

    class OkSender:
        def send(self, notification):
            return {"bridge_request_id": "req-1", "http_status": 200}

    db = tmp_path / "notifier-sent.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()
    run = models.create_workflow_run({
        "workflow_type": "daily",
        "status": "completed",
        "report_phase": "full_sent",
        "logical_date": "2026-04-28",
        "trigger_key": "daily:2026-04-28",
        "excel_path": "report.xlsx",
    })
    models.update_workflow_report_status(
        run["id"],
        report_generation_status="generated",
        email_delivery_status="sent",
        workflow_notification_status="pending",
    )
    models.enqueue_notification({
        "kind": "workflow_full_report",
        "target": "ops",
        "payload": {"run_id": run["id"], "email_status": "success"},
        "dedupe_key": "workflow:1:full-report",
        "payload_hash": "abc",
    })

    NotifierWorker(OkSender(), max_attempts=1).process_once(now="2026-04-28T10:00:00")

    loaded = models.get_workflow_run(run["id"])
    assert loaded["workflow_notification_status"] == "sent"
