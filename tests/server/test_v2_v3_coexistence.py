"""F011 §6.4 / AC-23 — v2/v3 ``prompt_version`` coexistence in ``review_analysis``.

The ``review_analysis`` table has a UNIQUE(review_id, prompt_version) constraint,
which lets two rows (one ``prompt_version='v2'``, one ``prompt_version='v3'``)
exist for the same review. The current MAX(analyzed_at) join in
``models.get_reviews_with_analysis`` and ``report.query_report_data`` picks the
latest analyzed row regardless of version.

These tests prove:

1. A DB containing only v2 rows still loads through the report query/analytics
   path without crashing (v3-only output fields default gracefully — they live
   on the LLM JSON copy, not on the analysis row).
2. A DB containing only v3 rows loads identically.
3. A DB with mixed v2 + v3 rows for the same review loads without crashing,
   and the analytics layer does not raise.

There are no v3-only DB columns: v3-specific fields like ``short_title`` /
``evidence_review_ids`` live in the LLM-generated ``improvement_priorities``
JSON shape (or its rule-based fallback), not in ``review_analysis``. So the
risk surface is limited to the SELECT join semantics + the analytics builder
tolerating either version label uniformly.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from qbu_crawler import config, models
from qbu_crawler.server import report
from qbu_crawler.server.report_analytics import build_dual_report_analytics


# ── Fixture helpers ──────────────────────────────────────────────────────────


def _get_test_conn(db_file: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_db(
    db_file: str,
    *,
    v2_count: int,
    v3_count: int,
    overlap_count: int = 0,
) -> int:
    """Seed a DB with ``v2_count`` v2-only reviews + ``v3_count`` v3-only reviews
    + ``overlap_count`` reviews that have both v2 and v3 analysis rows.

    Returns the workflow_run id.
    """
    conn = _get_test_conn(db_file)
    # One own product is enough.
    conn.execute(
        "INSERT INTO products (url, site, name, sku, price, stock_status, "
        "review_count, rating, ownership, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "http://own/coexist",
            "waltons",
            "Walton Coexistence Test Grinder",
            "OWN-COEX",
            199.99,
            "in_stock",
            v2_count + v3_count + overlap_count,
            4.0,
            "own",
            "2026-04-27 09:00:00",
        ),
    )
    product_id = conn.execute(
        "SELECT id FROM products WHERE sku=?", ("OWN-COEX",)
    ).fetchone()["id"]

    def _make_review(idx: int, label: str) -> int:
        cur = conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, "
            "rating, date_published, images, scraped_at, "
            "headline_cn, body_cn, translate_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product_id,
                f"Reviewer{idx}",
                f"Headline {idx} ({label})",
                f"Body text {idx} ({label}).",
                f"hash{idx}{label}",
                3.0 if label.startswith("v2") else 4.0,
                "2026-04-15",
                json.dumps([]),
                "2026-04-27 09:30:00",
                f"标题 {idx}",
                f"正文 {idx}",
                "done",
            ),
        )
        return cur.lastrowid

    def _add_analysis(review_id: int, prompt_version: str, analyzed_at: str) -> None:
        conn.execute(
            "INSERT INTO review_analysis "
            "(review_id, sentiment, sentiment_score, labels, features, insight_cn, insight_en, "
            " impact_category, failure_mode, prompt_version, llm_model, analyzed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                review_id,
                "negative",
                0.2,
                '[{"code":"quality_stability","polarity":"negative","severity":"medium","confidence":0.85}]',
                '["手柄松动"]',
                "手柄松动需要排查",
                "Handle is loose; needs inspection.",
                "durability",
                "loose_assembly",
                prompt_version,
                "gpt-4o-mini",
                analyzed_at,
            ),
        )

    idx = 0
    for _ in range(v2_count):
        idx += 1
        rid = _make_review(idx, "v2")
        _add_analysis(rid, "v2", "2026-04-27 10:00:00")
    for _ in range(v3_count):
        idx += 1
        rid = _make_review(idx, "v3")
        _add_analysis(rid, "v3", "2026-04-27 10:05:00")
    for _ in range(overlap_count):
        idx += 1
        rid = _make_review(idx, "overlap")
        # v2 row first, then a (slightly later) v3 row — same review_id.
        _add_analysis(rid, "v2", "2026-04-27 10:00:00")
        _add_analysis(rid, "v3", "2026-04-27 10:10:00")

    conn.commit()
    conn.close()

    run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "reporting",
            "logical_date": "2026-04-27",
            "trigger_key": (
                f"daily:2026-04-27:coex-{v2_count}-{v3_count}-{overlap_count}"
            ),
            "data_since": "2026-04-27T00:00:00+08:00",
            "data_until": "2026-04-28T00:00:00+08:00",
            "requested_by": "coexistence-test",
            "service_version": "test",
        }
    )
    return run["id"]


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Empty DB with F011 schema applied. Tests seed it themselves."""
    db_file = str(tmp_path / "products.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file, raising=False)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    # Disable LLM so insights use the deterministic fallback path.
    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    Path(config.REPORT_DIR).mkdir(parents=True, exist_ok=True)

    models.init_db()
    return {"db_file": db_file, "tmp_path": tmp_path}


def _build_synthetic_snapshot(run_id: int) -> dict:
    """Mimic ``freeze_report_snapshot`` minus the file/DB write — gives us a
    snapshot dict suitable for ``build_dual_report_analytics``."""
    products, reviews = report.query_report_data(
        "2026-04-27T00:00:00+08:00",
        until="2026-04-28T00:00:00+08:00",
    )
    cum_products, cum_reviews = report.query_cumulative_data()
    return {
        "run_id": run_id,
        "logical_date": "2026-04-27",
        "data_since": "2026-04-27T00:00:00+08:00",
        "data_until": "2026-04-28T00:00:00+08:00",
        "snapshot_at": "2026-04-27T12:00:00+08:00",
        "snapshot_hash": "test-hash-coexistence",
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": sum(
            1 for r in reviews if r.get("translate_status") == "done"
        ),
        "untranslated_count": sum(
            1 for r in reviews if r.get("translate_status") != "done"
        ),
        "cumulative": {
            "products": cum_products,
            "reviews": cum_reviews,
            "products_count": len(cum_products),
            "reviews_count": len(cum_reviews),
            "translated_count": sum(
                1 for r in cum_reviews if r.get("translate_status") == "done"
            ),
            "untranslated_count": sum(
                1 for r in cum_reviews if r.get("translate_status") != "done"
            ),
        },
    }


# ── Tests ────────────────────────────────────────────────────────────────────


def test_v2_only_db_query_and_analytics(isolated_db):
    """Pure v2 DB: the report query layer + analytics builder do not crash and
    return the expected number of reviews. No v3-specific assumptions leak."""
    run_id = _seed_db(isolated_db["db_file"], v2_count=4, v3_count=0)

    # Query layer must surface all 4 reviews with v2 analysis fields populated.
    _, reviews = report.query_report_data(
        "2026-04-27T00:00:00+08:00", until="2026-04-28T00:00:00+08:00"
    )
    assert len(reviews) == 4
    for r in reviews:
        assert r["sentiment"] == "negative"
        # impact_category was added in migration 0010 — independent of prompt
        # version, so v2 rows still populate it.
        assert r["impact_category"] == "durability"

    # Analytics must build without raising.
    snapshot = _build_synthetic_snapshot(run_id)
    analytics = build_dual_report_analytics(snapshot)
    assert analytics is not None
    assert "kpis" in analytics


def test_v3_only_db_query_and_analytics(isolated_db):
    """Pure v3 DB: same coverage as v2 — the loader is version-agnostic."""
    run_id = _seed_db(isolated_db["db_file"], v2_count=0, v3_count=4)

    _, reviews = report.query_report_data(
        "2026-04-27T00:00:00+08:00", until="2026-04-28T00:00:00+08:00"
    )
    assert len(reviews) == 4
    for r in reviews:
        assert r["sentiment"] == "negative"
        assert r["impact_category"] == "durability"

    snapshot = _build_synthetic_snapshot(run_id)
    analytics = build_dual_report_analytics(snapshot)
    assert analytics is not None
    assert "kpis" in analytics


def test_mixed_v2_v3_review_analysis_does_not_crash(isolated_db):
    """DB containing both v2 and v3 rows — including reviews with one of each
    version on the same review_id — must not crash any path:

    * ``models.get_reviews_with_analysis`` (used during snapshot enrichment)
    * ``report.query_report_data`` (window query)
    * ``report.query_cumulative_data`` (cumulative query)
    * ``build_dual_report_analytics`` (analytics builder)

    The MAX(analyzed_at) join picks the latest row per review_id; for the
    overlap reviews the v3 row wins (it was inserted with a later timestamp).
    """
    run_id = _seed_db(
        isolated_db["db_file"], v2_count=2, v3_count=2, overlap_count=2
    )

    # 6 distinct reviews total: 2 v2-only + 2 v3-only + 2 overlap.
    _, reviews = report.query_report_data(
        "2026-04-27T00:00:00+08:00", until="2026-04-28T00:00:00+08:00"
    )
    review_ids = [r["id"] for r in reviews]
    # No duplicates: the MAX(analyzed_at) subquery must collapse overlap reviews
    # to a single row each. (If it ever stops doing that we want to know.)
    assert len(review_ids) == len(set(review_ids)), (
        f"Duplicate review ids leaked from the analysis join: {review_ids}"
    )
    assert len(reviews) == 6

    # Cumulative query path also tolerates mixed versions.
    _, cum_reviews = report.query_cumulative_data()
    cum_ids = [r["id"] for r in cum_reviews]
    assert len(cum_ids) == len(set(cum_ids))
    assert len(cum_reviews) == 6

    # Bulk loader used by snapshot enrichment.
    enriched = models.get_reviews_with_analysis(review_ids=review_ids)
    enriched_ids = [r["id"] for r in enriched]
    assert len(enriched_ids) == len(set(enriched_ids)), (
        f"get_reviews_with_analysis returned duplicates: {enriched_ids}"
    )

    # Analytics builder must not raise.
    snapshot = _build_synthetic_snapshot(run_id)
    analytics = build_dual_report_analytics(snapshot)
    assert analytics is not None
    assert "kpis" in analytics


def test_mixed_versions_unique_constraint_holds(isolated_db):
    """Sanity: UNIQUE(review_id, prompt_version) lets two rows coexist for the
    same review when versions differ, and rejects a duplicate (review_id, version)."""
    _seed_db(isolated_db["db_file"], v2_count=0, v3_count=0, overlap_count=1)

    conn = _get_test_conn(isolated_db["db_file"])
    try:
        # The overlap row already has both v2 and v3 analyses.
        rows = conn.execute(
            "SELECT prompt_version FROM review_analysis ORDER BY prompt_version"
        ).fetchall()
        versions = [r["prompt_version"] for r in rows]
        assert versions == ["v2", "v3"]

        # Inserting a second v3 for the same review must violate the UNIQUE
        # constraint — proving the DB-level guard is intact.
        review_id = conn.execute(
            "SELECT review_id FROM review_analysis LIMIT 1"
        ).fetchone()["review_id"]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_analysis "
                "(review_id, sentiment, sentiment_score, labels, features, "
                " insight_cn, insight_en, impact_category, failure_mode, "
                " prompt_version, llm_model, analyzed_at) "
                "VALUES (?, 'negative', 0.2, '[]', '[]', 'x', 'x', NULL, NULL, "
                " 'v3', 'gpt-4o-mini', '2026-04-27 11:00:00')",
                (review_id,),
            )
            conn.commit()
    finally:
        conn.close()
