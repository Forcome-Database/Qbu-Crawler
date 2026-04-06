"""Tests for the Plotly chart builder module."""

from __future__ import annotations

import pytest

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
