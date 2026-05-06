from qbu_crawler.server.report_charts import build_chartjs_configs
from qbu_crawler.server.report_html import render_attachment_html


def _workspace_panel(title):
    return {
        "status": "ready",
        "title": title,
        "comparison": {"label": "较前30天"},
        "kpis": {"items": [
            {"label": "指标一", "value": 1},
            {"label": "指标二", "value": 2},
            {"label": "指标三", "value": 3},
        ]},
        "primary_chart": {
            "status": "ready",
            "chart_type": "line",
            "title": title,
            "labels": ["2026-04-28", "2026-04-29"],
            "series": [{"name": "自有平均评分", "data": [4.2, 4.0]}],
        },
        "table": {"columns": ["日期", "值"], "rows": [{"日期": "2026-04-29", "值": 1}]},
    }


def _workspace():
    data = {}
    for view in ["week", "month", "year"]:
        data[view] = {
            "reputation": _workspace_panel("近30天 / 口碑趋势"),
            "issues": _workspace_panel("近30天 / 问题趋势"),
            "products": _workspace_panel("近30天 / 产品趋势"),
            "competition": _workspace_panel("近30天 / 竞品对比"),
        }
    return {
        "views": ["week", "month", "year"],
        "dimensions": ["reputation", "issues", "products", "competition"],
        "default_view": "month",
        "default_dimension": "reputation",
        "data": data,
    }


def _snapshot():
    return {
        "logical_date": "2026-04-29",
        "run_id": 1,
        "snapshot_at": "2026-04-29T12:00:00+08:00",
        "data_since": "2026-04-29T00:00:00+08:00",
        "data_until": "2026-04-30T00:00:00+08:00",
        "products": [],
        "reviews": [],
    }


def _analytics(workspace=True):
    digest = {
        "primary_chart": {
            "kind": "health_trend",
            "confidence": "high",
            "default_window": "30d",
            "series_own": [{"date": "2026-04-29", "value": 70}],
            "series_competitor": [{"date": "2026-04-29", "value": 80}],
            "comparison": {"own_vs_prior_window": {"current": 70, "prior": 60, "delta": 10}},
            "windows_available": ["7d", "30d"],
        },
        "drill_downs": [],
    }
    if workspace:
        digest["workspace"] = _workspace()
    return {
        "report_semantics": "incremental",
        "mode": "incremental",
        "kpis": {"health_index": 80},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": [], "coverage": {}},
        "change_digest": {},
        "trend_digest": digest,
    }


def test_chart_configs_include_trend_workspace():
    configs = build_chartjs_configs(_analytics(workspace=True))

    assert "trend_workspace_month_reputation" in configs
    assert "trend_workspace_month_issues" in configs
    assert "trend_workspace_month_products" in configs
    assert "trend_workspace_month_competition" in configs


def test_workspace_trend_template_has_switches_and_no_forbidden_words():
    html = render_attachment_html(_snapshot(), _analytics(workspace=True))

    assert "近7天" in html
    assert "近30天" in html
    assert "近12个月" in html
    assert "口碑趋势" in html
    assert "问题趋势" in html
    assert "产品趋势" in html
    assert "竞品对比" in html
    assert 'data-trend-workspace-view="month"' in html
    assert 'data-trend-workspace-dimension="reputation"' in html
    assert "快照" not in html
    assert "声浪" not in html
    assert "声量" not in html
    assert "上期" not in html


def test_workspace_trend_charts_use_chartjs_config_attribute():
    html = render_attachment_html(_snapshot(), _analytics(workspace=True))

    assert '<canvas data-chart-config=' in html
    assert '<canvas data-chart=' not in html


def test_workspace_trend_switch_resizes_hidden_chartjs_canvases():
    js_source = (
        __import__("pathlib")
        .Path("qbu_crawler/server/report_templates/daily_report_v3.js")
        .read_text(encoding="utf-8")
    )

    assert "resizeChartsIn" in js_source
    assert "requestAnimationFrame" in js_source
    assert "Chart.getChart(canvas)" in js_source


def test_legacy_trend_fallback_uses_allowed_words():
    html = render_attachment_html(_snapshot(), _analytics(workspace=False))

    assert "对比前30天平均" in html or "较前30天" in html
    assert "上期" not in html
