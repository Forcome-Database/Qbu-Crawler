"""Tests for server/report_common.py — shared constants and helpers."""

import pytest
from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _SEVERITY_DISPLAY,
    _PRIORITY_DISPLAY,
    _label_display,
    _summary_text,
    normalize_deep_report_analytics,
)


def test_label_display_known_code():
    assert _label_display("quality_stability") == "质量稳定性"


def test_label_display_unknown_code():
    assert _label_display("unknown_xyz") == "unknown_xyz"


def test_summary_text_cn_preferred():
    review = {"headline_cn": "标题", "body_cn": "内容", "headline": "Title", "body": "Content"}
    result = _summary_text(review)
    assert "标题" in result
    assert "内容" in result


def test_normalize_handles_none():
    result = normalize_deep_report_analytics(None)
    assert result["kpis"]["product_count"] == 0
    assert result["mode"] == "baseline"


def test_normalize_computes_rates():
    analytics = {"kpis": {"ingested_review_rows": 100, "negative_review_rows": 10, "translated_count": 90}}
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["negative_review_rate_display"] == "10.0%"
    assert result["kpis"]["translation_completion_rate_display"] == "90.0%"


def test_issue_cards_complete_fields():
    """issue_cards must carry all fields required by the P3 template."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "logical_date": "2026-04-07",
        "mode": "baseline",
        "snapshot_hash": "abc",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "review_count": 3,
                    "severity": "high",
                    "affected_product_count": 1,
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-04-01",
                    "image_review_count": 1,
                    "example_reviews": [
                        {"product_name": "P", "rating": 1, "headline": "bad",
                         "headline_cn": "差", "body": "broke", "body_cn": "坏了",
                         "images": ["https://example.com/img1.jpg"],
                         "author": "A", "date_published": "2026-01-01"}
                    ],
                }
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {
            "improvement_priorities": [
                {"rank": 1, "target": "P", "issue": "手柄松动", "action": "加强出厂耐久测试", "evidence_count": 3}
            ]
        },
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert card["first_seen"] == "2026-01-01"
    assert card["last_seen"] == "2026-04-01"
    assert card["duration_display"] is not None
    assert "月" in card["duration_display"] or "天" in card["duration_display"]
    assert len(card["example_reviews"]) == 1
    assert len(card["image_evidence"]) == 1
    assert card["image_evidence"][0]["url"] == "https://example.com/img1.jpg"
    assert card["image_evidence"][0]["evidence_id"] == "I1"
    assert card["image_evidence"][0]["data_uri"] is None  # data_uri is None pre-render (render_report_html converts it)
    assert card["recommendation"] == "加强出厂耐久测试"


# ---------------------------------------------------------------------------
# Tests for _cluster_summary_items and _risk_products (report_analytics)
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_analytics import _cluster_summary_items, _risk_products


def _make_labeled_review(ownership, polarity, label_code, severity="medium",
                         product_sku="SKU-1", product_name="Product A",
                         date_published="2026-03-01", headline="Title", body="Body",
                         headline_cn="标题", body_cn="正文", images=None):
    return {
        "review": {
            "ownership": ownership, "product_sku": product_sku,
            "product_name": product_name, "date_published": date_published,
            "headline": headline, "body": body,
            "headline_cn": headline_cn, "body_cn": body_cn,
        },
        "labels": [{"label_code": label_code, "label_polarity": polarity, "severity": severity, "confidence": 0.9}],
        "images": images or [],
    }


def test_cluster_has_affected_product_count():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="B"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["affected_product_count"] == 2


def test_cluster_has_timeline():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-02-14"),
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-03-29"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] == "2026-02-14"
    assert items[0]["last_seen"] == "2026-03-29"


def test_cluster_example_has_en_and_date():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             headline="Broke!", body="Support beam snapped",
                             date_published="2026-03-12"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    ex = items[0]["example_reviews"][0]
    assert ex["headline_en"] == "Broke!"
    assert ex["body_en"] == "Support beam snapped"
    assert ex["date_published"] == "2026-03-12"


def test_cluster_no_dates():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published=""),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] is None
    assert items[0]["last_seen"] is None


def test_risk_products_has_total_reviews():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    items = _risk_products(reviews, snapshot_products=[
        {"sku": "SKU-1", "review_count": 50},
    ])
    assert items[0]["total_reviews"] == 50


def test_risk_products_no_snapshot():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    items = _risk_products(reviews)
    assert items[0]["total_reviews"] == 0


# ---------------------------------------------------------------------------
# Tests for _competitor_gap_analysis and _compute_kpi_deltas
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_common import (
    _competitor_gap_analysis,
    _compute_kpi_deltas,
)


def test_competitor_gap_analysis_finds_intersection():
    # quality_stability and material_finish both map to "solid_build" via _NEGATIVE_TO_POSITIVE_DIMENSION
    normalized = {
        "self": {"top_negative_clusters": [
            {"label_code": "quality_stability", "review_count": 13},
            {"label_code": "material_finish", "review_count": 7},
        ]},
        "competitor": {"top_positive_themes": [
            {"label_code": "solid_build", "review_count": 69},
        ]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    assert gaps[0]["label_code"] == "solid_build"
    assert gaps[0]["competitor_positive_count"] == 69
    assert gaps[0]["own_negative_count"] == 20  # 13 + 7 aggregated under solid_build


def test_competitor_gap_analysis_empty():
    # service_fulfillment has no positive counterpart in _NEGATIVE_TO_POSITIVE_DIMENSION → no gap
    normalized = {
        "self": {"top_negative_clusters": [{"label_code": "service_fulfillment", "review_count": 7}]},
        "competitor": {"top_positive_themes": [{"label_code": "solid_build", "review_count": 69}]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 0


def test_compute_kpi_deltas_normal():
    current = {"negative_review_rows": 78, "ingested_review_rows": 636, "product_count": 9}
    prev = {"kpis": {"negative_review_rows": 66, "ingested_review_rows": 500, "product_count": 9}}
    deltas = _compute_kpi_deltas(current, prev)
    assert deltas["negative_review_rows_delta"] == 12
    assert deltas["negative_review_rows_delta_display"] == "+12"
    assert deltas["product_count_delta"] == 0
    assert deltas["product_count_delta_display"] == "—"


def test_compute_kpi_deltas_no_prev():
    deltas = _compute_kpi_deltas({"negative_review_rows": 78}, None)
    assert deltas == {}


def test_compute_kpi_deltas_missing_field():
    deltas = _compute_kpi_deltas({"negative_review_rows": 10}, {"kpis": {}})
    assert deltas["negative_review_rows_delta"] == 10


# ---------------------------------------------------------------------------
# Tests for _generate_hero_headline, _compute_alert_level, _humanize_bullets
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_common import (
    _generate_hero_headline,
    _compute_alert_level,
    _humanize_bullets,
)


def test_hero_headline_with_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Cabela's Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 14}]}],
                 "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
        "kpis": {"own_negative_review_rows_delta": 12},
    }
    result = _generate_hero_headline(normalized)
    assert "环比" in result
    assert "Cabela's Stuffer" in result
    assert "质量稳定性" in result


def test_hero_headline_no_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability"}]}]},
        "competitor": {"top_positive_themes": []},
        "kpis": {},
    }
    result = _generate_hero_headline(normalized)
    assert "36%" in result  # 18/50


def test_hero_headline_no_risk():
    normalized = {"self": {"risk_products": []}, "competitor": {"top_positive_themes": []}, "kpis": {}}
    result = _generate_hero_headline(normalized)
    assert "样本不足" in result


def test_alert_level_red():
    normalized = {
        "self": {"top_negative_clusters": [{"severity": "high", "review_count": 10}]},
        "kpis": {"negative_review_rows_delta": 0},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "red"


def test_alert_level_yellow():
    normalized = {
        "self": {"top_negative_clusters": [{"severity": "medium", "review_count": 3}]},
        "kpis": {"own_negative_review_rows_delta": 5},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "yellow"


def test_alert_level_green():
    normalized = {"self": {"top_negative_clusters": []}, "kpis": {"negative_review_rows_delta": 0}}
    level, _ = _compute_alert_level(normalized)
    assert level == "green"


def test_humanize_bullets_with_rate_and_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability"}]}]},
        "competitor": {"top_positive_themes": [{"label_display": "做工扎实", "review_count": 69, "label_code": "solid_build"}],
                       "gap_analysis": []},
        "kpis": {"product_count": 9, "ingested_review_rows": 636, "untranslated_count": 0,
                 "own_negative_review_rows_delta": 5, "translation_completion_rate": 1.0},
    }
    bullets = _humanize_bullets(normalized)
    assert len(bullets) == 3
    assert "36%" in bullets[0]
    assert "新增 5 条" in bullets[0]


def test_humanize_bullets_low_translation():
    normalized = {
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "gap_analysis": []},
        "kpis": {"product_count": 5, "ingested_review_rows": 100,
                 "untranslated_count": 40, "translation_completion_rate": 0.6},
    }
    bullets = _humanize_bullets(normalized)
    assert any("翻译未完成" in b for b in bullets)


# ---------------------------------------------------------------------------
# Tests for compute_health_index and compute_competitive_gap_index
# ---------------------------------------------------------------------------

from qbu_crawler.server import report_common


def test_compute_health_index_perfect():
    analytics = {
        "kpis": {"own_avg_rating": 5.0, "negative_review_rate": 0, "own_product_count": 3},
        "self": {"risk_products": []},
    }
    assert report_common.compute_health_index(analytics) == 100.0


def test_compute_health_index_worst():
    from qbu_crawler import config
    analytics = {
        "kpis": {"own_avg_rating": 1.0, "negative_review_rate": 1.0, "own_product_count": 1},
        "self": {"risk_products": [{"risk_score": config.HIGH_RISK_THRESHOLD + 1}]},
    }
    assert report_common.compute_health_index(analytics) == 9.0  # 0.2*20 + 0.2*25 + 0*35 + 0*20 = 9


def test_compute_competitive_gap_index():
    gaps = [
        {"competitor_positive_count": 10, "own_negative_count": 5,
         "competitor_total": 100, "own_total": 100},
        {"competitor_positive_count": 8, "own_negative_count": 3,
         "competitor_total": 100, "own_total": 100},
    ]
    # dim1: (10/100 + 5/100) / 2 = 0.075
    # dim2: (8/100 + 3/100) / 2 = 0.055
    # avg = (0.075 + 0.055) / 2 = 0.065 → round(6.5) = 6
    assert report_common.compute_competitive_gap_index(gaps) == 6


def test_compute_competitive_gap_index_empty():
    assert report_common.compute_competitive_gap_index([]) == 0


def test_competitive_gap_index_normalized():
    """Gap index should be rate-based, not inflated by sample size."""
    from qbu_crawler.server.report_common import compute_competitive_gap_index

    small_sample = [
        {"competitor_positive_count": 5, "own_negative_count": 3,
         "competitor_total": 10, "own_total": 10},
    ]
    large_sample = [
        {"competitor_positive_count": 50, "own_negative_count": 30,
         "competitor_total": 100, "own_total": 100},
    ]
    idx_small = compute_competitive_gap_index(small_sample)
    idx_large = compute_competitive_gap_index(large_sample)
    # Same proportions → same index
    assert idx_small == idx_large, \
        f"Same proportions should yield equal index: {idx_small} vs {idx_large}"


# ---------------------------------------------------------------------------
# Tests for normalize injecting health_index, kpi_cards, issue_cards
# ---------------------------------------------------------------------------


def test_normalize_injects_health_index():
    analytics = {
        "kpis": {
            "ingested_review_rows": 100,
            "negative_review_rows": 10,
            "translated_count": 90,
            "own_product_count": 2,
            "own_avg_rating": 4.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "health_index" in result["kpis"]
    assert isinstance(result["kpis"]["health_index"], float)
    assert result["kpis"]["health_index"] > 0


def test_normalize_injects_kpi_cards():
    analytics = {
        "kpis": {"ingested_review_rows": 50, "negative_review_rows": 5, "translated_count": 50},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "kpi_cards" in result
    assert len(result["kpi_cards"]) == 5
    labels = [c["label"] for c in result["kpi_cards"]]
    assert "健康指数" in labels
    assert "竞品差距指数" in labels


def test_normalize_injects_issue_cards():
    analytics = {
        "kpis": {"ingested_review_rows": 10, "translated_count": 10},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {"label_code": "quality_stability", "severity": "high", "review_count": 5, "example_reviews": []},
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "issue_cards" in result["self"]
    assert result["self"]["issue_cards"][0]["label_display"] == "质量稳定性"


def test_alert_level_red_on_low_health(monkeypatch):
    from qbu_crawler import config as _config
    monkeypatch.setattr(_config, "HEALTH_RED", 60)
    normalized = {
        "self": {"top_negative_clusters": []},
        "kpis": {"negative_review_rows_delta": 0, "health_index": 50},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "red"
    assert "健康指数" in text


def test_alert_level_yellow_on_moderate_health(monkeypatch):
    from qbu_crawler import config as _config
    monkeypatch.setattr(_config, "HEALTH_YELLOW", 80)
    monkeypatch.setattr(_config, "HEALTH_RED", 60)
    normalized = {
        "self": {"top_negative_clusters": []},
        "kpis": {"negative_review_rows_delta": 0, "health_index": 70},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "yellow"
    assert "健康指数" in text


# ---------------------------------------------------------------------------
# Tests for _risk_products rating_avg / negative_rate / top_features_display
# ---------------------------------------------------------------------------


def test_risk_products_has_rating_avg_and_negative_rate():
    """_risk_products via normalize returns rating_avg, negative_rate, top_features_display."""
    from qbu_crawler.server.report_analytics import _risk_products
    labeled_reviews = [
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 1},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                        "severity": "high", "confidence": 0.9}],
            "images": [],
        },
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 5},
            "labels": [],
            "images": [],
        },
    ]
    snapshot_products = [{"sku": "SKU1", "rating": 3.5, "review_count": 20}]
    result = _risk_products(labeled_reviews, snapshot_products=snapshot_products)
    assert len(result) == 1
    p = result[0]
    assert p["rating_avg"] == 3.5          # from snapshot_products
    assert p["negative_rate"] == pytest.approx(1 / 20)  # 1 negative / 20 site total
    assert "top_features_display" in p


def test_gap_analysis_has_gap_and_priority_display():
    """Gap analysis items must include 'gap' and 'priority_display'."""
    # material_finish maps to solid_build via _NEGATIVE_TO_POSITIVE_DIMENSION
    normalized = {
        "competitor": {
            "top_positive_themes": [
                {"label_code": "solid_build", "review_count": 10}
            ]
        },
        "self": {
            "top_negative_clusters": [
                {"label_code": "material_finish", "review_count": 6, "severity": "high"}
            ]
        },
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    g = gaps[0]
    assert "gap" in g
    assert "priority_display" in g
    assert g["competitor_positive_count"] == 10
    assert g["own_negative_count"] == 6
    assert g["gap"] == 10 - 6
    assert g["priority_display"] in ("高", "中", "低")


# ---------------------------------------------------------------------------
# Tests for _duration_display with relative dates and MM/DD/YYYY
# ---------------------------------------------------------------------------


def test_duration_display_relative_dates():
    """_duration_display handles relative dates like 'X months ago'."""
    from qbu_crawler.server.report_common import _duration_display
    # Relative dates: "a year ago" is ~365 days, "2 months ago" is ~60 days → ~10 months apart
    result = _duration_display("a year ago", "2 months ago")
    assert result is not None
    assert "月" in result or "年" in result

    # MM/DD/YYYY dates: 01/01/2025 to 06/15/2025 → ~5 months
    result2 = _duration_display("01/01/2025", "06/15/2025")
    assert result2 is not None
    assert "月" in result2

    # Mixed formats: MM/DD/YYYY and ISO
    result3 = _duration_display("01/01/2025", "2026-06-15")
    assert result3 is not None

    # None inputs still return None
    assert _duration_display(None, "2026-01-01") is None
    assert _duration_display("2026-01-01", None) is None


def test_duration_display_year_display():
    """_duration_display renders '约 X 年' for long durations."""
    from qbu_crawler.server.report_common import _duration_display
    # 2 years apart
    result = _duration_display("2023-01-01", "2025-01-01")
    assert result is not None
    assert "年" in result


def test_duration_display_abs_order_invariant():
    """_duration_display returns same result regardless of argument order."""
    from qbu_crawler.server.report_common import _duration_display
    r1 = _duration_display("2026-01-01", "2026-04-01")
    r2 = _duration_display("2026-04-01", "2026-01-01")
    assert r1 == r2
    assert r1 is not None


def test_kpi_cards_value_class_health_index():
    """KPI cards should assign status color classes based on health_index threshold."""
    # Create analytics with conditions that result in low health (< 60)
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 10,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.9,  # Very high negative rate
            "own_avg_rating": 1.0,  # Very low rating
        },
        "self": {
            "risk_products": [
                {"risk_score": 10},  # High risk product to lower health
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    health_card = [c for c in result["kpi_cards"] if c["label"] == "健康指数"][0]
    # Verify that the card has value_class set (it should be one of the severity classes)
    assert health_card["value_class"] in ["severity-high", "severity-medium", "severity-low"]


# ---------------------------------------------------------------------------
# Tests for _parse_date_flexible month/year precision
# ---------------------------------------------------------------------------


def test_parse_date_flexible_month_precision():
    """'5 months ago' from 2026-04-07 should be 2025-11-07, not 2025-11-08 (timedelta drift)."""
    from unittest.mock import patch
    from datetime import date as real_date
    from qbu_crawler.server import report_common

    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2026, 4, 7)

    with patch.object(report_common, "date", FakeDate):
        result = report_common._parse_date_flexible("5 months ago")

    assert result is not None
    assert result == real_date(2025, 11, 7), \
        f"Expected 2025-11-07 but got {result}"

    # Create analytics with high health (> 80)
    analytics2 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 1,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,  # Low negative rate
            "own_avg_rating": 4.8,  # Very high rating
        },
        "self": {
            "risk_products": [],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result2 = normalize_deep_report_analytics(analytics2)
    health_card2 = [c for c in result2["kpi_cards"] if c["label"] == "健康指数"][0]
    # High health should either be severity-low or have no class
    assert health_card2["value_class"] in ["severity-low", ""]


def test_kpi_cards_value_class_negative_rate():
    """KPI cards should assign status colors based on negative_review_rate thresholds."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.25,  # 25% → severity-high
            "own_avg_rating": 3.0,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    rate_card = [c for c in result["kpi_cards"] if c["label"] == "差评率"][0]
    assert rate_card["value_class"] == "severity-high"

    # Test middle range: 10% < rate < 20% → severity-medium
    analytics["kpis"]["own_negative_review_rate"] = 0.15  # 15%
    result = normalize_deep_report_analytics(analytics)
    rate_card = [c for c in result["kpi_cards"] if c["label"] == "差评率"][0]
    assert rate_card["value_class"] == "severity-medium"

    # Test good range: rate <= 10% → no class
    analytics["kpis"]["own_negative_review_rate"] = 0.05  # 5%
    result = normalize_deep_report_analytics(analytics)
    rate_card = [c for c in result["kpi_cards"] if c["label"] == "差评率"][0]
    assert rate_card["value_class"] == ""


def test_kpi_cards_value_class_high_risk_products():
    """KPI cards should assign severity-high for high_risk_count > 0."""
    from qbu_crawler import config as _config

    # Create analytics with high-risk products (risk_score >= HIGH_RISK_THRESHOLD)
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {
            "risk_products": [
                {"risk_score": _config.HIGH_RISK_THRESHOLD},  # Meets threshold
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    risk_card = [c for c in result["kpi_cards"] if c["label"] == "高风险产品"][0]
    assert risk_card["value_class"] == "severity-high"

    # Test with no high-risk products
    analytics2 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {
            "risk_products": [
                {"risk_score": _config.HIGH_RISK_THRESHOLD - 1},  # Below threshold
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result2 = normalize_deep_report_analytics(analytics2)
    risk_card2 = [c for c in result2["kpi_cards"] if c["label"] == "高风险产品"][0]
    assert risk_card2["value_class"] == ""


def test_alert_level_ignores_competitor_negative_delta():
    """Competitor negative review growth must NOT trigger own-product yellow/red alert."""
    from qbu_crawler.server.report_common import _compute_alert_level, normalize_deep_report_analytics

    analytics = {
        "kpis": {
            "ingested_review_rows": 50,
            "negative_review_rows": 20,
            "own_negative_review_rows": 2,
            "own_review_rows": 20,
            "competitor_review_rows": 30,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 4.5,
            "translated_count": 50,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    normalized = normalize_deep_report_analytics(analytics)
    # Simulate previous run had 10 total negatives (mostly competitor)
    normalized["kpis"]["negative_review_rows_delta"] = 10
    normalized["kpis"]["own_negative_review_rows_delta"] = 0

    level, _ = _compute_alert_level(normalized)
    assert level == "green", f"Expected green but got {level} — competitor delta is inflating alert"


def test_health_index_sensitive_to_negative_spike():
    """Health index should drop significantly when negative rate spikes."""
    from qbu_crawler.server.report_common import compute_health_index

    baseline = {
        "kpis": {"own_avg_rating": 4.5, "own_negative_review_rate": 0.05,
                 "own_product_count": 5, "sample_avg_rating": 4.5},
        "self": {"risk_products": []},
    }
    spiked = {
        "kpis": {"own_avg_rating": 4.5, "own_negative_review_rate": 0.30,
                 "own_product_count": 5, "sample_avg_rating": 3.0},
        "self": {"risk_products": []},
    }
    idx_baseline = compute_health_index(baseline)
    idx_spiked = compute_health_index(spiked)
    assert idx_baseline - idx_spiked > 15, \
        f"Index drop too small: {idx_baseline} → {idx_spiked} (diff {idx_baseline - idx_spiked})"


def test_kpi_cards_value_class_competitive_gap():
    """KPI cards should assign status colors based on competitive_gap_index thresholds (0-100 scale)."""
    # severity-high: index > 60
    # Rate-based: (80/100 + 70/100) / 2 = 0.75 → 75 > 60 → severity-high
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 80, "own_negative_count": 70,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }
    result = normalize_deep_report_analytics(analytics)
    gap_card = [c for c in result["kpi_cards"] if c["label"] == "竞品差距指数"][0]
    assert gap_card["value_class"] == "severity-high"

    # severity-medium: 30 < index <= 60
    # Rate-based: (40/100 + 30/100) / 2 = 0.35 → 35 → severity-medium
    analytics2 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 40, "own_negative_count": 30,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }
    result2 = normalize_deep_report_analytics(analytics2)
    gap_card2 = [c for c in result2["kpi_cards"] if c["label"] == "竞品差距指数"][0]
    assert gap_card2["value_class"] == "severity-medium"

    # no class: index <= 30
    # Rate-based: (8/100 + 7/100) / 2 = 0.075 → 8 → no class
    analytics3 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 8, "own_negative_count": 7,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }
    result3 = normalize_deep_report_analytics(analytics3)
    gap_card3 = [c for c in result3["kpi_cards"] if c["label"] == "竞品差距指数"][0]
    assert gap_card3["value_class"] == ""


def test_baseline_mode_suppresses_deltas():
    """In baseline mode, KPI deltas should show '—' and baseline_note should exist."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "mode": "baseline",
        "baseline_sample_days": 1,
        "kpis": {
            "ingested_review_rows": 50,
            "negative_review_rows": 5,
            "own_negative_review_rows": 3,
            "translated_count": 50,
            "negative_review_rows_delta": 5,
            "negative_review_rows_delta_display": "+5",
            "own_negative_review_rows_delta": 3,
            "own_negative_review_rows_delta_display": "+3",
            "ingested_review_rows_delta": 10,
            "ingested_review_rows_delta_display": "+10",
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    normalized = normalize_deep_report_analytics(analytics)
    assert normalized.get("baseline_note"), "Baseline mode should include explanatory note"
    # All delta displays should be suppressed
    assert normalized["kpis"]["negative_review_rows_delta_display"] == "—"
    assert normalized["kpis"]["own_negative_review_rows_delta_display"] == "—"
    assert normalized["kpis"]["ingested_review_rows_delta_display"] == "—"
    # Delta values should be 0
    assert normalized["kpis"]["negative_review_rows_delta"] == 0
    assert normalized["kpis"]["own_negative_review_rows_delta"] == 0
