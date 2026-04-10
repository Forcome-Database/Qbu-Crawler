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
