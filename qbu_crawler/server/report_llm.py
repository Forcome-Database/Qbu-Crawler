import copy
import json
import logging
import re
import time as _time

import jsonschema
from json_repair import repair_json

from qbu_crawler import config, models
from qbu_crawler.server import report_analytics
from qbu_crawler.server.report_common import BACKFILL_DOMINANT_RATIO

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# F011 H9+H14 — LLM prompt v3: JSON schema + tone guards + retry
# ══════════════════════════════════════════════════════════════════════════════


class SchemaError(ValueError):
    """LLM output failed JSON schema or string-length validation."""


class ToneGuardError(ValueError):
    """LLM hero copy violated tone guards (severe word with high health, etc.)."""


LLM_INSIGHTS_SCHEMA_V3 = {
    "type": "object",
    "required": ["hero_headline", "executive_summary", "executive_bullets", "improvement_priorities"],
    "properties": {
        "hero_headline":     {"type": "string", "maxLength": 100},
        "executive_summary": {"type": "string"},
        "executive_bullets": {"type": "array", "maxItems": 5,
                              "items": {"type": "string"}},
        "improvement_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label_code", "short_title", "full_action",
                             "evidence_count", "evidence_review_ids"],
                "properties": {
                    "label_code":     {"type": "string"},
                    "short_title":    {"type": "string", "maxLength": 30},
                    "full_action":    {"type": "string", "minLength": 80},
                    "evidence_count": {"type": "integer", "minimum": 0},
                    "evidence_review_ids": {"type": "array",
                                            "items": {"type": "integer"}},
                    "affected_products":   {"type": "array",
                                            "items": {"type": "string"}},
                },
            },
        },
        "competitive_insight": {"type": "string"},
    },
}

TONE_GUARDS_PROMPT = (
    "措辞规则（必须遵守）：\n"
    "1. 若 health_index ≥ 90，hero_headline 禁止使用 严重 / 侵蚀 / 重灾区 等强负面词；\n"
    "   改用 仍存在结构性短板 / 局部需要关注 等温和措辞。\n"
    "2. executive_bullets 中的所有数字必须能在 kpis / risk_products 中找到原始来源；\n"
    "   不得自行计算或外推。\n"
    "3. 若 high_risk_count = 0，禁止使用「高风险产品」作为主语。\n"
    "4. improvement_priorities[].short_title 必须 ≤ 20 字（中文计字）；\n"
    "   full_action 必须 ≥ 80 字。\n"
    "5. evidence_review_ids 必须从 input 中的 reviews 列表挑选实际存在的 id。\n"
)

SEVERE_WORDS = ("严重", "侵蚀", "重灾区")
HEALTH_HIGH_THRESHOLD = 90.0
SHORT_TITLE_MAX_CHARS = 20
EXECUTIVE_BULLET_MAX_ITEMS = 5


def _count_chinese_or_general_chars(text: str) -> int:
    """Return user-facing character count (treats CJK and ASCII as 1 unit each)."""
    return len(text or "")


def normalize_llm_copy_shape(llm_copy):
    result = copy.deepcopy(llm_copy or {})
    if not isinstance(result.get("hero_headline"), str):
        result["hero_headline"] = ""
    if not isinstance(result.get("executive_summary"), str):
        result["executive_summary"] = ""

    bullets = result.get("executive_bullets")
    if isinstance(bullets, str):
        bullets = [bullets]
    elif not isinstance(bullets, list):
        bullets = []
    result["executive_bullets"] = [
        str(item)
        for item in bullets[:EXECUTIVE_BULLET_MAX_ITEMS]
        if item is not None
    ]

    priorities = result.get("improvement_priorities")
    if not isinstance(priorities, list):
        priorities = []
    result["improvement_priorities"] = [
        item for item in priorities if isinstance(item, dict)
    ]

    competitive_insight = result.get("competitive_insight")
    if competitive_insight is not None and not isinstance(competitive_insight, str):
        result["competitive_insight"] = str(competitive_insight)
    return result


def validate_llm_copy(copy: dict) -> dict:
    """JSON-schema + character-length validation for v3 LLM output.

    Raises SchemaError on any failure. Returns the validated dict on success.
    """
    try:
        jsonschema.validate(copy, LLM_INSIGHTS_SCHEMA_V3)
    except jsonschema.ValidationError as e:
        raise SchemaError(str(e)) from e

    for item in copy.get("improvement_priorities", []) or []:
        title = item.get("short_title") or ""
        if _count_chinese_or_general_chars(title) > SHORT_TITLE_MAX_CHARS:
            raise SchemaError(
                f"short_title 超过 {SHORT_TITLE_MAX_CHARS} 字: {title!r}"
            )
    return copy


def validate_tone_guards(copy: dict, kpis: dict) -> None:
    """Apply tone-guard rules. Raises ToneGuardError on violation."""
    health = float(kpis.get("health_index") or 0)
    high_risk = int(kpis.get("high_risk_count") or 0)
    hero = copy.get("hero_headline") or ""

    if health >= HEALTH_HIGH_THRESHOLD:
        for word in SEVERE_WORDS:
            if word in hero:
                raise ToneGuardError(
                    f"health_index={health} (>= {HEALTH_HIGH_THRESHOLD}) "
                    f"不应在 hero 中使用 '{word}'"
                )

    if high_risk == 0 and "高风险产品" in hero:
        raise ToneGuardError(
            "high_risk_count=0 不应主语为'高风险产品'"
        )


_HEALTH_NUM_RE = re.compile(r"健康(?:指数|度)\s*([0-9]+(?:\.[0-9]+)?)")

# Matches standalone decimal or integer numbers.
# Uses negative lookbehind to avoid matching the integer part of ".75"-style
# product names (e.g. ".75 HP") where the dot is a non-word char before the digits.
NUMBER_RE = re.compile(r"(?<![.\d])([0-9]+(?:\.[0-9]+)?)\b")


def _assert_hero_health_match(copy: dict, kpis: dict) -> None:
    """Assert hero headline health number matches kpis['health_index'] within ±0.5."""
    hero = copy.get("hero_headline") or ""
    m = _HEALTH_NUM_RE.search(hero)
    if not m:
        return
    try:
        claimed = float(m.group(1))
    except (TypeError, ValueError):
        return
    actual = float(kpis.get("health_index") or 0)
    if abs(claimed - actual) > 0.5:
        raise AssertionError(
            f"hero claims health={claimed} but kpis health_index={actual}"
        )


def _collect_known_numbers(kpis: dict, risk_products=None, reviews=None, contract=None) -> set:
    """Collect all numeric values from kpis and risk_products into a set of floats.

    Includes:
    - All numeric values from kpis dict (rounded to 2 dp)
    - All numeric values from each risk_product dict (rounded to 2 dp)
    - len(reviews) and len(risk_products) as total counts
    """
    if risk_products is None and reviews is None and isinstance(kpis, dict) and (
        "kpis" in kpis or "report_user_contract" in kpis
    ):
        analytics = kpis
        kpis = analytics.get("kpis") or {}
        risk_products = (analytics.get("self") or {}).get("risk_products") or []
        reviews = analytics.get("reviews") or []
        contract = contract or analytics.get("report_user_contract") or {}
    risk_products = risk_products or []
    reviews = reviews or []
    contract = contract or {}
    known: set = set()

    def add_number(val):
        try:
            numeric = float(val)
            known.add(round(numeric, 2))
            if 0 < abs(numeric) <= 1:
                known.add(round(numeric * 100, 2))
        except (TypeError, ValueError):
            pass

    # All numeric kpi values
    for val in (kpis or {}).values():
        add_number(val)

    # All numeric values from risk products
    for product in risk_products:
        for val in product.values():
            add_number(val)

    for item in contract.get("action_priorities") or []:
        add_number(item.get("evidence_count"))
        add_number(item.get("affected_products_count"))
    for item in contract.get("issue_diagnostics") or []:
        add_number(item.get("evidence_count"))
        add_number(item.get("affected_products_count"))
    for section_items in (contract.get("competitor_insights") or {}).values():
        for item in section_items or []:
            add_number(item.get("evidence_count"))
            add_number(item.get("affected_products_count") or item.get("product_count"))
    baseline_summary = ((contract.get("bootstrap_digest") or {}).get("baseline_summary") or {})
    add_number(baseline_summary.get("product_count"))
    add_number(baseline_summary.get("review_count"))

    # Total counts
    known.add(float(len(reviews)))
    known.add(float(len(risk_products)))

    return known


def _assert_numbers_traceable(text: str, known_numbers: set, context_label: str) -> None:
    """Assert every number >= 2 in text can be traced to known_numbers.

    Tolerances:
    - absolute: ±0.5
    - relative: ≤1%

    Numbers < 2 are skipped (treated as ordinals like "Top 1", "Top 2").
    """
    for m in NUMBER_RE.finditer(text):
        if m.start() > 0 and text[m.start() - 1] == "#":
            continue
        try:
            num = float(m.group(1))
        except ValueError:
            continue
        if num < 2:
            continue  # ordinal / small count — skip
        # Check if num is within tolerance of any known number
        traceable = False
        for known in known_numbers:
            abs_diff = abs(num - known)
            if abs_diff <= 0.5:
                traceable = True
                break
            # relative tolerance: ≤1%
            if known != 0 and abs_diff / abs(known) <= 0.01:
                traceable = True
                break
        if not traceable:
            raise AssertionError(
                f"bullet 中数字 {num} 无法在 kpis/risk_products 中找到来源 "
                f"(context: {context_label!r})"
            )


_SENTINEL = object()  # sentinel to distinguish "not passed" from explicit empty list


def _build_llm_evidence_payload(analytics: dict) -> dict:
    contract = (analytics or {}).get("report_user_contract") or {}
    diagnostics = []
    for item in contract.get("issue_diagnostics") or []:
        diagnostics.append({
            "label_code": item.get("label_code"),
            "label_display": item.get("label_display"),
            "allowed_products": item.get("allowed_products") or item.get("affected_products") or [],
            "affected_products": item.get("affected_products") or [],
            "evidence_count": item.get("evidence_count") or len(item.get("evidence_review_ids") or []),
            "evidence_review_ids": item.get("evidence_review_ids") or [],
            "text_evidence": (item.get("text_evidence") or [])[:3],
            "image_evidence": (item.get("image_evidence") or [])[:3],
            "failure_modes": item.get("failure_modes") or [],
            "root_causes": item.get("root_causes") or [],
            "user_workarounds": item.get("user_workarounds") or [],
            "recommended_action": item.get("recommended_action") or item.get("ai_recommendation") or "",
        })
    return {
        "kpis": (analytics or {}).get("kpis") or {},
        "issue_diagnostics": diagnostics,
    }


def assert_consistency(
    copy: dict,
    kpis: dict,
    *,
    risk_products=_SENTINEL,
    reviews=_SENTINEL,
    allowed_products_by_label=None,
    all_product_names=None,
    contract=None,
) -> None:
    """Full numeric + structural assertion for LLM copy.

    Checks:
    1. hero health number matches kpis['health_index'] within ±0.5
    2. executive_bullets — every number must be traceable to kpis or risk_products
       (within ±0.5 absolute or ≤1% relative tolerance); numbers < 2 are skipped.
       **Only activated when risk_products or reviews are explicitly passed.**
    3. improvement_priorities[].evidence_count >= 1
    4. improvement_priorities[].evidence_review_ids must all be IDs present in reviews
    5. improvement_priorities[].affected_products must all be product names
       in the matching label's allowed product set, or all known products, or
       risk_products as a legacy fallback.

    Backward compatible: callers passing only (copy, kpis) skip bullet traceability
    and priority structure checks (Task 2.6 behavior is preserved).
    """
    # Determine whether extended checks are enabled (caller explicitly passed args)
    extended = risk_products is not _SENTINEL or reviews is not _SENTINEL
    _risk_products = [] if risk_products is _SENTINEL else (risk_products or [])
    _reviews = [] if reviews is _SENTINEL else (reviews or [])

    # 1. Hero health assertion (always active)
    _assert_hero_health_match(copy, kpis)

    if not extended:
        # Minimal Task 2.6 behavior: only hero health check
        return

    # Precompute known numbers for bullet traceability
    known_numbers = _collect_known_numbers(kpis, _risk_products, _reviews, contract=contract)

    # 2. executive_bullets numeric traceability
    for i, bullet in enumerate(copy.get("executive_bullets") or []):
        if not isinstance(bullet, str):
            continue
        _assert_numbers_traceable(bullet, known_numbers, f"bullet[{i}]: {bullet[:60]}")

    # Precompute valid review IDs and product names for priorities checks
    valid_review_ids: set = set()
    for r in _reviews:
        rid = r.get("id") or r.get("review_id")
        if rid is not None:
            valid_review_ids.add(rid)

    valid_product_names: set = {
        (p.get("product_name") or "").strip()
        for p in _risk_products
        if (p.get("product_name") or "").strip()
    }
    allowed_by_label = {}
    for code, names in (allowed_products_by_label or {}).items():
        allowed_by_label[code] = {
            (name or "").strip()
            for name in (names or [])
            if (name or "").strip()
        }
    all_known_products = {
        (name or "").strip()
        for name in (all_product_names or [])
        if (name or "").strip()
    }

    for i, priority in enumerate(copy.get("improvement_priorities") or []):
        if not isinstance(priority, dict):
            continue

        # 3. evidence_count >= 1
        evidence_count = int(priority.get("evidence_count") or 0)
        if evidence_count < 1:
            raise AssertionError(
                f"improvement_priorities[{i}].evidence_count must be >= 1, "
                f"got {evidence_count}"
            )

        # 4. evidence_review_ids must all be in valid review IDs
        if _reviews:  # only check if reviews were provided
            for rid in priority.get("evidence_review_ids") or []:
                if rid not in valid_review_ids:
                    raise AssertionError(
                        f"improvement_priorities[{i}].evidence_review_ids 包含"
                        f"未知 review id: {rid}"
                    )

        # 5. affected_products must be in the best available product scope.
        label_code = priority.get("label_code")
        allowed_product_names = allowed_by_label.get(label_code) or all_known_products or valid_product_names
        if allowed_product_names:
            for product_name in priority.get("affected_products") or []:
                if (product_name or "").strip() not in allowed_product_names:
                    raise AssertionError(
                        f"improvement_priorities[{i}].affected_products 包含"
                        f"未知产品名: {product_name!r}，"
                        f"应在允许产品集合中: {sorted(allowed_product_names)}"
                    )


def _build_insights_prompt_v3(analytics: dict, snapshot: dict | None = None) -> str:
    """v3 prompt: includes schema description + tone guards.

    Wraps the existing v2 prompt body and adds:
    - explicit JSON schema (v3 fields)
    - TONE_GUARDS_PROMPT
    - 'prompt_version: v3' tag
    """
    evidence_payload = _build_llm_evidence_payload(analytics)
    base = (
        "你是产品评论日报分析助手。只能使用下面 evidence_payload 中已经锁定的事实，"
        "不要引入未列出的产品、评论或问题簇。\n"
        f"evidence_payload:\n{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}\n"
    )
    schema_block = (
        "\n\nJSON 输出格式要求 v3（严格遵守）：\n"
        "executive_bullets <= 5; recommended 3. Do not enumerate every KPI; merge related metrics into concise decisions.\n"
        "{\n"
        '  "hero_headline": "...",\n'
        '  "executive_summary": "...",\n'
        '  "executive_bullets": ["..."],\n'
        '  "improvement_priorities": [\n'
        '    {\n'
        '      "label_code": "...",\n'
        '      "short_title": "≤20字一句话标题",\n'
        '      "full_action": "≥80字详细行动方案，含具体子步骤",\n'
        '      "evidence_count": 13,\n'
        '      "evidence_review_ids": [12, 34, 56],\n'
        '      "affected_products": ["..."]\n'
        '    }\n'
        '  ],\n'
        '  "competitive_insight": "..."\n'
        "}\n"
    )
    product_scope_guard = (
        "\n重要：improvement_priorities[].affected_products 必须来自对应 label_code "
        "在「主要问题」中列出的涉及产品；不要只限于高风险产品，也不要编造未出现的产品名。\n"
    )
    return f"{base}\n{schema_block}\n{product_scope_guard}\n{TONE_GUARDS_PROMPT}\n[prompt_version: v3]"


def generate_report_insights_with_validation(
    analytics: dict, snapshot: dict | None = None, *, max_retries: int = 3
) -> dict:
    """v3 orchestrator: prompt v3 → schema → tone → assertion → retry → fallback.

    On persistent failure, returns `_fallback_insights(analytics)`. Each retry
    uses exponential backoff (1s, 2s, 4s).
    """
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        logger.info("LLM not configured, using fallback insights (v3)")
        return _fallback_insights(analytics)

    kpis = analytics.get("kpis") or {}
    last_err: Exception | None = None

    for attempt in range(max_retries):
        try:
            from openai import OpenAI

            client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "user", "content": _build_insights_prompt_v3(analytics, snapshot=snapshot)}],
            )
            raw = (response.choices[0].message.content or "").strip()
            copy = _parse_llm_response(raw)
            copy = normalize_llm_copy_shape(copy)
            validate_llm_copy(copy)
            validate_tone_guards(copy, kpis)
            risk_products = (analytics.get("self") or {}).get("risk_products") or []
            reviews_for_check = (
                (analytics.get("self") or {}).get("reviews_with_ids")
                or analytics.get("reviews")
                or []
            )
            allowed_products_by_label = {}
            all_product_names = set()
            for product in risk_products:
                name = (product.get("product_name") or product.get("name") or "").strip()
                if name:
                    all_product_names.add(name)
            for cluster in (analytics.get("self") or {}).get("top_negative_clusters") or []:
                code = cluster.get("label_code")
                names = {
                    (name or "").strip()
                    for name in (cluster.get("affected_products") or cluster.get("products") or [])
                    if (name or "").strip()
                }
                if code and names:
                    allowed_products_by_label[code] = names
                    all_product_names.update(names)
            for product in (snapshot or {}).get("products") or []:
                name = (product.get("product_name") or product.get("name") or "").strip()
                if name:
                    all_product_names.add(name)
            assert_consistency(
                copy,
                kpis,
                risk_products=risk_products,
                reviews=reviews_for_check,
                allowed_products_by_label=allowed_products_by_label,
                all_product_names=all_product_names,
                contract=analytics.get("report_user_contract") or {},
            )
            copy["_prompt_version"] = "v3"
            return copy
        except (SchemaError, ToneGuardError, AssertionError) as e:
            last_err = e
            logger.warning(
                "LLM v3 attempt %d/%d failed: %s", attempt + 1, max_retries, e
            )
            _time.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            logger.warning(
                "LLM v3 attempt %d/%d non-validation error: %s",
                attempt + 1, max_retries, e,
            )
            _time.sleep(2 ** attempt)

    logger.error("LLM v3 generation failed after %d attempts: %s", max_retries, last_err)
    return _fallback_insights(analytics)


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
    "benchmark_takeaway",
)


def _report_semantics(analytics):
    return analytics.get("report_semantics") or (
        "bootstrap" if analytics.get("mode", "baseline") == "baseline" else "incremental"
    )


def _has_bootstrap_language_violation(result, analytics):
    if _report_semantics(analytics) != "bootstrap":
        return False

    priorities = result.get("improvement_priorities") or []
    texts = [
        result.get("hero_headline", ""),
        result.get("executive_summary", ""),
        result.get("competitive_insight", ""),
        result.get("benchmark_takeaway", ""),
        *[str(item) for item in (result.get("executive_bullets") or [])],
        *[str((p or {}).get("action", "")) for p in priorities],
    ]
    merged = "\n".join(texts)
    forbidden_patterns = (
        r"今日新增",  # forbidden_patterns 条目：禁止使用
        r"今日暴增",
        r"较昨日",
        r"较上期",
        r"环比",
        r"同比",
        r"今日.*新增",
        r"本日.*新增",
        r"新增\s*\d+\s*条\s*评论",   # generic fallback pattern — covers "新增 450 条评论" etc.
    )
    return any(re.search(pattern, merged) for pattern in forbidden_patterns)


# Relational-word correctness check (T0 hotfix, 2026-04-24).
# LLM was observed claiming a non-top risk SKU is "领跑" or that unequal cluster
# counts are "并列". _validate_insights only caps numbers; it does not verify
# ordering/comparison claims, so we add a conservative post-check here.
_RELATION_TOP_WORDS = (
    "领跑", "最高", "第一", "榜首", "首位", "登顶", "最严重",
    "核心风险", "首要风险", "重点风险", "最值得优先",
)
_RELATION_TIED_WORDS = ("并列", "打平", "持平")


def _check_relation_claims(result: dict, analytics: dict) -> list[str]:
    """Detect relational-word hallucinations in LLM output.

    Conservative: a violation is only emitted when evidence is definitive.
      - TOP word + a non-top SKU name appears in the same text, AND
        the actual top SKU name does NOT appear in that same text
      - TIED word + both top-2 cluster labels present in the text, AND
        their review_count values are not equal
    Returns empty list if nothing definitive was found.
    """
    risks = (analytics.get("self") or {}).get("risk_products") or []
    clusters = (analytics.get("self") or {}).get("top_negative_clusters") or []

    top_risk_name = (risks[0].get("product_name") or "").strip() if risks else ""
    non_top_risk_names = [
        (r.get("product_name") or "").strip()
        for r in risks[1:]
        if (r.get("product_name") or "").strip()
    ]

    texts: dict[str, str] = {
        "hero_headline": str(result.get("hero_headline", "") or ""),
        "executive_summary": str(result.get("executive_summary", "") or ""),
        "competitive_insight": str(result.get("competitive_insight", "") or ""),
        "benchmark_takeaway": str(result.get("benchmark_takeaway", "") or ""),
    }
    for idx, bullet in enumerate(result.get("executive_bullets") or []):
        texts[f"bullet_{idx}"] = str(bullet or "")
    for idx, priority in enumerate(result.get("improvement_priorities") or []):
        texts[f"priority_{idx}_action"] = str((priority or {}).get("action", "") or "")

    violations: list[str] = []
    for source, text in texts.items():
        if not text:
            continue

        if top_risk_name and non_top_risk_names:
            for word in _RELATION_TOP_WORDS:
                if word not in text:
                    continue
                if top_risk_name in text:
                    # Top SKU is explicitly mentioned; assume claim is about top.
                    continue
                for non_top in non_top_risk_names:
                    if non_top and non_top in text:
                        violations.append(
                            f"{source}: 关系词 '{word}' 指向非最高风险 SKU '{non_top}'，"
                            f"真实最高风险是 '{top_risk_name}'"
                        )
                        break

        if len(clusters) >= 2:
            c1 = clusters[0] or {}
            c2 = clusters[1] or {}
            c1_count = int(c1.get("review_count", 0) or 0)
            c2_count = int(c2.get("review_count", 0) or 0)
            if c1_count == c2_count:
                continue
            c1_label = (c1.get("label_display") or c1.get("label_code") or "").strip()
            c2_label = (c2.get("label_display") or c2.get("label_code") or "").strip()
            if not c1_label or not c2_label:
                continue
            for word in _RELATION_TIED_WORDS:
                if word in text and c1_label in text and c2_label in text:
                    violations.append(
                        f"{source}: '{word}' 声称 '{c1_label}'({c1_count}) 与 "
                        f"'{c2_label}'({c2_count}) 对等，实际不等"
                    )
                    break

    return violations


def _select_insight_samples(snapshot, analytics):
    """Select 15-20 diverse reviews for LLM synthesis from snapshot only.

    All samples come from snapshot["reviews"] to ensure consistency with KPI cards.
    Strategy: worst per risk product, image-bearing negatives, top competitor,
    mixed sentiment, most recent.
    """
    reviews = (
        (snapshot.get("cumulative") or {}).get("reviews")
        or snapshot.get("reviews", [])
    )
    if not reviews:
        return []

    risk_products = analytics.get("self", {}).get("risk_products", [])
    samples = []
    seen_ids = set()

    def _add(review_list, limit):
        added = 0
        for r in review_list:
            rid = r.get("id")
            if rid and rid not in seen_ids and len(samples) < 20:
                seen_ids.add(rid)
                samples.append(r)
                added += 1
                if added >= limit:
                    break

    # 1. Worst reviews per risk product (OWN products)
    risk_skus = [p.get("product_sku", "") for p in risk_products[:3] if p.get("product_sku")]
    for sku in risk_skus:
        sku_neg = sorted(
            [r for r in reviews
             if r.get("product_sku") == sku
             and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD],
            key=lambda r: r.get("rating") or 5,
        )
        _add(sku_neg, 2)

    # 2. Image-bearing own negatives
    img_neg = sorted(
        [r for r in reviews
         if r.get("ownership") == "own"
         and r.get("images")
         and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD],
        key=lambda r: r.get("rating") or 5,
    )
    _add(img_neg, 3)

    # 3. Top competitor reviews (5-star, most recent)
    comp_pos = sorted(
        [r for r in reviews
         if r.get("ownership") == "competitor"
         and (r.get("rating") or 0) >= 5],
        key=lambda r: r.get("scraped_at") or "",
        reverse=True,
    )
    _add(comp_pos, 3)

    # 4. Mixed sentiment
    mixed = [r for r in reviews if r.get("sentiment") == "mixed"]
    _add(mixed, 2)

    # 5. Most recent
    recent = sorted(
        reviews,
        key=lambda r: r.get("date_published_parsed") or "",
        reverse=True,
    )
    _add(recent, 2)

    return samples[:20]


def _build_insights_prompt(analytics, snapshot=None):
    """Build a concise prompt summarizing analytics for LLM executive insights.

    Expects pre-normalized analytics with gap_analysis, enriched clusters, etc.
    """
    kpis = analytics.get("kpis", {})
    own_count = kpis.get("own_product_count", 0)
    comp_count = kpis.get("competitor_product_count", 0)
    total = kpis.get("ingested_review_rows", 0)
    neg = kpis.get("negative_review_rows", 0)
    health = kpis.get("health_index", "N/A")
    # Own-specific KPIs (aligned with KPI cards)
    own_reviews = kpis.get("own_review_rows", 0)
    own_neg = kpis.get("own_negative_review_rows", 0)
    own_rate = kpis.get("own_negative_review_rate", 0)
    comp_reviews = kpis.get("competitor_review_rows", 0)
    report_semantics = _report_semantics(analytics)
    change_digest = analytics.get("change_digest") or {}

    # Top issues with concrete symptoms from sub_features
    clusters = analytics.get("self", {}).get("top_negative_clusters", [])
    issue_lines = []
    for c in clusters[:8]:
        label_code = c.get("label_code", "")
        display = c.get("feature_display") or c.get("label_display", "")
        count = c.get("review_count", 0)
        sev = c.get("severity_display") or c.get("severity", "")
        line = f"  - [{label_code}] {display}：{count} 条评论，严重度 {sev}"
        # Add top symptoms for product-specific context
        sub_features = c.get("sub_features") or []
        if sub_features:
            symptoms = "、".join(
                f"{sf['feature']}({sf['count']}条)" for sf in sub_features[:5] if sf.get("feature")
            )
            if symptoms:
                line += f"\n    高频表现：{symptoms}"
        affected = c.get("affected_products") or []
        if affected:
            line += f"\n    涉及产品：{'、'.join(affected[:3])}"
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
            f"维度差距指数 {g.get('gap_rate', 0)}"
        )
    gaps_text = "\n".join(gap_lines) if gap_lines else "  暂无明显差距"

    # Benchmark examples for competitive takeaway
    benchmarks = analytics.get("competitor", {}).get("benchmark_examples", [])
    if isinstance(benchmarks, dict):
        benchmarks = [
            item
            for key in ("product_design", "marketing_message", "service_model")
            for item in (benchmarks.get(key) or [])
        ]
    bench_lines = []
    for b in benchmarks[:2]:
        name = b.get("product_name", "")
        summary = b.get("summary_text", "")[:150]
        bench_lines.append(f"  - {name}: {summary}")
    bench_text = "\n".join(bench_lines) if bench_lines else "  暂无"

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

    prompt = f"""你是一位高级产品分析师。基于以下产品评论分析数据，生成执行摘要和改良建议。
注意：你的分析必须基于下方提供的数据，不要编造数据或做无依据的推断。

数据概要：
- 自有产品 {own_count} 个，竞品 {comp_count} 个
- 自有评论 {own_reviews} 条，自有差评 {own_neg} 条（自有差评率 {own_rate * 100:.1f}%）
- 全量评论 {total} 条（含竞品 {comp_reviews} 条），全量差评 {neg} 条
- 健康指数：{health}/100
- 竞品差距分：{analytics.get("kpis", {}).get("competitive_gap_index", "暂无")}/100（跨维度平均，原"总体竞品差距指数"）

高风险产品：
{risk_text}

主要问题（按影响排序，含用户原话高频表现）：
{issues_text}

当前改进建议（含具体症状）：
{recs_text}

竞品差距（基于比率对比，维度差距指数 0-100，越高差距越大）：
{gaps_text}

竞品高分样本（用于提炼竞品成功要素）：
{bench_text}

请返回 JSON（不要包含 markdown 代码块标记）：
{{
  "hero_headline": "一句话核心结论（不超过40字，必须引用自有产品数据，不要引用含竞品的全量数据）",
  "executive_summary": "3-5句执行摘要，引用具体数字和产品名",
  "executive_bullets": ["要点1（含数据）", "要点2（含数据）", "要点3（含数据）"],
  "improvement_priorities": [
    {{"label_code": "上方问题列表中方括号内的标识（如 packaging_shipping）", "action": "引用该类别的具体高频表现和涉及产品，给出针对性改进建议（如：针对 XX 产品的 YY 问题(N条)，建议...）", "evidence_count": N}}
  ],
  "competitive_insight": "一段竞品洞察，必须引用维度差距指数和比率数据",
  "benchmark_takeaway": "一段话总结竞品做对了什么，可供自有产品借鉴的具体做法"
}}

重要：improvement_priorities 中每条必须对应上方「主要问题」列表中的一个 label_code，action 必须针对该类别用户实际反馈的症状，不要张冠李戴。"""

    if report_semantics == "bootstrap":
        ingested_count = (change_digest.get("summary") or {}).get("ingested_review_count", total)
        prompt += "\n\n[report_semantics=bootstrap]"
        prompt += (
            "\n\n--- 报告语义 ---"
            f"\n当前是首次基线（监控起点），本次入库评论 {ingested_count} 条。"
            "\n不要写“今日新增”“较昨日”“较上期”“环比”等增量措辞，只能描述当前截面和监控起点。"
        )
    else:
        summary = change_digest.get("summary") or {}
        if summary:
            ingested = summary.get("ingested_review_count", total)
            fresh = summary.get("fresh_review_count", 0)
            backfill = summary.get("historical_backfill_count", 0)
            fresh_neg = summary.get("fresh_own_negative_count", 0)
            prompt += "\n\n--- 今日变化 ---"
            prompt += (
                f"\n本次入库评论 {ingested} 条"
                f"（近30天业务新增 {fresh} 条、历史补采 {backfill} 条）"
            )
            if fresh_neg > 0:
                prompt += (
                    f"\n其中自有近30天差评 {fresh_neg} 条，"
                    "请在 executive_bullets 中优先提示。"
                )
            if ingested > 0 and backfill / ingested >= BACKFILL_DOMINANT_RATIO:
                prompt += (
                    "\n⚠️ 本次入库以历史补采为主。禁止把补采评论计入业务新增，"
                    "不要使用「今日新增」或「暴增」等措辞。"
                )
            prompt += (
                "\n叙述请使用「本次入库」「近30天业务新增」，"
                "不要使用「今日新增」。"
            )

    # Low-sample warning (Stage B 修 10): 改读 change_digest.summary.fresh_review_count，
    # 避免 backfill-dominant 场景被 ingested/window 的大数掩盖业务真实新增不足。
    # bootstrap 不触发：首次基线本身就是基线，"样本不足"不是有意义的概念。
    if report_semantics != "bootstrap":
        _summary = (change_digest.get("summary") or {})
        _fresh_count = _summary.get("fresh_review_count", 0)
        if _fresh_count < 5:
            _count_phrase = (
                f"仅 {_fresh_count} 条" if _fresh_count > 0 else f"{_fresh_count} 条"
            )
            prompt += (
                f"\n\n⚠️ 本期近30天业务新增{_count_phrase}，样本极少。"
                "请仅基于上述数据做事实性记录，禁止做趋势推断或问题严重度判定。"
                "hero_headline 应体现「样本不足」或「数据有限」。"
            )

    # Fallback for dual-perspective incremental with zero fresh reviews —
    # the main "--- 今日变化 ---" section is already written above (change_digest branch).
    if report_semantics != "bootstrap" and analytics.get("perspective") == "dual" \
            and not (change_digest.get("summary") or {}).get("fresh_review_count", 0):
        prompt += (
            "\n\n本次入库近30天业务评论为 0。"
            "executive_bullets 应聚焦累积数据中的持续性问题。"
        )

    # Inject review samples for grounded insights
    if snapshot:
        sample_reviews = _select_insight_samples(snapshot, analytics)
        if sample_reviews:
            lines = []
            for r in sample_reviews:
                tag = "自有" if r.get("ownership") == "own" else "竞品"
                body = (r.get("body_cn") or r.get("body") or "")[:250]
                lines.append(
                    f"[{tag}|{r.get('product_name', '')}|{r.get('rating', '')}星] {body}"
                )
            prompt += (
                f"\n\n关键评论原文（{len(lines)}条，用于提炼洞察和引用客户语言）：\n"
                + "\n".join(lines)
                + "\n\n补充要求：hero_headline 必须反映评论中的核心客户体验痛点，不要只堆砌数字。"
            )

    return prompt


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
        "benchmark_takeaway": "",
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


def generate_report_insights(analytics, snapshot=None):
    """Generate executive summary, headline, and recommendations via LLM.

    Makes a SINGLE LLM call to produce executive-level insights from the
    already-computed analytics data (KPIs, issue clusters, gap analysis).

    Returns dict with keys: executive_summary, hero_headline,
    executive_bullets, improvement_priorities, competitive_insight.
    """
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        logger.info("LLM not configured, using fallback insights")
        return _fallback_insights(analytics)

    prompt = _build_insights_prompt(analytics, snapshot=snapshot)

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

        result = _validate_insights(result, analytics)
        if _has_bootstrap_language_violation(result, analytics):
            logger.warning("LLM insights violated bootstrap semantics, using fallback")
            return _fallback_insights(analytics)
        relation_violations = _check_relation_claims(result, analytics)
        if relation_violations:
            logger.warning(
                "LLM insights contain relational-word hallucinations (%d), using fallback: %s",
                len(relation_violations),
                "; ".join(relation_violations[:3]),
            )
            return _fallback_insights(analytics)
        return result

    except Exception:
        logger.warning("LLM insights generation failed, using fallback", exc_info=True)
        return _fallback_insights(analytics)


def analyze_cluster_deep(cluster, cluster_reviews):
    """LLM-powered root-cause analysis for a single issue cluster.

    Args:
        cluster: dict with label_code, label_display, review_count
        cluster_reviews: list of review dicts (from query_cluster_reviews)

    Returns dict with: failure_modes, root_causes, user_workarounds,
    actionable_summary. Returns None if LLM unavailable.

    F011 §4.2.3.1 v1.2 — ``temporal_pattern`` retired (template-y filler text,
    low signal value).
    """
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        return None
    if not config.REPORT_CLUSTER_ANALYSIS:
        return None
    if not cluster_reviews:
        return None

    review_lines = []
    for r in cluster_reviews[:30]:
        review_lines.append(
            f"[{r.get('rating', '')}星|{r.get('product_name', '')}|"
            f"{r.get('date_published_parsed', '')}] "
            f"{(r.get('body_cn') or r.get('body', ''))[:300]}"
        )
    reviews_text = "\n".join(review_lines)

    prompt = (
        f"你是产品质量分析专家。以下是 {cluster.get('review_count', 0)} 条关于"
        f"「{cluster.get('label_display', '')}」问题的用户评论"
        f"（展示前 {len(review_lines)} 条）。\n\n"
        f"{reviews_text}\n\n"
        "请分析并返回JSON（不要包含 markdown 代码块标记）：\n"
        "{\n"
        '  "failure_modes": [\n'
        '    {"mode": "具体失效模式描述", "frequency": 出现次数估计, '
        '"severity": "critical/major/minor", '
        '"example_quote": "最能说明此失效的一句用户原话"}\n'
        "  ],\n"
        '  "root_causes": [\n'
        '    {"cause": "推测根因", "evidence": "从评论推断的依据", '
        '"confidence": "high/medium/low"}\n'
        "  ],\n"
        '  "user_workarounds": ["用户自行采取的应对方法"],\n'
        '  "actionable_summary": "不超过2句话：这个问题的本质是什么，最高优先的改进动作是什么"\n'
        "}\n\n"
        "注意：failure_modes 按 frequency 降序排列，"
        "每个必须有 example_quote 直接引用评论原文。"
    )

    try:
        from openai import OpenAI

        client = OpenAI(base_url=config.LLM_API_BASE, api_key=config.LLM_API_KEY)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _parse_llm_response(raw)
        return _validate_cluster_analysis(parsed)
    except Exception as e:
        logger.warning("analyze_cluster_deep failed for %s: %s", cluster.get("label_code"), e)
        return None


def _validate_cluster_analysis(parsed):
    """Validate and sanitize cluster analysis output."""
    if not isinstance(parsed, dict):
        return None
    # F011 §4.2.3.1 v1.2 — ``temporal_pattern`` retired; ignore it even if
    # an upstream LLM still returns it.
    result = {
        "failure_modes": parsed.get("failure_modes", []),
        "root_causes": parsed.get("root_causes", []),
        "user_workarounds": parsed.get("user_workarounds", []),
        "actionable_summary": parsed.get("actionable_summary", ""),
    }
    # Type guards for lists
    if not isinstance(result["failure_modes"], list):
        result["failure_modes"] = []
    if not isinstance(result["root_causes"], list):
        result["root_causes"] = []
    if not isinstance(result["user_workarounds"], list):
        result["user_workarounds"] = []
    # Type guards for strings
    if not isinstance(result["actionable_summary"], str):
        result["actionable_summary"] = ""
    # Filter non-dict elements from lists and cap lengths
    result["failure_modes"] = [m for m in result["failure_modes"] if isinstance(m, dict)][:10]
    result["root_causes"] = [m for m in result["root_causes"] if isinstance(m, dict)][:5]
    result["user_workarounds"] = [w for w in result["user_workarounds"] if isinstance(w, str)][:5]
    return result
