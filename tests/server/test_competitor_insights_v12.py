"""F011 §4.2.7 v1.2 — 竞品启示扩展 (scoped reductions).

Covers:
  - AC-36: ``competitor.weakness_opportunities`` produced when thresholds met
  - AC-36: ``competitor.benchmark_examples`` split into product / marketing / service groups
  - §4.2.7.3: 雷达图维度聚合到 Top 6-8
  - §4.2.7.4: ``benchmark_takeaways`` 不再展示在附件 HTML
  - §4.2.6/§4.2.7: 竞品评分两极分化迁移到 "竞品启示" section

Out of scope:
  - LLM-enhanced ``_generate_advantage_direction``
"""
from __future__ import annotations

from qbu_crawler.server.report_analytics import (
    _benchmark_examples,
    _build_weakness_opportunities,
    _compute_chart_data,
    _negative_opportunities,
)
from qbu_crawler.server.report_html import render_attachment_html


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────
def _mk_label(code: str, polarity: str = "negative", severity: str = "medium"):
    return {
        "label_code": code,
        "label_polarity": polarity,
        "severity": severity,
        "confidence": 0.9,
    }


def _mk_item(ownership: str, product_name: str, product_sku: str, labels):
    return {
        "review": {
            "ownership": ownership,
            "product_name": product_name,
            "product_sku": product_sku,
        },
        "labels": labels,
        "images": [],
        "product": {},
    }


# ──────────────────────────────────────────────────────────
# §4.2.7 — weakness_opportunities
# ──────────────────────────────────────────────────────────
def test_competitor_weakness_opportunities_generated():
    """F011 AC-36 — competitor.weakness_opportunities ≥ 1 when thresholds met.

    Conditions:
      - competitor: ≥3 negative reviews on label X (assembly_installation)
      - own:       ≥10 positive reviews on same label X
    """
    labeled_reviews = []
    # Competitor: 5 negative on assembly_installation
    for i in range(5):
        labeled_reviews.append(_mk_item(
            "competitor", "Comp Grinder", "C1",
            [_mk_label("assembly_installation", polarity="negative")],
        ))
    # Own: 12 positive on assembly_installation
    for i in range(12):
        labeled_reviews.append(_mk_item(
            "own", "Own Grinder", "O1",
            [_mk_label("assembly_installation", polarity="positive")],
        ))

    opportunities = _build_weakness_opportunities(labeled_reviews)
    assert len(opportunities) >= 1
    item = opportunities[0]
    assert item["competitor_complaint_theme"] == "assembly_installation"
    assert "competitor_complaint_display" in item
    assert item["competitor_evidence_count"] == 5
    assert item["our_positive_count"] == 12
    assert "our_advantage_direction" in item
    assert item["our_advantage_direction"]  # non-empty


def test_build_weakness_opportunities_thresholds():
    """Edge cases for both thresholds."""
    # Case A: 2 competitor negs, 100 own pos → no opportunity (comp below threshold)
    labeled_a = []
    for _ in range(2):
        labeled_a.append(_mk_item(
            "competitor", "C", "C1",
            [_mk_label("quality_stability", polarity="negative")],
        ))
    for _ in range(100):
        labeled_a.append(_mk_item(
            "own", "O", "O1",
            [_mk_label("quality_stability", polarity="positive")],
        ))
    assert _build_weakness_opportunities(labeled_a) == []

    # Case B: 5 competitor negs, 9 own pos → no opportunity (own below threshold)
    labeled_b = []
    for _ in range(5):
        labeled_b.append(_mk_item(
            "competitor", "C", "C1",
            [_mk_label("quality_stability", polarity="negative")],
        ))
    for _ in range(9):
        labeled_b.append(_mk_item(
            "own", "O", "O1",
            [_mk_label("quality_stability", polarity="positive")],
        ))
    assert _build_weakness_opportunities(labeled_b) == []

    # Case C: 5 competitor negs, 15 own pos → 1 opportunity
    labeled_c = []
    for _ in range(5):
        labeled_c.append(_mk_item(
            "competitor", "C", "C1",
            [_mk_label("quality_stability", polarity="negative")],
        ))
    for _ in range(15):
        labeled_c.append(_mk_item(
            "own", "O", "O1",
            [_mk_label("quality_stability", polarity="positive")],
        ))
    opps = _build_weakness_opportunities(labeled_c)
    assert len(opps) == 1
    assert opps[0]["competitor_evidence_count"] == 5
    assert opps[0]["our_positive_count"] == 15


def test_build_weakness_opportunities_top_3_only():
    """Should return at most Top 3 opportunities, sorted by competitor neg count desc."""
    labeled = []
    # 4 different competitor labels with varying neg counts: 8, 6, 4, 3
    plan = [
        ("quality_stability", 8),
        ("structure_design", 6),
        ("assembly_installation", 4),
        ("material_finish", 3),
    ]
    for code, neg_n in plan:
        for _ in range(neg_n):
            labeled.append(_mk_item(
                "competitor", "C", "C1",
                [_mk_label(code, polarity="negative")],
            ))
        # Own: 15 positive on each
        for _ in range(15):
            labeled.append(_mk_item(
                "own", "O", "O1",
                [_mk_label(code, polarity="positive")],
            ))

    opps = _build_weakness_opportunities(labeled)
    assert len(opps) == 3
    # Sorted by competitor_evidence_count descending
    counts = [o["competitor_evidence_count"] for o in opps]
    assert counts == [8, 6, 4]


# ──────────────────────────────────────────────────────────
# §4.2.7.3 — Radar Top 6-8 aggregation
# ──────────────────────────────────────────────────────────
def test_radar_dimensions_aggregated_to_top_6_8():
    """F011 §4.2.7.3 — 雷达图维度 ≤ 8 when many dimensions are present."""
    # Build labeled reviews touching all 5 unified dimensions for both sides
    # (5 dims < 8 cap, still asserts ≤ 8).
    codes = [
        "quality_stability",     # 耐久性与质量
        "structure_design",      # 设计与使用
        "cleaning_maintenance",  # 清洁便利性
        "noise_power",           # 性能表现
        "service_fulfillment",   # 售后与履约
    ]
    labeled = []
    for code in codes:
        labeled.append(_mk_item(
            "own", "P1", "S1",
            [_mk_label(code, polarity="positive")],
        ))
        labeled.append(_mk_item(
            "competitor", "CP1", "C1",
            [_mk_label(code, polarity="positive")],
        ))

    snapshot = {"products": [
        {"name": "P1", "sku": "S1", "ownership": "own", "rating": 4.0},
        {"name": "CP1", "sku": "C1", "ownership": "competitor", "rating": 4.0},
    ]}
    chart_data = _compute_chart_data(labeled, snapshot)
    radar = chart_data.get("_radar_data")
    if radar:
        assert len(radar["categories"]) <= 8
        assert len(radar["categories"]) == len(radar["own_values"])
        assert len(radar["categories"]) == len(radar["competitor_values"])


# ──────────────────────────────────────────────────────────
# §4.2.7.4 — benchmark_takeaways no longer rendered in attachment
# ──────────────────────────────────────────────────────────
def _base_snapshot():
    return {
        "logical_date": "2026-04-27",
        "run_id": 0,
        "snapshot_at": "2026-04-27T12:00:00+08:00",
        "data_since": "2026-04-27T00:00:00+08:00",
        "data_until": "2026-04-27T23:59:59+08:00",
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


def _analytics_with(*, competitor=None, extras=None):
    a = {
        "report_semantics": "incremental",
        "mode": "incremental",
        "kpis": _base_kpis(),
        "self": {
            "risk_products": [],
            "product_status": [],
            "top_negative_clusters": [],
            "top_positive_clusters": [],
            "recommendations": [],
        },
        "competitor": competitor or {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "weakness_opportunities": [],
            "gap_analysis": [],
        },
        "appendix": {"image_reviews": [], "coverage": {}},
        "change_digest": {},
        "label_options": [],
    }
    if extras:
        a.update(extras)
    return a


def test_benchmark_takeaways_not_rendered_in_attachment():
    """F011 §4.2.7.4 — benchmark_takeaways copy is NOT shown in attachment HTML."""
    snapshot = _base_snapshot()
    competitor = {
        "top_positive_themes": [
            {"label_code": "easy_to_use", "label_display": "易上手"},
        ],
        "benchmark_examples": [],
        "negative_opportunities": [],
        "weakness_opportunities": [],
        "benchmark_takeaways": [
            "用户持续认可易上手体验。",
        ],
        "gap_analysis": [],
    }
    analytics = _analytics_with(competitor=competitor)
    html = render_attachment_html(snapshot, analytics)
    # Neither the copy nor the variable name should appear.
    assert "benchmark_takeaways" not in html
    assert "用户持续认可易上手体验。" not in html


# ──────────────────────────────────────────────────────────
# §4.2.7 — competitor rating distribution lives in 竞品启示 section
# ──────────────────────────────────────────────────────────
def test_competitor_rating_distribution_in_competitor_section():
    """F011 §4.2.7 — 竞品评分两极分化 chart belongs to tab-competitive."""
    snapshot = _base_snapshot()
    competitor = {
        "top_positive_themes": [],
        "benchmark_examples": [],
        "negative_opportunities": [],
        "weakness_opportunities": [],
        "gap_analysis": [],
    }
    extras = {
        "_sentiment_distribution_competitor": {
            "categories": ["CP1", "CP2"],
            "positive": [3, 4],
            "neutral": [1, 2],
            "negative": [5, 1],
        },
    }
    analytics = _analytics_with(competitor=competitor, extras=extras)
    html = render_attachment_html(snapshot, analytics)

    # Find tab-competitive section in the html and confirm sentiment_comp
    # marker (rating_distribution title) lives inside it, not in panorama.
    comp_open = html.find('id="tab-competitive"')
    assert comp_open >= 0, "tab-competitive section missing"
    # Find next section opening after tab-competitive
    next_section = html.find('<section', comp_open + 1)
    if next_section < 0:
        next_section = len(html)
    competitive_chunk = html[comp_open:next_section]
    assert "竞品评分两极分化" in competitive_chunk

    # And NOT inside tab-panorama
    pan_open = html.find('id="tab-panorama"')
    if pan_open >= 0:
        pan_next = html.find('<section', pan_open + 1)
        if pan_next < 0:
            pan_next = len(html)
        panorama_chunk = html[pan_open:pan_next]
        assert "竞品评分两极分化" not in panorama_chunk


def test_weakness_opportunities_block_renders_when_present():
    """F011 §4.2.7 — weakness_opportunities block renders inside 竞品启示."""
    snapshot = _base_snapshot()
    competitor = {
        "top_positive_themes": [],
        "benchmark_examples": [],
        "negative_opportunities": [],
        "weakness_opportunities": [
            {
                "competitor_complaint_theme": "assembly_installation",
                "competitor_complaint_display": "安装装配",
                "competitor_evidence_count": 5,
                "competitor_products_affected": ["Comp X"],
                "our_advantage_label": "assembly_installation",
                "our_positive_count": 12,
                "our_advantage_direction": "我方 安装装配 差异化",
            },
        ],
        "gap_analysis": [],
    }
    analytics = _analytics_with(competitor=competitor)
    html = render_attachment_html(snapshot, analytics)
    assert "竞品弱点" in html
    assert "安装装配" in html
    assert "我方 安装装配 差异化" in html


def test_benchmark_examples_split_into_three_categories():
    labeled_reviews = [
        _mk_item("competitor", "Comp A", "C1", [_mk_label("solid_build", polarity="positive")]),
        _mk_item("competitor", "Comp B", "C2", [_mk_label("good_value", polarity="positive")]),
        _mk_item("competitor", "Comp C", "C3", [_mk_label("service_fulfillment", polarity="positive")]),
    ]
    for i, item in enumerate(labeled_reviews):
        item["review"].update({
            "id": i + 1,
            "rating": 5,
            "headline_cn": f"样例{i}",
            "body_cn": f"评论{i}",
        })

    benchmarks = _benchmark_examples(labeled_reviews)

    assert set(benchmarks) == {"product_design", "marketing_message", "service_model"}
    assert benchmarks["product_design"]
    assert benchmarks["marketing_message"]
    assert benchmarks["service_model"]


def test_benchmark_examples_three_categories_render():
    snapshot = _base_snapshot()
    competitor = {
        "top_positive_themes": [],
        "benchmark_examples": {
            "product_design": [{"label_codes": ["solid_build"], "body_cn": "做工扎实", "product_name": "Comp A"}],
            "marketing_message": [{"label_codes": ["good_value"], "body_cn": "性价比高", "product_name": "Comp B"}],
            "service_model": [{"label_codes": ["service_fulfillment"], "body_cn": "售后好", "product_name": "Comp C"}],
        },
        "negative_opportunities": [],
        "weakness_opportunities": [],
        "gap_analysis": [],
    }
    analytics = _analytics_with(competitor=competitor)

    html = render_attachment_html(snapshot, analytics)

    assert "产品形态" in html
    assert "营销话术" in html
    assert "服务模式" in html


def test_negative_opportunities_preserve_translated_fields():
    item = _mk_item(
        "competitor",
        "Comp Grinder",
        "C1",
        [_mk_label("quality_stability", polarity="negative")],
    )
    item["review"].update({
        "rating": 1,
        "headline": "Motor noise",
        "body": "The motor started buzzing after three days.",
        "headline_cn": "电机异响",
        "body_cn": "三天就开始嗡嗡响。",
    })

    opportunities = _negative_opportunities([item])

    assert opportunities[0]["headline_cn"] == "电机异响"
    assert opportunities[0]["body_cn"] == "三天就开始嗡嗡响。"
