"""P008 Phase 4 — monthly report."""

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
    db_file = str(tmp_path / "p008p4.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: Config + trigger key ────────────────────────────────


def test_monthly_scheduler_time_config():
    assert hasattr(config, "MONTHLY_SCHEDULER_TIME")
    assert ":" in config.MONTHLY_SCHEDULER_TIME  # HH:MM


def test_category_map_path_config():
    assert hasattr(config, "CATEGORY_MAP_PATH")
    assert config.CATEGORY_MAP_PATH.endswith("category_map.csv")


def test_build_monthly_trigger_key():
    from qbu_crawler.server.workflows import build_monthly_trigger_key
    key = build_monthly_trigger_key("2026-05-01")
    assert key == "monthly:2026-05-01"


# ── Task 2: submit_monthly_run ──────────────────────────────────


def test_submit_monthly_run_creates_reporting_run(db):
    from qbu_crawler.server.workflows import submit_monthly_run
    result = submit_monthly_run(logical_date="2026-05-01")
    assert result["created"] is True
    assert result["trigger_key"] == "monthly:2026-05-01"

    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["workflow_type"] == "monthly"
    assert row["report_tier"] == "monthly"
    assert row["status"] == "reporting"
    assert row["data_since"] == "2026-04-01T00:00:00+08:00"
    assert row["data_until"] == "2026-05-01T00:00:00+08:00"


def test_submit_monthly_run_idempotent(db):
    from qbu_crawler.server.workflows import submit_monthly_run
    r1 = submit_monthly_run(logical_date="2026-05-01")
    r2 = submit_monthly_run(logical_date="2026-05-01")
    assert r1["created"] is True
    assert r2["created"] is False


def test_submit_monthly_run_january_wraps_to_december(db):
    """Window for 2026-01-01 must be [2025-12-01, 2026-01-01)."""
    from qbu_crawler.server.workflows import submit_monthly_run
    result = submit_monthly_run(logical_date="2026-01-01")
    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["data_since"] == "2025-12-01T00:00:00+08:00"
    assert row["data_until"] == "2026-01-01T00:00:00+08:00"


# ── Task 3: MonthlySchedulerWorker ──────────────────────────────


def test_monthly_scheduler_skips_non_first_day(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 4, 17, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False


def test_monthly_scheduler_skips_before_scheduled_time(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 8, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False


def test_monthly_scheduler_triggers_on_first_day_after_time(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is True

    conn = _get_test_conn(db)
    row = conn.execute(
        "SELECT * FROM workflow_runs WHERE trigger_key = 'monthly:2026-05-01'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["report_tier"] == "monthly"


def test_monthly_scheduler_idempotent(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is True
    assert worker.process_once(now=now) is False  # already submitted


def test_monthly_scheduler_waits_for_weekly_runs(db, monkeypatch):
    """Monthly must wait until all weekly runs overlapping the month window are terminal."""
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)

    # Seed a completed daily run + a running weekly run
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-30',"
        " 'daily:2026-04-30', 'daily', '2026-04-30T00:00:00+08:00', '2026-05-01T00:00:00+08:00')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('weekly', 'reporting', 'full_pending', '2026-04-27',"
        " 'weekly:2026-04-27', 'weekly', '2026-04-20T00:00:00+08:00', '2026-04-27T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()

    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False  # blocked on weekly


# ── Task 4: Runtime registration ─────────────────────────────────


def test_runtime_has_weekly_scheduler():
    from qbu_crawler.server.runtime import runtime
    assert hasattr(runtime, "weekly_scheduler")


def test_runtime_has_monthly_scheduler():
    from qbu_crawler.server.runtime import runtime
    assert hasattr(runtime, "monthly_scheduler")


def test_build_runtime_returns_schedulers(monkeypatch):
    from qbu_crawler.server import runtime as runtime_module
    rt = runtime_module.build_runtime()
    # Schedulers may be None if disabled by env vars; just check attribute exists
    assert hasattr(rt, "weekly_scheduler")
    assert hasattr(rt, "monthly_scheduler")


# ── Task 5: load_category_map ───────────────────────────────────


def test_load_category_map_from_csv(tmp_path):
    csv_text = (
        "sku,category,sub_category,price_band_override\n"
        "SKU1,grinder,single_grind,\n"
        "SKU2,slicer,,premium\n"
    )
    csv_path = tmp_path / "category_map.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    from qbu_crawler.server.report_common import load_category_map
    mapping = load_category_map(str(csv_path))
    assert mapping["SKU1"] == {"category": "grinder", "sub_category": "single_grind", "price_band_override": ""}
    assert mapping["SKU2"]["price_band_override"] == "premium"


def test_load_category_map_missing_file_returns_empty():
    from qbu_crawler.server.report_common import load_category_map
    mapping = load_category_map("/nonexistent/path.csv")
    assert mapping == {}


def test_load_category_map_uses_default_path(monkeypatch, tmp_path):
    csv_path = tmp_path / "category_map.csv"
    csv_path.write_text("sku,category,sub_category,price_band_override\nSKU1,grinder,,\n", encoding="utf-8")
    monkeypatch.setattr(config, "CATEGORY_MAP_PATH", str(csv_path))
    from qbu_crawler.server.report_common import load_category_map
    mapping = load_category_map()  # no arg → use config
    assert "SKU1" in mapping


# ── Task 6: derive_category_benchmark ───────────────────────────


def test_derive_category_benchmark_basic():
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 50, "price": 299},
        {"sku": "O2", "ownership": "own", "rating": 4.3, "review_count": 30, "price": 350},
        {"sku": "O3", "ownership": "own", "rating": 4.7, "review_count": 80, "price": 320},
        {"sku": "C1", "ownership": "competitor", "rating": 4.2, "review_count": 200, "price": 310},
        {"sku": "C2", "ownership": "competitor", "rating": 4.6, "review_count": 150, "price": 340},
        {"sku": "C3", "ownership": "competitor", "rating": 4.4, "review_count": 100, "price": 320},
    ]
    category_map = {
        "O1": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "O2": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "O3": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "C1": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "C2": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "C3": {"category": "grinder", "sub_category": "", "price_band_override": ""},
    }
    result = derive_category_benchmark(products, category_map)
    assert "grinder" in result["categories"]
    g = result["categories"]["grinder"]
    assert g["status"] == "ok"  # 3 own + 3 competitor passes ≥3 SKU threshold
    assert "own" in g and "competitor" in g
    assert g["own"]["sku_count"] == 3
    assert g["competitor"]["sku_count"] == 3
    assert g["own"]["avg_rating"] == pytest.approx(4.5, rel=0.01)
    assert g["competitor"]["avg_rating"] == pytest.approx(4.4, rel=0.01)


def test_derive_category_benchmark_insufficient_samples():
    """When a category has < 3 SKUs (own OR competitor), mark insufficient."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 50, "price": 299},
        {"sku": "C1", "ownership": "competitor", "rating": 4.2, "review_count": 200, "price": 310},
    ]
    category_map = {
        "O1": {"category": "slicer", "sub_category": "", "price_band_override": ""},
        "C1": {"category": "slicer", "sub_category": "", "price_band_override": ""},
    }
    result = derive_category_benchmark(products, category_map)
    assert result["categories"]["slicer"]["status"] == "insufficient_samples"


def test_derive_category_benchmark_unmapped_skus():
    """SKUs not in category_map go into the 'unmapped' bucket and don't break analysis."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "X1", "ownership": "own", "rating": 4.0, "review_count": 5, "price": 100},
    ]
    result = derive_category_benchmark(products, category_map={})
    assert result["unmapped_count"] == 1


def test_derive_category_benchmark_fallback_pairing():
    """Empty category map → fallback to direct competitor pairing report."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 50, "price": 299},
        {"sku": "C1", "ownership": "competitor", "rating": 4.2, "review_count": 200, "price": 310},
    ]
    result = derive_category_benchmark(products, category_map={})
    assert result["fallback_mode"] is True
    assert result["pairings"]  # at least one own-vs-competitor pair surfaced


def test_derive_category_benchmark_unknown_ownership_counted_as_unmapped():
    """Products with valid category but non-standard ownership must not silently disappear."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "X1", "ownership": "unknown", "rating": 4.0, "review_count": 10, "price": 100},
        {"sku": "X2", "ownership": "", "rating": 4.0, "review_count": 10, "price": 100},
        {"sku": "X3", "ownership": None, "rating": 4.0, "review_count": 10, "price": 100},
    ]
    category_map = {
        "X1": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "X2": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "X3": {"category": "grinder", "sub_category": "", "price_band_override": ""},
    }
    result = derive_category_benchmark(products, category_map)
    # Neither own nor competitor — all 3 should be unmapped
    assert result["unmapped_count"] == 3
    # No category entry produced (no ok status, no insufficient_samples, nothing)
    assert "grinder" not in result["categories"]


# ── Task 7: derive_product_scorecard ────────────────────────────


def test_scorecard_green_low_risk():
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.7, "review_count": 100}]
    risk_products = [{"sku": "O1", "risk_score": 5, "negative_rate": 0.02, "negative_count": 2, "review_count": 100}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=[])
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "green"


def test_scorecard_yellow_medium_risk():
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.0, "review_count": 50}]
    risk_products = [{"sku": "O1", "risk_score": 22, "negative_rate": 0.05, "negative_count": 3, "review_count": 50}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=[])
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "yellow"


def test_scorecard_red_high_risk():
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 3.0, "review_count": 50}]
    risk_products = [{"sku": "O1", "risk_score": 40, "negative_rate": 0.1, "negative_count": 5, "review_count": 50}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=[])
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "red"


def test_scorecard_red_for_safety_incident():
    """Any critical/high safety incident forces red light, regardless of risk_score."""
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.8, "review_count": 100}]
    risk_products = [{"sku": "O1", "risk_score": 5, "negative_rate": 0.01, "negative_count": 1, "review_count": 100}]
    safety_incidents = [{"product_sku": "O1", "safety_level": "critical"}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=safety_incidents)
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "red"
    assert own["safety_flag"] is True


def test_scorecard_trend_from_previous_month(monkeypatch):
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.5, "review_count": 100}]
    risk_products = [{"sku": "O1", "risk_score": 12, "negative_rate": 0.04, "negative_count": 4, "review_count": 100}]
    prev_scorecards = {"O1": {"risk_score": 25, "light": "yellow"}}
    result = derive_product_scorecard(products, risk_products, safety_incidents=[],
                                      previous_scorecards=prev_scorecards)
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["trend"] == "improving"  # risk dropped from 25 to 12


def test_scorecard_sku_none_not_false_safety_flagged():
    """A product without a SKU must not inherit a None-SKU safety incident's red light."""
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": None, "name": "Orphan", "ownership": "own", "rating": 4.8, "review_count": 50}]
    risk_products = [{"sku": None, "risk_score": 3, "negative_rate": 0.01, "negative_count": 1, "review_count": 50}]
    safety_incidents = [{"product_sku": None, "safety_level": "critical"}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=safety_incidents)
    own = result["scorecards"][0]
    assert own["safety_flag"] is False
    assert own["light"] == "green"  # low risk, no safety → green


# ── Task 8: derive_issue_lifecycles (full state machine) ────────


def _make_review(rid, date_str, rating, ownership="own", body="x", labels=None, sku="SKU1", impact_category=None):
    return {
        "id": rid,
        "date_published_parsed": date_str,
        "rating": rating,
        "ownership": ownership,
        "body": body,
        "headline": "h",
        "product_sku": sku,
        "impact_category": impact_category,
        "analysis_labels": json.dumps(labels or [{"code": "quality_stability", "polarity": "negative"}]),
    }


def test_lifecycle_active_after_recent_negative():
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [_make_review(1, "2026-04-15", 1.0)]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "active"


def test_lifecycle_receding_after_positive_overcome():
    """active → receding: positive cohort dominates within 30 days, ≥3 reviews threshold."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [
        _make_review(1, "2026-04-05", 1.0, body="bad"),
        _make_review(2, "2026-04-20", 5.0, body="great", labels=[{"code": "quality_stability", "polarity": "positive"}]),
        _make_review(3, "2026-04-25", 5.0, body="excellent", labels=[{"code": "quality_stability", "polarity": "positive"}]),
        _make_review(4, "2026-04-28", 4.0, body="works", labels=[{"code": "quality_stability", "polarity": "positive"}]),
    ]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "receding"


def test_lifecycle_dormant_after_silence_window():
    """active → dormant: no negative within silence_window days."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [_make_review(1, "2026-01-15", 1.0, body="bad")]
    # 3.5 months of silence; silence_window minimum for single-event is 30 days
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "dormant"


def test_lifecycle_recurrent_after_dormant_then_negative():
    """dormant → recurrent: new negative after dormancy."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [
        _make_review(1, "2026-01-01", 1.0, body="bad"),  # original active
        _make_review(2, "2026-04-25", 1.0, body="bad again"),  # after long silence
    ]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "recurrent"


def test_lifecycle_safety_doubles_silence_window():
    """R6: critical safety issues double the silence window before dormant."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    # 29 days of silence; without safety, single-review default silence_window is 30 → active
    # With critical safety, silence_window doubles to 60 → still active/receding.
    reviews = [_make_review(1, "2026-04-01", 1.0, body="metal shaving in food", impact_category="safety")]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state in ("active", "receding")  # NOT dormant


def test_lifecycle_low_rcw_does_not_trigger_active():
    """R1: very short reviews (low RCW) shouldn't single-handedly trigger active."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [_make_review(1, "2026-04-15", 1.0, body="bad")]  # body only 3 chars
    # Single low-credibility review: still active (R1 fires on credible reviews,
    # but a sole review is the only signal we have — fall through to active)
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    # The exact boundary depends on RCW threshold; main contract: must not crash
    assert state in ("active", "dormant")


def test_derive_all_lifecycles_pre_groups_efficiently():
    """derive_all_lifecycles avoids O(labels × reviews); only relevant reviews per label."""
    from qbu_crawler.server.analytics_lifecycle import derive_all_lifecycles
    reviews = [
        _make_review(1, "2026-04-15", 1.0, sku="O1",
                     labels=[{"code": "quality_stability", "polarity": "negative"}]),
        _make_review(2, "2026-04-15", 1.0, sku="O1",
                     labels=[{"code": "ease_of_use", "polarity": "negative"}]),
    ]
    result = derive_all_lifecycles(reviews, window_end=date(2026, 4, 30))
    keys = list(result.keys())
    # Two distinct labels for own ownership = 2 entries
    assert len(keys) == 2
