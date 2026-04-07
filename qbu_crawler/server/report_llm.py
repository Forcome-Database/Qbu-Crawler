import copy
import json
import logging

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
    """Build a concise prompt summarizing analytics for LLM executive insights."""
    kpis = analytics.get("kpis", {})
    own_count = kpis.get("own_product_count", 0)
    comp_count = kpis.get("competitor_product_count", 0)
    total = kpis.get("ingested_review_rows", 0)
    neg = kpis.get("negative_review_rows", 0)
    rate = kpis.get("negative_review_rate", 0)
    health = kpis.get("health_index", "N/A")

    # Top issues
    clusters = analytics.get("self", {}).get("top_negative_clusters", [])
    issue_lines = []
    for c in clusters[:8]:
        display = c.get("feature_display") or c.get("label_display", "")
        count = c.get("review_count", 0)
        sev = c.get("severity_display") or c.get("severity", "")
        issue_lines.append(f"  - {display}：{count} 条评论，严重度 {sev}")
    issues_text = "\n".join(issue_lines) if issue_lines else "  暂无显著问题"

    # Gap analysis
    gaps = analytics.get("competitor", {}).get("gap_analysis", [])
    gap_lines = []
    for g in gaps[:5]:
        gap_lines.append(
            f"  - {g.get('label_display', '')}：竞品好评 {g.get('competitor_positive_count', 0)} 条，"
            f"自有差评 {g.get('own_negative_count', 0)} 条"
        )
    gaps_text = "\n".join(gap_lines) if gap_lines else "  暂无明显差距"

    return f"""你是一位高级产品分析师。基于以下产品评论分析数据，生成执行摘要和改良建议。

数据概要：
- 自有产品 {own_count} 个，竞品 {comp_count} 个
- 总评论 {total} 条，差评 {neg} 条（差评率 {rate * 100:.1f}%）
- 健康指数：{health}/100

主要问题（按影响排序）：
{issues_text}

竞品差距（我方短板 vs 竞品优势）：
{gaps_text}

请返回 JSON（不要包含 markdown 代码块标记）：
{{
  "hero_headline": "一句话核心结论（不超过40字）",
  "executive_summary": "3-5句执行摘要",
  "executive_bullets": ["第一条要点", "第二条要点", "第三条要点"],
  "improvement_priorities": [
    {{"rank": 1, "target": "产品名", "issue": "具体问题", "action": "建议行动", "evidence_count": N}}
  ],
  "competitive_insight": "一段竞品洞察"
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
    # Strip markdown code block if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


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
        claimed = p.get("evidence_count", 0) or 0
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
            temperature=0.3,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content or ""
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
