import json
import sqlite3

from qbu_crawler.server.report_manifest import (
    build_report_manifest,
    update_analytics_delivery_from_db,
)


def _setup_schema(conn):
    conn.executescript(
        """
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            status TEXT,
            report_phase TEXT,
            logical_date TEXT,
            analytics_path TEXT,
            excel_path TEXT,
            pdf_path TEXT
        );
        CREATE TABLE report_artifacts (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            artifact_type TEXT,
            path TEXT,
            hash TEXT,
            template_version TEXT,
            generator_version TEXT,
            bytes INTEGER,
            created_at TEXT
        );
        CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY,
            kind TEXT,
            status TEXT,
            payload TEXT,
            last_error TEXT,
            last_http_status INTEGER,
            attempts INTEGER,
            delivered_at TEXT,
            created_at TEXT
        );
        """
    )


def test_report_manifest_separates_artifacts_and_delivery():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_schema(conn)
    conn.execute(
        "INSERT INTO workflow_runs VALUES (1, 'completed', 'full_sent_local', "
        "'2026-04-28', 'analytics.json', 'report.xlsx', NULL)"
    )
    conn.execute(
        "INSERT INTO report_artifacts "
        "(run_id, artifact_type, path, hash, bytes) VALUES "
        "(1, 'xlsx', 'report.xlsx', 'abc', 123)"
    )
    conn.execute(
        "INSERT INTO notification_outbox "
        "(kind, status, payload, last_error, last_http_status, attempts) VALUES "
        "('workflow_full_report', 'deadletter', ?, 'bridge returned HTTP 401', 401, 1)",
        (json.dumps({"run_id": 1, "email_status": "success"}),),
    )
    conn.commit()

    manifest = build_report_manifest(conn, run_id=1)

    assert manifest["artifacts"]["xlsx"]["path"] == "report.xlsx"
    assert manifest["delivery"]["report_generated"] is True
    assert manifest["delivery"]["email_delivered"] is True
    assert manifest["delivery"]["workflow_notification_delivered"] is False
    assert manifest["delivery"]["deadletter_count"] == 1
    assert manifest["delivery"]["internal_status"] == "full_sent_local"
    assert "bridge returned HTTP 401" in manifest["delivery"]["last_errors"][0]


def test_update_analytics_delivery_from_db_rewrites_contract(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _setup_schema(conn)
    analytics_path = tmp_path / "analytics.json"
    analytics_path.write_text(
        json.dumps({
            "report_user_contract": {
                "schema_version": "report_user_contract.v1",
                "delivery": {"internal_status": "unknown"},
                "executive_slots": [],
                "executive_bullets": [],
            }
        }),
        encoding="utf-8",
    )
    conn.execute(
        "INSERT INTO workflow_runs VALUES (1, 'completed', 'full_sent_local', "
        "'2026-04-28', ?, 'report.xlsx', NULL)",
        (str(analytics_path),),
    )
    conn.execute(
        "INSERT INTO report_artifacts "
        "(run_id, artifact_type, path, hash, bytes) VALUES "
        "(1, 'html_attachment', 'report.html', 'def', 456)"
    )
    conn.execute(
        "INSERT INTO notification_outbox "
        "(kind, status, payload, last_error, last_http_status, attempts) VALUES "
        "('workflow_full_report', 'deadletter', ?, 'bridge returned HTTP 401', 401, 1)",
        (json.dumps({"run_id": 1, "email_status": "success"}),),
    )
    conn.commit()

    update_analytics_delivery_from_db(conn, run_id=1, analytics_path=str(analytics_path))

    data = json.loads(analytics_path.read_text(encoding="utf-8"))
    delivery = data["report_user_contract"]["delivery"]
    assert delivery["report_generated"] is True
    assert delivery["email_delivered"] is True
    assert delivery["workflow_notification_delivered"] is False
    assert delivery["deadletter_count"] == 1
    assert data["report_manifest"]["delivery"]["internal_status"] == "full_sent_local"
