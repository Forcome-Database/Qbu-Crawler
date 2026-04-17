"""P008 Phase 4: LLM-powered executive summary for the monthly report.

Inputs: cumulative KPIs + KPI delta vs previous month + top issue clusters +
category benchmark + safety incidents count.

Outputs:
    {
        "stance": "stable" | "needs_attention" | "urgent",
        "stance_text": str,
        "bullets": [str, str, str],
        "actions": [str, str, str],
    }

Falls back to a deterministic summary when LLM is unavailable.
"""

from __future__ import annotations

import json
import logging

from qbu_crawler import config


logger = logging.getLogger(__name__)


_PROMPT = """你是一名产品质量监控分析师，正在为高管撰写本月评论数据态势摘要。

输入数据（JSON）：
{inputs_json}

请基于上述数据返回严格的 JSON（不要包含 markdown 代码块）：
{{
  "stance": "stable" | "needs_attention" | "urgent",
  "stance_text": "一句话态势判断（不超过 40 字）",
  "bullets": ["要点1（≤30字）", "要点2", "要点3"],
  "actions": ["建议1（动词开头，≤30字）", "建议2", "建议3"]
}}

字段单位说明（重要，避免误判）：
- `own_negative_review_rate` / `neg_rate` 是 [0.0, 1.0] 区间的小数（fraction），而非百分数。
  例：0.05 == 5%，0.12 == 12%。判断阈值使用小数形式（threshold 0.05 == 5%）。
- `health_index` 是 [0, 100] 区间的整数/浮点数，单位即为分值，直接比较。

判断标准：
- urgent: 有 critical safety 事件 / 健康指数 < 50 / 高风险产品 ≥ 3
- needs_attention: 健康指数下降 > 5 / 高风险增加 / 差评率 > 0.05（即 > 5%）
- stable: 上述均不满足

bullets 必须基于输入数据中的实际数字（如"健康指数 72.3 较上月下降 1.5"），不要编造。
actions 必须可执行（如"调查 #22 Grinder 金属碎屑投诉"），避免空话。
"""


def _classify_stance(inputs: dict) -> str:
    kpis = inputs.get("kpis") or {}
    delta = inputs.get("kpi_delta") or {}
    health = float(kpis.get("health_index") or 0)
    high_risk = int(kpis.get("high_risk_count") or 0)
    neg_rate = float(kpis.get("own_negative_review_rate") or 0)
    safety_count = int(inputs.get("safety_incidents_count") or 0)
    health_delta = float(delta.get("health_index") or 0)
    risk_delta = int(delta.get("high_risk_count") or 0)

    if safety_count > 0 and any(
        s.get("safety_level") == "critical"
        for s in (inputs.get("safety_incidents") or [])
    ):
        return "urgent"
    if health < 50 or high_risk >= 3:
        return "urgent"
    if health_delta < -5 or risk_delta > 0 or neg_rate > 0.05:
        return "needs_attention"
    return "stable"


def _fallback_executive_summary(inputs: dict) -> dict:
    """Deterministic summary used when LLM is unavailable or fails."""
    kpis = inputs.get("kpis") or {}
    delta = inputs.get("kpi_delta") or {}
    top_issues = inputs.get("top_issues") or []
    safety_count = int(inputs.get("safety_incidents_count") or 0)

    stance = _classify_stance(inputs)
    stance_text = {
        "stable": "本月整体表现稳定",
        "needs_attention": "本月需要关注几项指标变动",
        "urgent": "本月出现紧急情况，建议立即行动",
    }[stance]

    bullets = []
    health = kpis.get("health_index")
    health_delta = delta.get("health_index")
    if health is not None and health_delta is not None:
        sign = "+" if health_delta >= 0 else ""
        bullets.append(f"健康指数 {health}（较上月 {sign}{round(health_delta, 1)}）")
    elif health is not None:
        bullets.append(f"健康指数 {health}")

    neg_rate = kpis.get("own_negative_review_rate")
    if neg_rate is not None:
        bullets.append(
            f"差评率 {round(float(neg_rate) * 100, 1)}% · "
            f"本月新增评论 {kpis.get('own_review_rows', 0)} 条"
        )

    if top_issues:
        first = top_issues[0]
        bullets.append(
            f"主要问题：{first.get('label_display', '')} "
            f"({first.get('review_count', 0)} 条 · {first.get('severity_display', '')})"
        )
    elif safety_count > 0:
        bullets.append(f"安全事件 {safety_count} 起，需重点核查")
    else:
        bullets.append("无突出问题集群")

    actions = []
    if stance == "urgent":
        actions.append("立即调查所有 critical safety 事件并冻结相关 SKU")
    if (kpis.get("high_risk_count") or 0) > 0:
        actions.append("逐个 review 高风险产品的差评样本，识别共性问题")
    if top_issues:
        actions.append(f"针对「{top_issues[0].get('label_display', '')}」制定短期改进计划")

    # Design says 2-3 建议行动. Ensure at least 2, even for stable stance.
    if len(actions) < 2:
        actions.append("复盘本月 TOP 3 正面评论主题，沉淀可复用营销卖点")
    if len(actions) < 2:
        actions.append("维持当前节奏，下月继续监控关键指标")
    actions = actions[:3]

    return {
        "stance": stance,
        "stance_text": stance_text,
        "bullets": bullets[:3],
        "actions": actions,
    }


def generate_executive_summary(inputs: dict) -> dict:
    """Generate executive summary via LLM, falling back to deterministic logic on error."""
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        logger.info("Executive summary: LLM not configured, using fallback")
        return _fallback_executive_summary(inputs)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)
        prompt = _PROMPT.format(inputs_json=json.dumps(inputs, ensure_ascii=False, sort_keys=True, indent=2))
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            timeout=60.0,  # seconds; prevents indefinite hang if LLM endpoint stalls
        )
        raw = (response.choices[0].message.content or "").strip()
        from qbu_crawler.server.report_llm import _parse_llm_response
        result = _parse_llm_response(raw)

        # Validate shape; fall back if malformed
        if not isinstance(result, dict) or "stance" not in result:
            raise ValueError("LLM returned malformed executive summary")

        result.setdefault("stance_text", "")
        result["bullets"] = list(result.get("bullets") or [])[:3]
        result["actions"] = list(result.get("actions") or [])[:3]
        if result["stance"] not in ("stable", "needs_attention", "urgent"):
            result["stance"] = _classify_stance(inputs)
        return result
    except Exception:
        logger.warning("Executive summary LLM call failed, using fallback", exc_info=True)
        return _fallback_executive_summary(inputs)
