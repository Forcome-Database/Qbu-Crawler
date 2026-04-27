"""F011 §4.2.3 + §4.2.6 + H17 — 自有产品状态灯 + 全景数据筛选 + 模板健壮性。

Covers:
  §4.2.3: 自有产品状态：灯 + 一句原因，详细风险因子悬停查看
  §4.2.6: 全景数据：561 评论嵌入保留 + 5 个客户端筛选器
  H17:    模板按 columns key 输出表格，不依赖 dict 顺序
"""
from __future__ import annotations

from qbu_crawler.server.report_html import render_attachment_html


# ──────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────
def _base_snapshot(*, reviews=None, products=None, logical_date="2026-04-27", run_id=0):
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
    product_status=None,
    label_options=None,
    risk_products=None,
    report_semantics="incremental",
):
    return {
        "report_semantics": report_semantics,
        "mode": "incremental",
        "kpis": _base_kpis(),
        "self": {
            "risk_products": risk_products or [],
            "product_status": product_status or [],
            "top_negative_clusters": [],
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
        "label_options": label_options or [],
    }


# ──────────────────────────────────────────────────────────
# §4.2.3 — Product status lamps
# ──────────────────────────────────────────────────────────
def test_product_status_uses_lights_not_numbers():
    """F011 §4.2.3 — 自有产品状态灯+一句原因，不再展示 risk_score 数字为主显内容。

    risk_score may appear in tooltip / hover-only column, but primary display is lamp + label.
    """
    product_status = [
        {
            "product_name": "Walton's Grinder",
            "product_sku": "W22",
            "status_lamp": "yellow",
            "status_label": "需关注",
            "primary_concern": "开关失灵 + 售后失联",
            "risk_score": 32.6,
            "risk_factors": {
                "neg_rate": 0.20,
                "severity": 0.50,
                "evidence": 0.10,
                "recency": 0.40,
                "volume_sig": 0.30,
            },
            "near_high_risk": True,
        },
    ]
    analytics = _base_analytics(product_status=product_status)
    html = render_attachment_html(_base_snapshot(), analytics)

    # Lamp emoji or status class
    assert ("🟡" in html) or ("yellow" in html)
    assert "需关注" in html
    # risk_score appears (in hover/tooltip area)
    assert "32.6" in html


def test_product_status_returns_all_own_products_including_healthy():
    """All own products appear with status_lamp regardless of risk_score (incl. green/gray)."""
    product_status = [
        {"product_name": "Red Product", "product_sku": "R1",
         "status_lamp": "red", "status_label": "高风险",
         "primary_concern": "金属碎屑", "risk_score": 60.0,
         "risk_factors": {}, "near_high_risk": False},
        {"product_name": "Yellow Product", "product_sku": "Y1",
         "status_lamp": "yellow", "status_label": "需关注",
         "primary_concern": "异响", "risk_score": 30.0,
         "risk_factors": {}, "near_high_risk": True},
        {"product_name": "Green One", "product_sku": "G1",
         "status_lamp": "green", "status_label": "健康",
         "primary_concern": "", "risk_score": 5.0,
         "risk_factors": {}, "near_high_risk": False},
        {"product_name": "Green Two", "product_sku": "G2",
         "status_lamp": "green", "status_label": "健康",
         "primary_concern": "", "risk_score": 0.0,
         "risk_factors": None, "near_high_risk": False},
        {"product_name": "Gray No-Data", "product_sku": "X1",
         "status_lamp": "gray", "status_label": "无数据",
         "primary_concern": "", "risk_score": 0.0,
         "risk_factors": None, "near_high_risk": False},
    ]
    analytics = _base_analytics(product_status=product_status)
    html = render_attachment_html(_base_snapshot(), analytics)
    for name in ("Red Product", "Yellow Product", "Green One", "Green Two", "Gray No-Data"):
        assert name in html, f"product {name} missing from rendered html"


def test_product_status_lamp_thresholds():
    """F011 §4.2.3 — _product_status() data-builder lamp threshold rules:
        🔴 red:    risk_score >= HIGH_RISK_THRESHOLD (35)
        🟡 yellow: 0.85*HIGH_RISK_THRESHOLD <= score < HIGH_RISK_THRESHOLD OR has any negative
        🟢 green:  no negative AND risk_score < 29.75
        ⚪ gray:   ingested_reviews == 0
    """
    from qbu_crawler.server.report_analytics import _product_status

    # Build labeled_reviews fixture: 4 own SKUs, varying negative profiles
    labeled = [
        # SKU 'R' — 8 critical negatives w/ images → red (high risk)
        *[{
            "review": {"product_sku": "R", "product_name": "Red Prod",
                       "ownership": "own", "rating": 1, "date_published": "2026-04-20"},
            "labels": [{"label_code": "quality_stability",
                        "label_polarity": "negative", "severity": "critical"}],
            "product": {}, "images": True,
        } for _ in range(8)],
        # SKU 'Y' — 1 mild negative + 19 positives → low risk_score but has_negative → yellow
        {
            "review": {"product_sku": "Y", "product_name": "Yellow Prod",
                       "ownership": "own", "rating": 2, "date_published": "2026-04-20"},
            "labels": [{"label_code": "noise_power",
                        "label_polarity": "negative", "severity": "low"}],
            "product": {}, "images": False,
        },
        *[{
            "review": {"product_sku": "Y", "product_name": "Yellow Prod",
                       "ownership": "own", "rating": 5, "date_published": "2026-04-20"},
            "labels": [{"label_code": "good_value",
                        "label_polarity": "positive", "severity": "low"}],
            "product": {}, "images": False,
        } for _ in range(19)],
        # SKU 'G' — only positives → green
        *[{
            "review": {"product_sku": "G", "product_name": "Green Prod",
                       "ownership": "own", "rating": 5, "date_published": "2026-04-20"},
            "labels": [{"label_code": "good_value",
                        "label_polarity": "positive", "severity": "low"}],
            "product": {}, "images": False,
        } for _ in range(3)],
    ]
    snapshot_products = [
        {"sku": "R", "review_count": 100},
        {"sku": "Y", "review_count": 100},
        {"sku": "G", "review_count": 100},
        # SKU 'X' has zero ingested → gray
        {"sku": "X", "name": "Gray Prod", "review_count": 100, "ownership": "own"},
    ]
    out = _product_status(labeled, snapshot_products=snapshot_products,
                          logical_date="2026-04-27")
    by_sku = {p["product_sku"]: p for p in out}

    assert by_sku["R"]["status_lamp"] == "red"
    assert by_sku["Y"]["status_lamp"] == "yellow"
    assert by_sku["G"]["status_lamp"] == "green"
    assert by_sku["X"]["status_lamp"] == "gray"
    assert by_sku["G"]["primary_concern"] == ""
    assert by_sku["X"]["primary_concern"] == ""
    # Yellow primary_concern populated from top neg label
    assert by_sku["Y"]["primary_concern"]


# ──────────────────────────────────────────────────────────
# §4.2.6 — Panorama filters + 561-review embedding
# ──────────────────────────────────────────────────────────
def _panorama_reviews(n=561):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "id": i,
            "ownership": "own" if i % 2 == 0 else "competitor",
            "product_name": f"Product {i % 5}",
            "rating": (i % 5) + 1,
            "headline": f"H{i}",
            "body": f"Body {i}",
            "date_published": "2026-04-20",
            "images": [] if i % 3 else ["img.jpg"],
            "analysis_labels": '[{"code":"noise_power","polarity":"negative"}]',
        })
    return rows


def test_panorama_has_5_filters():
    snapshot = _base_snapshot(reviews=_panorama_reviews(5))
    analytics = _base_analytics(label_options=[
        {"code": "noise_power", "display": "噪音与动力"},
    ])
    html = render_attachment_html(snapshot, analytics)
    assert 'name="ownership"' in html
    assert 'name="rating"' in html
    assert 'name="has_images"' in html
    assert 'name="recent"' in html
    assert 'name="label"' in html


def test_panorama_embeds_all_561_reviews():
    """F011 §4.2.6 — full 561 embed (no link-out)"""
    snapshot = _base_snapshot(reviews=_panorama_reviews(561))
    analytics = _base_analytics()
    html = render_attachment_html(snapshot, analytics)
    for review_id in [10, 100, 200, 400, 561]:
        assert f'data-review-id="{review_id}"' in html


# ──────────────────────────────────────────────────────────
# H17 — template uses columns key, never row.values()
# ──────────────────────────────────────────────────────────
def test_trend_table_uses_columns_key_not_dict_values():
    """F011 H17 — 模板按 columns key 输出表格，不依赖 dict 顺序"""
    import os
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "qbu_crawler", "server", "report_templates", "daily_report_v3.html.j2",
    )
    with open(template_path, "r", encoding="utf-8") as f:
        template_source = f.read()
    assert "row.values()" not in template_source
