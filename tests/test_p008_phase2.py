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
