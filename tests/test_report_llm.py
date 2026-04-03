from __future__ import annotations


def _snapshot():
    return {
        "run_id": 1,
        "logical_date": "2026-04-03",
        "snapshot_hash": "hash-1",
        "products": [
            {"name": "Own Grinder", "sku": "OWN-1", "ownership": "own"},
            {"name": "Competitor Grinder", "sku": "COMP-1", "ownership": "competitor"},
        ],
        "reviews": [
            {
                "id": 101,
                "product_name": "Own Grinder",
                "product_sku": "OWN-1",
                "ownership": "own",
                "headline": "Motor failed",
                "body": "The motor broke after two uses.",
                "rating": 1,
                "images": ["https://img.example.com/own-negative.jpg"],
            },
            {
                "id": 102,
                "product_name": "Own Grinder",
                "product_sku": "OWN-1",
                "ownership": "own",
                "headline": "Works great",
                "body": "Solid and well made machine.",
                "rating": 5,
                "images": [],
            },
            {
                "id": 201,
                "product_name": "Competitor Grinder",
                "product_sku": "COMP-1",
                "ownership": "competitor",
                "headline": "Easy to use",
                "body": "Easy to use and easy to clean.",
                "rating": 5,
                "images": ["https://img.example.com/comp-positive.jpg"],
            },
            {
                "id": 202,
                "product_name": "Competitor Grinder",
                "product_sku": "COMP-1",
                "ownership": "competitor",
                "headline": "Box was damaged",
                "body": "Packaging was damaged on arrival.",
                "rating": 1,
                "images": ["https://img.example.com/comp-negative.jpg"],
            },
        ],
    }


def _analytics():
    return {
        "mode": "baseline",
        "kpis": {},
        "self": {
            "risk_products": [
                {
                    "product_name": "Own Grinder",
                    "product_sku": "OWN-1",
                    "negative_review_rows": 2,
                    "image_review_rows": 1,
                    "risk_score": 8,
                    "top_labels": [{"label_code": "quality_stability", "count": 2}],
                }
            ],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "label_polarity": "negative",
                    "review_count": 2,
                    "image_review_count": 1,
                    "severity": "high",
                    "example_reviews": [
                        {
                            "id": 101,
                            "product_name": "Own Grinder",
                            "product_sku": "OWN-1",
                            "rating": 1,
                            "headline": "Motor failed",
                            "body": "The motor broke after two uses.",
                            "images": ["https://img.example.com/own-negative.jpg"],
                        },
                        {
                            "id": 102,
                            "product_name": "Own Grinder",
                            "product_sku": "OWN-1",
                            "rating": 5,
                            "headline": "Works great",
                            "body": "Solid and well made machine.",
                            "images": [],
                        },
                    ],
                },
                {
                    "label_code": "service_fulfillment",
                    "label_polarity": "negative",
                    "review_count": 1,
                    "image_review_count": 0,
                    "severity": "low",
                    "example_reviews": [
                        {
                            "id": 102,
                            "product_name": "Own Grinder",
                            "product_sku": "OWN-1",
                            "rating": 5,
                            "headline": "Works great",
                            "body": "Solid and well made machine.",
                            "images": [],
                        }
                    ],
                },
            ],
            "recommendations": [
                {
                    "label_code": "quality_stability",
                    "priority": "high",
                    "possible_cause_boundary": "可能与核心部件耐久性有关",
                    "improvement_direction": "优先复核高频失效部件寿命",
                    "evidence_count": 2,
                },
                {
                    "label_code": "service_fulfillment",
                    "priority": "medium",
                    "possible_cause_boundary": "可能与售后SOP有关",
                    "improvement_direction": "复核售后闭环时间",
                    "evidence_count": 1,
                },
            ],
        },
        "competitor": {
            "top_positive_themes": [
                {
                    "label_code": "easy_to_use",
                    "label_polarity": "positive",
                    "review_count": 2,
                    "image_review_count": 1,
                    "severity": "low",
                    "example_reviews": [
                        {
                            "id": 201,
                            "product_name": "Competitor Grinder",
                            "product_sku": "COMP-1",
                            "rating": 5,
                            "headline": "Easy to use",
                            "body": "Easy to use and easy to clean.",
                            "images": ["https://img.example.com/comp-positive.jpg"],
                        },
                        {
                            "id": 202,
                            "product_name": "Competitor Grinder",
                            "product_sku": "COMP-1",
                            "rating": 1,
                            "headline": "Box was damaged",
                            "body": "Packaging was damaged on arrival.",
                            "images": ["https://img.example.com/comp-negative.jpg"],
                        },
                    ],
                }
            ],
            "benchmark_examples": [
                {
                    "review_id": 201,
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "rating": 5,
                    "label_codes": ["easy_to_use"],
                },
                {
                    "review_id": 202,
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "rating": 1,
                    "label_codes": ["solid_build"],
                },
            ],
            "negative_opportunities": [
                {
                    "review_id": 202,
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "rating": 1,
                    "label_codes": ["packaging_shipping"],
                },
                {
                    "review_id": 201,
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "rating": 5,
                    "label_codes": ["material_finish"],
                },
            ],
        },
        "appendix": {
            "image_reviews": [
                {
                    "id": 101,
                    "product_name": "Own Grinder",
                    "product_sku": "OWN-1",
                    "ownership": "own",
                    "rating": 1,
                    "headline": "Motor failed",
                    "body": "The motor broke after two uses.",
                    "images": ["https://img.example.com/own-negative.jpg"],
                },
                {
                    "id": 201,
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "ownership": "competitor",
                    "rating": 5,
                    "headline": "Easy to use",
                    "body": "Easy to use and easy to clean.",
                    "images": ["https://img.example.com/comp-positive.jpg"],
                },
            ]
        },
    }


def test_build_candidate_pools_filters_by_ownership_rating_and_images():
    from qbu_crawler.server.report_llm import build_candidate_pools

    pools = build_candidate_pools(_snapshot(), _analytics())

    assert [item["id"] for item in pools["own_negative_candidates"]] == [101]
    assert [item["id"] for item in pools["competitor_positive_candidates"]] == [201]
    assert [item["id"] for item in pools["own_negative_image_candidates"]] == [101]
    assert [item["id"] for item in pools["competitor_negative_opportunity_candidates"]] == [202]


def test_validate_findings_filters_examples_appendix_and_opportunities():
    from qbu_crawler.server.report_llm import build_candidate_pools, validate_findings

    snapshot = _snapshot()
    analytics = _analytics()
    candidate_pools = build_candidate_pools(snapshot, analytics)

    validated = validate_findings(
        snapshot,
        analytics,
        {
            "candidate_pools": candidate_pools,
            "llm_findings": {},
            "report_copy": {},
        },
    )

    assert [item["label_code"] for item in validated["self_negative_clusters"]] == ["quality_stability"]
    assert [item["id"] for item in validated["self_negative_clusters"][0]["example_reviews"]] == [101]
    assert {item["label_code"] for item in validated["competitor_positive_themes"]} == {
        "easy_to_use",
        "easy_to_clean",
    }
    assert [item["id"] for item in validated["competitor_positive_themes"][0]["example_reviews"]] == [201]
    assert [item["id"] for item in validated["own_image_evidence"]] == [101]
    assert [item["review_id"] for item in validated["competitor_negative_opportunities"]] == [202]
    assert [item["review_id"] for item in validated["competitor_benchmark_examples"]] == [201]
    assert [item["label_code"] for item in validated["recommendations"]] == ["quality_stability"]


def test_merge_final_analytics_overrides_unvalidated_sections():
    from qbu_crawler.server.report_llm import build_candidate_pools, merge_final_analytics, validate_findings

    snapshot = _snapshot()
    analytics = _analytics()
    candidate_pools = build_candidate_pools(snapshot, analytics)
    validated = validate_findings(
        snapshot,
        analytics,
        {"candidate_pools": candidate_pools, "llm_findings": {}, "report_copy": {"hero_headline": "聚焦可靠性"}},
    )

    final_analytics = merge_final_analytics(analytics, {"candidate_pools": candidate_pools, "llm_findings": {}, "report_copy": {"hero_headline": "聚焦可靠性"}}, validated)

    assert final_analytics["self"]["top_negative_clusters"][0]["example_reviews"][0]["id"] == 101
    assert final_analytics["appendix"]["image_reviews"][0]["id"] == 101
    assert final_analytics["competitor"]["benchmark_examples"][0]["review_id"] == 201
    assert final_analytics["validated_findings"]["own_image_evidence"][0]["id"] == 101
    assert final_analytics["report_copy"]["hero_headline"] == "聚焦可靠性"
