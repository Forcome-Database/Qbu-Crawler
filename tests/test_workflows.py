"""Workflow and rollout configuration tests."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from qbu_crawler import models


_FEATURE_FLAG_KEYS = (
    "NOTIFICATION_MODE",
    "DAILY_SUBMIT_MODE",
    "REPORT_MODE",
    "AI_DIGEST_MODE",
)


def _reload_config(monkeypatch: pytest.MonkeyPatch, **overrides: str):
    for key in _FEATURE_FLAG_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    import qbu_crawler.config as config_module

    return importlib.reload(config_module)


def test_config_feature_flag_defaults(monkeypatch: pytest.MonkeyPatch):
    config = _reload_config(monkeypatch)

    assert config.NOTIFICATION_MODE == "legacy"
    assert config.DAILY_SUBMIT_MODE == "openclaw"
    assert config.REPORT_MODE == "legacy"
    assert config.AI_DIGEST_MODE == "off"


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("NOTIFICATION_MODE", "outbox"),
        ("DAILY_SUBMIT_MODE", "crawler_systemd"),
        ("REPORT_MODE", "snapshot_fast_full"),
        ("AI_DIGEST_MODE", "async"),
    ],
)
def test_config_feature_flags_accept_valid_values(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
):
    config = _reload_config(monkeypatch, **{env_name: env_value})

    assert getattr(config, env_name) == env_value


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("NOTIFICATION_MODE", "bad"),
        ("DAILY_SUBMIT_MODE", "remote"),
        ("REPORT_MODE", "snapshot_only"),
        ("AI_DIGEST_MODE", "on"),
    ],
)
def test_config_feature_flags_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
):
    with pytest.raises(ValueError, match=env_name):
        _reload_config(monkeypatch, **{env_name: env_value})


@pytest.fixture()
def workflow_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "workflow.db")

    def _conn():
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(models, "get_conn", _conn)
    models.init_db()
    return _conn


def _save_running_task(task_id: str):
    _save_task(task_id, status="running")


def _save_task(
    task_id: str,
    status: str,
    *,
    updated_at: str = "2026-03-29T08:01:00+08:00",
    last_progress_at: str | None = "2026-03-29T08:01:00+08:00",
    finished_at: str | None = None,
    error: str | None = None,
):
    models.save_task(
        {
            "id": task_id,
            "type": "scrape",
            "status": status,
            "params": {"urls": ["https://example.com/p/1"]},
            "progress": {"total": 1, "completed": 0},
            "result": None,
            "error": error,
            "created_at": "2026-03-29T08:00:00+08:00",
            "started_at": "2026-03-29T08:00:05+08:00",
            "finished_at": finished_at,
            "reply_to": "",
            "notified_at": None,
            "updated_at": updated_at,
            "last_progress_at": last_progress_at,
            "worker_token": "worker-1",
            "system_error_code": None,
        }
    )


class TestTaskLiveness:
    def test_task_liveness_columns_exist(self, workflow_db):
        conn = workflow_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        conn.close()

        assert "updated_at" in cols
        assert "last_progress_at" in cols
        assert "worker_token" in cols
        assert "system_error_code" in cols

    def test_task_manager_persist_updates_liveness_fields(self, workflow_db, monkeypatch):
        from qbu_crawler.server.task_manager import Task, TaskManager, TaskStatus

        monkeypatch.setattr("qbu_crawler.server.task_manager.config.OPENCLAW_HOOK_URL", "")

        manager = TaskManager(max_workers=1)
        task = Task(type="scrape", params={"urls": ["https://example.com/p/1"]})
        task.status = TaskStatus.running
        task.worker_token = "worker-1"
        task.progress = {"total": 1, "completed": 0}

        manager._persist(task)

        conn = workflow_db()
        row = conn.execute(
            "SELECT status, worker_token, updated_at, last_progress_at FROM tasks WHERE id = ?",
            (task.id,),
        ).fetchone()
        conn.close()

        assert row["status"] == "running"
        assert row["worker_token"] == "worker-1"
        assert row["updated_at"]
        assert row["last_progress_at"]

        manager._executor.shutdown(wait=False, cancel_futures=True)

    def test_task_liveness_reconcile_marks_stale_running_task_lost(self, workflow_db):
        _save_running_task("task-stale")

        stale = models.list_stale_running_tasks("2026-03-29T08:10:00+08:00")
        assert [task["id"] for task in stale] == ["task-stale"]

        updated = models.mark_task_lost(
            "task-stale",
            error_code="worker_lost",
            error_message="Task worker heartbeat expired",
            finished_at="2026-03-29T08:10:00+08:00",
        )
        assert updated is True

        task = models.get_task("task-stale")
        assert task["status"] == "failed"
        assert task["system_error_code"] == "worker_lost"
        assert task["error"] == "Task worker heartbeat expired"
        assert task["finished_at"] == "2026-03-29T08:10:00+08:00"


class TestWorkflowModels:
    def test_workflow_run_report_phase_defaults_to_none(self, workflow_db):
        conn = workflow_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        conn.close()

        assert "report_phase" in cols

        run = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "pending",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29:phase",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )

        assert run["report_phase"] == "none"

    def test_workflow_run_trigger_key_is_idempotent(self, workflow_db):
        first = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "pending",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )
        second = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "pending",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )

        assert second["id"] == first["id"]

        conn = workflow_db()
        count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        conn.close()
        assert count == 1

    def test_workflow_run_task_unique_per_run(self, workflow_db):
        run = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "pending",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )
        _save_running_task("task-for-run")

        first = models.attach_task_to_workflow(
            run_id=run["id"],
            task_id="task-for-run",
            task_type="scrape",
            site="basspro",
            ownership="own",
        )
        second = models.attach_task_to_workflow(
            run_id=run["id"],
            task_id="task-for-run",
            task_type="scrape",
            site="basspro",
            ownership="own",
        )

        assert second["id"] == first["id"]

        conn = workflow_db()
        count = conn.execute("SELECT COUNT(*) FROM workflow_run_tasks").fetchone()[0]
        conn.close()
        assert count == 1


class _StubSubmitter:
    def __init__(self):
        self.collect_calls = []
        self.scrape_calls = []
        self._counter = 0

    def _task(self, prefix: str, task_type: str):
        self._counter += 1
        task_id = f"{prefix}-{self._counter}"
        models.save_task(
            {
                "id": task_id,
                "type": task_type,
                "status": "pending",
                "params": {},
                "progress": {},
                "result": None,
                "error": None,
                "created_at": "2026-03-29T08:00:00+08:00",
                "updated_at": "2026-03-29T08:00:00+08:00",
                "last_progress_at": None,
                "worker_token": None,
                "system_error_code": None,
                "started_at": None,
                "finished_at": None,
                "reply_to": "",
                "notified_at": None,
            }
        )
        return SimpleNamespace(id=task_id)

    def submit_collect(self, category_url: str, ownership: str, max_pages: int = 0, reply_to: str = ""):
        self.collect_calls.append(
            {
                "category_url": category_url,
                "ownership": ownership,
                "max_pages": max_pages,
                "reply_to": reply_to,
            }
        )
        return self._task("collect", "collect")

    def submit_scrape(self, urls: list[str], ownership: str, reply_to: str = ""):
        self.scrape_calls.append(
            {
                "urls": list(urls),
                "ownership": ownership,
                "reply_to": reply_to,
            }
        )
        return self._task("scrape", "scrape")


def _write_csv(path: Path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestDailySubmit:
    def test_daily_submit_same_logical_date_returns_existing_run(self, workflow_db, tmp_path):
        from qbu_crawler.server.workflows import submit_daily_run

        source_csv = _write_csv(
            tmp_path / "source.csv",
            [
                "url,ownership",
                "https://www.basspro.com/shop/en/camping,own",
            ],
        )
        detail_csv = _write_csv(
            tmp_path / "detail.csv",
            [
                "url,ownership",
                "https://www.basspro.com/shop/en/example-product-1,own",
                "https://www.basspro.com/shop/en/example-product-2,own",
            ],
        )
        submitter = _StubSubmitter()

        first = submit_daily_run(
            submitter=submitter,
            source_csv=source_csv,
            detail_csv=detail_csv,
            logical_date="2026-03-29",
            requested_by="systemd",
        )
        second = submit_daily_run(
            submitter=submitter,
            source_csv=source_csv,
            detail_csv=detail_csv,
            logical_date="2026-03-29",
            requested_by="systemd",
        )

        assert first["created"] is True
        assert second["created"] is False
        assert second["run"]["id"] == first["run"]["id"]
        assert first["run"]["report_phase"] == "none"
        assert len(submitter.collect_calls) == 1
        assert len(submitter.scrape_calls) == 1

        conn = workflow_db()
        run_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        outbox_count = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
        conn.close()
        assert run_count == 1
        assert outbox_count == 1

    def test_daily_submit_invalid_csv_does_not_create_run(self, workflow_db, tmp_path):
        from qbu_crawler.server.daily_inputs import DailyInputValidationError
        from qbu_crawler.server.workflows import submit_daily_run

        source_csv = _write_csv(
            tmp_path / "source.csv",
            [
                "url,ownership",
                "https://www.basspro.com/shop/en/camping,broken",
            ],
        )
        detail_csv = _write_csv(tmp_path / "detail.csv", ["url,ownership"])

        with pytest.raises(DailyInputValidationError):
            submit_daily_run(
                submitter=_StubSubmitter(),
                source_csv=source_csv,
                detail_csv=detail_csv,
                logical_date="2026-03-29",
                requested_by="systemd",
            )

        conn = workflow_db()
        run_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        outbox_count = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
        conn.close()
        assert run_count == 0
        assert outbox_count == 0


class TestWorkflowReconcile:
    def test_reconcile_marks_stale_running_task_and_run_needs_attention(self, workflow_db):
        from qbu_crawler.server.workflows import WorkflowWorker

        _save_running_task("task-stale-run")
        run = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "running",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29:stale",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )
        models.attach_task_to_workflow(run_id=run["id"], task_id="task-stale-run", task_type="scrape", site="basspro", ownership="own")

        worker = WorkflowWorker(task_stale_seconds=60)
        assert worker.process_once(now="2026-03-29T08:10:00+08:00") is True

        task = models.get_task("task-stale-run")
        refreshed = models.get_workflow_run(run["id"])
        notifications = models.list_notifications(statuses=["pending"])

        assert task["status"] == "failed"
        assert task["system_error_code"] == "worker_lost"
        assert refreshed["status"] == "needs_attention"
        assert any(item["kind"] == "workflow_attention" for item in notifications)

    def test_reconcile_advances_reporting_run_to_full_sent(self, workflow_db, monkeypatch, tmp_path):
        from qbu_crawler.server import workflows as workflows_module
        from qbu_crawler.server.workflows import WorkflowWorker

        _save_task(
            "task-complete-run",
            status="completed",
            last_progress_at="2026-03-29T08:05:00+08:00",
            finished_at="2026-03-29T08:05:00+08:00",
        )
        run = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "submitted",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29:complete",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )
        models.attach_task_to_workflow(run_id=run["id"], task_id="task-complete-run", task_type="scrape", site="basspro", ownership="own")

        snapshot_path = str(tmp_path / "snapshot.json")
        (tmp_path / "snapshot.json").write_text(
            '{"run_id": 1, "logical_date": "2026-03-29", "snapshot_hash": "hash-1", "products_count": 1, "reviews_count": 2, "translated_count": 1, "untranslated_count": 1}',
            encoding="utf-8",
        )
        monkeypatch.setattr(workflows_module.config, "WORKFLOW_NOTIFICATION_TARGET", "chat:cid-workflow")
        monkeypatch.setattr(workflows_module, "freeze_report_snapshot", lambda run_id, now=None: models.update_workflow_run(run_id, snapshot_path=snapshot_path, snapshot_hash="hash-1", snapshot_at=now))
        monkeypatch.setattr(workflows_module, "load_report_snapshot", lambda path: {"run_id": run["id"], "logical_date": "2026-03-29", "snapshot_hash": "hash-1", "products_count": 1, "reviews_count": 2, "translated_count": 1, "untranslated_count": 1})
        monkeypatch.setattr(workflows_module, "build_fast_report", lambda snapshot: dict(snapshot))
        monkeypatch.setattr(workflows_module, "generate_full_report_from_snapshot", lambda snapshot, send_email=True: {"snapshot_hash": snapshot["snapshot_hash"], "excel_path": str(tmp_path / "full.xlsx"), "email": {"success": True}})

        worker = WorkflowWorker(task_stale_seconds=60)
        assert worker.process_once(now="2026-03-29T08:10:00+08:00") is True

        refreshed = models.get_workflow_run(run["id"])
        notifications = models.list_notifications(statuses=["pending"])

        assert refreshed["status"] == "completed"
        assert refreshed["report_phase"] == "full_sent"
        assert refreshed["snapshot_hash"] == "hash-1"
        assert refreshed["excel_path"] == str(tmp_path / "full.xlsx")
        assert [item["kind"] for item in notifications if item["kind"].startswith("workflow_")] == [
            "workflow_fast_report",
            "workflow_full_report",
        ]

    def test_full_report_failure_leaves_fast_sent_snapshot_intact(self, workflow_db, monkeypatch, tmp_path):
        from qbu_crawler.server import workflows as workflows_module
        from qbu_crawler.server.workflows import WorkflowWorker

        _save_task(
            "task-fast-run",
            status="completed",
            last_progress_at="2026-03-29T08:05:00+08:00",
            finished_at="2026-03-29T08:05:00+08:00",
        )
        snapshot_path = str(tmp_path / "snapshot.json")
        Path(snapshot_path).write_text('{"snapshot_hash":"hash-fast"}', encoding="utf-8")
        run = models.create_workflow_run(
            {
                "workflow_type": "daily",
                "status": "reporting",
                "report_phase": "full_pending",
                "logical_date": "2026-03-29",
                "trigger_key": "daily:2026-03-29:full-fail",
                "data_since": "2026-03-29T00:00:00+08:00",
                "data_until": "2026-03-30T00:00:00+08:00",
                "snapshot_at": "2026-03-29T08:06:00+08:00",
                "snapshot_path": snapshot_path,
                "snapshot_hash": "hash-fast",
                "requested_by": "systemd",
                "service_version": "test",
            }
        )
        models.attach_task_to_workflow(run_id=run["id"], task_id="task-fast-run", task_type="scrape", site="basspro", ownership="own")

        monkeypatch.setattr(workflows_module.config, "WORKFLOW_NOTIFICATION_TARGET", "chat:cid-workflow")
        monkeypatch.setattr(workflows_module, "load_report_snapshot", lambda path: {"snapshot_hash": "hash-fast", "logical_date": "2026-03-29", "run_id": run["id"]})
        monkeypatch.setattr(workflows_module, "generate_full_report_from_snapshot", lambda snapshot, send_email=True: (_ for _ in ()).throw(RuntimeError("smtp exploded")))

        worker = WorkflowWorker(task_stale_seconds=60)
        assert worker.process_once(now="2026-03-29T08:10:00+08:00") is True

        refreshed = models.get_workflow_run(run["id"])

        assert refreshed["status"] == "needs_attention"
        assert refreshed["report_phase"] == "fast_sent"
        assert refreshed["snapshot_path"] == snapshot_path
        assert refreshed["snapshot_hash"] == "hash-fast"
