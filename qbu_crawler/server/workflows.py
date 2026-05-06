"""Workflow orchestration helpers for deterministic daily automation."""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from ipaddress import ip_address
from pathlib import Path
from datetime import date, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

from qbu_crawler import __version__, config, models
from qbu_crawler.server.daily_digest import build_daily_digest
from qbu_crawler.server.daily_inputs import load_daily_inputs
from qbu_crawler.server.report_snapshot import (
    FullReportGenerationError,
    build_fast_report,
    build_windowed_report_snapshot,
    freeze_report_snapshot,
    generate_report_from_snapshot,
    load_report_snapshot,
)
from qbu_crawler.server.report_cadence import decide_business_email

logger = logging.getLogger(__name__)


class LocalHttpTaskSubmitter:
    """Submit tasks into the long-running crawler service over loopback HTTP."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self._base_url = (base_url or config.LOCAL_API_BASE_URL).rstrip("/")
        self._api_key = api_key or config.API_KEY

    def submit_collect(
        self,
        category_url: str,
        ownership: str,
        max_pages: int = 0,
        review_limit: int = 0,
        reply_to: str = "",
    ):
        return self._post(
            "/api/tasks/collect",
            {
                "category_url": category_url,
                "max_pages": max_pages,
                "review_limit": review_limit,
                "ownership": ownership,
                "reply_to": reply_to,
            },
        )

    def submit_scrape(self, urls: list[str], ownership: str, review_limit: int = 0, reply_to: str = ""):
        return self._post(
            "/api/tasks/scrape",
            {
                "urls": urls,
                "ownership": ownership,
                "review_limit": review_limit,
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


class InProcessTaskSubmitter:
    """Submit tasks directly into the in-process TaskManager."""

    def __init__(self, task_manager: Any):
        self._task_manager = task_manager

    def submit_collect(
        self,
        category_url: str,
        ownership: str,
        max_pages: int = 0,
        review_limit: int = 0,
        reply_to: str = "",
    ):
        task = self._task_manager.submit_collect(
            category_url=category_url,
            max_pages=max_pages,
            review_limit=review_limit,
            ownership=ownership,
            reply_to=reply_to,
        )
        return SimpleNamespace(id=task.id, status=task.status.value)

    def submit_scrape(self, urls: list[str], ownership: str, review_limit: int = 0, reply_to: str = ""):
        task = self._task_manager.submit_scrape(
            urls=urls,
            ownership=ownership,
            review_limit=review_limit,
            reply_to=reply_to,
        )
        return SimpleNamespace(id=task.id, status=task.status.value)


def build_daily_trigger_key(logical_date: str) -> str:
    return f"daily:{logical_date}"


def submit_daily_run(
    submitter: Any,
    source_csv: str,
    detail_csv: str,
    source_csv_url: str | None = None,
    detail_csv_url: str | None = None,
    logical_date: str | None = None,
    requested_by: str = "cli",
    dry_run: bool = False,
    notification_target: str | None = None,
) -> dict:
    """Create or reuse a daily workflow run, then submit tasks deterministically."""
    logical_date = logical_date or config.now_shanghai().date().isoformat()
    trigger_key = build_daily_trigger_key(logical_date)
    notification_target = notification_target or config.WORKFLOW_NOTIFICATION_TARGET

    existing = models.get_workflow_run_by_trigger_key(trigger_key)
    if existing:
        return {"created": False, "run": existing, "trigger_key": trigger_key}

    bundle = _load_daily_inputs_bundle(
        source_csv,
        detail_csv,
        source_csv_url=source_csv_url,
        detail_csv_url=detail_csv_url,
    )
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
    if not run.get("created", True):
        return {"created": False, "run": run, "trigger_key": trigger_key}

    collect_task_ids: list[str] = []
    scrape_task_ids: list[str] = []

    for request in bundle.collect_requests:
        task = submitter.submit_collect(
            request.category_url,
            ownership=request.ownership,
            max_pages=request.max_pages,
            review_limit=request.review_limit,
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
            review_limit=request.review_limit,
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


def _count_pending_translations_for_window(since: str, until: str) -> int:
    conn = models.get_conn()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM reviews
            WHERE scraped_at >= ?
              AND scraped_at < ?
              AND (
                    translate_status IS NULL
                 OR translate_status = 'failed'
              )
            """,
            (_report_db_ts(since), _report_db_ts(until)),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def _report_db_ts(value: str) -> str:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(config.SHANGHAI_TZ).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# Track translation progress per run to detect stalls.
# {run_id: (last_pending_count, stall_since_iso)}
_translation_progress: dict[int, tuple[int, str]] = {}


def _translation_wait_expired(run: dict, now: str, pending: int = 0) -> bool:
    """Return True when the translation wait should be abandoned.

    Strategy: keep waiting as long as pending count is decreasing (translations
    are making progress).  Only start the stall timer when pending stops
    decreasing for consecutive checks.  If stalled for longer than
    WORKFLOW_TRANSLATION_WAIT_SECONDS, give up.

    This replaces the old fixed-timeout approach which couldn't handle large
    review volumes — 1000+ reviews easily exceed 15 minutes of translation time.
    """
    run_id = run["id"]
    prev = _translation_progress.get(run_id)

    if prev is None:
        # First observation — record baseline, not stalled yet.
        _translation_progress[run_id] = (pending, now)
        return False

    last_pending, stall_since = prev

    if pending < last_pending:
        # Progress! Reset stall timer.
        _translation_progress[run_id] = (pending, now)
        return False

    # No progress (pending unchanged or increased) — check stall duration.
    stall_start = datetime.fromisoformat(stall_since)
    current = datetime.fromisoformat(now)
    stall_seconds = (current - stall_start).total_seconds()

    # Update count (in case it increased) but keep the stall_since.
    _translation_progress[run_id] = (pending, stall_since)

    return stall_seconds >= config.WORKFLOW_TRANSLATION_WAIT_SECONDS


def _clear_translation_progress(run_id: int) -> None:
    """Clean up tracking state when a run exits the reporting phase."""
    _translation_progress.pop(run_id, None)


# Track report generation retry attempts per run.
# {run_id: consecutive_failure_count}
_report_attempts: dict[int, int] = {}
_REPORT_MAX_RETRIES = 3


def _report_retry_or_fail(run_id: int) -> bool:
    """Return True if we should retry, False if max retries exhausted."""
    count = _report_attempts.get(run_id, 0) + 1
    _report_attempts[run_id] = count
    return count < _REPORT_MAX_RETRIES


def _clear_report_attempts(run_id: int) -> None:
    _report_attempts.pop(run_id, None)


class DailySchedulerWorker:
    """Embed daily-submit scheduling into the long-running crawler service."""

    def __init__(
        self,
        submitter: Any,
        source_csv: str,
        detail_csv: str,
        source_csv_url: str | None = None,
        detail_csv_url: str | None = None,
        *,
        schedule_time: str | None = None,
        interval: int | None = None,
        retry_seconds: int | None = None,
        notification_target: str | None = None,
        requested_by: str = "embedded_scheduler",
    ):
        self._submitter = submitter
        self._source_csv = source_csv
        self._detail_csv = detail_csv
        self._source_csv_url = source_csv_url or config.DAILY_SOURCE_CSV_URL
        self._detail_csv_url = detail_csv_url or config.DAILY_PRODUCT_CSV_URL
        self._notification_target = notification_target or config.WORKFLOW_NOTIFICATION_TARGET
        self._requested_by = requested_by
        self._schedule_time = schedule_time or config.DAILY_SCHEDULER_TIME
        self._schedule_hour, self._schedule_minute = _parse_schedule_time(self._schedule_time)
        self._interval = interval or config.DAILY_SCHEDULER_INTERVAL
        self._retry_seconds = retry_seconds or config.DAILY_SCHEDULER_RETRY_SECONDS
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="daily-scheduler")
        self._last_attempt_logical_date: str | None = None
        self._last_attempt_at: datetime | None = None

    def start(self):
        self._thread.start()
        logger.info(
            "DailySchedulerWorker: started (time=%s, interval=%ds, retry_seconds=%ds)",
            self._schedule_time,
            self._interval,
            self._retry_seconds,
        )

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def trigger(self):
        self._wake_event.set()

    def process_once(self, now: datetime | None = None) -> bool:
        current = now or config.now_shanghai()
        logical_date = current.date().isoformat()
        scheduled_at = current.replace(
            hour=self._schedule_hour,
            minute=self._schedule_minute,
            second=0,
            microsecond=0,
        )

        if current < scheduled_at:
            return False

        trigger_key = build_daily_trigger_key(logical_date)
        if models.get_workflow_run_by_trigger_key(trigger_key):
            return False

        if (
            self._last_attempt_logical_date == logical_date
            and self._last_attempt_at is not None
            and (current - self._last_attempt_at).total_seconds() < self._retry_seconds
        ):
            return False

        self._last_attempt_logical_date = logical_date
        self._last_attempt_at = current

        result = submit_daily_run(
            submitter=self._submitter,
            source_csv=self._source_csv,
            detail_csv=self._detail_csv,
            source_csv_url=self._source_csv_url,
            detail_csv_url=self._detail_csv_url,
            logical_date=logical_date,
            requested_by=self._requested_by,
            dry_run=False,
            notification_target=self._notification_target,
        )
        if result.get("created"):
            logger.info(
                "DailySchedulerWorker: submitted daily run for %s (trigger_key=%s)",
                logical_date,
                result["trigger_key"],
            )
            return True

        return False

    def _run(self):
        while not self._stop_event.is_set():
            try:
                while self.process_once() and not self._stop_event.is_set():
                    continue
            except Exception:
                logger.exception("DailySchedulerWorker: unexpected error")

            self._wake_event.clear()
            self._wake_event.wait(timeout=self._interval)


def _parse_schedule_time(value: str) -> tuple[int, int]:
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.hour, parsed.minute


def _load_daily_inputs_bundle(
    source_csv: str,
    detail_csv: str,
    *,
    source_csv_url: str | None = None,
    detail_csv_url: str | None = None,
):
    source_csv_url = source_csv_url or config.DAILY_SOURCE_CSV_URL
    detail_csv_url = detail_csv_url or config.DAILY_PRODUCT_CSV_URL
    if not source_csv_url and not detail_csv_url:
        return load_daily_inputs(source_csv, detail_csv)

    with tempfile.TemporaryDirectory(prefix="qbu-daily-inputs-") as tmpdir:
        resolved_source = source_csv
        resolved_detail = detail_csv
        if source_csv_url:
            resolved_source = _download_daily_csv(source_csv_url, Path(tmpdir) / "sku-list-source.csv")
        if detail_csv_url:
            resolved_detail = _download_daily_csv(detail_csv_url, Path(tmpdir) / "sku-product-details.csv")
        return load_daily_inputs(resolved_source, resolved_detail)


def _download_daily_csv(url: str, destination: Path) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"qbu-crawler/{__version__}"},
        method="GET",
    )
    context = _build_daily_csv_ssl_context(url)
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        destination.write_bytes(response.read())
    return str(destination)


def _build_daily_csv_ssl_context(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        return None
    try:
        ip_address(parsed.hostname or "")
    except ValueError:
        return None
    logger.warning(
        "Daily CSV download uses HTTPS IP URL (%s); disabling SSL hostname verification for compatibility",
        url,
    )
    return ssl._create_unverified_context()


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
        try:
            from qbu_crawler.server.notifier import reconcile_full_sent_deadletters
            conn = models.get_conn()
            try:
                changed = reconcile_full_sent_deadletters(conn) > 0 or changed
            finally:
                conn.close()
        except Exception:
            logger.exception("WorkflowWorker: full_sent deadletter reconcile failed")

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

        # F011 H13 — when a run already reached `full_sent`, opportunistically
        # check the outbox for deadletter rows and downgrade the phase to
        # `full_sent_local`.  Best-effort: failures here must not block any
        # further pipeline work, but the downgrade is required so ops alerts
        # later see the correct delivery state. Only runs once the run is in
        # the terminal-ish phase; earlier phases are skipped by the helper.
        if run.get("report_phase") == "full_sent":
            try:
                from qbu_crawler.server.notifier import downgrade_report_phase_on_deadletter
                conn = models.get_conn()
                try:
                    downgrade_report_phase_on_deadletter(conn, run_id)
                finally:
                    conn.close()
                # Re-fetch the run so any downgrade is reflected downstream.
                run = models.get_workflow_run(run_id) or run
            except Exception:
                logger.exception(
                    "WorkflowWorker: deadletter downgrade check failed "
                    "(non-fatal, run %s continues)", run_id,
                )

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

        # Partial failure: if some tasks succeeded, continue to reporting with
        # available data.  Only block when ALL tasks failed — no data to report.
        if statuses & {"failed", "cancelled"}:
            if "completed" not in statuses:
                self._move_run_to_attention(run, now, "All workflow tasks failed")
                return True
            failed_count = sum(1 for t in task_rows if t["status"] in ("failed", "cancelled"))
            logger.warning(
                "WorkflowWorker: %d/%d tasks failed for run %s, continuing with partial data",
                failed_count, len(task_rows), run_id,
            )

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
            pending_translations = _count_pending_translations_for_window(
                run["data_since"],
                run["data_until"],
            )
            if pending_translations > 0 and not _translation_wait_expired(run, now, pending=pending_translations):
                if changed:
                    logger.info(
                        "WorkflowWorker: waiting for %d translations before reporting run %s",
                        pending_translations,
                        run_id,
                    )
                return changed
            if pending_translations > 0:
                logger.warning(
                    "WorkflowWorker: translation stalled for run %s; continuing with %d untranslated reviews",
                    run_id,
                    pending_translations,
                )
            _clear_translation_progress(run_id)
            run = freeze_report_snapshot(run_id, now=now)
            models.update_workflow_report_status(
                run_id,
                report_generation_status="pending",
            )
            try:
                from qbu_crawler.server.run_log import append_run_log
                append_run_log(
                    run_id=run_id,
                    logical_date=run["logical_date"],
                    event="snapshot_frozen",
                    lines=[
                        f"snapshot_path={run.get('snapshot_path')}",
                        f"snapshot_hash={run.get('snapshot_hash')}",
                    ],
                )
            except Exception:
                logger.exception("WorkflowWorker: run log snapshot entry failed")
            changed = True

        # ── 数据质量统计与独立告警（P008 Task 6 + F011 §4.4.1） ──────
        # Gate by persisted scrape_quality rather than snapshot_path, so that
        # a transient failure on first attempt is re-tried on subsequent ticks.
        if models.get_scrape_quality(run_id) is None:
            try:
                from qbu_crawler.server.scrape_quality import summarize_scrape_quality
                from qbu_crawler.server.notifier import (
                    _evaluate_ops_alert_triggers, count_outbox_deadletter,
                )
                snapshot = load_report_snapshot(run["snapshot_path"])
                quality = summarize_scrape_quality(snapshot.get("products", []), tasks=task_rows)
                # F011 §4.4.1 — augment quality with the inputs that the
                # P0/P1/P2 evaluator consults beyond legacy ratios. Share the
                # notifier-side json_extract counter to keep the deadletter
                # match semantics identical (Group B Critical B-2).
                _conn = models.get_conn()
                try:
                    quality["outbox_deadletter_count"] = count_outbox_deadletter(_conn, run_id)
                finally:
                    _conn.close()
                quality["estimated_date_ratio"] = _estimated_date_ratio(
                    snapshot.get("reviews") or [], run.get("logical_date") or "",
                )
                models.update_scrape_quality(run_id, quality)
                log_path = None
                try:
                    from qbu_crawler.server.run_log import (
                        append_run_log,
                        build_quality_log_lines,
                    )
                    log_path = append_run_log(
                        run_id=run_id,
                        logical_date=run["logical_date"],
                        event="scrape_quality_summary",
                        lines=build_quality_log_lines(snapshot, quality, task_rows),
                    )
                except Exception:
                    logger.exception("WorkflowWorker: run log quality entry failed")
                triggered, severity = _evaluate_ops_alert_triggers(quality)
                if triggered:
                    _send_data_quality_alert(
                        run_id=run_id,
                        logical_date=run["logical_date"],
                        quality=quality,
                        severity=severity,
                        log_path=str(log_path) if log_path else None,
                    )
            except Exception:
                logger.exception(
                    "WorkflowWorker: scrape-quality summary/alert failed "
                    "(non-fatal, run %s continues)", run_id)

        snapshot = load_report_snapshot(run["snapshot_path"])
        digest = build_daily_digest(snapshot)
        _enqueue_workflow_notification(
            kind="workflow_daily_digest",
            target=config.WORKFLOW_NOTIFICATION_TARGET,
            payload=digest,
            dedupe_key=f"workflow:{run_id}:daily-digest",
        )

        if run.get("report_phase") == "none":
            if snapshot.get("reviews_count", 0) == 0:
                # No new reviews — skip fast report (meaningless without reviews),
                # jump directly to full_pending where generate_report_from_snapshot
                # will route to change or quiet mode.
                _clear_translation_progress(run_id)
                run = models.update_workflow_run(run_id, report_phase="full_pending")
            else:
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
                from qbu_crawler.server import report_snapshot as report_snapshot_module
                _prev_analytics, prev_snapshot = report_snapshot_module.load_previous_report_context(run_id)
                snapshot_for_decision = dict(snapshot)
                snapshot_for_decision["is_bootstrap"] = prev_snapshot is None
                decision = decide_business_email(
                    run=run,
                    snapshot=snapshot_for_decision,
                    mode=run.get("report_mode") or "",
                )
                report_snapshot_for_delivery = snapshot
                if decision.report_window_type == "bootstrap":
                    report_snapshot_for_delivery = dict(snapshot)
                    report_snapshot_for_delivery["report_window"] = {
                        "type": "bootstrap",
                        "label": "监控起点",
                        "days": 0,
                    }
                elif decision.report_window_type == "weekly":
                    report_snapshot_for_delivery = build_windowed_report_snapshot(
                        snapshot,
                        window_type="weekly",
                        window_days=decision.window_days,
                    )
                else:
                    report_snapshot_for_delivery = dict(snapshot)
                    report_snapshot_for_delivery.setdefault(
                        "report_window",
                        {"type": "daily", "label": "今日", "days": 1},
                    )
                should_send_email = decision.send_email
                full_report = generate_report_from_snapshot(
                    report_snapshot_for_delivery,
                    send_email=should_send_email,
                )
            except FullReportGenerationError as exc:
                models.update_workflow_run(
                    run_id,
                    analytics_path=exc.analytics_path,
                    excel_path=exc.excel_path,
                    pdf_path=exc.pdf_path,
                )
                if _report_retry_or_fail(run_id):
                    logger.warning(
                        "WorkflowWorker: report generation failed for run %s (attempt %d/%d), will retry — %s",
                        run_id, _report_attempts[run_id], _REPORT_MAX_RETRIES, exc,
                    )
                    return False  # break inner loop, retry after next interval sleep
                models.update_workflow_report_status(
                    run_id,
                    report_generation_status="failed",
                    delivery_last_error=str(exc),
                )
                self._move_run_to_attention(run, now, str(exc), report_phase="fast_sent")
                return True
            except Exception as exc:
                if _report_retry_or_fail(run_id):
                    logger.warning(
                        "WorkflowWorker: report generation failed for run %s (attempt %d/%d), will retry — %s",
                        run_id, _report_attempts[run_id], _REPORT_MAX_RETRIES, exc,
                    )
                    return False  # break inner loop, retry after next interval sleep
                models.update_workflow_report_status(
                    run_id,
                    report_generation_status="failed",
                    delivery_last_error=str(exc),
                )
                self._move_run_to_attention(run, now, str(exc), report_phase="fast_sent")
                return True
            _clear_report_attempts(run_id)

            excel_path = full_report.get("excel_path")
            analytics_path = full_report.get("analytics_path")
            pdf_path = full_report.get("pdf_path")
            html_path = full_report.get("html_path") or full_report.get("v3_html_path")
            email = full_report.get("email")
            email_ok = (email or {}).get("success")
            # Stage B 修 7 follow-up: report_snapshot.generate_report_from_snapshot
            # is the single source of truth for path shape — it already returns
            # paths relativized to REPORT_DIR. Storing them verbatim here keeps the
            # producer/consumer contract clean. Do NOT call _artifact_db_value again:
            # it is not idempotent for relative inputs (Path(rel).resolve() roots
            # at CWD and breaks the relative_to() lookup, falling through to a
            # bogus CWD-absolute path).
            models.update_workflow_run(
                run_id,
                excel_path=excel_path,
                analytics_path=analytics_path,
                pdf_path=pdf_path,
            )
            # Email failure should not block run completion — report files
            # already exist on disk.  Log the problem and mark in notification.
            if should_send_email and not email_ok:
                logger.warning(
                    "WorkflowWorker: email failed for run %s — %s",
                    run_id, (email or {}).get("error"),
                )

            _enqueue_workflow_notification(
                kind="workflow_full_report",
                target=config.WORKFLOW_NOTIFICATION_TARGET,
                payload={
                    "run_id": run_id,
                    "logical_date": run["logical_date"],
                    "snapshot_hash": full_report.get("snapshot_hash", ""),
                    "excel_path": excel_path,
                    "analytics_path": analytics_path,
                    "pdf_path": pdf_path,
                    "html_path": html_path,
                    "report_mode": full_report.get("mode", "full"),
                    "email_status": _workflow_email_status_from_decision(
                        decision=decision,
                        email_success=email_ok,
                        untranslated_count=report_snapshot_for_delivery.get("untranslated_count", 0),
                    ),
                },
                dedupe_key=f"workflow:{run_id}:full-report",
            )
            email_delivery_status = "skipped"
            delivery_last_error = None
            if should_send_email:
                email_delivery_status = "sent" if email_ok else "failed"
                delivery_last_error = (email or {}).get("error")
            else:
                delivery_last_error = decision.reason
            models.update_workflow_run(
                run_id,
                status="completed",
                report_phase="full_sent",
                excel_path=excel_path,
                analytics_path=analytics_path,
                pdf_path=pdf_path,
                finished_at=now,
                error=None,
            )
            models.update_workflow_report_status(
                run_id,
                report_generation_status="generated",
                email_delivery_status=email_delivery_status,
                workflow_notification_status="pending",
                delivery_last_error=delivery_last_error,
            )
            try:
                from qbu_crawler.server.report_manifest import update_analytics_delivery_from_db
                from qbu_crawler.server.run_log import append_run_log
                conn = models.get_conn()
                try:
                    manifest = update_analytics_delivery_from_db(
                        conn,
                        run_id=run_id,
                        analytics_path=analytics_path,
                    )
                finally:
                    conn.close()
                lines = [
                    f"excel_path={excel_path}",
                    f"html_path={html_path}",
                    f"analytics_path={analytics_path}",
                    f"email_success={bool(email_ok)}",
                ]
                if manifest:
                    delivery = manifest.get("delivery") or {}
                    lines.extend([
                        f"report_generated={delivery.get('report_generated')}",
                        f"workflow_notification_delivered={delivery.get('workflow_notification_delivered')}",
                        f"deadletter_count={delivery.get('deadletter_count')}",
                        f"internal_status={delivery.get('internal_status')}",
                    ])
                append_run_log(
                    run_id=run_id,
                    logical_date=run["logical_date"],
                    event="full_report_completed",
                    lines=lines,
                )
            except Exception:
                logger.exception("WorkflowWorker: final manifest/log refresh failed")
            _maybe_trigger_ai_digest(run_id, run, snapshot, full_report)
            _clear_translation_progress(run_id)
            _clear_report_attempts(run_id)
            return True

        return changed

    def _move_run_to_attention(
        self,
        run: dict,
        now: str,
        error_message: str,
        report_phase: str | None = None,
    ):
        _clear_translation_progress(run["id"])
        _clear_report_attempts(run["id"])
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


def _send_data_quality_alert(
    *,
    run_id: int,
    logical_date: str,
    quality: dict,
    severity: str = "",
    log_path: str | None = None,
) -> None:
    """独立于业务报告的运行运维日志通知。"""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from pathlib import Path
    from qbu_crawler.server import report as _report
    from qbu_crawler.server.run_log import build_ops_log_summary

    ops_summary = build_ops_log_summary(quality, log_path or "")

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    body_html = env.get_template("email_data_quality.html.j2").render(
        logical_date=logical_date,
        run_id=run_id,
        quality=quality,
        threshold=config.SCRAPE_QUALITY_ALERT_RATIO,
        severity=severity,
        ops_summary=ops_summary,
        run_log_path=log_path,
    )

    recipients = config.SCRAPE_QUALITY_ALERT_RECIPIENTS
    if not recipients:
        logger.warning("Ops run-log email skipped: no technical recipients configured")
        return

    severity_prefix = f"[{severity}] " if severity else ""
    subject = (
        f"{severity_prefix}[运维日志] 日报运行需关注 "
        f"{logical_date} (run #{run_id})"
    )
    try:
        _report.send_email(
            recipients=recipients,
            subject=subject,
            body_text=ops_summary,
            body_html=body_html,
            attachment_paths=[log_path] if log_path else None,
        )
    except Exception:
        logger.exception("Data-quality alert email send failed")


def _estimated_date_ratio(reviews: list[dict], logical_date_str: str) -> float:
    """F011 §4.4.1 — fraction of reviews whose parsed date falls on the same
    MM-DD as ``logical_date_str``, indicating the parser collapsed relative
    dates ("3 years ago") onto today. Returns 0.0 on bad input.
    """
    if not reviews or not logical_date_str or len(logical_date_str) < 10:
        return 0.0
    logical_mmdd = logical_date_str[5:10]
    if not logical_mmdd:
        return 0.0
    matching = 0
    for r in reviews:
        parsed = (r.get("date_published_parsed") or "")
        if parsed.endswith(logical_mmdd):
            matching += 1
    return matching / len(reviews)


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


def _workflow_email_status(email_success: bool | None, untranslated_count: int) -> str:
    if email_success is None:
        return "skipped"
    if email_success is False:
        return "failed"
    if untranslated_count > 0:
        return f"已发送（{untranslated_count} 条评论仍在翻译中）"
    return "success"


def _workflow_email_status_from_decision(decision, email_success: bool | None, untranslated_count: int) -> str:
    if not decision.send_email:
        if decision.reason == "weekly_cadence_skip":
            return "已跳过（周报频率）"
        return f"已跳过（{decision.reason}）"
    return _workflow_email_status(email_success, untranslated_count)


def _should_send_workflow_email(task_rows: list[dict], snapshot: dict) -> bool:
    """Always return True — email send/skip decisions are delegated to
    ``generate_report_from_snapshot`` which routes to the appropriate mode
    (full / change / quiet) and each mode handler decides internally whether
    to actually send an email (e.g. quiet-day frequency gating)."""
    return True


def _workflow_reviews_saved(task_rows: list[dict]) -> int | None:
    total = 0
    for row in task_rows:
        result = row.get("result") or {}
        if result.get("reviews_saved") is None:
            return None
        total += int(result.get("reviews_saved") or 0)
    return total


def _maybe_trigger_ai_digest(run_id: int, run: dict, snapshot: dict, full_report: dict):
    if config.AI_DIGEST_MODE != "async":
        return
    if not config.OPENCLAW_HOOK_URL:
        return

    prompt = (
        "请基于以下固定日报快照做简短业务摘要，不要触发任何工具。\n"
        f"run_id={run_id}\n"
        f"logical_date={run['logical_date']}\n"
        f"snapshot_hash={snapshot.get('snapshot_hash', '')}\n"
        f"products_count={snapshot.get('products_count', 0)}\n"
        f"reviews_count={snapshot.get('reviews_count', 0)}\n"
        f"translated_count={snapshot.get('translated_count', 0)}\n"
        f"excel_path={full_report.get('excel_path', '')}"
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
