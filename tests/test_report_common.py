"""Tests for server/report_common.py — shared constants and helpers."""

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
    normalized = {
        "self": {"top_negative_clusters": [
            {"label_code": "quality_stability", "review_count": 13},
            {"label_code": "material_finish", "review_count": 7},
        ]},
        "competitor": {"top_positive_themes": [
            {"label_code": "solid_build", "review_count": 69},
            {"label_code": "quality_stability", "review_count": 5},
        ]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    assert gaps[0]["label_code"] == "quality_stability"
    assert gaps[0]["competitor_positive_count"] == 5
    assert gaps[0]["own_negative_count"] == 13


def test_competitor_gap_analysis_empty():
    normalized = {
        "self": {"top_negative_clusters": [{"label_code": "material_finish", "review_count": 7}]},
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
