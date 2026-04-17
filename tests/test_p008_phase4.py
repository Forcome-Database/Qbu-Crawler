"""P008 Phase 4 — monthly report."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "p008p4.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: Config + trigger key ────────────────────────────────


def test_monthly_scheduler_time_config():
    assert hasattr(config, "MONTHLY_SCHEDULER_TIME")
    assert ":" in config.MONTHLY_SCHEDULER_TIME  # HH:MM


def test_category_map_path_config():
    assert hasattr(config, "CATEGORY_MAP_PATH")
    assert config.CATEGORY_MAP_PATH.endswith("category_map.csv")


def test_build_monthly_trigger_key():
    from qbu_crawler.server.workflows import build_monthly_trigger_key
    key = build_monthly_trigger_key("2026-05-01")
    assert key == "monthly:2026-05-01"


# ── Task 2: submit_monthly_run ──────────────────────────────────


def test_submit_monthly_run_creates_reporting_run(db):
    from qbu_crawler.server.workflows import submit_monthly_run
    result = submit_monthly_run(logical_date="2026-05-01")
    assert result["created"] is True
    assert result["trigger_key"] == "monthly:2026-05-01"

    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["workflow_type"] == "monthly"
    assert row["report_tier"] == "monthly"
    assert row["status"] == "reporting"
    assert row["data_since"] == "2026-04-01T00:00:00+08:00"
    assert row["data_until"] == "2026-05-01T00:00:00+08:00"


def test_submit_monthly_run_idempotent(db):
    from qbu_crawler.server.workflows import submit_monthly_run
    r1 = submit_monthly_run(logical_date="2026-05-01")
    r2 = submit_monthly_run(logical_date="2026-05-01")
    assert r1["created"] is True
    assert r2["created"] is False


def test_submit_monthly_run_january_wraps_to_december(db):
    """Window for 2026-01-01 must be [2025-12-01, 2026-01-01)."""
    from qbu_crawler.server.workflows import submit_monthly_run
    result = submit_monthly_run(logical_date="2026-01-01")
    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["data_since"] == "2025-12-01T00:00:00+08:00"
    assert row["data_until"] == "2026-01-01T00:00:00+08:00"
