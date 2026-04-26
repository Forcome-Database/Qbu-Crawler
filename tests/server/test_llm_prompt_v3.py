import pytest
from qbu_crawler.server.report_llm import (
    LLM_INSIGHTS_SCHEMA_V3, SchemaError, ToneGuardError,
    validate_llm_copy, validate_tone_guards, assert_consistency,
    _build_insights_prompt_v3, TONE_GUARDS_PROMPT,
)


def _good_copy():
    return {
        "hero_headline": "健康指数 96.2，仍存在结构性短板待夯实",
        "executive_summary": "本期……",
        "executive_bullets": ["本期入库 30 条评论"],
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "肉饼厚度调节缺位",
            "full_action": (
                "针对结构调节机构在 13 条用户反馈中提及的卡顿与不可调节问题，"
                "建议产品团队评估三档卡扣替代连续调节、引入自验证装配工序、"
                "并在月度 QA 中加入操作模拟测试以闭环。"
            ),
            "evidence_count": 13,
            "evidence_review_ids": [1, 2, 3],
            "affected_products": ["A", "B"],
        }],
        "competitive_insight": "竞品在……",
    }


def test_schema_has_short_title_full_action_evidence_review_ids():
    item = LLM_INSIGHTS_SCHEMA_V3["properties"]["improvement_priorities"]["items"]
    assert "short_title" in item["properties"]
    assert "full_action" in item["properties"]
    assert "evidence_review_ids" in item["properties"]
    assert set(item["required"]) >= {
        "label_code", "short_title", "full_action", "evidence_count", "evidence_review_ids"
    }


def test_validate_passes_good_copy():
    validate_llm_copy(_good_copy())


def test_short_title_max_20_chars_raises():
    bad = _good_copy()
    bad["improvement_priorities"][0]["short_title"] = "结构设计：肉饼厚度不可调影响 3 款，需重新设计调节机构"  # >20
    with pytest.raises(SchemaError):
        validate_llm_copy(bad)


def test_full_action_min_80_raises():
    bad = _good_copy()
    bad["improvement_priorities"][0]["full_action"] = "太短"
    with pytest.raises(SchemaError):
        validate_llm_copy(bad)


def test_tone_guard_blocks_severe_word_when_health_high():
    kpis = {"health_index": 96.2, "high_risk_count": 0}
    bad = _good_copy()
    bad["hero_headline"] = "健康指数 96.2，但缺陷正严重侵蚀核心体验"
    with pytest.raises(ToneGuardError):
        validate_tone_guards(bad, kpis)


def test_tone_guard_passes_neutral_phrasing_when_health_high():
    kpis = {"health_index": 96.2, "high_risk_count": 0}
    validate_tone_guards(_good_copy(), kpis)


def test_tone_guard_blocks_high_risk_subject_when_count_zero():
    kpis = {"health_index": 96.2, "high_risk_count": 0}
    bad = _good_copy()
    bad["hero_headline"] = "高风险产品仍需关注"
    with pytest.raises(ToneGuardError):
        validate_tone_guards(bad, kpis)


def test_tone_guard_severe_word_OK_when_health_low():
    """严重 etc. is allowed when health < 90."""
    kpis = {"health_index": 60, "high_risk_count": 2}
    bad = _good_copy()
    bad["hero_headline"] = "差评严重侵蚀健康指数"
    validate_tone_guards(bad, kpis)


def test_assert_consistency_blocks_health_mismatch():
    kpis = {"health_index": 50.0}
    bad = _good_copy()
    bad["hero_headline"] = "健康指数 96.2，仍有改进空间"
    with pytest.raises(AssertionError):
        assert_consistency(bad, kpis)


def test_assert_consistency_passes_within_05():
    kpis = {"health_index": 96.4}
    assert_consistency(_good_copy(), kpis)


def test_assert_consistency_no_health_number_skips():
    kpis = {"health_index": 50.0}
    bad = _good_copy()
    bad["hero_headline"] = "本期表现良好，需关注结构性问题"  # no number
    assert_consistency(bad, kpis)  # must not raise


def test_prompt_v3_contains_schema_block_and_tone_guards():
    analytics = {"kpis": {}, "self": {"top_negative_clusters": []},
                 "competition": {}, "report_semantics": "incremental"}
    prompt = _build_insights_prompt_v3(analytics, snapshot=None)
    assert "short_title" in prompt
    assert "full_action" in prompt
    assert "evidence_review_ids" in prompt
    assert TONE_GUARDS_PROMPT.strip().splitlines()[0].strip() in prompt
    assert "[prompt_version: v3]" in prompt
