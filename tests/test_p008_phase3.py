"""P008 Phase 3 — weekly report."""

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
    db_file = str(tmp_path / "p008p3.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: Config + trigger key ────────────────────────────────


def test_weekly_scheduler_time_config():
    assert hasattr(config, "WEEKLY_SCHEDULER_TIME")
    assert ":" in config.WEEKLY_SCHEDULER_TIME


def test_build_weekly_trigger_key():
    from qbu_crawler.server.workflows import build_weekly_trigger_key
    key = build_weekly_trigger_key("2026-04-20")
    assert key == "weekly:2026-04-20"


# ── Task 2: get_previous_completed_run(report_tier=) ────────────


def test_get_previous_completed_run_filters_by_tier(db):
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '/tmp/daily.json')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-14',"
        " 'weekly:2026-04-14', 'weekly', '/tmp/weekly.json')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'weekly', 'reporting', 'none', '2026-04-21',"
        " 'weekly:2026-04-21', 'weekly')"
    )
    conn.commit()
    conn.close()

    prev = models.get_previous_completed_run(3)
    assert prev is not None
    assert prev["id"] == 2

    prev_weekly = models.get_previous_completed_run(3, report_tier="weekly")
    assert prev_weekly is not None
    assert prev_weekly["id"] == 2

    prev_daily = models.get_previous_completed_run(3, report_tier="daily")
    assert prev_daily is not None
    assert prev_daily["id"] == 1
