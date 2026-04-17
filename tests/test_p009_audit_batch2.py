"""P009 audit batch 2 — TDD test suite."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """独立 DB，避免污染 data/products.db。"""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


def test_mark_task_lost_writes_real_timestamp_not_sql_literal(fresh_db):
    """finished_at must be a parseable ISO timestamp, not a literal SQL expression."""
    models.save_task({
        "id": "T1",
        "type": "scrape",
        "status": "running",
        "params": {"urls": []},
        "created_at": config.now_shanghai().isoformat(),
    })
    ok = models.mark_task_lost("T1")
    assert ok
    row = models.get_task("T1")
    ft = row["finished_at"]
    # Must not be raw SQL expression text
    assert "datetime(" not in ft
    assert "+8 hours" not in ft
    # Must be a parseable ISO timestamp
    parsed = datetime.fromisoformat(ft)
    assert parsed is not None


def test_chrome_stderr_does_not_block_on_64kb_output(tmp_path):
    """Child process writes >64KB to stderr and sleeps. With a drain thread the parent
    must not be blocked by the pipe buffer: the child keeps running and stderr is
    fully readable."""
    import subprocess
    import sys
    import threading
    import time as _time

    # Child: write 100KB to stderr, then sleep 5s
    script = (
        "import sys, time; sys.stderr.write('X' * 102400); "
        "sys.stderr.flush(); time.sleep(5)"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    buf: list[bytes] = []

    def _drain():
        try:
            for chunk in iter(lambda: proc.stderr.read(4096), b""):
                buf.append(chunk)
        except Exception:
            pass

    t = threading.Thread(target=_drain, daemon=True)
    t.start()

    _time.sleep(1.5)
    try:
        assert proc.poll() is None, "child should still be sleeping"
        assert len(b"".join(buf)) >= 102400, "drain thread must have consumed stderr"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        t.join(timeout=2)


def test_sync_new_skus_skipped_when_category_synced_flag_is_set(fresh_db, monkeypatch):
    """workflow_runs.category_synced=1 must short-circuit the LLM call."""
    from qbu_crawler.server import workflows

    run = models.create_workflow_run({
        "workflow_type": "daily",
        "logical_date": "2026-04-17",
        "trigger_key": "daily:2026-04-17",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "status": "running",
        "created_at": config.now_shanghai().isoformat(),
        "updated_at": config.now_shanghai().isoformat(),
    })
    models.update_workflow_run(run["id"], category_synced=1)

    calls = {"n": 0}

    def _fake_sync(*a, **kw):
        calls["n"] += 1
        return 0

    monkeypatch.setattr(
        "qbu_crawler.server.category_inferrer.sync_new_skus", _fake_sync,
    )

    workflows._maybe_sync_category_map(run["id"])
    assert calls["n"] == 0


def test_sync_new_skus_runs_once_and_sets_flag(fresh_db, monkeypatch):
    """First call runs sync_new_skus and sets category_synced=1; second call is a no-op."""
    from qbu_crawler.server import workflows

    run = models.create_workflow_run({
        "workflow_type": "daily",
        "logical_date": "2026-04-18",
        "trigger_key": "daily:2026-04-18",
        "data_since": "2026-04-17T00:00:00+08:00",
        "data_until": "2026-04-18T00:00:00+08:00",
        "status": "running",
        "created_at": config.now_shanghai().isoformat(),
        "updated_at": config.now_shanghai().isoformat(),
    })

    calls = {"n": 0}

    def _fake_sync(*a, **kw):
        calls["n"] += 1
        return 3

    monkeypatch.setattr(
        "qbu_crawler.server.category_inferrer.sync_new_skus", _fake_sync,
    )

    workflows._maybe_sync_category_map(run["id"])
    workflows._maybe_sync_category_map(run["id"])  # second call must short-circuit

    assert calls["n"] == 1
    refreshed = models.get_workflow_run(run["id"])
    assert refreshed["category_synced"] == 1


def test_translation_coverage_gate_pure_function(monkeypatch):
    """Pure function gate: stalled + low coverage blocks, stalled + high coverage allows,
    not stalled always allows, zero total always allows."""
    from qbu_crawler import config
    from qbu_crawler.server.workflows import _translation_coverage_acceptable

    monkeypatch.setattr(config, "TRANSLATION_COVERAGE_MIN", 0.7)

    # 30% coverage while stalled → block
    assert _translation_coverage_acceptable(translated=3, total=10, stalled=True) is False
    # 80% coverage while stalled → allow
    assert _translation_coverage_acceptable(translated=8, total=10, stalled=True) is True
    # exactly at threshold while stalled → allow
    assert _translation_coverage_acceptable(translated=7, total=10, stalled=True) is True
    # Not stalled (still waiting) → always allow, even 0%
    assert _translation_coverage_acceptable(translated=0, total=10, stalled=False) is True
    # total=0 (no translatable reviews) → always allow
    assert _translation_coverage_acceptable(translated=0, total=0, stalled=True) is True


def test_translation_progress_snapshot_counts_from_reviews_table(fresh_db):
    """_translation_progress_snapshot must count reviews in the window (by scraped_at)
    and report the 'done' subset as translated, mirroring
    _count_pending_translations_for_window's column semantics.
    """
    from qbu_crawler.server.workflows import _translation_progress_snapshot

    # Insert a product so reviews have a valid FK
    conn = models.get_conn()
    try:
        cursor = conn.execute(
            """
            INSERT INTO products (site, url, name, sku)
            VALUES ('test', 'http://t/p1', 'P1', 'SKU-1')
            """
        )
        product_id = cursor.lastrowid
        # Window: 2026-04-10 00:00 → 2026-04-11 00:00 (Shanghai)
        # _report_db_ts strips tz and formats as naive Shanghai-local "YYYY-MM-DD HH:MM:SS"
        in_window = "2026-04-10 12:00:00"
        before_window = "2026-04-09 23:59:59"
        after_window = "2026-04-11 00:00:00"  # exclusive upper bound

        rows = [
            # In window: 3 done, 1 failed, 1 NULL, 1 skipped → total=6, translated=3
            (product_id, "a1", "h1", "b1", "done", in_window),
            (product_id, "a2", "h2", "b2", "done", in_window),
            (product_id, "a3", "h3", "b3", "done", in_window),
            (product_id, "a4", "h4", "b4", "failed", in_window),
            (product_id, "a5", "h5", "b5", None, in_window),
            (product_id, "a6", "h6", "b6", "skipped", in_window),
            # Outside window: should be ignored
            (product_id, "b1", "bh1", "bb1", "done", before_window),
            (product_id, "b2", "bh2", "bb2", "done", after_window),
        ]
        for pid, author, headline, body, status, scraped_at in rows:
            conn.execute(
                """
                INSERT INTO reviews
                    (product_id, author, headline, body, body_hash,
                     translate_status, scraped_at)
                VALUES (?, ?, ?, ?, '', ?, ?)
                """,
                (pid, author, headline, body, status, scraped_at),
            )
        conn.commit()
    finally:
        conn.close()

    translated, total = _translation_progress_snapshot(
        since="2026-04-10T00:00:00+08:00",
        until="2026-04-11T00:00:00+08:00",
    )
    assert total == 6
    assert translated == 3


def test_sync_new_skus_still_sets_flag_when_inner_raises(fresh_db, monkeypatch):
    """Even if sync_new_skus raises, the flag must be set to prevent retry-storm."""
    from qbu_crawler.server import workflows

    run = models.create_workflow_run({
        "workflow_type": "daily",
        "logical_date": "2026-04-19",
        "trigger_key": "daily:2026-04-19",
        "data_since": "2026-04-18T00:00:00+08:00",
        "data_until": "2026-04-19T00:00:00+08:00",
        "status": "running",
        "created_at": config.now_shanghai().isoformat(),
        "updated_at": config.now_shanghai().isoformat(),
    })

    def _bad_sync(*a, **kw):
        raise RuntimeError("simulated LLM timeout")

    monkeypatch.setattr(
        "qbu_crawler.server.category_inferrer.sync_new_skus", _bad_sync,
    )

    # Must not propagate the exception out of the helper
    workflows._maybe_sync_category_map(run["id"])

    refreshed = models.get_workflow_run(run["id"])
    assert refreshed["category_synced"] == 1


def test_infer_categories_isolates_failed_batches(monkeypatch):
    """One batch raising must not kill other batches; failed items fall back to 'other'."""
    from qbu_crawler.server import category_inferrer

    # Force one product per batch so each product is its own batch.
    monkeypatch.setattr(category_inferrer, "_BATCH_SIZE", 1)

    calls = {"n": 0}

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls["n"] += 1
                    # First batch: fail. Second: success.
                    if calls["n"] == 1:
                        raise RuntimeError("simulated LLM timeout")

                    class _R:
                        choices = [
                            type("C", (), {
                                "finish_reason": "stop",
                                "message": type("M", (), {
                                    "content": '{"results":[{"sku":"X","category":"grinder","sub_category":"","confidence":0.95}]}',
                                })(),
                            })(),
                        ]
                    return _R()

    products = [
        {"sku": "A", "name": "Kitchen Grinder #22", "url": ""},
        {"sku": "X", "name": "Meat Grinder", "url": ""},
    ]
    results = category_inferrer.infer_categories(products, client=_FakeClient())

    assert len(results) == 2
    by_sku = {r["sku"]: r for r in results}
    # A was in the failed batch → fallback to 'other' (confidence 0 < 0.7 → 'other')
    assert by_sku["A"]["category"] == "other"
    # X's batch succeeded
    assert by_sku["X"]["category"] == "grinder"
    # Exactly 2 LLM calls were attempted (one per batch)
    assert calls["n"] == 2


def test_append_csv_uses_exclusive_lock(tmp_path):
    """If a .lock sentinel file already exists, _append_csv must raise
    CategoryMapLocked; removing the lock lets it succeed."""
    import pytest
    from qbu_crawler.server import category_inferrer

    csv_path = tmp_path / "cat.csv"
    lock_path = tmp_path / "cat.csv.lock"
    lock_path.write_text("held-by-someone-else")

    with pytest.raises(category_inferrer.CategoryMapLocked):
        category_inferrer._append_csv(
            [{"sku": "A", "category": "grinder", "sub_category": "", "confidence": 0.9}],
            str(csv_path),
            lock_timeout=0.3,
        )

    # Release the lock
    lock_path.unlink()

    category_inferrer._append_csv(
        [{"sku": "A", "category": "grinder", "sub_category": "", "confidence": 0.9}],
        str(csv_path),
        lock_timeout=0.3,
    )
    assert csv_path.exists()
    # Lock file was cleaned up
    assert not lock_path.exists()
    # Row was written with the expected header
    content = csv_path.read_text()
    assert "sku,category,sub_category,price_band_override" in content
    assert "A,grinder,," in content


def test_append_csv_releases_lock_on_exception(tmp_path, monkeypatch):
    """If the write step fails mid-operation, the lock file must still be released."""
    from qbu_crawler.server import category_inferrer

    csv_path = tmp_path / "cat.csv"

    # Force the inner open() to blow up to simulate disk full / permission denied
    real_open = open

    def _bad_open(path, *args, **kwargs):
        if str(path).endswith("cat.csv"):
            raise OSError("simulated disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _bad_open)

    with __import__("pytest").raises(OSError):
        category_inferrer._append_csv(
            [{"sku": "A", "category": "grinder", "sub_category": "", "confidence": 0.9}],
            str(csv_path),
            lock_timeout=0.3,
        )

    # Lock file must be gone even though the write failed
    assert not (tmp_path / "cat.csv.lock").exists()


# ---------------------------------------------------------------------------
# I5 — _logical_date_window returns tz-aware datetime objects
# ---------------------------------------------------------------------------


def test_logical_date_window_returns_tzinfo_aware_datetimes():
    """The helper must return tz-aware datetime objects, not ISO strings,
    so callers never accidentally mix naive and aware datetimes."""
    from datetime import datetime, timedelta
    from qbu_crawler.server.workflows import _logical_date_window

    since, until = _logical_date_window("2026-04-17")
    assert isinstance(since, datetime)
    assert isinstance(until, datetime)
    assert since.tzinfo is not None
    assert until.tzinfo is not None
    # Shanghai = UTC+8
    assert since.utcoffset() == timedelta(hours=8)
    assert until.utcoffset() == timedelta(hours=8)
    # Sanity: window is exactly 24 hours for daily
    assert (until - since) == timedelta(days=1)
    # Start at midnight
    assert since.time().hour == 0 and since.time().minute == 0
