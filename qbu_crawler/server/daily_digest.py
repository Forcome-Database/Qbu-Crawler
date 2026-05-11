from __future__ import annotations

import json
from collections import Counter

from qbu_crawler import config
from qbu_crawler.server.report_common import _LABEL_DISPLAY

MAX_ORIGINAL_LENGTH = 120
MAX_TRANSLATION_LENGTH = 120
MAX_ANALYSIS_LENGTH = 120
MAX_PRODUCT_NAME_LENGTH = 18

TEXT_ELLIPSIS = "…"
TEXT_UNCLASSIFIED = "未分类"
TEXT_UNKNOWN_SKU = "未知 SKU"
TEXT_GOOD = "好评"
TEXT_BAD = "差评"
TEXT_NEUTRAL = "中性"
TEXT_UNKNOWN = "未知"
TEXT_NO_NEW = "今日无新增评论"
TEXT_HAS_NEW = "今日新增评论"
TEXT_TRANSLATING = "翻译中"

# 视觉锚（emoji）— 钉钉 Markdown 兼容
# 注意：emoji 一物一锚，避免重复使用造成视觉混淆。
EMOJI_HEADER = "🔍"      # 顶部标题（监控）
EMOJI_RED = "🔴"
EMOJI_GREEN = "🟢"
EMOJI_GRAY = "⚪"
EMOJI_BASELINE = "📊"    # 累计/监控起点
EMOJI_DAILY = "📥"       # 今日新增
EMOJI_AI = "🤖"          # AI 判断（机器人 = AI）
EMOJI_RAW = "📝"         # 原文（笔记 = 原始文本）
EMOJI_INSIGHT = "🎯"     # 关键判断
EMOJI_PIN = "📍"         # 风险/集中度定位


def _text(value) -> str:
    return str(value or "").strip()


def _truncate(value, limit=MAX_ORIGINAL_LENGTH) -> str:
    text = _text(value).replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + TEXT_ELLIPSIS


def _short_product_name(name: str | None, limit: int = MAX_PRODUCT_NAME_LENGTH) -> str:
    """产品名截断到 ~18 字，便于挂在 SKU 后面而不撑爆 meta 行。"""
    text = _text(name)
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + TEXT_ELLIPSIS


def _label_display(review: dict) -> str:
    labels = review.get("analysis_labels")
    if isinstance(labels, str) and labels.strip():
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    if isinstance(labels, list) and labels:
        first = labels[0] or {}
        if isinstance(first, dict):
            code = _text(first.get("code"))
            return _text(first.get("display") or first.get("label") or _LABEL_DISPLAY.get(code) or code)
    return _text(review.get("impact_category") or review.get("failure_mode") or TEXT_UNCLASSIFIED)


def _rating_value(review: dict, default=0) -> float:
    try:
        return float(review.get("rating"))
    except (TypeError, ValueError):
        return default


def _review_sku(review: dict) -> str:
    return _text(review.get("product_sku") or review.get("sku") or TEXT_UNKNOWN_SKU)


def _review_item(review: dict) -> dict:
    return {
        "id": review.get("id"),
        "sku": _review_sku(review),
        "product_name": _text(review.get("product_name") or review.get("name")),
        "rating": review.get("rating"),
        "sentiment": _text(review.get("sentiment")),
        "issue": _label_display(review),
        "original": _truncate(review.get("body") or review.get("headline")),
        "translation": _truncate(review.get("body_cn") or review.get("headline_cn"), MAX_TRANSLATION_LENGTH),
        "analysis": _truncate(review.get("analysis_insight_cn") or review.get("analysis_insight_en") or _label_display(review), MAX_ANALYSIS_LENGTH),
    }


def _own_rank(review: dict):
    rating = _rating_value(review, 5)
    negative = rating <= config.NEGATIVE_THRESHOLD
    has_analysis = bool(_text(review.get("analysis_insight_cn")))
    return (0 if negative else 1, rating, 0 if has_analysis else 1, _text(review.get("scraped_at")))


def _competitor_rank(review: dict):
    rating = _rating_value(review, 0)
    positive = rating >= 5 or _text(review.get("sentiment")).lower() == "positive"
    has_analysis = bool(_text(review.get("analysis_insight_cn")))
    return (0 if positive else 1, -rating, 0 if has_analysis else 1, _text(review.get("scraped_at")))


def _positive_rank(review: dict):
    rating = _rating_value(review, 0)
    has_analysis = bool(_text(review.get("analysis_insight_cn")))
    return (-rating, 0 if has_analysis else 1, _text(review.get("scraped_at")))


def _negative_rank(review: dict):
    rating = _rating_value(review, 5)
    has_analysis = bool(_text(review.get("analysis_insight_cn")))
    return (rating, 0 if has_analysis else 1, _text(review.get("scraped_at")))


def _item_tone(item: dict, competitor: bool = False) -> str:
    rating = _rating_value(item, 0)
    if rating <= config.NEGATIVE_THRESHOLD:
        return TEXT_BAD
    if rating >= 4:
        return TEXT_GOOD
    return TEXT_NEUTRAL


def _rating_display(item: dict) -> str:
    rating = item.get("rating")
    if rating is None or rating == "":
        return TEXT_UNKNOWN
    try:
        return f"{float(rating):.1f}"
    except (TypeError, ValueError):
        return str(rating)


def _dedup_by_sku(reviews: list[dict], limit: int = 3) -> list[dict]:
    """SKU 多样性优先 + 不足时回填同 SKU 次重要评论。

    - 第 1 轮：每个 SKU 至多取 1 条（确保 TOP 3 覆盖多产品）
    - 第 2 轮：若 SKU 不足 limit 条，从 leftover 池按原排序补齐（同 SKU 的次重要评论）

    例：
      3 个 SKU 各 10 条差评 → TOP 3 = 三个不同 SKU 各 1 条
      1 个 SKU 10 条差评     → TOP 3 = 同 SKU 的 3 条最重要差评（回退到原排序）
      2 个 SKU 各 5 条差评    → TOP 3 = SKU1#1, SKU2#1, SKU1#2（多样性 + 深度）

    保留输入顺序（排序稳定性），最重要的那条优先入选。空 SKU 视为同一 fallback 桶。
    """
    if not reviews:
        return []
    seen: set[str] = set()
    primary: list[dict] = []
    leftover: list[dict] = []
    for r in reviews:
        sku = _review_sku(r) or "__nosku__"
        if sku in seen:
            leftover.append(r)
        else:
            seen.add(sku)
            primary.append(r)
    result = primary[:limit]
    if len(result) < limit:
        result.extend(leftover[: limit - len(result)])
    return result


def _aggregate_top_labels(reviews: list[dict], top_n: int = 2) -> list[tuple[str, int]]:
    counter = Counter(_label_display(r) for r in reviews if _label_display(r))
    return counter.most_common(top_n)


def _aggregate_top_skus(reviews: list[dict], top_n: int = 2) -> list[tuple[str, int]]:
    counter = Counter(_review_sku(r) for r in reviews if _review_sku(r))
    return counter.most_common(top_n)


def _meta_line(index: int, item: dict) -> str:
    """渲染单条证据的 meta 行：序号 + SKU + 产品名(短) + 星评 + 标签。

    布局：**1.** `SKU` 产品名 · ★ 1.0 · **标签**
    section 标题已经携带 lamp emoji（🔴/🟢/⚪），item 不再重复挂灯，避免视觉拥挤。
    """
    rating = _rating_display(item)
    sku = item.get("sku") or TEXT_UNKNOWN_SKU
    pname = _short_product_name(item.get("product_name"))
    sku_part = f"`{sku}`" + (f" {pname}" if pname else "")
    return f"**{index}.** {sku_part} · ★ {rating} · **{item['issue']}**"


def _render_items(items: list[dict], *, empty: str) -> list[str]:
    """以钉钉 Markdown 渲染证据块（4 行 / 条，全部内容保留，条间加 --- 分隔）。

    布局：
        **N.** `SKU` 产品名 · ★ 1.0 · **标签**
        > 译文（完整保留）
        **🤖 AI**：…
        **📝 EN**：…
        ---
    """
    if not items:
        return [empty]
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        if index > 1:
            lines.append("---")  # TOP 3 条间分隔
        lines.append(_meta_line(index, item))
        lines.append(f"> {item['translation'] or TEXT_TRANSLATING}")
        lines.append(f"**{EMOJI_AI} AI**：{item['analysis']}")
        lines.append(f"**{EMOJI_RAW} EN**：{item['original']}")
    return lines


def _render_neutral_items(items: list[dict], *, title: str) -> list[str]:
    if not items:
        return []
    lines = [f"**{title}**"]
    for index, item in enumerate(items, start=1):
        if index > 1:
            lines.append("---")
        lines.append(_meta_line(index, item))
        lines.append(f"> {item['translation'] or TEXT_TRANSLATING}")
        lines.append(f"**{EMOJI_AI} AI**：{item['analysis']}")
        lines.append(f"**{EMOJI_RAW} EN**：{item['original']}")
    return lines


def _build_analysis(payload: dict) -> str:
    """文本版 analysis（保持 backward-compatible 字段，被 outbox / 邮件等其它处复用）。"""
    if payload["new_review_count"] == 0:
        return (
            f"{TEXT_NO_NEW}。当前累计样本："
            f"自有 {payload['cumulative_own_count']} 条 / "
            f"竞品 {payload['cumulative_competitor_count']} 条。"
        )
    parts = []
    if payload["own_top"]:
        first = payload["own_top"][0]
        if payload["own_section_type"] == "risk":
            parts.append(f"自有风险优先关注 {first['sku']} 的{first['issue']}：{first['analysis']}")
        elif payload["own_section_type"] == "highlight":
            parts.append(f"自有新增正向反馈集中在 {first['sku']} 的{first['issue']}：{first['analysis']}")
        else:
            parts.append(f"自有新增评论集中在 {first['sku']} 的{first['issue']}：{first['analysis']}")
    if payload["competitor_top"]:
        first = payload["competitor_top"][0]
        if payload["competitor_section_type"] == "highlight":
            parts.append(f"竞品可参考 {first['sku']} 的{first['issue']}：{first['analysis']}")
        elif payload["competitor_section_type"] == "opportunity":
            parts.append(f"竞品差评暴露 {first['sku']} 的{first['issue']}，可作为自有机会参考：{first['analysis']}")
        else:
            parts.append(f"竞品新增评论集中在 {first['sku']} 的{first['issue']}：{first['analysis']}")
    return "；".join(parts) or "今日新增评论已入库，暂未形成明确高优先级信号。"


def _format_label_dist(label_dist: list[tuple[str, int]], top: int = 2) -> str:
    """`["清洁维护", 17] / ["噪音与动力", 9]` → '**清洁维护** 17 条、**噪音与动力** 9 条'."""
    return "、".join(f"**{name}** {count} 条" for name, count in label_dist[:top])


def _format_sku_dist(sku_dist: list[tuple[str, int]], top: int = 2) -> str:
    return "、".join(f"`{sku}` ({count} 条)" for sku, count in sku_dist[:top])


def _render_analysis_block(payload: dict) -> list[str]:
    """关键判断：从"复述 TOP 1"改为"聚合视角"——差评率/好评率 + 标签集中 + 风险产品集中度。"""
    if payload["new_review_count"] == 0:
        return [f"**{EMOJI_INSIGHT} 关键判断**", f"- {TEXT_NO_NEW}。"]

    bullets: list[str] = []

    own_neg = payload["own_negative_count"]
    own_total = payload["own_new_count"]
    own_pos = payload["own_positive_count"]

    # 自有侧聚合
    if own_total > 0:
        if own_neg > 0:
            rate = own_neg / own_total * 100
            label_str = _format_label_dist(payload.get("own_negative_label_top") or [])
            tail = f"，集中在 {label_str}" if label_str else ""
            bullets.append(
                f"- {EMOJI_RED} 自有差评率 `{own_neg}/{own_total} ≈ {rate:.1f}%`{tail}"
            )
        elif own_pos > 0:
            label_str = _format_label_dist(payload.get("own_positive_label_top") or [])
            tail = f"，亮点集中在 {label_str}" if label_str else ""
            bullets.append(
                f"- {EMOJI_GREEN} 自有正向反馈 `{own_pos}/{own_total}`{tail}"
            )

    # 竞品侧聚合
    cmp_pos = payload["competitor_positive_count"]
    cmp_neg = payload["competitor_negative_count"]
    cmp_total = payload["competitor_new_count"]
    if cmp_total > 0:
        if cmp_pos > 0:
            rate = cmp_pos / cmp_total * 100
            label_str = _format_label_dist(payload.get("competitor_positive_label_top") or [])
            tail = f"，亮点集中在 {label_str}" if label_str else ""
            bullets.append(
                f"- {EMOJI_GREEN} 竞品好评率 `{cmp_pos}/{cmp_total} ≈ {rate:.1f}%`{tail}"
            )
        elif cmp_neg > 0:
            label_str = _format_label_dist(payload.get("competitor_negative_label_top") or [])
            tail = f"，可作机会参考 {label_str}" if label_str else ""
            bullets.append(
                f"- {EMOJI_RED} 竞品差评 `{cmp_neg}/{cmp_total}`{tail}"
            )

    # 风险产品集中度（自有差评 SKU 热度）
    risk_skus = payload.get("own_negative_sku_top") or []
    if risk_skus:
        bullets.append(f"- {EMOJI_PIN} 风险产品集中：{_format_sku_dist(risk_skus)}")

    if not bullets:
        bullets.append("- 今日新增评论已入库，暂未形成明确高优先级信号。")

    return [f"**{EMOJI_INSIGHT} 关键判断**", *bullets]


def _section_title(ownership: str, section_type: str) -> str:
    if ownership == "own":
        if section_type == "risk":
            return f"{EMOJI_RED} 自有风险 · TOP 3"
        if section_type == "highlight":
            return f"{EMOJI_GREEN} 自有亮点 · TOP 3"
        return f"{EMOJI_GRAY} 自有新增评论 · TOP 3"
    if section_type == "highlight":
        return f"{EMOJI_GREEN} 竞品亮点 · TOP 3"
    if section_type == "opportunity":
        return f"{EMOJI_RED} 竞品机会 · TOP 3"
    return f"{EMOJI_GRAY} 竞品新增评论 · TOP 3"


def _render_summary_line(payload: dict) -> str:
    """顶部三色灯摘要：emoji + inline code 数字。"""
    own_neg = payload["own_negative_count"]
    own_pos = payload["own_positive_count"]
    own_neu = payload["own_neutral_count"]
    cmp_pos = payload["competitor_positive_count"]
    cmp_neg = payload["competitor_negative_count"]
    cmp_neu = payload["competitor_neutral_count"]
    return (
        f"{EMOJI_RED} 差评 自有 `{own_neg}` / 竞品 `{cmp_neg}` · "
        f"{EMOJI_GREEN} 好评 自有 `{own_pos}` / 竞品 `{cmp_pos}` · "
        f"{EMOJI_GRAY} 中评 自有 `{own_neu}` / 竞品 `{cmp_neu}`"
    )


def _render_baseline_line(payload: dict) -> str:
    """累计样本行。bootstrap 日（累计 == 今日新增）合并显示为"监控起点"。"""
    own = payload["cumulative_own_count"]
    cmp = payload["cumulative_competitor_count"]
    own_new = payload["own_new_count"]
    cmp_new = payload["competitor_new_count"]
    has_data = (own_new + cmp_new) > 0
    is_bootstrap = has_data and own == own_new and cmp == cmp_new
    if is_bootstrap:
        return f"{EMOJI_BASELINE} 监控起点（首次入库）：自有 `{own}` 条 / 竞品 `{cmp}` 条"
    return f"{EMOJI_BASELINE} 累计样本：自有 `{own}` 条 / 竞品 `{cmp}` 条"


def _join_blocks(*blocks) -> str:
    """以空行分段拼接（钉钉 Markdown 用 \\n\\n 强制段落断行）。"""
    flat: list[str] = []
    for block in blocks:
        if block is None:
            continue
        if isinstance(block, list):
            for line in block:
                if line is not None:
                    flat.append(line)
        else:
            flat.append(block)
    return "\n\n".join(s for s in flat if s != "")


def _render_markdown(payload: dict) -> str:
    title = f"## {EMOJI_HEADER} QBU 今日评论监控 · {payload['logical_date']}"
    if payload["new_review_count"] == 0:
        no_new_line = f"{EMOJI_GRAY} {TEXT_NO_NEW}（今日总入库 `0` 条）"
        return _join_blocks(
            title,
            no_new_line,
            _render_baseline_line(payload),
            "---",
            _render_analysis_block(payload),
        )

    summary_total = (
        f"{EMOJI_DAILY} 今日新增 `{payload['new_review_count']}` 条 · "
        f"自有 `{payload['own_new_count']}` / 竞品 `{payload['competitor_new_count']}`"
    )

    own_section_lines: list[str] = []
    if payload["own_top"] or payload["own_new_count"]:
        # section 标题：H3 → bold（字号降一档，整体节奏更平顺）
        own_section_lines.append(f"**{_section_title('own', payload['own_section_type'])}**")
        own_section_lines.extend(
            _render_items(
                payload["own_top"],
                empty=f"{EMOJI_GRAY} 今日无自有新增评论",
            )
        )

    competitor_section_lines: list[str] = []
    if payload["competitor_top"] or payload["competitor_new_count"]:
        competitor_section_lines.append(
            f"**{_section_title('competitor', payload['competitor_section_type'])}**"
        )
        competitor_section_lines.extend(
            _render_items(
                payload["competitor_top"],
                empty=f"{EMOJI_GRAY} 今日无竞品新增评论",
            )
        )

    neutral_section_lines: list[str] = []
    if payload["own_neutral_top"] or payload["competitor_neutral_top"]:
        neutral_section_lines.append(f"**{EMOJI_GRAY} 中评观察**")
        neutral_section_lines.extend(
            _render_neutral_items(
                payload["own_neutral_top"],
                title=f"自有中评 {payload['own_neutral_count']} 条",
            )
        )
        neutral_section_lines.extend(
            _render_neutral_items(
                payload["competitor_neutral_top"],
                title=f"竞品中评 {payload['competitor_neutral_count']} 条",
            )
        )

    return _join_blocks(
        title,
        _render_summary_line(payload),
        summary_total,
        _render_baseline_line(payload),
        "---",
        own_section_lines or None,
        competitor_section_lines or None,
        neutral_section_lines or None,
        "---",
        _render_analysis_block(payload),
    )


def build_daily_digest(snapshot: dict) -> dict:
    reviews = list(snapshot.get("reviews") or [])
    own_reviews = [r for r in reviews if r.get("ownership") == "own"]
    competitor_reviews = [r for r in reviews if r.get("ownership") == "competitor"]
    cumulative_reviews = list((snapshot.get("cumulative") or {}).get("reviews") or [])
    own_negative = [r for r in own_reviews if _rating_value(r, 5) <= config.NEGATIVE_THRESHOLD]
    own_positive = [r for r in own_reviews if _rating_value(r, 0) >= 4]
    competitor_positive = [
        r for r in competitor_reviews
        if _rating_value(r, 0) >= 4 or _text(r.get("sentiment")).lower() == "positive"
    ]
    competitor_negative = [r for r in competitor_reviews if _rating_value(r, 5) <= config.NEGATIVE_THRESHOLD]
    own_neutral = [r for r in own_reviews if r not in own_positive and r not in own_negative]
    competitor_neutral = [r for r in competitor_reviews if r not in competitor_positive and r not in competitor_negative]
    own_section_type = "risk" if own_negative else ("highlight" if own_positive else "neutral")
    competitor_section_type = "highlight" if competitor_positive else ("opportunity" if competitor_negative else "neutral")
    own_source = sorted(own_negative, key=_negative_rank) if own_negative else sorted(own_reviews, key=_positive_rank)
    competitor_source = (
        sorted(competitor_positive, key=_competitor_rank)
        if competitor_positive
        else sorted(competitor_reviews, key=_negative_rank)
    )
    # SKU dedup：同一产品在 TOP 3 里最多 1 条，确保多产品覆盖广度。
    own_top = [_review_item(r) for r in _dedup_by_sku(own_source, 3)]
    competitor_top = [_review_item(r) for r in _dedup_by_sku(competitor_source, 3)]
    # 中评示例从 [:1] 升到 [:2]，给出更多对比样本
    own_neutral_top = [_review_item(r) for r in _dedup_by_sku(sorted(own_neutral, key=_positive_rank), 2)]
    competitor_neutral_top = [_review_item(r) for r in _dedup_by_sku(sorted(competitor_neutral, key=_positive_rank), 2)]

    payload = {
        "run_id": snapshot.get("run_id"),
        "logical_date": snapshot.get("logical_date", ""),
        "new_review_count": int(snapshot.get("reviews_count") or len(reviews)),
        "own_new_count": len(own_reviews),
        "competitor_new_count": len(competitor_reviews),
        "own_positive_count": len(own_positive),
        "own_neutral_count": len(own_neutral),
        "own_negative_count": len(own_negative),
        "competitor_positive_count": len(competitor_positive),
        "competitor_neutral_count": len(competitor_neutral),
        "competitor_negative_count": len(competitor_negative),
        "cumulative_own_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "own"),
        "cumulative_competitor_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "competitor"),
        "own_top": own_top,
        "competitor_top": competitor_top,
        "own_neutral_top": own_neutral_top,
        "competitor_neutral_top": competitor_neutral_top,
        "own_section_type": own_section_type,
        "competitor_section_type": competitor_section_type,
        "message_title": TEXT_NO_NEW if not reviews else TEXT_HAS_NEW,
        # 聚合统计：供"关键判断"做群体视角而非个体复述
        "own_negative_label_top": _aggregate_top_labels(own_negative),
        "own_positive_label_top": _aggregate_top_labels(own_positive),
        "competitor_positive_label_top": _aggregate_top_labels(competitor_positive),
        "competitor_negative_label_top": _aggregate_top_labels(competitor_negative),
        "own_negative_sku_top": _aggregate_top_skus(own_negative),
    }
    payload["analysis"] = _build_analysis(payload)
    payload["markdown"] = _render_markdown(payload)
    return payload
