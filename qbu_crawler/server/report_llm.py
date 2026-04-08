import copy
import json
import logging

from json_repair import repair_json

from qbu_crawler import config
from qbu_crawler.server import report_analytics

logger = logging.getLogger(__name__)


def _review_id(review):
    return review.get("id") or review.get("review_id")


def _review_images(review):
    return report_analytics._review_images(review)


def _review_labels(review, polarity):
    return [
        label
        for label in report_analytics.classify_review_labels(review)
        if label.get("label_polarity") == polarity
    ]


def build_candidate_pools(snapshot, analytics):
    own_negative_candidates = []
    competitor_positive_candidates = []
    own_negative_image_candidates = []
    competitor_negative_opportunity_candidates = []

    for review in snapshot.get("reviews") or []:
        ownership = review.get("ownership")
        rating = float(review.get("rating") or 0)
        negative_labels = _review_labels(review, "negative")
        positive_labels = _review_labels(review, "positive")
        images = _review_images(review)

        if ownership == "own" and (rating <= 2 or (rating <= 3 and negative_labels)):
            own_negative_candidates.append(review)
            if images:
                own_negative_image_candidates.append(review)

        if ownership == "competitor" and rating >= 4 and positive_labels:
            competitor_positive_candidates.append(review)

        if ownership == "competitor" and rating <= 2 and negative_labels:
            competitor_negative_opportunity_candidates.append(review)

    return {
        "own_negative_candidates": own_negative_candidates,
        "competitor_positive_candidates": competitor_positive_candidates,
        "own_negative_image_candidates": own_negative_image_candidates,
        "competitor_negative_opportunity_candidates": competitor_negative_opportunity_candidates,
    }


def classify_review_batch(pool_name, reviews):
    polarity = "positive" if pool_name == "competitor_positive_candidates" else "negative"
    items = []
    for review in reviews:
        labels = _review_labels(review, polarity)
        if not labels:
            continue
        items.append(
            {
                "review_id": _review_id(review),
                "polarity": polarity,
                "label_codes": [label["label_code"] for label in labels],
                "severity": max(labels, key=lambda label: report_analytics._SEVERITY_SCORE[label["severity"]])["severity"],
                "confidence": max(label["confidence"] for label in labels),
                "summary_text": (review.get("headline_cn") or review.get("headline") or "").strip(),
                "source": "deterministic",
            }
        )
    return items


def classify_candidate_pools(candidate_pools):
    return {
        pool_name: classify_review_batch(pool_name, reviews)
        for pool_name, reviews in candidate_pools.items()
    }


def _cluster_items(reviews, polarity):
    grouped = {}
    for review in reviews:
        labels = _review_labels(review, polarity)
        for label in labels:
            cluster = grouped.setdefault(
                label["label_code"],
                {
                    "label_code": label["label_code"],
                    "label_polarity": polarity,
                    "review_count": 0,
                    "image_review_count": 0,
                    "severity": label["severity"],
                    "severity_score": report_analytics._SEVERITY_SCORE[label["severity"]],
                    "example_reviews": [],
                    "supporting_review_ids": [],
                },
            )
            cluster["review_count"] += 1
            cluster["supporting_review_ids"].append(_review_id(review))
            images = _review_images(review)
            if images:
                cluster["image_review_count"] += 1
            if report_analytics._SEVERITY_SCORE[label["severity"]] > cluster["severity_score"]:
                cluster["severity"] = label["severity"]
                cluster["severity_score"] = report_analytics._SEVERITY_SCORE[label["severity"]]
            if len(cluster["example_reviews"]) < 3:
                example = dict(review)
                example["images"] = images
                cluster["example_reviews"].append(example)

    items = list(grouped.values())
    items.sort(
        key=lambda item: (
            -item["review_count"],
            -item["image_review_count"],
            -item["severity_score"],
            item["label_code"],
        )
    )
    for item in items:
        item.pop("severity_score")
    return items


def _benchmark_examples(reviews):
    items = []
    for review in reviews:
        labels = _review_labels(review, "positive")
        if not labels:
            continue
        items.append(
            {
                "review_id": _review_id(review),
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "author": review.get("author"),
                "rating": review.get("rating"),
                "headline": review.get("headline"),
                "body": review.get("body"),
                "headline_cn": review.get("headline_cn"),
                "body_cn": review.get("body_cn"),
                "images": _review_images(review),
                "label_codes": [label["label_code"] for label in labels],
            }
        )
    items.sort(key=lambda item: (-(item.get("rating") or 0), -(len(item["label_codes"])), item.get("product_sku") or ""))
    return items[:5]


def _negative_opportunities(reviews):
    items = []
    for review in reviews:
        labels = _review_labels(review, "negative")
        if not labels:
            continue
        items.append(
            {
                "review_id": _review_id(review),
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "author": review.get("author"),
                "rating": review.get("rating"),
                "headline": review.get("headline"),
                "body": review.get("body"),
                "headline_cn": review.get("headline_cn"),
                "body_cn": review.get("body_cn"),
                "images": _review_images(review),
                "label_codes": [label["label_code"] for label in labels],
            }
        )
    items.sort(key=lambda item: ((item.get("rating") or 5), item.get("product_sku") or ""))
    return items[:5]


def _recommendations(analytics, validated_clusters):
    allowed = {item["label_code"]: item["review_count"] for item in validated_clusters}
    items = []
    for recommendation in (analytics.get("self") or {}).get("recommendations") or []:
        label_code = recommendation.get("label_code")
        if label_code not in allowed:
            continue
        item = dict(recommendation)
        item["evidence_count"] = allowed[label_code]
        items.append(item)
    return items


def run_llm_report_analysis(snapshot, analytics):
    # DEPRECATED: Superseded by generate_report_insights() which uses review_analysis table data.
    # Kept for backward compatibility with existing code paths.
    candidate_pools = build_candidate_pools(snapshot, analytics)
    llm_findings = {"classified_reviews": classify_candidate_pools(candidate_pools)}
    return {
        "candidate_pools": candidate_pools,
        "llm_findings": llm_findings,
        "report_copy": {},
    }


def validate_findings(snapshot, analytics, llm_result):
    # DEPRECATED: Superseded by generate_report_insights() which uses review_analysis table data.
    # Kept for backward compatibility with existing code paths.
    candidate_pools = (llm_result or {}).get("candidate_pools") or build_candidate_pools(snapshot, analytics)
    own_negative_candidates = candidate_pools.get("own_negative_candidates") or []
    competitor_positive_candidates = candidate_pools.get("competitor_positive_candidates") or []
    own_negative_image_candidates = candidate_pools.get("own_negative_image_candidates") or []
    competitor_negative_opportunity_candidates = candidate_pools.get("competitor_negative_opportunity_candidates") or []

    self_negative_clusters = _cluster_items(own_negative_candidates, "negative")
    competitor_positive_themes = _cluster_items(competitor_positive_candidates, "positive")
    own_image_evidence = []
    for review in own_negative_image_candidates:
        item = dict(review)
        item["images"] = _review_images(review)
        own_image_evidence.append(item)

    return {
        "self_negative_clusters": self_negative_clusters,
        "competitor_positive_themes": competitor_positive_themes,
        "own_image_evidence": own_image_evidence[:10],
        "competitor_negative_opportunities": _negative_opportunities(competitor_negative_opportunity_candidates),
        "competitor_benchmark_examples": _benchmark_examples(competitor_positive_candidates),
        "recommendations": _recommendations(analytics, self_negative_clusters),
    }


def merge_final_analytics(analytics, llm_result, validated_result):
    # DEPRECATED: Superseded by generate_report_insights() which uses review_analysis table data.
    # Kept for backward compatibility with existing code paths.
    merged = copy.deepcopy(analytics)
    merged.setdefault("self", {})
    merged.setdefault("competitor", {})
    merged.setdefault("appendix", {})

    merged["self"]["top_negative_clusters"] = validated_result.get("self_negative_clusters") or []
    merged["self"]["recommendations"] = validated_result.get("recommendations") or []
    merged["competitor"]["top_positive_themes"] = validated_result.get("competitor_positive_themes") or []
    merged["competitor"]["benchmark_examples"] = validated_result.get("competitor_benchmark_examples") or []
    merged["competitor"]["negative_opportunities"] = validated_result.get("competitor_negative_opportunities") or []
    merged["appendix"]["image_reviews"] = validated_result.get("own_image_evidence") or []
    merged["candidate_pools"] = (llm_result or {}).get("candidate_pools") or {}
    merged["llm_findings"] = (llm_result or {}).get("llm_findings") or {}
    merged["validated_findings"] = validated_result or {}
    merged["report_copy"] = (llm_result or {}).get("report_copy") or {}
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# New pipeline: generate_report_insights() — single LLM call for executive
# insights, replacing the deprecated candidate-pool workflow above.
# ══════════════════════════════════════════════════════════════════════════════


_INSIGHTS_KEYS = (
    "hero_headline",
    "executive_summary",
    "executive_bullets",
    "improvement_priorities",
    "competitive_insight",
)


def _build_insights_prompt(analytics):
    """Build a concise prompt summarizing analytics for LLM executive insights.

    Expects pre-normalized analytics with gap_analysis, enriched clusters, etc.
    """
    kpis = analytics.get("kpis", {})
    own_count = kpis.get("own_product_count", 0)
    comp_count = kpis.get("competitor_product_count", 0)
    total = kpis.get("ingested_review_rows", 0)
    neg = kpis.get("negative_review_rows", 0)
    rate = kpis.get("negative_review_rate", 0)
    health = kpis.get("health_index", "N/A")

    # Top issues with concrete symptoms from sub_features
    clusters = analytics.get("self", {}).get("top_negative_clusters", [])
    issue_lines = []
    for c in clusters[:8]:
        display = c.get("feature_display") or c.get("label_display", "")
        count = c.get("review_count", 0)
        sev = c.get("severity_display") or c.get("severity", "")
        line = f"  - {display}：{count} 条评论，严重度 {sev}"
        # Add top symptoms for product-specific context
        sub_features = c.get("sub_features") or []
        if sub_features:
            symptoms = "、".join(sf["feature"] for sf in sub_features[:5] if sf.get("feature"))
            if symptoms:
                line += f"（具体表现：{symptoms}）"
        issue_lines.append(line)
    issues_text = "\n".join(issue_lines) if issue_lines else "  暂无显著问题"

    # Recommendations with concrete symptoms
    recs = analytics.get("self", {}).get("recommendations", [])
    rec_lines = []
    for r in recs[:5]:
        top_symptoms = r.get("top_symptoms", "")
        symptom_text = f"（高频表现：{top_symptoms}）" if top_symptoms else ""
        rec_lines.append(
            f"  - {r.get('label_code', '')}{symptom_text}: "
            f"{r.get('improvement_direction', '')}"
        )
    recs_text = "\n".join(rec_lines) if rec_lines else "  暂无"

    # Gap analysis with rates (from pre-normalized data)
    gaps = analytics.get("competitor", {}).get("gap_analysis", [])
    gap_lines = []
    for g in gaps[:5]:
        gap_lines.append(
            f"  - {g.get('label_display', '')}：竞品好评率 {g.get('competitor_positive_rate', 0)}%"
            f"（{g.get('competitor_positive_count', 0)}/{g.get('competitor_total', 0)}），"
            f"自有差评率 {g.get('own_negative_rate', 0)}%"
            f"（{g.get('own_negative_count', 0)}/{g.get('own_total', 0)}），"
            f"差距指数 {g.get('gap_rate', 0)}"
        )
    gaps_text = "\n".join(gap_lines) if gap_lines else "  暂无明显差距"

    # Risk products
    risk_products = analytics.get("self", {}).get("risk_products", [])
    risk_lines = []
    for p in risk_products[:3]:
        risk_lines.append(
            f"  - {p.get('product_name', '')}：风险分 {p.get('risk_score', 0)}/100，"
            f"差评率 {(p.get('negative_rate') or 0) * 100:.0f}%，"
            f"主要问题 {p.get('top_features_display', '')}"
        )
    risk_text = "\n".join(risk_lines) if risk_lines else "  暂无高风险产品"

    return f"""你是一位高级产品分析师。基于以下产品评论分析数据，生成执行摘要和改良建议。
注意：你的分析必须基于下方提供的数据，不要编造数据或做无依据的推断。

数据概要：
- 自有产品 {own_count} 个，竞品 {comp_count} 个
- 总评论 {total} 条，差评 {neg} 条（差评率 {rate * 100:.1f}%）
- 健康指数：{health}/100

高风险产品：
{risk_text}

主要问题（按影响排序，含用户原话高频表现）：
{issues_text}

当前改进建议（含具体症状）：
{recs_text}

竞品差距（基于比率对比，差距指数 0-100，越高差距越大）：
{gaps_text}

请返回 JSON（不要包含 markdown 代码块标记）：
{{
  "hero_headline": "一句话核心结论（不超过40字，必须引用具体数据）",
  "executive_summary": "3-5句执行摘要，引用具体数字和产品名",
  "executive_bullets": ["要点1（含数据）", "要点2（含数据）", "要点3（含数据）"],
  "improvement_priorities": [
    {{"rank": 1, "target": "产品名", "issue": "引用上方具体症状", "action": "建议行动", "evidence_count": N}}
  ],
  "competitive_insight": "一段竞品洞察，必须引用差距指数和比率数据"
}}"""


def _fallback_insights(analytics):
    """Generate mechanical insights when LLM is unavailable."""
    from qbu_crawler.server.report_common import (
        _fallback_executive_bullets,
        _fallback_hero_headline,
        _humanize_bullets,
        normalize_deep_report_analytics,
    )

    # Ensure we have a normalized structure for the helper functions
    normalized = normalize_deep_report_analytics(analytics)
    return {
        "hero_headline": _fallback_hero_headline(normalized),
        "executive_summary": "",
        "executive_bullets": _humanize_bullets(normalized),
        "improvement_priorities": [],
        "competitive_insight": "",
    }


def _parse_llm_response(text):
    """Parse LLM response text into a dict, handling markdown code blocks."""
    text = text.strip()
    if not text:
        raise ValueError("LLM returned empty response")
    # Strip markdown code block if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("report_llm: raw JSON invalid, attempting repair")
        result = json.loads(repair_json(text))
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object, got {type(result).__name__}")
    return result


_MAX_HEADLINE_LEN = 80


def _validate_insights(llm_output: dict, analytics: dict) -> dict:
    """Cross-validate LLM output against actual analytics data."""
    result = dict(llm_output)

    # Cap headline length
    headline = result.get("hero_headline", "")
    if len(headline) > _MAX_HEADLINE_LEN:
        result["hero_headline"] = headline[:_MAX_HEADLINE_LEN - 1] + "\u2026"

    # Cap executive_bullets to 3
    bullets = result.get("executive_bullets") or []
    result["executive_bullets"] = bullets[:3]

    # Validate improvement_priorities evidence counts
    cluster_counts = {}
    for c in (analytics.get("self") or {}).get("top_negative_clusters") or []:
        code = c.get("label_code") or c.get("feature_display") or ""
        cluster_counts[code] = cluster_counts.get(code, 0) + (c.get("review_count") or 0)
    total_negative = sum(cluster_counts.values())

    for p in result.get("improvement_priorities") or []:
        try:
            claimed = int(p.get("evidence_count", 0) or 0)
        except (TypeError, ValueError):
            claimed = 0
        p["evidence_count"] = min(claimed, total_negative)

    return result


def generate_report_insights(analytics):
    """Generate executive summary, headline, and recommendations via LLM.

    Makes a SINGLE LLM call to produce executive-level insights from the
    already-computed analytics data (KPIs, issue clusters, gap analysis).

    Returns dict with keys: executive_summary, hero_headline,
    executive_bullets, improvement_priorities, competitive_insight.
    """
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        logger.info("LLM not configured, using fallback insights")
        return _fallback_insights(analytics)

    prompt = _build_insights_prompt(analytics)

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_API_BASE,
        )
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (response.choices[0].message.content or "").strip()
        result = _parse_llm_response(raw)

        # Validate required keys
        for key in _INSIGHTS_KEYS:
            if key not in result:
                result[key] = "" if key != "executive_bullets" and key != "improvement_priorities" else []

        # Ensure correct types
        if not isinstance(result.get("executive_bullets"), list):
            result["executive_bullets"] = []
        if not isinstance(result.get("improvement_priorities"), list):
            result["improvement_priorities"] = []

        return _validate_insights(result, analytics)

    except Exception:
        logger.warning("LLM insights generation failed, using fallback", exc_info=True)
        return _fallback_insights(analytics)
