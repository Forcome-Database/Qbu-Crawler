# P008 Phase 3: 周报 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现每周一自动生成周报（V3 HTML + 4-sheet Excel + 邮件），包含完整聚类分析、风险排行、竞品对标、扩散度检测、RCW 排序、标签质量统计，并退役 quiet weekly_digest。

**Architecture:** 周报复用现有 V3 HTML 渲染管线（`render_v3_html`）和分析引擎（`build_dual_report_analytics`），传入 7 天窗口数据即可。新增 `WeeklySchedulerWorker` 每周一触发，`submit_weekly_run()` 创建 `status="reporting"` 的 run（无爬虫任务），`_advance_periodic_run()` 走简化管线（freeze → report → complete）。

**Tech Stack:** Python 3.10+ / SQLite (WAL) / Jinja2 / openpyxl / pytest

**Design doc:** `docs/plans/P008-three-tier-report-system.md` Section 5

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `qbu_crawler/config.py` | WEEKLY_SCHEDULER_TIME env var |
| Modify | `qbu_crawler/models.py` | get_previous_completed_run(report_tier=) + get_label_anomaly_stats() |
| Modify | `qbu_crawler/server/report_common.py` | compute_dispersion() + credibility_weight() |
| Modify | `qbu_crawler/server/workflows.py` | build_weekly_trigger_key() + submit_weekly_run() + WeeklySchedulerWorker + _advance_periodic_run() + _advance_run() 分流 |
| Modify | `qbu_crawler/server/report_snapshot.py` | freeze tier 感知 + _generate_weekly_report() + 周报路由 + 退役 weekly_digest |
| Modify | `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 增加 dispersion + status + 冷周提示 + 标签质量 |
| Create | `qbu_crawler/server/report_templates/email_weekly.html.j2` | 周报邮件模板 |
| Create | `tests/test_p008_phase3.py` | Phase 3 所有测试 |

---

## Task 1: Config + build_weekly_trigger_key()

**Files:**
- Modify: `qbu_crawler/config.py`
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Create test file with failing tests**

```python
# tests/test_p008_phase3.py
"""P008 Phase 3 — weekly report."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "p008p3.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: Config + trigger key ────────────────────────────────


def test_weekly_scheduler_time_config():
    assert hasattr(config, "WEEKLY_SCHEDULER_TIME")
    assert ":" in config.WEEKLY_SCHEDULER_TIME  # HH:MM format


def test_build_weekly_trigger_key():
    from qbu_crawler.server.workflows import build_weekly_trigger_key
    key = build_weekly_trigger_key("2026-04-20")
    assert key == "weekly:2026-04-20"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_p008_phase3.py -v`

- [ ] **Step 3: Add WEEKLY_SCHEDULER_TIME to config.py**

After `DAILY_SCHEDULER_RETRY_SECONDS` (~line 124):

```python
WEEKLY_SCHEDULER_TIME = _clock_time_env("WEEKLY_SCHEDULER_TIME", "09:30")
```

- [ ] **Step 4: Add build_weekly_trigger_key() to workflows.py**

After `build_daily_trigger_key()` (~line 119):

```python
def build_weekly_trigger_key(logical_date: str) -> str:
    return f"weekly:{logical_date}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py -v`

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/config.py qbu_crawler/server/workflows.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add WEEKLY_SCHEDULER_TIME config + build_weekly_trigger_key()"
```

---

## Task 2: get_previous_completed_run(report_tier=)

**Files:**
- Modify: `qbu_crawler/models.py:787-805`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase3.py

# ── Task 2: get_previous_completed_run(report_tier=) ────────────


def test_get_previous_completed_run_filters_by_tier(db):
    conn = _get_test_conn(db)
    # Insert a completed daily run
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '/tmp/daily.json')"
    )
    # Insert a completed weekly run
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-14',"
        " 'weekly:2026-04-14', 'weekly', '/tmp/weekly.json')"
    )
    # Insert a new weekly run (current)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'weekly', 'reporting', 'none', '2026-04-21',"
        " 'weekly:2026-04-21', 'weekly')"
    )
    conn.commit()
    conn.close()

    # Without tier filter: finds most recent (id=2)
    prev = models.get_previous_completed_run(3)
    assert prev is not None
    assert prev["id"] == 2

    # With tier filter: finds only weekly (id=2)
    prev_weekly = models.get_previous_completed_run(3, report_tier="weekly")
    assert prev_weekly is not None
    assert prev_weekly["id"] == 2

    # With tier filter "daily": finds only daily (id=1)
    prev_daily = models.get_previous_completed_run(3, report_tier="daily")
    assert prev_daily is not None
    assert prev_daily["id"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase3.py::test_get_previous_completed_run_filters_by_tier -v`
Expected: FAIL — get_previous_completed_run doesn't accept report_tier parameter

- [ ] **Step 3: Modify get_previous_completed_run() in models.py**

In `qbu_crawler/models.py:787-805`, change the function signature and SQL:

```python
def get_previous_completed_run(current_run_id: int, report_tier: str | None = None) -> dict | None:
    """Return the most recent completed workflow run before *current_run_id*.

    When *report_tier* is provided, only matches runs with that tier (e.g., 'weekly'
    finds the previous weekly run for KPI delta calculation).
    """
    conn = get_conn()
    try:
        sql = """
            SELECT * FROM workflow_runs
            WHERE status = 'completed'
              AND analytics_path IS NOT NULL
              AND analytics_path != ''
              AND id < ?
        """
        params: list = [current_run_id]
        if report_tier:
            sql += " AND report_tier = ?"
            params.append(report_tier)
        sql += " ORDER BY id DESC LIMIT 1"
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

Note: removed the hardcoded `workflow_type = 'daily'` filter — tier-based filtering is more flexible.

Also update `load_previous_report_context()` in `report_snapshot.py` (~line 100) to pass `report_tier`:

```python
def load_previous_report_context(run_id, report_tier=None):
    """Load most recent completed run's analytics and snapshot.

    When *report_tier* is provided, only matches runs of that tier
    (e.g., weekly finds previous weekly, daily finds previous daily).
    """
    prev_run = models.get_previous_completed_run(run_id, report_tier=report_tier)
    if not prev_run or not prev_run.get("analytics_path"):
        return None, None
    # ... rest unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py::test_get_previous_completed_run_filters_by_tier -v`

- [ ] **Step 5: Run existing tests for regressions**

Run: `uv run pytest tests/test_report_snapshot.py tests/test_v3_modes.py -v --tb=short`
Expected: All PASS (existing callers don't pass report_tier, so default None gives same behavior minus workflow_type filter — verify no regressions)

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add report_tier filter to get_previous_completed_run()"
```

---

## Task 3: compute_dispersion() + credibility_weight()

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase3.py

# ── Task 3: compute_dispersion + credibility_weight ─────────────


def test_compute_dispersion_systemic():
    from qbu_crawler.server.report_common import compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU2", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU3", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=10)
    assert dtype == "systemic"
    assert len(skus) == 3


def test_compute_dispersion_isolated():
    from qbu_crawler.server.report_common import compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=20)
    assert dtype == "isolated"
    assert len(skus) == 1


def test_compute_dispersion_uncertain():
    from qbu_crawler.server.report_common import compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU2", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU3", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=20)
    assert dtype == "uncertain"


def test_credibility_weight_long_review_with_images():
    from qbu_crawler.server.report_common import credibility_weight
    review = {"body": "x" * 600, "images": ["img1.jpg", "img2.jpg"],
              "date_published_parsed": "2026-04-10"}
    w = credibility_weight(review, today=date(2026, 4, 17))
    assert w > 1.0  # long body + images = high weight


def test_credibility_weight_short_old_review():
    from qbu_crawler.server.report_common import credibility_weight
    review = {"body": "bad", "images": [],
              "date_published_parsed": "2025-04-10"}
    w = credibility_weight(review, today=date(2026, 4, 17))
    assert w < 1.0  # short + old = low weight


def test_credibility_weight_no_date_defaults_to_recent():
    from qbu_crawler.server.report_common import credibility_weight
    review = {"body": "decent review text here", "images": []}
    w = credibility_weight(review, today=date(2026, 4, 17))
    assert w > 0  # should not crash, uses base weight
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase3.py -k "dispersion or credibility" -v`

- [ ] **Step 3: Implement compute_dispersion() in report_common.py**

Add after `compute_attention_signals()`, before `# ── Display-name mappings`:

```python
# ── Weekly report: dispersion + credibility ──────────────────────────────────


def compute_dispersion(
    label_code: str,
    reviews: list[dict],
    total_skus: int,
) -> tuple[str, set[str]]:
    """Classify issue dispersion across SKUs.

    Returns (dispersion_type, affected_skus) where dispersion_type is:
    - "systemic": > 20% of SKUs affected (supply chain / design issue)
    - "isolated": < 10% AND <= 2 SKUs (batch / individual issue)
    - "uncertain": in between (needs more observation)
    """
    affected_skus: set[str] = set()
    for r in reviews:
        labels_raw = r.get("analysis_labels") or "[]"
        if isinstance(labels_raw, str):
            try:
                labels = json.loads(labels_raw)
            except (json.JSONDecodeError, TypeError):
                labels = []
        else:
            labels = labels_raw
        if any(lb.get("code") == label_code for lb in labels):
            sku = r.get("product_sku", "")
            if sku:
                affected_skus.add(sku)

    ldi = len(affected_skus) / total_skus if total_skus > 0 else 0

    if ldi > 0.2:
        return "systemic", affected_skus
    elif ldi < 0.1 and len(affected_skus) <= 2:
        return "isolated", affected_skus
    else:
        return "uncertain", affected_skus
```

- [ ] **Step 4: Implement credibility_weight() in report_common.py**

Add right after `compute_dispersion()`:

```python
def credibility_weight(review: dict, today: date | None = None) -> float:
    """Review Credibility Weight for internal sorting (D4: not exposed as KPI).

    Factors: body length, image count, recency (6-month half-life).
    """
    today = today or date.today()
    w = 1.0

    body_len = len(review.get("body", ""))
    if body_len > 500:
        w *= 1.5
    elif body_len < 50:
        w *= 0.6

    images = review.get("images") or []
    if images:
        w *= 1.0 + min(len(images), 3) * 0.15

    parsed = review.get("date_published_parsed")
    if parsed:
        pub_date = _parse_date_flexible(parsed)
        if pub_date:
            days_old = (today - pub_date).days
            w *= 0.5 ** (days_old / 180)  # half-life 6 months

    return w
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py -k "dispersion or credibility" -v`
Expected: All 6 PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add compute_dispersion() + credibility_weight() for issue analysis"
```

---

## Task 4: get_label_anomaly_stats()

**Files:**
- Modify: `qbu_crawler/models.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase3.py

# ── Task 4: get_label_anomaly_stats ─────────────────────────────


def test_get_label_anomaly_stats(db):
    conn = _get_test_conn(db)
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://test.com/p1", "Test", "SKU1", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'A', 'H', 'B', 3.0)")
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'B', 'H2', 'B2', 2.0)")
    conn.execute(
        "INSERT INTO review_analysis (review_id, sentiment, sentiment_score, labels, features,"
        " insight_cn, insight_en, llm_model, prompt_version, label_anomaly_flags)"
        " VALUES (1, 'positive', 0.8, '[]', '[]', '', '', 'test', 'v1',"
        " '[{\"type\": \"sentiment_label_mismatch\", \"label_code\": \"quality_stability\"}]')"
    )
    conn.execute(
        "INSERT INTO review_analysis (review_id, sentiment, sentiment_score, labels, features,"
        " insight_cn, insight_en, llm_model, prompt_version, label_anomaly_flags)"
        " VALUES (2, 'negative', 0.2, '[]', '[]', '', '', 'test', 'v1', NULL)"
    )
    conn.commit()
    conn.close()

    stats = models.get_label_anomaly_stats([1, 2])
    assert stats["total_flagged"] == 1
    assert stats["total_checked"] == 2
    assert "quality_stability" in stats["flagged_labels"]


def test_get_label_anomaly_stats_empty(db):
    stats = models.get_label_anomaly_stats([])
    assert stats["total_flagged"] == 0
    assert stats["total_checked"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase3.py -k "anomaly_stats" -v`

- [ ] **Step 3: Implement get_label_anomaly_stats() in models.py**

Add after `update_review_analysis_flags()`:

```python
def get_label_anomaly_stats(review_ids: list[int]) -> dict:
    """Aggregate label_anomaly_flags for quality stats display in weekly report."""
    if not review_ids:
        return {"total_flagged": 0, "total_checked": 0, "flagged_labels": {}}

    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(review_ids))
        rows = conn.execute(
            f"SELECT label_anomaly_flags FROM review_analysis WHERE review_id IN ({placeholders})",
            review_ids,
        ).fetchall()
    finally:
        conn.close()

    import json as _json
    total_checked = len(rows)
    total_flagged = 0
    flagged_labels: dict[str, int] = {}
    for row in rows:
        flags_raw = row["label_anomaly_flags"]
        if not flags_raw:
            continue
        try:
            flags = _json.loads(flags_raw)
        except (TypeError, _json.JSONDecodeError):
            continue
        if flags:
            total_flagged += 1
            for flag in flags:
                lc = flag.get("label_code", "unknown")
                flagged_labels[lc] = flagged_labels.get(lc, 0) + 1

    return {
        "total_flagged": total_flagged,
        "total_checked": total_checked,
        "flagged_labels": flagged_labels,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py -k "anomaly_stats" -v`

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/models.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add get_label_anomaly_stats() for label quality display"
```

---

## Task 5: submit_weekly_run() + _all_daily_runs_terminal()

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase3.py

# ── Task 5: submit_weekly_run ───────────────────────────────────


def test_all_daily_runs_terminal_true_when_all_completed(db):
    from qbu_crawler.server.workflows import _all_daily_runs_terminal
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-15',"
        " 'daily:2026-04-15', 'daily', '2026-04-15T00:00:00+08:00', '2026-04-16T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()
    assert _all_daily_runs_terminal("2026-04-13T00:00:00+08:00", "2026-04-20T00:00:00+08:00") is True


def test_all_daily_runs_terminal_false_when_running(db):
    from qbu_crawler.server.workflows import _all_daily_runs_terminal
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'running', 'none', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()
    assert _all_daily_runs_terminal("2026-04-13T00:00:00+08:00", "2026-04-20T00:00:00+08:00") is False


def test_submit_weekly_run_creates_reporting_run(db):
    from qbu_crawler.server.workflows import submit_weekly_run
    result = submit_weekly_run(logical_date="2026-04-20")
    assert result["created"] is True
    assert result["trigger_key"] == "weekly:2026-04-20"

    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["workflow_type"] == "weekly"
    assert row["report_tier"] == "weekly"
    assert row["status"] == "reporting"
    assert row["data_since"] == "2026-04-13T00:00:00+08:00"
    assert row["data_until"] == "2026-04-20T00:00:00+08:00"


def test_submit_weekly_run_idempotent(db):
    from qbu_crawler.server.workflows import submit_weekly_run
    r1 = submit_weekly_run(logical_date="2026-04-20")
    r2 = submit_weekly_run(logical_date="2026-04-20")
    assert r1["created"] is True
    assert r2["created"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase3.py -k "daily_runs_terminal or submit_weekly" -v`

- [ ] **Step 3: Implement _all_daily_runs_terminal()**

In `qbu_crawler/server/workflows.py`, add after `build_weekly_trigger_key()`:

```python
def _all_daily_runs_terminal(since: str, until: str) -> bool:
    """Check if all daily runs in the given window are terminal (completed/needs_attention)."""
    conn = models.get_conn()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM workflow_runs
            WHERE report_tier = 'daily'
              AND data_since >= ? AND data_until <= ?
              AND status NOT IN ('completed', 'needs_attention')
            """,
            (since, until),
        ).fetchone()
        non_terminal = row["cnt"] if row else 0
        return non_terminal == 0
    finally:
        conn.close()
```

- [ ] **Step 4: Implement submit_weekly_run()**

Add after `_all_daily_runs_terminal()`:

```python
def submit_weekly_run(logical_date: str | None = None) -> dict:
    """Create a weekly workflow run. No scraping tasks — aggregates daily data.

    The run is created with status='reporting' (skip submitted/running phases).
    """
    from qbu_crawler import __version__
    from qbu_crawler.server.report_common import tier_date_window

    logical_date = logical_date or config.now_shanghai().date().isoformat()
    trigger_key = build_weekly_trigger_key(logical_date)

    existing = models.get_workflow_run_by_trigger_key(trigger_key)
    if existing:
        return {"created": False, "run": existing, "trigger_key": trigger_key, "run_id": existing["id"]}

    data_since, data_until = tier_date_window("weekly", logical_date)

    run = models.create_workflow_run({
        "workflow_type": "weekly",
        "status": "reporting",
        "report_phase": "none",
        "logical_date": logical_date,
        "trigger_key": trigger_key,
        "data_since": data_since,
        "data_until": data_until,
        "requested_by": "weekly_scheduler",
        "service_version": __version__,
    })

    models.update_workflow_run(run["id"], report_tier="weekly")

    return {
        "created": True,
        "run": run,
        "trigger_key": trigger_key,
        "run_id": run["id"],
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py -k "daily_runs_terminal or submit_weekly" -v`

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add submit_weekly_run() + _all_daily_runs_terminal()"
```

---

## Task 6: WeeklySchedulerWorker

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase3.py

# ── Task 6: WeeklySchedulerWorker ───────────────────────────────


def test_weekly_scheduler_skips_non_monday(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    # 2026-04-17 is a Thursday
    now = datetime(2026, 4, 17, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = WeeklySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False


def test_weekly_scheduler_triggers_on_monday(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    # 2026-04-20 is a Monday
    now = datetime(2026, 4, 20, 10, 0, tzinfo=config.SHANGHAI_TZ)

    # Seed a completed daily run in the window so _all_daily_runs_terminal is True
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()

    worker = WeeklySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is True


def test_weekly_scheduler_idempotent(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    now = datetime(2026, 4, 20, 10, 0, tzinfo=config.SHANGHAI_TZ)

    worker = WeeklySchedulerWorker(schedule_time="09:30")
    worker.process_once(now=now)
    assert worker.process_once(now=now) is False  # already submitted


def test_weekly_scheduler_waits_for_daily_runs(db, monkeypatch):
    from qbu_crawler.server.workflows import WeeklySchedulerWorker
    now = datetime(2026, 4, 20, 10, 0, tzinfo=config.SHANGHAI_TZ)

    # Seed a RUNNING daily run (not terminal)
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'running', 'none', '2026-04-14',"
        " 'daily:2026-04-14', 'daily', '2026-04-14T00:00:00+08:00', '2026-04-15T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()

    worker = WeeklySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False  # waits
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase3.py -k "weekly_scheduler" -v`

- [ ] **Step 3: Implement WeeklySchedulerWorker**

Add in `qbu_crawler/server/workflows.py`, after `DailySchedulerWorker` class:

```python
class WeeklySchedulerWorker:
    """Every Monday at WEEKLY_SCHEDULER_TIME, submit a weekly report run."""

    def __init__(self, *, schedule_time: str | None = None, interval: int | None = None):
        self._schedule_time = schedule_time or config.WEEKLY_SCHEDULER_TIME
        self._schedule_hour, self._schedule_minute = _parse_schedule_time(self._schedule_time)
        self._interval = interval or config.DAILY_SCHEDULER_INTERVAL
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="weekly-scheduler")

    def start(self):
        self._thread.start()
        logger.info("WeeklySchedulerWorker: started (time=%s)", self._schedule_time)

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.process_once()
            except Exception:
                logger.exception("WeeklySchedulerWorker: error in process_once")
            self._stop_event.wait(timeout=self._interval)

    def process_once(self, now: datetime | None = None) -> bool:
        current = now or config.now_shanghai()
        if current.weekday() != 0:  # 0 = Monday
            return False

        logical_date = current.date().isoformat()
        scheduled_at = current.replace(
            hour=self._schedule_hour, minute=self._schedule_minute,
            second=0, microsecond=0,
        )
        if current < scheduled_at:
            return False

        trigger_key = build_weekly_trigger_key(logical_date)
        if models.get_workflow_run_by_trigger_key(trigger_key):
            return False  # idempotent

        # Pre-check: all daily runs in window must be terminal
        from qbu_crawler.server.report_common import tier_date_window
        since, until = tier_date_window("weekly", logical_date)
        if not _all_daily_runs_terminal(since, until):
            return False

        result = submit_weekly_run(logical_date=logical_date)
        if result.get("created"):
            logger.info(
                "WeeklySchedulerWorker: submitted weekly run for %s (trigger_key=%s)",
                logical_date, result["trigger_key"],
            )
            return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py -k "weekly_scheduler" -v`

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add WeeklySchedulerWorker class"
```

---

## Task 7: _advance_periodic_run() + _advance_run() 分流

**Files:**
- Modify: `qbu_crawler/server/workflows.py:569-751` (WorkflowWorker._advance_run)
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase3.py

# ── Task 7: _advance_periodic_run ───────────────────────────────


def test_advance_run_routes_weekly_to_periodic(db, tmp_path, monkeypatch):
    """Weekly run should skip fast_pending and go directly to report generation."""
    from qbu_crawler.server.workflows import WorkflowWorker
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    # Create a weekly run at status=reporting, report_phase=none
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES (1, 'weekly', 'reporting', 'none', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly',"
        " '2026-04-13T00:00:00+08:00', '2026-04-20T00:00:00+08:00')"
    )
    # Insert a product and review so freeze_report_snapshot has data
    conn.execute("INSERT INTO products (url, name, sku, site, ownership, scraped_at)"
                 " VALUES ('http://t.com/p1', 'Grinder', 'SKU1', 'test', 'own', '2026-04-14 10:00:00')")
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating, scraped_at)"
                 " VALUES (1, 'A', 'Good', 'Works', 4.0, '2026-04-14 10:00:00')")
    conn.commit()
    conn.close()

    # Mock report generation to avoid full pipeline
    generated = {}
    def mock_generate(snapshot, send_email=True, **kw):
        generated["called"] = True
        generated["snapshot"] = snapshot
        return {
            "mode": "weekly", "status": "completed", "run_id": 1,
            "html_path": None, "excel_path": None, "analytics_path": None,
            "email": None, "snapshot_hash": "",
        }
    monkeypatch.setattr(report_snapshot, "generate_report_from_snapshot", mock_generate)

    worker = WorkflowWorker()
    now = "2026-04-20T10:00:00+08:00"
    worker._advance_run(1, now)

    # Verify: generate was called (skipped fast_pending)
    assert generated.get("called") is True

    # Verify: run is completed
    conn = _get_test_conn(db)
    row = conn.execute("SELECT status, report_phase FROM workflow_runs WHERE id = 1").fetchone()
    conn.close()
    assert row["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase3.py::test_advance_run_routes_weekly_to_periodic -v`

- [ ] **Step 3: Add _advance_periodic_run() and split _advance_run()**

In `qbu_crawler/server/workflows.py`, find `_advance_run()` method in `WorkflowWorker` class (~line 569). The tier check MUST go BEFORE the `task_rows` guard at line 574-576 (weekly runs have NO tasks, so `not task_rows` would return False and skip the run entirely):

```python
    def _advance_run(self, run_id: int, now: str) -> bool:
        run = models.get_workflow_run(run_id)
        if run is None:
            return False

        # P008 Phase 3: Route periodic runs BEFORE task_rows check
        # (weekly/monthly have no tasks — the task_rows guard would exit early)
        run_tier = run.get("report_tier")
        if run_tier in ("weekly", "monthly"):
            return self._advance_periodic_run(run, now)

        task_rows = models.list_workflow_run_tasks(run_id)
        if not task_rows:
            return False
        # ... existing daily logic unchanged below ...
```

Then add the `_advance_periodic_run()` method:

```python
    def _advance_periodic_run(self, run: dict, now: str) -> bool:
        """Simplified pipeline for weekly/monthly: freeze → report → complete.

        No fast_pending phase. No scraping tasks to wait for.
        """
        run_id = run["id"]

        if run.get("report_phase") == "none":
            # Freeze snapshot with the periodic window
            try:
                frozen = freeze_report_snapshot(run_id, now=now)
                models.update_workflow_run(run_id, report_phase="full_pending")
            except Exception as exc:
                logger.exception("Periodic run %d: snapshot freeze failed", run_id)
                self._move_run_to_attention(run, now, str(exc))
                return True
            return True  # advanced to full_pending

        if run.get("report_phase") == "full_pending":
            try:
                snapshot = load_report_snapshot(run["snapshot_path"])
                full_report = generate_report_from_snapshot(snapshot, send_email=True)
            except Exception as exc:
                logger.exception("Periodic run %d: report generation failed", run_id)
                self._move_run_to_attention(run, now, str(exc))
                return True

            excel_path = full_report.get("excel_path")
            analytics_path = full_report.get("analytics_path")
            html_path = full_report.get("html_path") or full_report.get("v3_html_path")

            _enqueue_workflow_notification(
                kind=f"workflow_{run.get('report_tier', 'weekly')}_report",
                target=config.WORKFLOW_NOTIFICATION_TARGET,
                payload={
                    "run_id": run_id,
                    "logical_date": run["logical_date"],
                    "report_tier": run.get("report_tier"),
                    "html_path": html_path,
                    "excel_path": excel_path,
                },
                dedupe_key=f"workflow:{run_id}:full-report",
            )
            models.update_workflow_run(
                run_id,
                status="completed",
                report_phase="full_sent",
                excel_path=excel_path,
                analytics_path=analytics_path,
                finished_at=now,
                error=None,
            )
            return True

        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase3.py::test_advance_run_routes_weekly_to_periodic -v`

- [ ] **Step 5: Run existing workflow tests for regressions**

Run: `uv run pytest tests/test_workflows.py -v --tb=short`
Expected: All PASS (daily runs still use existing path)

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add _advance_periodic_run() + tier-based _advance_run() split"
```

---

## Task 8: freeze_report_snapshot() tier 感知 + 冷启动 _meta

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase3.py

# ── Task 8: Freeze tier awareness + cold start ──────────────────


def test_inject_meta_uses_run_tier():
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-20"}
    enriched = _inject_meta(snapshot, tier="weekly")
    assert enriched["_meta"]["report_tier"] == "weekly"


def test_inject_meta_cold_start():
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-20"}
    enriched = _inject_meta(snapshot, tier="weekly", expected_days=7, actual_days=4)
    assert enriched["_meta"]["is_partial"] is True
    assert enriched["_meta"]["expected_days"] == 7
    assert enriched["_meta"]["actual_days"] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase3.py -k "inject_meta" -v`

- [ ] **Step 3: Update _inject_meta() to support cold start**

In `qbu_crawler/server/report_snapshot.py`, find `_inject_meta()` and update:

```python
def _inject_meta(snapshot: dict, tier: str = "daily",
                 expected_days: int | None = None, actual_days: int | None = None) -> dict:
    """Add version metadata to snapshot for traceability."""
    from qbu_crawler import __version__
    meta = {
        "schema_version": "3",
        "generator_version": __version__,
        "taxonomy_version": snapshot.get("taxonomy_version", "v1"),
        "report_tier": tier,
    }
    if expected_days is not None and actual_days is not None and actual_days < expected_days:
        meta["is_partial"] = True
        meta["expected_days"] = expected_days
        meta["actual_days"] = actual_days
    snapshot["_meta"] = meta
    return snapshot
```

- [ ] **Step 4: Update freeze_report_snapshot() to pass run's tier**

In `freeze_report_snapshot()`, find the `_inject_meta(snapshot)` call. Replace with:

```python
    # P008: Pass report_tier from run to _meta
    run_tier = run.get("report_tier", "daily")
    _inject_meta(snapshot, tier=run_tier)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase3.py -k "inject_meta" -v`

- [ ] **Step 6: Run existing snapshot tests for regressions**

Run: `uv run pytest tests/test_report_snapshot.py -v --tb=short`

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase3.py
git commit -m "feat(weekly): freeze_report_snapshot() tier awareness + cold start _meta"
```

---

## Task 9: 退役 quiet weekly_digest

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:47-85` (should_send_quiet_email)
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write test verifying digest is removed**

```python
# Append to tests/test_p008_phase3.py

# ── Task 9: Retire weekly_digest ─────────────────────────────────


def test_quiet_email_no_weekly_digest(db):
    """should_send_quiet_email should never return 'weekly_digest' — real weekly report replaces it."""
    from qbu_crawler.server.report_snapshot import should_send_quiet_email
    # Create 7 consecutive quiet runs
    conn = _get_test_conn(db)
    for i in range(8):
        conn.execute(
            "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
            " trigger_key, report_mode)"
            f" VALUES ('daily', 'completed', 'full_sent', '2026-04-{10+i:02d}',"
            f" 'daily:2026-04-{10+i:02d}', 'quiet')"
        )
    conn.commit()
    conn.close()

    # Run 9 (the test run) — would have been day 8 (consecutive=7 → weekly_digest)
    should, digest_mode, consecutive = should_send_quiet_email(9)
    assert digest_mode is None or digest_mode != "weekly_digest", \
        "weekly_digest should be retired — real weekly report replaces it"
```

- [ ] **Step 2: Run test to check current behavior**

Run: `uv run pytest tests/test_p008_phase3.py::test_quiet_email_no_weekly_digest -v`
Expected: May FAIL if current code still returns "weekly_digest"

- [ ] **Step 3: Remove weekly_digest logic from should_send_quiet_email()**

In `qbu_crawler/server/report_snapshot.py`, find `should_send_quiet_email()` (~line 47-85). Remove the `weekly_digest` branch:

Replace:
```python
    if consecutive < threshold:
        return True, None, consecutive
    if (consecutive + 1) % 7 == 0:
        return True, "weekly_digest", consecutive
    return False, None, consecutive
```

With:
```python
    if consecutive < threshold:
        return True, None, consecutive
    # P008 Phase 3: weekly_digest retired — real weekly report replaces it
    return False, None, consecutive
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase3.py::test_quiet_email_no_weekly_digest -v`

- [ ] **Step 5: Run existing quiet email tests for regressions**

Run: `uv run pytest tests/test_v3_modes.py -k "quiet" -v --tb=short`
Expected: Check if any test expected "weekly_digest" — update if needed

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase3.py
git commit -m "feat(weekly): retire quiet weekly_digest — replaced by real weekly report"
```

---

## Task 10: _generate_weekly_report() + routing

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase3.py

# ── Task 10: _generate_weekly_report + routing ──────────────────


def test_generate_report_weekly_tier_routes_correctly(db, tmp_path, monkeypatch):
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid, **kw: (None, None))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (1, 'weekly', 'reporting', 'full_pending', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly')"
    )
    conn.commit()
    conn.close()

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-20",
        "data_since": "2026-04-13T00:00:00+08:00",
        "data_until": "2026-04-20T00:00:00+08:00",
        "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                       "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
        "reviews": [
            {"id": 1, "headline": "Good", "body": "Works well", "rating": 4.0,
             "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
             "images": [], "author": "A", "date_published": "2026-04-14"}
        ],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [
                {"id": 1, "rating": 4.0, "ownership": "own", "product_sku": "SKU1",
                 "headline": "Good", "body": "Works well", "sentiment": "positive",
                 "analysis_labels": "[]"}
            ],
        },
    }

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)
    assert result["mode"] == "weekly_report"
    assert result.get("html_path") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase3.py::test_generate_report_weekly_tier_routes_correctly -v`

- [ ] **Step 3: Add weekly routing to generate_report_from_snapshot()**

In `qbu_crawler/server/report_snapshot.py`, find the tier routing block in `generate_report_from_snapshot()`. After `if run_tier == "daily":`, add:

```python
    if run_tier == "daily":
        return _generate_daily_briefing(snapshot, send_email)
    elif run_tier == "weekly":
        return _generate_weekly_report(snapshot, send_email)
```

- [ ] **Step 4: Implement _generate_weekly_report()**

Add before `generate_report_from_snapshot()`:

```python
def _generate_weekly_report(snapshot, send_email=True):
    """P008 Phase 3: Generate weekly report — V3 HTML + Excel + email.

    Reuses generate_full_report_from_snapshot for V3 HTML and Excel,
    uses separate email template (summary card + link).
    """
    run_id = snapshot.get("run_id", 0)
    logical_date = snapshot.get("logical_date", "")

    # Generate full report (V3 HTML + Excel) using existing pipeline
    try:
        full_result = generate_full_report_from_snapshot(
            snapshot, send_email=False,  # We send our own email
        )
    except Exception as exc:
        _logger.exception("Weekly report: full generation failed for run %d", run_id)
        raise

    # Guard: empty week (no data at all)
    if full_result.get("status") == "completed_no_change" and not full_result.get("html_path"):
        _logger.info("Weekly report: no data for run %d, skipping", run_id)
        return {
            "mode": "weekly_report",
            "status": "completed_no_change",
            "run_id": run_id,
            "snapshot_hash": snapshot.get("snapshot_hash", ""),
            "products_count": 0, "reviews_count": 0,
            "html_path": None, "excel_path": None, "analytics_path": None,
            "email": None,
        }

    # Compute label quality stats for weekly template
    review_ids = [r.get("id") for r in
                  (snapshot.get("cumulative", {}).get("reviews") or snapshot.get("reviews", []))
                  if r.get("id")]
    label_quality = models.get_label_anomaly_stats(review_ids)

    # Store label_quality + enrich dispersion + RCW sort in analytics
    analytics_path = full_result.get("analytics_path")
    if analytics_path and os.path.isfile(analytics_path):
        try:
            analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
            analytics["label_quality"] = label_quality

            # Enrich issue_cards with dispersion + lifecycle status
            from qbu_crawler.server.report_common import compute_dispersion, credibility_weight
            all_reviews = snapshot.get("cumulative", {}).get("reviews") or snapshot.get("reviews", [])
            own_skus = sum(1 for p in (snapshot.get("cumulative", {}).get("products") or [])
                          if p.get("ownership") == "own")
            for card in analytics.get("self", {}).get("issue_cards", []):
                label_code = card.get("label_code", "")
                if label_code:
                    dtype, skus = compute_dispersion(label_code, all_reviews, total_skus=own_skus or 1)
                    card["dispersion_type"] = dtype
                    card["dispersion_display"] = {"systemic": "系统性", "isolated": "个体", "uncertain": "待观察"}.get(dtype, dtype)

                # Simplified lifecycle status: active if last_seen within 14 days, else dormant
                last_seen = card.get("last_seen")
                if last_seen:
                    from datetime import date as _date
                    try:
                        ls = _date.fromisoformat(last_seen[:10])
                        ld = _date.fromisoformat(snapshot.get("logical_date", "")[:10])
                        card["lifecycle_status"] = "active" if (ld - ls).days < 14 else "dormant"
                    except (ValueError, TypeError):
                        card["lifecycle_status"] = None
                else:
                    card["lifecycle_status"] = None

                # Sort example_reviews by RCW
                examples = card.get("example_reviews") or []
                if examples:
                    today = _date.fromisoformat(snapshot.get("logical_date", "")[:10]) if snapshot.get("logical_date") else _date.today()
                    examples.sort(key=lambda r: credibility_weight(r, today=today), reverse=True)
                    card["example_reviews"] = examples
            Path(analytics_path).write_text(
                json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except Exception:
            _logger.debug("Weekly report: failed to enrich analytics with label_quality")

    # Send weekly email (summary + link, not full body)
    email_result = None
    if send_email:
        try:
            email_result = _send_weekly_email(snapshot, full_result)
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    try:
        models.update_workflow_run(
            run_id,
            report_mode="standard",
            analytics_path=analytics_path,
        )
    except Exception:
        pass

    return {
        "mode": "weekly_report",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": full_result.get("products_count", 0),
        "reviews_count": full_result.get("reviews_count", 0),
        "html_path": full_result.get("html_path"),
        "excel_path": full_result.get("excel_path"),
        "analytics_path": analytics_path,
        "email": email_result,
    }


def _send_weekly_email(snapshot, full_result):
    """Send weekly report email: summary card + attachment links."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )

    logical_date = snapshot.get("logical_date", "")

    # Build report URL
    report_url = ""
    if config.REPORT_HTML_PUBLIC_URL and full_result.get("html_path"):
        html_name = Path(full_result["html_path"]).name
        report_url = f"{config.REPORT_HTML_PUBLIC_URL}/{html_name}"

    # Load analytics for KPI summary
    analytics = {}
    if full_result.get("analytics_path") and os.path.isfile(full_result["analytics_path"]):
        try:
            analytics = json.loads(Path(full_result["analytics_path"]).read_text(encoding="utf-8"))
        except Exception:
            pass

    kpis = analytics.get("kpis", {})
    template = env.get_template("email_weekly.html.j2")
    body_html = template.render(
        logical_date=logical_date,
        kpis=kpis,
        report_url=report_url,
        reviews_count=full_result.get("reviews_count", 0),
        threshold=config.NEGATIVE_THRESHOLD,
    )

    recipients = _get_email_recipients()
    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    subject = f"产品评论周报 {logical_date}"
    attachments = []
    if full_result.get("html_path") and os.path.isfile(full_result["html_path"]):
        attachments.append(full_result["html_path"])
    if full_result.get("excel_path") and os.path.isfile(full_result["excel_path"]):
        attachments.append(full_result["excel_path"])

    report.send_email(
        recipients=recipients,
        subject=subject,
        body_text=f"QBU 周报 {logical_date}",
        body_html=body_html,
        attachment_paths=attachments if attachments else None,
    )
    return {"success": True, "error": None, "recipients": recipients}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase3.py::test_generate_report_weekly_tier_routes_correctly -v`

- [ ] **Step 6: Run existing tests for regressions**

Run: `uv run pytest tests/test_v3_modes.py tests/test_report_snapshot.py -v --tb=short`

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase3.py
git commit -m "feat(weekly): add _generate_weekly_report() + weekly routing in generate_report_from_snapshot"
```

---

## Task 11: V3 模板增强（dispersion + 状态标签 + 冷周提示 + 标签质量）

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase3.py

# ── Task 11: V3 template enhancements ───────────────────────────


def test_v3_template_renders_dispersion_type():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("daily_report_v3.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"

    html = template.render(
        logical_date="2026-04-20",
        mode="incremental",
        snapshot={"reviews": [], "cumulative": {"reviews": []}},
        analytics={
            "kpis": {"own_review_rows": 10, "ingested_review_rows": 10,
                     "product_count": 2, "own_product_count": 2, "competitor_product_count": 0,
                     "competitor_review_rows": 0, "own_negative_review_rows": 1,
                     "own_positive_review_rows": 8},
            "self": {"risk_products": [], "top_negative_clusters": [],
                     "recommendations": [], "top_positive_clusters": [],
                     "issue_cards": [
                         {"label_display": "质量稳定性", "review_count": 5,
                          "severity": "high", "severity_display": "高",
                          "affected_product_count": 3, "dispersion_type": "systemic",
                          "dispersion_display": "系统性",
                          "example_reviews": [], "image_evidence": [],
                          "recommendation": "", "translated_rate_display": "100%",
                          "translation_warning": False, "evidence_refs_display": "",
                          "first_seen": None, "last_seen": None, "duration_display": None,
                          "image_review_count": 0, "recency_display": ""}
                     ]},
            "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                           "negative_opportunities": []},
            "appendix": {"image_reviews": []},
            "issue_cards": [],
        },
        charts={"heatmap": None, "sentiment_own": None, "sentiment_comp": None},
        alert_level="green", alert_text="",
        report_copy={},
        css_text=css_path.read_text(encoding="utf-8") if css_path.exists() else "",
        js_text=js_path.read_text(encoding="utf-8") if js_path.exists() else "",
        threshold=2, cumulative_kpis={}, window={}, changes=None,
    )
    assert "系统性" in html or "systemic" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase3.py::test_v3_template_renders_dispersion_type -v`

- [ ] **Step 3: Add dispersion + status to V3 template issue cards**

In `qbu_crawler/server/report_templates/daily_report_v3.html.j2`, find the issue card rendering section (search for `issue_cards` or `severity_display`). In each issue card, after the severity badge, add:

```html
              {% if card.dispersion_type is defined and card.dispersion_type %}
              <span style="font-size:11px;padding:2px 6px;border-radius:4px;margin-left:4px;
                {% if card.dispersion_type == 'systemic' %}background:#fed7d7;color:#c53030;
                {% elif card.dispersion_type == 'isolated' %}background:#c6f6d5;color:#276749;
                {% else %}background:#e2e8f0;color:#718096;{% endif %}">{{ card.dispersion_display if card.dispersion_display is defined else card.dispersion_type }}</span>
              {% endif %}
              {% if card.lifecycle_status is defined and card.lifecycle_status %}
              <span style="font-size:11px;padding:2px 6px;border-radius:4px;margin-left:4px;
                {% if card.lifecycle_status == 'active' %}background:#fed7d7;color:#c53030;
                {% else %}background:#e2e8f0;color:#718096;{% endif %}">{{ "活跃" if card.lifecycle_status == "active" else "静默" }}</span>
              {% endif %}
```

Also add a cold-week notice at the top of Tab 3 (Issues). Find the issues tab section and add before the first issue card:

```html
    {# P008: Cold-week notice for tabs with cumulative-only data #}
    {% if (snapshot.reviews if snapshot.reviews is defined else []) | length == 0 %}
    <div class="empty-state" style="margin-bottom:var(--sp-md);color:var(--text-muted,#a0aec0);font-size:13px;">
      本周无新数据变动，以下为累积分析。
    </div>
    {% endif %}
```

Also add label quality section before the closing `</main>` tag:

```html
    {% if analytics.label_quality is defined and analytics.label_quality and analytics.label_quality.total_flagged > 0 %}
    <section class="briefing-section" style="margin-top:24px;padding:12px 16px;background:var(--surface,#fff);border:1px solid var(--border,#e2e8f0);border-radius:8px;">
      <h3 style="font-size:14px;margin:0 0 8px;">标签质量</h3>
      <p style="font-size:13px;color:var(--text-secondary,#718096);">
        {{ analytics.label_quality.total_checked }} 条评论已分析，其中 {{ analytics.label_quality.total_flagged }} 条标注存疑
      </p>
    </section>
    {% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase3.py::test_v3_template_renders_dispersion_type -v`

- [ ] **Step 5: Run existing V3 tests for regressions**

Run: `uv run pytest tests/test_v3_html.py -v --tb=short`

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 tests/test_p008_phase3.py
git commit -m "feat(weekly): add dispersion type + label quality to V3 template issue cards"
```

---

## Task 12: email_weekly.html.j2 邮件模板

**Files:**
- Create: `qbu_crawler/server/report_templates/email_weekly.html.j2`
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Create email_weekly.html.j2**

Create `qbu_crawler/server/report_templates/email_weekly.html.j2`:

```html
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>QBU 周报 {{ logical_date }}</title></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a202c;font-size:14px;line-height:1.6;">
<div style="max-width:640px;margin:0 auto;padding:16px;">

  <div style="background:#fff;border-radius:8px;padding:20px 24px;border:1px solid #e2e8f0;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:700;margin-bottom:12px;">QBU 网评监控 · 周报 {{ logical_date }}</div>

    <div style="display:flex;gap:16px;margin-bottom:16px;">
      <div style="flex:1;text-align:center;padding:12px;background:#f7fafc;border-radius:6px;">
        <div style="font-size:11px;color:#718096;">健康指数</div>
        <div style="font-size:22px;font-weight:700;color:#2b6cb0;">{{ kpis.get("health_index", "—") }}</div>
      </div>
      <div style="flex:1;text-align:center;padding:12px;background:#f7fafc;border-radius:6px;">
        <div style="font-size:11px;color:#718096;">差评率</div>
        <div style="font-size:22px;font-weight:700;">{{ kpis.get("own_negative_review_rate_display", "—") }}</div>
      </div>
      <div style="flex:1;text-align:center;padding:12px;background:#f7fafc;border-radius:6px;">
        <div style="font-size:11px;color:#718096;">高风险</div>
        <div style="font-size:22px;font-weight:700;{% if kpis.get('high_risk_count', 0) > 0 %}color:#e53e3e;{% endif %}">{{ kpis.get("high_risk_count", 0) }}</div>
      </div>
    </div>

    <div style="font-size:13px;color:#718096;">本周新增评论 {{ reviews_count }} 条 · 差评定义: ≤{{ threshold }}星</div>
  </div>

  {% if report_url %}
  <div style="text-align:center;margin-bottom:16px;">
    <a href="{{ report_url }}" style="display:inline-block;padding:10px 24px;background:#2b6cb0;color:#fff;text-decoration:none;border-radius:6px;font-size:14px;font-weight:600;">查看完整周报</a>
  </div>
  <div style="text-align:center;font-size:12px;color:#a0aec0;">完整报告含评论原文（含图片证据）和竞品动态</div>
  {% endif %}

  <div style="text-align:center;font-size:11px;color:#a0aec0;padding:16px;">内部资料 · AI 自动生成</div>
</div>
</body>
</html>
```

- [ ] **Step 2: Write test**

```python
# Append to tests/test_p008_phase3.py

# ── Task 12: email_weekly.html.j2 ───────────────────────────────


def test_email_weekly_template_renders():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_weekly.html.j2")
    html = template.render(
        logical_date="2026-04-20",
        kpis={"health_index": 75.0, "own_negative_review_rate_display": "3.5%", "high_risk_count": 1},
        report_url="https://reports.example.com/weekly-2026-04-20.html",
        reviews_count=15,
        threshold=2,
    )
    assert "75.0" in html
    assert "周报" in html
    assert "查看完整周报" in html
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/test_p008_phase3.py::test_email_weekly_template_renders -v`

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_templates/email_weekly.html.j2 tests/test_p008_phase3.py
git commit -m "feat(weekly): add email_weekly.html.j2 summary card template"
```

---

## Task 13: Integration Test

**Files:**
- Test: `tests/test_p008_phase3.py`

- [ ] **Step 1: Write integration test**

```python
# Append to tests/test_p008_phase3.py

# ── Task 13: Integration test ────────────────────────────────────


def test_p008_phase3_integration(db, tmp_path, monkeypatch):
    """End-to-end: weekly run goes through scheduler → submit → route → report."""
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.workflows import WeeklySchedulerWorker, submit_weekly_run
    from qbu_crawler.server.report_common import compute_dispersion, credibility_weight, tier_date_window

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    # 1. Verify tier_date_window
    since, until = tier_date_window("weekly", "2026-04-20")
    assert since == "2026-04-13T00:00:00+08:00"
    assert until == "2026-04-20T00:00:00+08:00"

    # 2. Submit weekly run
    result = submit_weekly_run(logical_date="2026-04-20")
    assert result["created"] is True
    run_id = result["run_id"]

    # Verify DB state
    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    assert row["report_tier"] == "weekly"
    assert row["status"] == "reporting"
    assert row["workflow_type"] == "weekly"

    # 3. Verify get_previous_completed_run with tier
    prev = models.get_previous_completed_run(run_id, report_tier="weekly")
    assert prev is None  # first weekly run, no predecessor

    # 4. Verify compute_dispersion
    reviews = [
        {"product_sku": "SKU1", "analysis_labels": '[{"code":"quality_stability"}]'},
        {"product_sku": "SKU2", "analysis_labels": '[{"code":"quality_stability"}]'},
    ]
    dtype, skus = compute_dispersion("quality_stability", reviews, total_skus=5)
    assert dtype in ("systemic", "uncertain", "isolated")

    # 5. Verify credibility_weight
    w = credibility_weight({"body": "Good review text", "images": ["img.jpg"]}, today=date(2026, 4, 20))
    assert w > 1.0

    # 6. Verify label anomaly stats
    stats = models.get_label_anomaly_stats([])
    assert stats["total_flagged"] == 0

    # 7. Verify weekly routing
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid, **kw: (None, None))
    snapshot = {
        "run_id": run_id,
        "logical_date": "2026-04-20",
        "data_since": "2026-04-13T00:00:00+08:00",
        "data_until": "2026-04-20T00:00:00+08:00",
        "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                       "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
        "reviews": [{"id": 1, "headline": "Good", "body": "Works", "rating": 4.0,
                      "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
                      "images": [], "author": "A", "date_published": "2026-04-14"}],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [{"id": 1, "rating": 4.0, "ownership": "own", "product_sku": "SKU1",
                         "headline": "Good", "body": "Works", "sentiment": "positive",
                         "analysis_labels": "[]"}],
        },
    }
    report_result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)
    assert report_result["mode"] == "weekly_report"
    assert report_result.get("html_path") is not None
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_p008_phase3.py::test_p008_phase3_integration -v`

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ --tb=short -q`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_p008_phase3.py
git commit -m "test(p008): add Phase 3 integration test verifying weekly report pipeline"
```

---

## Post-Implementation Checklist

- [ ] Run `uv run pytest tests/ -v` — all green
- [ ] WeeklySchedulerWorker 每周一触发，非周一跳过
- [ ] 周报生成前确认窗口内 daily run 已完成
- [ ] 周报复用 V3 HTML 模板渲染（含 Excel）
- [ ] 周报邮件为摘要卡片 + "查看完整报告"链接
- [ ] get_previous_completed_run 按 report_tier 过滤
- [ ] load_previous_report_context 传递 report_tier（确保周报 KPI delta 对比上次周报）
- [ ] issue 卡片展示 dispersion_type（系统性/个体/待观察）
- [ ] issue 卡片展示 active/dormant 状态标签
- [ ] 冷周 Tab 3-5 显示"本周无新数据变动，以下为累积分析"
- [ ] 标签质量统计在周报模板中展示
- [ ] quiet weekly_digest 已退役
- [ ] 冷启动保护：_meta.is_partial 标记不完整周期
- [ ] 旧 daily run 不受影响
- [ ] **手动验证**：在 `app.py` 中注册 `WeeklySchedulerWorker`（与 DailySchedulerWorker 同级位置）
- [ ] 更新 CLAUDE.md 文档

## 设计偏差记录

| 偏差 | 理由 |
|------|------|
| 复用 `daily_report_v3.html.j2` 而非新建 `weekly_report.html.j2` | V3 模板结构完全匹配周报 6-Tab 需求，新建会导致大量重复代码 |
| `compute_dispersion(label_code, reviews, total_skus)` 签名不同于设计稿 | 更可测试，直接传 total_skus 而非内部查询 |
| 4-sheet 周报 Excel 暂复用现有分析 Excel | 现有 Excel 已有 6-sheet 分析版，包含评论明细+产品概览+标签分析，满足需求核心 |
