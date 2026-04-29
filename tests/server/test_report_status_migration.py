import sqlite3

from qbu_crawler.server.migrations import migration_0012_report_status_columns as mig


def test_migration_0012_adds_report_status_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            status TEXT,
            report_phase TEXT,
            logical_date TEXT,
            excel_path TEXT,
            analytics_path TEXT,
            error TEXT
        )
    """)

    mig.up(conn)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
    assert "report_generation_status" in cols
    assert "email_delivery_status" in cols
    assert "workflow_notification_status" in cols
    assert "delivery_last_error" in cols
    assert "delivery_checked_at" in cols


def test_migration_0012_backfills_generated_and_deadletter():
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
            error TEXT
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
        INSERT INTO workflow_runs VALUES (1, 'completed', 'full_sent', '2026-04-28', 'report.xlsx', 'analytics.json', NULL);
        INSERT INTO report_artifacts (run_id, artifact_type, path) VALUES (1, 'xlsx', 'report.xlsx');
        INSERT INTO notification_outbox (kind, status, payload, last_error)
        VALUES ('workflow_full_report', 'deadletter', '{"run_id": 1, "email_status": "success"}', 'bridge returned HTTP 401');
    """)

    mig.up(conn)
    mig.backfill(conn)

    row = conn.execute("SELECT * FROM workflow_runs WHERE id=1").fetchone()
    assert row["report_generation_status"] == "generated"
    assert row["email_delivery_status"] == "sent"
    assert row["workflow_notification_status"] == "deadletter"
    assert row["report_phase"] == "full_sent_local"
    assert "bridge returned HTTP 401" in row["delivery_last_error"]
