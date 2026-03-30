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
                "task_type": payload.get("task_type", ""),
                "status": payload.get("status", ""),
                "summary": _summarize_task_result(payload.get("result"), payload.get("error")),
            }
        if kind == "workflow_started":
            return {
                "logical_date": payload.get("logical_date", ""),
                "collect_count": len(payload.get("collect_task_ids") or []),
                "scrape_count": len(payload.get("scrape_task_ids") or []),
            }
        return dict(payload)


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
            return True
        except Exception as exc:
            models.mark_notification_failure(
                notification_id=claimed["id"],
                failed_at=now,
                error_message=str(exc),
                retryable=True,
                max_attempts=self._max_attempts,
            )
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


def _notification_dedupe_key(notification: dict) -> str:
    identifier = notification.get("id") or "unknown"
    kind = notification.get("kind") or "notification"
    return f"notification:{identifier}:{kind}"
