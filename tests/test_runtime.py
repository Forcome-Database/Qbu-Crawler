"""Runtime lifecycle tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class _DummyWorker:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def test_server_runtime_starts_and_stops_components():
    from qbu_crawler.server.runtime import ServerRuntime

    translator = _DummyWorker()
    notifier = _DummyWorker()
    workflow = _DummyWorker()
    scheduler = _DummyWorker()

    runtime = ServerRuntime(
        translator=translator,
        task_manager=object(),
        notifier=notifier,
        workflow_worker=workflow,
        daily_scheduler=scheduler,
    )
    runtime.start()
    runtime.stop()

    assert translator.started == 1
    assert notifier.started == 1
    assert workflow.started == 1
    assert scheduler.started == 1
    assert translator.stopped == 1
    assert notifier.stopped == 1
    assert workflow.stopped == 1
    assert scheduler.stopped == 1


def test_app_lifespan_starts_and_stops_runtime(monkeypatch):
    from qbu_crawler.server import app as app_module

    start = MagicMock()
    stop = MagicMock()
    monkeypatch.setattr(app_module.runtime, "start", start)
    monkeypatch.setattr(app_module.runtime, "stop", stop)

    with TestClient(app_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    start.assert_called_once()
    stop.assert_called_once()
