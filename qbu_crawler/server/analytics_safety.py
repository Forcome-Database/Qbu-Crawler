"""Safety incident grouping for monthly reports (D3 + D11)."""
from typing import Iterable


def group_safety_incidents(incidents: Iterable[dict]) -> list[dict]:
    """Group raw safety_incidents rows by review_id.

    For each unique review_id, emit one card with:
      - safety_level / failure_mode from first (earliest) row
      - review_count: how many raw rows belong to this review (if any drift)
      - first_seen: earliest created_at/detected_at across grouped rows
      - review_excerpt: body snippet if available
      - product_sku / product_name

    Sorted critical first, then by first_seen ascending.
    """
    by_review: dict = {}
    for inc in incidents or []:
        rid = inc.get("review_id")
        key = rid if rid is not None else f"noreview-{inc.get('id')}"
        group = by_review.setdefault(key, {
            "review_id": rid,
            "safety_level": inc.get("safety_level"),
            "failure_mode": inc.get("failure_mode"),
            "product_sku": inc.get("product_sku"),
            "product_name": inc.get("product_name"),
            "review_excerpt": inc.get("review_body") or inc.get("review_excerpt"),
            "first_seen": inc.get("created_at") or inc.get("detected_at") or inc.get("first_seen"),
            "review_count": 0,
        })
        group["review_count"] += 1
        new_ts = inc.get("created_at") or inc.get("detected_at")
        if new_ts and (not group["first_seen"] or new_ts < group["first_seen"]):
            group["first_seen"] = new_ts

    def _sort_key(g):
        level_rank = 0 if g.get("safety_level") == "critical" else 1
        return (level_rank, g.get("first_seen") or "")

    return sorted(by_review.values(), key=_sort_key)
