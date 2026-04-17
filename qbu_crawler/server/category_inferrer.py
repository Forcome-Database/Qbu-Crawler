"""LLM-based category inference for SKU → category_map.csv backfill.

One-shot CLI: read all SKUs from a SQLite db, infer categories via LLM,
write to data/category_map.csv. The infer_categories() function is also
designed to be called incrementally from a future workflow hook for new SKUs.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

from json_repair import repair_json
from openai import OpenAI

from qbu_crawler import config

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = [
    "grinder",      # meat grinders incl. "Kitchen Grinder #N" (#N = grinder size)
    "slicer",       # meat slicers, food slicers
    "mixer",        # meat mixers
    "stuffer",      # sausage stuffers
    "tenderizer",   # tenderizers + cubers (same mechanism)
    "saw",          # meat saws / band saws
    "patty_maker",  # patty / hamburger forming
    "accessory",    # attachments, spare motors, foot pedals, plates, knives
    "container",    # meat lugs / tubs
    "other",        # fallback when confidence is low
]

_CONFIDENCE_FLOOR = 0.7

_FEW_SHOTS = [
    {"name": "1 HP Dual Grind Grinder (#22)", "category": "grinder"},
    {"name": "Walton's #8 Kitchen Grinder", "category": "grinder",
     "note": "#8 is a meat grinder size; 'Kitchen' is brand wording, not coffee/spice"},
    {"name": "Pro Series Manual Meat Cuber", "category": "tenderizer",
     "note": "cubers and tenderizers share the same mechanism"},
    {"name": "16\" Meat Saw", "category": "saw"},
    {"name": "Walton's Quick Patty Maker", "category": "patty_maker"},
    {"name": "Walton's Premier Electric Motor", "category": "accessory",
     "note": "spare motor for a grinder, not a standalone product"},
    {"name": "Foot Pedal Switch", "category": "accessory"},
    {"name": "1HP Dual Grind #22 Throat Attachment", "category": "accessory"},
    {"name": "40 LB Meat Lug", "category": "container"},
    {"name": "Cabela's Heavy-Duty 20-lb. Meat Mixer", "category": "mixer"},
    {"name": "8.7\" Pro Series Food Slicer", "category": "slicer"},
    {"name": "Cabela's Commercial-Grade Sausage Stuffer", "category": "stuffer"},
]


class CategoryResult(TypedDict):
    sku: str
    category: str
    sub_category: str
    confidence: float


def _url_hint(url: str) -> str:
    """Last 3 path segments help the LLM (e.g. /process/grinders/...)."""
    if not url:
        return ""
    parts = [p for p in url.split("/") if p and "." not in p[-6:]]
    return "/".join(parts[-3:])


def _build_messages(products: list[dict]) -> list[dict]:
    system = (
        "You classify meat-processing equipment SKUs into ONE of these categories ONLY: "
        + ", ".join(ALLOWED_CATEGORIES) + ".\n\n"
        "Rules:\n"
        "- '#N Kitchen Grinder' or '#N Meat Grinder' → grinder (#N = grinder size)\n"
        "- Cubers and tenderizers → tenderizer (same mechanism)\n"
        "- Spare motors, pedals, attachments, plates, knives → accessory\n"
        "- Meat lugs / tubs → container\n"
        "- Use 'other' if confidence < 0.7. NEVER invent new categories.\n\n"
        'Output strict JSON only: {"results":[{"sku":"...","category":"...",'
        '"sub_category":"","confidence":0.0}]}'
    )
    examples = "Examples:\n" + "\n".join(
        f"- '{ex['name']}' → {ex['category']}"
        + (f"  ({ex['note']})" if ex.get("note") else "")
        for ex in _FEW_SHOTS
    )
    payload = json.dumps(
        [{"sku": p["sku"], "name": p["name"], "url_hint": _url_hint(p.get("url", ""))}
         for p in products],
        ensure_ascii=False, indent=2,
    )
    user = (
        f"{examples}\n\nClassify these products. sub_category is optional "
        "(e.g., 'dual_grind','commercial','#22'); leave empty if unsure.\n\n"
        f"{payload}\n\nReturn JSON only."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


_BATCH_SIZE = 12  # keep output JSON well under typical max_tokens limits


def _infer_one_batch(products: list[dict], client: OpenAI) -> dict[str, dict]:
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=_build_messages(products),
        temperature=0.0,
        max_tokens=4096,
    )
    finish = resp.choices[0].finish_reason
    raw = (resp.choices[0].message.content or "").strip()
    if finish == "length":
        logger.warning("LLM response truncated (finish_reason=length) for batch of %d", len(products))
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(repair_json(raw))
    items = data.get("results", []) if isinstance(data, dict) else []
    return {str(it.get("sku")): it for it in items if isinstance(it, dict)}


def infer_categories(
    products: list[dict],
    client: OpenAI | None = None,
) -> list[CategoryResult]:
    """Classify products via LLM. Auto-batches to avoid token-limit truncation.

    products: dicts with sku, name, url (url optional).
    Returns one CategoryResult per input SKU. Unknown/low-confidence → 'other'.
    """
    if not products:
        return []
    client = client or OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_API_BASE or None,
    )
    by_sku: dict[str, dict] = {}
    for i in range(0, len(products), _BATCH_SIZE):
        batch = products[i:i + _BATCH_SIZE]
        logger.info("Inferring batch %d-%d (size=%d)", i, i + len(batch), len(batch))
        try:
            by_sku.update(_infer_one_batch(batch, client))
        except Exception:
            logger.exception(
                "Batch %d-%d LLM call failed; items will fall back to 'other'",
                i, i + len(batch),
            )
            # Deliberately continue — partial results are better than none.
            # Failed-batch SKUs are absent from by_sku; the validation loop
            # below maps them to 'other' via the ALLOWED_CATEGORIES check.

    out: list[CategoryResult] = []
    for p in products:
        sku = str(p["sku"])
        item = by_sku.get(sku, {})
        cat = (item.get("category") or "").strip().lower()
        confidence = float(item.get("confidence") or 0.0)
        if cat not in ALLOWED_CATEGORIES:
            logger.warning("unknown category %r for sku=%s -> 'other'", cat, sku)
            cat = "other"
        if confidence < _CONFIDENCE_FLOOR:
            cat = "other"
        out.append({
            "sku": sku,
            "category": cat,
            "sub_category": (item.get("sub_category") or "").strip(),
            "confidence": confidence,
        })
    return out


def _read_existing_skus(csv_path: str) -> set[str]:
    """Return the set of SKUs already mapped in the csv (empty if file missing)."""
    if not Path(csv_path).exists():
        return set()
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {(row.get("sku") or "").strip() for row in reader if row.get("sku")}


class CategoryMapLocked(RuntimeError):
    """Raised when the CSV lock cannot be acquired within timeout."""


def _acquire_lock(csv_path: str, timeout: float) -> Path:
    """Cross-platform exclusive lock using O_CREAT|O_EXCL sentinel file."""
    import time as _time
    lock_path = Path(csv_path + ".lock")
    deadline = _time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock_path
        except FileExistsError:
            if _time.monotonic() >= deadline:
                raise CategoryMapLocked(
                    f"Could not acquire {lock_path} within {timeout}s"
                )
            _time.sleep(0.05)


def _append_csv(
    results: list[CategoryResult],
    csv_path: str,
    lock_timeout: float = 5.0,
) -> None:
    """Append rows to csv under exclusive lock. Preserves existing manual edits."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _acquire_lock(csv_path, lock_timeout)
    try:
        file_exists = path.exists()
        with open(path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["sku", "category", "sub_category", "price_band_override"])
            for r in results:
                writer.writerow([r["sku"], r["category"], r["sub_category"], ""])
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def sync_new_skus(db_path: str | None = None, csv_path: str | None = None) -> int:
    """Diff db SKUs vs csv SKUs, infer missing ones via LLM, append to csv.

    Called after each daily run completes. All errors are swallowed and logged —
    LLM/network hiccups must never block the workflow. Returns the number of
    SKUs newly mapped (0 if none new or on error).
    """
    db_path = db_path or config.DB_PATH
    csv_path = csv_path or config.CATEGORY_MAP_PATH
    try:
        if not config.LLM_API_KEY:
            logger.debug("sync_new_skus: LLM_API_KEY not set, skipping")
            return 0
        existing = _read_existing_skus(csv_path)
        all_products = _load_skus_from_db(db_path)
        new_products = [p for p in all_products if str(p["sku"]) not in existing]
        if not new_products:
            return 0
        logger.info("sync_new_skus: %d new SKU(s) to map", len(new_products))
        results = infer_categories(new_products)
        _append_csv(results, csv_path)
        logger.info(
            "sync_new_skus: appended %d row(s) to %s",
            len(results), csv_path,
        )
        return len(results)
    except Exception:
        logger.exception("sync_new_skus: failed silently (will retry next run)")
        return 0


def _load_skus_from_db(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT sku, name, url, ownership FROM products ORDER BY ownership, site, sku"
        ).fetchall()
    finally:
        conn.close()
    return [{"sku": s, "name": n, "url": u, "ownership": o}
            for s, n, u, o in rows]


def _write_csv(results: list[CategoryResult], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "category", "sub_category", "price_band_override"])
        for r in results:
            writer.writerow([r["sku"], r["category"], r["sub_category"], ""])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="Backfill data/category_map.csv via LLM inference",
    )
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--output", default=config.CATEGORY_MAP_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="print results without writing csv")
    args = ap.parse_args()

    if not config.LLM_API_KEY:
        print("ERROR: LLM_API_KEY not configured", file=sys.stderr)
        return 1

    products = _load_skus_from_db(args.db)
    print(f"Loaded {len(products)} SKUs from {args.db}")
    if not products:
        return 0

    results = infer_categories(products)
    name_by_sku = {p["sku"]: p["name"] for p in products}
    own_by_sku = {p["sku"]: (p["ownership"] or "?") for p in products}
    print(f"\n{'SKU':<12} | {'Own':<10} | {'Category':<12} | {'Sub':<14} | {'Conf':>5} | Name")
    print("-" * 120)
    for r in results:
        print(f"{r['sku']:<12} | {own_by_sku.get(r['sku'], '?'):<10} | "
              f"{r['category']:<12} | {r['sub_category'][:13]:<14} | "
              f"{r['confidence']:5.2f} | {name_by_sku.get(r['sku'], '')[:55]}")

    # category distribution summary
    from collections import Counter
    dist = Counter(r["category"] for r in results)
    print("\nDistribution:", dict(dist))

    if args.dry_run:
        print("\n--dry-run: not writing csv")
        return 0
    _write_csv(results, args.output)
    print(f"\nWrote {len(results)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
