from qbu_crawler.server.report_llm import assert_consistency


def test_percentage_form_numbers_are_traceable_to_ratio_kpis():
    copy = {
        "hero_headline": "当前健康指数 94.7，整体稳定",
        "executive_bullets": [
            "全量差评率12.1%（72/594），自有产品差评率仅3.8%（17/451）。",
            ".5 HP Dual Grind Grinder (#8)差评率达21%，需优先关注。",
        ],
        "improvement_priorities": [],
    }
    kpis = {
        "health_index": 94.7,
        "all_sample_negative_rate": 0.121,
        "own_negative_review_rate": 0.038,
        "negative_review_rows": 72,
        "ingested_review_rows": 594,
        "own_negative_review_rows": 17,
        "own_review_rows": 451,
    }
    risk_products = [{"negative_rate": 0.21, "negative_reviews": 7}]

    assert_consistency(copy, kpis, risk_products=risk_products, reviews=[{}] * 594)
