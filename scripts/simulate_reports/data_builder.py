"""Data-construction operations that mutate simulation.db or derive mutations."""
import hashlib
import json
from datetime import date, datetime, timedelta
from datetime import date as date_cls

from .body_pool import BodyPool


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


def _synthetic_hash(base_hash: str, salt: str) -> str:
    return hashlib.md5((base_hash + "|" + salt).encode()).hexdigest()[:16]


def inject_new_reviews(
    conn,
    *,
    pool: BodyPool,
    product_id: int,
    logical_date: date_cls,
    count: int,
    label_code: str,
    polarity: str,
    rating_range: tuple[float, float] = (1.0, 5.0),
    scraped_time_hhmm: str = "09:15",
) -> list[int]:
    """Clone reviews from pool and insert as new rows on `logical_date`.
    Returns inserted review IDs."""
    samples = pool.sample(label_code, polarity, count)
    if not samples:
        raise RuntimeError(
            f"BodyPool empty for ({label_code}, {polarity}); "
            "seed review_issue_labels first"
        )
    date_iso = logical_date.strftime("%Y-%m-%d")
    scraped_at = f"{date_iso}T{scraped_time_hhmm}:00"
    published = f"{date_iso}T08:00:00"

    inserted_ids = []
    for idx, s in enumerate(samples):
        salt = f"sim-{date_iso}-{product_id}-{idx}"
        body_hash = _synthetic_hash(s["body_hash"] or s["body"][:32], salt)
        # Choose rating from range based on polarity
        if polarity == "negative":
            rating = max(rating_range[0], min(2.0, s["rating"] or 2.0))
        else:
            rating = min(rating_range[1], max(4.0, s["rating"] or 4.0))
        cur = conn.execute(
            """INSERT INTO reviews
               (product_id, author, headline, body, body_hash, rating,
                date_published, date_published_parsed, scraped_at,
                translate_status, translate_retries, headline_cn, body_cn)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', 0, ?, ?)""",
            (
                product_id, f"SimUser{idx}", s["headline"], s["body"],
                body_hash, rating, date_iso, published, scraped_at,
                # reuse the pool's headline/body as "translation" for determinism
                (s["headline"] or "")[:200], (s["body"] or "")[:1000],
            ),
        )
        review_id = cur.lastrowid
        inserted_ids.append(review_id)
        # Mirror into review_analysis (minimal row)
        labels_json = (
            '[{"code":"' + label_code + '","polarity":"' + polarity +
            '","severity":"medium","confidence":0.8}]'
        )
        conn.execute(
            """INSERT INTO review_analysis
               (review_id, sentiment, sentiment_score, labels, insight_cn,
                prompt_version, analyzed_at, impact_category)
               VALUES (?, ?, ?, ?, ?, 'sim-v1', ?, ?)""",
            (
                review_id,
                "negative" if polarity == "negative" else "positive",
                -0.7 if polarity == "negative" else 0.7,
                labels_json, s["body"][:200], scraped_at,
                "experience",
            ),
        )
        # Mirror into review_issue_labels
        conn.execute(
            """INSERT INTO review_issue_labels
               (review_id, label_code, label_polarity, severity, confidence,
                source, taxonomy_version, created_at, updated_at)
               VALUES (?, ?, ?, 'medium', 0.8, 'sim', 'v1', ?, ?)""",
            (review_id, label_code, polarity, scraped_at, scraped_at),
        )
    return inserted_ids


def mutate_product(
    conn,
    *,
    product_id: int,
    logical_date: date_cls,
    price_delta_pct: float | None = None,
    stock_status: str | None = None,
    rating_delta: float | None = None,
) -> None:
    """Update products + append product_snapshots row on logical_date."""
    row = conn.execute(
        "SELECT price, stock_status, rating, review_count FROM products WHERE id=?",
        (product_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"product {product_id} not found")
    price, stock, rating, rc = row
    new_price = price * (1 + price_delta_pct) if price_delta_pct else price
    new_stock = stock_status or stock
    new_rating = (rating or 0) + (rating_delta or 0) if rating_delta else rating
    scraped_at = logical_date.strftime("%Y-%m-%dT09:15:00")
    conn.execute(
        """UPDATE products SET price=?, stock_status=?, rating=?, scraped_at=?
           WHERE id=?""",
        (new_price, new_stock, new_rating, scraped_at, product_id),
    )
    conn.execute(
        """INSERT INTO product_snapshots
           (product_id, price, stock_status, review_count, rating, scraped_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (product_id, new_price, new_stock, rc, new_rating, scraped_at),
    )


def inject_safety_incidents(
    conn,
    *,
    review_ids: list[int],
    safety_level: str = "critical",
    failure_mode: str = "foreign_object",
) -> None:
    for rid in review_ids:
        rsku = conn.execute(
            "SELECT p.sku FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.id=?",
            (rid,),
        ).fetchone()
        sku = rsku[0] if rsku else None
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            """INSERT INTO safety_incidents
               (review_id, product_sku, safety_level, failure_mode,
                evidence_snapshot, evidence_hash, detected_at, created_at)
               VALUES (?, ?, ?, ?, 'sim-evidence', 'sim-hash', ?, ?)""",
            (rid, sku, safety_level, failure_mode, ts, ts),
        )


def force_translation_stall(
    conn,
    *,
    logical_date: date_cls,
    pending_fraction: float = 0.3,
) -> int:
    """Mark `pending_fraction` of reviews scraped on this date as stalled."""
    date_prefix = logical_date.strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT id FROM reviews WHERE scraped_at LIKE ? || '%'",
        (date_prefix,),
    ).fetchall()
    if not rows:
        return 0
    n = max(1, int(len(rows) * pending_fraction))
    ids = [r[0] for r in rows[:n]]
    conn.execute(
        f"""UPDATE reviews SET translate_status='pending', translate_retries=3
            WHERE id IN ({','.join('?'*len(ids))})""",
        ids,
    )
    return len(ids)


def seed_historical_pattern(
    conn,
    *,
    pool: BodyPool,
    product_id: int,
    label_code: str,
    polarity: str,
    dates: list[date_cls],
    count_per_date: int = 1,
) -> list[int]:
    """Inject N reviews per date for a label, establishing history
    so that avg_interval and silence_window make sense for R3/R4 triggers."""
    all_ids = []
    for d in dates:
        ids = inject_new_reviews(
            conn, pool=pool, product_id=product_id,
            logical_date=d, count=count_per_date,
            label_code=label_code, polarity=polarity,
        )
        all_ids.extend(ids)
    return all_ids
