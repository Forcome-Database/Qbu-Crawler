"""Tests for review_analysis table DDL and CRUD functions."""

import json
import sqlite3

import pytest

from qbu_crawler import config, models


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Create a temp SQLite DB, patch DB_PATH + get_conn, initialise schema.

    Returns a (conn_fn, product_id, review_id) tuple so callers can insert
    more rows or query the DB directly.
    """
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)

    def _conn():
        c = sqlite3.connect(db_file)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(models, "get_conn", _conn)
    models.init_db()

    # Insert a product and a review for use by tests
    conn = _conn()
    conn.execute(
        "INSERT INTO products (url, site, name, sku, price, ownership) "
        "VALUES ('https://example.com/p/1', 'basspro', 'Test Product', 'SKU001', 19.99, 'own')"
    )
    conn.commit()
    product_id = conn.execute("SELECT id FROM products").fetchone()["id"]

    conn.execute(
        """INSERT INTO reviews
               (product_id, author, headline, body, body_hash, rating,
                translate_status, headline_cn, body_cn)
           VALUES (?, 'Alice', 'Great item', 'Really liked it', 'hash001', 4.5,
                   'done', '好产品', '真的很喜欢')""",
        (product_id,),
    )
    conn.commit()
    review_id = conn.execute("SELECT id FROM reviews").fetchone()["id"]
    conn.close()

    return _conn, product_id, review_id


# ---------------------------------------------------------------------------
# Part 1 — schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_review_analysis_table_exists(self, test_db):
        conn_fn, _, _ = test_db
        conn = conn_fn()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "review_analysis" in tables

    def test_review_analysis_indexes_exist(self, test_db):
        conn_fn, _, _ = test_db
        conn = conn_fn()
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        conn.close()
        assert "idx_ra_review" in indexes
        assert "idx_ra_sentiment" in indexes

    def test_review_analysis_columns(self, test_db):
        conn_fn, _, _ = test_db
        conn = conn_fn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(review_analysis)"
        ).fetchall()}
        conn.close()
        expected = {
            "id", "review_id", "sentiment", "sentiment_score",
            "labels", "features", "insight_cn", "insight_en",
            "llm_model", "prompt_version", "token_usage", "analyzed_at",
            "failure_mode_raw",
        }
        assert expected <= cols


# ---------------------------------------------------------------------------
# Part 2 — CRUD
# ---------------------------------------------------------------------------

class TestSaveReviewAnalysis:
    def test_save_review_analysis(self, test_db):
        """Save an analysis row and verify all persisted fields."""
        conn_fn, _, review_id = test_db

        models.save_review_analysis(
            review_id=review_id,
            sentiment="positive",
            sentiment_score=0.92,
            labels=["quality", "value"],
            features=["durability"],
            insight_cn="质量很好",
            insight_en="Great quality",
            llm_model="gpt-4o-mini",
            prompt_version="v1",
            token_usage=123,
        )

        result = models.get_review_analysis(review_id)
        assert result is not None
        assert result["review_id"] == review_id
        assert result["sentiment"] == "positive"
        assert result["sentiment_score"] == pytest.approx(0.92)
        assert result["prompt_version"] == "v1"
        assert result["llm_model"] == "gpt-4o-mini"
        assert result["token_usage"] == 123
        assert result["insight_cn"] == "质量很好"
        assert result["insight_en"] == "Great quality"
        # labels and features are stored as JSON strings
        assert json.loads(result["labels"]) == ["quality", "value"]
        assert json.loads(result["features"]) == ["durability"]

    def test_save_review_analysis_defaults(self, test_db):
        """Save with minimal args; labels/features default to '[]'."""
        _, _, review_id = test_db

        models.save_review_analysis(review_id=review_id, sentiment="neutral")

        result = models.get_review_analysis(review_id)
        assert result is not None
        assert result["sentiment"] == "neutral"
        assert result["sentiment_score"] is None
        assert json.loads(result["labels"]) == []
        assert json.loads(result["features"]) == []

    def test_save_review_analysis_upsert(self, test_db):
        """Same (review_id, prompt_version) updates in place; no duplicate rows."""
        conn_fn, _, review_id = test_db

        models.save_review_analysis(
            review_id=review_id,
            sentiment="positive",
            insight_en="First pass",
            prompt_version="v1",
        )
        models.save_review_analysis(
            review_id=review_id,
            sentiment="negative",
            insight_en="Second pass",
            prompt_version="v1",
        )

        conn = conn_fn()
        count = conn.execute(
            "SELECT COUNT(*) FROM review_analysis WHERE review_id = ? AND prompt_version = 'v1'",
            (review_id,),
        ).fetchone()[0]
        conn.close()
        assert count == 1

        result = models.get_review_analysis(review_id)
        assert result["sentiment"] == "negative"
        assert result["insight_en"] == "Second pass"


class TestGetReviewAnalysisLatestVersion:
    def test_get_review_analysis_latest_version(self, test_db):
        """When both v1 and v2 exist, get_review_analysis returns the newer one."""
        _, _, review_id = test_db

        models.save_review_analysis(
            review_id=review_id,
            sentiment="positive",
            insight_en="v1 result",
            prompt_version="v1",
            analyzed_at="2026-01-01 00:00:00",
        )
        models.save_review_analysis(
            review_id=review_id,
            sentiment="negative",
            insight_en="v2 result",
            prompt_version="v2",
            analyzed_at="2026-01-02 00:00:00",
        )

        result = models.get_review_analysis(review_id)
        # Most recent analyzed_at wins
        assert result["prompt_version"] == "v2"
        assert result["insight_en"] == "v2 result"


class TestGetReviewsWithAnalysis:
    def test_get_reviews_with_analysis_no_filter(self, test_db):
        """Without filters, returns all reviews joined with product data."""
        _, _, review_id = test_db

        models.save_review_analysis(
            review_id=review_id,
            sentiment="positive",
            sentiment_score=0.8,
            labels=["comfort"],
            features=["fit"],
            insight_cn="舒适",
            insight_en="Comfortable",
            prompt_version="v1",
        )

        results = models.get_reviews_with_analysis()
        assert len(results) == 1

        r = results[0]
        # Review fields
        assert r["id"] == review_id
        assert r["headline"] == "Great item"
        assert r["rating"] == 4.5
        assert r["headline_cn"] == "好产品"
        # Product fields
        assert r["product_name"] == "Test Product"
        assert r["product_sku"] == "SKU001"
        assert r["site"] == "basspro"
        assert r["ownership"] == "own"
        assert r["price"] == pytest.approx(19.99)
        # Analysis fields
        assert r["sentiment"] == "positive"
        assert r["analysis_labels"] == '["comfort"]'
        assert r["analysis_insight_cn"] == "舒适"
        assert r["analysis_insight_en"] == "Comfortable"

    def test_get_reviews_with_analysis_by_review_ids(self, test_db):
        """Filter by explicit review_ids returns only matching rows."""
        _, _, review_id = test_db

        results = models.get_reviews_with_analysis(review_ids=[review_id])
        assert len(results) == 1
        assert results[0]["id"] == review_id

    def test_get_reviews_with_analysis_wrong_id(self, test_db):
        """review_ids filter with non-existent id returns empty list."""
        _ = test_db
        results = models.get_reviews_with_analysis(review_ids=[99999])
        assert results == []

    def test_get_reviews_with_analysis_no_analysis_row(self, test_db):
        """Reviews without an analysis row still appear (LEFT JOIN), analysis fields are None."""
        _, _, review_id = test_db

        results = models.get_reviews_with_analysis(review_ids=[review_id])
        assert len(results) == 1
        r = results[0]
        assert r["sentiment"] is None
        assert r["analysis_labels"] is None

    def test_get_reviews_with_analysis_since_filter(self, test_db):
        """since filter excludes reviews scraped before the cutoff."""
        _ = test_db
        results = models.get_reviews_with_analysis(since="2099-01-01")
        assert results == []


# ---------------------------------------------------------------------------
# Part 3 — get_pending_translations includes product fields
# ---------------------------------------------------------------------------

class TestGetPendingTranslationsIncludesProductName:
    def test_pending_translations_includes_product_name(self, test_db):
        """get_pending_translations() should return product_name, product_sku, rating."""
        conn_fn, product_id, _ = test_db

        # Insert a fresh review with NULL translate_status (pending)
        conn = conn_fn()
        conn.execute(
            """INSERT INTO reviews (product_id, author, headline, body, body_hash, rating,
                                    translate_status)
               VALUES (?, 'Bob', 'Pending review', 'Body text', 'hash_p1', 3.5, NULL)""",
            (product_id,),
        )
        conn.commit()
        conn.close()

        rows = models.get_pending_translations(limit=10)
        # Filter to our specific review
        pending = [r for r in rows if r["headline"] == "Pending review"]
        assert len(pending) == 1

        r = pending[0]
        assert r["product_name"] == "Test Product"
        assert r["product_sku"] == "SKU001"
        assert r["rating"] == 3.5

    def test_pending_translations_still_has_id_headline_body(self, test_db):
        """Existing callers' fields (id, headline, body) must still be present."""
        conn_fn, product_id, _ = test_db

        conn = conn_fn()
        conn.execute(
            """INSERT INTO reviews (product_id, author, headline, body, body_hash,
                                    translate_status)
               VALUES (?, 'Carol', 'Old field check', 'Body here', 'hash_p2', NULL)""",
            (product_id,),
        )
        conn.commit()
        conn.close()

        rows = models.get_pending_translations(limit=10)
        pending = [r for r in rows if r["headline"] == "Old field check"]
        assert len(pending) == 1

        r = pending[0]
        assert "id" in r
        assert "headline" in r
        assert "body" in r
