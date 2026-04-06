"""Shared constants and helper functions used by report.py and report_pdf.py."""

import json
import os

from qbu_crawler import config
from qbu_crawler.server import report_analytics

# ── Display-name mappings ─────────────────────────────────────────────────────

_LABEL_DISPLAY = {
    "quality_stability": "质量稳定性",
    "structure_design": "结构设计",
    "assembly_installation": "安装装配",
    "material_finish": "材料与做工",
    "cleaning_maintenance": "清洁维护",
    "noise_power": "噪音与动力",
    "packaging_shipping": "包装运输",
    "service_fulfillment": "售后与履约",
    "easy_to_use": "易上手",
    "solid_build": "做工扎实",
    "good_value": "性价比高",
    "easy_to_clean": "易清洗",
    "strong_performance": "性能强",
    "good_packaging": "包装到位",
}

_PRIORITY_DISPLAY = {"high": "高", "medium": "中", "low": "低"}
_SEVERITY_DISPLAY = {"high": "高", "medium": "中", "low": "低"}


# ── Helper functions ──────────────────────────────────────────────────────────


def _label_display(label_code):
    return _LABEL_DISPLAY.get(label_code or "", label_code or "")


def _join_label_counts(items):
    values = []
    for item in items or []:
        label_code = item.get("label_code")
        if not label_code:
            continue
        values.append(f"{_label_display(label_code)}({item.get('count') or 0})")
    return "、".join(values) or "暂无"


def _join_label_codes(label_codes):
    values = [_label_display(label_code) for label_code in label_codes or [] if label_code]
    return "、".join(values) or "暂无"


def _summary_text(item):
    title = (item.get("headline_cn") or item.get("headline") or "").strip()
    body = (item.get("body_cn") or item.get("body") or "").strip()
    if title and body:
        return f"{title}：{body}"
    return title or body or "暂无摘要"


def _derive_review_label_codes(review):
    label_codes = [item for item in (review.get("label_codes") or []) if item]
    if label_codes:
        return label_codes
    labels = report_analytics.classify_review_labels(review)
    ownership = review.get("ownership") or ""
    preferred = "negative" if ownership == "own" else "positive"
    preferred_codes = [item["label_code"] for item in labels if item.get("label_polarity") == preferred]
    if preferred_codes:
        return preferred_codes[:3]
    return [item["label_code"] for item in labels[:3]]


# ── Competitor gap analysis ──────────────────────────────────────────────────


def _competitor_gap_analysis(normalized):
    """Find themes where competitors are praised but our products are criticised."""
    comp_positive = {
        t["label_code"]: t
        for t in normalized.get("competitor", {}).get("top_positive_themes", [])
    }
    own_negative = {
        c["label_code"]: c
        for c in normalized.get("self", {}).get("top_negative_clusters", [])
    }
    gap_codes = set(comp_positive) & set(own_negative)
    gaps = []
    for code in gap_codes:
        gaps.append({
            "label_code": code,
            "label_display": _LABEL_DISPLAY.get(code, code),
            "competitor_positive_count": comp_positive[code].get("review_count", 0),
            "own_negative_count": own_negative[code].get("review_count", 0),
        })
    return sorted(gaps, key=lambda g: g["own_negative_count"], reverse=True)


# ── KPI delta computation ───────────────────────────────────────────────────


def _compute_kpi_deltas(current_kpis, prev_analytics):
    """Compute difference between current KPIs and those from a previous report."""
    if not prev_analytics:
        return {}
    prev_kpis = prev_analytics.get("kpis", {})
    deltas = {}
    for key in ("negative_review_rows", "ingested_review_rows", "product_count"):
        curr = current_kpis.get(key, 0) or 0
        prev = prev_kpis.get(key, 0) or 0
        diff = curr - prev
        deltas[f"{key}_delta"] = diff
        deltas[f"{key}_delta_display"] = (
            f"+{diff}" if diff > 0 else str(diff)
        ) if diff != 0 else "—"
    return deltas


# ── Hero page helpers ──────────────────────────────────────────────────────


def _generate_hero_headline(normalized):
    """Generate a data-driven hero headline from *normalized* analytics."""
    top = (normalized.get("self", {}).get("risk_products") or [None])[0]
    if not top:
        # No own-product risk data — fall back to competitor themes
        themes = normalized.get("competitor", {}).get("top_positive_themes") or []
        if themes:
            return f"当前竞品最稳定的用户认可点集中在{themes[0].get('label_display', '')}。"
        return "当前样本不足以形成明确主结论，建议继续积累样本后再判读。"

    top_labels = top.get("top_labels") or []
    cluster_code = top_labels[0].get("label_code") if top_labels else ""
    cluster_name = _LABEL_DISPLAY.get(cluster_code, cluster_code)

    neg_delta = normalized.get("kpis", {}).get("negative_review_rows_delta")
    total_reviews = top.get("total_reviews") or 0
    neg_count = top.get("negative_review_rows", 0)

    if neg_delta and neg_delta > 0:
        rate_word = "环比增加" if neg_delta < 10 else "环比激增"
        return f"本期最高风险：{top['product_name']} {cluster_name}问题{rate_word} {neg_delta} 条，需优先跟进。"
    elif total_reviews > 0:
        pct = neg_count / total_reviews
        return f"自有产品 {top['product_name']} 差评率 {pct:.0%}，{cluster_name}问题集中。"
    else:
        return f"自有产品 {top['product_name']} 的{cluster_name}问题最值得优先处理。"


def _compute_alert_level(normalized):
    """Return ``(level, text)`` where *level* is ``"red"``/``"yellow"``/``"green"``."""
    top_neg = normalized.get("self", {}).get("top_negative_clusters") or []
    high_sev = [c for c in top_neg if c.get("severity") == "high" and (c.get("review_count") or 0) >= 5]
    delta = normalized.get("kpis", {}).get("negative_review_rows_delta", 0) or 0
    health = normalized.get("kpis", {}).get("health_index")

    # Red conditions
    if high_sev or delta >= 10:
        return "red", "存在高严重度问题簇，建议今日跟进"
    if health is not None and health < config.HEALTH_RED:
        return "red", f"健康指数 {health} 低于警戒线 {config.HEALTH_RED}，建议今日跟进"

    # Yellow conditions
    if delta > 0:
        return "yellow", "差评数较上期有所上升，请持续关注"
    if health is not None and health < config.HEALTH_YELLOW:
        return "yellow", f"健康指数 {health} 偏低，请持续关注"

    return "green", "无新增高风险信号"


def _humanize_bullets(normalized):
    """Generate up to 3 natural-language conclusions for the executive summary."""
    bullets = []
    # Bullet 1: highest-risk product — negative rate and delta
    top = (normalized.get("self", {}).get("risk_products") or [None])[0]
    if top:
        top_labels = top.get("top_labels") or []
        cluster_code = top_labels[0].get("label_code") if top_labels else ""
        cluster_name = _LABEL_DISPLAY.get(cluster_code, cluster_code)
        total = top.get("total_reviews") or 0
        neg = top.get("negative_review_rows", 0)
        rate_str = f"（差评率 {neg/total:.0%}）" if total else ""
        neg_delta = normalized.get("kpis", {}).get("negative_review_rows_delta", 0) or 0
        delta_str = f"，较上期新增 {neg_delta} 条" if neg_delta > 0 else ""
        bullets.append(
            f"自有产品 {top['product_name']} 累计 {neg} 条差评"
            f"{rate_str}，问题集中在{cluster_name}{delta_str}"
        )

    # Bullet 2: competitor comparison — prefer gap analysis
    gaps = normalized.get("competitor", {}).get("gap_analysis") or []
    themes = normalized.get("competitor", {}).get("top_positive_themes") or []
    if gaps:
        g = gaps[0]
        bullets.append(
            f"竞品在{g['label_display']}方面好评 {g['competitor_positive_count']} 条，"
            f"同期自有同维度差评 {g['own_negative_count']} 条，存在差距"
        )
    elif themes:
        bullets.append(
            f"竞品好评聚焦在{themes[0].get('label_display', '')}（{themes[0].get('review_count', 0)} 条）"
        )

    # Bullet 3: coverage summary — show translation warning only if abnormal
    kpis = normalized.get("kpis", {})
    translation_rate = kpis.get("translation_completion_rate") or 1.0
    if translation_rate < 0.7:
        bullets.append(
            f"注意：{kpis.get('untranslated_count', 0)} 条评论翻译未完成，中文分析可能不完整"
        )
    else:
        bullets.append(
            f"本期覆盖 {kpis.get('product_count', 0)} 个产品、{kpis.get('ingested_review_rows', 0)} 条评论"
        )
    return bullets[:3]


# ── Health & competitive gap indices ─────────────────────────────────────────


def compute_health_index(analytics: dict) -> float:
    """Compute 0-100 health index. Higher = healthier."""
    kpis = analytics.get("kpis", {})
    own_count = kpis.get("own_product_count", 0) or 1

    avg_rating = kpis.get("own_avg_rating", 0) or 0
    rating_score = min(avg_rating / 5.0, 1.0)

    # Use own-only negative rate (not polluted by competitor reviews)
    neg_rate = kpis.get("own_negative_review_rate") or kpis.get("negative_review_rate", 0) or 0
    neg_score = 1.0 - min(neg_rate, 1.0)

    high_risk_count = sum(
        1 for p in analytics.get("self", {}).get("risk_products", [])
        if p.get("risk_score", 0) >= config.HIGH_RISK_THRESHOLD
    )
    risk_ratio = high_risk_count / max(own_count, 1)
    risk_score = 1.0 - min(risk_ratio, 1.0)

    index = (rating_score * 0.40 + neg_score * 0.35 + risk_score * 0.25) * 100
    return round(max(0, min(100, index)), 1)


def compute_competitive_gap_index(gap_analysis: list[dict]) -> int:
    """Scalar competitive gap index: sum of all dimension gaps."""
    return sum(
        (g.get("competitor_positive_count", 0) + g.get("own_negative_count", 0))
        for g in gap_analysis
    )


# ── Previous analytics loader ───────────────────────────────────────────────


def _load_previous_analytics(current_run_id):
    """Load the analytics JSON from the most recent completed run before *current_run_id*."""
    if not current_run_id:
        return None
    try:
        from qbu_crawler import models
        prev_run = models.get_previous_completed_run(current_run_id)
    except Exception:
        return None
    if not prev_run or not prev_run.get("analytics_path"):
        return None
    path = prev_run["analytics_path"]
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── normalize_deep_report_analytics ──────────────────────────────────────────


def _fallback_hero_headline(normalized):
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    top_cluster = (normalized["self"]["top_negative_clusters"] or [None])[0]
    if top_product and top_cluster:
        return (
            f"自有产品 {top_product.get('product_name')} 的{top_cluster.get('label_display')}问题最值得优先处理。"
        )
    if top_product:
        return f"自有产品 {top_product.get('product_name')} 当前风险最高，建议优先排查。"
    if normalized["competitor"]["top_positive_themes"]:
        return (
            f"当前竞品用户认可以 {normalized['competitor']['top_positive_themes'][0].get('label_display')} 为主。"
        )
    return "当前样本不足以形成明确主结论，建议继续积累样本后再判断。"


def _fallback_executive_bullets(normalized):
    bullets = []
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    if top_product:
        product_name = top_product.get("product_name") or "自有产品"
        product_sku = top_product.get("product_sku") or ""
        sku_text = f"（SKU: {product_sku}）" if product_sku else ""
        bullets.append(
            f"{product_name}{sku_text}：{top_product.get('top_labels_display') or '暂无主要问题'}"
        )
    top_theme = (normalized["competitor"]["top_positive_themes"] or [None])[0]
    if top_theme:
        bullets.append(
            f"{top_theme.get('label_display')}：{top_theme.get('review_count') or 0} 条"
        )
    top_opportunity = (normalized["competitor"]["negative_opportunities"] or [None])[0]
    if top_opportunity:
        product_name = top_opportunity.get("product_name") or "竞品"
        product_sku = top_opportunity.get("product_sku") or ""
        sku_text = f"（SKU: {product_sku}）" if product_sku else ""
        bullets.append(
            f"{product_name}{sku_text}：{top_opportunity.get('label_display_list') or '暂无主要短板'}"
        )
    if not bullets:
        bullets.append(
            f"当前纳入分析产品 {normalized['kpis']['product_count']} 个，新增评论 {normalized['kpis']['ingested_review_rows']} 条。"
        )
    return bullets[:3]


def normalize_deep_report_analytics(analytics):
    analytics = analytics or {}
    normalized = {
        "mode": analytics.get("mode", "baseline"),
        "mode_display": "首日全量基线版" if analytics.get("mode", "baseline") == "baseline" else "增量监测版",
        "baseline_sample_days": analytics.get("baseline_sample_days", 0),
        "metric_semantics": {
            "ingested_review_rows": "reviews 实际入库行数",
            "site_reported_review_total_current": "products.review_count 当前站点展示总评论数",
            **(analytics.get("metric_semantics") or {}),
        },
        "report_copy": {
            "hero_headline": "",
            "executive_bullets": [],
            **(analytics.get("report_copy") or {}),
        },
        "kpis": {
            "product_count": 0,
            "ingested_review_rows": 0,
            "site_reported_review_total_current": 0,
            "translated_count": 0,
            "untranslated_count": 0,
            "own_product_count": 0,
            "competitor_product_count": 0,
            "own_review_rows": 0,
            "competitor_review_rows": 0,
            "image_review_rows": 0,
            "low_rating_review_rows": 0,
            "negative_review_rows": 0,
            **(analytics.get("kpis") or {}),
        },
        "self": {
            "risk_products": [],
            "top_negative_clusters": [],
            "recommendations": [],
            **(analytics.get("self") or {}),
        },
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            **(analytics.get("competitor") or {}),
        },
        "appendix": {
            "image_reviews": [],
            "coverage": {
                "own_products": 0,
                "competitor_products": 0,
                "own_reviews": 0,
                "competitor_reviews": 0,
                **((analytics.get("appendix") or {}).get("coverage") or {}),
            },
            **{
                key: value
                for key, value in (analytics.get("appendix") or {}).items()
                if key != "coverage"
            },
        },
        **{
            key: value
            for key, value in analytics.items()
            if key not in {"metric_semantics", "report_copy", "kpis", "self", "competitor", "appendix"}
        },
    }

    ingested_review_rows = normalized["kpis"].get("ingested_review_rows") or 0
    negative_review_rows = normalized["kpis"].get("negative_review_rows")
    if negative_review_rows is None:
        negative_review_rows = normalized["kpis"].get("low_rating_review_rows") or 0
    translated_count = normalized["kpis"].get("translated_count") or 0
    normalized["kpis"]["negative_review_rows"] = negative_review_rows
    normalized["kpis"]["negative_review_rate"] = (
        negative_review_rows / ingested_review_rows if ingested_review_rows else 0
    )
    normalized["kpis"]["negative_review_rate_display"] = (
        f"{normalized['kpis']['negative_review_rate'] * 100:.1f}%"
    )
    normalized["kpis"]["translation_completion_rate"] = (
        translated_count / ingested_review_rows if ingested_review_rows else 0
    )
    normalized["kpis"]["translation_completion_rate_display"] = (
        f"{normalized['kpis']['translation_completion_rate'] * 100:.1f}%"
    )

    negative_clusters = []
    for item in normalized["self"]["top_negative_clusters"]:
        cluster = dict(item)
        cluster["label_display"] = _label_display(cluster.get("label_code"))
        cluster["severity_display"] = _SEVERITY_DISPLAY.get(cluster.get("severity"), cluster.get("severity") or "")
        examples = []
        for example in cluster.get("example_reviews") or []:
            record = dict(example)
            record["summary_text"] = _summary_text(record)
            record["primary_image"] = (record.get("images") or [None])[0]
            examples.append(record)
        cluster["example_reviews"] = examples
        negative_clusters.append(cluster)
    normalized["self"]["top_negative_clusters"] = negative_clusters

    recommendations = []
    for item in normalized["self"]["recommendations"]:
        recommendation = dict(item)
        recommendation["label_display"] = _label_display(recommendation.get("label_code"))
        recommendation["priority_display"] = _PRIORITY_DISPLAY.get(
            recommendation.get("priority"),
            recommendation.get("priority") or "",
        )
        recommendations.append(recommendation)
    normalized["self"]["recommendations"] = recommendations

    positive_themes = []
    for item in normalized["competitor"]["top_positive_themes"]:
        theme = dict(item)
        theme["label_display"] = _label_display(theme.get("label_code"))
        positive_themes.append(theme)
    normalized["competitor"]["top_positive_themes"] = positive_themes

    benchmark_examples = []
    for item in normalized["competitor"]["benchmark_examples"]:
        example = dict(item)
        example["label_display_list"] = _join_label_codes(example.get("label_codes") or [])
        example["summary_text"] = _summary_text(example)
        benchmark_examples.append(example)
    normalized["competitor"]["benchmark_examples"] = benchmark_examples

    opportunities = []
    for item in normalized["competitor"]["negative_opportunities"]:
        opportunity = dict(item)
        opportunity["label_display_list"] = _join_label_codes(opportunity.get("label_codes") or [])
        opportunity["summary_text"] = _summary_text(opportunity)
        opportunities.append(opportunity)
    normalized["competitor"]["negative_opportunities"] = opportunities

    image_reviews = []
    evidence_refs_by_sku = {}
    evidence_refs_by_label = {}
    for index, item in enumerate(normalized["appendix"]["image_reviews"][:10], start=1):
        review = dict(item)
        images = review.get("images") or []
        label_codes = _derive_review_label_codes(review)
        review["label_codes"] = label_codes
        review["label_display_list"] = _join_label_codes(label_codes)
        review["primary_image"] = images[0] if images else None
        review["headline_display"] = review.get("headline_cn") or review.get("headline") or "图片证据"
        review["body_display"] = review.get("body_cn") or review.get("body") or ""
        review["evidence_id"] = f"E{index}"
        review["supports_text"] = (
            f"支撑结论：{review['label_display_list']}" if label_codes else "支撑结论：自有产品差评判断"
        )
        product_key = review.get("product_sku") or review.get("product_name") or ""
        if product_key:
            evidence_refs_by_sku.setdefault(product_key, []).append(review["evidence_id"])
        for label_code in label_codes:
            evidence_refs_by_label.setdefault(label_code, []).append(review["evidence_id"])
        image_reviews.append(review)
    normalized["appendix"]["image_reviews"] = image_reviews

    risk_products = []
    for item in normalized["self"]["risk_products"]:
        product = dict(item)
        product["top_labels_display"] = _join_label_counts(product.get("top_labels") or [])
        evidence_refs = evidence_refs_by_sku.get(product.get("product_sku") or product.get("product_name") or "", [])
        product["evidence_refs"] = evidence_refs
        product["evidence_refs_display"] = "、".join(evidence_refs) or "暂无图片证据"
        product["focus_summary"] = ""
        for cluster in normalized["self"]["top_negative_clusters"]:
            for example in cluster.get("example_reviews") or []:
                if example.get("product_sku") == product.get("product_sku"):
                    product["focus_summary"] = example.get("summary_text") or ""
                    break
            if product["focus_summary"]:
                break
        risk_products.append(product)
    normalized["self"]["risk_products"] = risk_products

    for item in normalized["self"]["top_negative_clusters"]:
        evidence_refs = evidence_refs_by_label.get(item.get("label_code"), [])
        item["evidence_refs"] = evidence_refs
        item["evidence_refs_display"] = "、".join(evidence_refs) or "暂无图片证据"

    for item in normalized["self"]["recommendations"]:
        evidence_refs = evidence_refs_by_label.get(item.get("label_code"), [])
        item["evidence_refs"] = evidence_refs
        item["evidence_refs_display"] = "、".join(evidence_refs) or "暂无图片证据"

    normalized["competitor"]["benchmark_takeaways"] = [
        f"用户持续认可{item.get('label_display')}体验。"
        for item in normalized["competitor"]["top_positive_themes"][:3]
    ]

    # ── Compute gap analysis ──────────────────────────────────────────────
    if "gap_analysis" not in normalized.get("competitor", {}):
        normalized["competitor"]["gap_analysis"] = _competitor_gap_analysis(normalized)

    # ── Compute health_index, competitive_gap_index, high_risk_count ─────
    normalized["kpis"]["health_index"] = compute_health_index(normalized)
    normalized["kpis"]["competitive_gap_index"] = compute_competitive_gap_index(
        normalized.get("competitor", {}).get("gap_analysis") or []
    )
    normalized["kpis"]["high_risk_count"] = sum(
        1 for p in normalized.get("self", {}).get("risk_products", [])
        if p.get("risk_score", 0) >= config.HIGH_RISK_THRESHOLD
    )

    # ── Build kpi_cards for template ─────────────────────────────────────
    kpis = normalized["kpis"]
    kpi_cards = [
        {
            "label": "健康指数",
            "value": kpis.get("health_index", "—"),
            "delta_display": kpis.get("health_index_delta_display", ""),
            "delta_class": "neutral",
        },
        {
            "label": "差评率",
            "value": kpis.get("negative_review_rate_display", "—"),
            "delta_display": kpis.get("negative_review_rows_delta_display", ""),
            "delta_class": "up" if (kpis.get("negative_review_rows_delta", 0) or 0) > 0 else "neutral",
        },
        {
            "label": "评论总数",
            "value": kpis.get("ingested_review_rows", 0),
            "delta_display": kpis.get("ingested_review_rows_delta_display", ""),
            "delta_class": "neutral",
        },
        {
            "label": "高风险产品",
            "value": kpis.get("high_risk_count", 0),
            "delta_display": "",
            "delta_class": "up" if kpis.get("high_risk_count", 0) > 0 else "neutral",
        },
        {
            "label": "竞品差距指数",
            "value": kpis.get("competitive_gap_index", "—"),
            "delta_display": kpis.get("competitive_gap_index_delta_display", ""),
            "delta_class": "neutral",
        },
    ]
    normalized["kpi_cards"] = kpi_cards

    # ── Build issue_cards from top_negative_clusters ─────────────────────
    issue_cards = []
    for cluster in normalized["self"]["top_negative_clusters"]:
        issue_cards.append({
            "feature_display": cluster.get("feature_display") or cluster.get("label_display", ""),
            "label_display": cluster.get("label_display", ""),
            "review_count": cluster.get("review_count", 0),
            "severity": cluster.get("severity", "low"),
            "severity_display": cluster.get("severity_display", ""),
            "affected_product_count": cluster.get("affected_product_count", 0),
        })
    normalized["self"]["issue_cards"] = issue_cards

    if not normalized["report_copy"]["hero_headline"]:
        normalized["report_copy"]["hero_headline"] = _fallback_hero_headline(normalized)
    if not normalized["report_copy"]["executive_bullets"]:
        normalized["report_copy"]["executive_bullets"] = _fallback_executive_bullets(normalized)

    return normalized
