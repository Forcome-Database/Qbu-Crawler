"""Shared constants and helper functions used by report.py and report_html.py."""

import calendar
import json
import os
import re
from datetime import date, datetime, timedelta

from qbu_crawler import config
from qbu_crawler.server import report_analytics

# ── Safety Tier Detection ────────────────────────────────────────────────────

_BUILTIN_SAFETY_TIERS = {
    "critical": [
        "metal shaving", "metal debris", "metal particle", "metal flake",
        "grease in food", "oil contamination", "black substance",
        "contamina", "foreign object", "foreign material",
        "injury", "injured", "cut myself", "sliced finger",
        "burned", "electric shock", "exploded", "shattered",
    ],
    "high": [
        "rust on blade", "rust on plate", "rusty", "corrosion",
        "worn blade", "chipped blade", "blade broke",
        "motor overheating", "smoking", "burning smell",
        "seal failure", "leaking grease",
    ],
    "moderate": [
        "misaligned", "not aligned", "loose screw",
        "bolt came off", "wobbles", "tips over", "unstable",
    ],
}

_SAFETY_TIER_ORDER = ["critical", "high", "moderate"]


def load_safety_tiers(path: str | None = None) -> dict:
    """Load safety tier keywords from JSON file, falling back to built-in defaults."""
    path = path or getattr(config, "SAFETY_TIERS_PATH", None)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    return _BUILTIN_SAFETY_TIERS


_safety_tiers_cache: dict | None = None


def get_safety_tiers() -> dict:
    global _safety_tiers_cache
    if _safety_tiers_cache is None:
        _safety_tiers_cache = load_safety_tiers()
    return _safety_tiers_cache


def detect_safety_level(text: str) -> str | None:
    """Return highest matching safety tier ('critical'/'high'/'moderate') or None."""
    text_lower = text.lower()
    tiers = get_safety_tiers()
    for level in _SAFETY_TIER_ORDER:
        keywords = tiers.get(level, [])
        if any(kw in text_lower for kw in keywords):
            return level
    return None


def check_label_consistency(sentiment_score: float, labels: list[dict]) -> list[dict]:
    """Detect mismatches between sentiment_score and label polarity."""
    anomalies = []
    for label in labels:
        polarity = label.get("polarity", "")
        code = label.get("code", "")
        if polarity == "negative" and sentiment_score > 0.7:
            anomalies.append({
                "type": "sentiment_label_mismatch",
                "label_code": code,
                "polarity": polarity,
                "sentiment_score": sentiment_score,
            })
        elif polarity == "positive" and sentiment_score < 0.3:
            anomalies.append({
                "type": "sentiment_label_mismatch",
                "label_code": code,
                "polarity": polarity,
                "sentiment_score": sentiment_score,
            })
    return anomalies


# ── Tier date window computation ─────────────────────────────────────────────


def tier_date_window(tier: str, logical_date: str) -> tuple[str, str]:
    """Compute [since, until) half-open interval for the given tier and logical_date.

    All boundaries align to 00:00:00 Asia/Shanghai (no DST).

    - daily:   [logical_date 00:00, logical_date+1 00:00)
    - weekly:  [previous Monday 00:00, logical_date(Monday) 00:00)
    - monthly: [previous month 1st 00:00, logical_date(1st) 00:00)
    """
    d = date.fromisoformat(logical_date[:10])
    tz_suffix = "+08:00"

    if tier == "daily":
        since = d
        until = d + timedelta(days=1)
    elif tier == "weekly":
        until = d  # logical_date should be a Monday
        since = until - timedelta(days=7)
    elif tier == "monthly":
        until = d  # logical_date should be 1st of month
        if d.month == 1:
            since = d.replace(year=d.year - 1, month=12, day=1)
        else:
            since = d.replace(month=d.month - 1, day=1)
    else:
        raise ValueError(f"Unknown tier: {tier}")

    return (
        f"{since.isoformat()}T00:00:00{tz_suffix}",
        f"{until.isoformat()}T00:00:00{tz_suffix}",
    )


# ── Review attention label ───────────────────────────────────────────────────


def review_attention_label(review: dict, safety_level: str | None) -> dict:
    """Generate a human-readable weight label for a single review.

    Returns {"signals": [...], "label": "高关注度评论" | "差评" | "常规好评" | "中评"}.
    Uses RCW signal factors but does NOT expose the RCW score (D4 decision).
    """
    signals = []
    if safety_level:
        signals.append(f"⚠安全关键词({safety_level})")
    images = review.get("images") or []
    if images:
        signals.append(f"📸 {len(images)}张图")
    body_len = len(review.get("body", ""))
    if body_len > 300:
        signals.append(f"{body_len}字详评")
    elif body_len < 50:
        signals.append("短评")

    rating = float(review.get("rating") or 5)  # None defaults to 5 (lenient, consistent with signals)
    if safety_level == "critical" or (rating <= 2 and len(images) > 0):
        label = "高关注度评论"
    elif rating <= 2:
        label = "差评"
    elif rating >= 4:
        label = "常规好评"
    else:
        label = "中评"

    return {"signals": signals, "label": label}


# ── Attention signals engine ─────────────────────────────────────────────────


def compute_attention_signals(
    window_reviews: list[dict],
    changes: dict,
    cumulative_clusters: list[dict],
    logical_date: str | None = None,
    recent_reviews_7d: list[dict] | None = None,
) -> list[dict]:
    """Compute "needs attention" signals for the daily briefing.

    Args:
        window_reviews: Today's 24h window reviews.
        changes: Snapshot changes dict (price/stock/rating).
        cumulative_clusters: Negative clusters from cumulative analytics.
        logical_date: Current report date.
        recent_reviews_7d: Last 7 days of own reviews (for consecutive negative check).
                           Falls back to window_reviews if not provided.

    Returns list of signal dicts sorted by urgency (action first, reference second).
    Each signal: {"type": str, "urgency": "action"|"reference", "title": str, "detail": str}
    """
    signals = []
    changes = changes or {}
    ref_date = date.fromisoformat(logical_date[:10]) if logical_date else date.today()

    # ── Signal 1: Safety keyword hit (action) ──
    for r in window_reviews:
        text = f"{r.get('headline', '')} {r.get('body', '')}"
        level = detect_safety_level(text)
        if level:
            signals.append({
                "type": "safety_keyword",
                "urgency": "action",
                "title": f"安全: {r.get('product_name', '')} 评论提及安全关键词",
                "detail": f"级别: {level} · SKU: {r.get('product_sku', '')}",
                "review_id": r.get("id"),
                "safety_level": level,
            })

    # ── Signal 1b: Image evidence in negative review (action) ──
    for r in window_reviews:
        images = r.get("images") or []
        rating = float(r.get("rating") or 5)
        if images and rating <= config.NEGATIVE_THRESHOLD:
            signals.append({
                "type": "image_evidence",
                "urgency": "action",
                "title": f"图片证据: {r.get('product_name', '')} 差评含 {len(images)} 张图片",
                "detail": f"SKU: {r.get('product_sku', '')}",
                "review_id": r.get("id"),
            })

    # ── Signal 2: Consecutive negative for same SKU within 7 days (action) ──
    neg_source = recent_reviews_7d if recent_reviews_7d is not None else window_reviews
    own_negative_by_sku: dict[str, int] = {}
    for r in neg_source:
        if r.get("ownership") == "own" and (float(r.get("rating") or 5)) <= config.NEGATIVE_THRESHOLD:
            sku = r.get("product_sku", "")
            if sku:
                own_negative_by_sku[sku] = own_negative_by_sku.get(sku, 0) + 1
    for sku, count in own_negative_by_sku.items():
        if count >= 2:
            name = next(
                (r.get("product_name", sku) for r in neg_source if r.get("product_sku") == sku),
                sku,
            )
            signals.append({
                "type": "consecutive_negative",
                "urgency": "action",
                "title": f"连续差评: {name} 7天内 {count} 条差评",
                "detail": f"SKU: {sku}",
            })

    # ── Signal 3: Own product out of stock (action) ──
    for sc in (changes.get("stock_changes") or []):
        if sc.get("ownership") == "own" and sc.get("new") == "out_of_stock":
            signals.append({
                "type": "own_stock_out",
                "urgency": "action",
                "title": f"缺货: {sc.get('name', '')} 从有货变为缺货",
                "detail": f"SKU: {sc.get('sku', '')}",
            })

    # ── Signal 4: Competitor rating drop >= 0.3 (reference) ──
    for rc in (changes.get("rating_changes") or []):
        if rc.get("ownership") != "competitor":
            continue
        old_r = rc.get("old") or 0
        new_r = rc.get("new") or 0
        if old_r and new_r and (old_r - new_r) >= 0.3:
            signals.append({
                "type": "competitor_rating_change",
                "urgency": "reference",
                "title": f"竞品: {rc.get('name', '')} 评分 {old_r}→{new_r} ({new_r - old_r:+.1f})",
                "detail": f"SKU: {rc.get('sku', '')}",
            })

    # ── Signal 5: Silence good news — negative cluster dormant > 14 days (reference) ──
    for cluster in cumulative_clusters:
        last_seen_str = cluster.get("last_seen")
        if not last_seen_str:
            continue
        try:
            last_seen = date.fromisoformat(last_seen_str[:10])
        except (ValueError, TypeError):
            continue
        if (ref_date - last_seen).days >= 14:
            signals.append({
                "type": "silence_good_news",
                "urgency": "reference",
                "title": f"静默观察: {cluster.get('label_display', '')} 已 {(ref_date - last_seen).days} 天无新投诉",
                "detail": f"上次出现: {last_seen_str[:10]}",
            })

    # Sort: action first, then reference
    urgency_order = {"action": 0, "reference": 1}
    signals.sort(key=lambda s: urgency_order.get(s["urgency"], 2))
    return signals


# ── Weekly report: dispersion + credibility ──────────────────────────────────


def compute_dispersion(
    label_code: str,
    reviews: list[dict],
    total_skus: int,
) -> tuple[str, set[str]]:
    """Classify issue dispersion across SKUs.

    Returns (dispersion_type, affected_skus) where dispersion_type is:
    - "systemic": > 20% of SKUs affected (supply chain / design issue)
    - "isolated": < 10% AND <= 2 SKUs (batch / individual issue)
    - "uncertain": in between (needs more observation)
    """
    affected_skus: set[str] = set()
    for r in reviews:
        labels_raw = r.get("analysis_labels") or "[]"
        if isinstance(labels_raw, str):
            try:
                labels = json.loads(labels_raw)
            except (json.JSONDecodeError, TypeError):
                labels = []
        else:
            labels = labels_raw
        if any(lb.get("code") == label_code for lb in labels):
            sku = r.get("product_sku", "")
            if sku:
                affected_skus.add(sku)

    ldi = len(affected_skus) / total_skus if total_skus > 0 else 0

    if ldi > 0.2:
        return "systemic", affected_skus
    elif ldi < 0.1 and len(affected_skus) <= 2:
        return "isolated", affected_skus
    else:
        return "uncertain", affected_skus


def credibility_weight(review: dict, today: date | None = None) -> float:
    """Review Credibility Weight for internal sorting (D4: not exposed as KPI).

    Factors: body length, image count, recency (6-month half-life).
    """
    today = today or date.today()
    w = 1.0

    body_len = len(review.get("body", ""))
    if body_len > 500:
        w *= 1.5
    elif body_len < 50:
        w *= 0.6

    images = review.get("images") or []
    if images:
        w *= 1.0 + min(len(images), 3) * 0.15

    parsed = review.get("date_published_parsed")
    if parsed:
        pub_date = _parse_date_flexible(parsed)
        if pub_date:
            days_old = (today - pub_date).days
            w *= 0.5 ** (days_old / 180)  # half-life 6 months

    return w


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

_PRIORITY_DISPLAY = {"critical": "危急", "high": "高", "medium": "中", "low": "低"}
_SEVERITY_DISPLAY = {"critical": "危急", "high": "高", "medium": "中", "low": "低"}

CODE_TO_DIMENSION = {
    "quality_stability": "耐久性与质量",
    "material_finish": "耐久性与质量",
    "solid_build": "耐久性与质量",
    "structure_design": "设计与使用",
    "assembly_installation": "设计与使用",
    "easy_to_use": "设计与使用",
    "cleaning_maintenance": "清洁便利性",
    "easy_to_clean": "清洁便利性",
    "noise_power": "性能表现",
    "strong_performance": "性能表现",
    "service_fulfillment": "售后与履约",
}

# ── Metric tooltip explanations (Chinese) ────────────────────────────────────
# Keys match KPI card labels, table headers, and issue card stats.
# Used by PDF and email templates to render hover/title tooltips.

METRIC_TOOLTIPS = {
    # KPI cards (P1) — expanded with 公式/数据源/置信度 (Task 4.3)
    "健康指数": (
        "公式：(好评数 - 差评数) / 评论总数 × 50 + 50\n"
        "数据源：累积自有评论\n"
        "置信度：样本 ≥30 可信；<30 向先验值 50 收缩"
    ),
    "差评率": (
        "公式：差评数 ÷ 自有评论总数\n"
        "差评 = 评分 ≤ {threshold} 星\n"
        "3 星中评不计入好评也不计入差评"
    ),
    "自有评论": "累积抓取到的自有产品评论总数（已去重）",
    "好评率": "自有产品 ≥4 星评论占比（3 星为中评，不计入好评）",
    "高风险产品": (
        "公式：risk_score ≥ {high_risk} 的自有产品数\n"
        "risk_score 由差评率、评分、近期差评数加权\n"
        "数据源：累积"
    ),
    "竞品差距指数": (
        "公式：各维度 (comp_pos_rate + own_neg_rate) / 2 平均 × 100\n"
        "样本门槛：自有+竞品评论 ≥ 20 才展示\n"
        "数据源：累积"
    ),
    "样本覆盖率": (
        "公式：ingested_review_rows ÷ site_reported_review_total_current\n"
        "注：MAX_REVIEWS=200 截断每产品最多采集 200 条最新评论\n"
        "数据源：累积全量对比"
    ),
    "翻译完成度": "累积评论中 translate_status='done' 的比例",
    "安全事件": "本期新增 safety_incidents 记录数（按 review_id 去重）",
    # Product health matrix (P2)
    "评分": "站点展示的综合评分（历史累积，非本期样本）",
    "差评率_产品": "该产品 ≤{low_rating}星评论数 ÷ 该产品采集评论总数",
    "风险分": "低分评论×2 + 含图评论×1 + 各标签严重度累加；仅计 ≤{low_rating}星评论",
    # Issue cards (P3)
    "评论数": "匹配该问题标签的评论条数（关键词+词边界匹配）",
    "涉及产品数": "出现该问题的不同产品（SKU）数量",
    # Issue cluster footnote (P3)
    "问题聚类": "基于 AI 语义分析，包含差评和中性偏负面评论",
    # Gap analysis table (P4)
    "竞品好评": "竞品在该维度被正面标签命中的评论数",
    "自有差评": "自有产品在该维度被负面标签命中的评论数",
    "差距": "基于比率的差距指数(0-100)：(竞品好评率+自有差评率)/2×100",
}


def _resolve_tooltip(key: str, threshold=None, **kw) -> str:
    """Resolve a tooltip template with runtime threshold values."""
    text = METRIC_TOOLTIPS.get(key, "")
    if not text:
        return ""
    try:
        return text.format(
            threshold=threshold or config.NEGATIVE_THRESHOLD,
            low_rating=config.LOW_RATING_THRESHOLD,
            high_risk=config.HIGH_RISK_THRESHOLD,
        )
    except (KeyError, IndexError):
        return text


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

# Map negative label codes to their positive counterpart for cross-taxonomy gap analysis.
# Dimensions where competitors are praised AND own products are criticized.
_NEGATIVE_TO_POSITIVE_DIMENSION = {
    "quality_stability": "solid_build",
    "material_finish": "solid_build",
    "structure_design": "solid_build",
    "cleaning_maintenance": "easy_to_clean",
    "noise_power": "strong_performance",
    "packaging_shipping": "good_packaging",
    "assembly_installation": "easy_to_use",
    # service_fulfillment has no positive counterpart
}

# Human-readable dimension names for gap analysis display
_DIMENSION_DISPLAY = {
    "solid_build": "做工与质量",
    "easy_to_clean": "清洁便利性",
    "strong_performance": "性能与动力",
    "good_packaging": "包装运输",
    "easy_to_use": "安装与使用",
}


def _competitor_gap_analysis(normalized):
    """Find dimensions where competitors are praised but our products are criticised.

    Dual-dimension algorithm:
    - fix_urgency: own negative rate (止血 signal — we have problems to fix)
    - catch_up_gap: competitor positive rate minus own positive rate (追赶 signal — they lead us)
    - priority_score: fix_urgency * 0.7 + catch_up_gap * 0.3
    """
    kpis = normalized.get("kpis", {})
    competitor_total = kpis.get("competitor_review_rows", 0) or 1
    own_total = kpis.get("own_review_rows", 0) or 1

    comp_positive = {
        t["label_code"]: t
        for t in normalized.get("competitor", {}).get("top_positive_themes", [])
    }
    own_negative_clusters = normalized.get("self", {}).get("top_negative_clusters", [])

    # Own positive clusters (for catch_up_gap computation)
    own_positive_clusters = normalized.get("self", {}).get("top_positive_clusters", [])
    own_positive = {t["label_code"]: t for t in own_positive_clusters}

    # Group own negatives by their positive-taxonomy dimension
    dimension_own_negative: dict[str, int] = {}
    dimension_neg_codes: dict[str, list[str]] = {}
    for c in own_negative_clusters:
        neg_code = c.get("label_code", "")
        pos_dim = _NEGATIVE_TO_POSITIVE_DIMENSION.get(neg_code)
        if not pos_dim:
            continue
        dimension_own_negative[pos_dim] = dimension_own_negative.get(pos_dim, 0) + (c.get("review_count") or 0)
        dimension_neg_codes.setdefault(pos_dim, []).append(neg_code)

    # Find dimensions where competitor has positive OR own has negative
    gap_dims = set(comp_positive) | set(dimension_own_negative)
    gaps = []
    for dim in gap_dims:
        if dim.startswith("_"):
            continue
        comp_theme = comp_positive.get(dim)
        comp_cnt = comp_theme.get("review_count", 0) if comp_theme else 0
        own_cnt = dimension_own_negative.get(dim, 0)

        # Rate-based signals
        comp_rate = comp_cnt / max(competitor_total, 1)
        own_rate = own_cnt / max(own_total, 1)

        # Own positive count for the same dimension (for catch_up_gap)
        own_pos_theme = own_positive.get(dim)
        own_pos_cnt = own_pos_theme.get("review_count", 0) if own_pos_theme else 0
        own_pos_rate = own_pos_cnt / max(own_total, 1)

        # Dual-dimension signals
        fix_urgency = own_rate  # own negative rate (0-1)
        catch_up_gap = max(comp_rate - own_pos_rate, 0)  # competitor lead over own positive (0-1)
        priority_score = fix_urgency * 0.7 + catch_up_gap * 0.3  # weighted composite (0-1)
        priority_score_pct = round(priority_score * 100)

        # gap_type classification
        if own_rate >= 0.10:
            gap_type = "止血"
        elif catch_up_gap >= 0.20:
            gap_type = "追赶"
        else:
            gap_type = "监控"

        # Priority based on priority_score
        if priority_score_pct >= 25:
            priority, priority_display = "high", "高"
        elif priority_score_pct >= 10:
            priority, priority_display = "medium", "中"
        else:
            priority, priority_display = "low", "低"

        # Backward-compat gap_rate (kept for downstream consumers)
        if comp_cnt > 0 and own_cnt > 0:
            gap_rate = round((comp_rate + own_rate) / 2 * 100)
        elif comp_cnt > 0:
            gap_rate = round(comp_rate * 50)
        else:
            gap_rate = round(own_rate * 50)

        gaps.append({
            "label_code": dim,
            "label_display": _DIMENSION_DISPLAY.get(dim, _LABEL_DISPLAY.get(dim, dim)),
            "competitor_positive_count": comp_cnt,
            "competitor_positive_rate": round(comp_rate * 100, 1),
            "own_negative_count": own_cnt,
            "own_negative_rate": round(own_rate * 100, 1),
            "competitor_total": competitor_total,
            "own_total": own_total,
            "gap": comp_cnt - own_cnt,
            "gap_rate": gap_rate,
            "gap_type": gap_type,
            "priority": priority,
            "priority_display": priority_display,
            "fix_urgency": round(fix_urgency * 100),
            "catch_up_gap": round(catch_up_gap * 100),
            "priority_score": priority_score_pct,
        })
    return sorted(gaps, key=lambda g: g["priority_score"], reverse=True)


# ── KPI delta computation ───────────────────────────────────────────────────


def _compute_kpi_deltas(current_kpis, prev_analytics):
    """Compute difference between current KPIs and those from a previous report."""
    if not prev_analytics:
        return {}
    prev_kpis = prev_analytics.get("kpis", {})
    deltas = {}
    for key in ("negative_review_rows", "own_negative_review_rows",
                "ingested_review_rows", "product_count",
                "health_index", "recently_published_count"):
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

    neg_delta = normalized.get("kpis", {}).get("own_negative_review_rows_delta")
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
    """Compute alert level from health index, deltas, and mode."""
    mode = normalized.get("mode", "baseline")
    kpis = normalized.get("kpis", {})
    health = kpis.get("health_index", 100)
    own_reviews = kpis.get("own_review_rows", 0)

    if own_reviews == 0:
        return ("green", "自有评论数据不足，暂不预警")

    if mode == "baseline":
        if health < config.HEALTH_RED:
            return ("red", f"首次基线：健康指数 {health}/100，低于警戒线")
        if health < config.HEALTH_YELLOW:
            return ("yellow", f"首次基线：健康指数 {health}/100，需关注")
        return ("green", "首次基线采集完成，整体状态良好")

    neg_delta = kpis.get("own_negative_review_rows_delta", 0)
    clusters = normalized.get("self", {}).get("top_negative_clusters", [])
    # is_new_or_escalated is populated by compute_cluster_changes() in Phase 3b.
    # Until then, escalation detection relies on health index and delta thresholds only.
    has_escalation = any(
        c.get("severity") in ("critical", "high") and c.get("is_new_or_escalated")
        for c in clusters
    )

    if health < config.HEALTH_RED or neg_delta >= 10 or has_escalation:
        parts = []
        if health < config.HEALTH_RED:
            parts.append(f"健康指数 {health} 低于警戒线 {config.HEALTH_RED}")
        if neg_delta >= 10:
            parts.append(f"差评新增 {neg_delta} 条")
        if has_escalation:
            parts.append("存在高风险问题升级")
        return ("red", "；".join(parts) if parts else "高风险信号")

    if health < config.HEALTH_YELLOW or neg_delta > 0:
        parts = []
        if neg_delta > 0:
            parts.append(f"差评新增 {neg_delta} 条")
        if health < config.HEALTH_YELLOW:
            parts.append(f"健康指数 {health} 偏低")
        return ("yellow", "；".join(parts) if parts else "需关注")

    return ("green", "整体健康度良好，无需紧急处理")


def _parse_date_flexible(value: str | None, anchor_date=None):
    """Parse a date string in various formats: ISO, MM/DD/YYYY, or relative ('X months ago').

    For relative formats ('3 months ago'), *anchor_date* is used as the
    reference point instead of ``date.today()``.  When *None* (default),
    today's date is used, preserving backward compatibility.
    """
    if not value:
        return None
    s = value.strip()
    # ISO format: "2026-01-01" or "2026-01-01T..."
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, IndexError):
        pass
    # MM/DD/YYYY format
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        pass
    # Relative format: "X days/months/years ago", "a month ago", "a year ago"
    today = anchor_date or date.today()
    m = re.match(r"(?:(\d+)|a|an)\s+(day|week|month|year)s?\s+ago", s, re.IGNORECASE)
    if m:
        amount = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2).lower()
        if unit == "day":
            return today - timedelta(days=amount)
        elif unit == "week":
            return today - timedelta(weeks=amount)
        elif unit == "month":
            # Calendar-aware: subtract months, clamp day
            month = today.month - amount
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            max_day = calendar.monthrange(year, month)[1]
            day = min(today.day, max_day)
            return date(year, month, day)
        elif unit == "year":
            try:
                return today.replace(year=today.year - amount)
            except ValueError:
                # Feb 29 → Feb 28
                return today.replace(year=today.year - amount, day=28)
    return None


def _duration_display(first_seen: str | None, last_seen: str | None) -> str | None:
    """Human-readable duration between two date strings (any format)."""
    d1 = _parse_date_flexible(first_seen)
    d2 = _parse_date_flexible(last_seen)
    if not d1 or not d2:
        return None
    days = abs((d2 - d1).days)
    if days <= 0:
        return None
    if days < 30:
        return f"{days} 天"
    months = days // 30
    if months < 12:
        return f"约 {months} 个月"
    years = months // 12
    remaining = months % 12
    if remaining == 0:
        return f"约 {years} 年"
    return f"约 {years} 年 {remaining} 个月"


def _humanize_bullets(normalized):
    """Generate up to 3 natural-language conclusions for the executive summary."""
    bullets = []
    kpis = normalized.get("kpis", {})

    # Backfill disclosure — MUST be first to survive [:3] truncation
    recently_published = kpis.get("recently_published_count", 0)
    ingested = kpis.get("ingested_review_rows", 0)
    if ingested > 0 and recently_published < ingested * 0.5:
        backfill_count = ingested - recently_published
        bullets.append(
            f"注：本期 {ingested} 条评论中有 {backfill_count} 条为历史补采"
            f"（发布于 30 天前），数据含历史积累"
        )

    # Bullet 1: highest-risk product — negative rate and delta
    top = (normalized.get("self", {}).get("risk_products") or [None])[0]
    if top:
        top_labels = top.get("top_labels") or []
        cluster_code = top_labels[0].get("label_code") if top_labels else ""
        cluster_name = _LABEL_DISPLAY.get(cluster_code, cluster_code)
        total = top.get("total_reviews") or 0
        neg = top.get("negative_review_rows", 0)
        rate_str = f"（差评率 {neg/total:.0%}）" if total else ""
        neg_delta = normalized.get("kpis", {}).get("own_negative_review_rows_delta", 0) or 0
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
    translation_rate = kpis.get("translation_completion_rate") or 1.0
    if translation_rate < 0.7:
        bullets.append(
            f"注意：{kpis.get('untranslated_count', 0)} 条评论翻译未完成，中文分析可能不完整"
        )
    else:
        bullets.append(
            f"本期覆盖 {kpis.get('product_count', 0)} 个产品（自有 {kpis.get('own_product_count', 0)}、竞品 {kpis.get('competitor_product_count', 0)}），{kpis.get('own_review_rows', 0)} 条自有评论"
        )
    return bullets[:3]


# ── Health & competitive gap indices ─────────────────────────────────────────


def compute_health_index(analytics: dict) -> tuple[float, str]:
    """NPS-proxy health index with Bayesian shrinkage for small samples.

    Returns (health_index, confidence) where:
        health_index: 0-100 scale (shrunk toward 50.0 prior when sample < 30)
        confidence: "high" (>=30), "medium" (5-29), "low" (<5), "no_data" (0)

    Maps Net Promoter Score (-100..+100) to a 0..100 scale:
        promoters (rating >= 4) minus detractors (rating <= NEGATIVE_THRESHOLD),
        divided by total own reviews, times 100, then linearly mapped.

    Industry benchmarks for consumer products:
        > 75 excellent, 60-75 good, 50-60 needs attention, < 50 critical.
    """
    kpis = analytics.get("kpis", {}) if isinstance(analytics, dict) else {}
    own_reviews = kpis.get("own_review_rows", 0)
    if own_reviews == 0:
        return 50.0, "no_data"

    promoters = kpis.get("own_positive_review_rows", 0)
    detractors = kpis.get("own_negative_review_rows", 0)

    nps = ((promoters - detractors) / own_reviews) * 100
    raw_health = (nps + 100) / 2

    # Bayesian shrinkage: pull toward prior (50.0) when sample is small
    MIN_RELIABLE = 30
    PRIOR = 50.0
    if own_reviews < MIN_RELIABLE:
        weight = own_reviews / MIN_RELIABLE
        health = weight * raw_health + (1 - weight) * PRIOR
        confidence = "low" if own_reviews < 5 else "medium"
    else:
        health = raw_health
        confidence = "high"

    return round(max(0.0, min(100.0, health)), 1), confidence


def compute_competitive_gap_index(gap_analysis: list[dict]) -> int:
    """Rate-based competitive gap index (0-100 scale).

    For each dimension: gap_rate = (comp_pos_rate + own_neg_rate) / 2
    where each rate = count / total (capped at 1.0).
    Final index = average across dimensions × 100.
    """
    if not gap_analysis:
        return 0
    dimension_scores = []
    for g in gap_analysis:
        comp_pos = g.get("competitor_positive_count", 0)
        own_neg = g.get("own_negative_count", 0)
        comp_total = g.get("competitor_total", 0) or max(comp_pos, 1)
        own_total = g.get("own_total", 0) or max(own_neg, 1)
        comp_rate = min(comp_pos / max(comp_total, 1), 1.0)
        own_rate = min(own_neg / max(own_total, 1), 1.0)
        dimension_scores.append((comp_rate + own_rate) / 2)
    avg = sum(dimension_scores) / len(dimension_scores) if dimension_scores else 0
    return round(avg * 100)


def has_estimated_dates(reviews, logical_date_str):
    """Check if >30% of review dates cluster on the same MM-DD as logical_date.

    Indicates relative dates ('3 years ago') parsed to the same day-of-year.
    """
    if not reviews:
        return False
    logical_mmdd = logical_date_str[5:]  # "MM-DD" from "YYYY-MM-DD"
    count_matching = sum(
        1 for r in reviews
        if (r.get("date_published_parsed") or "").endswith(logical_mmdd)
    )
    return count_matching / len(reviews) > 0.30


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

    # ── Baseline mode: suppress delta displays (must run AFTER KPI spread) ──
    if normalized["mode"] == "baseline":
        normalized["baseline_note"] = (
            f"首次全量基线报告（历史样本 {normalized.get('baseline_sample_days', 0)} 天），"
            f"环比数据将在第 4 期报告后开始展示"
        )
        for key in list(normalized["kpis"].keys()):
            if key.endswith("_delta_display"):
                normalized["kpis"][key] = "—"
            elif key.endswith("_delta") and not key.endswith("_delta_display"):
                normalized["kpis"][key] = 0
    else:
        normalized["baseline_note"] = ""

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
        # Only link to the primary (first/highest-confidence) label
        review["primary_label"] = label_codes[0] if label_codes else None
        primary = label_codes[0] if label_codes else None
        if primary:
            evidence_refs_by_label.setdefault(primary, []).append(review["evidence_id"])
        image_reviews.append(review)
    normalized["appendix"]["image_reviews"] = image_reviews

    # Build trend lookup from _trend_series
    trend_lookup = {}
    for ts in (analytics.get("_trend_series") or []):
        sku = ts.get("product_sku", "")
        series = ts.get("series") or []
        if sku and len(series) >= 2:
            first = series[0]
            last = series[-1]
            r_old = first.get("rating") or 0
            r_new = last.get("rating") or 0
            rc_old = first.get("review_count") or 0
            rc_new = last.get("review_count") or 0
            r_arrow = "↑" if r_new > r_old + 0.1 else ("↓" if r_new < r_old - 0.1 else "→")
            rc_delta = rc_new - rc_old
            parts = [f"评分{r_arrow}{r_new:.1f}"]
            if rc_delta != 0:
                parts.append(f"评论{'+' if rc_delta > 0 else ''}{rc_delta}")
            trend_lookup[sku] = " ".join(parts)

    risk_products = []
    for item in normalized["self"]["risk_products"]:
        product = dict(item)
        product["top_labels_display"] = _join_label_counts(product.get("top_labels") or [])
        product["top_features_display"] = product["top_labels_display"]   # alias for template
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
        product["trend_display"] = trend_lookup.get(
            product.get("product_sku", ""), product.get("trend_display") or "—"
        )
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

    gap_analysis = normalized.get("competitor", {}).get("gap_analysis", [])
    kpis = normalized["kpis"]
    kpis["gap_fix_count"] = sum(1 for g in gap_analysis if g.get("gap_type") == "止血")
    kpis["gap_catch_count"] = sum(1 for g in gap_analysis if g.get("gap_type") == "追赶")

    # ── Compute health_index, competitive_gap_index, high_risk_count ─────
    _health, _health_confidence = compute_health_index(normalized)
    normalized["kpis"]["health_index"] = _health
    normalized["kpis"]["health_confidence"] = _health_confidence
    _total_reviews_for_gap = (
        normalized.get("kpis", {}).get("own_review_rows", 0)
        + normalized.get("kpis", {}).get("competitor_review_rows", 0)
    )
    _MIN_GAP_SAMPLE = 20
    if _total_reviews_for_gap < _MIN_GAP_SAMPLE:
        normalized["kpis"]["competitive_gap_index"] = None
    else:
        normalized["kpis"]["competitive_gap_index"] = compute_competitive_gap_index(
            normalized.get("competitor", {}).get("gap_analysis") or []
        )
    normalized["kpis"]["high_risk_count"] = sum(
        1 for p in normalized.get("self", {}).get("risk_products", [])
        if p.get("risk_score", 0) >= config.HIGH_RISK_THRESHOLD
    )

    # ── Build kpi_cards for template ─────────────────────────────────────
    kpis = normalized["kpis"]
    own_neg_rate = kpis.get("own_negative_review_rate") or 0
    kpis["own_negative_review_rate_display"] = f"{own_neg_rate * 100:.1f}%"
    own_pos = kpis.get("own_positive_review_rows", 0)
    own_total = kpis.get("own_review_rows", 0) or 1
    positive_rate = own_pos / own_total

    # Task 4.3 — confidence badges (derived from health_confidence + sample sizes)
    _health_conf = kpis.get("health_confidence", "no_data")
    _health_conf_badge = {"high": "high", "medium": "medium", "low": "low", "no_data": "low"}.get(_health_conf, "none")
    _own_reviews = kpis.get("own_review_rows", 0) or 0
    _competitor_reviews = kpis.get("competitor_review_rows", 0) or 0
    _review_sample_conf = "high" if _own_reviews >= 30 else ("medium" if _own_reviews >= 10 else "low")

    # Task 4.4 — rate bands for 差评率 card (好/中/差)
    _own_pos_val = kpis.get("own_positive_review_rows", 0) or 0
    _own_neg_val = kpis.get("own_negative_review_rows", 0) or 0
    _own_total_val = max(_own_reviews, 1)
    _neu = max(_own_total_val - _own_pos_val - _own_neg_val, 0)
    _rate_bands = {
        "positive": round(_own_pos_val / _own_total_val * 100, 1),
        "neutral":  round(_neu / _own_total_val * 100, 1),
        "negative": round(_own_neg_val / _own_total_val * 100, 1),
    }

    # D12 — competitive gap index sample status when <20
    _total_for_gap = _own_reviews + _competitor_reviews
    if _total_for_gap < 20:
        _gap_value = f"累积中 {_total_for_gap}/20"
        _gap_class = "kpi-delta--missing"
        _gap_conf = "low"
    else:
        _gap_value = kpis.get("competitive_gap_index") if kpis.get("competitive_gap_index") is not None else "—"
        _gap_class = "delta-flat"
        _gap_conf = "medium"

    # D5 — unclassified reviews count for "自有评论" tooltip
    _ingested = kpis.get("ingested_review_rows", 0) or 0
    _classified = _own_reviews + _competitor_reviews
    _unclassified = max(_ingested - _classified, 0)

    kpi_cards = [
        {
            "label": "健康指数",
            "value": kpis.get("health_index", "—"),
            "delta_display": kpis.get("health_index_delta_display", ""),
            "delta_class": "delta-flat",
            "tooltip": _resolve_tooltip("健康指数"),
        },
        {
            "label": "差评率",
            "value": kpis.get("own_negative_review_rate_display", "—"),
            "delta_display": kpis.get("negative_review_rows_delta_display", ""),
            "delta_class": "delta-up" if (kpis.get("negative_review_rows_delta", 0) or 0) > 0 else "delta-flat",
            "tooltip": _resolve_tooltip("差评率"),
        },
        {
            "label": "自有评论",
            "value": kpis.get("own_review_rows", 0),
            "delta_display": kpis.get("ingested_review_rows_delta_display", ""),
            "delta_class": "delta-flat",
            "tooltip": _resolve_tooltip("自有评论"),
        },
        {
            "label": "好评率",
            "value": f"{positive_rate * 100:.1f}%",
            "delta_display": "",
            "delta_class": "delta-flat",
            "tooltip": _resolve_tooltip("好评率"),
            "value_class": "severity-low" if positive_rate >= 0.7 else "",
        },
        {
            "label": "高风险产品",
            "value": kpis.get("high_risk_count", 0),
            "delta_display": "",
            "delta_class": "delta-up" if kpis.get("high_risk_count", 0) > 0 else "delta-flat",
            "tooltip": _resolve_tooltip("高风险产品"),
        },
        {
            "label": "竞品差距指数",
            "value": kpis.get("competitive_gap_index") if kpis.get("competitive_gap_index") is not None else "—",
            "delta_display": kpis.get("competitive_gap_index_delta_display", ""),
            "delta_class": "delta-flat",
            "tooltip": _resolve_tooltip("竞品差距指数"),
        },
    ]

    # Task 4.3/4.4 — attach confidence badges + rate bands + unclassified note
    for c in kpi_cards:
        if c.get("label") == "健康指数":
            c["confidence"] = _health_conf_badge
        elif c.get("label") == "差评率":
            c["confidence"] = _review_sample_conf
            c["rate_bands"] = _rate_bands
        elif c.get("label") == "自有评论":
            c["confidence"] = _review_sample_conf
            if _unclassified > 0:
                c["tooltip"] = (c.get("tooltip") or "") + f"\n注：当前 {_unclassified} 条评论 ownership 未分类"
        elif c.get("label") == "高风险产品":
            c["confidence"] = _review_sample_conf
        elif c.get("label") == "好评率":
            c["confidence"] = _review_sample_conf
        elif c.get("label") == "竞品差距指数":
            c["value"] = _gap_value
            c["delta_class"] = _gap_class
            c["confidence"] = _gap_conf

    # Coverage rate card
    site_total = kpis.get("site_reported_review_total_current", 0) or 0
    ingested = kpis.get("ingested_review_rows", 0) or 0
    coverage_rate = ingested / max(site_total, 1) if site_total > 0 else 0
    kpis["coverage_rate"] = coverage_rate
    kpi_cards.append({
        "label": "样本覆盖率",
        "value": f"{coverage_rate:.0%}" if site_total > 0 else "—",
        "delta_display": "",
        "delta_class": "delta-flat",
        "tooltip": _resolve_tooltip("样本覆盖率"),
        "value_class": "severity-medium" if 0 < coverage_rate < 0.5 else "",
    })

    # ── Assign status color classes to KPI values ────────────────────
    for card in kpi_cards:
        label = card["label"]
        val = card["value"]
        if label == "健康指数" and isinstance(val, (int, float)):
            card["value_class"] = "severity-high" if val < 60 else ("severity-medium" if val < 80 else "severity-low")
        elif label == "差评率" and isinstance(val, str) and val.endswith("%"):
            rate = float(val.rstrip("%"))
            card["value_class"] = "severity-high" if rate > 20 else ("severity-medium" if rate > 10 else "")
        elif label == "高风险产品" and isinstance(val, (int, float)):
            card["value_class"] = "severity-high" if val > 0 else ""
        elif label == "竞品差距指数" and isinstance(val, (int, float)):
            card["value_class"] = "severity-high" if val > 60 else ("severity-medium" if val > 30 else "")
        else:
            card.setdefault("value_class", "")

    normalized["kpi_cards"] = kpi_cards

    # ── Resolved tooltip dict for templates (table headers, issue stats) ──
    normalized["tooltips"] = {k: _resolve_tooltip(k) for k in METRIC_TOOLTIPS}

    # ── Build issue_cards from top_negative_clusters ─────────────────────
    report_priorities = (normalized.get("report_copy") or {}).get("improvement_priorities") or []
    # Match by label_code for semantic alignment; fall back to rank-based for legacy data
    priority_by_label = {p["label_code"]: p.get("action", "") for p in report_priorities if p.get("label_code")}
    if not priority_by_label:
        priority_by_label = {p.get("rank", i + 1): p.get("action", "") for i, p in enumerate(report_priorities)}
        _label_key = False
    else:
        _label_key = True

    logical_date_str = normalized.get("logical_date", "")
    cutoff_90d = ""
    if logical_date_str:
        try:
            cutoff_90d = (date.fromisoformat(logical_date_str) - timedelta(days=90)).isoformat()
        except ValueError:
            pass

    issue_cards = []
    for i, cluster in enumerate(normalized["self"]["top_negative_clusters"]):
        # Collect image URLs from example_reviews (max 3 unique)
        image_evidence = []
        seen_urls: set[str] = set()
        for ex in cluster.get("example_reviews") or []:
            for url in ex.get("images") or []:
                if url and url not in seen_urls and len(image_evidence) < 3:
                    seen_urls.add(url)
                    image_evidence.append({"url": url, "data_uri": None,
                                            "evidence_id": f"I{len(image_evidence)+1}"})
        translated_rate = cluster.get("translated_rate", 1.0)
        lookup_key = cluster.get("label_code", "") if _label_key else (i + 1)
        issue_cards.append({
            "feature_display": cluster.get("feature_display") or cluster.get("label_display", ""),
            "label_display": cluster.get("label_display", ""),
            "review_count": cluster.get("review_count", 0),
            "severity": cluster.get("severity", "low"),
            "severity_display": cluster.get("severity_display", ""),
            "affected_product_count": cluster.get("affected_product_count", 0),
            "first_seen": cluster.get("first_seen"),
            "last_seen": cluster.get("last_seen"),
            "duration_display": _duration_display(cluster.get("first_seen"), cluster.get("last_seen")),
            "image_review_count": cluster.get("image_review_count", 0),
            "example_reviews": cluster.get("example_reviews") or [],
            "image_evidence": image_evidence,
            "recommendation": priority_by_label.get(lookup_key, ""),
            "translated_rate_display": f"{translated_rate * 100:.0f}%",
            "translation_warning": translated_rate < 0.5,
        })
        # ── 90-day recency indicator ──
        review_dates = cluster.get("review_dates") or []
        if cutoff_90d and review_dates:
            recent = sum(1 for d in review_dates if d >= cutoff_90d)
        else:
            recent = 0
        total = cluster.get("review_count", 0) or 1
        recency_pct = round(recent / total * 100)
        issue_cards[-1]["recency_display"] = f"近90天 {recent} 条（{recency_pct}%）"
    normalized["self"]["issue_cards"] = issue_cards

    # ── Top-level alias for V3 template convenience ─────────────────────
    normalized["issue_cards"] = issue_cards

    # ── Build top_actions from improvement_priorities (LLM) + top_negative_clusters
    top_actions = []
    priorities = (normalized.get("report_copy") or {}).get("improvement_priorities", [])
    clusters_by_code = {
        c.get("label_code"): c
        for c in normalized.get("self", {}).get("top_negative_clusters", [])
        if c.get("label_code")
    }
    for i, p in enumerate(priorities[:3]):
        cluster = clusters_by_code.get(p.get("label_code", ""))
        top_actions.append({
            "rank": i + 1,
            "title": (p.get("action") or "")[:80],
            "evidence_summary": f"{cluster['review_count']}条投诉" if cluster else "",
            "affected_products": (cluster.get("affected_products") or []) if cluster else [],
            "recommendation": p.get("action", ""),
            "linked_cluster": p.get("label_code", ""),
        })
    normalized["top_actions"] = top_actions

    if not normalized["report_copy"]["hero_headline"]:
        normalized["report_copy"]["hero_headline"] = _fallback_hero_headline(normalized)
    if not normalized["report_copy"]["executive_bullets"]:
        normalized["report_copy"]["executive_bullets"] = _fallback_executive_bullets(normalized)

    return normalized


# ── Monthly: category map loader ─────────────────────────────────────────────


def load_category_map(path: str | None = None) -> dict[str, dict]:
    """Load SKU→category mapping from CSV.

    Returns ``{sku: {"category": str, "sub_category": str, "price_band_override": str}}``.
    Missing file or CSV errors return ``{}`` (caller falls back to direct competitor pairing).
    """
    import csv as _csv
    path = path or getattr(config, "CATEGORY_MAP_PATH", None)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8", newline="") as f:
            reader = _csv.DictReader(f)
            mapping: dict[str, dict] = {}
            for row in reader:
                sku = (row.get("sku") or "").strip()
                if not sku:
                    continue
                mapping[sku] = {
                    "category": (row.get("category") or "").strip(),
                    "sub_category": (row.get("sub_category") or "").strip(),
                    "price_band_override": (row.get("price_band_override") or "").strip(),
                }
            return mapping
    except (FileNotFoundError, _csv.Error, OSError):
        return {}


# ── AnalyticsEnvelope persistence contract (V4) ──────────────────────────────

_ENVELOPE_SCHEMA_VERSION = "v4"


def build_analytics_envelope(
    raw_analytics: dict,
    *,
    mode: str,
    mode_context: dict | None = None,
) -> dict:
    """Build V4 analytics envelope: raw + normalized + mode metadata.

    Persisted to `analytics.json` so later consumers (monthly re-render,
    kpi_delta lookup) can read normalized derived fields (health_index,
    own_negative_review_rate_display, high_risk_count, kpi_cards, ...)
    without re-running normalize.
    """
    import copy
    normalized = normalize_deep_report_analytics(copy.deepcopy(raw_analytics))
    envelope = {
        "_schema_version": _ENVELOPE_SCHEMA_VERSION,
        "kpis_raw": raw_analytics.get("kpis", {}),
        "kpis_normalized": normalized.get("kpis", {}),
        "self": normalized.get("self", {}),
        "competitor": normalized.get("competitor", {}),
        "report_copy": normalized.get("report_copy", {}),
        "kpi_cards": normalized.get("kpi_cards", []),
        "issue_cards": normalized.get("issue_cards", []),
        "mode": mode,
        "mode_context": mode_context or {},
        "logical_date": raw_analytics.get("logical_date", ""),
        "run_id": raw_analytics.get("run_id", 0),
    }
    # Preserve any other top-level keys the legacy pipeline attached
    for k, v in raw_analytics.items():
        if k not in envelope and not k.startswith("_"):
            envelope.setdefault(k, v)
    return envelope


def load_analytics_envelope(path_or_dict) -> dict:
    """Load an analytics envelope from disk or return as-is if dict.

    Back-compat: if file is legacy (no `_schema_version`), wrap it so
    callers can always read `envelope["kpis_normalized"]`.
    """
    if isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        with open(path_or_dict, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    if data.get("_schema_version") == _ENVELOPE_SCHEMA_VERSION:
        return data
    # Legacy shim: normalize on read
    kpis = data.get("kpis")
    raw = {"kpis": kpis if isinstance(kpis, dict) else {}, **data}
    return build_analytics_envelope(raw, mode=data.get("mode", "full"), mode_context={})
