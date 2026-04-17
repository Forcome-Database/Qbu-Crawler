"""Data-construction operations that mutate simulation.db or derive mutations."""
import json
from datetime import date, datetime, timedelta


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


def expand_labels_rows(review_analysis_rows: list[dict]) -> list[dict]:
    """Flatten review_analysis.labels JSON into review_issue_labels rows."""
    out = []
    for ra in review_analysis_rows:
        labels_raw = ra.get("labels")
        if not labels_raw:
            continue
        try:
            labels = json.loads(labels_raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(labels, list):
            continue
        for lbl in labels:
            if not isinstance(lbl, dict) or "code" not in lbl:
                continue
            out.append({
                "review_id": ra["review_id"],
                "label_code": lbl.get("code"),
                "label_polarity": lbl.get("polarity", "neutral"),
                "severity": lbl.get("severity", "low"),
                "confidence": float(lbl.get("confidence", 0.5) or 0.5),
                "source": "seed_from_review_analysis",
                "taxonomy_version": "v1",
            })
    return out


def seed_issue_labels(conn) -> int:
    """Populate review_issue_labels from review_analysis.labels JSON."""
    rows = [dict(r) for r in conn.execute(
        "SELECT review_id, labels FROM review_analysis"
    ).fetchall()]
    to_insert = expand_labels_rows(rows)
    # Clear existing to be idempotent
    conn.execute("DELETE FROM review_issue_labels")
    now = "2026-03-20T09:00:00"
    conn.executemany(
        """INSERT INTO review_issue_labels
           (review_id, label_code, label_polarity, severity, confidence,
            source, taxonomy_version, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r["review_id"], r["label_code"], r["label_polarity"],
                r["severity"], r["confidence"], r["source"],
                r["taxonomy_version"], now, now,
            )
            for r in to_insert
        ],
    )
    return len(to_insert)
