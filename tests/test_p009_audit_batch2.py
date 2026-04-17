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
