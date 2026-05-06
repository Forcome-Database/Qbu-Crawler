import sqlite3
from datetime import date
from pathlib import Path


def test_build_logical_dates_goes_oldest_to_today():
    from scripts.simulate_daily_report import build_logical_dates

    assert build_logical_dates(3, today=date(2026, 4, 29)) == [
        date(2026, 4, 27),
        date(2026, 4, 28),
        date(2026, 4, 29),
    ]


def test_run_simulation_writes_isolated_daily_rows(tmp_path, monkeypatch):
    from qbu_crawler import config
    from scripts import simulate_daily_report

    reports = []
    monkeypatch.setattr(config, "AI_DIGEST_MODE", "async")
    monkeypatch.setattr(config, "OPENCLAW_HOOK_URL", "http://127.0.0.1:9")

    def fake_advance(run_id, logical_date, send_email):
        assert config.AI_DIGEST_MODE == "off"
        assert config.OPENCLAW_HOOK_URL == ""
        reports.append((run_id, logical_date.isoformat(), send_email))
        return {
            "run_id": run_id,
            "logical_date": logical_date.isoformat(),
            "status": "completed",
            "report_phase": "full_sent",
            "html_path": f"workflow-run-{run_id}-full-report.html",
            "excel_path": f"workflow-run-{run_id}-full-report.xlsx",
            "analytics_path": f"workflow-run-{run_id}-analytics-{logical_date.isoformat()}.json",
        }

    monkeypatch.setattr(simulate_daily_report, "_advance_workflow", fake_advance)

    result = simulate_daily_report.run_simulation(
        days=2,
        output_dir=tmp_path / "sim",
        today=date(2026, 4, 29),
        seed=7,
        use_llm=False,
        send_email=False,
    )

    assert Path(result["db_path"]).is_file()
    assert Path(result["report_dir"]).is_dir()
    assert [item["logical_date"] for item in result["runs"]] == ["2026-04-28", "2026-04-29"]
    assert reports == [(1, "2026-04-28", False), (2, "2026-04-29", False)]

    conn = sqlite3.connect(result["db_path"])
    conn.row_factory = sqlite3.Row
    try:
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        snapshot_count = conn.execute("SELECT COUNT(*) FROM product_snapshots").fetchone()[0]
        review_count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        task_rows = conn.execute("SELECT result FROM tasks ORDER BY id").fetchall()
        run_rows = conn.execute("SELECT status, requested_by FROM workflow_runs ORDER BY id").fetchall()
    finally:
        conn.close()

    assert product_count >= 6
    assert snapshot_count >= product_count * 2
    assert review_count > 0
    assert [row["status"] for row in run_rows] == ["completed", "completed"]
    assert {row["requested_by"] for row in run_rows} == {"simulation"}
    assert all("expected_urls" in row["result"] for row in task_rows)
    assert config.DB_PATH != result["db_path"]
    assert config.AI_DIGEST_MODE == "async"
    assert config.OPENCLAW_HOOK_URL == "http://127.0.0.1:9"


def test_advance_workflow_suppresses_ops_alert_sender(tmp_path, monkeypatch):
    from qbu_crawler import models
    from qbu_crawler.server import workflows
    from scripts import simulate_daily_report

    called = {"alert": 0}

    def fake_alert(*args, **kwargs):
        called["alert"] += 1

    class FakeWorker:
        def __init__(self, interval=1, task_stale_seconds=3600):
            pass

        def process_once(self, now=None):
            workflows._send_data_quality_alert(
                run_id=1,
                logical_date="2026-04-29",
                quality={},
                severity="P1",
                log_path=None,
            )
            return False

    monkeypatch.setattr(workflows, "_send_data_quality_alert", fake_alert)
    monkeypatch.setattr(workflows, "WorkflowWorker", FakeWorker)

    with simulate_daily_report._isolated_runtime(
        tmp_path / "sim.db",
        tmp_path / "reports",
        use_llm=False,
        send_email=False,
    ):
        models.init_db()
        run = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "submitted",
                "logical_date": "2026-04-29",
                "trigger_key": "simulation:test",
                "data_since": "2026-04-29T00:00:00+08:00",
                "data_until": "2026-04-30T00:00:00+08:00",
                "requested_by": "simulation",
            }
        )

        simulate_daily_report._advance_workflow(run["id"], date(2026, 4, 29), send_email=False)

    assert called["alert"] == 0
    assert workflows._send_data_quality_alert is fake_alert
