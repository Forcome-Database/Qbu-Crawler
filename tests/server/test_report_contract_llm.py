import json

from qbu_crawler.server.report_contract import build_report_user_contract, merge_llm_copy_into_contract
from qbu_crawler.server.report_common import normalize_deep_report_analytics
from qbu_crawler.server.report_llm import (
    _build_insights_prompt_v3,
    _build_llm_evidence_payload,
    normalize_llm_copy_shape,
    validate_llm_copy,
)


def _contract():
    return {
        "action_priorities": [],
        "issue_diagnostics": [{
            "label_code": "structure_design",
            "label_display": "Structure design",
            "allowed_products": ["Walton's Quick Patty Maker"],
            "affected_products": ["Walton's Quick Patty Maker"],
            "evidence_review_ids": [101],
            "text_evidence": [{"review_id": 101, "display_body": "肉饼太大"}],
            "recommended_action": "Use the locked evidence pack action.",
        }],
        "validation_warnings": [],
    }


def test_merge_llm_copy_replaces_product_outside_evidence_pack_with_locked_action():
    llm_copy = {
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "复核结构",
            "full_action": "复核结构尺寸",
            "affected_products": ["Unknown Product"],
            "evidence_review_ids": [101],
        }]
    }

    merged = merge_llm_copy_into_contract(_contract(), llm_copy)

    action = merged["action_priorities"][0]
    assert action["source"] == "evidence_fallback"
    assert action["affected_products"] == ["Walton's Quick Patty Maker"]
    assert action["full_action"] == "Use the locked evidence pack action."
    assert "Unknown Product" not in action["affected_products"]
    assert merged["validation_warnings"]


def test_merge_llm_copy_accepts_fact_locked_action():
    llm_copy = {
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "复核结构",
            "full_action": "复核结构尺寸",
            "affected_products": ["Walton's Quick Patty Maker"],
            "evidence_review_ids": [101],
        }]
    }

    merged = merge_llm_copy_into_contract(_contract(), llm_copy)

    assert merged["action_priorities"][0]["source"] == "llm_rewrite"
    assert merged["action_priorities"][0]["full_action"] == "复核结构尺寸"


def test_build_report_user_contract_merges_llm_copy_when_provided():
    analytics = {
        "self": {
            "top_negative_clusters": [{
                "label_code": "structure_design",
                "label_display": "结构设计",
                "affected_products": ["Walton's Quick Patty Maker"],
                "example_reviews": [{"id": 101, "body_cn": "肉饼太大"}],
            }]
        }
    }
    llm_copy = {
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "复核结构",
            "full_action": "复核结构尺寸",
            "affected_products": ["Walton's Quick Patty Maker"],
            "evidence_review_ids": [101],
        }]
    }

    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28"},
        analytics=analytics,
        llm_copy=llm_copy,
    )

    assert contract["action_priorities"][0]["source"] == "llm_rewrite"


def test_llm_payload_excludes_raw_analytics_and_uses_evidence_pack_only():
    analytics = {
        "self": {
            "risk_products": [{"product_name": "Raw Risk Product"}],
            "top_negative_clusters": [{"label_code": "raw_cluster"}],
        },
        "reviews": [{"id": 999, "body": "raw review should not be serialized"}],
        "report_user_contract": {
            "issue_diagnostics": [{
                "label_code": "structure_design",
                "allowed_products": ["Walton's Quick Patty Maker"],
                "affected_products": ["Walton's Quick Patty Maker"],
                "evidence_review_ids": [101],
                "text_evidence": [{"review_id": 101, "display_body": "肉饼太大"}],
            }]
        },
    }

    payload = _build_llm_evidence_payload(analytics)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert "structure_design" in payload_text
    assert "肉饼太大" in payload_text
    assert "Raw Risk Product" not in payload_text
    assert "raw_cluster" not in payload_text
    assert "raw review should not be serialized" not in payload_text


def test_normalize_llm_copy_shape_caps_executive_bullets_before_schema_validation():
    copy = {
        "hero_headline": "Health index 96.2 is stable",
        "executive_summary": "Summary",
        "executive_bullets": [
            "sample covers 8 products",
            "translation completed",
            "own products are stable",
            "negative reviews need attention",
            "image reviews are available",
            "extra KPI repetition",
        ],
        "improvement_priorities": [],
    }

    normalized = normalize_llm_copy_shape(copy)

    assert len(normalized["executive_bullets"]) == 5
    assert "extra KPI repetition" not in normalized["executive_bullets"]
    assert validate_llm_copy(normalized) == normalized


def test_prompt_declares_executive_bullet_count_contract():
    prompt = _build_insights_prompt_v3({"report_user_contract": {"issue_diagnostics": []}})

    assert "executive_bullets <= 5" in prompt
    assert "recommended 3" in prompt
    assert "Do not enumerate every KPI" in prompt


def test_normalized_issue_cards_keep_text_evidence_for_llm_payload():
    analytics = {
        "self": {
            "top_negative_clusters": [{
                "label_code": "structure_design",
                "review_count": 1,
                "affected_products": ["Walton's Quick Patty Maker"],
                "example_reviews": [{
                    "id": 101,
                    "headline_cn": "Too large",
                    "body_cn": "The patty is too large for daily use.",
                }],
            }]
        },
    }

    normalized = normalize_deep_report_analytics(analytics)
    payload = _build_llm_evidence_payload(normalized)

    text_evidence = payload["issue_diagnostics"][0]["text_evidence"]
    assert text_evidence
    assert text_evidence[0]["review_id"] == 101
    assert "too large" in text_evidence[0]["display_body"].lower()
