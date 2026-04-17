"""Notification outbox model tests."""

import sqlite3
import subprocess
import urllib.error
from datetime import timedelta
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


def test_completion_notification_outbox_payload_is_human_contextualized(monkeypatch):
    from qbu_crawler.server import task_manager as task_manager_module

    manager = task_manager_module.TaskManager(max_workers=1)
    task = task_manager_module.Task(
        type="scrape",
        params={
            "urls": ["https://waltons.com/waltons-meat-tenderizer/"],
            "ownership": "competitor",
        },
        reply_to="chat:cid-1",
    )
    task.status = task_manager_module.TaskStatus.completed
    task.result = {"products_saved": 1, "reviews_saved": 0}
    manager._tasks[task.id] = task

    monkeypatch.setattr(task_manager_module.config, "NOTIFICATION_MODE", "outbox")

    with patch.object(task_manager_module.models, "enqueue_notification") as mock_enqueue:
        manager._notify_completion(task.id)

    payload = mock_enqueue.call_args.args[0]["payload"]
    assert payload["task_type"] == "scrape"
    assert payload["site"] == "waltons"
    assert payload["ownership"] == "competitor"
    assert payload["target_summary"] == "Waltons Meat Tenderizer"
    assert payload["result_summary"] == "产品信息已刷新，未发现新评论"
    assert payload["product_count"] == 1
    assert payload["review_count"] == 0

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


def test_bridge_normalizes_dingtalk_group_target_for_cli():
    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, _send_via_openclaw

    settings = BridgeSettings(
        auth_token="secret",
        allowed_sources=set(),
        allowed_targets=set(),
        command=["openclaw", "message", "send"],
        channel="dingtalk",
    )

    with patch("qbu_crawler.server.openclaw.bridge.app.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["openclaw"],
            returncode=0,
            stdout='{"message_id":"msg-group"}',
            stderr="",
        )

        result = _send_via_openclaw(settings, "chat:cid-group", "group test")

    assert result["bridge_request_id"] == "msg-group"
    called_args = mock_run.call_args.args[0]
    assert "--target" in called_args
    assert called_args[called_args.index("--target") + 1] == "channel:cid-group"


def test_bridge_accepts_chat_target_when_allowlist_uses_channel_alias():
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"channel:cid-bridge"},
            command=["openclaw", "message", "send"],
            channel="dingtalk",
        )
    )
    client = TestClient(app)

    with patch("qbu_crawler.server.openclaw.bridge.app.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["openclaw"],
            returncode=0,
            stdout='{"message_id":"msg-allow"}',
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
                "dedupe_key": "bridge-allow-normalized",
            },
        )

    assert response.status_code == 200
    called_args = mock_run.call_args.args[0]
    assert called_args[called_args.index("--target") + 1] == "channel:cid-bridge"


@pytest.mark.parametrize(
    ("template_key", "template_vars", "expected_message"),
    [
        (
            "workflow_started",
            {
                "logical_date": "2026-03-31",
                "run_id": 7,
                "collect_count": 2,
                "scrape_count": 5,
            },
            (
                "## 🚀 每日任务已启动\n\n"
                "- **日期**：2026-03-31\n"
                "- **状态**：已触发\n"
                "- **workflow**：7\n"
                "- **分类采集任务**：2\n"
                "- **产品抓取任务**：5\n\n"
                "后续会继续跟进执行、快报和完整报告状态。"
            ),
        ),
        (
            "workflow_fast_report",
            {
                "logical_date": "2026-03-31",
                "run_id": 7,
                "products_count": 41,
                "reviews_count": 2464,
                "translated_count": 2464,
            },
            (
                "## 📊 每日快报已生成\n\n"
                "- **日期**：2026-03-31\n"
                "- **状态**：快报已生成\n"
                "- **workflow**：7\n"
                "- **产品数**：41\n"
                "- **已入库评论数**：2464\n"
                "- **翻译进度**：2464/2464\n\n"
                "完整版报告生成后会继续通知。"
            ),
        ),
        (
            "workflow_full_report",
            {
                "logical_date": "2026-03-31",
                "run_id": 7,
                "excel_path": "./reports/workflow-run-7-full-report.xlsx",
                "email_status": "success",
            },
            (
                "## ✅ 每日完整报告已生成\n\n"
                "- **日期**：2026-03-31\n"
                "- **状态**：完整报告已生成\n"
                "- **workflow**：7\n"
                "- **附件**：./reports/workflow-run-7-full-report.xlsx\n"
                "- **邮件发送**：已发送\n\n"
                "如需，我可以继续补充差评、价格波动和竞品对比解读。"
            ),
        ),
        (
            "workflow_full_report",
            {
                "logical_date": "2026-03-31",
                "run_id": 8,
                "excel_path": "./reports/workflow-run-8-full-report.xlsx",
                "email_status": "skipped",
            },
            (
                "## ✅ 每日完整报告已生成\n\n"
                "- **日期**：2026-03-31\n"
                "- **状态**：完整报告已生成\n"
                "- **workflow**：8\n"
                "- **附件**：./reports/workflow-run-8-full-report.xlsx\n"
                "- **邮件发送**：已跳过（无新增评论）\n\n"
                "如需，我可以继续补充差评、价格波动和竞品对比解读。"
            ),
        ),
        (
            "workflow_report_skipped",
            {
                "logical_date": "2026-04-14",
                "run_id": 9,
                "products_count": 41,
                "reviews_count": 0,
                "reason": "no_new_reviews",
            },
            (
                "## ✅ 每日任务已完成\n\n"
                "- **日期**：2026-04-14\n"
                "- **workflow**：9\n"
                "- **产品数**：41\n"
                "- **新增评论数**：0\n"
                "- **说明**：新增评论为 0，已跳过 Excel 生成和邮件发送"
            ),
        ),
    ],
)
def test_bridge_workflow_templates_use_icon_markdown_style(
    template_key,
    template_vars,
    expected_message,
):
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"chat:cid-bridge"},
            command=["openclaw", "message", "send"],
            channel="dingtalk",
        )
    )
    client = TestClient(app)

    with patch("qbu_crawler.server.openclaw.bridge.app.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["openclaw"],
            returncode=0,
            stdout='{"message_id":"msg-template"}',
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
                "template_key": template_key,
                "template_vars": template_vars,
                "dedupe_key": f"template-{template_key}",
            },
        )

    assert response.status_code == 200
    called_args = mock_run.call_args.args[0]
    assert called_args[called_args.index("--message") + 1] == expected_message


def test_bridge_task_completed_template_uses_human_summary():
    from fastapi.testclient import TestClient

    from qbu_crawler.server.openclaw.bridge.app import BridgeSettings, create_bridge_app

    app = create_bridge_app(
        BridgeSettings(
            auth_token="secret",
            allowed_sources={"10.0.0.1"},
            allowed_targets={"chat:cid-bridge"},
            command=["openclaw", "message", "send"],
            channel="dingtalk",
        )
    )
    client = TestClient(app)

    with patch("qbu_crawler.server.openclaw.bridge.app.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["openclaw"],
            returncode=0,
            stdout='{"message_id":"msg-task-complete"}',
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
                "template_vars": {
                    "task_heading": "✅ 抓取完成",
                    "task_type": "产品页抓取",
                    "task_id": "task-1",
                    "target_summary": "Waltons Meat Tenderizer",
                    "site": "Walton's",
                    "ownership": "竞品",
                    "result_summary": "产品信息已刷新，未发现新评论",
                    "product_count": "1",
                    "review_count": "0",
                    "failed_summary": "无",
                },
                "dedupe_key": "bridge-task-complete",
            },
        )

    assert response.status_code == 200
    called_args = mock_run.call_args.args[0]
    expected_message = (
        "## ✅ 抓取完成\n\n"
        "- **目标**：Waltons Meat Tenderizer\n"
        "- **站点**：Walton's\n"
        "- **归属**：竞品\n"
        "- **任务类型**：产品页抓取\n"
        "- **结果**：产品信息已刷新，未发现新评论\n\n"
        "### 本次产出\n"
        "- **产品记录**：1 个\n"
        "- **新增评论**：0 条\n"
        "- **失败项**：无\n\n"
        "- **任务 ID**：task-1"
    )
    assert called_args[called_args.index("--message") + 1] == expected_message


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


def test_openclaw_bridge_sender_translates_task_completed_payload_to_human_template_vars():
    from qbu_crawler.server.notifier import OpenClawBridgeSender

    sender = OpenClawBridgeSender("http://bridge.local/notify", auth_token="secret", timeout=10)
    template_vars = sender._template_vars_for(
        {
            "kind": "task_completed",
            "payload": {
                "task_id": "task-1",
                "task_type": "scrape",
                "status": "completed",
                "task_heading": "✅ 抓取完成",
                "site": "waltons",
                "ownership": "competitor",
                "target_summary": "Waltons Meat Tenderizer",
                "product_count": 1,
                "review_count": 0,
                "result_summary": "产品信息已刷新，未发现新评论",
                "failed_summary": "无",
            },
        }
    )

    assert template_vars["task_id"] == "task-1"
    assert template_vars["task_heading"] == "✅ 抓取完成"
    assert template_vars["task_type"] == "产品页抓取"
    assert template_vars["status"] == "completed"
    assert template_vars["target_summary"] == "Waltons Meat Tenderizer"
    assert template_vars["site"] == "Walton's"
    assert template_vars["ownership"] == "竞品"
    assert template_vars["result_summary"] == "产品信息已刷新，未发现新评论"
    assert template_vars["product_count"] == 1
    assert template_vars["review_count"] == 0
    assert template_vars["failed_summary"] == "无"


def test_openclaw_bridge_sender_sanitizes_none_paths_for_change_quiet_modes():
    """When report mode is change or quiet, excel_path/analytics_path/pdf_path
    may be None. _template_vars_for should sanitize them to empty strings
    so DingTalk messages don't show the literal string 'None' (Fix-1C)."""
    from qbu_crawler.server.notifier import OpenClawBridgeSender

    sender = OpenClawBridgeSender("http://bridge.local/notify", auth_token="secret", timeout=10)
    template_vars = sender._template_vars_for(
        {
            "kind": "workflow_full_report",
            "payload": {
                "run_id": 7,
                "logical_date": "2026-04-10",
                "snapshot_hash": "hash-change",
                "excel_path": None,
                "analytics_path": None,
                "pdf_path": None,
                "html_path": "/reports/change-report.html",
                "report_mode": "change",
                "email_status": "success",
            },
        }
    )

    assert template_vars["excel_path"] == "", "None excel_path should be sanitized to empty string"
    assert template_vars["analytics_path"] == "", "None analytics_path should be sanitized to empty string"
    assert template_vars["pdf_path"] == "", "None pdf_path should be sanitized to empty string"
    assert template_vars["html_path"] == "/reports/change-report.html", "Non-None paths should be preserved"
    assert template_vars["excel_path"] != "None", "Should not be the string 'None'"


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


# ---------------------------------------------------------------------------
# I3: cleanup_old_notifications wiring + Shanghai tz
# ---------------------------------------------------------------------------


def test_cleanup_old_notifications_removes_expired_delivered_rows(notifier_db):
    """Expired delivered rows are purged; fresh rows and non-delivered rows
    are kept. Cutoff uses Shanghai tz (now_shanghai - retention_days)."""
    from qbu_crawler import config as _config

    fresh = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-fresh",
            "payload": {"task_id": "task-fresh"},
            "dedupe_key": "task-fresh:completed",
            "payload_hash": "hash-fresh",
        }
    )
    old = models.enqueue_notification(
        {
            "kind": "task_completed",
            "channel": "dingtalk",
            "target": "chat:cid-old",
            "payload": {"task_id": "task-old"},
            "dedupe_key": "task-old:completed",
            "payload_hash": "hash-old",
        }
    )

    # Make the "old" row delivered + updated_at 31 days ago in Shanghai tz.
    old_ts = (_config.now_shanghai() - timedelta(days=31)).isoformat()
    # Make the "fresh" row delivered + updated_at today in Shanghai tz.
    fresh_ts = _config.now_shanghai().isoformat()

    conn = notifier_db()
    conn.execute(
        "UPDATE notification_outbox SET status = 'delivered', updated_at = ? WHERE id = ?",
        (old_ts, old["id"]),
    )
    conn.execute(
        "UPDATE notification_outbox SET status = 'delivered', updated_at = ? WHERE id = ?",
        (fresh_ts, fresh["id"]),
    )
    conn.commit()
    conn.close()

    removed = models.cleanup_old_notifications(retention_days=30)
    assert removed == 1

    assert models.get_notification(old["id"]) is None
    assert models.get_notification(fresh["id"]) is not None


def test_notifier_worker_calls_cleanup_on_interval(monkeypatch):
    """_maybe_cleanup is gated by NOTIFICATION_CLEANUP_INTERVAL_S via
    time.monotonic(). Calling it twice in a row must only trigger cleanup
    once; resetting _last_cleanup_ts should allow a second call."""
    from qbu_crawler.server.notifier import NotifierWorker
    from qbu_crawler.server import notifier as notifier_module

    class _DummySender:
        def send(self, notification):
            return {"bridge_request_id": "x", "http_status": 200}

    worker = NotifierWorker(sender=_DummySender(), lease_seconds=30, max_attempts=3)

    call_count = {"n": 0}

    def _stub(retention_days: int = 30):
        call_count["n"] += 1
        return 0

    monkeypatch.setattr(notifier_module.models, "cleanup_old_notifications", _stub)
    # Ensure the interval > 0 so gating is meaningful.
    monkeypatch.setattr(notifier_module.config, "NOTIFICATION_CLEANUP_INTERVAL_S", 3600)
    monkeypatch.setattr(notifier_module.config, "NOTIFICATION_RETENTION_DAYS", 30)

    # First call: _last_cleanup_ts == 0.0, must invoke cleanup.
    worker._maybe_cleanup()
    assert call_count["n"] == 1

    # Second call immediately: interval not elapsed, must NOT invoke cleanup.
    worker._maybe_cleanup()
    assert call_count["n"] == 1

    # Reset timestamp: next call should invoke cleanup again.
    worker._last_cleanup_ts = 0.0
    worker._maybe_cleanup()
    assert call_count["n"] == 2


def test_notifier_worker_cleanup_failure_is_non_fatal(monkeypatch):
    """If cleanup_old_notifications raises, _maybe_cleanup must not propagate
    the exception — the notifier loop must stay alive."""
    from qbu_crawler.server.notifier import NotifierWorker
    from qbu_crawler.server import notifier as notifier_module

    class _DummySender:
        def send(self, notification):
            return {"bridge_request_id": "x", "http_status": 200}

    worker = NotifierWorker(sender=_DummySender(), lease_seconds=30, max_attempts=3)

    def _boom(retention_days: int = 30):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(notifier_module.models, "cleanup_old_notifications", _boom)
    monkeypatch.setattr(notifier_module.config, "NOTIFICATION_CLEANUP_INTERVAL_S", 3600)
    monkeypatch.setattr(notifier_module.config, "NOTIFICATION_RETENTION_DAYS", 30)

    # Must not raise
    worker._maybe_cleanup()
    # Timestamp should still have advanced so we don't hammer the broken cleanup.
    assert worker._last_cleanup_ts > 0.0
