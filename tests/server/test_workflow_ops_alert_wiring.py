"""F011 Critical A-3 — wiring tests for workflows.py:
  * `_evaluate_ops_alert_triggers` (P0/P1/P2 evaluator) replaces legacy
    `should_raise_alert` in the data-quality alert path.
  * `downgrade_report_phase_on_deadletter` is invoked from the WorkflowWorker
    main loop after a run reaches `full_sent`.

These tests touch the *integration* (call-site wiring) only — the individual
unit behaviour of `_evaluate_ops_alert_triggers` and
`downgrade_report_phase_on_deadletter` is covered by
`tests/server/test_internal_ops_alert.py`.
"""

from __future__ import annotations


def _seed_workflow_run(conn, *, logical_date="2026-04-27",
                        report_phase="none", status="reporting",
                        trigger_key="test:trigger:1"):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO workflow_runs (
            workflow_type, logical_date, status, report_phase, trigger_key,
            snapshot_path
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("daily", logical_date, status, report_phase, trigger_key,
         "/tmp/fake-snapshot.json"),
    )
    return cur.lastrowid


def _seed_completed_task(conn, run_id):
    """Insert a completed `tasks` row + its workflow_run_tasks link."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tasks (id, type, status, params, finished_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"t-{run_id}", "scrape", "completed", "{}", "2026-04-27T00:00:00"),
    )
    cur.execute(
        """
        INSERT INTO workflow_run_tasks (run_id, task_id, task_type, site, ownership)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, f"t-{run_id}", "scrape", "basspro", "own"),
    )


# ──────────────────────────────────────────────────────────────────────────
# A-3 (1/2) — workflow wires _evaluate_ops_alert_triggers
# ──────────────────────────────────────────────────────────────────────────


def test_workflow_ops_alert_uses_p0_p1_p2_evaluator(tmp_path, monkeypatch):
    """zero_scrape_skus must trigger P0 via the new evaluator and the P0
    severity must reach _send_data_quality_alert."""
    from qbu_crawler import config, models
    from qbu_crawler.server import workflows

    db = tmp_path / "ops-alert.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(config, "SCRAPE_QUALITY_ALERT_RATIO", 0.10)
    monkeypatch.setattr(
        config, "SCRAPE_QUALITY_ALERT_RECIPIENTS", ["ops@example.com"]
    )
    models.init_db()

    conn = models.get_conn()
    try:
        run_id = _seed_workflow_run(conn, trigger_key="ops:1")
        _seed_completed_task(conn, run_id)
        conn.commit()
    finally:
        conn.close()

    # Snapshot with one product whose review_count > 0 but ingested_count == 0
    # ⇒ summarize_scrape_quality.zero_scrape_skus = ["SKU-X"] ⇒ P0.
    snapshot = {
        "logical_date": "2026-04-27",
        "products": [
            {"sku": "SKU-X", "review_count": 50, "ingested_count": 0,
             "rating": 4.5, "stock_status": "in_stock"}
        ],
        "reviews": [],
    }
    monkeypatch.setattr(workflows, "load_report_snapshot", lambda path: snapshot)
    monkeypatch.setattr(workflows, "_count_pending_translations_for_window",
                        lambda *a, **k: 0)

    captured = {"alert_called": False}

    def spy_alert(*, run_id, logical_date, quality, severity="", log_path=None):
        captured["alert_called"] = True
        captured["severity"] = severity
        captured["quality"] = quality
        captured["log_path"] = log_path
        # Short-circuit the rest of _advance_run via the outer except.
        raise RuntimeError("__short_circuit__")

    monkeypatch.setattr(workflows, "_send_data_quality_alert", spy_alert)

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    try:
        worker._advance_run(run_id, "2026-04-27T01:00:00")
    except Exception:
        # Expected — spy_alert raises to stop further pipeline work.
        pass

    assert captured["alert_called"] is True, (
        "_advance_run must call _send_data_quality_alert when the "
        "P0/P1/P2 evaluator reports triggered=True"
    )
    assert captured["severity"] == "P0", (
        f"zero_scrape_skus must yield P0 severity; got {captured.get('severity')!r}"
    )


# ──────────────────────────────────────────────────────────────────────────
# A-3 (2/2) — workflow wires downgrade_report_phase_on_deadletter
# ──────────────────────────────────────────────────────────────────────────


def test_workflow_calls_downgrade_after_full_sent_with_deadletter(tmp_path, monkeypatch):
    """When a run is at `full_sent` and the outbox has a matching deadletter
    row, _advance_run must invoke downgrade_report_phase_on_deadletter and
    the run's report_phase must transition to `full_sent_local`."""
    from qbu_crawler import config, models
    from qbu_crawler.server import workflows

    db = tmp_path / "downgrade.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()

    conn = models.get_conn()
    try:
        run_id = _seed_workflow_run(
            conn, status="completed", report_phase="full_sent",
            trigger_key="dl:1",
        )
        _seed_completed_task(conn, run_id)
        # Outbox row for this run, in deadletter, with the canonical
        # `"run_id": <id>` payload shape (json.dumps default spacing) —
        # synced with notifier.downgrade_report_phase_on_deadletter and
        # with Group B's SQL LIKE fix.
        conn.execute(
            """
            INSERT INTO notification_outbox (
                kind, channel, target, payload, dedupe_key, payload_hash,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "workflow_full_report",
                "dingtalk",
                "ops",
                f'{{"run_id": {run_id}, "msg": "boom"}}',
                f"workflow:{run_id}:full-report",
                "hash",
                "deadletter",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Stop work after the downgrade by short-circuiting downstream blocks.
    monkeypatch.setattr(workflows, "_count_pending_translations_for_window",
                        lambda *a, **k: 0)
    # Skip the data-quality alert block.
    monkeypatch.setattr(workflows.models, "get_scrape_quality",
                        lambda rid: {"total": 0})
    # If we reach the report_phase routing, bail out cleanly.
    monkeypatch.setattr(workflows, "load_report_snapshot",
                        lambda path: {"reviews_count": 0,
                                       "logical_date": "2026-04-27"})

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    try:
        worker._advance_run(run_id, "2026-04-27T03:00:00")
    except Exception:
        pass

    phase = models.get_workflow_run(run_id)["report_phase"]
    assert phase == "full_sent_local", (
        f"Expected report_phase to downgrade to 'full_sent_local' after "
        f"deadletter detection; got {phase!r}."
    )


def test_process_once_reconciles_completed_full_sent_deadletter(tmp_path, monkeypatch):
    """主循环必须扫描 completed/full_sent，否则终态 run 的 deadletter 永远不会降级。"""
    from qbu_crawler import config, models
    from qbu_crawler.server import workflows

    db = tmp_path / "downgrade-loop.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()

    conn = models.get_conn()
    try:
        run_id = _seed_workflow_run(
            conn, status="completed", report_phase="full_sent",
            trigger_key="dl-loop:1",
        )
        conn.execute(
            """
            INSERT INTO notification_outbox (
                kind, channel, target, payload, dedupe_key, payload_hash, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "workflow_full_report",
                "dingtalk",
                "ops",
                f'{{"run_id": {run_id}, "msg": "boom"}}',
                f"workflow:{run_id}:full-report",
                "hash",
                "deadletter",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    worker = workflows.WorkflowWorker(interval=999)

    changed = worker.process_once("2026-04-27T04:00:00")

    assert changed is True
    assert models.get_workflow_run(run_id)["report_phase"] == "full_sent_local"
