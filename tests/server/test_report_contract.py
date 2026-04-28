from qbu_crawler.server.report_contract import build_report_user_contract


def test_build_report_user_contract_has_required_top_level_fields():
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {"health_index": 96.2},
        "self": {"risk_products": []},
    }
    snapshot = {"logical_date": "2026-04-28", "reviews": [], "products": []}

    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    assert contract["schema_version"] == "report_user_contract.v1"
    assert contract["mode"] == "bootstrap"
    assert contract["logical_date"] == "2026-04-28"
    assert contract["contract_context"]["snapshot_source"] == "provided"
    assert "metric_definitions" in contract
    assert "kpis" in contract
    assert "action_priorities" in contract
    assert "issue_diagnostics" in contract
    assert "heatmap" in contract
    assert "competitor_insights" in contract
    assert "bootstrap_digest" in contract
    assert "delivery" in contract
    assert "validation_warnings" in contract


def test_renderer_refreshes_contract_with_real_snapshot_context():
    analytics = {
        "report_semantics": "bootstrap",
        "report_user_contract": {
            "schema_version": "report_user_contract.v1",
            "contract_context": {"snapshot_source": "missing"},
            "issue_diagnostics": [],
        },
    }
    snapshot = {
        "logical_date": "2026-04-28",
        "products": [{"name": "Walton's Quick Patty Maker"}],
        "reviews": [{"id": 101, "product_name": "Walton's Quick Patty Maker"}],
    }

    refreshed = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    assert refreshed["contract_context"]["snapshot_source"] == "provided"
    assert refreshed["contract_context"]["product_count"] == 1
    assert refreshed["contract_context"]["review_count"] == 1


def test_missing_snapshot_context_is_marked_as_temporary():
    contract = build_report_user_contract(
        snapshot={},
        analytics={"report_semantics": "bootstrap", "kpis": {}},
    )

    assert contract["contract_context"]["snapshot_source"] == "missing"
    assert contract["contract_context"]["product_count"] == 0
    assert contract["contract_context"]["review_count"] == 0


def test_metric_definitions_describe_time_basis_scope_and_denominator():
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "health_index": 96.2,
            "fresh_review_count": 5,
            "high_risk_count": 2,
            "attention_product_count": 3,
            "negative_review_rate": 0.18,
            "translation_completion_rate": 1.0,
            "scrape_missing_rate": 0.12,
        },
    }
    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28"},
        analytics=analytics,
    )

    required_fields = [
        "health_index",
        "high_risk_count",
        "attention_product_count",
        "negative_review_rate",
        "fresh_review_count",
        "translation_completion_rate",
        "scrape_missing_rate",
        "heatmap_experience_health",
    ]
    for field in required_fields:
        definition = contract["metric_definitions"][field]
        assert definition["field"] == field
        assert definition["formula"]
        assert definition["time_basis"]
        assert definition["product_scope"]
        assert definition["denominator"]
        assert definition["bootstrap_behavior"]
        assert definition["confidence"]
        assert definition["explanation"]


def test_issue_clusters_become_evidence_packs():
    analytics = {
        "report_semantics": "bootstrap",
        "self": {
            "top_negative_clusters": [{
                "label_code": "structure_design",
                "label_display": "结构设计",
                "affected_products": ["Walton's Quick Patty Maker"],
                "evidence_count": 2,
                "example_reviews": [
                    {"id": 101, "body_cn": "肉饼太大", "images": ["https://example.test/a.jpg"]}
                ],
                "deep_analysis": {
                    "actionable_summary": "复核成型尺寸",
                    "failure_modes": [{"name": "尺寸不匹配"}],
                    "root_causes": [{"name": "模具约束不足"}],
                    "user_workarounds": ["手工修整"],
                },
            }]
        },
    }

    contract = build_report_user_contract(snapshot={"logical_date": "2026-04-28"}, analytics=analytics)

    card = contract["issue_diagnostics"][0]
    assert card["label_code"] == "structure_design"
    assert card["affected_products"] == ["Walton's Quick Patty Maker"]
    assert card["allowed_products"] == ["Walton's Quick Patty Maker"]
    assert card["evidence_review_ids"] == [101]
    assert card["text_evidence"][0]["display_body"] == "肉饼太大"
    assert card["image_evidence"][0]["url"] == "https://example.test/a.jpg"
    assert card["failure_modes"] == [{"name": "尺寸不匹配"}]
    assert card["root_causes"] == [{"name": "模具约束不足"}]
    assert card["recommended_action"] == "复核成型尺寸"


def test_competitor_insights_contract_has_three_sections():
    analytics = {
        "competitor": {
            "positive_patterns": [{
                "summary_cn": "竞品安装步骤清晰",
                "review_ids": [201],
                "product_count": 2,
                "sample_size": 8,
            }],
            "negative_opportunities": [{
                "body_cn": "竞品包装容易破损",
                "review_ids": [301],
                "product_count": 1,
                "sample_size": 3,
            }],
        },
    }

    contract = build_report_user_contract(snapshot={"logical_date": "2026-04-28"}, analytics=analytics)

    insights = contract["competitor_insights"]
    assert "learn_from_competitors" in insights
    assert "avoid_competitor_failures" in insights
    assert "validation_hypotheses" in insights
    item = insights["learn_from_competitors"][0]
    assert item["summary_cn"] == "竞品安装步骤清晰"
    assert item["self_product_implication"]
    assert item["suggested_validation"]
    assert item["evidence_review_ids"] == [201]
    assert item["sample_size"] == 8
    assert item["product_count"] == 2


def test_bootstrap_digest_forbids_incremental_terms():
    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28", "reviews": [1, 2], "products": [1]},
        analytics={"report_semantics": "bootstrap", "kpis": {"attention_product_count": 3}},
    )

    text = str(contract["bootstrap_digest"])
    assert "较昨日" not in text
    assert "较上期" not in text
    assert "新增增长" not in text
    assert "监控起点" in text or contract["bootstrap_digest"]["baseline_summary"]


def test_bootstrap_digest_contains_baseline_and_data_quality():
    snapshot = {
        "logical_date": "2026-04-28",
        "products": [{"name": "A"}, {"name": "B"}],
        "reviews": [{"id": 1}, {"id": 2}, {"id": 3}],
    }
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "coverage_rate": 0.75,
            "translation_completion_rate": 1.0,
            "historical_backfill_ratio": 0.8,
            "estimated_date_ratio": 0.2,
            "attention_product_count": 2,
        },
        "data_quality": {
            "low_coverage_products": ["B"],
        },
    }

    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)
    digest = contract["bootstrap_digest"]

    assert digest["baseline_summary"]["product_count"] == 2
    assert digest["baseline_summary"]["review_count"] == 3
    assert digest["baseline_summary"]["coverage_rate"] == 0.75
    assert digest["baseline_summary"]["translation_completion_rate"] == 1.0
    assert digest["data_quality"]["historical_backfill_ratio"] == 0.8
    assert digest["data_quality"]["estimated_date_ratio"] == 0.2
    assert digest["data_quality"]["low_coverage_products"] == ["B"]
    assert digest["immediate_attention"]


def test_delivery_contract_distinguishes_generated_and_delivered():
    analytics = {
        "delivery": {
            "report_generated": True,
            "email_delivered": True,
            "workflow_notification_delivered": False,
            "deadletter_count": 3,
            "internal_status": "full_sent_local",
        }
    }

    contract = build_report_user_contract(snapshot={"logical_date": "2026-04-28"}, analytics=analytics)

    delivery = contract["delivery"]
    assert delivery["report_generated"] is True
    assert delivery["email_delivered"] is True
    assert delivery["workflow_notification_delivered"] is False
    assert delivery["deadletter_count"] == 3
    assert delivery["internal_status"] == "full_sent_local"
