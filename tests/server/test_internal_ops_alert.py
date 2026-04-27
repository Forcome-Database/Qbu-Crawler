"""Tests for F011 §4.4.1 — internal ops alert evaluator + H13 deadletter phase downgrade."""

from __future__ import annotations

import sqlite3

import pytest

from qbu_crawler.server.notifier import (
    _evaluate_ops_alert_triggers,
    downgrade_report_phase_on_deadletter,
)


# ──────────────────────────────────────────────────────────────────────────
# §4.4.1 — _evaluate_ops_alert_triggers
# ──────────────────────────────────────────────────────────────────────────


def test_zero_scrape_triggers_ops_alert():
    """F011 §4.4.1 — zero_scrape_skus 非空必须触发 P0."""
    quality = {"zero_scrape_skus": ["SKU_X"], "scrape_completeness_ratio": 0.95}
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P0"


def test_low_completeness_triggers_p1():
    quality = {"zero_scrape_skus": [], "scrape_completeness_ratio": 0.5}
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P1"


def test_high_estimated_dates_triggers_p2():
    quality = {
        "zero_scrape_skus": [],
        "scrape_completeness_ratio": 1.0,
        "estimated_date_ratio": 0.4,
    }
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P2"


def test_no_alert_when_clean():
    quality = {"zero_scrape_skus": [], "scrape_completeness_ratio": 1.0}
    triggered, _ = _evaluate_ops_alert_triggers(quality)
    assert triggered is False


def test_max_severity_wins_when_multiple():
    """P0 takes precedence over P1/P2 when multiple triggers fire."""
    quality = {
        "zero_scrape_skus": ["X"],
        "scrape_completeness_ratio": 0.5,
        "outbox_deadletter_count": 5,
    }
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P0"


def test_outbox_deadletter_triggers_p1():
    quality = {
        "zero_scrape_skus": [],
        "scrape_completeness_ratio": 1.0,
        "outbox_deadletter_count": 3,
    }
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P1"


# ──────────────────────────────────────────────────────────────────────────
# §H13 — downgrade_report_phase_on_deadletter
# ──────────────────────────────────────────────────────────────────────────


def _build_minimal_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_phase TEXT NOT NULL DEFAULT 'none'
        );
        CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'pending',
            payload TEXT NOT NULL
        );
        """
    )


def test_downgrade_report_phase_on_deadletter():
    """F011 H13 — outbox deadletter forces phase 'full_sent' → 'full_sent_local'."""
    conn = sqlite3.connect(":memory:")
    _build_minimal_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workflow_runs (report_phase) VALUES (?)", ("full_sent",)
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES (?, ?)",
        ("deadletter", f'{{"run_id":{run_id},"foo":"bar"}}'),
    )
    conn.commit()

    changed = downgrade_report_phase_on_deadletter(conn, run_id)
    assert changed is True
    phase = conn.execute(
        "SELECT report_phase FROM workflow_runs WHERE id=?", (run_id,)
    ).fetchone()[0]
    assert phase == "full_sent_local"


def test_downgrade_no_op_when_no_deadletter():
    conn = sqlite3.connect(":memory:")
    _build_minimal_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workflow_runs (report_phase) VALUES (?)", ("full_sent",)
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES (?, ?)",
        ("delivered", f'{{"run_id":{run_id}}}'),
    )
    conn.commit()

    changed = downgrade_report_phase_on_deadletter(conn, run_id)
    assert changed is False
    phase = conn.execute(
        "SELECT report_phase FROM workflow_runs WHERE id=?", (run_id,)
    ).fetchone()[0]
    assert phase == "full_sent"


def test_downgrade_no_op_when_phase_not_full_sent():
    """Only 'full_sent' is downgraded — earlier phases stay put."""
    conn = sqlite3.connect(":memory:")
    _build_minimal_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workflow_runs (report_phase) VALUES (?)", ("fast_sent",)
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES (?, ?)",
        ("deadletter", f'{{"run_id":{run_id}}}'),
    )
    conn.commit()

    changed = downgrade_report_phase_on_deadletter(conn, run_id)
    assert changed is False
