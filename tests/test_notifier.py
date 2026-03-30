"""Notification outbox model tests."""

import sqlite3
import subprocess
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from qbu_crawler import models


@pytest.fixture()
def notifier_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "notifier.db")

    def _conn():
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(models, "get_conn", _conn)
    models.init_db()
    return _conn


def test_outbox_deduplicates_by_dedupe_key(notifier_db):
    first = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-1",
            "payload": {"task_id": "task-1"},
            "dedupe_key": "task-1:completed",
            "payload_hash": "hash-1",
        }
    )
    second = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-1",
            "payload": {"task_id": "task-1"},
            "dedupe_key": "task-1:completed",
            "payload_hash": "hash-1",
        }
    )

    assert second["id"] == first["id"]

    conn = notifier_db()
    count = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
    conn.close()
    assert count == 1


def test_outbox_claim_and_reclaim_cycle(notifier_db):
    row = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-2",
            "payload": {"task_id": "task-2"},
            "dedupe_key": "task-2:completed",
            "payload_hash": "hash-2",
        }
    )

    claimed = models.claim_next_notification(
        claim_token="claim-1",
        claimed_at="2026-03-29T10:00:00+08:00",
        lease_until="2026-03-29T10:05:00+08:00",
    )
    assert claimed["id"] == row["id"]
    assert claimed["claim_token"] == "claim-1"
    assert claimed["status"] == "claimed"

    reclaimed = models.reclaim_stale_notifications("2026-03-29T10:06:00+08:00")
    assert reclaimed == 1

    pending = models.claim_next_notification(
        claim_token="claim-2",
        claimed_at="2026-03-29T10:07:00+08:00",
        lease_until="2026-03-29T10:12:00+08:00",
    )
    assert pending["id"] == row["id"]
    assert pending["claim_token"] == "claim-2"


def _build_task_manager_task():
    from qbu_crawler.server.task_manager import Task, TaskManager, TaskStatus

    manager = TaskManager(max_workers=1)
    task = Task(
        type="scrape",
        params={"urls": ["https://www.basspro.com/shop/en/example-product-1"], "ownership": "own"},
        reply_to="chat:cid-1",
    )
    task.status = TaskStatus.completed
    task.result = {"products_saved": 1, "reviews_saved": 2}
    manager._tasks[task.id] = task
    return manager, task


@pytest.mark.parametrize(
    ("mode", "expect_legacy_delivery", "expect_outbox_enqueue", "expect_mark_notified"),
    [
        ("legacy", True, False, True),
        ("shadow", True, True, True),
        ("outbox", False, True, False),
    ],
)
def test_completion_notification_cutover(
    monkeypatch,
    mode: str,
    expect_legacy_delivery: bool,
    expect_outbox_enqueue: bool,
    expect_mark_notified: bool,
):
    from qbu_crawler.server import task_manager as task_manager_module

    manager, task = _build_task_manager_task()
    monkeypatch.setattr(task_manager_module.config, "NOTIFICATION_MODE", mode)
    monkeypatch.setattr(task_manager_module.config, "OPENCLAW_HOOK_URL", "http://127.0.0.1:18789")
    monkeypatch.setattr(task_manager_module.config, "OPENCLAW_HOOK_TOKEN", "token")

    with (
        patch.object(task_manager_module.models, "mark_task_notified") as mock_mark_notified,
        patch.object(task_manager_module.models, "enqueue_notification") as mock_enqueue,
        patch.object(task_manager_module.urllib.request, "urlopen", return_value=MagicMock()) as mock_urlopen,
    ):
        manager._notify_completion(task.id)

    if expect_legacy_delivery:
        mock_urlopen.assert_called_once()
    else:
        mock_urlopen.assert_not_called()

    if expect_mark_notified:
        mock_mark_notified.assert_called_once_with([task.id])
    else:
        mock_mark_notified.assert_not_called()

    if expect_outbox_enqueue:
        mock_enqueue.assert_called_once()
        payload = mock_enqueue.call_args.args[0]
        assert payload["target"] == "chat:cid-1"
        assert payload["dedupe_key"] == f"task:{task.id}:completed"
    else:
        mock_enqueue.assert_not_called()

    manager._executor.shutdown(wait=False, cancel_futures=True)


class _FakeSender:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def send(self, notification):
        self.calls.append(notification["id"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_notifier_worker_marks_sent_and_does_not_repeat(notifier_db):
    from qbu_crawler.server.notifier import NotifierWorker

    row = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-sent",
            "payload": {"task_id": "task-sent"},
            "dedupe_key": "task-sent:completed",
            "payload_hash": "hash-sent",
        }
    )
    sender = _FakeSender([{"bridge_request_id": "req-1", "http_status": 200}])
    worker = NotifierWorker(sender=sender, lease_seconds=30, max_attempts=3)

    processed = worker.process_once(now="2026-03-29T11:00:00+08:00")
    assert processed is True

    stored = models.get_notification(row["id"])
    assert stored["status"] == "sent"
    assert stored["bridge_request_id"] == "req-1"
    assert stored["delivered_at"] == "2026-03-29T11:00:00+08:00"

    processed_again = worker.process_once(now="2026-03-29T11:01:00+08:00")
    assert processed_again is False
    assert sender.calls == [row["id"]]


def test_notifier_worker_retryable_failure_and_deadletter(notifier_db):
    from qbu_crawler.server.notifier import NotificationDeliveryError, NotifierWorker

    row = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-deadletter",
            "payload": {"task_id": "task-dead"},
            "dedupe_key": "task-dead:completed",
            "payload_hash": "hash-dead",
        }
    )
    sender = _FakeSender(
        [
            NotificationDeliveryError("temporary", retryable=True, http_status=503),
            NotificationDeliveryError("temporary", retryable=True, http_status=503),
            NotificationDeliveryError("temporary", retryable=True, http_status=503),
        ]
    )
    worker = NotifierWorker(sender=sender, lease_seconds=30, max_attempts=3)

    assert worker.process_once(now="2026-03-29T11:00:00+08:00") is True
    failed = models.get_notification(row["id"])
    assert failed["status"] == "failed"
    assert failed["attempts"] == 1
    assert failed["last_http_status"] == 503

    assert worker.process_once(now="2026-03-29T11:01:00+08:00") is True
    failed = models.get_notification(row["id"])
    assert failed["status"] == "failed"
    assert failed["attempts"] == 2

    assert worker.process_once(now="2026-03-29T11:02:00+08:00") is True
    deadletter = models.get_notification(row["id"])
    assert deadletter["status"] == "deadletter"
    assert deadletter["attempts"] == 3


def test_notifier_worker_reclaims_expired_claims(notifier_db):
    from qbu_crawler.server.notifier import NotifierWorker

    row = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-reclaim",
            "payload": {"task_id": "task-reclaim"},
            "dedupe_key": "task-reclaim:completed",
            "payload_hash": "hash-reclaim",
        }
    )
    claimed = models.claim_next_notification(
        claim_token="stale-claim",
        claimed_at="2026-03-29T10:00:00+08:00",
        lease_until="2026-03-29T10:00:30+08:00",
    )
    assert claimed["id"] == row["id"]

    sender = _FakeSender([{"bridge_request_id": "req-reclaim", "http_status": 200}])
    worker = NotifierWorker(sender=sender, lease_seconds=30, max_attempts=3)

    assert worker.process_once(now="2026-03-29T10:01:00+08:00") is True
    stored = models.get_notification(row["id"])
    assert stored["status"] == "sent"
    assert stored["bridge_request_id"] == "req-reclaim"


def test_bridge_rejects_disallowed_source():
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"chat:cid-bridge"},
            command=["openclaw", "message", "send"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/notify",
        headers={
            "X-Bridge-Token": "secret",
            "X-Forwarded-For": "10.0.0.2",
        },
        json={
            "target": "chat:cid-bridge",
            "template_key": "task_completed",
            "template_vars": {"task_type": "scrape", "status": "completed"},
            "dedupe_key": "bridge-source-test",
        },
    )

    assert response.status_code == 403


def test_bridge_rejects_auth_failure():
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"chat:cid-bridge"},
            command=["openclaw", "message", "send"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/notify",
        headers={
            "X-Bridge-Token": "wrong",
            "X-Forwarded-For": "10.0.0.1",
        },
        json={
            "target": "chat:cid-bridge",
            "template_key": "task_completed",
            "template_vars": {"task_type": "scrape", "status": "completed"},
            "dedupe_key": "bridge-auth-test",
        },
    )

    assert response.status_code == 401


def test_bridge_cli_success():
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"chat:cid-bridge"},
            command=["openclaw", "message", "send"],
        )
    )
    client = TestClient(app)

    with patch("qbu_crawler.server.openclaw.bridge.app.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["openclaw"],
            returncode=0,
            stdout='{"message_id":"msg-1"}',
            stderr="",
        )
        response = client.post(
            "/notify",
            headers={
                "X-Bridge-Token": "secret",
                "X-Forwarded-For": "10.0.0.1",
            },
            json={
                "target": "chat:cid-bridge",
                "template_key": "task_completed",
                "template_vars": {"task_type": "scrape", "status": "completed"},
                "dedupe_key": "bridge-cli-success",
            },
        )

    assert response.status_code == 200
    assert response.json()["bridge_request_id"] == "msg-1"
    mock_run.assert_called_once()


def test_bridge_cli_failure():
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"chat:cid-bridge"},
            command=["openclaw", "message", "send"],
        )
    )
    client = TestClient(app)

    with patch("qbu_crawler.server.openclaw.bridge.app.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["openclaw"],
            returncode=1,
            stdout="",
            stderr="delivery failed",
        )
        response = client.post(
            "/notify",
            headers={
                "X-Bridge-Token": "secret",
                "X-Forwarded-For": "10.0.0.1",
            },
            json={
                "target": "chat:cid-bridge",
                "template_key": "task_completed",
                "template_vars": {"task_type": "scrape", "status": "completed"},
                "dedupe_key": "bridge-cli-failure",
            },
        )

    assert response.status_code == 502


def test_openclaw_bridge_sender_success(monkeypatch):
    from qbu_crawler.server.notifier import OpenClawBridgeSender

    sender = OpenClawBridgeSender("http://bridge.local/notify", auth_token="secret", timeout=10)
    notification = {
        "id": 1,
        "kind": "task_completed",
        "target": "chat:cid-bridge",
        "payload": {
            "task_id": "task-1",
            "task_type": "scrape",
            "status": "completed",
            "result": {"products_saved": 2},
        },
    }

    response_mock = MagicMock()
    response_mock.read.return_value = b'{"bridge_request_id":"bridge-1","http_status":200}'
    response_mock.__enter__.return_value = response_mock
    response_mock.__exit__.return_value = False

    with patch("qbu_crawler.server.notifier.urllib.request.urlopen", return_value=response_mock) as mock_urlopen:
        result = sender.send(notification)

    assert result["bridge_request_id"] == "bridge-1"
    assert result["http_status"] == 200

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "http://bridge.local/notify"
    assert request.headers["X-bridge-token"] == "secret"


def test_openclaw_bridge_sender_classifies_retryable_and_permanent_failures():
    from qbu_crawler.server.notifier import NotificationDeliveryError, OpenClawBridgeSender

    sender = OpenClawBridgeSender("http://bridge.local/notify", auth_token="secret", timeout=10)
    notification = {
        "id": 1,
        "kind": "task_completed",
        "target": "chat:cid-bridge",
        "payload": {"task_id": "task-1", "task_type": "scrape", "status": "completed"},
    }

    with patch(
        "qbu_crawler.server.notifier.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url="http://bridge.local/notify",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        ),
    ):
        with pytest.raises(NotificationDeliveryError) as transient:
            sender.send(notification)

    assert transient.value.retryable is True
    assert transient.value.http_status == 503

    with patch(
        "qbu_crawler.server.notifier.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url="http://bridge.local/notify",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        ),
    ):
        with pytest.raises(NotificationDeliveryError) as permanent:
            sender.send(notification)

    assert permanent.value.retryable is False
    assert permanent.value.http_status == 403
