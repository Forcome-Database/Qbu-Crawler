"""Tests for F011 §4.4.1 — internal ops alert evaluator + H13 deadletter phase downgrade."""

from __future__ import annotations

import sqlite3

import pytest

from qbu_crawler.server.notifier import (
    _evaluate_ops_alert_triggers,
    count_outbox_deadletter,
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


def test_failed_url_triggers_ops_alert():
    from qbu_crawler.server.notifier import _evaluate_ops_alert_triggers

    triggered, severity = _evaluate_ops_alert_triggers({
        "failed_url_count": 1,
        "scrape_completeness_ratio": 1.0,
    })

    assert triggered is True
    assert severity == "P1"


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
    """F011 H13 — outbox deadletter forces phase 'full_sent' → 'full_sent_local'.

    Critical B-2: payload is now produced via ``json.dumps`` (which inserts
    a space after the colon: ``"run_id": 42``) so we exercise the same
    serialization shape that ``models.enqueue_notification`` writes.
    The previous LIKE pattern ``%"run_id":42%`` (no space) silently never
    matched in production.
    """
    import json
    conn = sqlite3.connect(":memory:")
    _build_minimal_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workflow_runs (report_phase) VALUES (?)", ("full_sent",)
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES (?, ?)",
        ("deadletter", json.dumps({"run_id": run_id, "foo": "bar"})),
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
    import json
    conn = sqlite3.connect(":memory:")
    _build_minimal_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workflow_runs (report_phase) VALUES (?)", ("fast_sent",)
    )
    run_id = cur.lastrowid
    cur.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES (?, ?)",
        ("deadletter", json.dumps({"run_id": run_id})),
    )
    conn.commit()

    changed = downgrade_report_phase_on_deadletter(conn, run_id)
    assert changed is False


# ──────────────────────────────────────────────────────────────────────────
# F011 Critical B-2 — JSON_EXTRACT-based deadletter counting
# ──────────────────────────────────────────────────────────────────────────


def test_downgrade_no_prefix_collision_on_run_id_1_vs_10():
    """Critical B-2 — run_id=1's deadletter must NOT be confused with run_id=10
    (and vice versa). The legacy LIKE pattern ``%"run_id":1%`` would match
    the substring inside ``"run_id": 10`` / ``"run_id": 100`` etc."""
    import json
    conn = sqlite3.connect(":memory:")
    _build_minimal_schema(conn)
    cur = conn.cursor()
    # Two separate runs, both currently 'full_sent'
    cur.execute("INSERT INTO workflow_runs (id, report_phase) VALUES (1, 'full_sent')")
    cur.execute("INSERT INTO workflow_runs (id, report_phase) VALUES (10, 'full_sent')")
    # Only run_id=10 has a deadletter
    cur.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES (?, ?)",
        ("deadletter", json.dumps({"run_id": 10, "kind": "report"})),
    )
    conn.commit()

    # run_id=1 must see zero deadletters and remain 'full_sent'
    assert count_outbox_deadletter(conn, 1) == 0
    assert downgrade_report_phase_on_deadletter(conn, 1) is False
    phase_1 = conn.execute(
        "SELECT report_phase FROM workflow_runs WHERE id=1"
    ).fetchone()[0]
    assert phase_1 == "full_sent"

    # run_id=10 must correctly downgrade
    assert count_outbox_deadletter(conn, 10) == 1
    assert downgrade_report_phase_on_deadletter(conn, 10) is True
    phase_10 = conn.execute(
        "SELECT report_phase FROM workflow_runs WHERE id=10"
    ).fetchone()[0]
    assert phase_10 == "full_sent_local"


def test_downgrade_report_phase_via_real_enqueue_notification(tmp_path, monkeypatch):
    """Critical B-2 — wire through ``models.enqueue_notification`` so we use
    the production payload shape (``json.dumps`` with default whitespace).

    This is the regression test for the original bug: the LIKE pattern
    ``%"run_id":<id>%`` (no space) never matched ``"run_id": <id>`` (with
    space) and the phase downgrade silently never fired.
    """
    from qbu_crawler import config, models

    db = tmp_path / "ops.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()

    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO workflow_runs (workflow_type, status, logical_date, "
            "trigger_key, report_phase) VALUES "
            "('daily','running','2026-04-27','t:2026-04-27','full_sent')"
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Enqueue a deadletter the same way production does (json.dumps with
    # default separators → "run_id": <id> with whitespace).
    notif = {
        "kind": "daily_report",
        "channel": "dingtalk",
        "target": "ops",
        "payload": {"run_id": run_id, "subject": "test"},
        "dedupe_key": f"daily_report:{run_id}",
        "payload_hash": "fakehash",
        "status": "deadletter",
    }
    models.enqueue_notification(notif)

    with sqlite3.connect(str(db)) as conn:
        # Verify the helper sees the deadletter…
        assert count_outbox_deadletter(conn, run_id) == 1
        # …and the downgrade actually fires.
        changed = downgrade_report_phase_on_deadletter(conn, run_id)
        assert changed is True
        phase = conn.execute(
            "SELECT report_phase FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()[0]
        assert phase == "full_sent_local"
