"""D3: safety_incidents must not double-count same (review_id, level, mode).

Note: evidence_hash UNIQUE index already exists (models.py:232). The new
composite index coexists — they enforce two different dedup dimensions:
  - evidence_hash: exact payload identity
  - (review_id, safety_level, failure_mode): logical identity per review
"""
import sqlite3
import pytest


def _open_db_with_schema(tmp_path, monkeypatch):
    """Stand up a fresh DB using the project's init helper."""
    from qbu_crawler import models
    db_file = str(tmp_path / "products.db")
    monkeypatch.setattr(models, "DB_PATH", db_file, raising=False)
    models.init_db()
    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO products (id, url, name) VALUES (1, 'u', 'n')")
    conn.execute("INSERT INTO reviews (id, product_id, body) VALUES (1, 1, 'x')")
    conn.commit()
    conn.close()
    return db_file


def test_safety_incidents_dedup_by_review_level_mode(tmp_path, monkeypatch):
    db_file = _open_db_with_schema(tmp_path, monkeypatch)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """INSERT INTO safety_incidents
               (review_id, product_sku, safety_level, failure_mode,
                evidence_snapshot, evidence_hash, detected_at)
               VALUES (1, 'SKU-X', 'critical', 'foreign_object',
                       's1', 'h1', '2026-04-18')"""
        )
        conn.commit()
        # Second insert: same (review_id, level, mode) but DIFFERENT evidence_hash —
        # composite index must block it.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO safety_incidents
                   (review_id, product_sku, safety_level, failure_mode,
                    evidence_snapshot, evidence_hash, detected_at)
                   VALUES (1, 'SKU-X', 'critical', 'foreign_object',
                           's2', 'h2', '2026-04-18')"""
            )
            conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM safety_incidents WHERE review_id=1"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()
