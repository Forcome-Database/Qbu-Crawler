"""P008 Phase 4: Category-level benchmark for the monthly report.

Groups products by category (per ``data/category_map.csv``) and produces an
own-vs-competitor comparison table per category. When a category has fewer
than 3 SKUs on either side, it's marked ``insufficient_samples``. When the
category map is empty/unavailable, the analysis degrades to direct competitor
pairings (closest-priced competitor per own SKU).
"""

from __future__ import annotations

from statistics import mean


_MIN_SKU_PER_OWNERSHIP = 3


def _avg(values: list[float]) -> float | None:
    cleaned = [v for v in values if v is not None]
    return round(mean(cleaned), 2) if cleaned else None


def _bucket_price(price: float | None, override: str = "") -> str:
    if override:
        return override
    if price is None:
        return "unknown"
    if price < 200:
        return "budget"
    if price < 600:
        return "mid"
    return "premium"


def _summarize(products: list[dict]) -> dict:
    if not products:
        return {"sku_count": 0, "avg_rating": None,
                "total_reviews": 0, "avg_price": None,
                "rating_p25": None, "rating_p75": None}
    ratings = sorted([p.get("rating") for p in products if p.get("rating") is not None])
    reviews_total = sum((p.get("review_count") or 0) for p in products)
    return {
        "sku_count": len(products),
        "avg_rating": _avg(ratings),
        "total_reviews": reviews_total,
        "avg_price": _avg([p.get("price") for p in products]),
        "rating_p25": ratings[int(len(ratings) * 0.25)] if ratings else None,
        "rating_p75": ratings[int(len(ratings) * 0.75)] if ratings else None,
    }


def derive_category_benchmark(
    products: list[dict],
    category_map: dict[str, dict],
) -> dict:
    """Build per-category own-vs-competitor benchmark.

    Args:
        products: list of product dicts with sku, ownership, rating, review_count, price.
        category_map: ``{sku: {"category": str, "sub_category": str, "price_band_override": str}}``.

    Returns dict with:
        - categories: ``{cat_name: {status, own, competitor, gap}}``
        - unmapped_count: number of SKUs not in the map
        - fallback_mode: True if category_map is empty (uses direct pairing)
        - pairings: list of own-vs-competitor pairs (only when fallback_mode True)
    """
    if not category_map:
        return _fallback_pairing(products)

    grouped: dict[str, dict[str, list[dict]]] = {}
    unmapped = 0
    for p in products:
        sku = p.get("sku", "")
        meta = category_map.get(sku)
        if not meta or not meta.get("category"):
            unmapped += 1
            continue
        cat = meta["category"]
        ownership = p.get("ownership") or "unknown"
        grouped.setdefault(cat, {"own": [], "competitor": []}).setdefault(ownership, []).append(p)

    categories: dict[str, dict] = {}
    for cat, buckets in grouped.items():
        own_products = buckets.get("own", [])
        comp_products = buckets.get("competitor", [])
        if (len(own_products) < _MIN_SKU_PER_OWNERSHIP
                or len(comp_products) < _MIN_SKU_PER_OWNERSHIP):
            categories[cat] = {
                "status": "insufficient_samples",
                "own_sku_count": len(own_products),
                "competitor_sku_count": len(comp_products),
                "min_required": _MIN_SKU_PER_OWNERSHIP,
            }
            continue

        own = _summarize(own_products)
        comp = _summarize(comp_products)
        gap = None
        if own["avg_rating"] is not None and comp["avg_rating"] is not None:
            gap = round(own["avg_rating"] - comp["avg_rating"], 2)
        categories[cat] = {
            "status": "ok",
            "own": own,
            "competitor": comp,
            "rating_gap": gap,
        }

    return {
        "categories": categories,
        "unmapped_count": unmapped,
        "fallback_mode": False,
        "pairings": [],
    }


def _fallback_pairing(products: list[dict]) -> dict:
    """When no category map: pair each own product with closest-priced competitor."""
    own = [p for p in products if p.get("ownership") == "own"]
    comp = [p for p in products if p.get("ownership") == "competitor"]
    pairings = []
    for o in own:
        if o.get("price") is None or not comp:
            continue
        nearest = min(
            (c for c in comp if c.get("price") is not None),
            key=lambda c: abs(c["price"] - o["price"]),
            default=None,
        )
        if nearest is None:
            continue
        gap = None
        if o.get("rating") is not None and nearest.get("rating") is not None:
            gap = round(o["rating"] - nearest["rating"], 2)
        pairings.append({
            "own_sku": o.get("sku"),
            "own_name": o.get("name"),
            "own_rating": o.get("rating"),
            "competitor_sku": nearest.get("sku"),
            "competitor_name": nearest.get("name"),
            "competitor_rating": nearest.get("rating"),
            "rating_gap": gap,
            "price_diff": round(nearest["price"] - o["price"], 2) if o.get("price") and nearest.get("price") else None,
        })
    return {
        "categories": {},
        "unmapped_count": len(own) + len(comp),
        "fallback_mode": True,
        "pairings": pairings,
    }
