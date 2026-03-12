# Async Translation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple review translation from the report pipeline into a background daemon thread, making translation concurrent with crawling and report generation instant.

**Architecture:** DB-as-Queue pattern — `reviews` table gains translation columns and serves as the work queue. A `TranslationWorker` daemon thread polls for untranslated rows, translates via LLM API, and persists results. Crawlers trigger the worker after saving reviews. `generate_report` reads pre-translated data from DB without blocking.

**Tech Stack:** Python 3.10+, SQLite (WAL), threading, OpenAI SDK, FastMCP

**Spec:** `docs/superpowers/specs/2026-03-11-async-translation-design.md`

---

## Chunk 1: Database Layer + Config

### Task 1: Add translation config

**Files:**
- Modify: `config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add config vars to `config.py`**

After the `LLM_TRANSLATE_BATCH_SIZE` line (~line 57), add:

```python
# ── Translation Worker ────────────────────────
TRANSLATE_INTERVAL = int(os.getenv("TRANSLATE_INTERVAL", "60"))
TRANSLATE_MAX_RETRIES = int(os.getenv("TRANSLATE_MAX_RETRIES", "3"))
```

- [ ] **Step 2: Update `.env.example`**

After the `LLM_TRANSLATE_BATCH_SIZE=20` line, add:

```
TRANSLATE_INTERVAL=60
TRANSLATE_MAX_RETRIES=3
```

- [ ] **Step 3: Commit**

```bash
git add config.py .env.example
git commit -m "feat: add TRANSLATE_INTERVAL and TRANSLATE_MAX_RETRIES config"
```

---

### Task 2: Database migration — add translation columns + index

**Files:**
- Modify: `models.py` (migrations in `init_db()`)
- Test: `tests/test_translator.py` (new file, migration test)

- [ ] **Step 1: Write the failing test**

Create `tests/test_translator.py`:

```python
"""Tests for async translation: DB migration, query/update functions, worker."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import config
import models


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


_review_counter = 0

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

    def test_historical_reviews_marked_skipped(self, tmp_path, monkeypatch):
        """Reviews that exist when translate_status column is first added should be marked skipped."""
        # Use a fresh DB without translate_status column to simulate first migration
        db_file = str(tmp_path / "fresh.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)

        def _conn():
            c = sqlite3.connect(db_file)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(models, "get_conn", _conn)
        # First init creates all columns including translate_status + backfill
        models.init_db()

        # Insert a product + review (will have translate_status from column default)
        conn = _conn()
        conn.execute("INSERT INTO products (url, site, name, ownership) VALUES ('http://x', 'basspro', 'X', 'own')")
        conn.commit()
        pid = conn.execute("SELECT id FROM products").fetchone()["id"]
        conn.execute("INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, translate_status) VALUES (?, 'A', 'H', 'B', 'hx', 5.0, NULL)", (pid,))
        conn.commit()
        conn.close()

        # Re-run init_db (simulates restart) — should NOT overwrite NULL reviews
        models.init_db()

        conn = _conn()
        row = conn.execute("SELECT translate_status FROM reviews").fetchone()
        conn.close()
        # NULL means pending translation — NOT overwritten to 'skipped'
        assert row["translate_status"] is None

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

        # Manually create tables WITHOUT translate_status to simulate pre-migration DB
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

        # Now run init_db — this is the FIRST migration, should backfill
        models.init_db()

        conn = _conn()
        row = conn.execute("SELECT translate_status FROM reviews").fetchone()
        conn.close()
        assert row["translate_status"] == "skipped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_translator.py::TestMigration -v`
Expected: FAIL — columns don't exist yet

- [ ] **Step 3: Implement migration in `models.py`**

In `init_db()`, **replace** the migrations list and the code after the `idx_reviews_dedup` index creation with the following. The key change: backfill is tied to a successful `ALTER TABLE` (first migration only), not unconditional.

First, append to the `migrations` list (~line 74):

```python
        "ALTER TABLE reviews ADD COLUMN headline_cn TEXT",
        "ALTER TABLE reviews ADD COLUMN body_cn TEXT",
        "ALTER TABLE reviews ADD COLUMN translate_retries INTEGER DEFAULT 0",
```

Note: `translate_status` is NOT in the migrations list — it gets special handling below.

Then, after the existing `idx_reviews_dedup` index creation and `conn.close()` at line 113-114, **replace** `conn.close()` with:

```python
    # ── Translation status column + one-time backfill ──
    # The backfill (marking historical reviews as 'skipped') must only run once,
    # when the column is first added. We detect this by checking if the ALTER TABLE
    # succeeds (first run) or raises OperationalError (column already exists).
    _needs_translate_backfill = False
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN translate_status TEXT")
        _needs_translate_backfill = True
    except sqlite3.OperationalError:
        pass  # Column already exists

    if _needs_translate_backfill:
        conn.execute("UPDATE reviews SET translate_status = 'skipped' WHERE translate_status IS NULL")
        conn.commit()

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reviews_translate_status
        ON reviews (translate_status)
    """)
    conn.close()
```

This ensures the backfill only runs on the first `init_db()` after the column is added. Subsequent restarts skip it, so newly inserted reviews with `translate_status IS NULL` (pending) are not overwritten.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_translator.py::TestMigration -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_translator.py
git commit -m "feat: add translation columns, index, and backfill migration"
```

---

### Task 3: Translation DB query/update functions in models.py

**Files:**
- Modify: `models.py`
- Test: `tests/test_translator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_translator.py`:

```python
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
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'A', 'Old', 'old', 'h1', 5, '2026-01-01', NULL)",
            (pid,),
        )
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'B', 'New', 'new', 'h2', 5, '2026-03-11', NULL)",
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
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'A', 'Old', 'old', 'h1', 5, '2026-01-01', 'done')",
            (pid,),
        )
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at, translate_status) VALUES (?, 'B', 'New', 'new', 'h2', 5, '2026-03-11', NULL)",
            (pid,),
        )
        conn.commit()
        conn.close()
        stats = models.get_translate_stats(since="2026-03-10")
        assert stats["total"] == 1
        assert stats["pending"] == 1
        assert stats["done"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_translator.py::TestTranslationDB -v`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement DB functions in `models.py`**

Add at the end of `models.py`, before any existing trailing code:

```python
# ---------------------------------------------------------------------------
# Translation queue functions
# ---------------------------------------------------------------------------

def get_pending_translations(limit: int = 20) -> list[dict]:
    """Fetch reviews needing translation, newest first."""
    import config as _cfg
    max_retries = _cfg.TRANSLATE_MAX_RETRIES
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, headline, body FROM reviews
               WHERE translate_status IS NULL
                  OR (translate_status = 'failed' AND translate_retries < ?)
               ORDER BY scraped_at DESC
               LIMIT ?""",
            (max_retries, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_translation(review_id: int, headline_cn: str, body_cn: str, status: str) -> None:
    """Mark a review as translated."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE reviews SET headline_cn = ?, body_cn = ?, translate_status = ? WHERE id = ?",
            (headline_cn, body_cn, status, review_id),
        )
        conn.commit()
    finally:
        conn.close()


def increment_translate_retries(review_id: int, max_retries: int = 3) -> None:
    """Increment retry counter; mark 'skipped' if max reached."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE reviews SET translate_retries = translate_retries + 1 WHERE id = ?",
            (review_id,),
        )
        conn.execute(
            "UPDATE reviews SET translate_status = 'skipped' WHERE id = ? AND translate_retries >= ?",
            (review_id, max_retries),
        )
        conn.execute(
            "UPDATE reviews SET translate_status = 'failed' WHERE id = ? AND translate_retries < ?",
            (review_id, max_retries),
        )
        conn.commit()
    finally:
        conn.close()


def reset_skipped_translations() -> int:
    """Reset all skipped reviews back to pending (NULL). Returns count."""
    conn = get_conn()
    try:
        cursor = conn.execute(
            "UPDATE reviews SET translate_status = NULL, translate_retries = 0 WHERE translate_status = 'skipped'"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_translate_stats(since: str | None = None) -> dict:
    """Return translation status counts. Optional since filter (YYYY-MM-DD or full timestamp)."""
    conn = get_conn()
    try:
        where = ""
        params: list = []
        if since:
            where = "WHERE scraped_at >= ?"
            params = [since]

        total = conn.execute(f"SELECT COUNT(*) FROM reviews {where}", params).fetchone()[0]

        def _count(status_val, is_null=False):
            if is_null:
                cond = "translate_status IS NULL"
                p = list(params)
            else:
                cond = "translate_status = ?"
                p = list(params) + [status_val]
            w = f"WHERE {cond}" if not where else f"{where} AND {cond}"
            return conn.execute(f"SELECT COUNT(*) FROM reviews {w}", p).fetchone()[0]

        return {
            "total": total,
            "done": _count("done"),
            "pending": _count(None, is_null=True),
            "failed": _count("failed"),
            "skipped": _count("skipped"),
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_translator.py::TestTranslationDB -v`
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_translator.py
git commit -m "feat: add translation queue DB functions"
```

---

## Chunk 2: TranslationWorker

### Task 4: Create `server/translator.py` — core worker

**Files:**
- Create: `server/translator.py`
- Test: `tests/test_translator.py` (append worker tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_translator.py`:

```python
import time
from threading import Event, Thread
from unittest.mock import MagicMock
from server.translator import TranslationWorker


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
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, translate_status) VALUES (?, 'A', '', '', 'h1', 5, NULL)",
            (pid,),
        )
        conn.commit()
        conn.close()

        worker = TranslationWorker(interval=1, batch_size=20)
        worker._process_batch()

        conn = test_db()
        row = conn.execute("SELECT translate_status, headline_cn, body_cn FROM reviews").fetchone()
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
        worker._process_batch()

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
        # Need unique dedup key for second review
        conn = test_db()
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, translate_status) VALUES (?, 'B', 'Bad', 'Hate it', 'h2', 1, NULL)",
            (pid,),
        )
        conn.commit()
        rid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        def mock_call_llm(client, messages):
            # Only return translation for index 0
            return json.dumps([{"index": 0, "headline_cn": "好", "body_cn": "不错"}])

        worker = TranslationWorker(interval=1, batch_size=20)
        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)
        worker._process_batch()

        conn = test_db()
        r1 = conn.execute("SELECT translate_status FROM reviews WHERE id = ?", (rid1,)).fetchone()
        r2 = conn.execute("SELECT translate_status FROM reviews WHERE id = ?", (rid2,)).fetchone()
        conn.close()
        assert r1["translate_status"] == "done"
        assert r2["translate_status"] is None  # stays pending

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
        worker._process_batch()

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
        worker._client = MagicMock()  # bypass OpenAI init
        worker._thread = Thread(target=worker._run, daemon=True, name="test-worker")
        worker._thread.start()
        worker.trigger()

        # Wait for the worker to process
        time.sleep(0.5)
        worker.stop()
        worker._thread.join(timeout=2)

        conn = test_db()
        row = conn.execute("SELECT headline_cn, translate_status FROM reviews").fetchone()
        conn.close()
        assert row["headline_cn"] == "你好"
        assert row["translate_status"] == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_translator.py::TestTranslationWorker -v`
Expected: FAIL — `server.translator` doesn't exist

- [ ] **Step 3: Create `server/translator.py`**

```python
"""Background translation worker — DB-as-queue pattern.

Polls for untranslated reviews, sends them to LLM in batches,
and persists results back to SQLite. Runs as a daemon thread.
"""

import json
import logging
from threading import Event, Thread

from openai import OpenAI

import config
import models

logger = logging.getLogger(__name__)


def _strip_markdown_json(text: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


class TranslationWorker:
    """Daemon thread that translates reviews in the background."""

    def __init__(self, interval: int = 60, batch_size: int = 20):
        self._interval = interval
        self._batch_size = batch_size
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="translation-worker")
        self._client: OpenAI | None = None

    def start(self):
        """Start the worker thread. No-op if LLM is not configured."""
        if not config.LLM_API_KEY:
            logger.info("TranslationWorker: LLM_API_KEY not set, skipping start")
            return
        self._client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_API_BASE or None,
        )
        self._thread.start()
        logger.info("TranslationWorker: started (interval=%ds, batch=%d)", self._interval, self._batch_size)

    def stop(self):
        """Signal the worker to stop."""
        self._stop_event.set()
        self._wake_event.set()  # unblock wait

    def trigger(self):
        """Wake the worker immediately (called after reviews are saved)."""
        self._wake_event.set()

    def _run(self):
        """Main loop: poll → translate → sleep/wait."""
        while not self._stop_event.is_set():
            self._wake_event.clear()
            self._wake_event.wait(timeout=self._interval)

            if self._stop_event.is_set():
                break

            try:
                has_more = self._process_batch()
                # If there are more pending reviews, loop immediately
                while has_more and not self._stop_event.is_set():
                    has_more = self._process_batch()
            except Exception:
                logger.exception("TranslationWorker: unexpected error in loop")

    def _process_batch(self) -> bool:
        """Process one batch. Returns True if there may be more pending."""
        pending = models.get_pending_translations(limit=self._batch_size)
        if not pending:
            return False

        # Separate empty-content reviews (mark done without LLM call)
        to_translate = []
        for review in pending:
            headline = review.get("headline") or ""
            body = review.get("body") or ""
            if not headline.strip() and not body.strip():
                models.update_translation(review["id"], "", "", "done")
            else:
                to_translate.append(review)

        if not to_translate:
            return len(pending) == self._batch_size

        # Build LLM prompt
        items_payload = [
            {"index": i, "headline": r.get("headline") or "", "body": r.get("body") or ""}
            for i, r in enumerate(to_translate)
        ]
        prompt = (
            "请将以下英文产品评论的 headline 和 body 翻译为中文，"
            "保持原意，语言自然流畅。\n"
            "以 JSON 数组形式返回，每个元素包含 index、headline_cn、body_cn 三个字段。\n"
            "不要返回其他内容。\n\n"
            f"输入：\n{json.dumps(items_payload, ensure_ascii=False)}"
        )

        try:
            raw = self._call_llm(self._client, [{"role": "user", "content": prompt}])
            cleaned = _strip_markdown_json(raw)
            results = json.loads(cleaned)

            # Track which indices were returned
            translated_indices = set()
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(to_translate):
                    continue
                review = to_translate[idx]
                models.update_translation(
                    review["id"],
                    item.get("headline_cn", ""),
                    item.get("body_cn", ""),
                    "done",
                )
                translated_indices.add(idx)

            # Reviews NOT returned by LLM stay as NULL — picked up next round
            logger.info(
                "TranslationWorker: batch translated %d/%d reviews",
                len(translated_indices),
                len(to_translate),
            )

        except Exception as exc:
            # Entire batch failed — increment retries for all
            logger.warning("TranslationWorker: batch failed — %s", exc)
            for review in to_translate:
                models.increment_translate_retries(
                    review["id"],
                    max_retries=config.TRANSLATE_MAX_RETRIES,
                )

        return len(pending) == self._batch_size

    def _call_llm(self, client: OpenAI | None, messages: list[dict]) -> str:
        """Call the LLM API. Separated for testability."""
        if client is None:
            raise RuntimeError("OpenAI client not initialized")
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
        )
        return response.choices[0].message.content or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_translator.py::TestTranslationWorker -v`
Expected: all PASSED

- [ ] **Step 5: Run all translator tests together**

Run: `uv run pytest tests/test_translator.py -v`
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add server/translator.py tests/test_translator.py
git commit -m "feat: add TranslationWorker background daemon thread"
```

---

## Chunk 3: Report Simplification + TaskManager Integration

### Task 5: Simplify `report.py` — remove translation, read from DB

**Files:**
- Modify: `server/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: Update `query_report_data()` SQL to include translation columns**

In `server/report.py`, update the review query (~line 48) to add `r.headline_cn, r.body_cn, r.translate_status`:

```python
        review_rows = conn.execute(
            """
            SELECT p.name AS product_name,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.images, p.ownership,
                   r.headline_cn, r.body_cn, r.translate_status
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            WHERE r.scraped_at >= ?
            ORDER BY r.scraped_at DESC
            """,
            (since_str,),
        ).fetchall()
```

- [ ] **Step 2: Remove translation from `generate_report()`**

Replace the entire `generate_report` function (~lines 344-412) with:

```python
def generate_report(
    since: datetime,
    send_email: bool = True,
) -> dict:
    """Report pipeline: query (with pre-translated data) → Excel → email.

    Translation is handled by the background TranslationWorker.
    Reviews that haven't been translated yet will have empty Chinese fields.
    """
    # 1. Query (includes headline_cn/body_cn from DB)
    products, reviews = query_report_data(since)

    # 2. Count translation status
    translated_count = sum(
        1 for r in reviews if r.get("translate_status") == "done"
    )
    untranslated_count = len(reviews) - translated_count

    # Ensure Chinese fields exist for Excel generation
    for r in reviews:
        r.setdefault("headline_cn", "")
        r.setdefault("body_cn", "")

    # 3. Excel
    excel_path = generate_excel(products, reviews, report_date=since)

    # 4. Email
    email_result = None
    if send_email:
        recipients = config.EMAIL_RECIPIENTS
        since_str = since.strftime("%Y-%m-%d")
        subject = f"Qbu 每日抓取报告 {since_str}"
        body = (
            f"您好，\n\n"
            f"以下是 {since_str} 的 Qbu 产品抓取报告汇总：\n"
            f"  - 产品数：{len(products)}\n"
            f"  - 评论数：{len(reviews)}\n"
            f"  - 已翻译评论：{translated_count}\n"
        )
        if untranslated_count > 0:
            body += f"  - 注：{untranslated_count} 条评论翻译进行中，中文列暂时为空\n"
        body += f"\n详细数据请查阅附件 Excel 文件。\n"
        email_result = _send_email_impl(
            recipients=recipients,
            subject=subject,
            body_text=body,
            attachment_path=excel_path,
        )

    return {
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "untranslated_count": untranslated_count,
        "excel_path": excel_path,
        "email": email_result,
    }
```

- [ ] **Step 3: Remove old translation functions from `report.py`**

Delete these functions entirely (they now live in `translator.py`):
- `_call_llm()` (~lines 84-94)
- `_strip_markdown_json()` (~lines 97-105)
- `translate_reviews()` (~lines 108-164)

Also remove the unused `from openai import OpenAI` import at line 14.

- [ ] **Step 4: Update `tests/test_report.py`**

Remove these test functions (they test code that moved to translator.py):
- `test_translate_reviews_success`
- `test_translate_reviews_empty`
- `test_translate_reviews_partial_failure`
- `test_translate_reviews_markdown_json`

Update `test_generate_report_full`:

```python
def test_generate_report_full(patch_db, tmp_path, monkeypatch):
    """Full pipeline — translation comes from DB, not inline."""
    monkeypatch.setattr(config, "DB_PATH", patch_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from server.report import generate_report

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = generate_report(since, send_email=False)

    assert result["products_count"] == 1
    assert result["reviews_count"] == 1
    assert result["translated_count"] == 0
    assert result["untranslated_count"] == 1
    assert os.path.isfile(result["excel_path"])
    assert result["email"] is None
```

Replace `test_generate_report_with_translation` with a test that verifies DB-based translation:

```python
def test_generate_report_with_pretranslated_reviews(patch_db, tmp_path, monkeypatch):
    """Pipeline reads pre-translated data from DB."""
    monkeypatch.setattr(config, "DB_PATH", patch_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    # Update the review to have translation data
    import sqlite3
    conn = sqlite3.connect(patch_db)
    conn.execute(
        "UPDATE reviews SET headline_cn = '好产品', body_cn = '非常喜欢', translate_status = 'done'"
    )
    conn.commit()
    conn.close()

    from server.report import generate_report

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = generate_report(since, send_email=False)

    assert result["reviews_count"] == 1
    assert result["translated_count"] == 1
    assert result["untranslated_count"] == 0
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_report.py -v`
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add server/report.py tests/test_report.py
git commit -m "refactor: remove inline translation from report pipeline, read from DB"
```

---

### Task 6: TaskManager integration — trigger translator after saving reviews

**Files:**
- Modify: `server/task_manager.py`

- [ ] **Step 1: Add `translator` parameter to `TaskManager.__init__`**

```python
class TaskManager:
    def __init__(self, max_workers: int = 3, translator=None):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, Task] = {}
        self._cancel_flags: dict[str, Event] = {}
        self._translator = translator
```

- [ ] **Step 2: Add trigger call in `_run_scrape` after `save_reviews`**

After `rc = models.save_reviews(pid, reviews)` (~line 137), add:

```python
                    rc = models.save_reviews(pid, reviews)
                    if rc > 0 and self._translator:
                        self._translator.trigger()
```

- [ ] **Step 3: Add trigger call in `_run_collect` after `save_reviews`**

After `rc = models.save_reviews(pid, reviews)` (~line 216), add the same pattern:

```python
                    rc = models.save_reviews(pid, reviews)
                    if rc > 0 and self._translator:
                        self._translator.trigger()
```

- [ ] **Step 4: Commit**

```bash
git add server/task_manager.py
git commit -m "feat: trigger translation worker after saving reviews"
```

---

## Chunk 4: MCP + App Wiring

### Task 7: Wire up in `server/app.py`

**Files:**
- Modify: `server/app.py`

- [ ] **Step 1: Import and initialize TranslationWorker**

Add import and create translator before task_manager:

```python
from server.translator import TranslationWorker

# ── Shared singletons ──────────────────────────
translator = TranslationWorker(
    interval=config.TRANSLATE_INTERVAL,
    batch_size=config.LLM_TRANSLATE_BATCH_SIZE,
)
task_manager = TaskManager(max_workers=config.MAX_WORKERS, translator=translator)
```

- [ ] **Step 2: Start translator in `start_server`**

After `models.init_db()` line, add:

```python
    models.init_db()
    translator.start()
```

- [ ] **Step 3: Commit**

```bash
git add server/app.py
git commit -m "feat: wire TranslationWorker into app startup"
```

---

### Task 8: MCP tools — new tools + update generate_report

**Files:**
- Modify: `server/mcp/tools.py`

- [ ] **Step 1: Update `generate_report` tool docstring**

Change the docstring from:
```
生成爬虫数据报告：查询新增数据 → 翻译评论为中文 → 生成 Excel → 发送邮件。
```
To:
```
生成爬虫数据报告：查询新增数据（含已翻译的中文）→ 生成 Excel → 发送邮件。
翻译由后台线程自动执行，无需等待。如需确认翻译完成度，先调用 get_translate_status。
```

- [ ] **Step 2: Add `trigger_translate` tool**

After the `generate_report` tool, add:

```python
    @mcp.tool
    def trigger_translate(reset_skipped: str = "false") -> str:
        """手动触发翻译，立即唤醒后台翻译线程处理未翻译的评论。
        reset_skipped: "true" 时先将所有 skipped 评论重置为待翻译（用于补翻历史数据），
        "false"（默认）只触发现有待翻译队列。
        返回当前待翻译数量。"""
        from server.app import translator
        if reset_skipped.lower() == "true":
            count = models.reset_skipped_translations()
            logger.info("trigger_translate: reset %d skipped reviews", count)
        translator.trigger()
        stats = models.get_translate_stats()
        return _json.dumps({
            "message": "翻译线程已唤醒",
            "pending": stats["pending"],
            "failed": stats["failed"],
        })
```

- [ ] **Step 3: Add `get_translate_status` tool**

```python
    @mcp.tool
    def get_translate_status(since: str = "") -> str:
        """查询翻译进度：总评论数、已翻译、待翻译、失败数、跳过数。
        since: 可选，上海时间戳（YYYY-MM-DDTHH:MM:SS），只统计该时间之后的评论。
        留空则返回全量统计。"""
        stats = models.get_translate_stats(since=since if since else None)
        return _json.dumps(stats)
```

- [ ] **Step 4: Add `import logging` and logger at top of tools.py**

At the top of `tools.py`, after the existing imports:

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 5: Commit**

```bash
git add server/mcp/tools.py
git commit -m "feat: add trigger_translate and get_translate_status MCP tools"
```

---

### Task 9: Update MCP resources — SCHEMA_REVIEWS

**Files:**
- Modify: `server/mcp/resources.py`

- [ ] **Step 1: Add translation columns to SCHEMA_REVIEWS**

In the `SCHEMA_REVIEWS` table, after the `scraped_at` row, add:

```
| headline_cn | TEXT | | 评论标题中文翻译 |
| body_cn | TEXT | | 评论正文中文翻译 |
| translate_status | TEXT | | 翻译状态：NULL=待翻译, done=完成, failed=重试中, skipped=跳过 |
| translate_retries | INTEGER | DEFAULT 0 | 翻译失败重试次数 |
```

Also update the `SCHEMA_OVERVIEW` string to mention the translation feature:

Add after "reviews 增量写入" line:
```
- reviews.translate_status 管理翻译队列（后台线程自动翻译评论为中文）
```

- [ ] **Step 2: Commit**

```bash
git add server/mcp/resources.py
git commit -m "docs: update MCP schema resources with translation columns"
```

---

## Chunk 5: Documentation

### Task 10: Update OpenClaw workspace docs

**Files:**
- Modify: `server/openclaw/workspace/TOOLS.md`
- Modify: `server/openclaw/workspace/skills/daily-scrape-report/SKILL.md`

- [ ] **Step 1: Update `TOOLS.md` — add new tools to parameter table**

In the "数据查询" table, after the `generate_report` row, add:

```
| `trigger_translate` | — | reset_skipped（默认 false） |
| `get_translate_status` | — | since（上海时间戳，可选） |
```

- [ ] **Step 2: Update `TOOLS.md` — add translate status to completion notification template**

In the "定时任务完成通知" template, after the `新增评论` line, add:

```
- **翻译进度**：N/M 已完成
```

- [ ] **Step 3: Update `daily-scrape-report/SKILL.md` step 2 description**

Change step 2 description from:
```
该工具由服务端程序化执行：查询新增数据 → LLM 翻译评论 → 生成 Excel → SMTP 发送邮件。不需要你本地做任何事。
```
To:
```
该工具由服务端程序化执行：查询新增数据（含已翻译的中文）→ 生成 Excel → SMTP 发送邮件。翻译由后台线程在爬虫采集期间自动完成。不需要你本地做任何事。
```

- [ ] **Step 4: Add optional translation check before report**

In `daily-scrape-report/SKILL.md`, before step 2 的 `调用方式：` block, add:

```markdown
**可选：检查翻译完成度**

调用 `get_translate_status(since=submitted_at)` 查看翻译进度。如果 `pending > 0`，可等待 1-2 分钟后再生成报告。最多等 3 轮（每轮 1 分钟），超时则直接生成报告（邮件中会标注未翻译数量）。
```

- [ ] **Step 5: Commit**

```bash
git add server/openclaw/workspace/TOOLS.md server/openclaw/workspace/skills/daily-scrape-report/SKILL.md
git commit -m "docs: update OpenClaw workspace docs for async translation"
```

---

### Task 11: Update project docs — CLAUDE.md + .env.example

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.env.example`

- [ ] **Step 1: Update project structure in CLAUDE.md**

In the project structure tree, add `server/translator.py` after `server/task_manager.py`:

```
│   ├── translator.py       # 后台翻译守护线程（DB-as-Queue + LLM 批量翻译）
```

And add `tests/test_translator.py` in the test section (if shown).

- [ ] **Step 2: Update architecture description in CLAUDE.md**

In "HTTP API + MCP 服务架构" section, update `generate_report` bullet:
```
- `generate_report` Tool：查询新增数据（含已翻译的中文）→ openpyxl 生成 Excel → smtplib 发送邮件，翻译由后台线程自动完成
- `TranslationWorker` 守护线程：DB-as-Queue 模式，轮询未翻译评论 → LLM 批量翻译 → 持久化到 reviews 表，与爬虫并行执行
```

- [ ] **Step 3: Add translation worker config table to CLAUDE.md**

After the LLM 翻译配置表, add:

```markdown
### 翻译 Worker 配置（.env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `TRANSLATE_INTERVAL` | `60` | 翻译轮询间隔（秒） |
| `TRANSLATE_MAX_RETRIES` | `3` | 单条评论最大重试次数，超过标记 skipped |
```

- [ ] **Step 4: Add `.env.example` entries**

Already done in Task 1 Step 2.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with async translation architecture"
```

---

### Task 12: Final integration test

- [ ] **Step 1: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: all PASSED

- [ ] **Step 2: Manual smoke test**

Start the server and verify:

```bash
uv run python main.py serve
```

Check logs for: `TranslationWorker: started (interval=60s, batch=20)` (or "skipping" if no LLM key).

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: final integration fixes for async translation"
```
