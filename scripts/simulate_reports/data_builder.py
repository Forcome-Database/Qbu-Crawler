"""Data-construction operations that mutate simulation.db or derive mutations."""
from datetime import date, datetime, timedelta
from typing import Iterable


# Fraction of reviews that land on the timeline start day (cold-start batch)
COLD_START_FRACTION = 0.15

# Remaining reviews spread across these relative offsets (days from timeline_start)
SPREAD_OFFSETS = (4, 8, 12, 18, 22, 26, 28)


def redistribute_scraped_at(
    reviews: list[dict],
    *,
    timeline_start: date,
) -> list[dict]:
    """Return a new list of reviews with scraped_at rewritten.

    Rules:
      - Earliest 15% (by date_published_parsed) → timeline_start 09:00
      - Remaining reviews sliced evenly across SPREAD_OFFSETS day-buckets
      - Always clamp: scraped_at >= date_published_parsed
    """
    sorted_reviews = sorted(
        reviews, key=lambda r: r.get("date_published_parsed") or ""
    )
    total = len(sorted_reviews)
    cold_n = max(1, int(total * COLD_START_FRACTION))

    out = []
    for i, r in enumerate(sorted_reviews):
        if i < cold_n:
            stamp = datetime.combine(timeline_start, datetime.min.time()).replace(hour=9)
        else:
            bucket_idx = (i - cold_n) % len(SPREAD_OFFSETS)
            offset = SPREAD_OFFSETS[bucket_idx]
            stamp = datetime.combine(
                timeline_start + timedelta(days=offset),
                datetime.min.time(),
            ).replace(hour=9, minute=15)
        # Enforce not-before-publish invariant
        pub_raw = r.get("date_published_parsed")
        if pub_raw:
            pub = datetime.fromisoformat(pub_raw.replace("Z", "+00:00").split("+")[0])
            if stamp < pub:
                stamp = pub
        new_r = dict(r)
        new_r["scraped_at"] = stamp.strftime("%Y-%m-%dT%H:%M:%S")
        out.append(new_r)
    return out
