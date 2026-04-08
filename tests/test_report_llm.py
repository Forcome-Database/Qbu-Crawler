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


# ---------------------------------------------------------------------------
# Tests for generate_report_insights (new pipeline)
# ---------------------------------------------------------------------------

import json


def _insights_analytics():
    """Build a minimal analytics dict for insights testing."""
    return {
        "kpis": {
            "own_product_count": 3,
            "competitor_product_count": 2,
            "ingested_review_rows": 100,
            "negative_review_rows": 15,
            "negative_review_rate": 0.15,
            "health_index": 72.0,
            "own_avg_rating": 3.8,
        },
        "self": {
            "risk_products": [
                {"product_name": "Own Grinder", "product_sku": "OWN-1", "risk_score": 10}
            ],
            "top_negative_clusters": [
                {
                    "feature_display": "手柄松动",
                    "label_display": "手柄松动",
                    "review_count": 8,
                    "severity": "high",
                    "severity_display": "高",
                },
                {
                    "feature_display": "噪音大",
                    "label_display": "噪音大",
                    "review_count": 5,
                    "severity": "medium",
                    "severity_display": "中",
                },
            ],
            "recommendations": [],
        },
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"label_display": "做工", "competitor_positive_count": 12, "own_negative_count": 6},
            ],
        },
        "appendix": {"image_reviews": []},
    }


def test_generate_report_insights_with_mock_llm(monkeypatch):
    from qbu_crawler.server import report_llm

    mock_response_json = json.dumps({
        "hero_headline": "手柄问题需立即关注",
        "executive_summary": "自有产品差评集中在手柄松动和噪音问题。",
        "executive_bullets": ["手柄松动影响8条评论", "噪音问题5条", "竞品做工优势明显"],
        "improvement_priorities": [
            {"rank": 1, "target": "Own Grinder", "issue": "手柄松动", "action": "加固手柄连接", "evidence_count": 8}
        ],
        "competitive_insight": "竞品在做工方面获得大量好评。",
    })

    class MockMessage:
        content = mock_response_json

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]

    class MockClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return MockResponse()

    monkeypatch.setattr("qbu_crawler.server.report_llm.config.LLM_API_BASE", "http://fake")
    monkeypatch.setattr("qbu_crawler.server.report_llm.config.LLM_API_KEY", "fake-key")

    # Patch OpenAI import
    import types
    mock_openai = types.ModuleType("openai")
    mock_openai.OpenAI = lambda **kwargs: MockClient()
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai)

    result = report_llm.generate_report_insights(_insights_analytics())

    assert result["hero_headline"] == "手柄问题需立即关注"
    assert len(result["executive_bullets"]) == 3
    assert len(result["improvement_priorities"]) == 1
    assert result["competitive_insight"] != ""
    # Check all required keys present
    for key in report_llm._INSIGHTS_KEYS:
        assert key in result


def test_generate_report_insights_fallback_on_failure(monkeypatch):
    from qbu_crawler.server import report_llm

    monkeypatch.setattr("qbu_crawler.server.report_llm.config.LLM_API_BASE", "http://fake")
    monkeypatch.setattr("qbu_crawler.server.report_llm.config.LLM_API_KEY", "fake-key")

    # Patch OpenAI to raise
    import types
    mock_openai = types.ModuleType("openai")

    def _raise(**kwargs):
        raise RuntimeError("LLM unavailable")

    mock_openai.OpenAI = _raise
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai)

    result = report_llm.generate_report_insights(_insights_analytics())

    # Should fall back gracefully
    assert "hero_headline" in result
    assert isinstance(result["executive_bullets"], list)
    assert "improvement_priorities" in result


def test_generate_report_insights_no_llm_configured(monkeypatch):
    from qbu_crawler.server import report_llm

    monkeypatch.setattr("qbu_crawler.server.report_llm.config.LLM_API_BASE", "")
    monkeypatch.setattr("qbu_crawler.server.report_llm.config.LLM_API_KEY", "")

    result = report_llm.generate_report_insights(_insights_analytics())

    assert "hero_headline" in result
    assert isinstance(result["executive_bullets"], list)


def test_build_insights_prompt_includes_data():
    from qbu_crawler.server.report_llm import _build_insights_prompt

    prompt = _build_insights_prompt(_insights_analytics())
    assert "自有产品 3 个" in prompt
    assert "竞品 2 个" in prompt
    assert "手柄松动" in prompt
    assert "做工" in prompt


def test_fallback_insights_has_required_keys():
    from qbu_crawler.server.report_llm import _fallback_insights

    result = _fallback_insights(_insights_analytics())
    assert "hero_headline" in result
    assert "executive_summary" in result
    assert "executive_bullets" in result
    assert "improvement_priorities" in result
    assert "competitive_insight" in result
    assert isinstance(result["executive_bullets"], list)


def test_parse_llm_response_with_code_block():
    from qbu_crawler.server.report_llm import _parse_llm_response

    raw = '```json\n{"hero_headline": "test"}\n```'
    result = _parse_llm_response(raw)
    assert result["hero_headline"] == "test"


def test_parse_llm_response_plain():
    from qbu_crawler.server.report_llm import _parse_llm_response

    raw = '{"hero_headline": "test"}'
    result = _parse_llm_response(raw)
    assert result["hero_headline"] == "test"


def test_validate_llm_evidence_counts():
    """LLM-reported evidence_count must be capped at actual cluster counts."""
    from qbu_crawler.server.report_llm import _validate_insights

    analytics = {
        "self": {
            "top_negative_clusters": [
                {"label_code": "quality_stability", "review_count": 5},
                {"label_code": "noise_power", "review_count": 3},
            ],
        },
    }
    llm_output = {
        "hero_headline": "质量问题严重",
        "executive_summary": "摘要",
        "executive_bullets": ["要点1"],
        "improvement_priorities": [
            {"rank": 1, "target": "Product A", "issue": "质量",
             "action": "修复", "evidence_count": 999},
        ],
        "competitive_insight": "洞察",
    }
    validated = _validate_insights(llm_output, analytics)
    for p in validated["improvement_priorities"]:
        assert p["evidence_count"] <= 8, \
            f"evidence_count {p['evidence_count']} exceeds total cluster count"


def test_hero_headline_truncation():
    """hero_headline must be capped at 80 chars."""
    from qbu_crawler.server.report_llm import _validate_insights

    llm_output = {
        "hero_headline": "A" * 200,
        "executive_summary": "",
        "executive_bullets": [],
        "improvement_priorities": [],
        "competitive_insight": "",
    }
    validated = _validate_insights(llm_output, {})
    assert len(validated["hero_headline"]) <= 80


def test_insights_prompt_uses_own_kpis():
    """Prompt must distinguish own vs total KPIs so LLM uses own data in hero_headline."""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = _insights_analytics()
    # Add own-specific KPIs that the real pipeline provides
    analytics["kpis"]["own_review_rows"] = 112
    analytics["kpis"]["own_negative_review_rows"] = 50
    analytics["kpis"]["own_negative_review_rate"] = 0.446
    analytics["kpis"]["competitor_review_rows"] = 36

    prompt = _build_insights_prompt(analytics)

    # Prompt must contain own-specific numbers
    assert "自有评论 112" in prompt, f"Prompt should contain '自有评论 112', got:\n{prompt}"
    assert "自有差评 50" in prompt, f"Prompt should contain '自有差评 50', got:\n{prompt}"
    assert "44.6%" in prompt, f"Prompt should contain own negative rate '44.6%', got:\n{prompt}"
    assert "竞品 36" in prompt or "含竞品 36" in prompt, (
        f"Prompt should mention competitor review count 36, got:\n{prompt}"
    )
    # Prompt must instruct LLM to use own data in hero_headline
    assert "自有" in prompt and "hero_headline" in prompt, (
        "Prompt must instruct LLM to reference own-product data in hero_headline"
    )
    # The hero_headline instruction should explicitly forbid using total/global data
    assert "不要引用" in prompt or "不要使用" in prompt, (
        "Prompt should instruct LLM NOT to use global/total data in hero_headline"
    )
