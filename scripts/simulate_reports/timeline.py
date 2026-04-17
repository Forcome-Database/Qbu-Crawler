"""42-day timeline: date → list of scenario IDs scheduled that day.
Plus apply_events() that translates event specs into data_builder calls."""
import random
from datetime import date, timedelta
from .scenarios import SCENARIOS, Scenario
from . import config


# One day may have multiple scenarios (e.g. daily + weekly + monthly on 2026-05-01).
TIMELINE: dict[date, list[str]] = {}


def _build():
    for sid, sc in SCENARIOS.items():
        TIMELINE.setdefault(sc.logical_date, []).append(sid)
    # Fill "gap days" with S02-variant daily so the timeline is contiguous
    cur = config.TIMELINE_START
    while cur <= config.TIMELINE_END:
        if cur not in TIMELINE or not any(
            SCENARIOS[s].tier == "daily" for s in TIMELINE[cur]
        ):
            variant_sid = f"S02_{cur.isoformat()}"
            SCENARIOS[variant_sid] = Scenario(
                sid=variant_sid, logical_date=cur, phase="P*", tier="daily",
                description="常规 Full 模式 (gap filler)",
                events=[
                    {"op": "inject_new_reviews", "count": 5,
                     "polarity": "positive", "label": "quality_stability"},
                    {"op": "inject_new_reviews", "count": 2,
                     "polarity": "negative", "label": "shipping"},
                ],
                expected={"tier": "daily", "report_mode": "standard"},
            )
            TIMELINE.setdefault(cur, []).append(variant_sid)
        cur += timedelta(days=1)


_build()


def apply_events(conn, *, logical_date: date, events: list[dict]) -> list[dict]:
    """Translate event specs into data_builder calls.
    Returns the applied events for logging."""
    from .body_pool import BodyPool
    from . import data_builder as db
    pool = BodyPool(config.SIM_DB)
    rng = random.Random(42 + logical_date.toordinal())
    product_ids = [
        r[0] for r in conn.execute("SELECT id FROM products ORDER BY id").fetchall()
    ]
    applied = []
    for ev in events:
        op = ev["op"]
        if op == "inject_new_reviews":
            pid = rng.choice(product_ids)
            ids = db.inject_new_reviews(
                conn, pool=pool, product_id=pid, logical_date=logical_date,
                count=ev["count"], label_code=ev["label"],
                polarity=ev["polarity"],
            )
            applied.append({**ev, "_product_id": pid, "_review_ids": ids})
        elif op == "inject_safety_incidents_from_today":
            # Use reviews scraped today that already have negative polarity
            today = logical_date.strftime("%Y-%m-%d")
            rids = [r[0] for r in conn.execute(
                "SELECT id FROM reviews WHERE scraped_at LIKE ? || '%' "
                "AND rating <= 2", (today,),
            ).fetchall()]
            db.inject_safety_incidents(
                conn, review_ids=rids,
                safety_level=ev.get("level", "critical"),
                failure_mode=ev.get("failure_mode", "foreign_object"),
            )
            applied.append({**ev, "_review_ids": rids})
        elif op == "mutate_random_product":
            pid = rng.choice(product_ids)
            db.mutate_product(
                conn, product_id=pid, logical_date=logical_date,
                price_delta_pct=ev.get("price_delta_pct"),
                stock_status=ev.get("stock_status"),
                rating_delta=ev.get("rating_delta"),
            )
            applied.append({**ev, "_product_id": pid})
        elif op == "force_translation_stall":
            n = db.force_translation_stall(
                conn, logical_date=logical_date,
                pending_fraction=ev.get("pending_fraction", 0.3),
            )
            applied.append({**ev, "_marked": n})
        else:
            raise ValueError(f"Unknown event op: {op!r}")
    conn.commit()
    return applied
