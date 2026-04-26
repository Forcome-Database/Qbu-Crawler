"""采集字段缺失统计与告警阈值判定。

与 report_snapshot.detect_snapshot_changes 共享 missing-value 约定（None/""/"unknown"）。
"""

from typing import Iterable

MISSING_SENTINELS = (None, "", "unknown")


def _is_missing(v) -> bool:
    return v in MISSING_SENTINELS


def _safe_int(p: dict, key: str) -> int:
    """Convert p[key] to int; treat None / "" / missing as 0."""
    return int(p.get(key, 0) or 0)


def summarize_scrape_quality(
    products: Iterable[dict],
    *,
    low_coverage_threshold: float = 0.6,
) -> dict:
    """对一次采集的产品列表统计字段缺失 + 采集完整度 (F011 H1)。

    入参每条 dict 至少含 rating / stock_status / review_count。
    ingested_count 字段可选，缺失时默认 0（兼容尚未回填的旧快照）。

    返回 dict（JSON-safe）：
        legacy keys:
            total, missing_rating, missing_stock, missing_review_count,
            missing_rating_ratio, missing_stock_ratio, missing_review_count_ratio
        F011 H1 new keys:
            zero_scrape_skus / zero_scrape_count
            scrape_completeness_ratio (global ingested_total/site_total; 1.0 when site_total=0)
            low_coverage_skus / low_coverage_count (per-product ingested/site < threshold)
    """
    products = list(products)
    total = len(products)

    # --- legacy missing-field metrics (unchanged contract) ---
    missing_rating = sum(1 for p in products if _is_missing(p.get("rating")))
    missing_stock = sum(1 for p in products if _is_missing(p.get("stock_status")))
    missing_rc = sum(1 for p in products if _is_missing(p.get("review_count")))

    def _ratio(n: int) -> float:
        return n / total if total > 0 else 0.0

    # --- new F011 metrics ---
    site_total = sum(_safe_int(p, "review_count") for p in products)
    ingested_total = sum(_safe_int(p, "ingested_count") for p in products)

    zero_scrape_skus = [
        p["sku"] for p in products
        if (_safe_int(p, "review_count") > 0)
        and (_safe_int(p, "ingested_count") == 0)
    ]

    low_coverage_skus = []
    for p in products:
        site = _safe_int(p, "review_count")
        ingested = _safe_int(p, "ingested_count")
        if site > 0 and (ingested / site) < low_coverage_threshold:
            low_coverage_skus.append(p["sku"])

    completeness = (ingested_total / site_total) if site_total else 1.0

    return {
        # legacy
        "total": total,
        "missing_rating": missing_rating,
        "missing_stock": missing_stock,
        "missing_review_count": missing_rc,
        "missing_rating_ratio": _ratio(missing_rating),
        "missing_stock_ratio": _ratio(missing_stock),
        "missing_review_count_ratio": _ratio(missing_rc),
        # F011 H1 new
        "zero_scrape_skus": zero_scrape_skus,
        "zero_scrape_count": len(zero_scrape_skus),
        "scrape_completeness_ratio": round(completeness, 4),
        "low_coverage_skus": low_coverage_skus,
        "low_coverage_count": len(low_coverage_skus),
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
