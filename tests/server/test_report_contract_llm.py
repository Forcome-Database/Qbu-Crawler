import json

from qbu_crawler.server.report_contract import build_report_user_contract, merge_llm_copy_into_contract
from qbu_crawler.server.report_llm import _build_llm_evidence_payload


def _contract():
    return {
        "action_priorities": [],
        "issue_diagnostics": [{
            "label_code": "structure_design",
            "allowed_products": ["Walton's Quick Patty Maker"],
            "affected_products": ["Walton's Quick Patty Maker"],
            "evidence_review_ids": [101],
            "text_evidence": [{"review_id": 101, "display_body": "肉饼太大"}],
        }],
        "validation_warnings": [],
    }


def test_merge_llm_copy_rejects_product_outside_evidence_pack():
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

    assert merged["action_priorities"][0]["source"] == "evidence_insufficient"
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
