"""F011 §4.2.4 — 附件 HTML 今日变化区块改三层金字塔（含 bootstrap 双模式）。

新布局 (mature 期):
  🔥 立即关注 (red)   — own_new_negative_reviews / own_rating_drops / own_stock_alerts
  📈 趋势变化 (yellow) — new_issues / escalated_issues / improving_issues
  💡 反向利用 (blue)  — competitor_new_negative_reviews / competitor_new_positive_reviews

bootstrap 期: 单卡 "首日基线已建档"。

删除（必须不出现于 mature 模式）:
  - "本次入库 / 自有新近差评 / 问题变化 / 状态变化 / 新近评论信号"
    （change-summary-grid 4 张统计卡 + change-grid 3 块 + change_warnings banner + change_empty 空状态）
"""
from __future__ import annotations

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
    """A complete-ish kpi dict, normalize_deep_report_analytics merges defaults."""
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


def _base_analytics(*, report_semantics, change_digest=None):
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
    }


def _bootstrap_snapshot():
    return _base_snapshot()


def _bootstrap_analytics():
    return _base_analytics(
        report_semantics="bootstrap",
        change_digest={
            "view_state": "bootstrap",
            "summary": {
                "ingested_review_count": 0,
                "fresh_review_count": 0,
                "historical_backfill_count": 0,
                "baseline_day_index": 1,
                "baseline_display_state": "initial",
            },
            "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
            "product_changes": {"price_changes": [], "stock_changes": [], "rating_changes": []},
            "review_signals": {"fresh_negative_reviews": [], "fresh_competitor_positive_reviews": []},
            "warnings": {},
            "empty_state": {"enabled": False},
            "immediate_attention": {"own_new_negative_reviews": [],
                                    "own_rating_drops": [], "own_stock_alerts": []},
            "trend_changes": {"new_issues": [], "escalated_issues": [],
                              "improving_issues": [], "de_escalated_issues": []},
            "competitive_opportunities": {"competitor_new_negative_reviews": [],
                                          "competitor_new_positive_reviews": []},
        },
    )


def _mature_change_digest_full():
    """All three pyramid layers populated (used by happy-path mature test)."""
    return {
        "view_state": "incremental",
        "summary": {
            "ingested_review_count": 12,
            "fresh_review_count": 12,
            "historical_backfill_count": 0,
            "fresh_own_negative_count": 3,
            "issue_new_count": 1,
            "issue_escalated_count": 1,
            "state_change_count": 2,
        },
        "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
        "product_changes": {"price_changes": [], "stock_changes": [], "rating_changes": []},
        "review_signals": {"fresh_negative_reviews": [], "fresh_competitor_positive_reviews": []},
        "warnings": {},
        "empty_state": {"enabled": False},
        "immediate_attention": {
            "own_new_negative_reviews": [
                {"product_name": ".75 HP Grinder", "review_count": 3,
                 "primary_problems": ["开关失灵", "售后失联"]},
            ],
            "own_rating_drops": [
                {"product_name": ".75 HP Grinder", "sku": "HP75",
                 "rating_from": 4.7, "rating_to": 4.5, "delta": -0.2,
                 # builder-shape mirror keys (see report_snapshot.py:660-668)
                 "prev": 4.7, "new": 4.5},
            ],
            "own_stock_alerts": [
                {"product_name": "Walton's #22", "sku": "W22", "stock_status": "out_of_stock",
                 "prev_status": "in_stock", "new_status": "out_of_stock"},
            ],
        },
        "trend_changes": {
            "new_issues": [
                {"label_code": "switch_failure", "label_display": "开关失灵",
                 "current_review_count": 4, "affected_product_count": 2, "severity": "high"},
            ],
            "escalated_issues": [
                {"label_code": "after_sales", "label_display": "售后履约",
                 "current_review_count": 6, "affected_product_count": 1, "severity": "high"},
            ],
            "improving_issues": [
                {"label_code": "noise", "label_display": "噪音",
                 "current_review_count": 1, "affected_product_count": 1, "severity": "low"},
            ],
        },
        "competitive_opportunities": {
            "competitor_new_negative_reviews": [
                {"product_name": "Acme Grinder X", "review_count": 2,
                 "primary_problems": ["卡顿", "异响"]},
            ],
            "competitor_new_positive_reviews": [
                {"product_name": "Acme Grinder X", "highlight": "出肉细腻"},
            ],
        },
    }


def _mature_snapshot():
    return _base_snapshot()


def _mature_analytics(change_digest=None):
    return _base_analytics(
        report_semantics="incremental",
        change_digest=change_digest or _mature_change_digest_full(),
    )


# ──────────────────────────────────────────────────────────
# Tests (RED first)
# ──────────────────────────────────────────────────────────
def test_today_changes_hidden_in_bootstrap():
    """bootstrap: 单卡 + 旧空状态 ('问题变化 0 / 0') 必须消失."""
    html = render_attachment_html(
        snapshot=_bootstrap_snapshot(),
        analytics=_bootstrap_analytics(),
    )
    assert "首日基线已建档" in html
    # 旧 4-stat-card 中 "问题变化" + "0 / 0" 子串组合不应出现
    assert "问题变化 0 / 0" not in html


def test_today_changes_pyramid_in_mature_period():
    """mature: 三层金字塔 H3 标题齐全."""
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(),
    )
    assert "立即关注" in html
    assert "趋势变化" in html
    assert "反向利用" in html


def test_today_changes_immediate_attention_shows_own_negative():
    """own_new_negative_reviews 渲染产品名出现于立即关注区."""
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(),
    )
    assert ".75 HP" in html
    # 立即关注区先出现，确保产品名落在该区下方
    ia_idx = html.find("立即关注")
    name_idx = html.find(".75 HP")
    assert ia_idx >= 0 and name_idx > ia_idx, (
        f"expected '.75 HP' to appear after '立即关注' marker; "
        f"ia_idx={ia_idx}, name_idx={name_idx}"
    )


def _extract_changes_section(html: str) -> str:
    """Slice out the `<section id="tab-changes">…</section>` block."""
    start = html.find('<section id="tab-changes"')
    assert start >= 0, "could not locate <section id=\"tab-changes\"> in rendered HTML"
    end = html.find("</section>", start)
    assert end >= 0
    return html[start:end]


def test_today_changes_legacy_4_blocks_removed():
    """旧 4 区块标签 / CSS class 在 mature 模式的今日变化区中必须不出现.

    注: 仅在 `<section id="tab-changes">` 切片内断言, 避免误伤 overview 区合法
    出现的 '本次入库评论' KPI 标签等同字串.
    """
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(),
    )
    section = _extract_changes_section(html)

    # 旧 4 张 KPI 统计卡标签 (本次入库 / 自有新近差评 / 问题变化 / 状态变化)
    # 注: '问题变化' 旧 stat-card 已删, 但新 trend-changes 层并未使用该字串作 H3
    # (新 H3 = '📈 趋势变化'), 因此可一并断言消失.
    assert "本次入库" not in section, "旧 stat-card '本次入库' 应已删除"
    assert "自有新近差评" not in section, "旧 stat-card '自有新近差评' 应已删除"
    assert "状态变化" not in section, "旧 stat-card '状态变化' 应已删除"
    # 旧 change-grid 3 块标题
    assert "新近评论信号" not in section, "旧 change-block '新近评论信号' 应已删除"
    assert "产品状态变化" not in section, "旧 change-block '产品状态变化' 应已删除"
    # 旧 CSS class 引用（attachment 模板中已不再使用; CSS 文件本身可保留以兼容旧模板）
    assert "change-summary-grid" not in section
    assert "change-stat-card" not in section
    assert "change-block-header" not in section
    assert 'class="change-grid"' not in section
    assert "change-pill" not in section


def test_today_changes_empty_layers_hidden():
    """三层全空时, 三个 H3 标题都不应出现 (§4.2.4 '三块仅在内部非空时显示')."""
    empty_digest = {
        "view_state": "incremental",
        "summary": {},
        "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
        "product_changes": {"price_changes": [], "stock_changes": [], "rating_changes": []},
        "review_signals": {"fresh_negative_reviews": [], "fresh_competitor_positive_reviews": []},
        "warnings": {},
        "empty_state": {"enabled": False},
        "immediate_attention": {
            "own_new_negative_reviews": [], "own_rating_drops": [], "own_stock_alerts": [],
        },
        "trend_changes": {"new_issues": [], "escalated_issues": [], "improving_issues": []},
        "competitive_opportunities": {
            "competitor_new_negative_reviews": [], "competitor_new_positive_reviews": [],
        },
    }
    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(change_digest=empty_digest),
    )
    assert "立即关注" not in html
    assert "趋势变化" not in html
    assert "反向利用" not in html


# ──────────────────────────────────────────────────────────
# F011 §4.2.4 — trend_changes key-name contract (regression)
# ──────────────────────────────────────────────────────────
def _empty_analytics_for_digest(report_semantics="incremental"):
    return {
        "report_semantics": report_semantics,
        "kpis": {"untranslated_count": 0},
        "self": {"top_negative_clusters": []},
        "baseline_day_index": 1,
        "baseline_display_state": "initial",
    }


def test_trend_changes_keys_match_template_contract():
    """F011 §4.2.4 — change_digest.trend_changes must use *_issues key names
    that the daily_report_v3.html.j2 template reads."""
    from qbu_crawler.server.report_snapshot import build_change_digest

    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-25T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "reviews": [],
        "products": [],
    }
    digest = build_change_digest(snapshot, _empty_analytics_for_digest())
    tc = digest["trend_changes"]
    assert "new_issues" in tc
    assert "escalated_issues" in tc
    assert "improving_issues" in tc
    # Old names must NOT be present (would mask reintroduction of the bug)
    assert "new" not in tc
    assert "escalated" not in tc
    assert "improving" not in tc


def test_trend_changes_layer_renders_real_builder_output():
    """F011 §4.2.4 regression — Layer 2 must actually render builder data.

    Build a real change_digest via build_change_digest() with a populated
    `top_negative_clusters` (no previous_analytics → all clusters become "new").
    Then render the attachment HTML and assert the trend label appears in
    Layer 2 (📈 趋势变化). If the builder→template wire is broken (e.g.
    keys revert to bare `new/escalated/...`), the issue label disappears.
    """
    from qbu_crawler.server.report_snapshot import build_change_digest

    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-25T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "reviews": [],
        "products": [],
    }
    analytics_for_digest = {
        "report_semantics": "incremental",
        "kpis": {"untranslated_count": 0},
        "self": {
            "top_negative_clusters": [
                {
                    "label_code": "switch_failure",
                    "label_display": "开关失灵",
                    "review_count": 4,
                    "severity": "high",
                    "affected_product_count": 2,
                    "affected_products": ["P1", "P2"],
                },
            ],
        },
        "baseline_day_index": 5,
        "baseline_display_state": "stable",
    }
    digest = build_change_digest(snapshot, analytics_for_digest, previous_analytics=None)
    # Sanity: the cluster lands in trend_changes.new_issues (not bare "new")
    assert digest["trend_changes"]["new_issues"], (
        f"expected new_issues populated; got {digest['trend_changes']!r}"
    )

    html = render_attachment_html(
        snapshot=_mature_snapshot(),
        analytics=_mature_analytics(change_digest=digest),
    )
    assert "趋势变化" in html, "Layer 2 H3 must render when builder produced trend_changes"
    assert "开关失灵" in html, (
        "trend_changes label_display must reach the rendered HTML; "
        "missing it means builder→template key contract is broken"
    )
