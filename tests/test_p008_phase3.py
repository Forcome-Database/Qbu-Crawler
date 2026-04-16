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
