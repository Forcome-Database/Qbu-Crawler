import copy
import json
import sqlite3
from pathlib import Path

from qbu_crawler.server.report_contract import build_report_user_contract
from qbu_crawler.server.report_html import _render_v3_html_string
from qbu_crawler.server.report_manifest import update_analytics_delivery_from_db


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "report_replay"


def _load_fixture():
    snapshot = json.loads((FIXTURE_DIR / "test7_minimal_snapshot.json").read_text(encoding="utf-8"))
    analytics = json.loads((FIXTURE_DIR / "test7_minimal_analytics.json").read_text(encoding="utf-8"))
    return snapshot, analytics


def _with_contract(snapshot, analytics):
    enriched = copy.deepcopy(analytics)
    enriched["report_user_contract"] = build_report_user_contract(
        snapshot=snapshot,
        analytics=enriched,
    )
    return enriched


def test_test7_replay_business_html_hides_ops_diagnostics():
    snapshot, analytics = _load_fixture()
    analytics = _with_contract(snapshot, analytics)
    analytics["delivery"] = {"deadletter_count": 3, "workflow_notification_delivered": False}
    analytics["data_quality"] = {
        "low_coverage_products": ["SKU-X"],
        "estimated_date_ratio": 0.5,
    }

    html = _render_v3_html_string(snapshot, analytics)

    assert "deadletter" not in html
    assert "SKU-X" not in html
    assert "estimated_date_ratio" not in html


def test_test7_replay_manifest_includes_db_status(tmp_path):
    snapshot, analytics = _load_fixture()
    analytics = _with_contract(snapshot, analytics)
    analytics_path = tmp_path / "analytics.json"
    analytics_path.write_text(json.dumps(analytics, ensure_ascii=False), encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            logical_date TEXT,
            status TEXT,
            report_phase TEXT,
            analytics_path TEXT,
            excel_path TEXT,
            report_generation_status TEXT,
            email_delivery_status TEXT,
            workflow_notification_status TEXT,
            delivery_last_error TEXT,
            delivery_checked_at TEXT
        );
        CREATE TABLE report_artifacts (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            artifact_type TEXT,
            path TEXT,
            bytes INTEGER,
            hash TEXT,
            template_version TEXT
        );
        CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY,
            kind TEXT,
            status TEXT,
            payload TEXT,
            last_error TEXT
        );
    """)
    conn.execute(
        "INSERT INTO workflow_runs VALUES (1, '2026-04-28', 'completed', 'full_sent_local', ?, "
        "'report.xlsx', 'generated', 'sent', 'deadletter', 'bridge returned HTTP 401', NULL)",
        (str(analytics_path),),
    )
    conn.execute(
        "INSERT INTO notification_outbox (kind, status, payload, last_error) "
        "VALUES ('workflow_full_report', 'deadletter', ?, 'bridge returned HTTP 401')",
        (json.dumps({"run_id": 1, "email_status": "success"}),),
    )

    update_analytics_delivery_from_db(conn, run_id=1, analytics_path=str(analytics_path))

    data = json.loads(analytics_path.read_text(encoding="utf-8"))
    delivery = data["report_user_contract"]["delivery"]
    assert delivery["workflow_notification_delivered"] is False
    assert delivery["db_status"]["workflow_notification_status"] == "deadletter"
