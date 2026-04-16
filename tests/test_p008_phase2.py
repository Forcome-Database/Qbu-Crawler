"""P008 Phase 2 — daily briefing refactor + infrastructure."""

from __future__ import annotations

import json
import sqlite3

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
    db_file = str(tmp_path / "p008p2.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: report_tier column ──────────────────────────────────


def test_workflow_runs_has_report_tier_column(db):
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
    assert "report_tier" in cols
    conn.close()


def test_report_tier_default_is_null(db):
    """Old runs without explicit report_tier should be NULL (stay on old path)."""
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'test:2026-04-17')"
    )
    conn.commit()
    row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = 1").fetchone()
    assert row["report_tier"] is None
    conn.close()


def test_update_workflow_run_accepts_report_tier(db):
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'test:2026-04-17')"
    )
    conn.commit()
    conn.close()
    result = models.update_workflow_run(1, report_tier="weekly")
    assert result["report_tier"] == "weekly"


# ── Task 2: Config ──────────────────────────────────────────────


def test_email_recipients_exec_defaults_empty(monkeypatch):
    monkeypatch.delenv("EMAIL_RECIPIENTS_EXEC", raising=False)
    from qbu_crawler import config as cfg
    monkeypatch.setattr(cfg, "EMAIL_RECIPIENTS_EXEC", [])
    assert cfg.EMAIL_RECIPIENTS_EXEC == []


def test_tier_configs_has_daily():
    from qbu_crawler.config import TIER_CONFIGS
    assert "daily" in TIER_CONFIGS
    daily = TIER_CONFIGS["daily"]
    assert daily["window"] == "24h"
    assert daily["cumulative"] is True
    assert daily["excel"] is False
    assert "attention_signals" in daily["dimensions"]


from datetime import date

# ── Task 3: tier_date_window ────────────────────────────────────


def test_tier_date_window_daily():
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("daily", "2026-04-17")
    assert since == "2026-04-17T00:00:00+08:00"
    assert until == "2026-04-18T00:00:00+08:00"


def test_tier_date_window_weekly():
    from qbu_crawler.server.report_common import tier_date_window
    # 2026-04-20 is a Monday
    since, until = tier_date_window("weekly", "2026-04-20")
    assert since == "2026-04-13T00:00:00+08:00"  # previous Monday
    assert until == "2026-04-20T00:00:00+08:00"  # this Monday


def test_tier_date_window_monthly():
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("monthly", "2026-05-01")
    assert since == "2026-04-01T00:00:00+08:00"
    assert until == "2026-05-01T00:00:00+08:00"
