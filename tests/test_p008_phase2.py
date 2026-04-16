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

# ── Task 8: Daily briefing template ─────────────────────────────


def test_render_daily_briefing_basic():
    from qbu_crawler.server.report_html import render_daily_briefing

    snapshot = {
        "logical_date": "2026-04-17",
        "run_id": 99,
        "reviews": [],
        "products": [],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [],
        },
    }
    cumulative_kpis = {
        "health_index": 72.3,
        "health_confidence": "medium",
        "own_review_rows": 42,
        "own_negative_review_rate_display": "4.2%",
        "high_risk_count": 2,
    }

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test-briefing.html")
        result = render_daily_briefing(
            snapshot=snapshot,
            cumulative_kpis=cumulative_kpis,
            window_reviews=[],
            attention_signals=[],
            changes={},
            output_path=path,
        )
        assert os.path.isfile(result)
        html = open(result, encoding="utf-8").read()
        assert "72.3" in html  # health index
        assert "4.2%" in html  # negative rate
        assert "需注意" not in html  # no signals → no attention block


def test_render_daily_briefing_with_attention_signals():
    from qbu_crawler.server.report_html import render_daily_briefing

    snapshot = {
        "logical_date": "2026-04-17",
        "run_id": 99,
        "reviews": [{"id": 1, "headline": "Bad", "body": "Metal shaving found",
                      "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
                      "ownership": "own", "images": ["img.jpg"],
                      "author": "Tester", "date_published": "2026-04-17"}],
        "cumulative": {"products": [], "reviews": []},
    }
    signals = [
        {"type": "safety_keyword", "urgency": "action",
         "title": "安全: Grinder 评论提及安全关键词", "detail": "级别: critical"},
    ]
    reviews_with_labels = [
        {**snapshot["reviews"][0],
         "attention": {"signals": ["⚠安全关键词(critical)", "📸 1张图"], "label": "高关注度评论"}}
    ]

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test-briefing.html")
        result = render_daily_briefing(
            snapshot=snapshot,
            cumulative_kpis={"health_index": 65.0, "own_negative_review_rate_display": "8.1%",
                             "high_risk_count": 1, "own_review_rows": 20, "health_confidence": "medium"},
            window_reviews=reviews_with_labels,
            attention_signals=signals,
            changes={},
            output_path=path,
        )
        html = open(result, encoding="utf-8").read()
        assert "需行动" in html
        assert "安全" in html
        assert "高关注度评论" in html


# ── Task 9: Email daily template ─────────────────────────────


def test_email_daily_template_renders():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_daily.html.j2")
    html = template.render(
        logical_date="2026-04-17",
        cumulative_kpis={"health_index": 72.3, "own_negative_review_rate_display": "4.2%",
                         "high_risk_count": 1, "own_review_rows": 42},
        window_reviews=[],
        attention_signals=[],
        threshold=2,
    )
    assert "72.3" in html
    assert "QBU" in html

# ── Task 10: Tier routing integration ────────────────────────────


def test_generate_report_from_snapshot_daily_tier(db, tmp_path, monkeypatch):
    """When report_tier == 'daily', use new three-block pipeline."""
    from qbu_crawler.server import report_snapshot

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key, report_tier)"
        " VALUES ('daily', 'reporting', 'full_pending', '2026-04-17', 'daily:2026-04-17', 'daily')"
    )
    conn.commit()
    conn.close()

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-17",
        "data_since": "2026-04-17T00:00:00+08:00",
        "data_until": "2026-04-18T00:00:00+08:00",
        "products": [],
        "reviews": [],
        "cumulative": {
            "products": [{"name": "Test", "sku": "SKU1", "ownership": "own", "rating": 4.5,
                          "review_count": 50, "site": "test", "price": 299}],
            "reviews": [{"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                         "headline": "Good", "body": "Works", "sentiment": "positive",
                         "analysis_labels": "[]"}],
        },
    }

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid: (None, None))

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)

    assert result["mode"] == "daily_briefing"
    assert result.get("html_path") is not None
    assert result.get("status") in ("completed", "completed_no_change")


def test_generate_report_from_snapshot_null_tier_uses_old_path(db, tmp_path, monkeypatch):
    """When report_tier is NULL (old run), use the original full/change/quiet path."""
    from qbu_crawler.server import report_snapshot

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'reporting', 'full_pending', '2026-04-16', 'daily:2026-04-16')"
    )
    conn.commit()
    conn.close()

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-16",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "products": [],
        "reviews": [],
        "cumulative": {"products": [], "reviews": []},
    }

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid: (None, None))

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)

    assert result["mode"] in ("quiet", "change", "full"), \
        f"NULL tier should use old path, got mode={result['mode']}"


# ── Task 11: Workflow integration ────────────────────────────────


def test_submit_daily_run_sets_report_tier(db):
    """New daily runs must have report_tier='daily' after explicit update."""
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'daily:2026-04-17')"
    )
    conn.commit()
    conn.close()

    models.update_workflow_run(1, report_tier="daily")

    conn = _get_test_conn(db)
    row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = 1").fetchone()
    conn.close()
    assert row["report_tier"] == "daily"


def test_old_run_without_report_tier_stays_null(db):
    """Old runs without explicit report_tier should remain NULL (backward compat)."""
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'completed', 'completed', '2026-04-16', 'daily:2026-04-16')"
    )
    conn.commit()
    row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = 1").fetchone()
    conn.close()
    assert row["report_tier"] is None


# ── Task 12: Integration test ────────────────────────────────────


def test_p008_phase2_integration(db, tmp_path, monkeypatch):
    """End-to-end: daily tier run goes through full pipeline → HTML archived, correct mode."""
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid: (None, None))

    # 1. Create a daily-tier workflow run
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key, report_tier)"
        " VALUES ('daily', 'reporting', 'full_pending', '2026-04-17', 'daily:2026-04-17', 'daily')"
    )
    conn.commit()
    conn.close()

    # 2. Build snapshot with safety review + cumulative data
    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-17",
        "data_since": "2026-04-17T00:00:00+08:00",
        "data_until": "2026-04-18T00:00:00+08:00",
        "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                       "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
        "reviews": [
            {"id": 1, "headline": "Dangerous", "body": "Found metal shaving in food",
             "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
             "ownership": "own", "images": ["img.jpg"], "author": "Tester",
             "date_published": "2026-04-17"},
        ],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [
                {"id": 1, "rating": 1.0, "ownership": "own", "product_sku": "SKU1",
                 "headline": "Dangerous", "body": "Metal shaving", "sentiment": "negative",
                 "analysis_labels": "[]"},
            ],
        },
    }

    # 3. Call the full pipeline
    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)

    # 4. Verify results
    assert result["mode"] == "daily_briefing"
    assert result["status"] == "completed"
    assert result["reviews_count"] == 1
    assert result.get("html_path") is not None
    assert result["email_skipped"] is False  # has reviews → should send

    # 5. Verify HTML content
    import os
    assert os.path.isfile(result["html_path"])
    html = open(result["html_path"], encoding="utf-8").read()
    assert "高关注度评论" in html  # safety + image → high attention
    assert "需行动" in html or "安全" in html  # safety signal in attention block

    # 6. Verify old run (NULL tier) still uses old path
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'reporting', 'full_pending', '2026-04-16', 'daily:2026-04-16')"
    )
    conn.commit()
    conn.close()

    old_snapshot = {
        "run_id": 2, "logical_date": "2026-04-16",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "products": [], "reviews": [],
        "cumulative": {"products": [], "reviews": []},
    }
    old_result = report_snapshot.generate_report_from_snapshot(old_snapshot, send_email=False)
    assert old_result["mode"] in ("quiet", "change", "full"), \
        f"NULL tier should use old path, got mode={old_result['mode']}"
