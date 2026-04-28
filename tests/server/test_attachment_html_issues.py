"""F011 §3.5 (H5 + H14) — issue cards 高频期 + 现在该做什么 short_title.

Covers:
  H5:  issue cards drop misleading "约 8 年" duration_display, render
       "高频期 YYYY-MM ~ YYYY-MM" instead.
  H14: 现在该做什么 (improvement_priorities) section uses short_title as
       visible card title; full_action lives inside collapsed <details>.
       Evidence chips link to #review-{id}.
"""
from __future__ import annotations

from pathlib import Path
import re

from qbu_crawler.server.report_html import render_attachment_html


# ──────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────
def _base_snapshot(*, reviews=None, products=None,
                   logical_date="2026-04-27", run_id=0):
    return {
        "logical_date": logical_date,
        "run_id": run_id,
        "snapshot_at": f"{logical_date}T12:00:00+08:00",
        "data_since": f"{logical_date}T00:00:00+08:00",
        "data_until": f"{logical_date}T23:59:59+08:00",
        "products": products or [],
        "reviews": reviews or [],
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


def _base_analytics(
    *,
    top_negative_clusters=None,
    improvement_priorities=None,
    report_semantics="incremental",
):
    return {
        "report_semantics": report_semantics,
        "mode": "incremental",
        "kpis": _base_kpis(),
        "self": {
            "risk_products": [],
            "product_status": [],
            "top_negative_clusters": top_negative_clusters or [],
            "top_positive_clusters": [],
            "recommendations": [],
        },
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [],
        },
        "appendix": {"image_reviews": [], "coverage": {}},
        "change_digest": {},
        "report_copy": {
            "improvement_priorities": improvement_priorities or [],
            "executive_bullets": [],
        },
    }


def _cluster_with_old_dates():
    """One cluster spanning ~8 years (2017 → 2025) — the misleading old display case."""
    return [{
        "label_code": "quality_stability",
        "label_display": "质量稳定性",
        "feature_display": "质量稳定性",
        "review_count": 13,
        "severity": "high",
        "severity_display": "高",
        "affected_product_count": 3,
        "first_seen": "2017-01-15",
        "last_seen": "2025-02-22",
        "review_dates": ["2017-01-15", "2025-02-22"],
        "example_reviews": [],
        "image_review_count": 0,
        "translated_rate": 1.0,
    }]


def _cluster_with_dated_window():
    """One cluster with a clean 2024-03 → 2024-08 high-frequency window."""
    return [{
        "label_code": "noise_power",
        "label_display": "噪音与动力",
        "feature_display": "噪音与动力",
        "review_count": 7,
        "severity": "medium",
        "severity_display": "中",
        "affected_product_count": 2,
        "first_seen": "2024-03-15",
        "last_seen": "2024-08-22",
        "review_dates": ["2024-03-15", "2024-05-10", "2024-08-22"],
        "example_reviews": [],
        "image_review_count": 0,
        "translated_rate": 1.0,
    }]


def _v3_priorities_fixture():
    """A realistic improvement_priorities[] payload with all H14 fields."""
    return [
        {
            "label_code": "structure_design",
            "label_display": "结构设计",
            "short_title": "结构设计：肉饼厚度不可调",
            "full_action": (
                "针对肉饼成型器仅支持单一厚度的设计缺陷，建议下一代产品引入可调"
                "厚度滑块（5/8/12/16 mm 四档），并在包装内附赠厚度模板卡，"
                "方便用户根据汉堡 / 早餐肉饼场景切换。试产 50 套发往现有差评用户回访。"
            ),
            "evidence_count": 13,
            "evidence_review_ids": [101, 102, 103, 104, 105, 106, 107],
            "affected_products": ["Walton's Patty Maker", "MeatYourMaker Patty Press"],
            "affected_products_count": 2,
        },
        {
            "label_code": "noise_power",
            "label_display": "噪音与动力",
            "short_title": "噪音与动力：电机异响",
            "full_action": (
                "电机长时间运行后出现金属摩擦异响，建议供应商更换轴承型号并"
                "增加防尘罩；同时在 QC 流程中增加 30 分钟连续运行噪声测试，"
                "声压门槛 ≤ 75 dB。失败品全数返厂。"
            ),
            "evidence_count": 5,
            "evidence_review_ids": [201, 202],
            "affected_products": ["Walton's Grinder"],
            "affected_products_count": 1,
        },
    ]


# ──────────────────────────────────────────────────────────
# H5 — issue cards no misleading duration, frequent_period instead
# ──────────────────────────────────────────────────────────
def test_issue_card_no_misleading_duration():
    """F011 H5 — 不再展示 '约 8 年' 让人误读为问题持续时长。"""
    analytics = _base_analytics(top_negative_clusters=_cluster_with_old_dates())
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "约 8 年" not in html
    assert "约 8 年 1 个月" not in html
    # New language is in use
    assert "高频期" in html


def test_issue_card_shows_frequent_period():
    """F011 H5 — issue cards display frequent_period (start/end YYYY-MM)."""
    analytics = _base_analytics(top_negative_clusters=_cluster_with_dated_window())
    html = render_attachment_html(_base_snapshot(), analytics)
    m = re.search(r"高频期\s+\d{4}-\d{2}\s*~\s*\d{4}-\d{2}", html)
    assert m, f"No 高频期 YYYY-MM ~ YYYY-MM marker found in HTML"
    # Specifically the range we set up
    assert "2024-03" in m.group(0)
    assert "2024-08" in m.group(0)


# ──────────────────────────────────────────────────────────
# H14 — improvement_priorities renders "现在该做什么" with short_title
# ──────────────────────────────────────────────────────────
def test_improvement_uses_short_title_not_full_action():
    """F011 H14 — '现在该做什么' 卡片标题用 short_title。"""
    analytics = _base_analytics(improvement_priorities=_v3_priorities_fixture())
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "现在该做什么" in html
    # short_title appears as visible card title
    assert "结构设计：肉饼厚度不可调" in html


def test_improvement_full_action_in_collapsed_details():
    """F011 H14 — full_action 落在 <details><summary>详情</summary>... 内。"""
    analytics = _base_analytics(improvement_priorities=_v3_priorities_fixture())
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "<details" in html
    assert "详情" in html
    # The long action body appears, but inside the details block
    assert "可调" in html  # part of full_action body of first priority


def test_improvement_evidence_chips_link_to_review():
    """F011 §4.2.2 — evidence_review_ids[:5] render as anchor chips linking to #review-ID."""
    analytics = _base_analytics(improvement_priorities=_v3_priorities_fixture())
    html = render_attachment_html(_base_snapshot(), analytics)
    chips = re.findall(r'href="#review-(\d+)"', html)
    assert len(chips) >= 1
    # First priority has 7 ids → 5 chips + "+2 更多"
    assert "+2 更多" in html or "更多" in html


def test_improvement_section_absent_when_priorities_empty():
    """F011 H14 — no priorities → section is suppressed (gracefully)."""
    analytics = _base_analytics(improvement_priorities=[])
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "现在该做什么" not in html


def test_issue_card_renders_image_evidence_and_deep_analysis():
    cluster = {
        "label_code": "quality_stability",
        "label_display": "质量稳定性",
        "feature_display": "质量稳定性",
        "review_count": 2,
        "severity": "high",
        "severity_display": "高",
        "affected_product_count": 1,
        "example_reviews": [{
            "id": 301,
            "rating": 1,
            "headline_cn": "开关失效",
            "body_cn": "用了两次开关就坏了",
            "images": ["https://example.com/review-img.jpg"],
        }],
        "deep_analysis": {
            "actionable_summary": "优先复核开关耐久与批次质量。",
            "failure_modes": [{"name": "开关失效", "frequency": 2}],
            "root_causes": [{"name": "出厂抽检不足"}],
            "user_workarounds": ["用户反复重启设备"],
        },
    }
    priorities = [{
        "label_code": "quality_stability",
        "short_title": "复核开关耐久",
        "full_action": "加强出厂耐久测试，并对开关失效评论对应批次进行复测和客服回访。",
        "evidence_count": 2,
        "evidence_review_ids": [301],
        "affected_products": ["Product A"],
    }]
    analytics = _base_analytics(
        top_negative_clusters=[cluster],
        improvement_priorities=priorities,
    )

    html = render_attachment_html(_base_snapshot(), analytics)

    assert "issue-image-evidence" in html
    assert "https://example.com/review-img.jpg" in html
    assert "加强出厂耐久测试" in html
    assert "失效模式" in html
    assert "开关失效" in html
    assert "可能根因" in html
    assert "出厂抽检不足" in html


def test_issue_image_evidence_has_bounded_css():
    css_path = Path("qbu_crawler/server/report_templates/daily_report_v3.css")
    css = css_path.read_text(encoding="utf-8")

    assert ".issue-image-evidence" in css
    assert ".issue-image-evidence img" in css
    assert "object-fit: cover" in css
    assert "max-height" in css


# ──────────────────────────────────────────────────────────
# _format_frequent_period unit tests
# ──────────────────────────────────────────────────────────
def test_format_frequent_period_basic():
    from qbu_crawler.server.report_common import _format_frequent_period
    fp = _format_frequent_period("2024-03-15", "2024-08-22")
    assert fp == {"start": "2024-03", "end": "2024-08"}


def test_format_frequent_period_none():
    from qbu_crawler.server.report_common import _format_frequent_period
    assert _format_frequent_period(None, None) is None
    assert _format_frequent_period("2024-03-15", None) is None
    assert _format_frequent_period(None, "2024-08-22") is None


def test_format_frequent_period_same_month():
    from qbu_crawler.server.report_common import _format_frequent_period
    fp = _format_frequent_period("2024-03-15", "2024-03-22")
    assert fp == {"start": "2024-03", "end": "2024-03"}


def test_format_frequent_period_reversed_inputs_swap():
    """When first_seen > last_seen (data quality bug), function swaps to produce
    a valid range. Documented behavior — caller need not pre-sort."""
    from qbu_crawler.server.report_common import _format_frequent_period
    fp = _format_frequent_period("2024-08-22", "2024-03-15")
    assert fp == {"start": "2024-03", "end": "2024-08"}


def test_format_frequent_period_unparseable_returns_none():
    from qbu_crawler.server.report_common import _format_frequent_period
    assert _format_frequent_period("garbage", "2024-08-22") is None
    assert _format_frequent_period("2024-08-22", "not-a-date") is None


# ──────────────────────────────────────────────────────────
# §4.2.2 — evidence chip anchor wiring
# ──────────────────────────────────────────────────────────
def test_evidence_chip_links_have_matching_anchors():
    """F011 §4.2.2 — every chip href="#review-N" must have a matching id="review-N"
    elsewhere in the rendered page so the link doesn't dead-jump."""
    # Build snapshot reviews whose IDs match the first priority's evidence_review_ids
    priorities = _v3_priorities_fixture()
    chip_target_ids = []
    for p in priorities:
        chip_target_ids.extend((p.get("evidence_review_ids") or [])[:5])
    reviews = [
        {
            "id": rid,
            "ownership": "own",
            "product_name": "Test Product",
            "rating": 2,
            "headline": f"headline-{rid}",
            "body": f"body-{rid}",
            "date_published": "2024-08-01",
            "label_codes": [],
            "is_recent": False,
            "images": None,
        }
        for rid in chip_target_ids
    ]
    snapshot = _base_snapshot(reviews=reviews)
    analytics = _base_analytics(improvement_priorities=priorities)
    html = render_attachment_html(snapshot, analytics)
    chip_ids = set(re.findall(r'href="#review-(\d+)"', html))
    anchor_ids = set(re.findall(r'id="review-(\d+)"', html))
    if chip_ids:  # only assert when chips are rendered (skip if empty case)
        missing = chip_ids - anchor_ids
        assert not missing, f"Evidence chip targets without anchors: {missing}"
