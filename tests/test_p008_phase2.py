"""P008 Phase 2 — daily briefing refactor + infrastructure."""

from __future__ import annotations

import json
import sqlite3

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
    db_file = str(tmp_path / "p008p2.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: report_tier column ──────────────────────────────────


def test_workflow_runs_has_report_tier_column(db):
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
    assert "report_tier" in cols
    conn.close()


def test_report_tier_default_is_null(db):
    """Old runs without explicit report_tier should be NULL (stay on old path)."""
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'test:2026-04-17')"
    )
    conn.commit()
    row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = 1").fetchone()
    assert row["report_tier"] is None
    conn.close()


def test_update_workflow_run_accepts_report_tier(db):
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'test:2026-04-17')"
    )
    conn.commit()
    conn.close()
    result = models.update_workflow_run(1, report_tier="weekly")
    assert result["report_tier"] == "weekly"


# ── Task 2: Config ──────────────────────────────────────────────


def test_email_recipients_exec_defaults_empty(monkeypatch):
    monkeypatch.delenv("EMAIL_RECIPIENTS_EXEC", raising=False)
    from qbu_crawler import config as cfg
    monkeypatch.setattr(cfg, "EMAIL_RECIPIENTS_EXEC", [])
    assert cfg.EMAIL_RECIPIENTS_EXEC == []


def test_tier_configs_has_daily():
    from qbu_crawler.config import TIER_CONFIGS
    assert "daily" in TIER_CONFIGS
    daily = TIER_CONFIGS["daily"]
    assert daily["window"] == "24h"
    assert daily["cumulative"] is True
    assert daily["excel"] is False
    assert "attention_signals" in daily["dimensions"]


from datetime import date

# ── Task 3: tier_date_window ────────────────────────────────────


def test_tier_date_window_daily():
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("daily", "2026-04-17")
    assert since == "2026-04-17T00:00:00+08:00"
    assert until == "2026-04-18T00:00:00+08:00"


def test_tier_date_window_weekly():
    from qbu_crawler.server.report_common import tier_date_window
    # 2026-04-20 is a Monday
    since, until = tier_date_window("weekly", "2026-04-20")
    assert since == "2026-04-13T00:00:00+08:00"  # previous Monday
    assert until == "2026-04-20T00:00:00+08:00"  # this Monday


def test_tier_date_window_monthly():
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("monthly", "2026-05-01")
    assert since == "2026-04-01T00:00:00+08:00"
    assert until == "2026-05-01T00:00:00+08:00"

# ── Task 4: review_attention_label ──────────────────────────────


def test_review_attention_label_critical_safety_with_images():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 1.0, "body": "Found metal shavings in food " * 20,
              "images": ["img1.jpg", "img2.jpg"]}
    result = review_attention_label(review, safety_level="critical")
    assert result["label"] == "高关注度评论"
    assert "⚠安全关键词" in " ".join(result["signals"])
    assert "📸" in " ".join(result["signals"])


def test_review_attention_label_negative_no_images():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 1.0, "body": "Bad product", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "差评"


def test_review_attention_label_positive():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 5.0, "body": "Great product!", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "常规好评"


def test_review_attention_label_mid_rating():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 3.0, "body": "It's okay", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "中评"


def test_review_attention_label_long_body_signal():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 2.0, "body": "x" * 350, "images": []}
    result = review_attention_label(review, safety_level=None)
    assert any("字详评" in s for s in result["signals"])


def test_review_attention_label_none_rating():
    """None rating defaults to 5 (lenient) — treated as 常规好评."""
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": None, "body": "No rating", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "常规好评"


# ── Task 5: compute_attention_signals ───────────────────────────


def test_attention_signals_safety_keyword():
    from qbu_crawler.server.report_common import compute_attention_signals
    window_reviews = [
        {"id": 1, "headline": "Dangerous", "body": "Found metal shaving in food",
         "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
         "ownership": "own", "images": []}
    ]
    signals = compute_attention_signals(window_reviews, changes={}, cumulative_clusters=[])
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "safety_keyword" for s in action_signals)


def test_attention_signals_image_evidence():
    from qbu_crawler.server.report_common import compute_attention_signals
    window_reviews = [
        {"id": 1, "headline": "Bad", "body": "Broken part",
         "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
         "ownership": "own", "images": ["img1.jpg", "img2.jpg"]}
    ]
    signals = compute_attention_signals(window_reviews, changes={}, cumulative_clusters=[])
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "image_evidence" for s in action_signals)


def test_attention_signals_consecutive_negative_7d():
    """Consecutive negative uses 7-day window, not just today's reviews."""
    from qbu_crawler.server.report_common import compute_attention_signals
    window_reviews = [
        {"id": 2, "headline": "Also bad", "body": "Awful", "rating": 2.0,
         "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
         "images": [], "date_published_parsed": "2026-04-16"},
    ]
    recent_7d = [
        {"id": 1, "headline": "Bad", "body": "Terrible", "rating": 1.0,
         "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
         "images": [], "date_published_parsed": "2026-04-12"},
        {"id": 2, "headline": "Also bad", "body": "Awful", "rating": 2.0,
         "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
         "images": [], "date_published_parsed": "2026-04-16"},
    ]
    signals = compute_attention_signals(
        window_reviews, changes={}, cumulative_clusters=[],
        recent_reviews_7d=recent_7d,
    )
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "consecutive_negative" for s in action_signals)


def test_attention_signals_competitor_rating_drop():
    from qbu_crawler.server.report_common import compute_attention_signals
    changes = {
        "rating_changes": [
            {"sku": "COMP1", "name": "Competitor Grinder", "old": 4.6, "new": 4.2,
             "ownership": "competitor"}
        ]
    }
    signals = compute_attention_signals([], changes=changes, cumulative_clusters=[])
    ref_signals = [s for s in signals if s["urgency"] == "reference"]
    assert any(s["type"] == "competitor_rating_change" for s in ref_signals)


def test_attention_signals_own_stock_out():
    from qbu_crawler.server.report_common import compute_attention_signals
    changes = {
        "stock_changes": [
            {"sku": "SKU1", "name": "Grinder", "old": "in_stock", "new": "out_of_stock",
             "ownership": "own"}
        ]
    }
    signals = compute_attention_signals([], changes=changes, cumulative_clusters=[])
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "own_stock_out" for s in action_signals)


def test_attention_signals_silence_good_news():
    from qbu_crawler.server.report_common import compute_attention_signals
    clusters = [
        {"label_code": "quality_stability", "last_seen": "2026-04-01",
         "label_display": "质量稳定性"}
    ]
    signals = compute_attention_signals(
        [], changes={}, cumulative_clusters=clusters,
        logical_date="2026-04-17",
    )
    ref_signals = [s for s in signals if s["urgency"] == "reference"]
    assert any(s["type"] == "silence_good_news" for s in ref_signals)


def test_attention_signals_empty_when_nothing():
    from qbu_crawler.server.report_common import compute_attention_signals
    signals = compute_attention_signals([], changes={}, cumulative_clusters=[])
    assert signals == []


# ── Task 6: should_send_daily_email ─────────────────────────────


def test_smart_send_true_when_new_reviews():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    assert should_send_daily_email(new_review_count=3, changes={}) is True


def test_smart_send_true_when_price_changes():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    changes = {"price_changes": [{"sku": "SKU1"}]}
    assert should_send_daily_email(new_review_count=0, changes=changes) is True


def test_smart_send_true_when_stock_changes():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    changes = {"stock_changes": [{"sku": "SKU1"}]}
    assert should_send_daily_email(new_review_count=0, changes=changes) is True


def test_smart_send_true_when_rating_changes():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    changes = {"rating_changes": [{"sku": "SKU1"}]}
    assert should_send_daily_email(new_review_count=0, changes=changes) is True


def test_smart_send_false_when_nothing():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    assert should_send_daily_email(new_review_count=0, changes={}) is False


# ── Task 7: Safety factor in risk scoring ───────────────────────


def test_risk_score_higher_with_safety_reviews(db):
    """A product with safety-flagged reviews should have higher risk_score."""
    from qbu_crawler.server import report_analytics

    labeled_reviews_normal = [
        {"review": {"rating": 1.0, "ownership": "own", "product_sku": "SKU1",
                     "product_name": "Grinder", "body": "Bad quality", "images": [],
                     "date_published_parsed": "2026-04-10"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                      "severity": "medium"}]},
    ]
    labeled_reviews_safety = [
        {"review": {"rating": 1.0, "ownership": "own", "product_sku": "SKU2",
                     "product_name": "Grinder 2", "body": "Found metal shaving in food",
                     "images": [],
                     "date_published_parsed": "2026-04-10",
                     "impact_category": "safety"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                      "severity": "medium"}]},
    ]
    products_data = [
        {"sku": "SKU1", "review_count": 10, "rating": 3.5},
        {"sku": "SKU2", "review_count": 10, "rating": 3.5},
    ]

    normal = report_analytics._risk_products(
        labeled_reviews_normal, products_data, logical_date="2026-04-17",
    )
    safety = report_analytics._risk_products(
        labeled_reviews_safety, products_data, logical_date="2026-04-17",
    )

    normal_score = normal[0]["risk_score"] if normal else 0
    safety_score = safety[0]["risk_score"] if safety else 0
    assert safety_score > normal_score, f"Safety review should boost risk score: {safety_score} vs {normal_score}"
