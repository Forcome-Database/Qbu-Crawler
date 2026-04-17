"""Call business report pipeline bypassing scheduler workers.

Strategy (Approach Y — proper __init__):
    WorkflowWorker.__init__ only constructs Event/Thread objects; the thread
    is NOT started until .start() is called. We instantiate normally and
    invoke the private _advance_run method directly, never touching .start().

Daily runs require at least one linked workflow_run_tasks row (the daily
advance path bails out on empty task_rows). We synthesise one completed
``scrape`` task per daily call so the advance loop treats the run as having
"all tasks completed" and proceeds to reporting.

Weekly/monthly runs go through submit_weekly_run / submit_monthly_run which
write a workflow_runs row with status='reporting' directly — no tasks needed.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

from .clock import frozen_today
from .env_bootstrap import load_business


TERMINAL = {"completed", "needs_attention", "failed"}


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _make_worker():
    biz = load_business()
    # Approach Y: proper ctor is safe — thread only starts on .start().
    return biz.workflows.WorkflowWorker()


def _final_status(run_id: int) -> str:
    biz = load_business()
    conn = biz.models.get_conn()
    try:
        row = conn.execute(
            "SELECT status FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else "unknown"


def _advance_until_terminal(worker, run_id: int, *, max_iters: int = 40) -> str:
    """Drive worker._advance_run(run_id, now) until the run reaches a terminal
    status or the advance loop stops reporting changes.

    Returns the final status.
    """
    for _ in range(max_iters):
        now_iso = datetime.now().isoformat(timespec="seconds")
        changed = worker._advance_run(run_id, now_iso)
        status = _final_status(run_id)
        if status in TERMINAL:
            return status
        if not changed:
            break
    return _final_status(run_id)


def _ensure_daily_task_link(run_id: int, logical_date: date) -> str:
    """Create a synthetic completed task + workflow_run_tasks link so the
    daily advance path sees task_rows and proceeds to reporting.

    Returns the task id.
    """
    biz = load_business()
    task_id = uuid.uuid4().hex
    params = json.dumps({"source": "simulator", "logical_date": logical_date.isoformat()})
    result = json.dumps({"reviews_saved": 0, "source": "simulator"})
    now_ts = datetime.now().isoformat(timespec="seconds")

    conn = biz.models.get_conn()
    try:
        conn.execute(
            """INSERT INTO tasks (id, type, status, params, result,
                                  created_at, updated_at, started_at, finished_at)
               VALUES (?, 'scrape', 'completed', ?, ?, ?, ?, ?, ?)""",
            (task_id, params, result, now_ts, now_ts, now_ts, now_ts),
        )
        conn.execute(
            """INSERT INTO workflow_run_tasks (run_id, task_id, task_type, site, ownership)
               VALUES (?, ?, 'scrape', 'basspro', 'own')""",
            (run_id, task_id),
        )
        conn.commit()
    finally:
        conn.close()
    return task_id


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def call_daily(logical_date: date) -> int:
    """Create a daily workflow_runs row, seed a completed task link, then
    drive _advance_run until terminal. Returns the workflow_runs.id."""
    biz = load_business()

    data_since = f"{logical_date.isoformat()}T00:00:00+08:00"
    data_until = f"{(logical_date + timedelta(days=1)).isoformat()}T00:00:00+08:00"
    trigger_key = f"sim-daily:{logical_date.isoformat()}:{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now().isoformat(timespec="seconds")

    run = biz.models.create_workflow_run({
        "workflow_type": "daily",
        "report_tier": "daily",
        "status": "running",          # bypass submitted; advance flips to reporting
        "report_phase": "none",
        "logical_date": logical_date.isoformat(),
        "trigger_key": trigger_key,
        "data_since": data_since,
        "data_until": data_until,
        "requested_by": "simulator",
        "service_version": "sim",
        "started_at": now_iso,
    })
    run_id = run["id"]

    _ensure_daily_task_link(run_id, logical_date)

    worker = _make_worker()
    with frozen_today(logical_date):
        _advance_until_terminal(worker, run_id)
    return run_id


def call_weekly(logical_date: date) -> int:
    biz = load_business()
    with frozen_today(logical_date):
        result = biz.workflows.submit_weekly_run(
            logical_date=logical_date.isoformat()
        )
        run_id = result["run"]["id"]
        worker = _make_worker()
        _advance_until_terminal(worker, run_id)
    return run_id


def call_monthly(logical_date: date) -> int:
    biz = load_business()
    with frozen_today(logical_date):
        result = biz.workflows.submit_monthly_run(
            logical_date=logical_date.isoformat()
        )
        run_id = result["run"]["id"]
        worker = _make_worker()
        _advance_until_terminal(worker, run_id)
    return run_id
