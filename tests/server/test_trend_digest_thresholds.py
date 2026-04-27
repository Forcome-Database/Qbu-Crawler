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
    assert len(digest["drill_downs"]) == 3


def test_drill_downs_are_three_items_with_full_contract():
    """F011 §4.2.5 — drill_downs must have id, title, data per spec."""
    digest = build_trend_digest(reviews=[])
    drills = digest["drill_downs"]
    assert len(drills) == 3
    expected = [
        ("top_issues", "Top 3 问题随时间"),
        ("product_ratings", "产品评分变化"),
        ("competitor_radar", "竞品对标雷达"),
    ]
    for drill, (expected_id, expected_title) in zip(drills, expected):
        assert drill["id"] == expected_id, f"id mismatch: {drill}"
        assert drill["title"] == expected_title, f"title mismatch: {drill}"
        assert "data" in drill, f"missing data: {drill}"
        assert isinstance(drill["data"], dict), f"data not dict: {drill}"
        # The original kind/items contract belongs inside data now
        assert drill["data"].get("kind") == expected_id


def test_drill_down_top_issues_actually_aggregates_labels():
    """F011 §4.2.5 I-5 regression — top_issues drill-down must aggregate label
    data, not silently return empty items because of phantom
    analysis_labels_parsed field. Production rows write `analysis_labels` as a
    JSON string (see report.py SQL alias `ra.labels AS analysis_labels`); the
    builder used to read a non-existent `analysis_labels_parsed` key and return
    an empty list for every product, even when labels were present."""
    import json
    reviews = [
        {
            "id": i,
            "ownership": "own",
            "rating": 2,
            "scraped_at": "2026-04-25T10:00:00+08:00",
            "date_published": "2026-04-25",
            "product_name": "Widget A",
            "product_sku": "SKU-A",
            # Realistic shape that production code actually writes (JSON string).
            "analysis_labels": json.dumps([
                {"code": "structure_design", "polarity": "negative", "display": "结构设计"},
            ]),
        }
        for i in range(40)
    ]
    digest = build_trend_digest(reviews=reviews)
    # drill_downs[0] is wrapped by _wrap_drilldown → {"id": ..., "title": ..., "data": {...}}
    top_issues = digest["drill_downs"][0]
    assert top_issues["id"] == "top_issues"
    items = top_issues["data"].get("items")
    assert items, (
        "top_issues drill-down silently empty (phantom analysis_labels_parsed bug): "
        f"{top_issues['data']}"
    )
    # Aggregation should have collapsed all 40 reviews onto the single label code.
    assert items[0] == {"label_code": "structure_design", "review_count": 40}


def test_drill_down_competitor_radar_actually_aggregates_labels():
    """F011 §4.2.5 I-5 regression — competitor_radar drill-down has the same
    phantom-field bug class as top_issues. Same fix, same assertion shape."""
    import json
    reviews = [
        {
            "id": i,
            "ownership": "competitor",
            "rating": 5,
            "scraped_at": "2026-04-25T10:00:00+08:00",
            "product_name": "Rival B",
            "product_sku": "SKU-B",
            "analysis_labels": json.dumps([
                {"code": "ease_of_use", "polarity": "positive"},
            ]),
        }
        for i in range(10)
    ]
    digest = build_trend_digest(reviews=reviews)
    radar = digest["drill_downs"][2]
    assert radar["id"] == "competitor_radar"
    items = radar["data"].get("items")
    assert items, f"competitor_radar drill-down silently empty: {radar['data']}"
    assert items[0] == {"label_code": "ease_of_use", "review_count": 10}


def test_competitor_series_separate():
    reviews = [
        _r(f"2026-04-{d:02d}", rating=4, ownership="own") for d in range(20, 27)
    ] + [
        _r(f"2026-04-{d:02d}", rating=3, ownership="competitor") for d in range(20, 27)
    ]
    digest = build_trend_digest(reviews)
    assert len(digest["primary_chart"]["series_own"]) == 7
    assert len(digest["primary_chart"]["series_competitor"]) == 7
