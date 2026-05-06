def test_daily_digest_builds_own_and_competitor_top3():
    from qbu_crawler.server.daily_digest import build_daily_digest

    snapshot = {
        "run_id": 9,
        "logical_date": "2026-05-07",
        "reviews_count": 2,
        "cumulative": {
            "reviews": [
                {"id": 1, "ownership": "own"},
                {"id": 2, "ownership": "competitor"},
            ]
        },
        "reviews": [
            {
                "id": 101,
                "product_sku": "OWN-1",
                "product_name": "Own Grinder",
                "ownership": "own",
                "rating": 1,
                "headline": "Broken",
                "body": "Switch broke after one use",
                "body_cn": "\u7528\u4e00\u6b21\u5f00\u5173\u5c31\u574f\u4e86",
                "analysis_labels": '[{"code":"after_sales","display":"\u552e\u540e\u5c65\u7ea6"}]',
                "analysis_insight_cn": "\u81ea\u6709\u4ea7\u54c1\u51fa\u73b0\u4f4e\u5206\u8d28\u91cf\u4fe1\u53f7\uff0c\u9700\u8981\u4f18\u5148\u590d\u6838\u5f00\u5173\u53ef\u9760\u6027\u3002",
            },
            {
                "id": 201,
                "product_sku": "CMP-1",
                "product_name": "Competitor Mixer",
                "ownership": "competitor",
                "rating": 5,
                "headline": "Easy",
                "body": "Very easy to clean",
                "body_cn": "\u975e\u5e38\u5bb9\u6613\u6e05\u6d01",
                "analysis_labels": '[{"code":"cleaning","display":"\u6e05\u6d01\u4fbf\u5229"}]',
                "analysis_insight_cn": "\u7ade\u54c1\u597d\u8bc4\u96c6\u4e2d\u5728\u6e05\u6d01\u4fbf\u5229\uff0c\u53ef\u4f5c\u4e3a\u81ea\u6709\u8bf4\u660e\u548c\u7ed3\u6784\u4f18\u5316\u53c2\u8003\u3002",
            },
        ],
    }

    digest = build_daily_digest(snapshot)

    assert digest["new_review_count"] == 2
    assert digest["own_top"][0]["sku"] == "OWN-1"
    assert digest["own_top"][0]["issue"] == "\u552e\u540e\u5c65\u7ea6"
    assert digest["competitor_top"][0]["sku"] == "CMP-1"
    assert "\u6e05\u6d01\u4fbf\u5229" in digest["analysis"]
    assert "SKU:OWN-1" in digest["markdown"]


def test_daily_digest_handles_no_new_reviews():
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 10,
        "logical_date": "2026-05-07",
        "reviews_count": 0,
        "reviews": [],
        "cumulative": {"reviews": [{"ownership": "own"}, {"ownership": "competitor"}]},
    })

    assert digest["new_review_count"] == 0
    assert digest["message_title"] == "\u4eca\u65e5\u65e0\u65b0\u589e\u8bc4\u8bba"
    assert digest["own_top"] == []
    assert digest["competitor_top"] == []
    assert "\u7d2f\u8ba1\u6837\u672c" in digest["analysis"]
    assert "\u4eca\u65e5\u65e0\u65b0\u589e\u8bc4\u8bba" in digest["markdown"]


def test_daily_digest_truncates_original_text_without_inventing_sku():
    from qbu_crawler.server.daily_digest import build_daily_digest

    long_body = "A" * 500
    digest = build_daily_digest({
        "run_id": 11,
        "logical_date": "2026-05-07",
        "reviews_count": 1,
        "reviews": [{
            "id": 301,
            "product_sku": "SKU-ONLY",
            "product_name": "Only Product",
            "ownership": "own",
            "rating": 2,
            "headline": "Long",
            "body": long_body,
        }],
    })

    text = digest["own_top"][0]["original"]
    assert len(text) <= 140
    assert "SKU:SKU-ONLY" in digest["markdown"]
    assert "UNKNOWN" not in digest["markdown"]


def test_workflow_enqueues_daily_digest_for_no_new_reviews(tmp_path, monkeypatch):
    from qbu_crawler import config, models
    from qbu_crawler.server import workflows

    db = tmp_path / "daily-digest.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(config, "AI_DIGEST_MODE", "off", raising=False)
    models.init_db()

    run_id = _seed_ready_run(models)
    snapshot = {
        "run_id": run_id,
        "logical_date": "2026-05-07",
        "data_since": "2026-05-07T00:00:00+08:00",
        "data_until": "2026-05-07T23:59:59+08:00",
        "snapshot_hash": "hash",
        "products": [],
        "reviews": [],
        "products_count": 0,
        "reviews_count": 0,
        "translated_count": 0,
        "untranslated_count": 0,
        "cumulative": {"reviews": [{"ownership": "own"}], "products": []},
    }
    notifications = []

    monkeypatch.setattr(workflows, "load_report_snapshot", lambda path: snapshot)
    monkeypatch.setattr(workflows, "_count_pending_translations_for_window", lambda *a, **k: 0)
    monkeypatch.setattr(workflows.models, "get_scrape_quality", lambda rid: {"total": 1})
    monkeypatch.setattr("qbu_crawler.server.report_snapshot.load_previous_report_context", lambda rid: ({}, {}))
    monkeypatch.setattr(workflows, "generate_report_from_snapshot", lambda *a, **k: {
        "snapshot_hash": "hash",
        "mode": "quiet",
        "email": {"success": True},
    })
    monkeypatch.setattr(workflows, "_enqueue_workflow_notification", lambda **kwargs: notifications.append(kwargs))

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    worker._advance_run(run_id, "2026-05-07T01:00:00")

    digest = [n for n in notifications if n["kind"] == "workflow_daily_digest"]
    assert digest
    assert digest[0]["dedupe_key"] == f"workflow:{run_id}:daily-digest"
    assert digest[0]["payload"]["message_title"] == "\u4eca\u65e5\u65e0\u65b0\u589e\u8bc4\u8bba"


def test_daily_digest_deadletter_does_not_downgrade_full_report(tmp_path, monkeypatch):
    from qbu_crawler import config, models
    from qbu_crawler.server.notifier import _sync_workflow_notification_status

    db = tmp_path / "daily-deadletter.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()

    conn = models.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO workflow_runs (
                workflow_type, logical_date, status, report_phase, trigger_key
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("daily", "2026-05-07", "completed", "full_sent", "digest-deadletter"),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    _sync_workflow_notification_status({
        "kind": "workflow_daily_digest",
        "payload": {"run_id": run_id},
        "status": "deadletter",
    })

    assert models.get_workflow_run(run_id)["report_phase"] == "full_sent"


def _seed_ready_run(models_module):
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
                "2026-05-07",
                "reporting",
                "full_pending",
                "digest",
                "2026-05-07T00:00:00+08:00",
                "2026-05-07T23:59:59+08:00",
                "/tmp/fake-snapshot.json",
            ),
        )
        run_id = cur.lastrowid
        cur.execute(
            "INSERT INTO tasks (id, type, status, params, finished_at) VALUES (?, ?, ?, ?, ?)",
            (f"t-{run_id}", "scrape", "completed", "{}", "2026-05-07T01:00:00"),
        )
        cur.execute(
            "INSERT INTO workflow_run_tasks (run_id, task_id, task_type, site, ownership) VALUES (?, ?, ?, ?, ?)",
            (run_id, f"t-{run_id}", "scrape", "basspro", "own"),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()
