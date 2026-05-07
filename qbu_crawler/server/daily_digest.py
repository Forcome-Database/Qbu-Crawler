from __future__ import annotations

import json

from qbu_crawler import config
from qbu_crawler.server.report_common import _LABEL_DISPLAY

MAX_ORIGINAL_LENGTH = 120
MAX_TRANSLATION_LENGTH = 120
MAX_ANALYSIS_LENGTH = 120

TEXT_ELLIPSIS = "\u2026"
TEXT_UNCLASSIFIED = "\u672a\u5206\u7c7b"
TEXT_UNKNOWN_SKU = "\u672a\u77e5 SKU"
TEXT_GOOD = "\u597d\u8bc4"
TEXT_BAD = "\u5dee\u8bc4"
TEXT_NEUTRAL = "\u4e2d\u6027"
TEXT_UNKNOWN = "\u672a\u77e5"
TEXT_NO_NEW = "\u4eca\u65e5\u65e0\u65b0\u589e\u8bc4\u8bba"
TEXT_HAS_NEW = "\u4eca\u65e5\u65b0\u589e\u8bc4\u8bba"
TEXT_TRANSLATING = "\u7ffb\u8bd1\u4e2d"


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
            code = _text(first.get("code"))
            return _text(first.get("display") or first.get("label") or _LABEL_DISPLAY.get(code) or code)
    return _text(review.get("impact_category") or review.get("failure_mode") or TEXT_UNCLASSIFIED)


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


def _render_items(items: list[dict], *, empty: str, competitor: bool = False, label_name: str = "\u95ee\u9898") -> list[str]:
    if not items:
        return [empty]
    lines = []
    for index, item in enumerate(items, start=1):
        lines.append(
            f"{index}. SKU:{item['sku']}\uff0c{_item_tone(item, competitor=competitor)}\uff0c"
            f"\u8bc4\u5206 {item.get('rating') or TEXT_UNKNOWN} \u5206\uff0c{label_name} {item['issue']}"
        )
        lines.append(f"  \u539f\u6587\uff1a{item['original']}")
        lines.append(f"  \u8bd1\u6587\uff1a{item['translation'] or TEXT_TRANSLATING}")
        lines.append(f"  \u5224\u65ad\uff1a{item['analysis']}")
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
        if payload["own_section_type"] == "risk":
            parts.append(f"\u81ea\u6709\u98ce\u9669\u4f18\u5148\u5173\u6ce8 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
        elif payload["own_section_type"] == "highlight":
            parts.append(f"\u81ea\u6709\u65b0\u589e\u6b63\u5411\u53cd\u9988\u96c6\u4e2d\u5728 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
        else:
            parts.append(f"\u81ea\u6709\u65b0\u589e\u8bc4\u8bba\u96c6\u4e2d\u5728 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
    if payload["competitor_top"]:
        first = payload["competitor_top"][0]
        if payload["competitor_section_type"] == "highlight":
            parts.append(f"\u7ade\u54c1\u53ef\u53c2\u8003 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
        elif payload["competitor_section_type"] == "opportunity":
            parts.append(f"\u7ade\u54c1\u5dee\u8bc4\u66b4\u9732 {first['sku']} \u7684{first['issue']}\uff0c\u53ef\u4f5c\u4e3a\u81ea\u6709\u673a\u4f1a\u53c2\u8003\uff1a{first['analysis']}")
        else:
            parts.append(f"\u7ade\u54c1\u65b0\u589e\u8bc4\u8bba\u96c6\u4e2d\u5728 {first['sku']} \u7684{first['issue']}\uff1a{first['analysis']}")
    return "\uff1b".join(parts) or "\u4eca\u65e5\u65b0\u589e\u8bc4\u8bba\u5df2\u5165\u5e93\uff0c\u6682\u672a\u5f62\u6210\u660e\u786e\u9ad8\u4f18\u5148\u7ea7\u4fe1\u53f7\u3002"


def _section_title(ownership: str, section_type: str) -> str:
    if ownership == "own":
        if section_type == "risk":
            return "\u81ea\u6709\u98ce\u9669 TOP3"
        if section_type == "highlight":
            return "\u81ea\u6709\u4eae\u70b9 TOP3"
        return "\u81ea\u6709\u65b0\u589e\u8bc4\u8bba TOP3"
    if section_type == "highlight":
        return "\u7ade\u54c1\u4eae\u70b9 TOP3"
    if section_type == "opportunity":
        return "\u7ade\u54c1\u673a\u4f1a TOP3"
    return "\u7ade\u54c1\u65b0\u589e\u8bc4\u8bba TOP3"


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
        f"\u81ea\u6709\u65b0\u589e {payload['own_new_count']} \u6761\uff1a\u597d\u8bc4 {payload['own_positive_count']} \u6761\uff0c\u5dee\u8bc4 {payload['own_negative_count']} \u6761",
        f"\u7ade\u54c1\u65b0\u589e {payload['competitor_new_count']} \u6761\uff1a\u597d\u8bc4 {payload['competitor_positive_count']} \u6761\uff0c\u5dee\u8bc4 {payload['competitor_negative_count']} \u6761",
        "",
        f"### {_section_title('own', payload['own_section_type'])}" if payload["own_top"] else "### \u81ea\u6709",
    ]
    own_label = (
        "\u95ee\u9898" if payload["own_section_type"] == "risk"
        else ("\u4eae\u70b9" if payload["own_section_type"] == "highlight" else "\u95ee\u9898/\u53cd\u9988")
    )
    competitor_label = (
        "\u4eae\u70b9" if payload["competitor_section_type"] == "highlight"
        else ("\u95ee\u9898" if payload["competitor_section_type"] == "opportunity" else "\u95ee\u9898/\u53cd\u9988")
    )
    lines.extend(_render_items(payload["own_top"], empty="\u4eca\u65e5\u65e0\u81ea\u6709\u65b0\u589e\u8bc4\u8bba", label_name=own_label))
    lines.extend(["", f"### {_section_title('competitor', payload['competitor_section_type'])}" if payload["competitor_top"] else "### \u7ade\u54c1"])
    lines.extend(_render_items(payload["competitor_top"], empty="\u4eca\u65e5\u65e0\u7ade\u54c1\u65b0\u589e\u8bc4\u8bba", competitor=True, label_name=competitor_label))
    lines.extend(["", f"\u5206\u6790\uff1a{payload['analysis']}"])
    return "\n".join(lines)


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
    own_section_type = "risk" if own_negative else ("highlight" if own_positive else "neutral")
    competitor_section_type = "highlight" if competitor_positive else ("opportunity" if competitor_negative else "neutral")
    own_source = sorted(own_negative, key=_negative_rank) if own_negative else sorted(own_reviews, key=_positive_rank)
    competitor_source = (
        sorted(competitor_positive, key=_competitor_rank)
        if competitor_positive
        else sorted(competitor_reviews, key=_negative_rank)
    )
    own_top = [_review_item(r) for r in own_source[:3]]
    competitor_top = [_review_item(r) for r in competitor_source[:3]]
    payload = {
        "run_id": snapshot.get("run_id"),
        "logical_date": snapshot.get("logical_date", ""),
        "new_review_count": int(snapshot.get("reviews_count") or len(reviews)),
        "own_new_count": len(own_reviews),
        "competitor_new_count": len(competitor_reviews),
        "own_positive_count": len(own_positive),
        "own_negative_count": len(own_negative),
        "competitor_positive_count": len(competitor_positive),
        "competitor_negative_count": len(competitor_negative),
        "cumulative_own_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "own"),
        "cumulative_competitor_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "competitor"),
        "own_top": own_top,
        "competitor_top": competitor_top,
        "own_section_type": own_section_type,
        "competitor_section_type": competitor_section_type,
        "message_title": TEXT_NO_NEW if not reviews else TEXT_HAS_NEW,
    }
    payload["analysis"] = _build_analysis(payload)
    payload["markdown"] = _render_markdown(payload)
    return payload
