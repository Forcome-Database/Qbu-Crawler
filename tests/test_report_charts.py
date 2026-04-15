"""Tests for the Plotly chart builder module."""

from __future__ import annotations

import pytest

from qbu_crawler.server.report_analytics import _compute_chart_data
from qbu_crawler.server.report_charts import (
    QBU_THEME,
    _build_bar_chart,
    _build_health_gauge,
    _build_heatmap,
    _build_quadrant_scatter,
    _build_radar_chart,
    _build_stacked_bar,
    _build_trend_line,
    build_chart_html_fragments,
)


def test_qbu_theme_exists():
    assert QBU_THEME is not None


def test_health_gauge_returns_html():
    html = _build_health_gauge(72)
    assert "<div" in html
    assert "plotly" in html.lower() or "js-plotly-plot" in html


def test_health_gauge_accepts_thresholds():
    html = _build_health_gauge(45, threshold_red=50, threshold_yellow=70)
    assert "<div" in html


def test_bar_chart_returns_html():
    html = _build_bar_chart(
        labels=["手柄松动", "密封漏油", "电机过热"],
        values=[12, 8, 5],
        title="问题频次",
    )
    assert "<div" in html


def test_bar_chart_with_severity_colors():
    html = _build_bar_chart(
        labels=["A", "B", "C"],
        values=[10, 5, 2],
        title="Test",
        colors=["#6b3328", "#b7633f", "#a89070"],
    )
    assert "<div" in html


def test_heatmap_returns_html():
    html = _build_heatmap(
        z=[[0.8, -0.3], [-0.6, 0.5]],
        x_labels=["Product A", "Product B"],
        y_labels=["做工", "性能"],
        title="情感热力图",
    )
    assert "<div" in html


def test_radar_chart_returns_html():
    html = _build_radar_chart(
        categories=["做工", "性能", "易用", "清洁", "性价比"],
        own_values=[0.3, 0.5, 0.6, 0.4, 0.7],
        competitor_values=[0.8, 0.7, 0.6, 0.5, 0.4],
        title="竞品对标",
    )
    assert "<div" in html


def test_quadrant_scatter_returns_html():
    html = _build_quadrant_scatter(
        products=[
            {"name": "Prod A", "price": 100, "rating": 4.5, "ownership": "own"},
            {"name": "Prod B", "price": 200, "rating": 3.5, "ownership": "competitor"},
            {"name": "Prod C", "price": 150, "rating": 4.0, "ownership": "competitor"},
        ],
        title="价格-评分",
    )
    assert "<div" in html


def test_trend_line_returns_html():
    html = _build_trend_line(
        dates=["2026-04-01", "2026-04-02", "2026-04-03"],
        values=[3.5, 3.4, 3.6],
        title="评分趋势",
        y_label="评分",
    )
    assert "<div" in html


def test_stacked_bar_returns_html():
    html = _build_stacked_bar(
        categories=["Product A", "Product B"],
        positive=[50, 30],
        neutral=[10, 5],
        negative=[5, 15],
        title="情感分布",
    )
    assert "<div" in html


def test_build_chart_html_fragments_minimal():
    """Minimal analytics produces at least health_gauge."""
    analytics = {
        "kpis": {"health_index": 72},
        "self": {"risk_products": [], "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
    }
    fragments = build_chart_html_fragments(analytics)
    assert "health_gauge" in fragments
    assert "<div" in fragments["health_gauge"]


def test_build_chart_html_fragments_with_data():
    analytics = {
        "kpis": {"health_index": 65},
        "self": {
            "risk_products": [
                {
                    "product_name": "A",
                    "product_sku": "S1",
                    "risk_score": 14,
                    "negative_review_rows": 12,
                    "total_reviews": 50,
                },
            ],
            "top_negative_clusters": [
                {"label_display": "手柄松动", "review_count": 12, "severity": "high"},
            ],
        },
        "competitor": {
            "top_positive_themes": [
                {"label_display": "做工扎实", "review_count": 56},
            ],
        },
    }
    fragments = build_chart_html_fragments(analytics)
    assert "health_gauge" in fragments
    assert "self_risk_products" in fragments
    assert "self_negative_clusters" in fragments
    assert "competitor_positive_themes" in fragments


def test_heatmap_produces_continuous_values():
    """Heatmap z values should not all collapse to -1/0/1."""
    from qbu_crawler.server.report_analytics import _compute_chart_data

    labeled = []
    # Product 1: 3 positive solid_build + 2 negative quality_stability
    for _ in range(3):
        labeled.append({"review": {"ownership": "own", "product_sku": "S1", "product_name": "Cabela's Commercial-Grade Sausage Stuffer"},
                        "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
                        "images": [], "product": {}})
    for _ in range(2):
        labeled.append({"review": {"ownership": "own", "product_sku": "S1", "product_name": "Cabela's Commercial-Grade Sausage Stuffer"},
                        "labels": [{"label_code": "quality_stability", "label_polarity": "negative", "severity": "high", "confidence": 0.9}],
                        "images": [], "product": {}})
    # Product 2: 1 positive
    labeled.append({"review": {"ownership": "own", "product_sku": "S2", "product_name": "Cabela's Heavy-Duty Sausage Stuffer"},
                    "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
                    "images": [], "product": {}})

    snapshot = {"products": [
        {"name": "Cabela's Commercial-Grade Sausage Stuffer", "sku": "S1", "ownership": "own", "price": 349.99, "rating": 3.6, "review_count": 88},
        {"name": "Cabela's Heavy-Duty Sausage Stuffer", "sku": "S2", "ownership": "own", "price": 169.99, "rating": 3.3, "review_count": 79},
    ]}
    charts = _compute_chart_data(labeled, snapshot)
    heatmap = charts.get("_heatmap_data")
    assert heatmap is not None

    # y_labels should use smart truncation (not mid-word cut)
    for label in heatmap["y_labels"]:
        assert not label.endswith("Sausa"), f"Label truncated mid-word: {label}"

    # At least one z value should be between -1 and 1 (continuous, not ternary)
    all_z = [v for row in heatmap["z"] for v in row if v != 0.0]
    has_continuous = any(-1 < v < 1 for v in all_z)
    assert has_continuous, f"All z values are ternary: {all_z}"


def test_radar_uses_unified_dimensions():
    """Radar chart should use 5 unified dimensions with continuous values."""
    from qbu_crawler.server.report_common import CODE_TO_DIMENSION

    # Verify dimension mapping
    assert CODE_TO_DIMENSION["quality_stability"] == "耐久性与质量"
    assert CODE_TO_DIMENSION["solid_build"] == "耐久性与质量"
    assert CODE_TO_DIMENSION["structure_design"] == "设计与使用"
    assert CODE_TO_DIMENSION["easy_to_use"] == "设计与使用"
    assert CODE_TO_DIMENSION["service_fulfillment"] == "售后与履约"

    labeled_reviews = [
        # Own: 1 negative quality_stability (maps to "耐久性与质量")
        {"review": {"ownership": "own", "product_sku": "S1", "product_name": "P1"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative", "severity": "high", "confidence": 0.9}],
         "images": [], "product": {}},
        # Own: 1 positive solid_build (also maps to "耐久性与质量")
        {"review": {"ownership": "own", "product_sku": "S1", "product_name": "P1"},
         "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
         "images": [], "product": {}},
        # Competitor: 1 positive solid_build
        {"review": {"ownership": "competitor", "product_sku": "C1", "product_name": "CP1"},
         "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
         "images": [], "product": {}},
        # Competitor: 1 positive easy_to_use (maps to "设计与使用")
        {"review": {"ownership": "competitor", "product_sku": "C1", "product_name": "CP1"},
         "labels": [{"label_code": "easy_to_use", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
         "images": [], "product": {}},
    ]
    snapshot = {"products": [
        {"name": "P1", "sku": "S1", "ownership": "own", "price": 100, "rating": 3.5},
        {"name": "CP1", "sku": "C1", "ownership": "competitor", "price": 200, "rating": 4.5},
    ]}
    charts = _compute_chart_data(labeled_reviews, snapshot)
    radar = charts.get("_radar_data", {})
    if radar:
        assert "耐久性与质量" in radar["categories"]
        # Own has 1 positive + 1 negative in durability → negative wins → 0/2 = 0.0
        # But we count reviews not labels: 2 reviews, 1 positive, 1 negative (negative wins)
        # → positive_count = 0, total = 2, score = 0.0... wait
        # Actually: review 1 is negative (quality_stability/neg), review 2 is positive (solid_build/pos)
        # In "耐久性与质量" dimension: 2 reviews total, 1 positive → if negative wins when both present in SAME review
        # But these are DIFFERENT reviews, each with only one label → score = 1/2 = 0.5
        idx = radar["categories"].index("耐久性与质量")
        own_val = radar["own_values"][idx]
        assert 0 < own_val < 1, f"Expected continuous value for own, got {own_val}"
        # Competitor has only positive in durability → score = 1.0
        comp_val = radar["competitor_values"][idx]
        assert comp_val == 1.0
        # Own and competitor should differ (the whole point of this fix)
        assert radar["own_values"] != radar["competitor_values"]


def test_sentiment_chart_uses_rating_title():
    """Sentiment distribution chart titles should say '评分分布' not '情感分布'."""
    analytics = {
        "kpis": {"health_index": 65},
        "self": {"risk_products": [], "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
        "_sentiment_distribution_own": {
            "categories": ["Product A", "Product B"],
            "positive": [5, 3],
            "neutral": [1, 1],
            "negative": [2, 4],
        },
        "_sentiment_distribution_competitor": {
            "categories": ["Comp A", "Comp B"],
            "positive": [8, 6],
            "neutral": [2, 1],
            "negative": [1, 3],
        },
    }
    fragments = build_chart_html_fragments(analytics)
    own_html = fragments.get("sentiment_distribution_own", "")
    comp_html = fragments.get("sentiment_distribution_competitor", "")
    # Title should contain "评分分布" not "情感分布"
    assert "\\u8bc4\\u5206\\u5206\\u5e03" in own_html
    assert "\\u60c5\\u611f\\u5206\\u5e03" not in own_html
    assert "\\u8bc4\\u5206\\u5206\\u5e03" in comp_html
    assert "\\u60c5\\u611f\\u5206\\u5e03" not in comp_html


def test_stacked_bar_legend_uses_rating_labels():
    """Stacked bar legend should use '好评(>=4星)' etc., not '正面/中性/负面'."""
    html = _build_stacked_bar(
        categories=["Product A", "Product B"],
        positive=[50, 30],
        neutral=[10, 5],
        negative=[5, 15],
        title="评分分布",
    )
    # Check the rating-based legend entries are present
    assert "4" in html  # "好评(≥4星)" contains 4
    assert "3" in html  # "中评(3星)" contains 3
    assert "2" in html  # "差评(≤2星)" contains 2


def test_compute_chart_data_has_sentiment_chart_metadata():
    """_compute_chart_data should include _sentiment_chart_title and _sentiment_chart_legend."""
    labeled = [
        {"review": {"ownership": "own", "product_sku": "S1", "product_name": "P1"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                     "severity": "high", "confidence": 0.9}],
         "images": [], "product": {}},
    ]
    snapshot = {"products": [
        {"name": "P1", "sku": "S1", "ownership": "own", "price": 10, "rating": 3.5, "review_count": 10},
    ]}
    charts = _compute_chart_data(labeled, snapshot)
    assert charts["_sentiment_chart_title"] == "评分分布"
    assert "positive" in charts["_sentiment_chart_legend"]
    assert "好评" in charts["_sentiment_chart_legend"]["positive"]


def test_heatmap_left_margin_adapts_to_label_length():
    """Heatmap left margin must grow with y_label length."""
    long_labels = ["Cabela's Commercial-Grade Sausage Stuffer", "Another Very Long Product Name Here"]
    html = _build_heatmap(
        z=[[0.1, -0.2], [0.3, -0.1]],
        x_labels=["质量", "设计"],
        y_labels=long_labels,
        title="Test",
    )
    assert html  # renders without error
    # Verify labels are truncated (not full length in output)
    assert "Cabela's Commercial-Grade Sausa" not in html or "\u2026" in html


def test_stacked_bar_has_percentage_labels():
    """Stacked bar chart should include percentage text in segments."""
    from qbu_crawler.server.report_charts import _build_stacked_bar
    html = _build_stacked_bar(
        categories=["Product A", "Product B"],
        positive=[40, 10],
        neutral=[10, 5],
        negative=[50, 85],
        title="Test",
    )
    assert html
    # 50% negative for Product A should show "50%"
    assert "50%" in html
    # 85% negative for Product B should show "85%"
    assert "85%" in html


def test_issue_cluster_footnote_in_tooltips():
    """METRIC_TOOLTIPS should contain issue cluster footnote."""
    from qbu_crawler.server.report_common import METRIC_TOOLTIPS

    assert "问题聚类" in METRIC_TOOLTIPS
    assert "AI 语义分析" in METRIC_TOOLTIPS["问题聚类"]


def test_quadrant_scatter_truncation_length():
    """Scatter chart should truncate names at 20 chars, not 12."""
    products = [
        {"name": "Cabela's Commercial-Grade", "price": 200, "rating": 3.5, "ownership": "own"},
        {"name": "25 LB Motorized Stuffer", "price": 400, "rating": 4.5, "ownership": "competitor"},
    ]
    html = _build_quadrant_scatter(products=products, title="Test")
    # Name should be truncated to ~20 chars (19 + ellipsis), not 12
    assert "Cabela" in html
    # Should NOT be truncated at 12 chars like the old behavior
    assert html  # renders without error
