"""Unified runtime lifecycle for crawler background workers."""

from __future__ import annotations

import logging

from qbu_crawler import config
from qbu_crawler.server.notifier import (
    NotificationDeliveryError,
    NotifierWorker,
    OpenClawBridgeSender,
)
from qbu_crawler.server.task_manager import TaskManager
from qbu_crawler.server.translator import TranslationWorker
from qbu_crawler.server.workflows import WorkflowWorker

logger = logging.getLogger(__name__)


class _DisabledBridgeSender:
    def send(self, notification: dict) -> dict:
        raise NotificationDeliveryError(
            "openclaw bridge is not configured",
            retryable=True,
        )


class ServerRuntime:
    """Own the background workers used by the API and automation flows."""

    def __init__(
        self,
        translator: TranslationWorker,
        task_manager: TaskManager,
        notifier: NotifierWorker | None = None,
        workflow_worker: WorkflowWorker | None = None,
    ):
        self.translator = translator
        self.task_manager = task_manager
        self.notifier = notifier
        self.workflow_worker = workflow_worker
        self._started = False

    def start(self):
        if self._started:
            return
        self.translator.start()
        if self.notifier is not None:
            self.notifier.start()
        if self.workflow_worker is not None:
            self.workflow_worker.start()
        self._started = True

    def stop(self):
        if not self._started:
            return
        if self.workflow_worker is not None:
            self.workflow_worker.stop()
        if self.notifier is not None:
            self.notifier.stop()
        self.translator.stop()
        self._started = False


def build_runtime() -> ServerRuntime:
    translator = TranslationWorker(
        interval=config.TRANSLATE_INTERVAL,
        batch_size=config.LLM_TRANSLATE_BATCH_SIZE,
        concurrency=config.TRANSLATE_WORKERS,
    )
    task_manager = TaskManager(max_workers=config.MAX_WORKERS, translator=translator)

    notifier = None
    if config.NOTIFICATION_MODE in {"shadow", "outbox"}:
        bridge_url = _normalize_bridge_url(config.OPENCLAW_BRIDGE_URL)
        if bridge_url and config.OPENCLAW_BRIDGE_TOKEN:
            sender = OpenClawBridgeSender(
                bridge_url=bridge_url,
                auth_token=config.OPENCLAW_BRIDGE_TOKEN,
                timeout=config.OPENCLAW_BRIDGE_TIMEOUT,
            )
        else:
            logger.warning("OpenClaw bridge not configured; outbox delivery will retry until configured")
            sender = _DisabledBridgeSender()
        notifier = NotifierWorker(
            sender=sender,
            interval=config.NOTIFIER_INTERVAL,
            lease_seconds=config.NOTIFIER_LEASE_SECONDS,
            max_attempts=config.NOTIFIER_MAX_ATTEMPTS,
        )

    workflow_worker = WorkflowWorker(
        interval=config.WORKFLOW_INTERVAL,
        task_stale_seconds=config.TASK_STALE_SECONDS,
    )

    return ServerRuntime(
        translator=translator,
        task_manager=task_manager,
        notifier=notifier,
        workflow_worker=workflow_worker,
    )


def _normalize_bridge_url(url: str) -> str:
    if not url:
        return ""
    normalized = url.rstrip("/")
    if not normalized.endswith("/notify"):
        normalized = f"{normalized}/notify"
    return normalized


runtime = build_runtime()
translator = runtime.translator
task_manager = runtime.task_manager
notifier = runtime.notifier
workflow_worker = runtime.workflow_worker
