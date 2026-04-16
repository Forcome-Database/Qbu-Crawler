"""P008 Phase 1 — safety_incidents, busy_timeout, label_anomaly_flags, three-tier safety."""

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
    db_file = str(tmp_path / "p008.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── busy_timeout ──────────────────────────────────────────────


def test_busy_timeout_is_set(tmp_path, monkeypatch):
    """get_conn() must set PRAGMA busy_timeout >= 5000."""
    db_file = str(tmp_path / "timeout.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    # Call the REAL get_conn (not the monkeypatched one used by the db fixture)
    conn = models.get_conn()
    row = conn.execute("PRAGMA busy_timeout").fetchone()
    assert row[0] >= 5000, f"busy_timeout too low: {row[0]}"
    conn.close()


# ── safety_incidents table ────────────────────────────────────


def test_safety_incidents_table_exists(db):
    """init_db() must create the safety_incidents table."""
    conn = sqlite3.connect(db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "safety_incidents" in tables
    conn.close()


def test_safety_incidents_columns(db):
    """safety_incidents must have all expected columns."""
    conn = sqlite3.connect(db)
    info = conn.execute("PRAGMA table_info(safety_incidents)").fetchall()
    columns = {r[1] for r in info}
    expected = {
        "id",
        "review_id",
        "product_sku",
        "safety_level",
        "failure_mode",
        "evidence_snapshot",
        "evidence_hash",
        "detected_at",
        "created_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"
    conn.close()


# ── label_anomaly_flags column ────────────────────────────────


def test_review_analysis_has_label_anomaly_flags(db):
    """review_analysis must include the label_anomaly_flags column."""
    conn = sqlite3.connect(db)
    info = conn.execute("PRAGMA table_info(review_analysis)").fetchall()
    columns = {r[1] for r in info}
    assert "label_anomaly_flags" in columns
    conn.close()


# ── Three-tier safety grading (Task 2) ──────────────────────────


def test_load_safety_tiers_from_json(tmp_path):
    cfg = {"critical": ["metal shaving"], "high": ["rust"], "moderate": ["loose screw"]}
    path = tmp_path / "tiers.json"
    path.write_text(json.dumps(cfg))
    from qbu_crawler.server.report_common import load_safety_tiers
    tiers = load_safety_tiers(str(path))
    assert tiers["critical"] == ["metal shaving"]
    assert tiers["high"] == ["rust"]


def test_load_safety_tiers_fallback():
    """Non-existent path falls back to built-in defaults."""
    from qbu_crawler.server.report_common import load_safety_tiers
    tiers = load_safety_tiers("/nonexistent/path.json")
    assert "critical" in tiers
    assert len(tiers["critical"]) > 0


def test_detect_safety_level_critical():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Found metal shaving in my ground beef") == "critical"


def test_detect_safety_level_high():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("The blade is rusty after 2 months") == "high"


def test_detect_safety_level_moderate():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Motor housing is misaligned with the body") == "moderate"


def test_detect_safety_level_none():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Great product, works perfectly") is None


def test_detect_safety_level_returns_highest():
    """When multiple tiers match, return the highest."""
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Rusty blade caused injury to my hand") == "critical"
