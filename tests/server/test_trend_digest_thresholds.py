import pytest
from qbu_crawler.server.report_analytics import (
    build_trend_digest, _classify_trend_confidence,
    TREND_MIN_HIGH, TREND_MIN_MEDIUM,
)


def _r(date_str, *, rating=5, ownership="own"):
    return {
        "ownership": ownership,
        "rating": rating,
        "scraped_at": date_str + "T10:00:00+08:00",
    }


def test_classify_thresholds():
    assert _classify_trend_confidence(0, 0) == "no_data"
    assert _classify_trend_confidence(5, 3) == "low"
    assert _classify_trend_confidence(15, 5) == "medium"
    assert _classify_trend_confidence(30, 7) == "high"
    assert _classify_trend_confidence(50, 5) == "medium"  # ≥30 but only 5 time points
    assert _classify_trend_confidence(15, 7) == "medium"  # 7 time points but only 15 samples


def test_low_sample_emits_min_sample_warning():
    """3 reviews → low confidence, warning present."""
    reviews = [_r(f"2026-04-0{i+1}") for i in range(3)]
    digest = build_trend_digest(reviews)
    assert digest["primary_chart"]["confidence"] == "low"
    assert digest["primary_chart"]["min_sample_warning"]


def test_medium_sample_threshold():
    """30 reviews / 5 time points → medium."""
    reviews = []
    for d in range(1, 6):  # 5 days
        for _ in range(6):  # 6 reviews per day = 30 total
            reviews.append(_r(f"2026-04-{d:02d}"))
    digest = build_trend_digest(reviews)
    assert digest["primary_chart"]["confidence"] == "medium"


def test_high_sample_threshold():
    """35 reviews / 7 time points → high."""
    reviews = []
    for d in range(1, 8):  # 7 days
        for _ in range(5):  # 5 reviews per day = 35 total
            reviews.append(_r(f"2026-04-{d:02d}"))
    digest = build_trend_digest(reviews)
    assert digest["primary_chart"]["confidence"] == "high"
    assert digest["primary_chart"]["min_sample_warning"] is None


def test_dual_anchor_metadata():
    digest = build_trend_digest([])
    pc = digest["primary_chart"]
    assert "scraped_at" in pc["anchors_available"]
    assert "date_published" in pc["anchors_available"]
    assert pc["default_anchor"] == "scraped_at"


def test_default_window_is_30d():
    digest = build_trend_digest([])
    pc = digest["primary_chart"]
    assert pc["default_window"] == "30d"
    assert "30d" in pc["windows_available"]


def test_comparison_baseline_when_prev_window_provided():
    reviews = [_r(f"2026-04-{d:02d}", rating=4) for d in range(20, 27)]
    prev = {"own_avg_health": 70.0}
    digest = build_trend_digest(reviews, prev_window_data=prev)
    cmp = digest["primary_chart"]["comparison"]["own_vs_prior_window"]
    assert "current" in cmp
    assert "prior" in cmp and cmp["prior"] == 70.0
    assert "delta" in cmp
    assert "delta_pct" in cmp


def test_comparison_is_none_when_prev_missing():
    reviews = [_r(f"2026-04-{d:02d}", rating=4) for d in range(20, 27)]
    digest = build_trend_digest(reviews)
    assert digest["primary_chart"]["comparison"] is None


def test_drill_downs_are_three_items():
    digest = build_trend_digest([])
    kinds = [d["kind"] for d in digest["drill_downs"]]
    assert kinds == ["top_issues", "product_ratings", "competitor_radar"]


def test_competitor_series_separate():
    reviews = [
        _r(f"2026-04-{d:02d}", rating=4, ownership="own") for d in range(20, 27)
    ] + [
        _r(f"2026-04-{d:02d}", rating=3, ownership="competitor") for d in range(20, 27)
    ]
    digest = build_trend_digest(reviews)
    assert len(digest["primary_chart"]["series_own"]) == 7
    assert len(digest["primary_chart"]["series_competitor"]) == 7
