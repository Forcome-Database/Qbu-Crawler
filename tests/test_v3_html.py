"""Tests for Report V3 HTML template and Chart.js generation (Phase 3a)."""

import json
from qbu_crawler.server.report_charts import build_chartjs_configs


class TestChartJsConfigs:
    def test_returns_dict(self):
        configs = build_chartjs_configs({})
        assert isinstance(configs, dict)

    def test_health_gauge_from_kpis(self):
        configs = build_chartjs_configs({"kpis": {"health_index": 57.4}})
        assert "health_gauge" in configs
        cfg = configs["health_gauge"]
        assert cfg["type"] == "doughnut"
        # Data should represent 57.4% filled
        assert json.dumps(cfg)  # must be JSON-serializable

    def test_radar_chart(self):
        configs = build_chartjs_configs({
            "_radar_data": {
                "categories": ["耐久性与质量", "设计与使用", "清洁便利性"],
                "own_values": [0.5, 0.3, 0.8],
                "competitor_values": [0.7, 0.6, 0.9],
            },
        })
        assert "radar" in configs
        assert configs["radar"]["type"] == "radar"
        assert len(configs["radar"]["data"]["labels"]) == 3
        assert len(configs["radar"]["data"]["datasets"]) == 2

    def test_radar_needs_3_categories(self):
        configs = build_chartjs_configs({
            "_radar_data": {"categories": ["A", "B"], "own_values": [0.5, 0.3], "competitor_values": [0.7, 0.6]},
        })
        assert "radar" not in configs  # Fewer than 3 categories → skip

    def test_sentiment_distribution(self):
        configs = build_chartjs_configs({
            "_sentiment_distribution_own": {
                "categories": ["Prod1", "Prod2"],
                "positive": [10, 20], "neutral": [3, 5], "negative": [5, 2],
            },
        })
        assert "sentiment_own" in configs
        assert configs["sentiment_own"]["type"] == "bar"

    def test_scatter_chart(self):
        configs = build_chartjs_configs({
            "_products_for_charts": [
                {"name": "Own Grinder", "ownership": "own", "price": 299.99, "rating": 3.5},
                {"name": "Comp Grinder", "ownership": "competitor", "price": 399.99, "rating": 4.7},
            ],
        })
        assert "scatter" in configs
        assert configs["scatter"]["type"] == "scatter"

    def test_scatter_needs_2_products(self):
        configs = build_chartjs_configs({
            "_products_for_charts": [{"name": "A", "ownership": "own", "price": 100, "rating": 4.0}],
        })
        assert "scatter" not in configs

    def test_all_configs_json_serializable(self):
        analytics = {
            "kpis": {"health_index": 60.0},
            "_radar_data": {"categories": ["A", "B", "C"], "own_values": [0.5, 0.3, 0.8], "competitor_values": [0.7, 0.6, 0.9]},
            "_sentiment_distribution_own": {"categories": ["P1"], "positive": [10], "neutral": [3], "negative": [5]},
            "_products_for_charts": [
                {"name": "P1", "ownership": "own", "price": 100, "rating": 4.0},
                {"name": "P2", "ownership": "competitor", "price": 200, "rating": 4.5},
            ],
        }
        configs = build_chartjs_configs(analytics)
        # All configs must be JSON serializable
        for name, cfg in configs.items():
            json.dumps(cfg)  # Should not raise


class TestV3TemplateRender:
    def test_renders_without_error(self):
        from jinja2 import Environment, FileSystemLoader
        import os

        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "qbu_crawler", "server", "report_templates"
        )
        env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
        template = env.get_template("daily_report_v3.html.j2")

        html = template.render(
            logical_date="2026-04-10",
            mode="baseline",
            snapshot={"snapshot_at": "2026-04-10T06:00:00", "run_id": 1, "reviews": []},
            analytics={
                "kpis": {"health_index": 57.4, "own_review_rows": 141,
                         "competitor_review_rows": 0, "product_count": 3,
                         "own_product_count": 3, "competitor_product_count": 0},
                "kpi_cards": [{"label": "健康指数", "value": "57.4", "tooltip": "test", "value_class": "", "delta_display": "", "delta_class": ""}],
                "issue_cards": [],
                "self": {"risk_products": []},
                "competitor": {},
                "report_copy": {"hero_headline": "Test headline", "executive_bullets": ["Point 1"]},
                "mode_display": "首日全量基线版",
                "top_actions": [],
            },
            charts={},
            alert_level="yellow",
            alert_text="测试预警",
            report_copy={"hero_headline": "Test", "executive_bullets": ["P1"]},
            css_text="body { color: black; }",
            js_text="console.log('test');",
            threshold=2,
        )
        assert "QBU网评监控智能分析报告" in html
        assert "57.4" in html
        assert "_uncategorized" not in html
        assert "tab-overview" in html
        assert "tab-issues" in html
        # Baseline mode: no changes tab
        assert "tab-changes" not in html

    def test_renders_with_issue_cards(self):
        from jinja2 import Environment, FileSystemLoader
        import os

        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "qbu_crawler", "server", "report_templates"
        )
        env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
        template = env.get_template("daily_report_v3.html.j2")

        html = template.render(
            logical_date="2026-04-10",
            mode="incremental",
            snapshot={"snapshot_at": "2026-04-10T06:00:00", "run_id": 2, "reviews": []},
            analytics={
                "kpis": {"health_index": 57.4, "own_review_rows": 141,
                         "competitor_review_rows": 100, "product_count": 9,
                         "own_product_count": 3, "competitor_product_count": 6},
                "kpi_cards": [],
                "issue_cards": [
                    {"label_code": "quality_stability", "label_display": "质量稳定性",
                     "feature_display": "质量稳定性", "review_count": 36,
                     "affected_product_count": 3, "severity": "critical",
                     "severity_display": "危急", "first_seen": "2021-04-08",
                     "last_seen": "2026-03-13", "duration_display": "约 5 年",
                     "recency_display": "近90天 2 条", "image_review_count": 5,
                     "translated_rate": 1.0, "example_reviews": [],
                     "image_evidence": [], "recommendation": None, "deep_analysis": None,
                     "sub_features": [], "affected_products": [], "rating_breakdown": {}},
                ],
                "self": {"risk_products": []},
                "competitor": {"gap_analysis": [], "benchmark_examples": []},
                "report_copy": {"hero_headline": "Test", "executive_bullets": []},
                "mode_display": "增量",
                "top_actions": [],
            },
            charts={},
            alert_level="green",
            alert_text="",
            report_copy={"hero_headline": "Test", "executive_bullets": []},
            css_text="",
            js_text="",
            threshold=2,
        )
        assert "质量稳定性" in html
        assert "危急" in html
        # Incremental mode: changes tab button present
        assert "tab-changes" in html
