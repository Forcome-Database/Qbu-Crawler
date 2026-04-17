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
