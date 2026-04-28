from qbu_crawler.server.report_contract import (
    build_report_user_contract,
    derive_executive_bullets,
    validate_report_user_contract,
)


def test_contract_builds_stable_executive_slots():
    snapshot = {
        "logical_date": "2026-04-28",
        "products": [{"name": "A"}, {"name": "B"}],
        "reviews": [{"id": 1}, {"id": 2}, {"id": 3}],
    }
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "coverage_rate": 0.675,
            "product_count": 2,
            "ingested_review_rows": 3,
            "translation_completion_rate": 1.0,
            "own_product_count": 1,
            "own_review_rows": 2,
            "own_avg_rating": 4.7,
            "own_negative_review_rate": 0.024,
            "high_risk_count": 0,
            "attention_product_count": 0,
        },
        "report_user_contract": {
            "issue_diagnostics": [{
                "label_code": "quality_stability",
                "label_display": "质量稳定性",
                "evidence_count": 13,
            }]
        },
    }

    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    slots = contract["executive_slots"]
    assert 1 <= len(slots) <= 5
    assert [slot["slot_id"] for slot in slots] == [
        "sample_scope",
        "translation_quality",
        "own_product_health",
        "priority_focus",
    ]
    assert all(slot["default_text"] for slot in slots)
    assert contract["executive_bullets"] == derive_executive_bullets(contract)
    assert len(contract["executive_bullets"]) <= 5


def test_llm_slot_text_overrides_only_matching_slots():
    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28", "products": [], "reviews": []},
        analytics={"report_semantics": "bootstrap", "kpis": {}},
        llm_copy={
            "executive_slots": [
                {"slot_id": "sample_scope", "text": "固定样本口径文案"},
                {"slot_id": "unknown_slot", "text": "不应出现"},
            ],
            "improvement_priorities": [],
        },
    )

    assert contract["executive_slots"][0]["llm_text"] == "固定样本口径文案"
    assert contract["executive_bullets"][0] == "固定样本口径文案"
    assert "unknown_slot" not in [slot["slot_id"] for slot in contract["executive_slots"]]
    assert any("unknown executive slot" in item for item in contract["validation_warnings"])


def test_validate_contract_flags_delivery_deadletter_conflict():
    warnings = validate_report_user_contract({
        "delivery": {
            "report_generated": True,
            "workflow_notification_delivered": True,
            "deadletter_count": 2,
            "internal_status": "full_sent",
        },
        "executive_slots": [{"slot_id": "sample_scope", "default_text": "ok"}],
        "executive_bullets": ["ok"],
        "action_priorities": [],
        "issue_diagnostics": [],
    })

    assert any("delivery conflict" in item for item in warnings)
