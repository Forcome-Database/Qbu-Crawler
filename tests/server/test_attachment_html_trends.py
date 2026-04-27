"""F011 §4.2.5 — 附件 HTML 变化趋势区块改 1 主图 + 3 折叠（含 bootstrap 双模式）。

新布局 (mature 期, confidence in {"high", "medium"}):
  口碑健康度趋势 (主图 — series_own + series_competitor)
  对比基线 (vs 上 30 天平均)
  时间切换 / 口径切换
  折叠下钻:
    - Top 3 问题随时间
    - 产品评分变化
    - 竞品对标雷达

bootstrap 期 (confidence in {"low", "no_data"}): 单卡 "趋势数据正在累积"。

删除（必须不出现于 mature 模式）:
  - 旧 12 panel 标题 ("近 7 天 / 评论声量与情绪" 等)
  - 旧 toggle/panel CSS class (trend-view-btn / trend-subtab-btn /
    trend-panel- / trend-toolbar)
  - 旧 trend_digest.data[view][dimension] 数据访问路径
"""
from __future__ import annotations

from pathlib import Path

from qbu_crawler.server.report_html import render_attachment_html


# ──────────────────────────────────────────────────────────
# 共享 fixtures
# ──────────────────────────────────────────────────────────
def _base_snapshot(logical_date="2026-04-27", run_id=0):
    return {
        "logical_date": logical_date,
        "run_id": run_id,
        "snapshot_at": f"{logical_date}T12:00:00+08:00",
        "data_since": f"{logical_date}T00:00:00+08:00",
        "data_until": f"{logical_date}T23:59:59+08:00",
        "products": [],
        "reviews": [],
    }


def _base_kpis():
    return {
        "health_index": 80,
        "ingested_review_rows": 0,
        "own_review_rows": 0,
        "competitor_review_rows": 0,
        "own_product_count": 0,
        "competitor_product_count": 0,
        "own_negative_review_rows": 0,
        "negative_review_rows": 0,
        "low_rating_review_rows": 0,
    }


def _base_analytics(*, report_semantics, trend_digest=None, change_digest=None):
    return {
        "report_semantics": report_semantics,
        "mode": "baseline" if report_semantics == "bootstrap" else "incremental",
        "kpis": _base_kpis(),
        "self": {"risk_products": [], "top_negative_clusters": [],
                 "top_positive_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                       "negative_opportunities": [], "gap_analysis": []},
        "appendix": {"image_reviews": [], "coverage": {}},
        "change_digest": change_digest or {},
        "trend_digest": trend_digest or {},
    }


def _bootstrap_trend_digest():
    """Confidence = no_data → bootstrap branch."""
    return {
        "primary_chart": {
            "kind": "health_trend",
            "default_window": "30d",
            "default_anchor": "scraped_at",
            "windows_available": ["7d", "30d", "12m"],
            "anchors_available": ["scraped_at", "date_published"],
            "series_own": [],
            "series_competitor": [],
            "comparison": None,
            "confidence": "no_data",
            "min_sample_warning": None,
        },
        "drill_downs": [],
    }


def _mature_trend_digest():
    """Confidence = high + populated series + comparison + drill-downs."""
    return {
        "primary_chart": {
            "kind": "health_trend",
            "default_window": "30d",
            "default_anchor": "scraped_at",
            "windows_available": ["7d", "30d", "12m"],
            "anchors_available": ["scraped_at", "date_published"],
            "series_own": [
                {"date": "2026-04-20", "value": 72.5, "sample_count": 10},
                {"date": "2026-04-21", "value": 75.0, "sample_count": 12},
                {"date": "2026-04-22", "value": 78.0, "sample_count": 11},
            ],
            "series_competitor": [
                {"date": "2026-04-20", "value": 68.0, "sample_count": 8},
                {"date": "2026-04-21", "value": 70.0, "sample_count": 9},
                {"date": "2026-04-22", "value": 71.5, "sample_count": 7},
            ],
            "comparison": {
                "own_vs_prior_window": {
                    "current": 78.0,
                    "prior": 73.0,
                    "delta": 5.0,
                    "delta_pct": 6.85,
                },
            },
            "confidence": "high",
            "min_sample_warning": None,
        },
        "drill_downs": [
            {
                "id": "top_issues",
                "title": "Top 3 问题随时间",
                "kind": "top_issues",
                "data": {"items": [{"label_code": "switch_failure", "review_count": 4}]},
            },
            {
                "id": "product_ratings",
                "title": "产品评分变化",
                "kind": "product_ratings",
                "data": {"items": [{"sku": "S1", "product_name": "P1", "rating_avg": 4.2, "review_count": 10}]},
            },
            {
                "id": "competitor_radar",
                "title": "竞品对标雷达",
                "kind": "competitor_radar",
                "data": {"items": [{"label_code": "easy_to_use", "review_count": 6}]},
            },
        ],
    }


def _bootstrap_snapshot():
    return _base_snapshot()


def _bootstrap_analytics():
    return _base_analytics(
        report_semantics="bootstrap",
        trend_digest=_bootstrap_trend_digest(),
    )


def _mature_snapshot():
    return _base_snapshot()


def _mature_analytics(trend_digest=None):
    return _base_analytics(
        report_semantics="incremental",
        trend_digest=trend_digest or _mature_trend_digest(),
    )


def _extract_trend_section(html: str) -> str:
    """Slice out the `<section id="tab-trends">…</section>` block."""
    start = html.find('<section id="tab-trends"')
    assert start >= 0, "could not locate <section id=\"tab-trends\"> in rendered HTML"
    end = html.find("</section>", start)
    assert end >= 0
    return html[start:end]


# ──────────────────────────────────────────────────────────
# Step 1: required RED tests
# ──────────────────────────────────────────────────────────
def test_trend_section_hidden_in_bootstrap():
    """bootstrap (confidence=no_data): 单卡 + 旧 12 panel 标题必须消失."""
    html = render_attachment_html(
        snapshot=_bootstrap_snapshot(),
        analytics=_bootstrap_analytics(),
    )
    assert "趋势数据正在累积" in html
    # 旧 12 panel 标题
    assert "近 7 天 / 评论声量与情绪" not in html
    assert "近 30 天 / 问题结构" not in html


def test_trend_section_shows_primary_chart_in_mature():
    """mature (confidence=high): 主图 + comparison + 三折叠下钻."""
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(),
    )
    assert "口碑健康度趋势" in html
    assert "对比上 30 天平均" in html or "vs 上期平均" in html
    # 折叠下钻
    assert "Top 3 问题随时间" in html
    assert "产品评分变化" in html
    assert "竞品对标雷达" in html


# ──────────────────────────────────────────────────────────
# Regression tests
# ──────────────────────────────────────────────────────────
def test_trend_section_uses_primary_chart_data_source():
    """模板必须读 trend_digest.primary_chart, 不能再读 trend_digest.data[view][dim]."""
    template_path = (
        Path(__file__).resolve().parents[2]
        / "qbu_crawler" / "server" / "report_templates" / "daily_report_v3.html.j2"
    )
    template_source = template_path.read_text(encoding="utf-8")
    assert "trend_digest.data[" not in template_source, (
        "F011 §4.2.5 — 模板必须不再访问 trend_digest.data[view][dim] 路径"
    )


def test_trend_section_no_legacy_12_panels():
    """mature 模式 HTML 中不得出现旧 12 panel toggle/panel class 名."""
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(),
    )
    section = _extract_trend_section(html)

    assert "trend-view-btn" not in section
    assert "trend-subtab-btn" not in section
    assert "trend-panel-" not in section
    assert "trend-toolbar" not in section


def test_trend_section_drill_downs_use_details_summary():
    """三折叠必须用 <details class="drill-down"> + <summary> 实现."""
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(),
    )
    section = _extract_trend_section(html)
    assert '<details class="drill-down"' in section
    assert "<summary>" in section


def test_trend_section_low_confidence_shows_warning_detail():
    """confidence=low + min_sample_warning 应渲染 warning-detail 提示."""
    td = _bootstrap_trend_digest()
    td["primary_chart"]["confidence"] = "low"
    td["primary_chart"]["min_sample_warning"] = "样本 5 条 / 时间点 2，需 ≥30 + ≥7 才能判趋势"
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(trend_digest=td),
    )
    assert "趋势数据正在累积" in html
    assert "样本 5 条" in html
