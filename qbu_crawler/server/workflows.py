"""Workflow orchestration helpers for deterministic daily automation."""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

from qbu_crawler import __version__, config, models
from qbu_crawler.server.daily_inputs import load_daily_inputs
from qbu_crawler.server.report_snapshot import (
    build_fast_report,
    freeze_report_snapshot,
    generate_full_report_from_snapshot,
    load_report_snapshot,
)

logger = logging.getLogger(__name__)


class LocalHttpTaskSubmitter:
    """Submit tasks into the long-running crawler service over loopback HTTP."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self._base_url = (base_url or config.LOCAL_API_BASE_URL).rstrip("/")
        self._api_key = api_key or config.API_KEY

    def submit_collect(self, category_url: str, ownership: str, max_pages: int = 0, reply_to: str = ""):
        return self._post(
            "/api/tasks/collect",
            {
                "category_url": category_url,
                "max_pages": max_pages,
                "ownership": ownership,
                "reply_to": reply_to,
            },
        )

    def submit_scrape(self, urls: list[str], ownership: str, reply_to: str = ""):
        return self._post(
            "/api/tasks/scrape",
            {
                "urls": urls,
                "ownership": ownership,
                "reply_to": reply_to,
            },
        )

    def _post(self, path: str, payload: dict) -> SimpleNamespace:
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                **({"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
        return SimpleNamespace(id=body["task_id"], status=body.get("status"))


def build_daily_trigger_key(logical_date: str) -> str:
    return f"daily:{logical_date}"


def submit_daily_run(
    submitter: Any,
    source_csv: str,
    detail_csv: str,
    logical_date: str | None = None,
    requested_by: str = "cli",
    dry_run: bool = False,
    notification_target: str | None = None,
) -> dict:
    """Create or reuse a daily workflow run, then submit tasks deterministically."""
    logical_date = logical_date or date.today().isoformat()
    trigger_key = build_daily_trigger_key(logical_date)
    notification_target = notification_target or config.WORKFLOW_NOTIFICATION_TARGET

    existing = models.get_workflow_run_by_trigger_key(trigger_key)
    if existing:
        return {"created": False, "run": existing, "trigger_key": trigger_key}

    bundle = load_daily_inputs(source_csv, detail_csv)
    if dry_run:
        return {
            "created": False,
            "dry_run": True,
            "trigger_key": trigger_key,
            "logical_date": logical_date,
            "summary": bundle.summary,
        }

    data_since, data_until = _logical_date_window(logical_date)
    run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "submitted",
            "logical_date": logical_date,
            "trigger_key": trigger_key,
            "data_since": data_since,
            "data_until": data_until,
            "requested_by": requested_by,
            "service_version": __version__,
        }
    )

    collect_task_ids: list[str] = []
    scrape_task_ids: list[str] = []

    for request in bundle.collect_requests:
        task = submitter.submit_collect(
            request.category_url,
            ownership=request.ownership,
            max_pages=request.max_pages,
            reply_to="",
        )
        collect_task_ids.append(task.id)
        models.attach_task_to_workflow(
            run_id=run["id"],
            task_id=task.id,
            task_type="collect",
            site=request.site,
            ownership=request.ownership,
        )

    for request in bundle.scrape_requests:
        task = submitter.submit_scrape(
            request.urls,
            ownership=request.ownership,
            reply_to="",
        )
        scrape_task_ids.append(task.id)
        models.attach_task_to_workflow(
            run_id=run["id"],
            task_id=task.id,
            task_type="scrape",
            site=request.site,
            ownership=request.ownership,
        )

    payload = {
        "run_id": run["id"],
        "logical_date": logical_date,
        "collect_task_ids": collect_task_ids,
        "scrape_task_ids": scrape_task_ids,
        "summary": bundle.summary,
    }
    payload_hash = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    models.enqueue_notification(
        {
            "kind": "workflow_started",
            "channel": "dingtalk",
            "target": notification_target,
            "payload": payload,
            "dedupe_key": f"workflow:{run['id']}:started",
            "payload_hash": payload_hash,
        }
    )

    return {
        "created": True,
        "run": models.get_workflow_run_by_trigger_key(trigger_key),
        "trigger_key": trigger_key,
        "collect_task_ids": collect_task_ids,
        "scrape_task_ids": scrape_task_ids,
    }


def _logical_date_window(logical_date: str) -> tuple[str, str]:
    start = datetime.fromisoformat(logical_date)
    end = start + timedelta(days=1)
    return (f"{start.date().isoformat()}T00:00:00+08:00", f"{end.date().isoformat()}T00:00:00+08:00")


class WorkflowWorker:
    """Reconcile stale tasks and advance workflow runs to completion."""

    _ACTIVE_STATUSES = ("submitted", "running", "reporting")

    def __init__(self, interval: int | None = None, task_stale_seconds: int | None = None):
        self._interval = interval or config.WORKFLOW_INTERVAL
        self._task_stale_seconds = task_stale_seconds or config.TASK_STALE_SECONDS
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="workflow-worker")

    def start(self):
        self._thread.start()
        logger.info(
            "WorkflowWorker: started (interval=%ds, task_stale_seconds=%ds)",
            self._interval,
            self._task_stale_seconds,
        )

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def trigger(self):
        self._wake_event.set()

    def process_once(self, now: str | None = None) -> bool:
        now = now or config.now_shanghai().isoformat()
        changed = self._reconcile_stale_tasks(now) > 0

        for run in models.list_workflow_runs(statuses=list(self._ACTIVE_STATUSES)):
            if self._advance_run(run["id"], now):
                changed = True
        return changed

    def _run(self):
        while not self._stop_event.is_set():
            self._wake_event.clear()
            self._wake_event.wait(timeout=self._interval)
            if self._stop_event.is_set():
                break
            try:
                while self.process_once() and not self._stop_event.is_set():
                    continue
            except Exception:
                logger.exception("WorkflowWorker: unexpected error")

    def _reconcile_stale_tasks(self, now: str) -> int:
        stale_before = _minus_seconds(now, self._task_stale_seconds)
        updated = 0
        for task in models.list_stale_running_tasks(stale_before):
            if models.mark_task_lost(
                task["id"],
                error_code="worker_lost",
                error_message="Task worker heartbeat expired",
                finished_at=now,
            ):
                updated += 1
        return updated

    def _advance_run(self, run_id: int, now: str) -> bool:
        run = models.get_workflow_run(run_id)
        if run is None:
            return False

        task_rows = models.list_workflow_run_tasks(run_id)
        if not task_rows:
            return False

        statuses = {row["status"] for row in task_rows}
        if statuses & {"pending", "running"}:
            if run["status"] != "running":
                models.update_workflow_run(
                    run_id,
                    status="running",
                    started_at=run.get("started_at") or now,
                    error=None,
                )
                return True
            return False

        if statuses & {"failed", "cancelled"}:
            self._move_run_to_attention(run, now, "One or more workflow tasks failed")
            return True

        changed = False
        if run["status"] != "reporting":
            run = models.update_workflow_run(
                run_id,
                status="reporting",
                started_at=run.get("started_at") or now,
                error=None,
            )
            changed = True

        if not run.get("snapshot_path"):
            run = freeze_report_snapshot(run_id, now=now)
            changed = True

        if run.get("report_phase") == "none":
            run = models.update_workflow_run(run_id, report_phase="fast_pending")
            changed = True

        if run.get("report_phase") == "fast_pending":
            snapshot = load_report_snapshot(run["snapshot_path"])
            fast_report = build_fast_report(snapshot)
            _enqueue_workflow_notification(
                kind="workflow_fast_report",
                target=config.WORKFLOW_NOTIFICATION_TARGET,
                payload={**fast_report, "logical_date": run["logical_date"]},
                dedupe_key=f"workflow:{run_id}:fast-report",
            )
            run = models.update_workflow_run(run_id, report_phase="fast_sent")
            changed = True

        if run.get("report_phase") == "fast_sent":
            run = models.update_workflow_run(run_id, report_phase="full_pending")
            changed = True

        if run.get("report_phase") == "full_pending":
            try:
                snapshot = load_report_snapshot(run["snapshot_path"])
                full_report = generate_full_report_from_snapshot(snapshot, send_email=True)
            except Exception as exc:
                self._move_run_to_attention(run, now, str(exc), report_phase="fast_sent")
                return True

            _enqueue_workflow_notification(
                kind="workflow_full_report",
                target=config.WORKFLOW_NOTIFICATION_TARGET,
                payload={
                    "run_id": run_id,
                    "logical_date": run["logical_date"],
                    "snapshot_hash": full_report["snapshot_hash"],
                    "excel_path": full_report["excel_path"],
                    "email_status": "success" if (full_report.get("email") or {}).get("success") else "failed",
                },
                dedupe_key=f"workflow:{run_id}:full-report",
            )
            models.update_workflow_run(
                run_id,
                status="completed",
                report_phase="full_sent",
                excel_path=full_report["excel_path"],
                finished_at=now,
                error=None,
            )
            _maybe_trigger_ai_digest(run_id, run, snapshot, full_report)
            return True

        return changed

    def _move_run_to_attention(
        self,
        run: dict,
        now: str,
        error_message: str,
        report_phase: str | None = None,
    ):
        updated = models.update_workflow_run(
            run["id"],
            status="needs_attention",
            report_phase=report_phase or run.get("report_phase", "none"),
            finished_at=now,
            error=error_message,
        )
        _enqueue_workflow_notification(
            kind="workflow_attention",
            target=config.WORKFLOW_NOTIFICATION_TARGET,
            payload={
                "run_id": run["id"],
                "logical_date": run["logical_date"],
                "reason": error_message,
            },
            dedupe_key=f"workflow:{run['id']}:attention:{updated['report_phase']}",
        )


def _enqueue_workflow_notification(kind: str, target: str, payload: dict, dedupe_key: str):
    payload_hash = hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    models.enqueue_notification(
        {
            "kind": kind,
            "channel": "dingtalk",
            "target": target,
            "payload": payload,
            "dedupe_key": dedupe_key,
            "payload_hash": payload_hash,
        }
    )


def _maybe_trigger_ai_digest(run_id: int, run: dict, snapshot: dict, full_report: dict):
    if config.AI_DIGEST_MODE != "async":
        return
    if not config.OPENCLAW_HOOK_URL:
        return

    prompt = (
        "请基于以下固定日报快照做简短业务摘要，不要触发任何工具。\n"
        f"run_id={run_id}\n"
        f"logical_date={run['logical_date']}\n"
        f"snapshot_hash={snapshot['snapshot_hash']}\n"
        f"products_count={snapshot['products_count']}\n"
        f"reviews_count={snapshot['reviews_count']}\n"
        f"translated_count={snapshot['translated_count']}\n"
        f"excel_path={full_report['excel_path']}"
    )
    base = config.OPENCLAW_HOOK_URL.rstrip("/").removesuffix("/hooks/wake").removesuffix("/hooks/agent")
    request = urllib.request.Request(
        url=f"{base}/hooks/agent",
        data=json.dumps(
            {
                "message": prompt,
                "deliver": True,
                "channel": "dingtalk",
                "to": config.WORKFLOW_NOTIFICATION_TARGET,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            **({"Authorization": f"Bearer {config.OPENCLAW_HOOK_TOKEN}"} if config.OPENCLAW_HOOK_TOKEN else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            return
    except Exception:
        logger.exception("WorkflowWorker: AI digest sidecar trigger failed for run %s", run_id)


def _minus_seconds(ts: str, seconds: int) -> str:
    dt = datetime.fromisoformat(ts)
    return (dt - timedelta(seconds=seconds)).isoformat()
