"""Tests for Report V3 LLM enhancements (Phase 2)."""

import sqlite3
import pytest
from qbu_crawler import config, models


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


class TestReviewAnalysisSchema:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return db_file

    def test_impact_category_column_exists(self, db):
        conn = _get_test_conn(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(review_analysis)").fetchall()]
        assert "impact_category" in cols

    def test_failure_mode_column_exists(self, db):
        conn = _get_test_conn(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(review_analysis)").fetchall()]
        assert "failure_mode" in cols

    def test_save_with_new_fields(self, db):
        conn = _get_test_conn(db)
        conn.execute("INSERT INTO products (url, site, name, sku) VALUES ('http://t', 'test', 'T', 'T1')")
        pid = conn.execute("SELECT id FROM products WHERE sku='T1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating) "
            "VALUES (?, 'a', 'h', 'b', 'x', 1.0)", (pid,))
        rid = conn.execute("SELECT id FROM reviews WHERE author='a'").fetchone()["id"]
        conn.commit()

        models.save_review_analysis(
            review_id=rid, sentiment="negative", sentiment_score=0.9,
            impact_category="safety", failure_mode="主轴金属屑脱落",
            prompt_version="v2",
        )

        row = conn.execute(
            "SELECT impact_category, failure_mode FROM review_analysis WHERE review_id=?", (rid,)
        ).fetchone()
        assert row["impact_category"] == "safety"
        assert row["failure_mode"] == "主轴金属屑脱落"

    def test_save_without_new_fields_backward_compat(self, db):
        """Calling without the new params should work (default None)."""
        conn = _get_test_conn(db)
        conn.execute("INSERT INTO products (url, site, name, sku) VALUES ('http://t2', 'test', 'T2', 'T2')")
        pid = conn.execute("SELECT id FROM products WHERE sku='T2'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating) "
            "VALUES (?, 'b', 'h2', 'b2', 'y', 2.0)", (pid,))
        rid = conn.execute("SELECT id FROM reviews WHERE author='b'").fetchone()["id"]
        conn.commit()

        # Call WITHOUT new params — should still work
        models.save_review_analysis(review_id=rid, sentiment="negative")

        row = conn.execute(
            "SELECT impact_category, failure_mode FROM review_analysis WHERE review_id=?", (rid,)
        ).fetchone()
        assert row["impact_category"] is None
        assert row["failure_mode"] is None


class TestTranslatorV2Prompt:
    def test_prompt_includes_impact_fields(self):
        from qbu_crawler.server.translator import TranslationWorker
        worker = TranslationWorker.__new__(TranslationWorker)
        prompt = worker._build_analysis_prompt([
            {"index": 0, "headline": "Broke", "body": "Metal shavings", "rating": 1.0, "product_name": "Test"}
        ])
        assert "impact_category" in prompt
        assert "failure_mode" in prompt
        assert "safety" in prompt
        # Removed fields from spec 15.6 should NOT be present
        assert "usage_context" not in prompt
        assert "purchase_intent_impact" not in prompt
