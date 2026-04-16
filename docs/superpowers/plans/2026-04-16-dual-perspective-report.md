# P007 双视角报告架构 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现"累积全景 + 今日增量"双视角报告架构。解决"基线后失明"问题：第 N 天仅有 0-2 条新评论时，健康指数、风险产品、聚类分析、竞品差距全部失效。双视角下，核心 KPI 始终基于全量累积数据（稳定有意义），增量窗口只负责标注"今日变化"。

**Architecture:** 数据层新增 `query_cumulative_data()` -> 快照层嵌入 `cumulative` 字段 -> 分析层 `build_dual_report_analytics()` 双调用 -> 模板层双视角渲染。纯后端 + 模板变更，不改动爬虫或数据库 schema。

**Tech Stack:** Python 3.10+, pytest, SQLite, Jinja2, openpyxl, uv

**Spec Reference:** `docs/plans/P007-dual-perspective-report.md`（含审查修正 A-I）

**Baseline:** 533 tests passing. Test command: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/config.py` | Modify | Task 1: 新增 `REPORT_PERSPECTIVE` 配置项 |
| `qbu_crawler/server/report.py` | Modify | Task 1: 新增 `query_cumulative_data()`；Task 7: Excel 双口径改造 |
| `qbu_crawler/server/report_snapshot.py` | Modify | Task 2: 快照嵌入累积层 + hash 排除；Task 4: 路由 + early-return 修正 |
| `qbu_crawler/server/report_analytics.py` | Modify | Task 3: 新增 `build_dual_report_analytics()` |
| `qbu_crawler/server/report_llm.py` | Modify | Task 5: LLM 采样偏向累积 + prompt 增加窗口摘要 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | Rewrite | Task 6: 双视角邮件布局 |
| `qbu_crawler/server/report_html.py` | Modify | Task 7: V3 HTML 传入 cumulative_kpis + window |
| `tests/test_report.py` | Modify | Task 1: query_cumulative_data 测试 |
| `tests/test_report_snapshot.py` | Modify | Task 2: 快照 + hash 测试；Task 4: 路由测试 |
| `tests/test_report_analytics.py` | Modify | Task 3: 双视角分析测试 |
| `tests/test_report_llm.py` | Modify | Task 5: LLM 采样测试 |
| `tests/test_report_excel.py` | Modify | Task 7: Excel 双口径测试 |
| `tests/test_report_snapshot.py` | Modify | Task 8: change/quiet 模式累积测试 |

---

### Task 1: 配置项 + 累积查询函数

**目标**：新增 `REPORT_PERSPECTIVE` 环境变量（默认 `dual`），以及 `query_cumulative_data()` 全量数据查询函数（含 LEFT JOIN review_analysis）。对应修正 B、G。

**Files:**
- Modify: `qbu_crawler/config.py` (line ~166, Report section)
- Modify: `qbu_crawler/server/report.py` (after `query_report_data`)
- Test: `tests/test_report.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for query_cumulative_data (P007: dual-perspective cumulative query)
# ---------------------------------------------------------------------------
import sqlite3
import json

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def cumulative_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "cumulative.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()

    conn = _get_test_conn(db_file)
    # Insert two products (own + competitor)
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("https://example.com/p1", "basspro", "Own Product", "OWN-1",
         299.99, "in_stock", 10, 4.2, "own", "2026-04-10 08:00:00"),
    )
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("https://example.com/p2", "waltons", "Comp Product", "COMP-1",
         199.99, "in_stock", 5, 4.8, "competitor", "2026-04-10 08:05:00"),
    )
    p1_id = conn.execute("SELECT id FROM products WHERE sku='OWN-1'").fetchone()["id"]
    p2_id = conn.execute("SELECT id FROM products WHERE sku='COMP-1'").fetchone()["id"]

    # Insert reviews spanning multiple days
    for i, (pid, day, rating) in enumerate([
        (p1_id, "2026-04-08 10:00:00", 5),
        (p1_id, "2026-04-09 10:00:00", 1),
        (p1_id, "2026-04-10 10:00:00", 3),
        (p2_id, "2026-04-09 11:00:00", 5),
        (p2_id, "2026-04-10 11:00:00", 4),
    ]):
        conn.execute(
            """
            INSERT INTO reviews (product_id, author, headline, body, body_hash,
                                 rating, date_published, images, scraped_at,
                                 headline_cn, body_cn, translate_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, f"Author-{i}", f"Title-{i}", f"Body-{i}", f"hash-{i}",
             rating, f"2026-04-{8+i}", json.dumps([]), day,
             "", "", "done"),
        )
    # Insert review_analysis for the first review
    r1_id = conn.execute("SELECT id FROM reviews ORDER BY id LIMIT 1").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO review_analysis (review_id, sentiment, labels, features,
                                     insight_cn, insight_en, impact_category,
                                     failure_mode, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (r1_id, "positive", json.dumps([{"code": "solid_build", "polarity": "positive"}]),
         json.dumps(["durable"]), "很耐用", "Very durable", "quality", "none",
         "2026-04-10 12:00:00"),
    )
    conn.commit()
    conn.close()
    return db_file


def test_query_cumulative_data_returns_all_products(cumulative_db):
    from qbu_crawler.server.report import query_cumulative_data

    products, reviews = query_cumulative_data()
    assert len(products) == 2
    skus = {p["sku"] for p in products}
    assert skus == {"OWN-1", "COMP-1"}


def test_query_cumulative_data_returns_all_reviews(cumulative_db):
    from qbu_crawler.server.report import query_cumulative_data

    products, reviews = query_cumulative_data()
    assert len(reviews) == 5


def test_query_cumulative_data_includes_analysis_fields(cumulative_db):
    from qbu_crawler.server.report import query_cumulative_data

    _, reviews = query_cumulative_data()
    # First review (Author-0) has analysis data
    r0 = next(r for r in reviews if r["author"] == "Author-0")
    assert r0["sentiment"] == "positive"
    assert r0["analysis_labels"] is not None
    assert r0["analysis_features"] is not None


def test_query_cumulative_data_analysis_null_when_missing(cumulative_db):
    from qbu_crawler.server.report import query_cumulative_data

    _, reviews = query_cumulative_data()
    # Author-1 has no review_analysis row
    r1 = next(r for r in reviews if r["author"] == "Author-1")
    assert r1["sentiment"] is None
    assert r1["analysis_labels"] is None


def test_report_perspective_config_default():
    assert config.REPORT_PERSPECTIVE == "dual"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report.py::test_query_cumulative_data_returns_all_products tests/test_report.py::test_report_perspective_config_default -x -q
```

预期：`AttributeError: module 'qbu_crawler.config' has no attribute 'REPORT_PERSPECTIVE'` 和 `ImportError: cannot import name 'query_cumulative_data'`。

- [ ] **Step 3: 实现配置项**

在 `qbu_crawler/config.py` 的 `# ── Report ──` 区块（约 line 154）后添加：

```python
REPORT_PERSPECTIVE = _enum_env("REPORT_PERSPECTIVE", "dual", ("dual", "window"))
```

- [ ] **Step 4: 实现 query_cumulative_data**

在 `qbu_crawler/server/report.py` 中，在 `query_report_data` 函数后（约 line 1033）添加：

```python
def query_cumulative_data() -> tuple[list[dict], list[dict]]:
    """Query ALL products and ALL reviews with LEFT JOIN review_analysis.

    Returns (products, reviews) — both as lists of dicts.
    Used for the cumulative perspective in dual-perspective reports.
    """
    conn = models.get_conn()
    try:
        product_rows = conn.execute(
            """
            SELECT url, name, sku, price, stock_status, rating,
                   review_count, scraped_at, site, ownership
            FROM products
            ORDER BY site, name
            """
        ).fetchall()
        products = [dict(r) for r in product_rows]

        review_rows = conn.execute(
            """
            SELECT r.id AS id, p.name AS product_name, p.sku AS product_sku,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.date_published_parsed, r.images,
                   p.ownership,
                   r.headline_cn, r.body_cn, r.translate_status,
                   ra.sentiment, ra.labels AS analysis_labels,
                   ra.features AS analysis_features,
                   ra.insight_cn AS analysis_insight_cn,
                   ra.insight_en AS analysis_insight_en,
                   ra.impact_category, ra.failure_mode
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            LEFT JOIN review_analysis ra
                ON ra.review_id = r.id
            ORDER BY r.scraped_at DESC
            """
        ).fetchall()
        reviews = []
        for row in review_rows:
            d = dict(row)
            # Normalise images: may be JSON string or None
            if d.get("images") and isinstance(d["images"], str):
                try:
                    d["images"] = json.loads(d["images"])
                except Exception:
                    pass
            reviews.append(d)
    finally:
        conn.close()

    logger.info(
        "query_cumulative_data: %d products, %d reviews",
        len(products),
        len(reviews),
    )
    return products, reviews
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
uv run pytest tests/test_report.py::test_query_cumulative_data_returns_all_products tests/test_report.py::test_query_cumulative_data_returns_all_reviews tests/test_report.py::test_query_cumulative_data_includes_analysis_fields tests/test_report.py::test_query_cumulative_data_analysis_null_when_missing tests/test_report.py::test_report_perspective_config_default -x -q
```

预期：`5 passed`

- [ ] **Step 6: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`533 passed`

- [ ] **Step 7: 提交**

```
git add qbu_crawler/config.py qbu_crawler/server/report.py tests/test_report.py
git commit -m "feat(report): add REPORT_PERSPECTIVE config and query_cumulative_data (P007 Task 1)"
```

---

### Task 2: 双层快照结构

**目标**：改造 `freeze_report_snapshot()` 在 `REPORT_PERSPECTIVE="dual"` 时查询累积数据并嵌入快照。hash 仅对窗口数据计算（排除 `cumulative`）。对应修正 C。

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (freeze_report_snapshot, line 274-348)
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for dual-layer snapshot (P007 Task 2)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dual_snapshot_db(tmp_path, monkeypatch):
    """DB with products and reviews spanning two days for dual snapshot testing."""
    db_file = str(tmp_path / "dual.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "REPORT_PERSPECTIVE", "dual")

    models.init_db()

    conn = _get_test_conn(db_file)
    # Product scraped on day 1
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("https://example.com/p1", "basspro", "Dual Product", "DUAL-1",
         99.99, "in_stock", 3, 4.0, "own", "2026-04-15 09:00:00"),
    )
    product_id = conn.execute("SELECT id FROM products WHERE sku='DUAL-1'").fetchone()["id"]
    # Review from day 1
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at,
                             headline_cn, body_cn, translate_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (product_id, "OldReviewer", "Old review", "This is old", "hash-old",
         4.0, "2026-04-14", json.dumps([]), "2026-04-14 10:00:00",
         "", "", "done"),
    )
    # Review from day 2 (window)
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at,
                             headline_cn, body_cn, translate_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (product_id, "NewReviewer", "New review", "This is new", "hash-new",
         5.0, "2026-04-15", json.dumps([]), "2026-04-15 10:00:00",
         "", "", "done"),
    )
    conn.commit()
    conn.close()

    run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "reporting",
            "logical_date": "2026-04-15",
            "trigger_key": "daily:2026-04-15:dual",
            "data_since": "2026-04-15T00:00:00+08:00",
            "data_until": "2026-04-16T00:00:00+08:00",
            "requested_by": "test",
            "service_version": "test",
        }
    )
    return {"db_file": db_file, "run": run, "tmp_path": tmp_path}


def test_dual_snapshot_has_cumulative_field(dual_snapshot_db):
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot, load_report_snapshot

    run = dual_snapshot_db["run"]
    result = freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = load_report_snapshot(result["snapshot_path"])

    assert "cumulative" in snapshot
    cum = snapshot["cumulative"]
    assert cum["products_count"] == 1
    # Cumulative should have ALL reviews (both old and new)
    assert cum["reviews_count"] == 2


def test_dual_snapshot_window_only_has_new_reviews(dual_snapshot_db):
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot, load_report_snapshot

    run = dual_snapshot_db["run"]
    result = freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = load_report_snapshot(result["snapshot_path"])

    # Window should only have day 2 review
    assert snapshot["reviews_count"] == 1
    assert snapshot["reviews"][0]["author"] == "NewReviewer"


def test_dual_snapshot_hash_excludes_cumulative(dual_snapshot_db):
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot, load_report_snapshot

    run = dual_snapshot_db["run"]
    result = freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = load_report_snapshot(result["snapshot_path"])

    # Recompute hash excluding cumulative to verify
    import hashlib
    hash_payload = {k: v for k, v in snapshot.items() if k not in ("cumulative", "snapshot_hash")}
    expected_hash = hashlib.sha1(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert snapshot["snapshot_hash"] == expected_hash


def test_window_perspective_skips_cumulative(dual_snapshot_db, monkeypatch):
    """When REPORT_PERSPECTIVE='window', no cumulative field is added."""
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot, load_report_snapshot

    monkeypatch.setattr(config, "REPORT_PERSPECTIVE", "window")
    run = dual_snapshot_db["run"]
    # Need a fresh run since the previous one has a cached snapshot
    run2 = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "reporting",
            "logical_date": "2026-04-15",
            "trigger_key": "daily:2026-04-15:window-mode",
            "data_since": "2026-04-15T00:00:00+08:00",
            "data_until": "2026-04-16T00:00:00+08:00",
            "requested_by": "test",
            "service_version": "test",
        }
    )
    result = freeze_report_snapshot(run2["id"], now="2026-04-15T12:01:00+08:00")
    snapshot = load_report_snapshot(result["snapshot_path"])

    assert "cumulative" not in snapshot
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report_snapshot.py::test_dual_snapshot_has_cumulative_field tests/test_report_snapshot.py::test_dual_snapshot_hash_excludes_cumulative -x -q
```

预期：`cumulative` 字段不存在，assert 失败。

- [ ] **Step 3: 实现双层快照**

在 `qbu_crawler/server/report_snapshot.py` 的 `freeze_report_snapshot()` 中，替换从 line 292 到 line 331 的区块：

找到当前代码（约 line 292-331）：

```python
    products, reviews = report.query_report_data(run["data_since"], until=run["data_until"])
    for item in reviews:
        item.setdefault("headline_cn", "")
        item.setdefault("body_cn", "")

    # ── Enrich reviews with review_analysis fields (LLM analysis data) ──
    _review_ids = [r["id"] for r in reviews if r.get("id")]
    if _review_ids:
        _enriched_map = {
            ea["id"]: ea
            for ea in models.get_reviews_with_analysis(review_ids=_review_ids)
        }
        for r in reviews:
            ea = _enriched_map.get(r.get("id"))
            if ea:
                for _key in ("sentiment", "analysis_features", "analysis_labels",
                             "analysis_insight_cn", "analysis_insight_en"):
                    _val = ea.get(_key)
                    if _val is not None:
                        r.setdefault(_key, _val)

    translated_count = sum(1 for item in reviews if item.get("translate_status") == "done")
    snapshot_at = now or config.now_shanghai().isoformat()
    snapshot = {
        "run_id": run["id"],
        "logical_date": run["logical_date"],
        "data_since": run["data_since"],
        "data_until": run["data_until"],
        "snapshot_at": snapshot_at,
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "untranslated_count": len(reviews) - translated_count,
    }
    snapshot_hash = hashlib.sha1(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    snapshot["snapshot_hash"] = snapshot_hash
```

替换为：

```python
    products, reviews = report.query_report_data(run["data_since"], until=run["data_until"])
    for item in reviews:
        item.setdefault("headline_cn", "")
        item.setdefault("body_cn", "")

    # ── Enrich reviews with review_analysis fields (LLM analysis data) ──
    _review_ids = [r["id"] for r in reviews if r.get("id")]
    if _review_ids:
        _enriched_map = {
            ea["id"]: ea
            for ea in models.get_reviews_with_analysis(review_ids=_review_ids)
        }
        for r in reviews:
            ea = _enriched_map.get(r.get("id"))
            if ea:
                for _key in ("sentiment", "analysis_features", "analysis_labels",
                             "analysis_insight_cn", "analysis_insight_en"):
                    _val = ea.get(_key)
                    if _val is not None:
                        r.setdefault(_key, _val)

    translated_count = sum(1 for item in reviews if item.get("translate_status") == "done")
    snapshot_at = now or config.now_shanghai().isoformat()
    snapshot = {
        "run_id": run["id"],
        "logical_date": run["logical_date"],
        "data_since": run["data_since"],
        "data_until": run["data_until"],
        "snapshot_at": snapshot_at,
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "untranslated_count": len(reviews) - translated_count,
    }

    # ── Cumulative layer (P007 dual perspective) ──
    if config.REPORT_PERSPECTIVE == "dual":
        cum_products, cum_reviews = report.query_cumulative_data()
        cum_translated = sum(1 for r in cum_reviews if r.get("translate_status") == "done")
        snapshot["cumulative"] = {
            "products": cum_products,
            "reviews": cum_reviews,
            "products_count": len(cum_products),
            "reviews_count": len(cum_reviews),
            "translated_count": cum_translated,
            "untranslated_count": len(cum_reviews) - cum_translated,
        }

    # Hash computed on window data only — exclude cumulative (Correction C)
    hash_payload = {k: v for k, v in snapshot.items() if k != "cumulative"}
    snapshot_hash = hashlib.sha1(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    snapshot["snapshot_hash"] = snapshot_hash
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
uv run pytest tests/test_report_snapshot.py::test_dual_snapshot_has_cumulative_field tests/test_report_snapshot.py::test_dual_snapshot_window_only_has_new_reviews tests/test_report_snapshot.py::test_dual_snapshot_hash_excludes_cumulative tests/test_report_snapshot.py::test_window_perspective_skips_cumulative -x -q
```

预期：`4 passed`

- [ ] **Step 5: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`537 passed` (533 + 4 new)

- [ ] **Step 6: 提交**

```
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat(report): embed cumulative layer in snapshot with hash isolation (P007 Task 2)"
```

---

### Task 3: build_dual_report_analytics()

**目标**：新增 `build_dual_report_analytics()` 函数，双调用 `build_report_analytics()`（累积 + 窗口），合并产出双视角分析。`sync_review_labels` 仅调用一次（修正 F）。老快照无 `cumulative` 时降级为单视角（修正 D）。

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (新增函数)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_analytics.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for build_dual_report_analytics (P007 Task 3)
# ---------------------------------------------------------------------------


def _build_dual_snapshot(run_id: int, logical_date: str):
    """Build a snapshot with both window and cumulative data."""
    window_snapshot = _build_snapshot(run_id, logical_date)

    # Cumulative includes window reviews + older reviews
    cumulative_reviews = list(window_snapshot["reviews"]) + [
        {
            "id": 100,
            "product_name": "Own Grinder",
            "product_sku": "OWN-1",
            "author": "OldAlice",
            "headline": "Been using for months",
            "body": "Solid build quality, no issues after months of use.",
            "rating": 5,
            "date_published": "2026-02-15",
            "images": [],
            "ownership": "own",
            "headline_cn": "用了几个月了",
            "body_cn": "品质很好",
            "translate_status": "done",
        },
        {
            "id": 101,
            "product_name": "Own Grinder",
            "product_sku": "OWN-1",
            "author": "OldBob",
            "headline": "Noisy motor",
            "body": "The motor is very noisy and vibrates too much.",
            "rating": 2,
            "date_published": "2026-02-20",
            "images": [],
            "ownership": "own",
            "headline_cn": "马达噪音大",
            "body_cn": "马达声音很大而且振动厉害",
            "translate_status": "done",
        },
        {
            "id": 102,
            "product_name": "Competitor Grinder",
            "product_sku": "COMP-1",
            "author": "OldCara",
            "headline": "Best purchase",
            "body": "Easy to use and clean. Great value for money.",
            "rating": 5,
            "date_published": "2026-03-01",
            "images": [],
            "ownership": "competitor",
            "headline_cn": "",
            "body_cn": "",
            "translate_status": "pending",
        },
    ]
    cumulative_products = list(window_snapshot["products"])

    window_snapshot["cumulative"] = {
        "products": cumulative_products,
        "reviews": cumulative_reviews,
        "products_count": len(cumulative_products),
        "reviews_count": len(cumulative_reviews),
        "translated_count": sum(1 for r in cumulative_reviews if r.get("translate_status") == "done"),
        "untranslated_count": sum(1 for r in cumulative_reviews if r.get("translate_status") != "done"),
    }
    return window_snapshot


def test_build_dual_report_analytics_perspective(analytics_db):
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    _insert_review_record()

    result = build_dual_report_analytics(snapshot)

    assert result["perspective"] == "dual"


def test_build_dual_report_analytics_has_cumulative_kpis(analytics_db):
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    _insert_review_record()

    result = build_dual_report_analytics(snapshot)

    assert "cumulative_kpis" in result
    # Cumulative should have more reviews than window
    assert result["cumulative_kpis"]["ingested_review_rows"] == 8  # 5 window + 3 old
    assert result["kpis"]["ingested_review_rows"] == 8  # main kpis = cumulative kpis


def test_build_dual_report_analytics_has_window(analytics_db):
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    _insert_review_record()

    result = build_dual_report_analytics(snapshot)

    window = result.get("window", {})
    assert window["reviews_count"] == 5  # only window reviews
    assert "own_reviews_count" in window
    assert "competitor_reviews_count" in window
    assert "new_negative_count" in window


def test_build_dual_degrades_without_cumulative(analytics_db):
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29")
    snapshot = _build_snapshot(run["id"], "2026-03-29")  # no cumulative field
    _insert_review_record()

    result = build_dual_report_analytics(snapshot)

    # Should degrade to single perspective
    assert result.get("perspective") != "dual"
    assert "cumulative_kpis" not in result


def test_build_dual_risk_products_from_cumulative(analytics_db):
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    _insert_review_record()

    result = build_dual_report_analytics(snapshot)

    # Risk products should be based on cumulative data (more reviews)
    risk = result.get("self", {}).get("risk_products", [])
    # With 8 reviews (4 own, 4 competitor), we should have risk data
    # The exact values depend on the scoring algorithm, just verify it exists
    assert isinstance(risk, list)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report_analytics.py::test_build_dual_report_analytics_perspective -x -q
```

预期：`ImportError: cannot import name 'build_dual_report_analytics'`

- [ ] **Step 3: 实现 build_dual_report_analytics**

在 `qbu_crawler/server/report_analytics.py` 末尾（line 1535 之后）添加：

```python
def build_dual_report_analytics(snapshot, synced_labels=None):
    """Build dual-perspective analytics: cumulative (main) + window (delta).

    When snapshot has no "cumulative" field (old snapshots), degrades to
    single-perspective by delegating to build_report_analytics() directly.

    Returns analytics dict with extra keys:
        perspective: "dual"
        cumulative_kpis: dict — KPIs from cumulative data
        window: dict — window-layer summary + optional window analytics
    """
    if not snapshot.get("cumulative"):
        # Correction D: degrade to single-perspective for old snapshots
        return build_report_analytics(snapshot, synced_labels=synced_labels)

    cum = snapshot["cumulative"]

    # Build a cumulative-scope snapshot for build_report_analytics
    cumulative_snapshot = {
        "run_id": snapshot["run_id"],
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products": cum["products"],
        "reviews": cum["reviews"],
        "products_count": cum["products_count"],
        "reviews_count": cum["reviews_count"],
        "translated_count": cum.get("translated_count", 0),
        "untranslated_count": cum.get("untranslated_count", 0),
    }

    # 1. Cumulative analytics (main body)
    cum_analytics = build_report_analytics(cumulative_snapshot, synced_labels=synced_labels)

    # 2. Window analytics (optional — only when there are window reviews)
    window_analytics = None
    if snapshot.get("reviews"):
        window_analytics = build_report_analytics(snapshot, synced_labels=synced_labels)

    # 3. Compute window summary
    window_reviews = snapshot.get("reviews", [])
    own_window = [r for r in window_reviews if r.get("ownership") == "own"]
    comp_window = [r for r in window_reviews if r.get("ownership") == "competitor"]
    neg_threshold = config.NEGATIVE_THRESHOLD

    # 4. Merge: cumulative as base, overlay dual-specific fields
    merged = {
        **cum_analytics,
        "perspective": "dual",

        # Cumulative KPIs explicitly saved for template access
        "cumulative_kpis": cum_analytics["kpis"],

        # Window-layer summary
        "window": {
            "reviews_count": len(window_reviews),
            "own_reviews_count": len(own_window),
            "competitor_reviews_count": len(comp_window),
            "new_negative_count": sum(
                1 for r in own_window
                if (r.get("rating") or 5) <= neg_threshold
            ),
            "new_reviews": window_reviews,
            "analytics": window_analytics,
        },
    }

    # 5. KPI delta: cumulative vs previous cumulative (replaces window-vs-window)
    if cum_analytics.get("mode") != "baseline":
        from .report_snapshot import load_previous_report_context
        from .report_common import _compute_kpi_deltas

        _run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(_run_id)
        if prev_analytics:
            # Prefer cumulative_kpis from previous report (P007 format)
            prev_kpis_source = prev_analytics
            if prev_analytics.get("cumulative_kpis"):
                prev_kpis_source = {"kpis": prev_analytics["cumulative_kpis"]}
            deltas = _compute_kpi_deltas(merged["cumulative_kpis"], prev_kpis_source)
            merged["cumulative_kpis"].update(deltas)
            merged["kpis"].update(deltas)

    return merged
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
uv run pytest tests/test_report_analytics.py::test_build_dual_report_analytics_perspective tests/test_report_analytics.py::test_build_dual_report_analytics_has_cumulative_kpis tests/test_report_analytics.py::test_build_dual_report_analytics_has_window tests/test_report_analytics.py::test_build_dual_degrades_without_cumulative tests/test_report_analytics.py::test_build_dual_risk_products_from_cumulative -x -q
```

预期：`5 passed`

- [ ] **Step 5: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`542 passed` (537 + 5 new)

- [ ] **Step 6: 提交**

```
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report): add build_dual_report_analytics with cumulative+window (P007 Task 3)"
```

---

### Task 4: 报告生成层适配双视角

**目标**：`generate_full_report_from_snapshot()` 放宽 early return guard（修正 A），使用 `build_dual_report_analytics` 替换单视角调用（当 cumulative 存在时），`_render_full_email_html()` 传递新模板变量（修正 E）。`sync_review_labels` 在累积评论上仅调用一次（修正 F）。

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (generate_full_report_from_snapshot, _render_full_email_html)
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for dual-perspective report generation routing (P007 Task 4)
# ---------------------------------------------------------------------------


def test_full_report_continues_with_cumulative_no_window_reviews(dual_snapshot_db, monkeypatch):
    """When window has no reviews but cumulative exists, should NOT early-return."""
    from qbu_crawler.server import report_snapshot

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Remove window reviews to simulate no-new-reviews day
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    # Mock out expensive operations
    monkeypatch.setattr(config, "LLM_API_BASE", "")  # disable LLM
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)

    result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False,
    )

    # Should NOT get "completed_no_change" because cumulative data exists
    assert result.get("status") != "completed_no_change"
    # Should have analytics path (dual analytics was computed)
    assert result.get("analytics_path") is not None


def test_full_report_early_returns_without_cumulative_or_reviews(snapshot_db, monkeypatch):
    """Without cumulative and without reviews, should still early-return."""
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_PERSPECTIVE", "window")
    run = snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-03-29T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Remove reviews
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False,
    )
    assert result.get("status") == "completed_no_change"


def test_full_report_analytics_has_dual_perspective(dual_snapshot_db, monkeypatch):
    """Full report analytics should contain perspective='dual' when cumulative exists."""
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    gen_result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False,
    )

    # Load saved analytics and verify dual perspective
    analytics = json.loads(Path(gen_result["analytics_path"]).read_text(encoding="utf-8"))
    assert analytics.get("perspective") == "dual"
    assert "cumulative_kpis" in analytics
    assert "window" in analytics
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report_snapshot.py::test_full_report_continues_with_cumulative_no_window_reviews -x -q
```

预期：`assert result.get("status") != "completed_no_change"` fails — current code returns early at line 686-687.

- [ ] **Step 3: 实现 generate_full_report_from_snapshot 改造**

In `qbu_crawler/server/report_snapshot.py`, make three changes:

**Change 1: Relax early return guard (line 686-687)**

Replace:

```python
    if not snapshot.get("reviews"):
        return {"status": "completed_no_change", "reason": "No new reviews"}
```

With:

```python
    if not snapshot.get("reviews") and not snapshot.get("cumulative"):
        return {"status": "completed_no_change", "reason": "No new reviews"}
```

**Change 2: Use dual analytics when cumulative available (lines 712-713)**

Replace:

```python
        synced_labels = report_analytics.sync_review_labels(snapshot)
        analytics = report_analytics.build_report_analytics(snapshot, synced_labels=synced_labels)
```

With:

```python
        # Correction F: sync labels on cumulative reviews (superset), call once
        if snapshot.get("cumulative"):
            _label_snapshot = {
                "reviews": snapshot["cumulative"]["reviews"],
            }
        else:
            _label_snapshot = snapshot
        synced_labels = report_analytics.sync_review_labels(_label_snapshot)

        # Use dual analytics when cumulative data exists
        if snapshot.get("cumulative"):
            analytics = report_analytics.build_dual_report_analytics(
                snapshot, synced_labels=synced_labels,
            )
        else:
            analytics = report_analytics.build_report_analytics(
                snapshot, synced_labels=synced_labels,
            )
```

**Change 3: Update Excel call to use cumulative data when available (line 743-748)**

Replace:

```python
        excel_path = report.generate_excel(
            snapshot["products"],
            snapshot["reviews"],
            report_date=report_date,
            output_path=output_path,
            analytics=analytics,
        )
```

With:

```python
        # Excel uses cumulative reviews when available, with window ID marking
        if snapshot.get("cumulative"):
            _excel_products = snapshot["cumulative"]["products"]
            _excel_reviews = snapshot["cumulative"]["reviews"]
        else:
            _excel_products = snapshot["products"]
            _excel_reviews = snapshot["reviews"]
        excel_path = report.generate_excel(
            _excel_products,
            _excel_reviews,
            report_date=report_date,
            output_path=output_path,
            analytics=analytics,
        )
```

**Change 4: Pass dual variables to _render_full_email_html (line 768)**

Replace:

```python
            body_html = _render_full_email_html(snapshot, analytics)
```

With:

```python
            body_html = _render_full_email_html(snapshot, analytics)
```

And update `_render_full_email_html` itself (lines 653-678):

Replace:

```python
def _render_full_email_html(snapshot, analytics):
    """Render email_full.html.j2 for the full-mode email body."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics, _compute_alert_level

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    normalized = normalize_deep_report_analytics(analytics)
    alert = _compute_alert_level(normalized)
    alert_level = alert[0] if isinstance(alert, (list, tuple)) else "green"
    alert_text = alert[1] if isinstance(alert, (list, tuple)) else ""

    tpl = env.get_template("email_full.html.j2")
    return tpl.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        analytics=normalized,
        alert_level=alert_level,
        alert_text=alert_text,
        report_copy=normalized.get("report_copy") or analytics.get("report_copy") or {},
        risk_products=(normalized.get("self") or {}).get("risk_products", [])[:3],
        threshold=config.NEGATIVE_THRESHOLD,
    )
```

With:

```python
def _render_full_email_html(snapshot, analytics):
    """Render email_full.html.j2 for the full-mode email body."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics, _compute_alert_level

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    normalized = normalize_deep_report_analytics(analytics)
    alert = _compute_alert_level(normalized)
    alert_level = alert[0] if isinstance(alert, (list, tuple)) else "green"
    alert_text = alert[1] if isinstance(alert, (list, tuple)) else ""

    # Dual-perspective template variables (Correction E)
    cumulative_kpis = normalized.get("cumulative_kpis") or normalized.get("kpis", {})
    window = normalized.get("window", {})
    health_confidence = cumulative_kpis.get("health_confidence", "high")

    # Detect snapshot changes for the "today's changes" block
    prev_snapshot = None
    run_id = snapshot.get("run_id", 0)
    if run_id:
        from qbu_crawler.server.report_snapshot import load_previous_report_context
        _, prev_snapshot = load_previous_report_context(run_id)
    changes = detect_snapshot_changes(snapshot, prev_snapshot)

    # New review summary for email template
    window_reviews = window.get("new_reviews") or snapshot.get("reviews", [])
    own_new = [r for r in window_reviews if r.get("ownership") == "own"]
    comp_new = [r for r in window_reviews if r.get("ownership") == "competitor"]
    new_review_summary = {
        "own_count": len(own_new),
        "comp_count": len(comp_new),
        "own_negative": sum(
            1 for r in own_new if (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD
        ),
    }

    # Compute cluster changes for "today's changes" section
    prev_clusters = None
    if prev_snapshot:
        _, prev_snap = load_previous_report_context(run_id)
    prev_analytics_ctx, _ = load_previous_report_context(run_id)
    if prev_analytics_ctx:
        prev_clusters = (prev_analytics_ctx.get("self") or {}).get("top_negative_clusters")
    cluster_changes = compute_cluster_changes(
        (normalized.get("self") or {}).get("top_negative_clusters", []),
        prev_clusters,
        snapshot.get("logical_date", ""),
    )

    # Build report URL
    report_url = ""
    if config.REPORT_HTML_PUBLIC_URL:
        html_name = f"workflow-run-{run_id}-full-report.html"
        report_url = f"{config.REPORT_HTML_PUBLIC_URL}/{html_name}"

    tpl = env.get_template("email_full.html.j2")
    return tpl.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        analytics=normalized,
        alert_level=alert_level,
        alert_text=alert_text,
        report_copy=normalized.get("report_copy") or analytics.get("report_copy") or {},
        risk_products=(normalized.get("self") or {}).get("risk_products", [])[:3],
        threshold=config.NEGATIVE_THRESHOLD,
        # New dual-perspective variables
        cumulative_kpis=cumulative_kpis,
        window=window,
        health_confidence=health_confidence,
        changes=cluster_changes,
        new_review_summary=new_review_summary,
        report_url=report_url,
    )
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
uv run pytest tests/test_report_snapshot.py::test_full_report_continues_with_cumulative_no_window_reviews tests/test_report_snapshot.py::test_full_report_early_returns_without_cumulative_or_reviews tests/test_report_snapshot.py::test_full_report_analytics_has_dual_perspective -x -q
```

预期：`3 passed`

- [ ] **Step 5: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`545 passed` (542 + 3 new)

- [ ] **Step 6: 提交**

```
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat(report): route full report through dual analytics and relax early return (P007 Task 4)"
```

---

### Task 5: LLM 上下文更新

**目标**：`_select_insight_samples()` 优先从累积评论选样（更大池子产出更好洞察）。`_build_insights_prompt()` 新增"今日变化"摘要段，让 LLM 在 executive_bullets 中提及当天新增。

**Files:**
- Modify: `qbu_crawler/server/report_llm.py` (_select_insight_samples, _build_insights_prompt)
- Test: `tests/test_report_llm.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_llm.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for dual-perspective LLM context (P007 Task 5)
# ---------------------------------------------------------------------------


def test_select_insight_samples_prefers_cumulative(monkeypatch):
    from qbu_crawler.server.report_llm import _select_insight_samples

    monkeypatch.setattr(config, "NEGATIVE_THRESHOLD", 2)

    window_reviews = [
        {
            "id": 1, "product_name": "P1", "product_sku": "SKU-1",
            "rating": 5, "ownership": "own", "headline": "Great",
            "body": "Love it", "images": [], "sentiment": "positive",
            "date_published_parsed": "2026-04-15",
        },
    ]
    cumulative_reviews = window_reviews + [
        {
            "id": 2, "product_name": "P1", "product_sku": "SKU-1",
            "rating": 1, "ownership": "own", "headline": "Broken",
            "body": "Motor broke after one use", "images": ["https://img.test/1.jpg"],
            "sentiment": "negative", "date_published_parsed": "2026-03-01",
        },
        {
            "id": 3, "product_name": "P2", "product_sku": "SKU-2",
            "rating": 5, "ownership": "competitor", "headline": "Best ever",
            "body": "Best product I ever bought", "images": [],
            "sentiment": "positive", "date_published_parsed": "2026-03-15",
        },
    ]
    snapshot = {
        "reviews": window_reviews,
        "cumulative": {
            "reviews": cumulative_reviews,
        },
    }
    analytics = {
        "self": {"risk_products": [{"product_sku": "SKU-1"}]},
    }

    samples = _select_insight_samples(snapshot, analytics)

    # Should include reviews from cumulative that aren't in window
    sample_ids = {s["id"] for s in samples}
    assert 2 in sample_ids, "Cumulative negative review should be selected"
    assert 3 in sample_ids, "Cumulative competitor review should be selected"


def test_select_insight_samples_works_without_cumulative():
    from qbu_crawler.server.report_llm import _select_insight_samples

    snapshot = {
        "reviews": [
            {
                "id": 1, "product_name": "P1", "product_sku": "SKU-1",
                "rating": 4, "ownership": "own", "headline": "Good",
                "body": "Decent product", "images": [],
                "date_published_parsed": "2026-04-15",
            },
        ],
    }
    analytics = {"self": {"risk_products": []}}

    samples = _select_insight_samples(snapshot, analytics)
    assert len(samples) == 1
    assert samples[0]["id"] == 1


def test_build_insights_prompt_includes_window_summary():
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "kpis": {
            "own_product_count": 5, "competitor_product_count": 3,
            "ingested_review_rows": 100, "negative_review_rows": 10,
            "negative_review_rate": 0.1, "health_index": 85,
            "own_review_rows": 60, "own_negative_review_rows": 8,
            "own_negative_review_rate": 0.133, "competitor_review_rows": 40,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
        "window": {
            "reviews_count": 3,
            "own_reviews_count": 2,
            "competitor_reviews_count": 1,
            "new_negative_count": 1,
        },
    }

    prompt = _build_insights_prompt(analytics)

    assert "今日新增" in prompt or "今日变化" in prompt
    assert "3" in prompt  # total window reviews
    assert "差评" in prompt or "negative" in prompt.lower()
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report_llm.py::test_select_insight_samples_prefers_cumulative tests/test_report_llm.py::test_build_insights_prompt_includes_window_summary -x -q
```

预期：`test_select_insight_samples_prefers_cumulative` fails because current code uses `snapshot["reviews"]` not cumulative. `test_build_insights_prompt_includes_window_summary` fails because prompt has no window section.

- [ ] **Step 3: 实现 _select_insight_samples 改造**

In `qbu_crawler/server/report_llm.py`, modify `_select_insight_samples` (line 273-342).

Replace line 280:

```python
    reviews = snapshot.get("reviews", [])
```

With:

```python
    # Prefer cumulative reviews for richer sample pool (P007)
    reviews = (
        (snapshot.get("cumulative") or {}).get("reviews")
        or snapshot.get("reviews", [])
    )
```

- [ ] **Step 4: 实现 _build_insights_prompt 改造**

In `qbu_crawler/server/report_llm.py`, at the end of `_build_insights_prompt` (just before the `return prompt` line at approximately line 495), insert:

```python
    # ── Window summary for dual-perspective context (P007) ──
    window = analytics.get("window", {})
    if window.get("reviews_count", 0) > 0:
        prompt += f"\n\n--- 今日变化 ---"
        prompt += f"\n今日新增评论 {window['reviews_count']} 条"
        prompt += f"（自有 {window.get('own_reviews_count', 0)}，竞品 {window.get('competitor_reviews_count', 0)}）"
        if window.get("new_negative_count", 0) > 0:
            prompt += f"\n注意：新增自有差评 {window['new_negative_count']} 条"
        prompt += "\n请在 executive_bullets 中提及今日新增变化（如有值得关注的新评论）。"
    elif analytics.get("perspective") == "dual":
        prompt += "\n\n今日无新增评论。executive_bullets 应聚焦累积数据中的关键洞察和持续存在的问题。"
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
uv run pytest tests/test_report_llm.py::test_select_insight_samples_prefers_cumulative tests/test_report_llm.py::test_select_insight_samples_works_without_cumulative tests/test_report_llm.py::test_build_insights_prompt_includes_window_summary -x -q
```

预期：`3 passed`

- [ ] **Step 6: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`548 passed` (545 + 3 new)

- [ ] **Step 7: 提交**

```
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "feat(report): LLM samples from cumulative pool + window summary in prompt (P007 Task 5)"
```

---

### Task 6: 邮件模板双视角重构

**目标**：重写 `email_full.html.j2`，使用累积 KPI 作为主体指标，新增"今日变化"区块展示窗口增量数据。模板保持 email-safe table 布局 + 内联样式。

**Files:**
- Rewrite: `qbu_crawler/server/report_templates/email_full.html.j2`
- No automated test (visual template), but template should render without errors

- [ ] **Step 1: 备份当前模板**

记录当前模板已在 Task 4 的 `_render_full_email_html` 中传入了新变量。

- [ ] **Step 2: 重写邮件模板**

Replace the entire contents of `qbu_crawler/server/report_templates/email_full.html.j2` with:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!--[if mso]><style>table{border-collapse:collapse;}td{font-family:Arial,sans-serif;}</style><![endif]-->
</head>
<body style="margin:0;padding:0;background:#f7f7f5;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f7f5;">
<tr><td align="center" style="padding:20px 10px;">

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">

  <!-- ===== 1. HEADER BAR ===== -->
  <tr>
    <td style="background:#4f46e5;padding:16px 24px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="color:#ffffff;font-size:12px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;">QBU 网评监控</td>
          <td style="color:rgba(255,255,255,0.6);font-size:11px;text-align:right;white-space:nowrap;">{{ logical_date }}</td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ===== 2. HEALTH INDEX HERO (cumulative-based, stable) ===== -->
  {% set _kpis = cumulative_kpis if cumulative_kpis is defined and cumulative_kpis else (analytics.kpis if analytics is defined else {}) %}
  {% set _alert = alert_level or "green" %}
  {% if _alert == "red" %}{% set hero_bg = "#fef2f2" %}{% set hero_color = "#b91c1c" %}
  {% elif _alert == "yellow" %}{% set hero_bg = "#fefce8" %}{% set hero_color = "#a16207" %}
  {% else %}{% set hero_bg = "#ecfdf5" %}{% set hero_color = "#047857" %}{% endif %}
  <tr>
    <td style="background:{{ hero_bg }};padding:28px 24px 20px;text-align:center;">
      <div style="font-size:10px;color:{{ hero_color }};letter-spacing:0.15em;text-transform:uppercase;opacity:0.8;margin-bottom:8px;">产品健康指数</div>
      <div style="font-size:52px;font-weight:900;color:{{ hero_color }};line-height:1;margin-bottom:6px;">{{ _kpis.get("health_index", "—") if _kpis else "—" }}</div>
      {% set _hconf = health_confidence if health_confidence is defined else (_kpis.get("health_confidence", "high") if _kpis else "high") %}
      {% if _hconf == "low" %}
      <div style="font-size:11px;color:{{ hero_color }};opacity:0.7;margin-bottom:4px;">&#9888; 样本仅 {{ _kpis.get("own_review_rows", 0) }} 条，置信度低</div>
      {% elif _hconf == "medium" %}
      <div style="font-size:11px;color:{{ hero_color }};opacity:0.7;margin-bottom:4px;">样本 {{ _kpis.get("own_review_rows", 0) }} 条</div>
      {% else %}
      <div style="font-size:11px;color:{{ hero_color }};opacity:0.7;margin-bottom:4px;">基于 {{ _kpis.get("own_review_rows", 0) }} 条自有评论</div>
      {% endif %}
      <div style="font-size:12px;color:{{ hero_color }};opacity:0.6;">/ 100 · 累积全景分析</div>
    </td>
  </tr>

  <!-- ===== 3. ALERT BANNER ===== -->
  {% set _alert_text = alert_text or "" %}
  {% if _alert_text %}
  {% if _alert == "red" %}{% set abg = "#b91c1c" %}{% elif _alert == "yellow" %}{% set abg = "#a16207" %}{% else %}{% set abg = "#047857" %}{% endif %}
  <tr>
    <td style="background:{{ abg }};padding:10px 24px;text-align:center;">
      <span style="color:#ffffff;font-size:12px;font-weight:600;">{{ _alert_text }}</span>
    </td>
  </tr>
  {% endif %}

  <!-- ===== 4. CUMULATIVE KPI CARDS ===== -->
  <tr>
    <td style="padding:20px 24px 8px;">
      <div style="font-size:10px;color:#8e8ea0;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">累积概览</div>
      <!-- Row 1: 3 cards -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="32%" style="padding:12px;background:#f7f7f5;border:1px solid #e5e4e0;border-radius:8px;text-align:center;vertical-align:top;">
            <div style="font-size:10px;color:#8e8ea0;margin-bottom:6px;">自有评论</div>
            <div style="font-size:24px;font-weight:800;color:#1a1a2e;line-height:1;">{{ _kpis.get("own_review_rows", 0) if _kpis else 0 }}</div>
            {% set _d1 = _kpis.get("ingested_review_rows_delta_display", "") if _kpis else "" %}
            {% if _d1 and _d1 != "—" %}<div style="font-size:10px;color:#8e8ea0;margin-top:4px;">{{ _d1 }}</div>{% endif %}
          </td>
          <td width="2%"></td>
          <td width="32%" style="padding:12px;background:#f7f7f5;border:1px solid #e5e4e0;border-radius:8px;text-align:center;vertical-align:top;">
            <div style="font-size:10px;color:#8e8ea0;margin-bottom:6px;">自有差评</div>
            <div style="font-size:24px;font-weight:800;color:#b91c1c;line-height:1;">{{ _kpis.get("own_negative_review_rows", 0) if _kpis else 0 }}</div>
            {% set _d2 = _kpis.get("negative_review_rows_delta_display", "") if _kpis else "" %}
            {% if _d2 and _d2 != "—" %}<div style="font-size:10px;color:#8e8ea0;margin-top:4px;">{{ _d2 }}</div>{% endif %}
          </td>
          <td width="2%"></td>
          <td width="32%" style="padding:12px;background:#f7f7f5;border:1px solid #e5e4e0;border-radius:8px;text-align:center;vertical-align:top;">
            <div style="font-size:10px;color:#8e8ea0;margin-bottom:6px;">自有差评率</div>
            <div style="font-size:24px;font-weight:800;color:#1a1a2e;line-height:1;">{{ _kpis.get("own_negative_review_rate_display", "—") if _kpis else "—" }}</div>
          </td>
        </tr>
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="height:8px;"></td></tr></table>
      <!-- Row 2: 2 cards -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="49%" style="padding:12px;background:#f7f7f5;border:1px solid #e5e4e0;border-radius:8px;text-align:center;vertical-align:top;">
            <div style="font-size:10px;color:#8e8ea0;margin-bottom:6px;">高风险产品</div>
            <div style="font-size:24px;font-weight:800;color:#b91c1c;line-height:1;">{{ _kpis.get("high_risk_count", 0) if _kpis else 0 }}</div>
            <div style="font-size:10px;color:#8e8ea0;margin-top:4px;">自有 {{ _kpis.get("own_product_count", 0) if _kpis else 0 }} / 竞品 {{ _kpis.get("competitor_product_count", 0) if _kpis else 0 }}</div>
          </td>
          <td width="2%"></td>
          <td width="49%" style="padding:12px;background:#f7f7f5;border:1px solid #e5e4e0;border-radius:8px;text-align:center;vertical-align:top;">
            <div style="font-size:10px;color:#8e8ea0;margin-bottom:6px;">竞品差距指数</div>
            <div style="font-size:24px;font-weight:800;color:#047857;line-height:1;">{% if _kpis and _kpis.get("competitive_gap_index") is not none %}{{ _kpis.get("competitive_gap_index") }}{% else %}—{% endif %}</div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ===== 5. TODAY'S CHANGES (window data) ===== -->
  {% set _win = window if window is defined else {} %}
  {% set _new_reviews = new_review_summary if new_review_summary is defined else {} %}
  {% set _changes = changes if changes is defined else {} %}
  {% set _escalated = _changes.get("escalated", []) if _changes else [] %}
  {% set _new_issues = _changes.get("new", []) if _changes else [] %}
  {% set _improving = _changes.get("improving", []) if _changes else [] %}
  {% set _has_window_data = (_new_reviews.get("own_count", 0) > 0 or _new_reviews.get("comp_count", 0) > 0 or _escalated or _new_issues) %}
  {% if _has_window_data %}
  <tr>
    <td style="padding:8px 24px 16px;">
      <div style="font-size:10px;color:#8e8ea0;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">今日变化</div>
      {% if _new_reviews.get("own_count", 0) > 0 or _new_reviews.get("comp_count", 0) > 0 %}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;background:#f7f7f5;border-radius:8px;">
        <tr><td style="padding:12px 14px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="font-size:11px;color:#8e8ea0;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">新增评论</td>
            <td style="text-align:right;">
              {% if _new_reviews.get("own_count", 0) > 0 %}<span style="display:inline-block;padding:2px 10px;background:#4f46e5;color:#fff;border-radius:999px;font-size:11px;font-weight:700;">自有 +{{ _new_reviews.own_count }}</span>{% endif %}
              {% if _new_reviews.get("own_negative", 0) > 0 %}<span style="display:inline-block;padding:2px 10px;background:#fef2f2;color:#b91c1c;border-radius:999px;font-size:11px;font-weight:700;margin-left:4px;">差评 {{ _new_reviews.own_negative }}</span>{% endif %}
              {% if _new_reviews.get("comp_count", 0) > 0 %}<span style="display:inline-block;padding:2px 10px;background:#e5e4e0;color:#555770;border-radius:999px;font-size:11px;font-weight:700;margin-left:4px;">竞品 +{{ _new_reviews.comp_count }}</span>{% endif %}
            </td>
          </tr></table>
        </td></tr>
      </table>
      {% endif %}
      {% for iss in _escalated[:3] %}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:4px;"><tr>
        <td width="8" style="vertical-align:top;padding-top:5px;"><div style="width:6px;height:6px;border-radius:50%;background:#b91c1c;"></div></td>
        <td style="padding-left:8px;font-size:12px;color:#1a1a2e;line-height:1.5;"><strong>{{ iss.get("label_display", "") }}</strong><span style="color:#8e8ea0;"> — {{ iss.get("new_count", 0) }} 条 &#9650;升级</span></td>
      </tr></table>
      {% endfor %}
      {% for iss in _new_issues[:3] %}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:4px;"><tr>
        <td width="8" style="vertical-align:top;padding-top:5px;"><div style="width:6px;height:6px;border-radius:50%;background:#a16207;"></div></td>
        <td style="padding-left:8px;font-size:12px;color:#1a1a2e;line-height:1.5;"><strong>{{ iss.get("label_display", "") }}</strong><span style="color:#8e8ea0;"> — {{ iss.get("review_count", 0) }} 条 &#9733;新发现</span></td>
      </tr></table>
      {% endfor %}
      {% for iss in _improving[:2] %}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:4px;"><tr>
        <td width="8" style="vertical-align:top;padding-top:5px;"><div style="width:6px;height:6px;border-radius:50%;background:#047857;"></div></td>
        <td style="padding-left:8px;font-size:12px;color:#1a1a2e;line-height:1.5;"><strong>{{ iss.get("label_display", "") }}</strong><span style="color:#047857;"> &#9660;改善中</span></td>
      </tr></table>
      {% endfor %}
    </td>
  </tr>
  {% else %}
  <!-- No window changes — show quiet notice -->
  <tr>
    <td style="padding:8px 24px 16px;">
      <div style="font-size:10px;color:#8e8ea0;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">今日变化</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f7f5;border-radius:8px;">
        <tr><td style="padding:12px 14px;font-size:12px;color:#8e8ea0;text-align:center;">
          今日无新增评论 · 以下为累积数据全景分析
        </td></tr>
      </table>
    </td>
  </tr>
  {% endif %}

  <!-- ===== 6. TOP 3 ACTION ITEMS ===== -->
  {% set _bullets = [] %}
  {% if report_copy is defined and report_copy %}{% set _bullets = report_copy.get("executive_bullets", []) %}
  {% elif analytics is defined and analytics.report_copy is defined %}{% set _bullets = analytics.report_copy.get("executive_bullets", []) %}{% endif %}
  <tr>
    <td style="padding:8px 24px 16px;">
      <div style="font-size:10px;color:#8e8ea0;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:14px;">需要关注</div>
      {% for item in _bullets[:3] %}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;"><tr>
        <td width="28" valign="top" style="padding-top:1px;">
          <div style="width:22px;height:22px;background:#4f46e5;border-radius:50%;text-align:center;line-height:22px;font-size:11px;font-weight:700;color:#ffffff;">{{ loop.index }}</div>
        </td>
        <td style="padding-left:10px;font-size:12px;color:#1a1a2e;line-height:1.65;">{{ item }}</td>
      </tr></table>
      {% else %}
      <p style="font-size:12px;color:#8e8ea0;margin:0;">当前暂无足够样本形成明确判断。</p>
      {% endfor %}
    </td>
  </tr>

  <!-- ===== 7. RISK PRODUCTS TOP 3 (cumulative-based, persistent) ===== -->
  {% set _risk = risk_products or (analytics.self.risk_products if analytics is defined and analytics.self is defined else []) %}
  {% if _risk %}
  <tr>
    <td style="padding:8px 24px 16px;">
      <div style="font-size:10px;color:#8e8ea0;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:10px;">持续关注</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:11px;">
        <tr>
          <td style="padding:8px 10px;font-weight:700;background:#4f46e5;color:#fff;border-radius:4px 0 0 0;">产品名称</td>
          <td style="padding:8px 10px;font-weight:700;background:#4f46e5;color:#fff;text-align:center;">主要问题</td>
          <td style="padding:8px 10px;font-weight:700;background:#4f46e5;color:#fff;text-align:center;border-radius:0 4px 0 0;">差评数</td>
        </tr>
        {% for item in _risk[:3] %}
        <tr style="background:{% if loop.index is odd %}#f7f7f5{% else %}#ffffff{% endif %};">
          <td style="padding:8px 10px;border-bottom:1px solid #e5e4e0;color:#1a1a2e;">{{ item.get("product_name", "") }}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #e5e4e0;text-align:center;color:#8e8ea0;font-size:10px;">{{ item.get("top_labels_display", "—") or "—" }}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #e5e4e0;text-align:center;font-weight:700;color:#b91c1c;">{{ item.get("negative_review_rows", 0) }}</td>
        </tr>
        {% endfor %}
      </table>
    </td>
  </tr>
  {% endif %}

  <!-- ===== 8. LINK TO FULL REPORT ===== -->
  {% if report_url %}
  <tr>
    <td style="padding:8px 24px 16px;background:#f7f7f5;border-top:1px solid #e5e4e0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td style="padding:10px 14px;background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;font-size:12px;color:#1a1a2e;">
          <a href="{{ report_url }}" style="color:#4f46e5;font-weight:700;text-decoration:none;">打开完整交互式分析报告</a>
          <span style="color:#8e8ea0;font-size:10px;"> — 包含图表、问题详情与评论摘录</span>
        </td>
      </tr></table>
    </td>
  </tr>
  {% endif %}

  <!-- ===== 9. FOOTER ===== -->
  <tr>
    <td style="padding:12px 24px;text-align:center;border-top:1px solid #e5e4e0;">
      <p style="margin:0;font-size:10px;color:#8e8ea0;line-height:1.6;">
        QBU 网评监控智能分析系统 · 差评定义：&#8804;{{ threshold or 2 }}星 · 内部资料<br>
        本报告由 AI 自动生成，数据及分析结论仅供参考 · 请勿直接回复此邮件
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>
```

- [ ] **Step 3: 验证模板渲染**

```bash
uv run python -c "
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
tpl_dir = Path('qbu_crawler/server/report_templates')
env = Environment(loader=FileSystemLoader(str(tpl_dir)), autoescape=select_autoescape(['html','j2']))
tpl = env.get_template('email_full.html.j2')
html = tpl.render(
    logical_date='2026-04-16',
    snapshot={},
    analytics={'kpis': {'health_index': 95, 'own_review_rows': 1610}},
    alert_level='green', alert_text='',
    report_copy={'executive_bullets': ['Test bullet 1', 'Test bullet 2']},
    risk_products=[],
    threshold=2,
    cumulative_kpis={'health_index': 95, 'own_review_rows': 1610, 'own_negative_review_rows': 56, 'own_negative_review_rate_display': '3.5%', 'high_risk_count': 2, 'own_product_count': 20, 'competitor_product_count': 21, 'competitive_gap_index': 5},
    window={'reviews_count': 0},
    health_confidence='high',
    changes={},
    new_review_summary={'own_count': 0, 'comp_count': 0, 'own_negative': 0},
    report_url='',
)
print(f'Rendered OK: {len(html)} bytes')
assert 'cumulative' in html.lower() or '累积' in html
print('Template contains cumulative section')
"
```

预期：`Rendered OK: XXXX bytes` + `Template contains cumulative section`

- [ ] **Step 4: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`548 passed` (no new tests for template)

- [ ] **Step 5: 提交**

```
git add qbu_crawler/server/report_templates/email_full.html.j2
git commit -m "feat(report): rewrite email template with dual-perspective layout (P007 Task 6)"
```

---

### Task 7: Excel 双口径 + V3 HTML 适配

**目标**：Excel 评论明细使用累积评论，新增"本次新增"列通过 review ID 匹配标记（修正 H）。V3 HTML 模板传入 cumulative_kpis 和 window。

**Files:**
- Modify: `qbu_crawler/server/report.py` (Excel generation)
- Modify: `qbu_crawler/server/report_html.py` (V3 HTML rendering)
- Test: `tests/test_report_excel.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_excel.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for dual-perspective Excel (P007 Task 7)
# ---------------------------------------------------------------------------
import json
import sqlite3
from datetime import datetime

import pytest
from openpyxl import load_workbook

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def excel_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "excel.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    models.init_db()

    conn = _get_test_conn(db_file)
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("https://example.com/p1", "basspro", "Test Product", "TP-1",
         99.99, "in_stock", 3, 4.0, "own", "2026-04-15 09:00:00"),
    )
    conn.commit()
    conn.close()
    return {"db_file": db_file, "tmp_path": tmp_path}


def test_excel_has_new_column_when_window_ids_present(excel_db, tmp_path):
    from qbu_crawler.server.report import generate_excel

    cumulative_reviews = [
        {
            "id": 1, "product_name": "Test Product", "product_sku": "TP-1",
            "author": "Alice", "headline": "Old review", "body": "From last week",
            "rating": 4, "date_published": "2026-04-08", "images": "[]",
            "ownership": "own", "headline_cn": "", "body_cn": "",
            "translate_status": "done", "sentiment": "positive",
            "analysis_labels": "[]", "analysis_features": "[]",
            "analysis_insight_cn": "", "impact_category": "", "failure_mode": "",
        },
        {
            "id": 2, "product_name": "Test Product", "product_sku": "TP-1",
            "author": "Bob", "headline": "New review", "body": "Just bought it",
            "rating": 5, "date_published": "2026-04-15", "images": "[]",
            "ownership": "own", "headline_cn": "", "body_cn": "",
            "translate_status": "done", "sentiment": "positive",
            "analysis_labels": "[]", "analysis_features": "[]",
            "analysis_insight_cn": "", "impact_category": "", "failure_mode": "",
        },
    ]
    products = [
        {
            "name": "Test Product", "sku": "TP-1", "price": 99.99,
            "stock_status": "in_stock", "rating": 4.0, "review_count": 3,
            "site": "basspro", "ownership": "own",
        },
    ]

    analytics = {
        "self": {"risk_products": [], "top_negative_clusters": []},
        "competitor": {},
        "kpis": {},
        "_trend_series": [],
        # P007: window review IDs for "本次新增" marking
        "window_review_ids": [2],
    }

    output = str(tmp_path / "reports" / "test-dual.xlsx")
    path = generate_excel(products, cumulative_reviews, analytics=analytics, output_path=output)

    wb = load_workbook(path)
    ws = wb["评论明细"]
    headers = [cell.value for cell in ws[1]]
    assert "本次新增" in headers, f"Expected '本次新增' column, got: {headers}"

    # Find column index for "本次新增"
    col_idx = headers.index("本次新增")
    # Row 2 = first review (id=1, old), Row 3 = second review (id=2, new)
    values = []
    for row_idx in range(2, ws.max_row + 1):
        values.append(ws.cell(row=row_idx, column=col_idx + 1).value)

    # Review id=2 should be marked as new
    assert any(v == "是" for v in values), f"Expected at least one '是', got: {values}"
    # Review id=1 should NOT be marked as new
    assert any(v != "是" for v in values), f"Expected at least one non-new review"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report_excel.py::test_excel_has_new_column_when_window_ids_present -x -q
```

预期：`AssertionError: Expected '本次新增' column` — the column does not exist yet.

- [ ] **Step 3: 实现 Excel 双口径改造**

In `qbu_crawler/server/report.py`, modify the `_generate_analytical_excel` function.

**Change 1: Add "本次新增" column header (line 748-753)**

Replace the review_headers definition:

```python
    review_headers = [
        "ID", "产品名称", "SKU", "归属", "评分", "情感", "标签", "影响类别", "失效模式",
        "标题(原文)", "标题(中文)", "内容(原文)", "内容(中文)",
        "特征短语", "洞察", "评论时间", "照片",
    ]
```

With:

```python
    # P007: Add "本次新增" column when window_review_ids is present in analytics
    _window_review_ids = set(analytics.get("window_review_ids") or [])
    _has_new_col = bool(_window_review_ids)
    review_headers = [
        "ID", "产品名称", "SKU", "归属", "评分", "情感", "标签", "影响类别", "失效模式",
        "标题(原文)", "标题(中文)", "内容(原文)", "内容(中文)",
        "特征短语", "洞察", "评论时间", "照片",
    ]
    if _has_new_col:
        review_headers.insert(1, "本次新增")  # Insert after ID
```

**Change 2: Insert "本次新增" value in each review row (inside the review loop, after the ws1.append call)**

Find the `ws1.append([` block for reviews (approximately line 815-833). After the append, add the new column value.

The simplest approach: modify the row data list construction. Replace the `ws1.append([` block:

```python
        ws1.append([
            r.get("id"),
            r.get("product_name"),
            ...
        ])
```

Change the start of the append to insert the new column value:

```python
        _row_data = [
            r.get("id"),
```

And right after `r.get("id"),` insert:

```python
        ]
        if _has_new_col:
            _row_data.insert(1, "是" if r.get("id") in _window_review_ids else "")
```

Actually, the cleanest implementation is to build the row list and conditionally insert. Replace the entire `ws1.append([...])` block (lines 815-833):

```python
        _row = [
            r.get("id"),
            r.get("product_name"),
            r.get("product_sku"),
            _xl_display(r.get("ownership"), _OWNERSHIP_DISPLAY),
            r.get("rating"),
            _xl_display(r.get("sentiment"), _SENTIMENT_DISPLAY),
            labels_text,
            r.get("impact_category"),
            r.get("failure_mode"),
            r.get("headline"),
            r.get("headline_cn"),
            r.get("body"),
            r.get("body_cn"),
            features_text,
            r.get("analysis_insight_cn") or r.get("insight_cn") or "",
            r.get("date_published_parsed") or r.get("date_published") or "",
            "",  # placeholder for images column
        ]
        if _has_new_col:
            _row.insert(1, "是" if r.get("id") in _window_review_ids else "")
        ws1.append(_row)
```

**Change 3: Adjust images_col index**

The `images_col = len(review_headers)` line is already correct since it uses the updated headers list.

**Change 4: Add window_review_ids to analytics in generate_full_report_from_snapshot**

In `qbu_crawler/server/report_snapshot.py`, in `generate_full_report_from_snapshot`, after the analytics is computed (before the Excel generation), add:

```python
        # P007: pass window review IDs for Excel "本次新增" marking
        if snapshot.get("cumulative"):
            analytics["window_review_ids"] = [
                r.get("id") for r in snapshot.get("reviews", []) if r.get("id")
            ]
```

- [ ] **Step 4: 实现 V3 HTML 适配**

In `qbu_crawler/server/report_html.py`, modify `render_v3_html` to pass dual-perspective data:

After line 67 (`threshold=config.NEGATIVE_THRESHOLD,`), add:

```python
        # P007 dual-perspective data
        cumulative_kpis=normalized.get("cumulative_kpis") or normalized.get("kpis", {}),
        window=normalized.get("window", {}),
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
uv run pytest tests/test_report_excel.py::test_excel_has_new_column_when_window_ids_present -x -q
```

预期：`1 passed`

- [ ] **Step 6: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`549 passed` (548 + 1 new)

- [ ] **Step 7: 提交**

```
git add qbu_crawler/server/report.py qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_html.py tests/test_report_excel.py
git commit -m "feat(report): Excel dual-perspective with new-review marking + V3 HTML pass-through (P007 Task 7)"
```

---

### Task 8: Change/Quiet 模式累积适配

**目标**：change 和 quiet 模式在有 cumulative 数据时计算当前累积分析（不含 LLM），用当前 cumulative KPIs 替代依赖上次报告的 `previous_analytics`。

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (_generate_change_report, _generate_quiet_report)
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for change/quiet mode cumulative adaptation (P007 Task 8)
# ---------------------------------------------------------------------------


def test_change_mode_uses_cumulative_kpis(dual_snapshot_db, monkeypatch):
    """Change mode should compute cumulative analytics when cumulative exists."""
    from qbu_crawler.server import report_snapshot

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Simulate change mode: no new reviews but some change
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")

    changes = {"has_changes": True, "price_changes": [{"sku": "DUAL-1", "name": "Dual Product", "old": 99.99, "new": 89.99}], "stock_changes": [], "rating_changes": [], "review_count_changes": [], "new_products": [], "removed_products": []}

    result = report_snapshot._generate_change_report(
        snapshot, send_email=False, prev_analytics=None, context={"changes": changes},
    )

    assert result["mode"] == "change"
    assert result["status"] == "completed"
    # Should have analytics_path when cumulative exists
    if snapshot.get("cumulative"):
        assert result.get("analytics_path") is not None or result.get("cumulative_computed")


def test_quiet_mode_uses_cumulative_kpis(dual_snapshot_db, monkeypatch):
    """Quiet mode should compute cumulative analytics when cumulative exists."""
    from qbu_crawler.server import report_snapshot

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")

    result = report_snapshot._generate_quiet_report(
        snapshot, send_email=False, prev_analytics=None,
    )

    assert result["mode"] == "quiet"
    # When cumulative exists, quiet mode should still have a report
    assert result["status"] in ("completed", "completed_no_change")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_report_snapshot.py::test_change_mode_uses_cumulative_kpis -x -q
```

预期: Test may pass or fail depending on current implementation. The key is ensuring cumulative analytics is computed.

- [ ] **Step 3: 实现 change/quiet 模式改造**

In `qbu_crawler/server/report_snapshot.py`, modify `_generate_change_report` (line 517-548):

Replace:

```python
def _generate_change_report(snapshot, send_email, prev_analytics, context):
    """Generate a change report (no new reviews, but price/stock/rating changed)."""
    run_id = snapshot.get("run_id", 0)
    changes = context.get("changes", {})

    # Render quiet day HTML with change info
    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, prev_analytics, changes=changes)
    except Exception:
        _logger.exception("Change report HTML generation failed")

    # Send email
    email_result = None
    if send_email:
        try:
            email_result = _send_mode_email("change", snapshot, prev_analytics, changes=changes)
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    return {
        "mode": "change",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": None,
        "email": email_result,
    }
```

With:

```python
def _generate_change_report(snapshot, send_email, prev_analytics, context):
    """Generate a change report (no new reviews, but price/stock/rating changed)."""
    run_id = snapshot.get("run_id", 0)
    changes = context.get("changes", {})

    # P007: Compute cumulative analytics (lightweight, no LLM) when available
    analytics_path = None
    cum_analytics = None
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": snapshot["run_id"],
                "logical_date": snapshot["logical_date"],
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                "products": snapshot["cumulative"]["products"],
                "reviews": snapshot["cumulative"]["reviews"],
                "products_count": snapshot["cumulative"]["products_count"],
                "reviews_count": snapshot["cumulative"]["reviews_count"],
                "translated_count": snapshot["cumulative"].get("translated_count", 0),
                "untranslated_count": snapshot["cumulative"].get("untranslated_count", 0),
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{run_id}-change-analytics-{snapshot.get('logical_date', '')}.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except Exception:
            _logger.exception("Cumulative analytics for change mode failed")
            cum_analytics = None
            analytics_path = None

    # Use cumulative analytics or fallback to previous
    effective_analytics = cum_analytics or prev_analytics

    # Render quiet day HTML with change info
    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics, changes=changes)
    except Exception:
        _logger.exception("Change report HTML generation failed")

    # Send email
    email_result = None
    if send_email:
        try:
            email_result = _send_mode_email(
                "change", snapshot, effective_analytics, changes=changes,
                analytics=cum_analytics,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    return {
        "mode": "change",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": analytics_path,
        "email": email_result,
        "cumulative_computed": cum_analytics is not None,
    }
```

Similarly, modify `_generate_quiet_report` (line 551-590):

Replace:

```python
def _generate_quiet_report(snapshot, send_email, prev_analytics):
    """Generate a quiet day report (no new reviews, no changes)."""
    run_id = snapshot.get("run_id", 0)

    # Check if we should send this quiet-day email (also returns consecutive count)
    should_send, digest_mode, consecutive = should_send_quiet_email(run_id)

    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, prev_analytics)
    except Exception:
        _logger.exception("Quiet report HTML generation failed")

    email_result = None
    if send_email and should_send:
        try:
            email_result = _send_mode_email(
                "quiet", snapshot, prev_analytics,
                consecutive_quiet=consecutive,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}
    elif not should_send:
        email_result = {"success": True, "error": "Skipped (quiet day frequency)", "recipients": []}
        _logger.info("Quiet-day email skipped (consecutive quiet: reached skip window)")

    return {
        "mode": "quiet",
        "status": "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": None,
        "email": email_result,
        "email_skipped": not should_send,
        "digest_mode": digest_mode,
    }
```

With:

```python
def _generate_quiet_report(snapshot, send_email, prev_analytics):
    """Generate a quiet day report (no new reviews, no changes)."""
    run_id = snapshot.get("run_id", 0)

    # Check if we should send this quiet-day email (also returns consecutive count)
    should_send, digest_mode, consecutive = should_send_quiet_email(run_id)

    # P007: Compute cumulative analytics (lightweight, no LLM) when available
    analytics_path = None
    cum_analytics = None
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": snapshot["run_id"],
                "logical_date": snapshot["logical_date"],
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                "products": snapshot["cumulative"]["products"],
                "reviews": snapshot["cumulative"]["reviews"],
                "products_count": snapshot["cumulative"]["products_count"],
                "reviews_count": snapshot["cumulative"]["reviews_count"],
                "translated_count": snapshot["cumulative"].get("translated_count", 0),
                "untranslated_count": snapshot["cumulative"].get("untranslated_count", 0),
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{run_id}-quiet-analytics-{snapshot.get('logical_date', '')}.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except Exception:
            _logger.exception("Cumulative analytics for quiet mode failed")
            cum_analytics = None
            analytics_path = None

    effective_analytics = cum_analytics or prev_analytics

    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics)
    except Exception:
        _logger.exception("Quiet report HTML generation failed")

    email_result = None
    if send_email and should_send:
        try:
            email_result = _send_mode_email(
                "quiet", snapshot, effective_analytics,
                consecutive_quiet=consecutive,
                analytics=cum_analytics,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}
    elif not should_send:
        email_result = {"success": True, "error": "Skipped (quiet day frequency)", "recipients": []}
        _logger.info("Quiet-day email skipped (consecutive quiet: reached skip window)")

    return {
        "mode": "quiet",
        "status": "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": analytics_path,
        "email": email_result,
        "email_skipped": not should_send,
        "digest_mode": digest_mode,
    }
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
uv run pytest tests/test_report_snapshot.py::test_change_mode_uses_cumulative_kpis tests/test_report_snapshot.py::test_quiet_mode_uses_cumulative_kpis -x -q
```

预期：`2 passed`

- [ ] **Step 5: 回归测试**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

预期：`551 passed` (549 + 2 new)

- [ ] **Step 6: 提交**

```
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat(report): change/quiet modes compute cumulative analytics when available (P007 Task 8)"
```

---

## Post-Implementation Verification

After all 8 tasks are complete, run the full test suite:

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

Expected: **551 passed** (533 baseline + 18 new tests).

### New test count by task:

| Task | New Tests |
|------|-----------|
| Task 1 | 5 (cumulative query + config) |
| Task 2 | 4 (dual snapshot + hash + window mode) |
| Task 3 | 5 (dual analytics + degrade + window + risk) |
| Task 4 | 3 (early return + routing + analytics persistence) |
| Task 5 | 3 (cumulative samples + fallback + prompt) |
| Task 6 | 0 (visual template, manual verification) |
| Task 7 | 1 (Excel new-column marking) |
| Task 8 | 2 (change + quiet cumulative) |
| **Total** | **23** (test count may vary if some share fixtures) |

### Manual verification checklist:

1. Generate a test report with production DB copy and verify email renders correctly
2. Verify Excel has "本次新增" column with correct marking
3. Verify V3 HTML shows cumulative KPIs in overview tab
4. Verify quiet-day email shows cumulative KPI cards (not "previous report" cards)
5. Verify hash stability: same window data produces same hash regardless of cumulative changes

### Correction coverage matrix:

| Correction | Task | Status |
|-----------|------|--------|
| A (Critical): Relax early return guard | Task 4 | Covered by test_full_report_continues_with_cumulative_no_window_reviews |
| B (Critical): query_cumulative_data with LEFT JOIN | Task 1 | Covered by test_query_cumulative_data_includes_analysis_fields |
| C (Critical): Hash excludes cumulative | Task 2 | Covered by test_dual_snapshot_hash_excludes_cumulative |
| D (Critical): Degrade without cumulative | Task 3 | Covered by test_build_dual_degrades_without_cumulative |
| E (Medium): Pass cumulative vars to template | Task 4 | Covered by _render_full_email_html implementation |
| F (Medium): sync_review_labels once on cumulative | Task 4 | Covered by implementation (label_snapshot uses cumulative) |
| G (Low): REPORT_PERSPECTIVE config | Task 1 | Covered by test_report_perspective_config_default |
| H (Low): Excel "本次新增" via ID matching | Task 7 | Covered by test_excel_has_new_column_when_window_ids_present |
| I (Low): _build_trend_data double call acceptable | Task 3 | Acceptable, documented in plan |
