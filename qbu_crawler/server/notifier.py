"""Notification outbox worker."""

from __future__ import annotations

import logging
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Thread
from typing import Any

from qbu_crawler import config, models

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
_TASK_TYPE_DISPLAY = {
    "scrape": "产品页抓取",
    "collect": "分类页采集",
}
_SITE_DISPLAY = {
    "basspro": "Bass Pro",
    "meatyourmaker": "Meat Your Maker",
    "waltons": "Walton's",
}
_OWNERSHIP_DISPLAY = {
    "own": "自有",
    "competitor": "竞品",
}
_FULL_REPORT_STATUS_BY_MODE = {
    "full": "已生成（完整版）",
    "change": "已生成（仅变动摘要）",
    "quiet": "已生成（精简日报）",
    "bootstrap": "已生成（监控起点版）",
}


def _full_report_status_display(report_mode: str | None) -> str:
    """根据 report_mode 给 workflow_full_report 通知挑一个语义清晰的状态串。
    未识别 mode 落到通用"已生成"，保留旧行为兜底。"""
    if not report_mode:
        return "已生成"
    return _FULL_REPORT_STATUS_BY_MODE.get(str(report_mode).lower(), "已生成")


@dataclass
class NotificationDeliveryError(RuntimeError):
    message: str
    retryable: bool = True
    http_status: int | None = None
    exit_code: int | None = None

    def __str__(self) -> str:
        return self.message


class OpenClawBridgeSender:
    """Send outbox notifications through the hardened OpenClaw bridge."""

    def __init__(self, bridge_url: str, auth_token: str, timeout: int = 15):
        self._bridge_url = bridge_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout = timeout

    def send(self, notification: dict) -> dict:
        body = {
            "target": notification["target"],
            "template_key": self._template_key_for(notification),
            "template_vars": self._template_vars_for(notification),
            "dedupe_key": notification.get("dedupe_key") or _notification_dedupe_key(notification),
        }
        request = urllib.request.Request(
            url=self._bridge_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Bridge-Token": self._auth_token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retryable = exc.code in _RETRYABLE_HTTP_STATUS
            raise NotificationDeliveryError(
                f"bridge returned HTTP {exc.code}",
                retryable=retryable,
                http_status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise NotificationDeliveryError(
                f"bridge request failed: {exc.reason}",
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise NotificationDeliveryError(
                "bridge request timed out",
                retryable=True,
            ) from exc
        except json.JSONDecodeError as exc:
            raise NotificationDeliveryError(
                "bridge returned invalid JSON",
                retryable=True,
            ) from exc

        return {
            "bridge_request_id": result.get("bridge_request_id", ""),
            "http_status": result.get("http_status", 200),
        }

    def _template_key_for(self, notification: dict) -> str:
        return str(notification["kind"])

    def _template_vars_for(self, notification: dict) -> dict[str, Any]:
        payload = notification.get("payload") or {}
        kind = notification.get("kind")
        if kind == "task_completed":
            return {
                "task_id": payload.get("task_id", ""),
                "task_type": _display_task_type(payload.get("task_type", "")),
                "status": payload.get("status", ""),
                "task_heading": payload.get("task_heading", ""),
                "target_summary": payload.get("target_summary", ""),
                "site": _display_site(payload.get("site", "")),
                "ownership": _display_ownership(payload.get("ownership", "")),
                "result_summary": payload.get("result_summary", _summarize_task_result(payload.get("result"), payload.get("error"))),
                "product_count": payload.get("product_count", (payload.get("result") or {}).get("products_saved", 0)),
                "review_count": payload.get("review_count", (payload.get("result") or {}).get("reviews_saved", 0)),
                "failed_summary": payload.get("failed_summary", "无"),
                "summary": _summarize_task_result(payload.get("result"), payload.get("error")),
            }
        if kind == "workflow_started":
            return {
                "logical_date": payload.get("logical_date", ""),
                "run_id": payload.get("run_id", ""),
                "collect_count": len(payload.get("collect_task_ids") or []),
                "scrape_count": len(payload.get("scrape_task_ids") or []),
            }
        if kind == "workflow_daily_digest":
            return {
                "logical_date": payload.get("logical_date", ""),
                "run_id": payload.get("run_id", ""),
                "new_review_count": payload.get("new_review_count", 0),
                "own_new_count": payload.get("own_new_count", 0),
                "competitor_new_count": payload.get("competitor_new_count", 0),
                "markdown": payload.get("markdown", ""),
            }
        # Sanitize path fields that may be None for change/quiet report modes
        # to avoid the literal string "None" in DingTalk messages.
        result = dict(payload)
        for path_key in ("excel_path", "analytics_path", "pdf_path", "html_path"):
            if result.get(path_key) is None:
                result[path_key] = ""
        if kind == "workflow_full_report":
            # 让 report_generation_status 携带 mode 语义，避免 quiet/change 模式
            # 显示"已生成"但附件为空的矛盾感。upstream 仍可显式传 status 覆盖。
            raw_status = payload.get("report_generation_status")
            if not raw_status:
                raw_status = _full_report_status_display(payload.get("report_mode"))
            result["report_generation_status"] = raw_status
            # Excel 附件为空时给出明确说明，避免空白行
            if not result.get("excel_path"):
                result["excel_path"] = "（本次无 Excel 附件）"
        return result


class NotifierWorker:
    """Poll the outbox, send notifications, and update delivery state."""

    def __init__(
        self,
        sender: Any,
        interval: int = 5,
        lease_seconds: int = 60,
        max_attempts: int = 3,
    ):
        self._sender = sender
        self._interval = interval
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="notification-worker")

    def start(self):
        self._thread.start()
        logger.info(
            "NotifierWorker: started (interval=%ds, lease=%ds, max_attempts=%d)",
            self._interval,
            self._lease_seconds,
            self._max_attempts,
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
        models.reclaim_stale_notifications(now)
        lease_until = _plus_seconds(now, self._lease_seconds)
        claimed = models.claim_next_notification(
            claim_token=uuid.uuid4().hex,
            claimed_at=now,
            lease_until=lease_until,
        )
        if not claimed:
            return False

        try:
            result = self._sender.send(claimed)
            models.mark_notification_sent(
                notification_id=claimed["id"],
                delivered_at=now,
                bridge_request_id=(result or {}).get("bridge_request_id", ""),
                http_status=(result or {}).get("http_status"),
            )
            if claimed["kind"] == "task_completed":
                task_id = (claimed.get("payload") or {}).get("task_id")
                if task_id:
                    models.mark_task_notified([task_id])
            _sync_workflow_notification_status(claimed)
            return True
        except NotificationDeliveryError as exc:
            models.mark_notification_failure(
                notification_id=claimed["id"],
                failed_at=now,
                error_message=str(exc),
                retryable=exc.retryable,
                max_attempts=self._max_attempts,
                http_status=exc.http_status,
                exit_code=exc.exit_code,
            )
            _sync_workflow_notification_status(claimed)
            return True
        except Exception as exc:
            models.mark_notification_failure(
                notification_id=claimed["id"],
                failed_at=now,
                error_message=str(exc),
                retryable=True,
                max_attempts=self._max_attempts,
            )
            _sync_workflow_notification_status(claimed)
            return True

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
                logger.exception("NotifierWorker: unexpected error")


def _plus_seconds(ts: str, seconds: int) -> str:
    dt = datetime.fromisoformat(ts)
    return (dt + timedelta(seconds=seconds)).isoformat()


def _sync_workflow_notification_status(notification: dict) -> None:
    if not str(notification.get("kind") or "").startswith("workflow_"):
        return
    if notification.get("kind") == "workflow_daily_digest":
        return
    payload = notification.get("payload") or {}
    run_id = payload.get("run_id")
    if not run_id:
        return
    conn = models.get_conn()
    try:
        if count_outbox_deadletter(conn, int(run_id)) > 0:
            downgrade_report_phase_on_deadletter(conn, int(run_id))
            return
        from qbu_crawler.server.report_status import sync_workflow_report_status
        sync_workflow_report_status(conn, int(run_id))
    finally:
        conn.close()


def _summarize_task_result(result: Any, error: str | None = None) -> str:
    if error:
        return str(error)
    if isinstance(result, dict):
        parts = []
        if result.get("products_saved") is not None:
            parts.append(f"products_saved={result['products_saved']}")
        if result.get("reviews_saved") is not None:
            parts.append(f"reviews_saved={result['reviews_saved']}")
        if result.get("products_collected") is not None:
            parts.append(f"products_collected={result['products_collected']}")
        if parts:
            return ", ".join(parts)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    return "" if result is None else str(result)


def _display_task_type(value: str) -> str:
    key = str(value or "").strip().lower()
    return _TASK_TYPE_DISPLAY.get(key, value)


def _display_site(value: str) -> str:
    key = str(value or "").strip().lower()
    return _SITE_DISPLAY.get(key, value)


def _display_ownership(value: str) -> str:
    key = str(value or "").strip().lower()
    return _OWNERSHIP_DISPLAY.get(key, value)


def _notification_dedupe_key(notification: dict) -> str:
    identifier = notification.get("id") or "unknown"
    kind = notification.get("kind") or "notification"
    return f"notification:{identifier}:{kind}"


# ──────────────────────────────────────────────────────────────────────────
# F011 §4.4.1 — internal ops alert severity ladder
# ──────────────────────────────────────────────────────────────────────────

OPS_ALERT_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _evaluate_ops_alert_triggers(quality: dict) -> tuple[bool, str]:
    """F011 §4.4.1 — return (triggered, max_severity).

    Triggers (highest precedence first):
      - zero_scrape_skus non-empty → P0
      - scrape_completeness_ratio < 0.6 → P1
      - failed_url_count / missing_url_count > 0 → P1
      - outbox_deadletter_count > 0 → P1
      - estimated_date_ratio > 0.3 → P2

    The returned severity is the *highest* among all firing triggers
    (P0 > P1 > P2 in priority). Empty string is returned when nothing
    fires alongside ``triggered=False``.
    """
    severities: list[str] = []
    if quality.get("zero_scrape_skus"):
        severities.append("P0")
    if (quality.get("scrape_completeness_ratio") or 1.0) < 0.6:
        severities.append("P1")
    if (quality.get("failed_url_count") or 0) > 0:
        severities.append("P1")
    if (quality.get("missing_url_count") or 0) > 0:
        severities.append("P1")
    if (quality.get("outbox_deadletter_count") or 0) > 0:
        severities.append("P1")
    if (quality.get("estimated_date_ratio") or 0.0) > 0.3:
        severities.append("P2")

    if not severities:
        return (False, "")
    # Lowest rank value = highest severity (P0=0 < P1=1 < P2=2)
    severity = min(severities, key=lambda s: OPS_ALERT_SEVERITY_RANK.get(s, 99))
    return (True, severity)


def count_outbox_deadletter(conn, run_id: int) -> int:
    """F011 H13 — count ``notification_outbox`` deadletter rows tied to a
    given workflow ``run_id``.

    Uses ``json_extract(payload, '$.run_id')`` rather than a substring LIKE
    so it is robust to:
      - whitespace produced by ``json.dumps`` (default ``"run_id": 10``),
      - prefix collisions (``run_id=1`` vs ``run_id=10``),
      - key-ordering / nested JSON shape changes.

    Falls back gracefully when the underlying SQLite build lacks JSON1
    (very rare on Python ≥3.10) by returning ``0`` rather than raising —
    callers treat this helper as best-effort observability.

    Exported as a module-level helper so other workflow code can share the
    exact same deadletter-counting semantics (avoids fragile per-call
    LIKE patterns drifting out of sync with ``json.dumps`` output).
    """
    cur = conn.cursor()
    try:
        return cur.execute(
            "SELECT COUNT(*) FROM notification_outbox "
            "WHERE status='deadletter' "
            "AND CAST(json_extract(payload, '$.run_id') AS INTEGER) = ?",
            (run_id,),
        ).fetchone()[0]
    except Exception:  # pragma: no cover — defensive for legacy SQLite
        logger.exception("count_outbox_deadletter: json_extract failed")
        return 0


def downgrade_report_phase_on_deadletter(conn, run_id: int) -> bool:
    """F011 H13 — when notification_outbox has deadletter rows for ``run_id``,
    downgrade ``workflow_runs.report_phase`` from ``'full_sent'`` to
    ``'full_sent_local'``.

    Returns True if a downgrade actually occurred, False otherwise (no
    deadletter rows OR phase wasn't ``full_sent``).

    Uses :func:`count_outbox_deadletter` so the JSON matching semantics stay
    consistent with the way ``models.enqueue_notification`` writes the
    payload (``json.dumps`` produces ``"run_id": <id>`` with whitespace,
    which the previous LIKE pattern ``%"run_id":<id>%`` never matched).
    """
    if count_outbox_deadletter(conn, run_id) == 0:
        return False
    cur = conn.cursor()
    result = cur.execute(
        "UPDATE workflow_runs SET report_phase='full_sent_local' "
        "WHERE id=? AND report_phase='full_sent'",
        (run_id,),
    )
    conn.commit()
    changed = result.rowcount > 0
    try:
        from qbu_crawler.server.report_status import sync_workflow_report_status
        sync_workflow_report_status(conn, run_id)
    except Exception:
        logger.exception("downgrade_report_phase_on_deadletter: status sync failed")
    try:
        from qbu_crawler.server.report_manifest import update_analytics_delivery_from_db
        update_analytics_delivery_from_db(conn, run_id)
    except Exception:
        logger.exception("downgrade_report_phase_on_deadletter: manifest refresh failed")
    return changed


def reconcile_full_sent_deadletters(conn, *, limit: int = 50) -> int:
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id FROM workflow_runs "
        "WHERE report_phase='full_sent' "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    changed = 0
    for row in rows:
        run_id = row["id"] if hasattr(row, "keys") else row[0]
        if downgrade_report_phase_on_deadletter(conn, run_id):
            changed += 1
    return changed
