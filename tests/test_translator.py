"""Tests for async translation: DB migration, query/update functions, worker."""

import json
import sqlite3
import time
from threading import Event, Thread
from unittest.mock import MagicMock

import pytest

from qbu_crawler import config, models


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Create a temp SQLite DB with schema initialized."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)

    def _conn():
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(models, "get_conn", _conn)
    models.init_db()
    return _conn


_review_counter = 0

def _insert_product(conn_fn, url="https://example.com/p/1", site="basspro"):
    conn = conn_fn()
    conn.execute(
        "INSERT INTO products (url, site, name, sku, price, ownership) VALUES (?, ?, 'Test', 'SKU1', 9.99, 'own')",
        (url, site),
    )
    conn.commit()
    pid = conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()["id"]
    conn.close()
    return pid


def _insert_review(conn_fn, product_id, headline="Good", body="Nice product", translate_status=None, retries=0):
    global _review_counter
    _review_counter += 1
    body_hash = f"hash{_review_counter}"
    conn = conn_fn()
    conn.execute(
        """INSERT INTO reviews (product_id, author, headline, body, body_hash, rating,
                                translate_status, translate_retries)
           VALUES (?, 'Author', ?, ?, ?, 5.0, ?, ?)""",
        (product_id, headline, body, body_hash, translate_status, retries),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rid


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------

class TestMigration:
    def test_translation_columns_exist(self, test_db):
        conn = test_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
        conn.close()
        assert "headline_cn" in cols
        assert "body_cn" in cols
        assert "translate_status" in cols
        assert "translate_retries" in cols

    def test_translate_status_index_exists(self, test_db):
        conn = test_db()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='reviews'"
        ).fetchall()
        conn.close()
        index_names = {row[0] for row in indexes}
        assert "idx_reviews_translate_status" in index_names

    def test_restart_does_not_overwrite_pending(self, tmp_path, monkeypatch):
        """Newly inserted reviews with NULL status should survive a restart."""
        db_file = str(tmp_path / "fresh.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)

        def _conn():
            c = sqlite3.connect(db_file)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(models, "get_conn", _conn)
        models.init_db()

        conn = _conn()
        conn.execute("INSERT INTO products (url, site, name, ownership) VALUES ('http://x', 'basspro', 'X', 'own')")
        conn.commit()
        pid = conn.execute("SELECT id FROM products").fetchone()["id"]
        conn.execute("INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, translate_status) VALUES (?, 'A', 'H', 'B', 'hx', 5.0, NULL)", (pid,))
        conn.commit()
        conn.close()

        # Re-run init_db (simulates restart)
        models.init_db()

        conn = _conn()
        row = conn.execute("SELECT translate_status FROM reviews").fetchone()
        conn.close()
        assert row["translate_status"] is None  # NOT overwritten to 'skipped'

    def test_backfill_only_runs_on_first_migration(self, tmp_path, monkeypatch):
        """Backfill marks existing reviews as skipped only when column is first added."""
        db_file = str(tmp_path / "backfill.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)

        def _conn():
            c = sqlite3.connect(db_file)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(models, "get_conn", _conn)

        # Create tables WITHOUT translate_status to simulate pre-migration DB
        conn = _conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                site TEXT NOT NULL DEFAULT 'basspro',
                name TEXT, sku TEXT, price REAL, stock_status TEXT,
                review_count INTEGER, rating REAL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ownership TEXT NOT NULL DEFAULT 'competitor'
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                author TEXT, headline TEXT, body TEXT, body_hash TEXT,
                rating REAL, date_published TEXT, images TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );
        """)
        conn.execute("INSERT INTO products (url, site, name, ownership) VALUES ('http://old', 'basspro', 'Old', 'own')")
        conn.commit()
        pid = conn.execute("SELECT id FROM products").fetchone()["id"]
        conn.execute("INSERT INTO reviews (product_id, author, headline, body, body_hash, rating) VALUES (?, 'A', 'H', 'B', 'hold', 5.0)", (pid,))
        conn.commit()
        conn.close()

        # First init_db — adds translate_status column + backfill
        models.init_db()

        conn = _conn()
        row = conn.execute("SELECT translate_status FROM reviews").fetchone()
        conn.close()
        assert row["translate_status"] == "skipped"


# ---------------------------------------------------------------------------
# DB query/update functions
# ---------------------------------------------------------------------------

class TestTranslationDB:
    def test_get_pending_translations_empty(self, test_db):
        result = models.get_pending_translations(limit=20)
        assert result == []

    def test_get_pending_translations_picks_null(self, test_db):
        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, translate_status=None)
        result = models.get_pending_translations(limit=20)
        assert len(result) == 1
        assert result[0]["id"] == rid

    def test_get_pending_translations_picks_failed(self, test_db):
        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, translate_status="failed", retries=1)
        result = models.get_pending_translations(limit=20)
        assert len(result) == 1
        assert result[0]["id"] == rid

    def test_get_pending_translations_skips_done(self, test_db):
        pid = _insert_product(test_db)
        _insert_review(test_db, pid, translate_status="done")
        result = models.get_pending_translations(limit=20)
        assert result == []

    def test_get_pending_translations_skips_max_retries(self, test_db):
        pid = _insert_product(test_db)
        _insert_review(test_db, pid, translate_status="failed", retries=3)
        result = models.get_pending_translations(limit=20)
        assert result == []

    def test_get_pending_translations_newest_first(self, test_db):
        pid = _insert_product(test_db)
        conn = test_db()
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'A', 'Old', 'old', 'ho1', 5, '2026-01-01', NULL)",
            (pid,),
        )
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'B', 'New', 'new', 'hn2', 5, '2026-03-11', NULL)",
            (pid,),
        )
        conn.commit()
        conn.close()
        result = models.get_pending_translations(limit=20)
        assert result[0]["headline"] == "New"

    def test_update_translation_done(self, test_db):
        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, translate_status=None)
        models.update_translation(rid, "中文标题", "中文内容", "done")
        conn = test_db()
        row = conn.execute("SELECT headline_cn, body_cn, translate_status FROM reviews WHERE id = ?", (rid,)).fetchone()
        conn.close()
        assert row["headline_cn"] == "中文标题"
        assert row["body_cn"] == "中文内容"
        assert row["translate_status"] == "done"

    def test_increment_translate_retries(self, test_db):
        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, translate_status=None, retries=0)
        models.increment_translate_retries(rid, max_retries=3)
        conn = test_db()
        row = conn.execute("SELECT translate_status, translate_retries FROM reviews WHERE id = ?", (rid,)).fetchone()
        conn.close()
        assert row["translate_retries"] == 1
        assert row["translate_status"] == "failed"

    def test_increment_translate_retries_marks_skipped(self, test_db):
        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, translate_status="failed", retries=2)
        models.increment_translate_retries(rid, max_retries=3)
        conn = test_db()
        row = conn.execute("SELECT translate_status, translate_retries FROM reviews WHERE id = ?", (rid,)).fetchone()
        conn.close()
        assert row["translate_retries"] == 3
        assert row["translate_status"] == "skipped"

    def test_reset_skipped_translations(self, test_db):
        pid = _insert_product(test_db)
        _insert_review(test_db, pid, translate_status="skipped", retries=3)
        count = models.reset_skipped_translations()
        assert count == 1
        conn = test_db()
        row = conn.execute("SELECT translate_status, translate_retries FROM reviews").fetchone()
        conn.close()
        assert row["translate_status"] is None
        assert row["translate_retries"] == 0

    def test_get_translate_stats(self, test_db):
        pid = _insert_product(test_db)
        _insert_review(test_db, pid, translate_status="done")
        _insert_review(test_db, pid, translate_status=None)
        _insert_review(test_db, pid, translate_status="failed", retries=1)
        _insert_review(test_db, pid, translate_status="skipped", retries=3)
        stats = models.get_translate_stats()
        assert stats["total"] == 4
        assert stats["done"] == 1
        assert stats["pending"] == 1
        assert stats["failed"] == 1
        assert stats["skipped"] == 1

    def test_get_translate_stats_with_since(self, test_db):
        pid = _insert_product(test_db)
        conn = test_db()
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'A', 'Old', 'old', 'hs1', 5, '2026-01-01', 'done')",
            (pid,),
        )
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'B', 'New', 'new', 'hs2', 5, '2026-03-11', NULL)",
            (pid,),
        )
        conn.commit()
        conn.close()
        stats = models.get_translate_stats(since="2026-03-10")
        assert stats["total"] == 1
        assert stats["pending"] == 1
        assert stats["done"] == 0


from qbu_crawler.server.translator import TranslationWorker


# ---------------------------------------------------------------------------
# TranslationWorker tests
# ---------------------------------------------------------------------------

class TestTranslationWorker:
    def test_skip_empty_content(self, test_db, monkeypatch):
        """Reviews with empty headline+body should be marked done without LLM call."""
        monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
        monkeypatch.setattr(config, "LLM_TRANSLATE_BATCH_SIZE", 20)
        monkeypatch.setattr(config, "TRANSLATE_INTERVAL", 1)
        monkeypatch.setattr(config, "TRANSLATE_MAX_RETRIES", 3)

        pid = _insert_product(test_db)
        conn = test_db()
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, translate_status) VALUES (?, 'A', '', '', 'hempty', 5, NULL)",
            (pid,),
        )
        conn.commit()
        conn.close()

        worker = TranslationWorker(interval=1, batch_size=20)
        worker._process_round()

        conn = test_db()
        row = conn.execute("SELECT translate_status, headline_cn, body_cn FROM reviews WHERE body_hash = 'hempty'").fetchone()
        conn.close()
        assert row["translate_status"] == "done"
        assert row["headline_cn"] == ""
        assert row["body_cn"] == ""

    def test_successful_translation(self, test_db, monkeypatch):
        """Successful LLM response should update headline_cn/body_cn and mark done."""
        monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
        monkeypatch.setattr(config, "LLM_API_BASE", "")
        monkeypatch.setattr(config, "LLM_MODEL", "test")
        monkeypatch.setattr(config, "LLM_TRANSLATE_BATCH_SIZE", 20)
        monkeypatch.setattr(config, "TRANSLATE_INTERVAL", 1)
        monkeypatch.setattr(config, "TRANSLATE_MAX_RETRIES", 3)

        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, headline="Great", body="Loved it", translate_status=None)

        def mock_call_llm(client, messages):
            return json.dumps([{"index": 0, "headline_cn": "很棒", "body_cn": "喜欢"}])

        worker = TranslationWorker(interval=1, batch_size=20)
        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)
        worker._process_round()

        conn = test_db()
        row = conn.execute("SELECT headline_cn, body_cn, translate_status FROM reviews WHERE id = ?", (rid,)).fetchone()
        conn.close()
        assert row["headline_cn"] == "很棒"
        assert row["body_cn"] == "喜欢"
        assert row["translate_status"] == "done"

    def test_partial_batch_success(self, test_db, monkeypatch):
        """LLM returns only 1 of 2 — translated one is done, other stays NULL."""
        monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
        monkeypatch.setattr(config, "LLM_API_BASE", "")
        monkeypatch.setattr(config, "LLM_MODEL", "test")
        monkeypatch.setattr(config, "LLM_TRANSLATE_BATCH_SIZE", 20)
        monkeypatch.setattr(config, "TRANSLATE_INTERVAL", 1)
        monkeypatch.setattr(config, "TRANSLATE_MAX_RETRIES", 3)

        pid = _insert_product(test_db)
        rid1 = _insert_review(test_db, pid, headline="Good", body="Nice", translate_status=None)
        conn = test_db()
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, translate_status) VALUES (?, 'B', 'Bad', 'Hate it', 'hpartial', 1, NULL)",
            (pid,),
        )
        conn.commit()
        rid2 = conn.execute("SELECT id FROM reviews WHERE body_hash = 'hpartial'").fetchone()["id"]
        conn.close()

        def mock_call_llm(client, messages):
            return json.dumps([{"index": 0, "headline_cn": "好", "body_cn": "不错"}])

        worker = TranslationWorker(interval=1, batch_size=20)
        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)
        worker._process_round()

        conn = test_db()
        r1 = conn.execute("SELECT translate_status FROM reviews WHERE id = ?", (rid1,)).fetchone()
        r2 = conn.execute("SELECT translate_status FROM reviews WHERE id = ?", (rid2,)).fetchone()
        conn.close()
        assert r1["translate_status"] == "done"
        assert r2["translate_status"] is None

    def test_batch_failure_increments_retries(self, test_db, monkeypatch):
        """Full batch LLM error should increment retries for all reviews."""
        monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
        monkeypatch.setattr(config, "LLM_API_BASE", "")
        monkeypatch.setattr(config, "LLM_MODEL", "test")
        monkeypatch.setattr(config, "LLM_TRANSLATE_BATCH_SIZE", 20)
        monkeypatch.setattr(config, "TRANSLATE_INTERVAL", 1)
        monkeypatch.setattr(config, "TRANSLATE_MAX_RETRIES", 3)

        pid = _insert_product(test_db)
        rid = _insert_review(test_db, pid, headline="Good", body="Nice", translate_status=None, retries=0)

        def mock_call_llm(client, messages):
            raise RuntimeError("API down")

        worker = TranslationWorker(interval=1, batch_size=20)
        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)
        worker._process_round()

        conn = test_db()
        row = conn.execute("SELECT translate_status, translate_retries FROM reviews WHERE id = ?", (rid,)).fetchone()
        conn.close()
        assert row["translate_retries"] == 1
        assert row["translate_status"] == "failed"

    def test_trigger_wakes_worker(self, test_db, monkeypatch):
        """trigger() should set the wake event."""
        worker = TranslationWorker(interval=60, batch_size=20)
        assert not worker._wake_event.is_set()
        worker.trigger()
        assert worker._wake_event.is_set()

    def test_no_start_without_api_key(self, test_db, monkeypatch):
        """Worker should not start thread if LLM_API_KEY is empty."""
        monkeypatch.setattr(config, "LLM_API_KEY", "")
        worker = TranslationWorker(interval=1, batch_size=20)
        worker.start()
        assert not worker._thread.is_alive()

    def test_run_loop_processes_and_idles(self, test_db, monkeypatch):
        """Integration test: start() → insert review → trigger() → verify translated → stop()."""
        monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
        monkeypatch.setattr(config, "LLM_API_BASE", "")
        monkeypatch.setattr(config, "LLM_MODEL", "test")
        monkeypatch.setattr(config, "LLM_TRANSLATE_BATCH_SIZE", 20)
        monkeypatch.setattr(config, "TRANSLATE_INTERVAL", 1)
        monkeypatch.setattr(config, "TRANSLATE_MAX_RETRIES", 3)

        pid = _insert_product(test_db)
        _insert_review(test_db, pid, headline="Hello", body="World", translate_status=None)

        def mock_call_llm(client, messages):
            return json.dumps([{"index": 0, "headline_cn": "你好", "body_cn": "世界"}])

        worker = TranslationWorker(interval=1, batch_size=20)
        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)
        worker._client = MagicMock()
        worker._thread = Thread(target=worker._run, daemon=True, name="test-worker")
        worker._thread.start()
        worker.trigger()

        time.sleep(0.5)
        worker.stop()
        worker._thread.join(timeout=2)

        conn = test_db()
        row = conn.execute("SELECT headline_cn, translate_status FROM reviews WHERE headline = 'Hello'").fetchone()
        conn.close()
        assert row["headline_cn"] == "你好"
        assert row["translate_status"] == "done"
