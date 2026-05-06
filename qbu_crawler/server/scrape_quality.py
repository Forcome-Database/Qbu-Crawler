"""采集字段缺失统计与告警阈值判定。

与 report_snapshot.detect_snapshot_changes 共享 missing-value 约定（None/""/"unknown"）。
"""

import json
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
    tasks: Iterable[dict] | None = None,
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
    tasks = list(tasks or [])
    total = len(products)

    # --- legacy missing-field metrics (unchanged contract) ---
    missing_rating = sum(1 for p in products if _is_missing(p.get("rating")))
    missing_stock = sum(1 for p in products if _is_missing(p.get("stock_status")))
    missing_rc = sum(1 for p in products if _is_missing(p.get("review_count")))

    def _ratio(n: int) -> float:
        return n / total if total > 0 else 0.0

    # --- new F011 metrics ---
    # ⚠ BV 把 ratings-only（仅星级、无文字）评论也算进 review_count，但 scraper
    # 不可能抓到没文字的评论。"文字评论数" = review_count - ratings_only_count
    # 才是 scraper 真正能抓的目标值，覆盖率必须用这个分母才不会有 false low_coverage。
    # 旧 scraper / 旧产品记录无该字段时 ratings_only_count=0，等同于"全部都是文字评论"，
    # 行为完全向后兼容。
    def _text_review_count(p: dict) -> int:
        site = _safe_int(p, "review_count")
        ratings_only = _safe_int(p, "ratings_only_count")
        return max(0, site - ratings_only)

    extracted_by_key = {}
    summary_text_total_by_key = {}
    expected_urls = []
    saved_urls = []
    failed_urls = []
    for row in tasks:
        params = row.get("params") or {}
        result = row.get("result") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                result = {}
        expected_urls.extend(params.get("urls") or [])
        saved_urls.extend(result.get("saved_urls") or [])
        failed_urls.extend(result.get("failed_urls") or [])
        for item in result.get("product_summaries") or []:
            key = item.get("url") or item.get("sku")
            if not key:
                continue
            extracted_by_key[key] = _safe_int(item, "extracted_review_count")
            site = _safe_int(item, "site_review_count")
            ratings_only = _safe_int(item, "ratings_only_count")
            summary_text_total_by_key[key] = max(0, site - ratings_only)
            if not item.get("url") and item.get("sku"):
                extracted_by_key[item["sku"]] = extracted_by_key[key]
                summary_text_total_by_key[item["sku"]] = summary_text_total_by_key[key]
        if not saved_urls:
            saved_urls.extend([
                item.get("url")
                for item in (result.get("product_summaries") or [])
                if item.get("url")
            ])

    def _product_key(p: dict) -> str:
        return p.get("url") or p.get("sku") or ""

    def _observed_count(p: dict) -> int:
        key = _product_key(p)
        if key in extracted_by_key:
            return extracted_by_key[key]
        sku = p.get("sku")
        if sku in extracted_by_key:
            return extracted_by_key[sku]
        return _safe_int(p, "ingested_count")

    def _target_count(p: dict) -> int:
        key = _product_key(p)
        if key in summary_text_total_by_key:
            return summary_text_total_by_key[key]
        sku = p.get("sku")
        if sku in summary_text_total_by_key:
            return summary_text_total_by_key[sku]
        return _text_review_count(p)

    site_total = sum(_target_count(p) for p in products)
    ingested_total = sum(_observed_count(p) for p in products)
    ratings_only_total = sum(_safe_int(p, "ratings_only_count") for p in products)

    # zero_scrape：只有"应该有文字评论"的产品才报。
    # 旧逻辑用 review_count > 0；现改用 text_review_count > 0，
    # 当 BV 给出 review_count=92 但 92 条全是 ratings-only 时不会再误报零采集。
    zero_scrape_skus = [
        p["sku"] for p in products
        if (_target_count(p) > 0)
        and (_observed_count(p) == 0)
    ]

    low_coverage_skus = []
    for p in products:
        text_total = _target_count(p)
        observed = _observed_count(p)
        if text_total > 0 and (observed / text_total) < low_coverage_threshold:
            low_coverage_skus.append(p["sku"])

    completeness = (ingested_total / site_total) if site_total else 1.0
    if not expected_urls:
        expected_urls = [p.get("url") for p in products if p.get("url")]
    if not saved_urls:
        saved_urls = [p.get("url") for p in products if p.get("url")]

    failed_url_set = {item.get("url") for item in failed_urls if item.get("url")}
    saved_url_set = {url for url in saved_urls if url}
    missing_urls = [
        url for url in expected_urls
        if url and url not in saved_url_set and url not in failed_url_set
    ]

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
        # 透明化 ratings-only 修正量，便于运维理解为何 review_count 大于 ingested 仍可能是 100% 覆盖
        "ratings_only_total": ratings_only_total,
        "expected_url_count": len([url for url in expected_urls if url]),
        "saved_product_count": len([url for url in saved_urls if url]) or total,
        "failed_url_count": len(failed_urls),
        "failed_urls": failed_urls,
        "missing_url_count": len(missing_urls),
        "missing_urls": missing_urls,
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
