"""P008 Phase 3 — weekly report."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "p008p3.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: Config + trigger key ────────────────────────────────


def test_weekly_scheduler_time_config():
    assert hasattr(config, "WEEKLY_SCHEDULER_TIME")
    assert ":" in config.WEEKLY_SCHEDULER_TIME


def test_build_weekly_trigger_key():
    from qbu_crawler.server.workflows import build_weekly_trigger_key
    key = build_weekly_trigger_key("2026-04-20")
    assert key == "weekly:2026-04-20"


# ── Task 2: get_previous_completed_run(report_tier=) ────────────


def test_get_previous_completed_run_filters_by_tier(db):
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '/tmp/daily.json')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-14',"
        " 'weekly:2026-04-14', 'weekly', '/tmp/weekly.json')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'weekly', 'reporting', 'none', '2026-04-21',"
        " 'weekly:2026-04-21', 'weekly')"
    )
    conn.commit()
    conn.close()

    prev = models.get_previous_completed_run(3)
    assert prev is not None
    assert prev["id"] == 2

    prev_weekly = models.get_previous_completed_run(3, report_tier="weekly")
    assert prev_weekly is not None
    assert prev_weekly["id"] == 2

    prev_daily = models.get_previous_completed_run(3, report_tier="daily")
    assert prev_daily is not None
    assert prev_daily["id"] == 1


# ── Task 3: compute_dispersion + credibility_weight ─────────────

from datetime import date


def test_compute_dispersion_systemic():
    from qbu_crawler.server.report_common import compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU2", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU3", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=10)
    assert dtype == "systemic"
    assert len(skus) == 3


def test_compute_dispersion_isolated():
    from qbu_crawler.server.report_common import compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=20)
    assert dtype == "isolated"
    assert len(skus) == 1


def test_compute_dispersion_uncertain():
    from qbu_crawler.server.report_common import compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU2", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU3", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=20)
    assert dtype == "uncertain"


def test_credibility_weight_long_review_with_images():
    from qbu_crawler.server.report_common import credibility_weight
    review = {"body": "x" * 600, "images": ["img1.jpg", "img2.jpg"],
              "date_published_parsed": "2026-04-10"}
    w = credibility_weight(review, today=date(2026, 4, 17))
    assert w > 1.0


def test_credibility_weight_short_old_review():
    from qbu_crawler.server.report_common import credibility_weight
    review = {"body": "bad", "images": [],
              "date_published_parsed": "2025-04-10"}
    w = credibility_weight(review, today=date(2026, 4, 17))
    assert w < 1.0


def test_credibility_weight_no_date_defaults_to_recent():
    from qbu_crawler.server.report_common import credibility_weight
    review = {"body": "decent review text here", "images": []}
    w = credibility_weight(review, today=date(2026, 4, 17))
    assert w > 0


# ── Task 4: get_label_anomaly_stats ─────────────────────────────


def test_get_label_anomaly_stats(db):
    conn = _get_test_conn(db)
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://test.com/p1", "Test", "SKU1", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'A', 'H', 'B', 3.0)")
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'B', 'H2', 'B2', 2.0)")
    conn.execute(
        "INSERT INTO review_analysis (review_id, sentiment, sentiment_score, labels, features,"
        " insight_cn, insight_en, llm_model, prompt_version, label_anomaly_flags)"
        " VALUES (1, 'positive', 0.8, '[]', '[]', '', '', 'test', 'v1',"
        " '[{\"type\": \"sentiment_label_mismatch\", \"label_code\": \"quality_stability\"}]')"
    )
    conn.execute(
        "INSERT INTO review_analysis (review_id, sentiment, sentiment_score, labels, features,"
        " insight_cn, insight_en, llm_model, prompt_version, label_anomaly_flags)"
        " VALUES (2, 'negative', 0.2, '[]', '[]', '', '', 'test', 'v1', NULL)"
    )
    conn.commit()
    conn.close()

    stats = models.get_label_anomaly_stats([1, 2])
    assert stats["total_flagged"] == 1
    assert stats["total_checked"] == 2
    assert "quality_stability" in stats["flagged_labels"]


def test_get_label_anomaly_stats_empty(db):
    stats = models.get_label_anomaly_stats([])
    assert stats["total_flagged"] == 0
    assert stats["total_checked"] == 0


# ── Task 5: submit_weekly_run ───────────────────────────────────


def test_all_daily_runs_terminal_true_when_all_completed(db):
    from qbu_crawler.server.workflows import _all_daily_runs_terminal
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-15',"
        " 'daily:2026-04-15', 'daily', '2026-04-15T00:00:00+08:00', '2026-04-16T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()
    assert _all_daily_runs_terminal("2026-04-13T00:00:00+08:00", "2026-04-20T00:00:00+08:00") is True


def test_all_daily_runs_terminal_false_when_running(db):
    from qbu_crawler.server.workflows import _all_daily_runs_terminal
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'running', 'none', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()
    assert _all_daily_runs_terminal("2026-04-13T00:00:00+08:00", "2026-04-20T00:00:00+08:00") is False


def test_submit_weekly_run_creates_reporting_run(db):
    from qbu_crawler.server.workflows import submit_weekly_run
    result = submit_weekly_run(logical_date="2026-04-20")
    assert result["created"] is True
    assert result["trigger_key"] == "weekly:2026-04-20"

    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["workflow_type"] == "weekly"
    assert row["report_tier"] == "weekly"
    assert row["status"] == "reporting"
    assert row["data_since"] == "2026-04-13T00:00:00+08:00"
    assert row["data_until"] == "2026-04-20T00:00:00+08:00"


def test_submit_weekly_run_idempotent(db):
    from qbu_crawler.server.workflows import submit_weekly_run
    r1 = submit_weekly_run(logical_date="2026-04-20")
    r2 = submit_weekly_run(logical_date="2026-04-20")
    assert r1["created"] is True
    assert r2["created"] is False


# ── Task 8: Freeze tier awareness + cold start ──────────────────


def test_inject_meta_uses_run_tier():
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-20"}
    enriched = _inject_meta(snapshot, tier="weekly")
    assert enriched["_meta"]["report_tier"] == "weekly"


def test_inject_meta_cold_start():
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-20"}
    enriched = _inject_meta(snapshot, tier="weekly", expected_days=7, actual_days=4)
    assert enriched["_meta"]["is_partial"] is True
    assert enriched["_meta"]["expected_days"] == 7
    assert enriched["_meta"]["actual_days"] == 4


def test_inject_meta_no_partial_when_complete():
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-20"}
    enriched = _inject_meta(snapshot, tier="weekly", expected_days=7, actual_days=7)
    assert "is_partial" not in enriched["_meta"]


# ── Task 9: Retire weekly_digest ─────────────────────────────────


def test_quiet_email_no_weekly_digest(db):
    """should_send_quiet_email should never return 'weekly_digest' — real weekly report replaces it."""
    from qbu_crawler.server.report_snapshot import should_send_quiet_email
    conn = _get_test_conn(db)
    for i in range(8):
        conn.execute(
            "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
            " trigger_key, report_mode)"
            f" VALUES ('daily', 'completed', 'full_sent', '2026-04-{10+i:02d}',"
            f" 'daily:2026-04-{10+i:02d}', 'quiet')"
        )
    conn.commit()
    conn.close()

    should, digest_mode, consecutive = should_send_quiet_email(9)
    assert digest_mode is None or digest_mode != "weekly_digest", \
        "weekly_digest should be retired — real weekly report replaces it"


# ── Task 6: WeeklySchedulerWorker ───────────────────────────────


def test_weekly_scheduler_skips_non_monday(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    now = datetime(2026, 4, 17, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = WeeklySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False


def test_weekly_scheduler_triggers_on_monday(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    now = datetime(2026, 4, 20, 10, 0, tzinfo=config.SHANGHAI_TZ)
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()
    worker = WeeklySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is True


def test_weekly_scheduler_idempotent(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    now = datetime(2026, 4, 20, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = WeeklySchedulerWorker(schedule_time="09:30")
    worker.process_once(now=now)
    assert worker.process_once(now=now) is False


def test_weekly_scheduler_waits_for_daily_runs(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    now = datetime(2026, 4, 20, 10, 0, tzinfo=config.SHANGHAI_TZ)
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'running', 'none', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()
    worker = WeeklySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False

# ── Task 12: email_weekly.html.j2 ───────────────────────────────


def test_email_weekly_template_renders():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_weekly.html.j2")
    html = template.render(
        logical_date="2026-04-20",
        kpis={"health_index": 75.0, "own_negative_review_rate_display": "3.5%", "high_risk_count": 1},
        report_url="https://reports.example.com/weekly-2026-04-20.html",
        reviews_count=15,
        threshold=2,
    )
    assert "75.0" in html
    assert "周报" in html
    assert "查看完整周报" in html


# ── Task 11: V3 template enhancements ───────────────────────────


def test_v3_template_renders_dispersion_type():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("daily_report_v3.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"

    html = template.render(
        logical_date="2026-04-20",
        mode="incremental",
        snapshot={"reviews": [], "cumulative": {"reviews": []}},
        analytics={
            "kpis": {"own_review_rows": 10, "ingested_review_rows": 10,
                     "product_count": 2, "own_product_count": 2, "competitor_product_count": 0,
                     "competitor_review_rows": 0, "own_negative_review_rows": 1,
                     "own_positive_review_rows": 8},
            "self": {"risk_products": [], "top_negative_clusters": [],
                     "recommendations": [], "top_positive_clusters": [],
                     "issue_cards": [
                         {"label_display": "质量稳定性", "review_count": 5,
                          "severity": "high", "severity_display": "高",
                          "affected_product_count": 3, "dispersion_type": "systemic",
                          "dispersion_display": "系统性", "lifecycle_status": "active",
                          "example_reviews": [], "image_evidence": [],
                          "recommendation": "", "translated_rate_display": "100%",
                          "translation_warning": False, "evidence_refs_display": "",
                          "first_seen": None, "last_seen": None, "duration_display": None,
                          "image_review_count": 0, "recency_display": ""}
                     ]},
            "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                           "negative_opportunities": []},
            "appendix": {"image_reviews": []},
            "issue_cards": [],
        },
        charts={"heatmap": None, "sentiment_own": None, "sentiment_comp": None},
        alert_level="green", alert_text="",
        report_copy={},
        css_text=css_path.read_text(encoding="utf-8") if css_path.exists() else "",
        js_text=js_path.read_text(encoding="utf-8") if js_path.exists() else "",
        threshold=2, cumulative_kpis={}, window={}, changes=None,
    )
    assert "系统性" in html
    assert "活跃" in html


# ── Task 7: _advance_periodic_run ───────────────────────────────


def test_advance_run_routes_weekly_to_periodic(db, tmp_path, monkeypatch):
    """Weekly run should skip fast_pending and go directly to report generation."""
    from qbu_crawler.server.workflows import WorkflowWorker
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES (1, 'weekly', 'reporting', 'none', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly',"
        " '2026-04-13T00:00:00+08:00', '2026-04-20T00:00:00+08:00')"
    )
    conn.execute("INSERT INTO products (url, name, sku, site, ownership, scraped_at)"
                 " VALUES ('http://t.com/p1', 'Grinder', 'SKU1', 'test', 'own', '2026-04-14 10:00:00')")
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating, scraped_at)"
                 " VALUES (1, 'A', 'Good', 'Works', 4.0, '2026-04-14 10:00:00')")
    conn.commit()
    conn.close()

    generated = {}
    def mock_generate(snapshot, send_email=True, **kw):
        generated["called"] = True
        generated["snapshot"] = snapshot
        return {
            "mode": "weekly_report", "status": "completed", "run_id": 1,
            "html_path": None, "excel_path": None, "analytics_path": None,
            "email": None, "snapshot_hash": "",
        }
    monkeypatch.setattr(report_snapshot, "generate_report_from_snapshot", mock_generate)

    worker = WorkflowWorker()
    now = "2026-04-20T10:00:00+08:00"
    worker._advance_run(1, now)

    assert generated.get("called") is True

    conn = _get_test_conn(db)
    row = conn.execute("SELECT status, report_phase FROM workflow_runs WHERE id = 1").fetchone()
    conn.close()
    assert row["status"] == "completed"


# ── Task 10: _generate_weekly_report + routing ──────────────────


def test_generate_report_weekly_tier_routes_correctly(db, tmp_path, monkeypatch):
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid, **kw: (None, None))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (1, 'weekly', 'reporting', 'full_pending', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly')"
    )
    conn.commit()
    conn.close()

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-20",
        "data_since": "2026-04-13T00:00:00+08:00",
        "data_until": "2026-04-20T00:00:00+08:00",
        "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                       "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
        "reviews": [
            {"id": 1, "headline": "Good", "body": "Works well", "rating": 4.0,
             "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
             "images": [], "author": "A", "date_published": "2026-04-14"}
        ],
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 0,
        "untranslated_count": 1,
        "snapshot_hash": "testhash",
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [
                {"id": 1, "rating": 4.0, "ownership": "own", "product_sku": "SKU1",
                 "headline": "Good", "body": "Works well", "sentiment": "positive",
                 "analysis_labels": "[]"}
            ],
            "products_count": 1,
            "reviews_count": 1,
            "translated_count": 0,
            "untranslated_count": 1,
        },
    }

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)
    assert result["mode"] == "weekly_report"
    assert result.get("html_path") is not None


# ── Task 13: Integration test ────────────────────────────────────


def test_p008_phase3_integration(db, tmp_path, monkeypatch):
    """End-to-end: weekly run goes through submit → route → report."""
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.workflows import submit_weekly_run
    from qbu_crawler.server.report_common import compute_dispersion, credibility_weight, tier_date_window

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    # 1. Verify tier_date_window
    since, until = tier_date_window("weekly", "2026-04-20")
    assert since == "2026-04-13T00:00:00+08:00"
    assert until == "2026-04-20T00:00:00+08:00"

    # 2. Submit weekly run
    result = submit_weekly_run(logical_date="2026-04-20")
    assert result["created"] is True
    run_id = result["run_id"]

    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    assert row["report_tier"] == "weekly"
    assert row["status"] == "reporting"

    # 3. Verify get_previous_completed_run with tier
    prev = models.get_previous_completed_run(run_id, report_tier="weekly")
    assert prev is None

    # 4. Verify compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU2", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=5)
    assert dtype in ("systemic", "uncertain", "isolated")

    # 5. Verify credibility_weight (long body + image + recent date → weight > 1.0)
    w = credibility_weight(
        {"body": "x" * 600, "images": ["img.jpg"], "date_published_parsed": "2026-04-14"},
        today=date(2026, 4, 20),
    )
    assert w > 1.0

    # 6. Verify weekly routing
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid, **kw: (None, None))
    snapshot = {
        "run_id": run_id,
        "logical_date": "2026-04-20",
        "data_since": "2026-04-13T00:00:00+08:00",
        "data_until": "2026-04-20T00:00:00+08:00",
        "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                       "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
        "reviews": [{"id": 1, "headline": "Good", "body": "Works", "rating": 4.0,
                      "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
                      "images": [], "author": "A", "date_published": "2026-04-14",
                      "date_published_parsed": "2026-04-14"}],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [{"id": 1, "rating": 4.0, "ownership": "own", "product_sku": "SKU1",
                         "headline": "Good", "body": "Works", "sentiment": "positive",
                         "analysis_labels": "[]"}],
            "products_count": 1,
            "reviews_count": 1,
            "translated_count": 1,
            "untranslated_count": 0,
        },
        "products_count": 1, "reviews_count": 1,
        "translated_count": 1, "untranslated_count": 0, "snapshot_hash": "test",
    }
    report_result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)
    assert report_result["mode"] == "weekly_report"
    assert report_result.get("html_path") is not None


# ── Task 3 (P4-B3): neg_series unit fix ─────────────────────────


def test_weekly_recap_neg_series_is_percentage(db, tmp_path, monkeypatch):
    """neg_series 必须为百分比值（0-100），与 Y 轴标签 '差评率 (%)' 对齐。

    own_negative_review_rate 存储为分数（0.0-1.0），_build_weekly_recap 在
    填充 neg_series 时必须乘以 100，否则图表数值是真实值的 1/100。
    """
    from qbu_crawler.server.report_snapshot import _build_weekly_recap

    # Write fake analytics JSON files that _build_weekly_recap reads
    analytics1 = {
        "kpis": {
            "health_index": 70.0,
            "own_negative_review_rate": 0.04,          # 4 % stored as fraction
            "own_negative_review_rate_display": "4.0%",
            "high_risk_count": 2,
        }
    }
    analytics2 = {
        "kpis": {
            "health_index": 68.0,
            "own_negative_review_rate": 0.06,          # 6 % stored as fraction
            "own_negative_review_rate_display": "6.0%",
            "high_risk_count": 3,
        }
    }
    path1 = tmp_path / "weekly_analytics_w1.json"
    path2 = tmp_path / "weekly_analytics_w2.json"
    path1.write_text(json.dumps(analytics1), encoding="utf-8")
    path2.write_text(json.dumps(analytics2), encoding="utf-8")

    # Insert completed weekly workflow_runs whose analytics_path points to the temp files
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until, analytics_path)"
        " VALUES ('weekly', 'completed', 'full_sent', '2026-04-07',"
        " 'weekly:2026-04-07', 'weekly',"
        " '2026-03-31T00:00:00+08:00', '2026-04-07T00:00:00+08:00', ?)",
        (str(path1),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until, analytics_path)"
        " VALUES ('weekly', 'completed', 'full_sent', '2026-04-14',"
        " 'weekly:2026-04-14', 'weekly',"
        " '2026-04-07T00:00:00+08:00', '2026-04-14T00:00:00+08:00', ?)",
        (str(path2),),
    )
    conn.commit()
    conn.close()

    # Call _build_weekly_recap with a window that overlaps both runs
    summaries, trend_config = _build_weekly_recap(
        "2026-03-31T00:00:00+08:00",
        "2026-04-30T00:00:00+08:00",
    )

    assert trend_config is not None, "trend_config should not be None with valid data"
    neg_dataset = next(
        d for d in trend_config["data"]["datasets"] if "差评率" in d.get("label", "")
    )
    data = neg_dataset["data"]

    # Values must be in percentage space: 4.0 and 6.0, not 0.04 and 0.06
    assert any(v is not None and 3.5 <= v <= 4.5 for v in data), (
        f"neg_series[0] should be ~4.0 (percentage), got {data}"
    )
    assert any(v is not None and 5.5 <= v <= 6.5 for v in data), (
        f"neg_series[1] should be ~6.0 (percentage), got {data}"
    )


# ── Task 4 (P008): load_previous_report_context tier isolation ───────────────


def test_weekly_report_does_not_use_daily_run_as_baseline(db, tmp_path, monkeypatch):
    """
    场景：DB 中存在近期已完成的 daily run（id=1, 分析文件存在）和上周已完成的 weekly run
    （id=2, 分析文件存在）。当生成本周 weekly 报告时，baseline 必须取 id=2（上周报），不能取 id=1（日报）。
    """
    import json
    from qbu_crawler.server.report_snapshot import load_previous_report_context

    daily_analytics = tmp_path / "daily.json"
    daily_analytics.write_text(json.dumps({"kpis": {"health_index": 70}}))
    weekly_analytics = tmp_path / "weekly.json"
    weekly_analytics.write_text(json.dumps({"kpis": {"health_index": 80}}))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-19',"
        " 'daily:2026-04-19', 'daily', ?)",
        (str(daily_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-13',"
        " 'weekly:2026-04-13', 'weekly', ?)",
        (str(weekly_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'weekly', 'reporting', 'none', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly')"
    )
    conn.commit()
    conn.close()

    prev_weekly, _ = load_previous_report_context(3, report_tier="weekly")
    assert prev_weekly is not None
    assert prev_weekly["kpis"]["health_index"] == 80


def test_daily_briefing_does_not_use_weekly_run_as_baseline(db, tmp_path, monkeypatch):
    """Reverse: daily run 只能看 daily 基线。"""
    import json
    from qbu_crawler.server.report_snapshot import load_previous_report_context

    daily_analytics = tmp_path / "daily.json"
    daily_analytics.write_text(json.dumps({"kpis": {"health_index": 70}}))
    weekly_analytics = tmp_path / "weekly.json"
    weekly_analytics.write_text(json.dumps({"kpis": {"health_index": 80}}))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-18',"
        " 'daily:2026-04-18', 'daily', ?)",
        (str(daily_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly', ?)",
        (str(weekly_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'daily', 'reporting', 'none', '2026-04-21',"
        " 'daily:2026-04-21', 'daily')"
    )
    conn.commit()
    conn.close()

    prev_daily, _ = load_previous_report_context(3, report_tier="daily")
    assert prev_daily is not None
    assert prev_daily["kpis"]["health_index"] == 70  # daily 基线，不是 80


# ── Task 8 (integration): freeze_report_snapshot propagates is_partial ──


def test_freeze_snapshot_sets_is_partial_on_short_weekly(db, tmp_path, monkeypatch):
    """Weekly run 数据不足 7 天时，_meta.is_partial 应为 True 并含 expected/actual days。"""
    import json as _json
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    # 4 天窗口的周报（冷启动）: data_since=2026-04-09, data_until=2026-04-13 → 4 days
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES (1, 'weekly', 'reporting', 'none', '2026-04-13',"
        " 'weekly:2026-04-13', 'weekly', '2026-04-09T00:00:00+08:00', '2026-04-13T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()

    # Isolate from DB/LLM calls
    monkeypatch.setattr(report_snapshot.report, "query_report_data",
                        lambda since, until=None: ([], []))
    monkeypatch.setattr(report_snapshot.report, "query_cumulative_data",
                        lambda: ([], []))

    report_snapshot.freeze_report_snapshot(1)

    # Read the saved snapshot from disk
    snap_path = tmp_path / "workflow-run-1-snapshot-2026-04-13.json"
    snapshot = _json.loads(snap_path.read_text(encoding="utf-8"))

    assert snapshot["_meta"]["report_tier"] == "weekly"
    assert snapshot["_meta"].get("is_partial") is True
    assert snapshot["_meta"]["expected_days"] == 7
    assert snapshot["_meta"]["actual_days"] == 4


def test_freeze_snapshot_full_week_has_no_is_partial(db, tmp_path, monkeypatch):
    """满 7 天的 weekly run 不应带 is_partial。"""
    import json as _json
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    # 7 天窗口：data_since=2026-04-13, data_until=2026-04-20 → 7 days
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES (2, 'weekly', 'reporting', 'none', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly', '2026-04-13T00:00:00+08:00', '2026-04-20T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(report_snapshot.report, "query_report_data",
                        lambda since, until=None: ([], []))
    monkeypatch.setattr(report_snapshot.report, "query_cumulative_data",
                        lambda: ([], []))

    report_snapshot.freeze_report_snapshot(2)

    snap_path = tmp_path / "workflow-run-2-snapshot-2026-04-20.json"
    snapshot = _json.loads(snap_path.read_text(encoding="utf-8"))

    assert snapshot["_meta"]["report_tier"] == "weekly"
    assert snapshot["_meta"].get("is_partial") is not True
