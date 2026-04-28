"""F011 §4.1 — email_full.html.j2 重构测试。

新模板布局:
  1. 标题 + 副标题 (own/competitor/ingested counts)
  2. KPI 灯条 4 张:
     - 总体口碑 (health_index, 阈值 ≥85 绿 / [70,85) 黄 / <70 红)
     - 好评率 (own_positive_review_rows / own_review_rows)
     - 差评率 (own_negative_review_rate)
     - 需关注产品 = count(product_status[].status_lamp in {red,yellow})
  3. Hero headline + executive_bullets[0:3]
  4. Top 3 improvement_priorities (short_title + affected_products_count)
  5. 自有产品状态 (analytics.self.product_status[])
  6. 附件链接 (HTML / Excel)

删除 (必须不出现):
  - 覆盖率 / 本次入库 / estimated_dates / backfill_dominant
  - 累计巨幅 health_index hero block / 4 张范围卡 / 高风险产品阈值数字

客户端兼容:
  max-width 640px / table 布局 / inline CSS / 无 JS / 无外部 CSS。
"""
from __future__ import annotations

import pytest

from qbu_crawler.server.report import render_email_full


def _mock_snapshot(logical_date="2026-04-27"):
    return {
        "logical_date": logical_date,
        "data_since": f"{logical_date}T00:00:00+08:00",
        "data_until": f"{logical_date}T23:59:59+08:00",
        "run_id": 0,  # avoid load_previous_report_context DB hit
        "products": [],
        "reviews": [],
    }


def _mock_analytics(
    health_index=96.2,
    own_positive=180,
    own_total=190,
    own_negative_rate=0.024,
    own_product_count=5,
    competitor_product_count=3,
    ingested_review_rows=42,
    bullets=None,
    priorities=None,
    product_status=None,
    hero_headline="本期口碑稳健，关注 1 款产品的售后履约。",
):
    return {
        "kpis": {
            "health_index": health_index,
            "own_positive_review_rows": own_positive,
            "own_review_rows": own_total,
            "own_negative_review_rate": own_negative_rate,
            "own_negative_review_rate_display": f"{own_negative_rate * 100:.1f}%",
            "own_product_count": own_product_count,
            "competitor_product_count": competitor_product_count,
            "ingested_review_rows": ingested_review_rows,
        },
        "self": {
            "risk_products": [],
            "top_negative_clusters": [],
            "product_status": product_status if product_status is not None else [],
        },
        "report_copy": {
            "hero_headline": hero_headline,
            "executive_bullets": bullets if bullets is not None else [
                "自有评价质量保持稳健，差评率 2.4%。",
                ".75 HP 售后开关失灵问题需要立即响应。",
                "竞品在易用性上获得新近正面反馈，建议跟进。",
            ],
            "improvement_priorities": priorities if priorities is not None else [
                {
                    "label_code": "structure",
                    "label_display": "结构设计",
                    "short_title": "肉饼厚度不可调",
                    "full_action": "增加可调节模具档位",
                    "evidence_count": 8,
                    "evidence_review_ids": [],
                    "affected_products": ["A", "B", "C"],
                    "affected_products_count": 3,
                },
                {
                    "label_code": "after_sales",
                    "label_display": "售后履约",
                    "short_title": "开关失灵",
                    "full_action": "建立售后快速响应通道",
                    "evidence_count": 4,
                    "evidence_review_ids": [],
                    "affected_products": [".75 HP"],
                    "affected_products_count": 1,
                },
                {
                    "label_code": "quality",
                    "label_display": "质量稳定",
                    "short_title": "金属碎屑",
                    "full_action": "完善出厂清洁与抽检",
                    "evidence_count": 5,
                    "evidence_review_ids": [],
                    "affected_products": ["X", "Y"],
                    "affected_products_count": 2,
                },
            ],
        },
    }


# ──────────────────────────────────────────────────────────
# Test 1: 4 KPI lamps present
# ──────────────────────────────────────────────────────────
def test_email_full_has_4_kpi_lights():
    """F011 §4.1 — 4 张语义灯（总体口碑 / 好评率 / 差评率 / 需关注产品）."""
    html = render_email_full(snapshot=_mock_snapshot(), analytics=_mock_analytics())
    assert "总体口碑" in html
    assert "好评率" in html
    assert "差评率" in html
    assert "需关注产品" in html


# ──────────────────────────────────────────────────────────
# Test 2: health lamp threshold edges
# ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "score,expected_class",
    [
        (85.0, "lamp-green"),     # 边界：85 → 绿
        (84.99, "lamp-yellow"),   # 边界：84.99 → 黄
        (70.0, "lamp-yellow"),    # 边界：70 → 黄
        (69.99, "lamp-red"),      # 边界：69.99 → 红
        (96.2, "lamp-green"),
        (50.0, "lamp-red"),
    ],
)
def test_kpi_health_lamp_thresholds(score, expected_class):
    """v1.1 / Bug 3 — 健康灯阈值开闭区间明确：≥85 绿 / [70,85) 黄 / <70 红."""
    html = render_email_full(
        snapshot=_mock_snapshot(),
        analytics=_mock_analytics(health_index=score),
    )
    assert expected_class in html, (
        f"score={score} expected lamp class {expected_class!r} in html"
    )


# ──────────────────────────────────────────────────────────
# Test 3: KPI 4 uses lamp count, not hardcoded risk_score
# ──────────────────────────────────────────────────────────
def test_kpi_4_uses_lamp_count_not_hardcoded_25():
    """v1.1 / I2 — 需关注产品数 = 黄+红灯产品数（不再硬编码 risk_score≥25）."""
    product_status = [
        {"product_name": "A", "status_lamp": "yellow", "primary_concern": "开关失灵"},
        {"product_name": "B", "status_lamp": "red", "primary_concern": "金属碎屑"},
        {"product_name": "C", "status_lamp": "green", "primary_concern": ""},
        {"product_name": "D", "status_lamp": "gray", "primary_concern": ""},
    ]
    html = render_email_full(
        snapshot=_mock_snapshot(),
        analytics=_mock_analytics(product_status=product_status),
    )
    assert "需关注产品" in html
    # accept "需关注产品  2 个" / "需关注产品 2 个" / "需关注产品 2"
    assert "2 个" in html or "需关注产品 2" in html, (
        f"expected '需关注产品 2 个' substring in html, got snippet:\n"
        f"{html[html.find('需关注产品'):html.find('需关注产品') + 80] if '需关注产品' in html else '(missing)'}"
    )


def test_kpi_4_prefers_attention_count_from_kpis():
    """邮件必须消费统一 KPI，不能在模板里重新算出另一个关注数。"""
    analytics = _mock_analytics(
        product_status=[
            {"product_name": "A", "status_lamp": "green", "primary_concern": ""},
            {"product_name": "B", "status_lamp": "green", "primary_concern": ""},
        ],
    )
    analytics["kpis"]["attention_product_count"] = 2

    html = render_email_full(snapshot=_mock_snapshot(), analytics=analytics)

    assert "需关注产品 2" in html


def test_kpi_4_zero_when_product_status_missing():
    """product_status 缺失时不能崩溃，需关注数为 0."""
    html = render_email_full(
        snapshot=_mock_snapshot(),
        analytics=_mock_analytics(product_status=[]),
    )
    assert "需关注产品" in html
    assert "0 个" in html or "需关注产品 0" in html


# ──────────────────────────────────────────────────────────
# Test 4: no engineering signals
# ──────────────────────────────────────────────────────────
def test_email_full_no_engineering_signals():
    """删除内部信号：覆盖率 / 本次入库 / estimated_dates / backfill_dominant."""
    analytics = _mock_analytics(
        bullets=[
            "基线样本 594 条，其中近30天样本 5 条。",
            "自有产品差评率 3.8%。",
        ]
    )
    html = render_email_full(snapshot=_mock_snapshot(), analytics=analytics)
    assert "覆盖率" not in html
    assert "本次入库" not in html
    assert "历史补采" not in html
    assert "estimated_dates" not in html
    assert "backfill_dominant" not in html


# ──────────────────────────────────────────────────────────
# Test 5: size budget
# ──────────────────────────────────────────────────────────
def test_email_full_size_under_50kb():
    """模板 + 内联 CSS 总大小不超过 50 KB."""
    html = render_email_full(snapshot=_mock_snapshot(), analytics=_mock_analytics())
    size = len(html.encode("utf-8"))
    assert size < 50 * 1024, f"html size {size} bytes exceeds 50KB budget"


# ──────────────────────────────────────────────────────────
# Test 6 (review I-3): None-safe report_copy extraction
# ──────────────────────────────────────────────────────────
def test_email_full_handles_none_report_copy():
    """analytics["report_copy"] = None (e.g. JSON null) must not crash.

    Hero / executive_bullets / improvement_priorities sections should render
    gracefully empty rather than raising AttributeError on `.get` against None.
    """
    analytics = {
        "report_copy": None,
        "kpis": {
            "health_index": 96.2,
            "own_positive_review_rows": 180,
            "own_review_rows": 190,
            "own_negative_review_rate": 0.024,
            "own_negative_review_rate_display": "2.4%",
            "own_product_count": 5,
            "competitor_product_count": 3,
            "ingested_review_rows": 42,
        },
        "self": {
            "risk_products": [],
            "top_negative_clusters": [],
            "product_status": [],
        },
    }
    # Must not raise.
    html = render_email_full(snapshot=_mock_snapshot(), analytics=analytics)
    # KPI lights still rendered.
    assert "总体口碑" in html
    # Hero headline area must render without injecting dummy text.
    # `_hero` resolves to "" when report_copy is missing/None — so the
    # mock executive bullets text shouldn't appear.
    assert "本期口碑稳健" not in html
    assert ".75 HP 售后开关失灵" not in html
