"""Tests for canonical metric and time semantics in the data layer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from qbu_crawler import config, models
from qbu_crawler.server.scope import normalize_scope


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _insert_product(
    conn,
    *,
    url: str,
    site: str,
    name: str,
    sku: str,
    ownership: str,
    review_count: int,
    price: float,
    rating: float,
    scraped_at: str,
):
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, ownership, review_count, price, rating, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (url, site, name, sku, ownership, review_count, price, rating, scraped_at),
    )
    return conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()["id"]


def _insert_snapshot(conn, *, product_id: int, review_count: int, scraped_at: str):
    conn.execute(
        """
        INSERT INTO product_snapshots (product_id, review_count, scraped_at)
        VALUES (?, ?, ?)
        """,
        (product_id, review_count, scraped_at),
    )


def _insert_review(
    conn,
    *,
    product_id: int,
    author: str,
    headline: str,
    body: str,
    rating: int,
    date_published: str,
    scraped_at: str,
    images: list[str] | None = None,
):
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, images, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            author,
            headline,
            body,
            f"hash-{product_id}-{author}-{headline}",
            rating,
            date_published,
            json.dumps(images) if images is not None else None,
            scraped_at,
        ),
    )


@pytest.fixture()
def metric_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "metric-semantics.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()

    conn = _get_test_conn(db_file)
    own_product_id = _insert_product(
        conn,
        url="https://example.com/products/own",
        site="basspro",
        name="Own Product",
        sku="SKU-OWN",
        ownership="own",
        review_count=120,
        price=499.99,
        rating=4.6,
        scraped_at="2026-03-02 09:00:00",
    )
    competitor_product_id = _insert_product(
        conn,
        url="https://example.com/products/competitor",
        site="waltons",
        name="Competitor Product",
        sku="SKU-COMP",
        ownership="competitor",
        review_count=80,
        price=299.99,
        rating=4.2,
        scraped_at="2026-03-03 10:00:00",
    )

    _insert_snapshot(conn, product_id=own_product_id, review_count=100, scraped_at="2026-03-01 08:00:00")
    _insert_snapshot(conn, product_id=competitor_product_id, review_count=70, scraped_at="2026-03-01 08:30:00")

    _insert_review(
        conn,
        product_id=own_product_id,
        author="Alice",
        headline="Own review",
        body="solid",
        rating=2,
        date_published="2026-02-28",
        scraped_at="2026-03-02 12:00:00",
    )
    _insert_review(
        conn,
        product_id=competitor_product_id,
        author="Bob",
        headline="Competitor review",
        body="competitor body",
        rating=1,
        date_published="2026-03-01",
        scraped_at="2026-03-03 12:30:00",
        images=["https://img.example.com/1.jpg"],
    )
    _insert_review(
        conn,
        product_id=competitor_product_id,
        author="Cara",
        headline="Competitor review 2",
        body="competitor follow up",
        rating=2,
        date_published="2026-03-02",
        scraped_at="2026-03-03 13:00:00",
    )
    conn.commit()
    conn.close()
    return db_file


def test_get_stats_distinguishes_ingested_rows_from_site_reported_totals(metric_db):
    stats = models.get_stats()

    assert stats["product_count"] == 2
    assert stats["ingested_review_rows"] == 3
    assert stats["site_reported_review_total_current"] == 200

    # Backward-compatible aliases still point to the canonical values.
    assert stats["total_products"] == stats["product_count"]
    assert stats["total_reviews"] == stats["ingested_review_rows"]


def test_preview_scope_counts_distinguish_product_count_from_matched_review_product_count(metric_db):
    scope = normalize_scope(
        products={"sites": ["basspro", "waltons"]},
        reviews={"keyword": "competitor"},
        window={"since": "2026-03-01", "until": "2026-03-03"},
    )

    counts = models.preview_scope_counts(scope)

    assert counts["product_count"] == 2
    assert counts["matched_review_product_count"] == 1
    assert counts["ingested_review_rows"] == 2
    assert counts["image_review_rows"] == 1

    # Backward-compatible preview aliases stay available for existing callers.
    assert counts["matched_product_count"] == 1
    assert counts["matched_review_count"] == 2
    assert counts["matched_image_review_count"] == 1


def test_time_axis_helpers_expose_canonical_fields_and_latest_values(metric_db):
    time_axes = models.get_time_axis_semantics()

    assert time_axes["product_state_time"]["field"] == "products.scraped_at"
    assert time_axes["product_state_time"]["latest"] == "2026-03-03 10:00:00"
    assert time_axes["snapshot_time"]["field"] == "product_snapshots.scraped_at"
    assert time_axes["snapshot_time"]["latest"] == "2026-03-01 08:30:00"
    assert time_axes["review_ingest_time"]["field"] == "reviews.scraped_at"
    assert time_axes["review_ingest_time"]["latest"] == "2026-03-03 13:00:00"
    assert time_axes["review_publish_time"]["field"] == "reviews.date_published"
    assert time_axes["review_publish_time"]["latest"] == "2026-03-02"


def test_report_analytics_keeps_ingested_and_site_total_separate(metric_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    analytics = build_report_analytics(
        {
            "run_id": 999,
            "logical_date": "2026-03-03",
            "snapshot_hash": "hash-metrics",
            "products_count": 2,
            "reviews_count": 2,
            "translated_count": 2,
            "untranslated_count": 0,
            "products": [
                {
                    "name": "Own Product",
                    "sku": "SKU-OWN",
                    "site": "basspro",
                    "ownership": "own",
                    "review_count": 7,
                    "rating": 4.6,
                    "price": 499.99,
                },
                {
                    "name": "Competitor Product",
                    "sku": "SKU-COMP",
                    "site": "waltons",
                    "ownership": "competitor",
                    "review_count": 3,
                    "rating": 4.2,
                    "price": 299.99,
                },
            ],
            "reviews": [
                {
                    "product_name": "Own Product",
                    "product_sku": "SKU-OWN",
                    "author": "Alice",
                    "headline": "Broken",
                    "body": "The motor broke quickly.",
                    "rating": 2,
                    "date_published": "2026-03-02",
                    "images": [],
                    "ownership": "own",
                    "headline_cn": "",
                    "body_cn": "",
                    "translate_status": "done",
                },
                {
                    "product_name": "Competitor Product",
                    "product_sku": "SKU-COMP",
                    "author": "Bob",
                    "headline": "Easy",
                    "body": "Easy to use and worth the money.",
                    "rating": 5,
                    "date_published": "2026-03-02",
                    "images": [],
                    "ownership": "competitor",
                    "headline_cn": "",
                    "body_cn": "",
                    "translate_status": "done",
                },
            ],
        }
    )

    assert analytics["kpis"]["ingested_review_rows"] == 2
    assert analytics["kpis"]["site_reported_review_total_current"] == 10


def test_change_digest_counts_fresh_reviews_and_backfill_from_publish_time():
    from qbu_crawler.server.report_snapshot import build_change_digest

    digest = build_change_digest(
        {
            "logical_date": "2026-03-30",
            "reviews": [
                {"ownership": "own", "rating": 2, "date_published": "2026-03-29"},
                {"ownership": "competitor", "rating": 5, "date_published": "2026-03-20"},
                {"ownership": "own", "rating": 1, "date_published": "2026-01-15"},
            ],
            "products": [],
            "untranslated_count": 0,
        },
        {
            "report_semantics": "bootstrap",
            "kpis": {"untranslated_count": 0},
            "self": {"top_negative_clusters": []},
        },
    )

    assert digest["summary"]["ingested_review_count"] == 3
    assert digest["summary"]["fresh_review_count"] == 2
    assert digest["summary"]["historical_backfill_count"] == 1
    assert digest["summary"]["fresh_own_negative_count"] == 1


def test_change_digest_marks_backfill_dominant_at_seventy_percent():
    from qbu_crawler.server.report_snapshot import build_change_digest

    reviews = [
        {
            "ownership": "own" if idx % 2 == 0 else "competitor",
            "rating": 4,
            "date_published": "2025-12-01",
        }
        for idx in range(7)
    ] + [
        {
            "ownership": "own",
            "rating": 3,
            "date_published": "2026-03-2%s" % idx,
        }
        for idx in range(7, 10)
    ]

    digest = build_change_digest(
        {
            "logical_date": "2026-03-30",
            "reviews": reviews,
            "products": [],
            "untranslated_count": 0,
        },
        {
            "report_semantics": "bootstrap",
            "kpis": {"untranslated_count": 0},
            "self": {"top_negative_clusters": []},
        },
    )

    assert digest["summary"]["ingested_review_count"] == 10
    assert digest["summary"]["fresh_review_count"] == 3
    assert digest["summary"]["historical_backfill_count"] == 7
    assert digest["warnings"]["backfill_dominant"]["enabled"] is True
    assert "70%" in digest["warnings"]["backfill_dominant"]["message"]


def test_change_digest_incremental_uses_empty_state_when_no_significant_changes():
    from qbu_crawler.server.report_snapshot import build_change_digest

    digest = build_change_digest(
        {
            "logical_date": "2026-03-30",
            "reviews": [
                {"ownership": "own", "rating": 3, "date_published": "2026-01-15"},
            ],
            "products": [
                {"sku": "SKU-1", "name": "Stable Product", "price": 199.0, "stock_status": "in_stock", "rating": 4.2},
            ],
            "untranslated_count": 0,
        },
        {
            "report_semantics": "incremental",
            "kpis": {"untranslated_count": 0},
            "self": {"top_negative_clusters": []},
        },
        {
            "products": [
                {"sku": "SKU-1", "name": "Stable Product", "price": 199.0, "stock_status": "in_stock", "rating": 4.2},
            ],
        },
        {"self": {"top_negative_clusters": []}},
    )

    assert digest["view_state"] == "empty"
    assert digest["summary"]["state_change_count"] == 0
    assert digest["review_signals"]["fresh_negative_reviews"] == []
    assert digest["empty_state"]["enabled"] is True


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_grep(repo_root, pattern, paths, use_extended_regex=False):
    """Helper: 跑 `git grep` 返回 (offending_files, returncode)。
    git grep 在 Windows 上对绝对 pathspec 不友好，统一用相对路径；
    returncode 处理：0=有匹配，1=无匹配，其它=git error 必须 skip 测试。"""
    import subprocess
    cmd = ["git", "grep", "-l"]
    if use_extended_regex:
        cmd.append("-E")
    cmd.append(pattern)
    cmd.append("--")
    cmd.extend(paths)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(repo_root), timeout=30
        )
    except subprocess.TimeoutExpired:
        import pytest
        pytest.skip("git grep timed out (>30s) — likely stalled, skipping contract gate")
    if result.returncode not in (0, 1):
        import pytest
        pytest.skip(
            f"git grep failed with returncode={result.returncode}: "
            f"stderr={result.stderr.strip()!r}"
        )
    files = result.stdout.strip().splitlines() if result.returncode == 0 else []
    return files, result.returncode


def test_phase2_t9_no_kpis_v2_or_metric_new_keys():
    """Phase 2 进行中禁改清单 (Continuity §🧊):
    不得新增第二套 KPI（kpis_v2 / metric_new_*）。"""
    repo_root = _REPO_ROOT
    # 用相对仓库根的 pathspec，避免 Windows 绝对路径让 git grep 报 returncode=128
    targets = ["qbu_crawler/", "tests/"]

    for pattern in ("kpis_v2", "metric_new_"):
        offending, _ = _git_grep(repo_root, pattern, targets)
        import os
        offending = [
            f for f in offending
            if os.path.basename(f) != "test_metric_semantics.py"
        ]
        assert not offending, \
            f"Phase 2 禁止引入第二套 KPI 命名 {pattern!r}，违规文件: {offending}"


def test_trend_template_consumes_secondary_charts_only_from_trend_digest():
    """P1 起模板可以展示 secondary_charts，但只能通过 trend_block 读取。"""
    repo_root = _REPO_ROOT
    targets = ["qbu_crawler/server/report_templates/daily_report_v3.html.j2"]

    consumers, _ = _git_grep(repo_root, "secondary_charts", targets)
    assert consumers == ["qbu_crawler/server/report_templates/daily_report_v3.html.j2"]

    offending, _ = _git_grep(
        repo_root,
        r"analytics\..*secondary_charts|_trend_series.*secondary_charts|window.*secondary_charts|cumulative_kpis.*secondary_charts",
        targets,
        use_extended_regex=True,
    )
    assert not offending, f"secondary_charts 必须经 trend_block 读取，违规: {offending}"


def test_phase2_t9_template_does_not_bypass_trend_digest():
    """Phase 2 进行中禁改清单 (Continuity §🧊):
    模板不得绕过 trend_digest 直接读 analytics.window / analytics._trend_series / cumulative_kpis。"""
    repo_root = _REPO_ROOT
    targets = ["qbu_crawler/server/report_templates/"]

    for pattern in (r"analytics\.window", r"analytics\._trend_series", r"cumulative_kpis"):
        offending, _ = _git_grep(repo_root, pattern, targets, use_extended_regex=True)
        assert not offending, \
            f"模板禁止直接读 {pattern!r}（必须经 trend_digest），违规: {offending}"


def test_report_outputs_do_not_expose_legacy_new_review_column():
    repo_root = _REPO_ROOT
    targets = ["qbu_crawler/server/report.py", "qbu_crawler/server/report_templates/"]

    offending, _ = _git_grep(repo_root, "本次新增", targets)

    assert not offending, f"生产报告代码不得再暴露旧列名“本次新增”，违规: {offending}"


def test_phase2_t9_phase1_trend_digest_keys_unchanged():
    """Phase 2 T9 契约不变量：trend_digest 顶层 views/dimensions/default_view/default_dimension
    与 Phase 1 完全一致。data[view][dim] 子层 Phase 1 5 键 (kpis/primary_chart/status/
    status_message/table) 必须仍然存在。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest
    snapshot = {"logical_date": "2026-04-25", "products": [], "reviews": []}
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    assert sorted(digest["views"]) == ["month", "week", "year"]
    assert sorted(digest["dimensions"]) == ["competition", "issues", "products", "sentiment"]
    assert digest["default_view"] == "month"
    assert digest["default_dimension"] == "sentiment"

    phase1_keys = {"kpis", "primary_chart", "status", "status_message", "table"}
    for view in digest["views"]:
        for dim in digest["dimensions"]:
            block = digest["data"][view][dim]
            missing = phase1_keys - set(block.keys())
            assert not missing, f"{view}/{dim} 丢了 Phase 1 键: {missing}"

    # 反向覆盖：构造非空 snapshot 让至少一个 block 进入 ready，验证 ready 路径下 5 键也齐全
    nonempty_snapshot = {"logical_date": "2026-04-25", "products": [], "reviews": []}
    labeled_reviews_for_ready = [
        {"review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-04-10"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}]},
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-15"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "positive"}]},
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-20"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "positive"}]},
    ]
    digest_with_data = _build_trend_digest(
        nonempty_snapshot, labeled_reviews=labeled_reviews_for_ready, trend_series={},
    )
    # 至少 sentiment month dim 应当 ready
    sentiment_month = digest_with_data["data"]["month"]["sentiment"]
    assert sentiment_month["status"] == "ready", \
        "测试构造 3 条 own 评论应让 sentiment month ready"
    # ready 路径下 5 个 Phase 1 键全在
    missing_in_ready = phase1_keys - set(sentiment_month.keys())
    assert not missing_in_ready, \
        f"ready 路径下 sentiment/month 丢了 Phase 1 键: {missing_in_ready}"


def test_git_grep_helper_finds_known_existing_pattern():
    """元测试: 防止 _git_grep 因 refactor 静默返回 [] 让所有 grep gate 测试假性 PASS。
    跑一个保证有匹配的模式 (_build_trend_digest 在 qbu_crawler/ 中至少 1 命中)。"""
    repo_root = _REPO_ROOT

    files, returncode = _git_grep(repo_root, "_build_trend_digest", ["qbu_crawler/"])
    assert returncode == 0, \
        f"git grep _build_trend_digest 应当 returncode=0，得到 {returncode}"
    assert files, \
        "_build_trend_digest 必定在 qbu_crawler/ 中存在；空结果说明 _git_grep helper 失效"
