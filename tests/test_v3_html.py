"""Tests for Report V3 HTML template and Chart.js generation."""

import json
import os

from jinja2 import Environment, FileSystemLoader

from qbu_crawler.server.report_charts import build_chartjs_configs


def _template():
    template_dir = os.path.join(
        os.path.dirname(__file__), "..", "qbu_crawler", "server", "report_templates"
    )
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    return env.get_template("daily_report_v3.html.j2")


def _empty_trend_dimension(status="accumulating", message="Accumulating"):
    return {
        "status": status,
        "status_message": message,
        "kpis": {"status": status, "items": []},
        "primary_chart": {
            "status": status,
            "chart_type": "line",
            "title": "",
            "labels": [],
            "series": [],
        },
        "table": {"status": status, "columns": [], "rows": []},
    }


def _build_trend_digest():
    data = {}
    for view in ("week", "month", "year"):
        data[view] = {
            "sentiment": _empty_trend_dimension(),
            "issues": _empty_trend_dimension(),
            "products": _empty_trend_dimension(),
            "competition": _empty_trend_dimension(),
        }

    data["month"]["sentiment"] = {
        "status": "ready",
        "status_message": "",
        "kpis": {
            "status": "ready",
            "items": [
                {"label": "Review Count", "value": 12},
                {"label": "Negative Count", "value": 3},
            ],
        },
        "primary_chart": {
            "status": "ready",
            "chart_type": "line",
            "title": "Sentiment Trend",
            "labels": ["2026-03-01", "2026-03-08"],
            "series": [
                {"name": "Review Count", "data": [5, 7]},
                {"name": "Negative Count", "data": [1, 2]},
            ],
        },
        "table": {
            "status": "ready",
            "columns": ["Date", "Review Count", "Negative Count"],
            "rows": [
                {"bucket": "2026-03-01", "review_count": 5, "negative_count": 1},
                {"bucket": "2026-03-08", "review_count": 7, "negative_count": 2},
            ],
        },
    }
    data["month"]["issues"] = {
        "status": "ready",
        "status_message": "",
        "kpis": {"status": "ready", "items": [{"label": "New Issues", "value": 1}]},
        "primary_chart": {
            "status": "ready",
            "chart_type": "line",
            "title": "Issue Trend",
            "labels": ["2026-03-01", "2026-03-08"],
            "series": [{"name": "New Issues", "data": [0, 1]}],
        },
        "table": {
            "status": "ready",
            "columns": ["Date", "New Issues"],
            "rows": [{"bucket": "2026-03-08", "new_issue_count": 1}],
        },
    }
    data["month"]["competition"] = {
        "status": "ready",
        "status_message": "",
        "kpis": {"status": "ready", "items": [{"label": "Rating Gap", "value": 0.4}]},
        "primary_chart": {
            "status": "ready",
            "chart_type": "line",
            "title": "Competition Trend",
            "labels": ["2026-03-01", "2026-03-08"],
            "series": [
                {"name": "Own Avg Rating", "data": [3.8, 3.9]},
                {"name": "Competitor Avg Rating", "data": [4.2, 4.3]},
            ],
        },
        "table": {
            "status": "ready",
            "columns": ["Date", "Own Avg Rating", "Competitor Avg Rating"],
            "rows": [{"bucket": "2026-03-08", "own_avg_rating": 3.9, "competitor_avg_rating": 4.3}],
        },
    }

    return {
        "views": ["week", "month", "year"],
        "dimensions": ["sentiment", "issues", "products", "competition"],
        "default_view": "month",
        "default_dimension": "sentiment",
        "data": data,
    }


def _build_change_digest(view_state, *, empty_state=False):
    return {
        "enabled": True,
        "view_state": view_state,
        "summary": {
            "ingested_review_count": 8,
            "fresh_review_count": 3,
            "historical_backfill_count": 5,
            "fresh_own_negative_count": 1,
            "issue_new_count": 1,
            "issue_escalated_count": 1,
            "issue_improving_count": 1,
            "state_change_count": 2,
        },
        "issue_changes": {
            "new": [
                {
                    "label_display": "Issue New",
                    "change_type": "new",
                    "current_review_count": 2,
                    "delta_review_count": 2,
                    "affected_product_count": 1,
                    "severity": "high",
                }
            ],
            "escalated": [
                {
                    "label_display": "Issue Escalated",
                    "change_type": "escalated",
                    "current_review_count": 3,
                    "delta_review_count": 1,
                    "affected_product_count": 2,
                    "severity": "critical",
                }
            ],
            "improving": [
                {
                    "label_display": "Issue Improving",
                    "change_type": "improving",
                    "current_review_count": 1,
                    "delta_review_count": 0,
                    "affected_product_count": 1,
                    "severity": "medium",
                    "days_quiet": 9,
                }
            ],
            "de_escalated": [],
        },
        "product_changes": {
            "price_changes": [
                {"sku": "OWN-1", "name": "Own Grinder", "old": "$199", "new": "$179"}
            ],
            "stock_changes": [],
            "rating_changes": [],
            "new_products": [],
            "removed_products": [],
        },
        "review_signals": {
            "fresh_negative_reviews": [
                {
                    "product_name": "Own Grinder",
                    "headline_display": "Motor failed",
                    "body_display": "Stopped working after two uses.",
                }
            ],
            "fresh_competitor_positive_reviews": [
                {
                    "product_name": "Competitor Pro",
                    "headline_display": "Worth every penny",
                    "body_display": "Quiet, stable, and easy to clean.",
                }
            ],
        },
        "warnings": {
            "translation_incomplete": {"enabled": False, "message": ""},
            "estimated_dates": {"enabled": False, "message": ""},
            "backfill_dominant": {"enabled": True, "message": "Backfill dominates this run."},
        },
        "empty_state": {
            "enabled": empty_state,
            "title": "No significant changes" if empty_state else "",
            "description": "Window is stable." if empty_state else "",
        },
    }


def _render_context(mode, report_semantics, change_view_state, *, kpi_overrides=None, empty_state=False):
    kpis = {
        "health_index": 57.4,
        "own_review_rows": 141,
        "competitor_review_rows": 100,
        "product_count": 9,
        "own_product_count": 3,
        "competitor_product_count": 6,
        "translation_completion_rate": 1.0,
    }
    if kpi_overrides:
        kpis.update(kpi_overrides)

    trend_digest = _build_trend_digest()
    return {
        "logical_date": "2026-04-10",
        "mode": mode,
        "snapshot": {"snapshot_at": "2026-04-10T06:00:00", "run_id": 2, "reviews": []},
        "analytics": {
            "mode": mode,
            "mode_display": "Bootstrap" if mode == "baseline" else "Incremental",
            "report_semantics": report_semantics,
            "is_bootstrap": report_semantics == "bootstrap",
            "kpis": kpis,
            "kpi_cards": [
                {
                    "label": "Health Index",
                    "value": "57.4",
                    "tooltip": "test",
                    "value_class": "",
                    "delta_display": "",
                    "delta_class": "",
                }
            ],
            "issue_cards": [],
            "self": {"risk_products": []},
            "competitor": {"gap_analysis": [], "benchmark_examples": []},
            "top_actions": [],
            "change_digest": _build_change_digest(change_view_state, empty_state=empty_state),
            "trend_digest": trend_digest,
        },
        "charts": build_chartjs_configs({"kpis": {"health_index": 57.4}, "trend_digest": trend_digest}),
        "alert_level": "yellow",
        "alert_text": "Alert",
        "report_copy": {"hero_headline": "Test", "executive_bullets": ["P1"]},
        "css_text": "",
        "js_text": "",
        "threshold": 2,
    }


class TestChartJsConfigs:
    def test_returns_dict(self):
        configs = build_chartjs_configs({})
        assert isinstance(configs, dict)

    def test_health_gauge_from_kpis(self):
        configs = build_chartjs_configs({"kpis": {"health_index": 57.4}})
        assert "health_gauge" in configs
        assert configs["health_gauge"]["type"] == "doughnut"
        json.dumps(configs["health_gauge"])

    def test_trend_chart_from_trend_digest(self):
        configs = build_chartjs_configs({"trend_digest": _build_trend_digest()})

        assert "trend_month_sentiment" in configs
        config = configs["trend_month_sentiment"]
        assert config["type"] == "line"
        assert config["data"]["labels"] == ["2026-03-01", "2026-03-08"]
        assert [item["label"] for item in config["data"]["datasets"]] == ["Review Count", "Negative Count"]
        json.dumps(config)

    def test_skips_non_ready_trend_chart(self):
        trend_digest = _build_trend_digest()
        trend_digest["data"]["month"]["products"] = _empty_trend_dimension()

        configs = build_chartjs_configs({"trend_digest": trend_digest})

        assert "trend_month_products" not in configs

    def test_all_configs_json_serializable(self):
        analytics = {
            "kpis": {"health_index": 60.0},
            "_radar_data": {
                "categories": ["A", "B", "C"],
                "own_values": [0.5, 0.3, 0.8],
                "competitor_values": [0.7, 0.6, 0.9],
            },
            "_sentiment_distribution_own": {
                "categories": ["P1"],
                "positive": [10],
                "neutral": [3],
                "negative": [5],
            },
            "_products_for_charts": [
                {"name": "P1", "ownership": "own", "price": 100, "rating": 4.0},
                {"name": "P2", "ownership": "competitor", "price": 200, "rating": 4.5},
            ],
            "trend_digest": _build_trend_digest(),
        }
        configs = build_chartjs_configs(analytics)
        for cfg in configs.values():
            json.dumps(cfg)


class TestV3TemplateRender:
    def test_baseline_keeps_changes_and_trends_tabs(self):
        html = _template().render(**_render_context("baseline", "bootstrap", "bootstrap"))

        assert "tab-overview" in html
        assert 'data-tab="changes"' in html
        assert 'id="tab-changes"' in html
        assert 'data-tab="trends"' in html
        assert 'id="tab-trends"' in html
        assert "Monitoring Start" in html

    def test_incremental_renders_grouped_change_content(self):
        html = _template().render(**_render_context("incremental", "incremental", "active"))

        assert "Issue New" in html
        assert "Issue Escalated" in html
        assert "Issue Improving" in html
        assert "Own Grinder" in html
        assert "Motor failed" in html
        assert "Competitor Pro" in html
        assert "Worth every penny" in html
        assert "Backfill dominates this run." in html
        assert "trend-subtab-btn" in html
        assert "trend-panel-month-sentiment" in html

    def test_tabs_and_sections_remain_visible_when_counts_are_empty(self):
        html = _template().render(
            **_render_context(
                "incremental",
                "incremental",
                "empty",
                kpi_overrides={
                    "own_review_rows": 0,
                    "competitor_review_rows": 0,
                    "product_count": 0,
                    "own_product_count": 0,
                    "competitor_product_count": 0,
                },
                empty_state=True,
            )
        )

        assert 'data-tab="overview"' in html
        assert 'data-tab="changes"' in html
        assert 'data-tab="trends"' in html
        assert 'data-tab="issues"' in html
        assert 'data-tab="products"' in html
        assert 'data-tab="competitive"' in html
        assert 'data-tab="panorama"' in html
        assert 'id="tab-issues"' in html
        assert 'id="tab-products"' in html
        assert 'id="tab-competitive"' in html

    def test_trend_panel_renders_ready_components_when_block_accumulating(self):
        """spec §8.5 + Codex P1-B：趋势组件必须按 kpis.status / primary_chart.status /
        table.status 独立判断，不能被外层 block.status='accumulating' 一刀切。"""
        context = _render_context("incremental", "incremental", "active")
        # Override month/products 为混合状态：block.status=accumulating 但 kpis/table 是 ready
        trend_digest = context["analytics"]["trend_digest"]
        trend_digest["data"]["month"]["products"] = {
            "status": "accumulating",
            "status_message": "产品快照样本不足，连续状态趋势仍在积累。",
            "kpis": {
                "status": "ready",
                "items": [
                    {"label": "跟踪 SKU", "value": 3},
                    {"label": "累计快照", "value": 12},
                ],
            },
            "primary_chart": {
                "status": "accumulating",
                "chart_type": "line",
                "title": "",
                "labels": [],
                "series": [],
            },
            "table": {
                "status": "ready",
                "columns": ["SKU"],
                "rows": [
                    {"SKU": "SKU-1"},
                    {"SKU": "SKU-2"},
                    {"SKU": "SKU-3"},
                ],
            },
        }
        html = _template().render(**context)

        # month/products 块必须渲染 KPI 与 table（status ready 的组件），而不是被整块吞掉
        assert "跟踪 SKU" in html
        assert "SKU-1" in html
        # status_message（主图未就绪的说明）也应该可见
        assert "产品快照样本不足" in html
