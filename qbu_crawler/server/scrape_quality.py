"""采集字段缺失统计与告警阈值判定。

与 report_snapshot.detect_snapshot_changes 共享 missing-value 约定（None/""/"unknown"）。
"""

from typing import Iterable

MISSING_SENTINELS = (None, "", "unknown")


def _is_missing(v) -> bool:
    return v in MISSING_SENTINELS


def summarize_scrape_quality(products: Iterable[dict]) -> dict:
    """对一次采集的产品列表统计字段缺失。

    入参每条 dict 至少含 rating / stock_status / review_count。
    返回 dict（JSON-safe）：
        total, missing_rating, missing_stock, missing_review_count,
        missing_rating_ratio, missing_stock_ratio, missing_review_count_ratio
    """
    products = list(products)
    total = len(products)
    missing_rating = sum(1 for p in products if _is_missing(p.get("rating")))
    missing_stock = sum(1 for p in products if _is_missing(p.get("stock_status")))
    missing_rc = sum(1 for p in products if _is_missing(p.get("review_count")))

    def _ratio(n: int) -> float:
        return n / total if total > 0 else 0.0

    return {
        "total": total,
        "missing_rating": missing_rating,
        "missing_stock": missing_stock,
        "missing_review_count": missing_rc,
        "missing_rating_ratio": _ratio(missing_rating),
        "missing_stock_ratio": _ratio(missing_stock),
        "missing_review_count_ratio": _ratio(missing_rc),
    }


def should_raise_alert(quality: dict, threshold: float) -> bool:
    """任一字段缺失率超过阈值即告警。total=0 时不告警（采集为空另行处理）。"""
    if (quality.get("total") or 0) == 0:
        return False
    return any(
        quality.get(key, 0.0) >= threshold
        for key in ("missing_rating_ratio",
                    "missing_stock_ratio",
                    "missing_review_count_ratio")
    )
