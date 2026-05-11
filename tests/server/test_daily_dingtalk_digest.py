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
                "body_cn": "用一次开关就坏了",
                "analysis_labels": '[{"code":"after_sales","display":"售后履约"}]',
                "analysis_insight_cn": "自有产品出现低分质量信号，需要优先复核开关可靠性。",
            },
            {
                "id": 201,
                "product_sku": "CMP-1",
                "product_name": "Competitor Mixer",
                "ownership": "competitor",
                "rating": 5,
                "headline": "Easy",
                "body": "Very easy to clean",
                "body_cn": "非常容易清洁",
                "analysis_labels": '[{"code":"cleaning","display":"清洁便利"}]',
                "analysis_insight_cn": "竞品好评集中在清洁便利，可作为自有说明和结构优化参考。",
            },
        ],
    }

    digest = build_daily_digest(snapshot)

    assert digest["new_review_count"] == 2
    assert digest["own_top"][0]["sku"] == "OWN-1"
    assert digest["own_top"][0]["issue"] == "售后履约"
    assert digest["competitor_top"][0]["sku"] == "CMP-1"
    assert "清洁便利" in digest["analysis"]
    # 新格式：SKU 用反引号包裹；译文走 blockquote（无"译文："前缀）；原文以 emoji 锚带"原文："
    assert "`OWN-1`" in digest["markdown"]
    assert "用一次开关就坏了" in digest["markdown"]
    assert "Switch broke after one use" in digest["markdown"]


def test_daily_digest_top3_dedup_falls_back_to_same_sku_when_diversity_lacks():
    """SKU 多样性优先，但只有 1 个 SKU 时仍返回足额 TOP 3（回填同 SKU 次重要评论）。"""
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 21,
        "logical_date": "2026-05-08",
        "reviews_count": 4,
        "reviews": [
            {
                "id": 700 + i,
                "product_sku": "ONLY-1",
                "ownership": "own",
                "rating": 1,
                "headline": f"bad {i}",
                "body": f"failure mode #{i}",
                "body_cn": f"问题 #{i}",
                "analysis_labels": '[{"code":"struct","display":"结构设计"}]',
                "analysis_insight_cn": f"问题点 {i}",
            }
            for i in range(4)
        ],
    })

    # 只有 1 个 SKU 但有 4 条差评 → TOP 应该是 3 条而不是塌缩成 1 条
    assert len(digest["own_top"]) == 3
    assert all(item["sku"] == "ONLY-1" for item in digest["own_top"])
    assert "ONLY-1" in digest["markdown"]


def test_daily_digest_top3_dedup_prefers_sku_diversity_when_available():
    """多 SKU 场景下，TOP 3 优先选不同 SKU 各 1 条。"""
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 22,
        "logical_date": "2026-05-08",
        "reviews_count": 6,
        "reviews": [
            *[{
                "id": 800 + i, "product_sku": "SKU-A", "ownership": "own",
                "rating": 1, "headline": f"a{i}", "body": f"a body {i}",
                "body_cn": f"A 问题 {i}",
                "analysis_labels": '[{"code":"struct","display":"结构设计"}]',
            } for i in range(4)],
            {
                "id": 901, "product_sku": "SKU-B", "ownership": "own",
                "rating": 1, "body": "b body", "body_cn": "B 问题",
                "analysis_labels": '[{"code":"ship","display":"包装运输"}]',
            },
            {
                "id": 902, "product_sku": "SKU-C", "ownership": "own",
                "rating": 1, "body": "c body", "body_cn": "C 问题",
                "analysis_labels": '[{"code":"clean","display":"清洁维护"}]',
            },
        ],
    })

    skus = [item["sku"] for item in digest["own_top"]]
    assert len(skus) == 3
    assert set(skus) == {"SKU-A", "SKU-B", "SKU-C"}, f"expected each SKU once, got {skus}"


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
    assert digest["message_title"] == "今日无新增评论"
    assert digest["own_top"] == []
    assert digest["competitor_top"] == []
    assert "累计样本" in digest["analysis"]
    assert "今日无新增评论" in digest["markdown"]


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
    assert "`SKU-ONLY`" in digest["markdown"]
    assert "UNKNOWN" not in digest["markdown"]


def test_daily_digest_switches_to_own_highlights_when_only_own_positive_reviews():
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 12,
        "logical_date": "2026-05-07",
        "reviews_count": 1,
        "reviews": [{
            "id": 401,
            "product_sku": "OWN-GOOD",
            "product_name": "Own Good",
            "ownership": "own",
            "rating": 5,
            "headline": "Powerful",
            "body": "This grinder is powerful and easy to clean.",
            "body_cn": "这台绞肉机动力很强，也容易清洁。",
            "analysis_labels": '[{"code":"strong_performance","display":"性能强"}]',
            "analysis_insight_cn": "自有产品动力表现获得正向验证，可沉淀为卖点证据。",
        }],
        "cumulative": {"reviews": [{"ownership": "own"}]},
    })

    md = digest["markdown"]
    assert "自有亮点" in md and "TOP 3" in md
    assert "自有风险" not in md
    # 新格式：无竞品新增时整个竞品 section 被省略（不再显示空占位行）
    assert "竞品亮点" not in md and "竞品风险" not in md
    assert "性能强" in md
    assert "This grinder is powerful and easy to clean." in md
    assert "这台绞肉机动力很强，也容易清洁。" in md
    assert "自有产品动力表现获得正向验证" in md


def test_daily_digest_does_not_label_neutral_reviews_as_highlights():
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 13,
        "logical_date": "2026-05-07",
        "reviews_count": 1,
        "reviews": [{
            "id": 501,
            "product_sku": "OWN-NEUTRAL",
            "ownership": "own",
            "rating": 3,
            "headline": "Okay",
            "body": "It is okay for occasional use.",
            "body_cn": "偶尔使用还可以。",
        }],
    })

    md = digest["markdown"]
    assert "自有新增评论" in md
    assert "自有亮点" not in md
    assert "未分类" in md
    assert "自有新增评论集中在 OWN-NEUTRAL" in digest["analysis"]


def test_daily_digest_surfaces_neutral_review_counts_and_examples():
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 14,
        "logical_date": "2026-05-06",
        "reviews_count": 4,
        "reviews": [
            {
                "id": 601,
                "product_sku": "OWN-BAD",
                "ownership": "own",
                "rating": 2,
                "headline": "Noisy",
                "body": "It gets loud after a few batches.",
                "body_cn": "处理几批后噪音会变大。",
                "analysis_labels": '[{"code":"noise_power","display":"噪音与动力"}]',
                "analysis_insight_cn": "自有产品仍有噪音风险。",
            },
            {
                "id": 602,
                "product_sku": "OWN-MID",
                "ownership": "own",
                "rating": 3,
                "headline": "Okay",
                "body": "It works, but setup takes more time than expected.",
                "body_cn": "可以使用，但安装比预期更花时间。",
                "analysis_labels": '[{"code":"easy_to_use","display":"易上手"}]',
                "analysis_insight_cn": "中评分歧集中在安装体验。",
            },
            {
                "id": 603,
                "product_sku": "CMP-GOOD",
                "ownership": "competitor",
                "rating": 5,
                "headline": "Fast",
                "body": "It processes meat quickly.",
                "body_cn": "处理速度很快。",
                "analysis_labels": '[{"code":"strong_performance","display":"性能强"}]',
                "analysis_insight_cn": "竞品性能体验值得参考。",
            },
            {
                "id": 604,
                "product_sku": "CMP-MID",
                "ownership": "competitor",
                "rating": 3,
                "headline": "Average",
                "body": "The product is acceptable but not especially easy to clean.",
                "body_cn": "产品可以接受，但清洁并不算特别方便。",
                "analysis_labels": '[{"code":"cleaning_maintenance","display":"清洁维护"}]',
                "analysis_insight_cn": "竞品中评也提到清洁维护门槛。",
            },
        ],
    })

    md = digest["markdown"]
    # 顶部计数行（新格式：emoji + inline code 数字）
    assert "差评 自有 `1`" in md
    assert "好评 自有 `0`" in md
    assert "中评 自有 `1`" in md
    assert "差评" in md and "竞品 `0`" in md
    # 中评观察块
    assert "中评观察" in md
    assert "自有中评" in md
    assert "OWN-MID" in md and "易上手" in md
    assert "竞品中评" in md
    assert "CMP-MID" in md and "清洁维护" in md


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
    assert digest[0]["payload"]["message_title"] == "今日无新增评论"


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
