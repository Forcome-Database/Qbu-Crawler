"""Shared constants and helper functions used by report.py and report_pdf.py."""

import calendar
import json
import os
import re
from datetime import date, datetime, timedelta

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
    # KPI cards (P1)
    "健康指数": "综合评分 = 20%站点评分 + 25%样本评分 + 35%(1−差评率) + 20%(1−高风险占比)，满分100",
    "差评率": "自有产品 ≤{threshold}星评论数 ÷ 自有评论总数",
    "自有评论": "本期采集窗口内入库的自有产品评论行数（按抓取时间计）",
    "高风险产品": "风险分 ≥{high_risk} 的自有产品数量",
    "竞品差距指数": "各维度(竞品好评率+自有差评率)/2 的均值×100，0=无差距，100=全面落后",
    "样本覆盖率": "实际入库评论数 ÷ 站点展示总评论数。受 MAX_REVIEWS 上限和翻页限制影响，部分产品覆盖率 <100% 属正常",
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
                "ingested_review_rows", "product_count"):
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
    """Return ``(level, text)`` where *level* is ``"red"``/``"yellow"``/``"green"``."""
    if normalized.get("mode") == "baseline":
        return "green", "首次基线采集完成，环比预警将在第 4 期后启用"
    top_neg = normalized.get("self", {}).get("top_negative_clusters") or []
    high_sev = [c for c in top_neg if c.get("severity") == "high" and (c.get("review_count") or 0) >= 5]
    delta = normalized.get("kpis", {}).get("own_negative_review_rows_delta", 0) or 0
    health = normalized.get("kpis", {}).get("health_index")

    # Red conditions
    if high_sev or delta >= 10:
        return "red", "存在高严重度问题簇，建议今日跟进"
    if health is not None and health < config.HEALTH_RED:
        return "red", f"健康指数 {health} 低于警戒线 {config.HEALTH_RED}，建议今日跟进"

    # Yellow conditions
    if delta > 0:
        return "yellow", "自有产品差评数较上期有所上升，请持续关注"
    if health is not None and health < config.HEALTH_YELLOW:
        return "yellow", f"健康指数 {health} 偏低，请持续关注"

    return "green", "无新增高风险信号"


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


def compute_health_index(analytics: dict) -> float:
    """NPS-proxy health index.

    Maps Net Promoter Score (-100..+100) to a 0..100 scale:
        promoters (rating >= 4) minus detractors (rating <= NEGATIVE_THRESHOLD),
        divided by total own reviews, times 100, then linearly mapped.

    Industry benchmarks for consumer products:
        > 75 excellent, 60-75 good, 50-60 needs attention, < 50 critical.
    """
    kpis = analytics.get("kpis", {}) if isinstance(analytics, dict) else {}
    own_reviews = kpis.get("own_review_rows", 0)
    if own_reviews == 0:
        return 50.0  # No data → neutral sentinel

    promoters = kpis.get("own_positive_review_rows", 0)
    detractors = kpis.get("own_negative_review_rows", 0)

    nps = ((promoters - detractors) / own_reviews) * 100
    health = (nps + 100) / 2

    return round(max(0.0, min(100.0, health)), 1)


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
    own_neg_rate = kpis.get("own_negative_review_rate") or 0
    kpis["own_negative_review_rate_display"] = f"{own_neg_rate * 100:.1f}%"
    own_pos = kpis.get("own_positive_review_rows", 0)
    own_total = kpis.get("own_review_rows", 0) or 1
    positive_rate = own_pos / own_total
    kpi_cards = [
        {
            "label": "健康指数",
            "value": kpis.get("health_index", "—"),
            "delta_display": kpis.get("health_index_delta_display", ""),
            "delta_class": "neutral",
            "tooltip": _resolve_tooltip("健康指数"),
        },
        {
            "label": "差评率",
            "value": kpis.get("own_negative_review_rate_display", "—"),
            "delta_display": kpis.get("negative_review_rows_delta_display", ""),
            "delta_class": "up" if (kpis.get("negative_review_rows_delta", 0) or 0) > 0 else "neutral",
            "tooltip": _resolve_tooltip("差评率"),
        },
        {
            "label": "自有评论",
            "value": kpis.get("own_review_rows", 0),
            "delta_display": kpis.get("ingested_review_rows_delta_display", ""),
            "delta_class": "neutral",
            "tooltip": _resolve_tooltip("自有评论"),
        },
        {
            "label": "好评率",
            "value": f"{positive_rate * 100:.1f}%",
            "delta_display": "",
            "delta_class": "neutral",
            "tooltip": "自有产品 ≥4 星评论占比（3 星为中评，不计入好评）",
            "value_class": "severity-low" if positive_rate >= 0.7 else "",
        },
        {
            "label": "高风险产品",
            "value": kpis.get("high_risk_count", 0),
            "delta_display": "",
            "delta_class": "up" if kpis.get("high_risk_count", 0) > 0 else "neutral",
            "tooltip": _resolve_tooltip("高风险产品"),
        },
        {
            "label": "竞品差距指数",
            "value": kpis.get("competitive_gap_index", "—"),
            "delta_display": kpis.get("competitive_gap_index_delta_display", ""),
            "delta_class": "neutral",
            "tooltip": _resolve_tooltip("竞品差距指数"),
        },
    ]

    # Coverage rate card
    site_total = kpis.get("site_reported_review_total_current", 0) or 0
    ingested = kpis.get("ingested_review_rows", 0) or 0
    coverage_rate = ingested / max(site_total, 1) if site_total > 0 else 0
    kpis["coverage_rate"] = coverage_rate
    kpi_cards.append({
        "label": "样本覆盖率",
        "value": f"{coverage_rate:.0%}" if site_total > 0 else "—",
        "delta_display": "",
        "delta_class": "neutral",
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

    if not normalized["report_copy"]["hero_headline"]:
        normalized["report_copy"]["hero_headline"] = _fallback_hero_headline(normalized)
    if not normalized["report_copy"]["executive_bullets"]:
        normalized["report_copy"]["executive_bullets"] = _fallback_executive_bullets(normalized)

    return normalized
