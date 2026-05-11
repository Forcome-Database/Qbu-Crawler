from qbu_crawler import config


def test_bootstrap_run_sends_email_when_enabled(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr(config, "REPORT_EMAIL_SEND_BOOTSTRAP", True, raising=False)

    decision = decide_business_email(
        run={"id": 9, "logical_date": "2026-05-07"},
        snapshot={"is_bootstrap": True, "reviews_count": 10},
        mode="full",
    )

    assert decision.send_email is True
    assert decision.cadence == "bootstrap"
    assert decision.report_window_type == "bootstrap"


def test_weekly_report_day_sends_weekly_email(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)
    monkeypatch.setattr(config, "AI_DIGEST_MODE", "off", raising=False)
    monkeypatch.setattr(config, "REPORT_WEEKLY_WINDOW_DAYS", 7, raising=False)

    decision = decide_business_email(
        run={"id": 2, "logical_date": "2026-05-04"},
        snapshot={"report_semantics": "incremental", "reviews_count": 3},
        mode="full",
    )

    assert decision.send_email is True
    assert decision.cadence == "weekly"
    assert decision.report_window_type == "weekly"
    assert decision.window_days == 7


def test_non_weekly_day_skips_business_email(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)
    monkeypatch.setattr(config, "AI_DIGEST_MODE", "off", raising=False)

    decision = decide_business_email(
        run={"id": 3, "logical_date": "2026-05-05"},
        snapshot={"report_semantics": "incremental", "reviews_count": 4},
        mode="full",
    )

    assert decision.send_email is False
    assert decision.reason == "weekly_cadence_skip"
    assert decision.report_window_type == "daily"


def test_workflow_email_status_from_decision_uses_business_friendly_skip_text():
    """A3 — _workflow_email_status_from_decision 把 weekly_cadence_skip 等
    技术词汇映射成业务用户能直接读懂的状态文本。"""
    from qbu_crawler.server.report_cadence import EmailDecision
    from qbu_crawler.server.workflows import _workflow_email_status_from_decision

    weekly_skip = EmailDecision(False, "weekly_cadence_skip", "weekly", "daily", 7)
    assert (
        _workflow_email_status_from_decision(weekly_skip, email_success=None, untranslated_count=0)
        == "已跳过（按周发送策略，今天非邮件发送日）"
    )

    disabled = EmailDecision(False, "email_disabled", "weekly", "daily", 7)
    assert (
        _workflow_email_status_from_decision(disabled, email_success=None, untranslated_count=0)
        == "已跳过（邮件功能已关闭）"
    )

    bootstrap_disabled = EmailDecision(False, "bootstrap_email_disabled", "bootstrap", "daily", 7)
    assert (
        _workflow_email_status_from_decision(bootstrap_disabled, email_success=None, untranslated_count=0)
        == "已跳过（监控起点邮件已关闭）"
    )

    # 未识别 reason 退回原始格式，保持可观测性
    unknown = EmailDecision(False, "future_unknown_reason", "weekly", "daily", 7)
    assert (
        _workflow_email_status_from_decision(unknown, email_success=None, untranslated_count=0)
        == "已跳过（future_unknown_reason）"
    )


def test_daily_cadence_keeps_existing_email_behavior(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "daily", raising=False)

    decision = decide_business_email(
        run={"id": 4, "logical_date": "2026-05-05"},
        snapshot={"report_semantics": "incremental", "reviews_count": 0},
        mode="quiet",
    )

    assert decision.send_email is True
    assert decision.cadence == "daily"


def test_email_force_disabled_overrides_weekly_cadence(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr(config, "REPORT_EMAIL_FORCE_DISABLED", True, raising=False)
    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)

    decision = decide_business_email(
        run={"id": 5, "logical_date": "2026-05-04"},
        snapshot={"is_bootstrap": True, "reviews_count": 10},
        mode="full",
    )

    assert decision.send_email is False
    assert decision.reason == "email_disabled"


def test_workflow_non_weekly_day_generates_local_report_without_email(tmp_path, monkeypatch):
    from qbu_crawler import models
    from qbu_crawler.server import workflows

    db = tmp_path / "weekly-skip.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr(config, "AI_DIGEST_MODE", "off", raising=False)
    monkeypatch.setattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)
    models.init_db()

    run_id = _seed_ready_run(models, logical_date="2026-05-05", trigger_key="weekly-skip")
    snapshot = _snapshot(run_id, logical_date="2026-05-05")
    calls = {}

    monkeypatch.setattr(workflows, "load_report_snapshot", lambda path: snapshot)
    monkeypatch.setattr(workflows, "_count_pending_translations_for_window", lambda *a, **k: 0)
    monkeypatch.setattr(workflows.models, "get_scrape_quality", lambda rid: {"total": 1})
    monkeypatch.setattr("qbu_crawler.server.report_snapshot.load_previous_report_context", lambda rid: ({}, {}))

    def fake_generate(snapshot_arg, send_email=True):
        calls["send_email"] = send_email
        calls["snapshot"] = snapshot_arg
        return _full_report_result()

    monkeypatch.setattr(workflows, "generate_report_from_snapshot", fake_generate)
    monkeypatch.setattr(workflows, "_enqueue_workflow_notification", lambda **kwargs: None)

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    worker._advance_run(run_id, "2026-05-05T01:00:00")

    assert calls["send_email"] is False
    assert calls["snapshot"]["report_window"]["type"] == "daily"
    assert models.get_workflow_run(run_id)["email_delivery_status"] == "skipped"


def test_workflow_weekly_day_uses_weekly_snapshot_and_sends_email(tmp_path, monkeypatch):
    from qbu_crawler import models
    from qbu_crawler.server import workflows

    db = tmp_path / "weekly-send.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)
    models.init_db()

    run_id = _seed_ready_run(models, logical_date="2026-05-04", trigger_key="weekly-send")
    snapshot = _snapshot(run_id, logical_date="2026-05-04")
    calls = {}

    monkeypatch.setattr(workflows, "load_report_snapshot", lambda path: snapshot)
    monkeypatch.setattr(workflows, "_count_pending_translations_for_window", lambda *a, **k: 0)
    monkeypatch.setattr(workflows.models, "get_scrape_quality", lambda rid: {"total": 1})
    monkeypatch.setattr("qbu_crawler.server.report_snapshot.load_previous_report_context", lambda rid: ({}, {}))

    def fake_build_windowed(snapshot_arg, *, window_type, window_days):
        calls["window_type"] = window_type
        result = dict(snapshot_arg)
        result["report_window"] = {"type": window_type, "label": "本周", "days": window_days}
        return result

    def fake_generate(snapshot_arg, send_email=True):
        calls["send_email"] = send_email
        calls["snapshot"] = snapshot_arg
        return _full_report_result()

    monkeypatch.setattr(workflows, "build_windowed_report_snapshot", fake_build_windowed, raising=False)
    monkeypatch.setattr(workflows, "generate_report_from_snapshot", fake_generate)
    monkeypatch.setattr(workflows, "_enqueue_workflow_notification", lambda **kwargs: None)

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    worker._advance_run(run_id, "2026-05-04T01:00:00")

    assert calls["window_type"] == "weekly"
    assert calls["send_email"] is True
    assert calls["snapshot"]["report_window"]["type"] == "weekly"
    assert models.get_workflow_run(run_id)["email_delivery_status"] == "sent"


def test_workflow_bootstrap_sends_baseline_without_weekly_window(tmp_path, monkeypatch):
    from qbu_crawler import models
    from qbu_crawler.server import workflows

    db = tmp_path / "bootstrap.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(config, "REPORT_EMAIL_CADENCE", "weekly", raising=False)
    models.init_db()

    run_id = _seed_ready_run(models, logical_date="2026-05-04", trigger_key="bootstrap")
    snapshot = _snapshot(run_id, logical_date="2026-05-04")
    calls = {"windowed": False}

    monkeypatch.setattr(workflows, "load_report_snapshot", lambda path: snapshot)
    monkeypatch.setattr(workflows, "_count_pending_translations_for_window", lambda *a, **k: 0)
    monkeypatch.setattr(workflows.models, "get_scrape_quality", lambda rid: {"total": 1})
    monkeypatch.setattr("qbu_crawler.server.report_snapshot.load_previous_report_context", lambda rid: (None, None))

    def fake_build_windowed(*args, **kwargs):
        calls["windowed"] = True
        return args[0]

    def fake_generate(snapshot_arg, send_email=True):
        calls["send_email"] = send_email
        calls["snapshot"] = snapshot_arg
        return _full_report_result()

    monkeypatch.setattr(workflows, "build_windowed_report_snapshot", fake_build_windowed, raising=False)
    monkeypatch.setattr(workflows, "generate_report_from_snapshot", fake_generate)
    monkeypatch.setattr(workflows, "_enqueue_workflow_notification", lambda **kwargs: None)

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    worker._advance_run(run_id, "2026-05-04T01:00:00")

    assert calls["windowed"] is False
    assert calls["send_email"] is True
    assert calls["snapshot"]["report_window"]["type"] == "bootstrap"


def _seed_ready_run(models_module, *, logical_date, trigger_key):
    conn = models_module.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO workflow_runs (
                workflow_type, logical_date, status, report_phase, trigger_key,
                data_since, data_until, snapshot_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "daily",
                logical_date,
                "reporting",
                "full_pending",
                trigger_key,
                f"{logical_date}T00:00:00+08:00",
                f"{logical_date}T23:59:59+08:00",
                "/tmp/fake-snapshot.json",
            ),
        )
        run_id = cur.lastrowid
        cur.execute(
            "INSERT INTO tasks (id, type, status, params, finished_at) VALUES (?, ?, ?, ?, ?)",
            (f"t-{run_id}", "scrape", "completed", "{}", f"{logical_date}T01:00:00"),
        )
        cur.execute(
            "INSERT INTO workflow_run_tasks (run_id, task_id, task_type, site, ownership) VALUES (?, ?, ?, ?, ?)",
            (run_id, f"t-{run_id}", "scrape", "basspro", "own"),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def _snapshot(run_id, *, logical_date):
    return {
        "run_id": run_id,
        "logical_date": logical_date,
        "data_since": f"{logical_date}T00:00:00+08:00",
        "data_until": f"{logical_date}T23:59:59+08:00",
        "snapshot_hash": "hash",
        "products": [],
        "reviews": [],
        "products_count": 0,
        "reviews_count": 0,
        "translated_count": 0,
        "untranslated_count": 0,
        "cumulative": {"products": [], "reviews": [], "products_count": 0, "reviews_count": 0},
    }


def _full_report_result():
    return {
        "snapshot_hash": "hash",
        "excel_path": "report.xlsx",
        "analytics_path": "analytics.json",
        "html_path": "report.html",
        "mode": "full",
        "email": {"success": True, "error": None, "recipients": ["a@example.com"]},
    }
