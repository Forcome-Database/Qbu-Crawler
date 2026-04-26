import pytest
from qbu_crawler.server.report_llm import assert_consistency

KPIS = {"health_index": 96.2, "high_risk_count": 0, "own_review_rows": 418}
RISK_PRODUCTS = [{"product_name": ".75 HP", "risk_score": 32.6}]
REVIEWS = [{"id": 1}, {"id": 2}, {"id": 252}, {"id": 254}]


def test_hero_health_match_passes():
    copy = {"hero_headline": "健康指数 96.2，仍存在结构性短板"}
    assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_hero_health_mismatch_raises():
    copy = {"hero_headline": "健康指数 90.0，仍存在结构性短板"}
    with pytest.raises(AssertionError, match=r"health"):
        assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_evidence_count_zero_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "improvement_priorities": [{
            "label_code": "x", "evidence_count": 0,
            "evidence_review_ids": [], "affected_products": [],
        }],
    }
    with pytest.raises(AssertionError, match=r"evidence_count"):
        assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_unknown_review_id_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "improvement_priorities": [{
            "label_code": "x", "evidence_count": 3,
            "evidence_review_ids": [1, 999, 1000],
            "affected_products": [".75 HP"],
        }],
    }
    with pytest.raises(AssertionError, match=r"未知 review id"):
        assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_unknown_product_in_affected_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "improvement_priorities": [{
            "label_code": "x", "evidence_count": 3,
            "evidence_review_ids": [1, 2],
            "affected_products": [".75 HP", "Unknown Product"],
        }],
    }
    with pytest.raises(AssertionError, match=r"affected_products"):
        assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_bullet_unknown_number_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "executive_bullets": [".75 HP 风险分高达 99.9/100"],
    }
    with pytest.raises(AssertionError, match=r"bullet"):
        assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_bullet_known_number_passes():
    copy = {
        "hero_headline": "健康指数 96.2",
        "executive_bullets": [".75 HP 风险分 32.6 接近高风险"],  # 32.6 in risk_products
    }
    assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_no_priorities_no_bullets_passes():
    """When copy is bare-minimum (no bullets/priorities), checks reduce to hero alone."""
    copy = {"hero_headline": "健康指数 96.2"}
    assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)


def test_default_args_preserve_v2_6_behavior():
    """Backward compat: callers passing only (copy, kpis) still work."""
    copy = {"hero_headline": "健康指数 96.2"}
    assert_consistency(copy, KPIS)  # no risk_products/reviews → bullets check skips, priorities check skips


def test_review_count_in_bullet_uses_len_reviews():
    """Phrasing like '本期入库 4 条评论' matches len(reviews)."""
    copy = {
        "hero_headline": "健康指数 96.2",
        "executive_bullets": ["本期入库 4 条评论"],
    }
    assert_consistency(copy, KPIS, risk_products=RISK_PRODUCTS, reviews=REVIEWS)
