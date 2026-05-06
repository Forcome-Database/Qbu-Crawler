from __future__ import annotations

import json

from qbu_crawler import config

MAX_ORIGINAL_LENGTH = 120

TEXT_ELLIPSIS = "\u2026"
TEXT_UNCLASSIFIED = "\u672a\u5206\u7c7b"
TEXT_UNKNOWN_SKU = "\u672a\u77e5 SKU"
TEXT_GOOD = "\u597d\u8bc4"
TEXT_BAD = "\u5dee\u8bc4"
TEXT_NEUTRAL = "\u4e2d\u6027"
TEXT_UNKNOWN = "\u672a\u77e5"
TEXT_NO_NEW = "\u4eca\u65e5\u65e0\u65b0\u589e\u8bc4\u8bba"
TEXT_HAS_NEW = "\u4eca\u65e5\u65b0\u589e\u8bc4\u8bba"


def _text(value) -> str:
    return str(value or "").strip()


def _truncate(value, limit=MAX_ORIGINAL_LENGTH) -> str:
    text = _text(value).replace("\n", " ")
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
            return _text(first.get("display") or first.get("label") or first.get("code"))
    return _text(review.get("impact_category") or review.get("failure_mode") or review.get("headline") or TEXT_UNCLASSIFIED)


def _rating_value(review: dict, default=0) -> float:
    try:
        return float(review.get("rating"))
    except (TypeError, ValueError):
        return default


def _review_item(review: dict) -> dict:
    return {
        "id": review.get("id"),
        "sku": _text(review.get("product_sku") or review.get("sku") or TEXT_UNKNOWN_SKU),
        "product_name": _text(review.get("product_name") or review.get("name")),
        "rating": review.get("rating"),
        "sentiment": _text(review.get("sentiment")),
        "issue": _label_display(review),
        "original": _truncate(review.get("body_cn") or review.get("body") or review.get("headline")),
        "analysis": _truncate(review.get("analysis_insight_cn") or review.get("analysis_insight_en") or _label_display(review), 160),
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


def _item_tone(item: dict, competitor: bool = False) -> str:
    rating = _rating_value(item, 0)
    if competitor and rating >= 4:
        return TEXT_GOOD
    if rating <= config.NEGATIVE_THRESHOLD:
        return TEXT_BAD
    return TEXT_NEUTRAL


def _render_items(items: list[dict], *, empty: str, competitor: bool = False) -> list[str]:
    if not items:
        return [f"- {empty}"]
    lines = []
    for item in items:
        lines.append(
            f"- SKU:{item['sku']}\uff0c{_item_tone(item, competitor=competitor)}\uff0c"
            f"\u8bc4\u5206 {item.get('rating') or TEXT_UNKNOWN} \u5206\uff0c\u95ee\u9898 {item['issue']}"
        )
        lines.append(f"  \u539f\u6587\uff1a{item['original']}")
    return lines


def _build_analysis(payload: dict) -> str:
    if payload["new_review_count"] == 0:
        return (
            f"{TEXT_NO_NEW}\u3002\u5f53\u524d\u7d2f\u8ba1\u6837\u672c\uff1a"
            f"\u81ea\u6709 {payload['cumulative_own_count']} \u6761 / "
            f"\u7ade\u54c1 {payload['cumulative_competitor_count']} \u6761\u3002"
        )
    parts = []
    if payload["own_top"]:
        first = payload["own_top"][0]
        parts.append(f"\u81ea\u6709\u91cd\u70b9\u5173\u6ce8 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
    if payload["competitor_top"]:
        first = payload["competitor_top"][0]
        parts.append(f"\u7ade\u54c1\u53ef\u53c2\u8003 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
    return "\uff1b".join(parts) or "\u4eca\u65e5\u65b0\u589e\u8bc4\u8bba\u5df2\u5165\u5e93\uff0c\u6682\u672a\u5f62\u6210\u660e\u786e\u9ad8\u4f18\u5148\u7ea7\u4fe1\u53f7\u3002"


def _render_markdown(payload: dict) -> str:
    if payload["new_review_count"] == 0:
        return (
            f"## QBU \u4eca\u65e5\u8bc4\u8bba\u76d1\u63a7 · {payload['logical_date']}\n\n"
            f"{TEXT_NO_NEW}\u3002\n\n"
            f"\u5f53\u524d\u7d2f\u8ba1\u6837\u672c\uff1a\u81ea\u6709 {payload['cumulative_own_count']} \u6761 / "
            f"\u7ade\u54c1 {payload['cumulative_competitor_count']} \u6761\u3002\n\n"
            f"\u5206\u6790\uff1a{payload['analysis']}"
        )
    lines = [
        f"## QBU \u4eca\u65e5\u8bc4\u8bba\u76d1\u63a7 · {payload['logical_date']}",
        "",
        f"{TEXT_HAS_NEW} `{payload['new_review_count']}` \u6761",
        f"\u81ea\u6709\u65b0\u589e {payload['own_new_count']} \u6761\uff0c\u7ade\u54c1\u65b0\u589e {payload['competitor_new_count']} \u6761",
        "",
        "### \u81ea\u6709 TOP3",
    ]
    lines.extend(_render_items(payload["own_top"], empty="\u6682\u65e0\u81ea\u6709\u5dee\u8bc4\u6216\u91cd\u70b9\u8bc4\u8bba"))
    lines.extend(["", "### \u7ade\u54c1 TOP3"])
    lines.extend(_render_items(payload["competitor_top"], empty="\u6682\u65e0\u7ade\u54c1\u597d\u8bc4\u6216\u91cd\u70b9\u8bc4\u8bba", competitor=True))
    lines.extend(["", f"\u5206\u6790\uff1a{payload['analysis']}"])
    return "\n".join(lines)


def build_daily_digest(snapshot: dict) -> dict:
    reviews = list(snapshot.get("reviews") or [])
    own_reviews = [r for r in reviews if r.get("ownership") == "own"]
    competitor_reviews = [r for r in reviews if r.get("ownership") == "competitor"]
    cumulative_reviews = list((snapshot.get("cumulative") or {}).get("reviews") or [])
    own_top = [_review_item(r) for r in sorted(own_reviews, key=_own_rank)[:3]]
    competitor_top = [_review_item(r) for r in sorted(competitor_reviews, key=_competitor_rank)[:3]]
    payload = {
        "run_id": snapshot.get("run_id"),
        "logical_date": snapshot.get("logical_date", ""),
        "new_review_count": int(snapshot.get("reviews_count") or len(reviews)),
        "own_new_count": len(own_reviews),
        "competitor_new_count": len(competitor_reviews),
        "own_negative_count": sum(1 for r in own_reviews if _rating_value(r, 5) <= config.NEGATIVE_THRESHOLD),
        "competitor_positive_count": sum(1 for r in competitor_reviews if _rating_value(r, 0) >= 5),
        "cumulative_own_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "own"),
        "cumulative_competitor_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "competitor"),
        "own_top": own_top,
        "competitor_top": competitor_top,
        "message_title": TEXT_NO_NEW if not reviews else TEXT_HAS_NEW,
    }
    payload["analysis"] = _build_analysis(payload)
    payload["markdown"] = _render_markdown(payload)
    return payload
