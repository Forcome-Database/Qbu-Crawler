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
