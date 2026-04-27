"""Tests for Report V3 HTML template and Chart.js generation."""

import json
import os
from pathlib import Path

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
        # F011 §4.2.4 — bootstrap 模式今日变化区改为单卡 "首日基线已建档"，
        # 旧 change-callout kicker ("Monitoring Start" / "Baseline Building") 已删除。
        assert "首日基线已建档" in html

    # ── F011 §4.2.4 — retired: legacy bootstrap "基线建立期第N天" wording ──
    # The change-callout block (kicker + h3 + bootstrap-meta) has been replaced
    # by a single info-card "首日基线已建档" notice. Coverage for the new
    # bootstrap branch lives in
    # tests/server/test_attachment_html_today_changes.py::test_today_changes_hidden_in_bootstrap.

    def test_overview_displays_review_scope_metrics(self):
        context = _render_context("baseline", "bootstrap", "bootstrap")
        context["analytics"]["kpis"].update({
            "own_review_rows": 450,
            "competitor_review_rows": 143,
            "recently_published_count": 1,
        })
        context["analytics"]["change_digest"]["summary"]["ingested_review_count"] = 32
        context["analytics"]["kpi_cards"] = [
            {
                "label": "累计自有评论",
                "value": 450,
                "tooltip": "累计入库的自有产品评论行数，包含历史补采",
                "value_class": "",
                "delta_display": "",
                "delta_class": "",
            }
        ]

        html = _template().render(**context)

        assert "累计自有评论" in html
        assert "累计竞品评论" in html
        assert "本次入库评论" in html
        assert "近30天评论" in html
        assert "累计评论" in html
        assert "本期采集窗口内入库的自有产品评论行数" not in html

    # F011 §4.2.6 — retired: panorama no longer renders heatmap or rating-distribution
    # charts. New panorama is filters + flat 561-row review table.
    # New attachment coverage lives in tests/server/test_attachment_html_other.py.

    # F011 §4.2.5 — retired: legacy 12-panel data shape replaced by primary_chart+drill_downs
    # Original tests asserted on:
    #   - trend_digest.data[view][dim].secondary_charts → flat shape removed
    #   - trend-secondary-grid CSS class → no longer rendered
    #   - "近7天 / 近30天 / 近12个月" view labels + "评论声量与情绪 / 问题结构 /
    #     产品状态 / 竞品对标" dimension labels → all 12-panel toggle text gone
    #   - "date_published" / "scraped_at" inline notes in trend section → moved
    #     into a single anchor toggle ("采集时间" / "发表时间")
    # New attachment coverage lives in tests/server/test_attachment_html_trends.py.

    # ── F011 §4.2.4 — retired: legacy "today changes" 4-region content ──
    # The legacy template rendered: change-summary-grid (4 stat cards), change-grid
    # (3 blocks: 问题变化 / 产品状态变化 / 新近评论信号), change_warnings banner
    # ("Backfill dominates this run."), and aggregated issue_change_items
    # (Issue New / Escalated / Improving English placeholders from the test fixture).
    # F011 §4.2.4 replaces all of it with the 三层金字塔 (立即关注 / 趋势变化 /
    # 反向利用), driven by change_digest.{immediate_attention,trend_changes,
    # competitive_opportunities}. New attachment coverage lives in
    # tests/server/test_attachment_html_today_changes.py.
    def test_incremental_renders_grouped_change_content(self):
        # F011 §4.2.5 — retired the trend-subtab-btn / trend-panel-month-sentiment
        # assertions: the 12-panel toolbar/panel structure is gone, replaced by
        # the primary_chart + drill_downs layout (see
        # tests/server/test_attachment_html_trends.py).
        html = _template().render(**_render_context("incremental", "incremental", "active"))

        # Smoke: trend tab shell still renders.
        assert 'id="tab-trends"' in html

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

    # F011 §4.2.5 — retired: per-component (kpis.status / primary_chart.status /
    # table.status) independent rendering inside a single trend block. The new
    # primary_chart layout has only one render path keyed off
    # primary_chart.confidence (low/no_data → bootstrap notice; high/medium →
    # chart + comparison + drill-downs). The "mixed-state" rendering invariant
    # no longer applies. Confidence-tier coverage lives in
    # tests/server/test_trend_digest_thresholds.py and template-branch coverage
    # in tests/server/test_attachment_html_trends.py.


# ── F011 §4.1.3 — removed legacy email_full.html.j2 fallback-wording tests ──
# These tests previously asserted on the bootstrap/incremental change_digest
# banner and "本次入库 / 历史补采 / 基线建立期第N天 / 监控起点" wording.
# F011 §4.1 redesigns the email body around 4 KPI lamps + Hero + Top 3 +
# product_status; §4.1.3 explicitly removes the change_digest banner from the
# email. New email-template coverage lives in
# tests/server/test_email_full_template.py.


# F011 §4.2.5 — retired: legacy year-view banner driven by trend_digest.view_notes.year.
# The new primary_chart layout no longer has 12 separate panels (week/month/year ×
# sentiment/issues/products/competition); the "year-view-banner" affordance
# disappears with the toolbar. Confidence-tier wording (e.g. "趋势数据正在累积")
# now provides the equivalent user signal — see
# tests/server/test_attachment_html_trends.py::
#   test_trend_section_low_confidence_shows_warning_detail.
