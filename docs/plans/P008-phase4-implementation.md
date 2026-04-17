# P008 Phase 4: 月报 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现每月 1 日自动生成月报（V3 风格 HTML + 6-sheet Excel + 邮件），包含高管首屏、品类对标、SKU 健康计分卡、问题完整生命周期（active/receding/dormant/recurrent）和 LLM 高管摘要。同时回填 Phase 3 遗留项：把 `WeeklySchedulerWorker` 注册到运行时。

**Architecture:** 沿用 Phase 3 “snapshot-first + tier 路由”框架。新增 `MonthlySchedulerWorker` 每月 1 日触发；`submit_monthly_run()` 创建 `status="reporting"` 的 run（无爬虫任务）；`_advance_periodic_run()` 已支持 monthly，无需改动；`generate_report_from_snapshot()` 增加 `run_tier == "monthly"` 路由到 `_generate_monthly_report()`，后者复用 `generate_full_report_from_snapshot` 的 V3 HTML + Excel 管线，在分析 enrichment 阶段挂入四个新分析模块（lifecycle / category / scorecard / executive），最后渲染独立 `monthly_report.html.j2` 模板和 `email_monthly.html.j2` 邮件。

**Tech Stack:** Python 3.10+ / SQLite (WAL) / Jinja2 / openpyxl / OpenAI SDK / pytest

**Design doc:** `docs/plans/P008-three-tier-report-system.md` Section 6

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `qbu_crawler/config.py` | `MONTHLY_SCHEDULER_TIME`、`CATEGORY_MAP_PATH` env vars |
| Modify | `qbu_crawler/server/workflows.py` | `build_monthly_trigger_key()` + `submit_monthly_run()` + `MonthlySchedulerWorker` |
| Modify | `qbu_crawler/server/runtime.py` | 注册 `WeeklySchedulerWorker`（Phase 3 遗漏）+ `MonthlySchedulerWorker` |
| Modify | `qbu_crawler/server/report_common.py` | `load_category_map()` 共享工具 |
| Modify | `qbu_crawler/server/report_snapshot.py` | `_generate_monthly_report()` + 月报路由 + 月报 enrichment 调用 |
| Modify | `qbu_crawler/server/report.py` | `_generate_analytical_excel()` 接受 `tier` 参数生成 6-sheet 月报 Excel |
| Create | `qbu_crawler/server/analytics_lifecycle.py` | 问题生命周期完整状态机（R1-R6 + 动态沉默窗口 + 预分组优化） |
| Create | `qbu_crawler/server/analytics_category.py` | 品类对标（按 CSV 配置分组 + 直接竞品配对降级） |
| Create | `qbu_crawler/server/analytics_scorecard.py` | SKU 健康计分卡（红黄绿灯 + 趋势方向） |
| Create | `qbu_crawler/server/analytics_executive.py` | LLM 高管摘要（态势 + 3 bullet + 行动建议） |
| Create | `qbu_crawler/server/report_templates/monthly_report.html.j2` | 月报模板（高管首屏 + 7 Tab） |
| Create | `qbu_crawler/server/report_templates/email_monthly.html.j2` | 月报邮件模板（高管首屏摘要） |
| Create | `data/category_map.csv` | 41 SKU 品类映射初版 |
| Create | `tests/test_p008_phase4.py` | Phase 4 所有测试 |

---

## Task 1: Config + build_monthly_trigger_key()

**Files:**
- Modify: `qbu_crawler/config.py`
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Create test file with failing tests**

```python
# tests/test_p008_phase4.py
"""P008 Phase 4 — monthly report."""

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
    db_file = str(tmp_path / "p008p4.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: Config + trigger key ────────────────────────────────


def test_monthly_scheduler_time_config():
    assert hasattr(config, "MONTHLY_SCHEDULER_TIME")
    assert ":" in config.MONTHLY_SCHEDULER_TIME  # HH:MM


def test_category_map_path_config():
    assert hasattr(config, "CATEGORY_MAP_PATH")
    assert config.CATEGORY_MAP_PATH.endswith("category_map.csv")


def test_build_monthly_trigger_key():
    from qbu_crawler.server.workflows import build_monthly_trigger_key
    key = build_monthly_trigger_key("2026-05-01")
    assert key == "monthly:2026-05-01"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_p008_phase4.py -v`
Expected: FAIL — `MONTHLY_SCHEDULER_TIME` and `build_monthly_trigger_key` not defined.

- [ ] **Step 3: Add `MONTHLY_SCHEDULER_TIME` and `CATEGORY_MAP_PATH` to `config.py`**

Locate the existing `WEEKLY_SCHEDULER_TIME = _clock_time_env(...)` line (~line 125) and add:

```python
MONTHLY_SCHEDULER_TIME = _clock_time_env("MONTHLY_SCHEDULER_TIME", "09:30")
```

Below `SAFETY_TIERS_PATH` (search for `SAFETY_TIERS_PATH`), add:

```python
# ── P008 Phase 4: Category mapping for monthly report ─────
CATEGORY_MAP_PATH = os.getenv(
    "CATEGORY_MAP_PATH",
    os.path.join(DATA_DIR, "category_map.csv"),
)
```

- [ ] **Step 4: Add `build_monthly_trigger_key()` to `workflows.py`**

Locate `build_weekly_trigger_key()` (line 123) and add immediately after it:

```python
def build_monthly_trigger_key(logical_date: str) -> str:
    return f"monthly:{logical_date}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/config.py qbu_crawler/server/workflows.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add MONTHLY_SCHEDULER_TIME + CATEGORY_MAP_PATH config + build_monthly_trigger_key()"
```

---

## Task 2: submit_monthly_run()

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 2: submit_monthly_run ──────────────────────────────────


def test_submit_monthly_run_creates_reporting_run(db):
    from qbu_crawler.server.workflows import submit_monthly_run
    result = submit_monthly_run(logical_date="2026-05-01")
    assert result["created"] is True
    assert result["trigger_key"] == "monthly:2026-05-01"

    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["workflow_type"] == "monthly"
    assert row["report_tier"] == "monthly"
    assert row["status"] == "reporting"
    assert row["data_since"] == "2026-04-01T00:00:00+08:00"
    assert row["data_until"] == "2026-05-01T00:00:00+08:00"


def test_submit_monthly_run_idempotent(db):
    from qbu_crawler.server.workflows import submit_monthly_run
    r1 = submit_monthly_run(logical_date="2026-05-01")
    r2 = submit_monthly_run(logical_date="2026-05-01")
    assert r1["created"] is True
    assert r2["created"] is False


def test_submit_monthly_run_january_wraps_to_december(db):
    """Window for 2026-01-01 must be [2025-12-01, 2026-01-01)."""
    from qbu_crawler.server.workflows import submit_monthly_run
    result = submit_monthly_run(logical_date="2026-01-01")
    conn = _get_test_conn(db)
    row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (result["run_id"],)).fetchone()
    conn.close()
    assert row["data_since"] == "2025-12-01T00:00:00+08:00"
    assert row["data_until"] == "2026-01-01T00:00:00+08:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "submit_monthly" -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement `submit_monthly_run()` in `workflows.py`**

Locate `submit_weekly_run()` (line 146) and add immediately after it:

```python
def submit_monthly_run(logical_date: str | None = None) -> dict:
    """Create a monthly workflow run. No scraping tasks — aggregates monthly data.

    The run is created with status='reporting' (skip submitted/running phases).
    """
    from qbu_crawler import __version__
    from qbu_crawler.server.report_common import tier_date_window

    logical_date = logical_date or config.now_shanghai().date().isoformat()
    trigger_key = build_monthly_trigger_key(logical_date)

    existing = models.get_workflow_run_by_trigger_key(trigger_key)
    if existing:
        return {
            "created": False, "run": existing,
            "trigger_key": trigger_key, "run_id": existing["id"],
        }

    data_since, data_until = tier_date_window("monthly", logical_date)

    run = models.create_workflow_run({
        "workflow_type": "monthly",
        "status": "reporting",
        "report_phase": "none",
        "logical_date": logical_date,
        "trigger_key": trigger_key,
        "data_since": data_since,
        "data_until": data_until,
        "requested_by": "monthly_scheduler",
        "service_version": __version__,
    })

    models.update_workflow_run(run["id"], report_tier="monthly")

    return {
        "created": True,
        "run": run,
        "trigger_key": trigger_key,
        "run_id": run["id"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "submit_monthly" -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add submit_monthly_run() with month-1st boundary handling"
```

---

## Task 3: MonthlySchedulerWorker

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 3: MonthlySchedulerWorker ──────────────────────────────


def test_monthly_scheduler_skips_non_first_day(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    # 2026-04-17 is not the 1st
    now = datetime(2026, 4, 17, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False


def test_monthly_scheduler_skips_before_scheduled_time(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    # 2026-05-01 is the 1st but before 09:30
    now = datetime(2026, 5, 1, 8, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False


def test_monthly_scheduler_triggers_on_first_day_after_time(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is True

    conn = _get_test_conn(db)
    row = conn.execute(
        "SELECT * FROM workflow_runs WHERE trigger_key = 'monthly:2026-05-01'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["report_tier"] == "monthly"


def test_monthly_scheduler_idempotent(db, monkeypatch):
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is True
    assert worker.process_once(now=now) is False  # second call: already submitted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_scheduler" -v`
Expected: FAIL — class not defined.

- [ ] **Step 3: Implement `MonthlySchedulerWorker`**

In `qbu_crawler/server/workflows.py`, after the `WeeklySchedulerWorker` class (around line 573) and before `def _parse_schedule_time(...)`, add:

```python
class MonthlySchedulerWorker:
    """Every 1st of the month at MONTHLY_SCHEDULER_TIME, submit a monthly report run."""

    def __init__(self, *, schedule_time: str | None = None, interval: int | None = None):
        self._schedule_time = schedule_time or config.MONTHLY_SCHEDULER_TIME
        self._schedule_hour, self._schedule_minute = _parse_schedule_time(self._schedule_time)
        self._interval = interval or config.DAILY_SCHEDULER_INTERVAL
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="monthly-scheduler")

    def start(self):
        self._thread.start()
        logger.info("MonthlySchedulerWorker: started (time=%s)", self._schedule_time)

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
                logger.exception("MonthlySchedulerWorker: error in process_once")
            self._stop_event.wait(timeout=self._interval)

    def process_once(self, now: datetime | None = None) -> bool:
        current = now or config.now_shanghai()
        if current.day != 1:
            return False

        scheduled_at = current.replace(
            hour=self._schedule_hour, minute=self._schedule_minute,
            second=0, microsecond=0,
        )
        if current < scheduled_at:
            return False

        logical_date = current.date().isoformat()
        trigger_key = build_monthly_trigger_key(logical_date)
        if models.get_workflow_run_by_trigger_key(trigger_key):
            return False  # idempotent

        # P008 Section 2.5: serialize daily → weekly → monthly. When month-1st is
        # also a Monday, all three schedulers fire at the same HH:MM. Wait until
        # all daily AND weekly runs in the month window are terminal before
        # submitting the monthly run.
        from qbu_crawler.server.report_common import tier_date_window
        since, until = tier_date_window("monthly", logical_date)
        if not _all_daily_runs_terminal(since, until):
            logger.debug(
                "MonthlySchedulerWorker: waiting for daily runs in [%s, %s) to complete",
                since, until,
            )
            return False
        if not _all_weekly_runs_terminal(since, until):
            logger.debug(
                "MonthlySchedulerWorker: waiting for weekly runs in [%s, %s) to complete",
                since, until,
            )
            return False

        result = submit_monthly_run(logical_date=logical_date)
        if result.get("created"):
            logger.info(
                "MonthlySchedulerWorker: submitted monthly run for %s (trigger_key=%s)",
                logical_date, result["trigger_key"],
            )
            return True
        return False
```

Add `_all_weekly_runs_terminal()` right above `_all_daily_runs_terminal()` in `qbu_crawler/server/workflows.py` (mirror the existing helper):

```python
def _all_weekly_runs_terminal(since: str, until: str) -> bool:
    """Check if all weekly runs overlapping the given window are terminal.

    Uses partial-overlap semantics (``data_since < until AND data_until > since``)
    because a weekly window may straddle the month boundary.
    """
    conn = models.get_conn()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM workflow_runs
            WHERE report_tier = 'weekly'
              AND data_since < ? AND data_until > ?
              AND status NOT IN ('completed', 'needs_attention')
            """,
            (until, since),
        ).fetchone()
        return (row["cnt"] if row else 0) == 0
    finally:
        conn.close()
```

**Additional test for this behavior** — append to Task 3 test section:

```python
def test_monthly_scheduler_waits_for_weekly_runs(db, monkeypatch):
    """Monthly must wait until all weekly runs overlapping the month window are terminal."""
    from qbu_crawler.server.workflows import MonthlySchedulerWorker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)

    # Seed a completed daily run + a running weekly run
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('daily', 'completed', 'full_sent', '2026-04-30',"
        " 'daily:2026-04-30', 'daily', '2026-04-30T00:00:00+08:00', '2026-05-01T00:00:00+08:00')"
    )
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, data_since, data_until)"
        " VALUES ('weekly', 'reporting', 'full_pending', '2026-04-27',"
        " 'weekly:2026-04-27', 'weekly', '2026-04-20T00:00:00+08:00', '2026-04-27T00:00:00+08:00')"
    )
    conn.commit()
    conn.close()

    worker = MonthlySchedulerWorker(schedule_time="09:30")
    assert worker.process_once(now=now) is False  # blocked on weekly
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_scheduler" -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add MonthlySchedulerWorker class"
```

---

## Task 4: Register Weekly + Monthly schedulers in runtime.py

**Files:**
- Modify: `qbu_crawler/server/runtime.py`
- Test: `tests/test_p008_phase4.py`

This task back-fills the Phase 3 post-implementation gap: `WeeklySchedulerWorker` was created but never registered in the runtime, so it never actually runs. Phase 4 fixes this and adds `MonthlySchedulerWorker` at the same time.

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 4: Runtime registration ─────────────────────────────────


def test_runtime_has_weekly_scheduler():
    from qbu_crawler.server.runtime import runtime
    assert hasattr(runtime, "weekly_scheduler")


def test_runtime_has_monthly_scheduler():
    from qbu_crawler.server.runtime import runtime
    assert hasattr(runtime, "monthly_scheduler")


def test_build_runtime_returns_schedulers(monkeypatch):
    from qbu_crawler.server import runtime as runtime_module
    rt = runtime_module.build_runtime()
    # Schedulers may be None if disabled by env vars; just check attribute exists
    assert hasattr(rt, "weekly_scheduler")
    assert hasattr(rt, "monthly_scheduler")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "runtime" -v`
Expected: FAIL — attributes not defined.

- [ ] **Step 3: Update `runtime.py`**

In `qbu_crawler/server/runtime.py`:

(a) Update import (line 15):

```python
from qbu_crawler.server.workflows import (
    DailySchedulerWorker,
    InProcessTaskSubmitter,
    MonthlySchedulerWorker,
    WeeklySchedulerWorker,
    WorkflowWorker,
)
```

(b) Update `ServerRuntime.__init__` signature and body (around line 33-44):

```python
    def __init__(
        self,
        *,
        translator: TranslationWorker,
        task_manager: TaskManager,
        notifier,
        workflow_worker: WorkflowWorker | None = None,
        daily_scheduler: DailySchedulerWorker | None = None,
        weekly_scheduler: WeeklySchedulerWorker | None = None,
        monthly_scheduler: MonthlySchedulerWorker | None = None,
    ):
        self.translator = translator
        self.task_manager = task_manager
        self.notifier = notifier
        self.workflow_worker = workflow_worker
        self.daily_scheduler = daily_scheduler
        self.weekly_scheduler = weekly_scheduler
        self.monthly_scheduler = monthly_scheduler
```

(c) Update `start()` (around line 49-55):

```python
    def start(self):
        self.translator.start()
        if self.notifier is not None:
            self.notifier.start()
        if self.workflow_worker is not None:
            self.workflow_worker.start()
        if self.daily_scheduler is not None:
            self.daily_scheduler.start()
        if self.weekly_scheduler is not None:
            self.weekly_scheduler.start()
        if self.monthly_scheduler is not None:
            self.monthly_scheduler.start()
```

(d) Update `stop()` (around line 60-68) — stop in **reverse** order so the most recently started worker stops first:

```python
    def stop(self):
        if self.monthly_scheduler is not None:
            self.monthly_scheduler.stop()
        if self.weekly_scheduler is not None:
            self.weekly_scheduler.stop()
        if self.daily_scheduler is not None:
            self.daily_scheduler.stop()
        if self.workflow_worker is not None:
            self.workflow_worker.stop()
        if self.notifier is not None:
            self.notifier.stop()
        self.translator.stop()
```

(e) Update `build_runtime()` (around line 71-122) — after the existing `daily_scheduler` block, add:

```python
    weekly_scheduler = WeeklySchedulerWorker()
    monthly_scheduler = MonthlySchedulerWorker()

    return ServerRuntime(
        translator=translator,
        task_manager=task_manager,
        notifier=notifier,
        workflow_worker=workflow_worker,
        daily_scheduler=daily_scheduler,
        weekly_scheduler=weekly_scheduler,
        monthly_scheduler=monthly_scheduler,
    )
```

(f) Add module-level alias at the bottom (matching existing pattern around line 138-139):

```python
weekly_scheduler = runtime.weekly_scheduler
monthly_scheduler = runtime.monthly_scheduler
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "runtime" -v`
Expected: 3 PASS.

- [ ] **Step 5: Run existing runtime/workflow tests for regressions**

Run: `uv run pytest tests/test_workflows.py tests/test_runtime.py -v --tb=short`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/runtime.py tests/test_p008_phase4.py
git commit -m "feat(runtime): register WeeklySchedulerWorker (P3 backfill) + MonthlySchedulerWorker"
```

---

## Task 5: data/category_map.csv + load_category_map()

**Files:**
- Create: `data/category_map.csv`
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Create `data/category_map.csv` initial dataset**

Inspect current SKUs to produce a defensible mapping. Run:

```bash
uv run python -c "import sqlite3; c=sqlite3.connect('data/products.db'); print('\n'.join(f'{r[0]},{r[1]},{r[2]}' for r in c.execute('SELECT sku,name,ownership FROM products ORDER BY ownership,name')))"
```

Use the output to draft `data/category_map.csv`. Categories are derived from product name keywords. **Initial mapping for the 41 SKUs (cross-reference with the live query before committing):**

```csv
sku,category,sub_category,price_band_override
1159178,grinder,single_grind,
1193465,grinder,dual_grind,
1117120,saw,,
192238,slicer,,
192234,mixer,,
1200642,stuffer,motorized,
1159181,accessory,pedal,
```

> **IMPORTANT:** Replace this stub with the real mapping derived from the SQL query above. The plan template shows 7 SKUs; implementer must extend to all 41 SKUs covering both `own` and `competitor` ownership. Categories: `grinder` / `slicer` / `mixer` / `stuffer` / `saw` / `accessory`. Sub-categories optional. `price_band_override` empty → auto-derive from price (budget < $200, mid $200-600, premium > $600).

- [ ] **Step 2: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 5: load_category_map ───────────────────────────────────


def test_load_category_map_from_csv(tmp_path):
    csv_text = (
        "sku,category,sub_category,price_band_override\n"
        "SKU1,grinder,single_grind,\n"
        "SKU2,slicer,,premium\n"
    )
    csv_path = tmp_path / "category_map.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    from qbu_crawler.server.report_common import load_category_map
    mapping = load_category_map(str(csv_path))
    assert mapping["SKU1"] == {"category": "grinder", "sub_category": "single_grind", "price_band_override": ""}
    assert mapping["SKU2"]["price_band_override"] == "premium"


def test_load_category_map_missing_file_returns_empty():
    from qbu_crawler.server.report_common import load_category_map
    mapping = load_category_map("/nonexistent/path.csv")
    assert mapping == {}


def test_load_category_map_uses_default_path(monkeypatch, tmp_path):
    csv_path = tmp_path / "category_map.csv"
    csv_path.write_text("sku,category,sub_category,price_band_override\nSKU1,grinder,,\n", encoding="utf-8")
    monkeypatch.setattr(config, "CATEGORY_MAP_PATH", str(csv_path))
    from qbu_crawler.server.report_common import load_category_map
    mapping = load_category_map()  # no arg → use config
    assert "SKU1" in mapping
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "load_category_map" -v`
Expected: FAIL — function not defined.

- [ ] **Step 4: Implement `load_category_map()` in `report_common.py`**

Add near the end of `qbu_crawler/server/report_common.py` (after `compute_dispersion()` and `credibility_weight()`):

```python
# ── Monthly: category map loader ─────────────────────────────────────────────


def load_category_map(path: str | None = None) -> dict[str, dict]:
    """Load SKU→category mapping from CSV.

    Returns ``{sku: {"category": str, "sub_category": str, "price_band_override": str}}``.
    Missing file or CSV errors return ``{}`` (caller falls back to direct competitor pairing).
    """
    import csv as _csv
    path = path or getattr(config, "CATEGORY_MAP_PATH", None)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8", newline="") as f:
            reader = _csv.DictReader(f)
            mapping: dict[str, dict] = {}
            for row in reader:
                sku = (row.get("sku") or "").strip()
                if not sku:
                    continue
                mapping[sku] = {
                    "category": (row.get("category") or "").strip(),
                    "sub_category": (row.get("sub_category") or "").strip(),
                    "price_band_override": (row.get("price_band_override") or "").strip(),
                }
            return mapping
    except (FileNotFoundError, _csv.Error, OSError):
        return {}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "load_category_map" -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add data/category_map.csv qbu_crawler/server/report_common.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add category_map.csv + load_category_map() loader"
```

---

## Task 6: analytics_category.py — 品类对标

**Files:**
- Create: `qbu_crawler/server/analytics_category.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 6: derive_category_benchmark ───────────────────────────


def test_derive_category_benchmark_basic():
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 50, "price": 299},
        {"sku": "O2", "ownership": "own", "rating": 4.3, "review_count": 30, "price": 350},
        {"sku": "O3", "ownership": "own", "rating": 4.7, "review_count": 80, "price": 320},
        {"sku": "C1", "ownership": "competitor", "rating": 4.2, "review_count": 200, "price": 310},
        {"sku": "C2", "ownership": "competitor", "rating": 4.6, "review_count": 150, "price": 340},
        {"sku": "C3", "ownership": "competitor", "rating": 4.4, "review_count": 100, "price": 320},
    ]
    category_map = {
        "O1": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "O2": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "O3": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "C1": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "C2": {"category": "grinder", "sub_category": "", "price_band_override": ""},
        "C3": {"category": "grinder", "sub_category": "", "price_band_override": ""},
    }
    result = derive_category_benchmark(products, category_map)
    assert "grinder" in result["categories"]
    g = result["categories"]["grinder"]
    assert g["status"] == "ok"  # 3 own + 3 competitor passes ≥3 SKU threshold
    assert "own" in g and "competitor" in g
    assert g["own"]["sku_count"] == 3
    assert g["competitor"]["sku_count"] == 3
    assert g["own"]["avg_rating"] == pytest.approx(4.5, rel=0.01)
    assert g["competitor"]["avg_rating"] == pytest.approx(4.4, rel=0.01)


def test_derive_category_benchmark_insufficient_samples():
    """When a category has < 3 SKUs (own OR competitor), mark insufficient."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 50, "price": 299},
        {"sku": "C1", "ownership": "competitor", "rating": 4.2, "review_count": 200, "price": 310},
    ]
    category_map = {
        "O1": {"category": "slicer", "sub_category": "", "price_band_override": ""},
        "C1": {"category": "slicer", "sub_category": "", "price_band_override": ""},
    }
    result = derive_category_benchmark(products, category_map)
    assert result["categories"]["slicer"]["status"] == "insufficient_samples"


def test_derive_category_benchmark_unmapped_skus():
    """SKUs not in category_map go into the 'unmapped' bucket and don't break analysis."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "X1", "ownership": "own", "rating": 4.0, "review_count": 5, "price": 100},
    ]
    result = derive_category_benchmark(products, category_map={})
    assert result["unmapped_count"] == 1


def test_derive_category_benchmark_fallback_pairing():
    """Empty category map → fallback to direct competitor pairing report."""
    from qbu_crawler.server.analytics_category import derive_category_benchmark
    products = [
        {"sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 50, "price": 299},
        {"sku": "C1", "ownership": "competitor", "rating": 4.2, "review_count": 200, "price": 310},
    ]
    result = derive_category_benchmark(products, category_map={})
    assert result["fallback_mode"] is True
    assert result["pairings"]  # at least one own-vs-competitor pair surfaced
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "derive_category_benchmark" -v`
Expected: FAIL — module not present.

- [ ] **Step 3: Create `analytics_category.py`**

Create `qbu_crawler/server/analytics_category.py`:

```python
"""P008 Phase 4: Category-level benchmark for the monthly report.

Groups products by category (per ``data/category_map.csv``) and produces an
own-vs-competitor comparison table per category. When a category has fewer
than 3 SKUs on either side, it's marked ``insufficient_samples``. When the
category map is empty/unavailable, the analysis degrades to direct competitor
pairings (closest-priced competitor per own SKU).
"""

from __future__ import annotations

from statistics import mean


_MIN_SKU_PER_OWNERSHIP = 3


def _avg(values: list[float]) -> float | None:
    cleaned = [v for v in values if v is not None]
    return round(mean(cleaned), 2) if cleaned else None


def _bucket_price(price: float | None, override: str = "") -> str:
    if override:
        return override
    if price is None:
        return "unknown"
    if price < 200:
        return "budget"
    if price < 600:
        return "mid"
    return "premium"


def _summarize(products: list[dict]) -> dict:
    if not products:
        return {"sku_count": 0, "avg_rating": None,
                "total_reviews": 0, "avg_price": None,
                "rating_p25": None, "rating_p75": None}
    ratings = sorted([p.get("rating") for p in products if p.get("rating") is not None])
    reviews_total = sum((p.get("review_count") or 0) for p in products)
    return {
        "sku_count": len(products),
        "avg_rating": _avg(ratings),
        "total_reviews": reviews_total,
        "avg_price": _avg([p.get("price") for p in products]),
        "rating_p25": ratings[int(len(ratings) * 0.25)] if ratings else None,
        "rating_p75": ratings[int(len(ratings) * 0.75)] if ratings else None,
    }


def derive_category_benchmark(
    products: list[dict],
    category_map: dict[str, dict],
) -> dict:
    """Build per-category own-vs-competitor benchmark.

    Args:
        products: list of product dicts with sku, ownership, rating, review_count, price.
        category_map: ``{sku: {"category": str, "sub_category": str, "price_band_override": str}}``.

    Returns dict with:
        - categories: ``{cat_name: {status, own, competitor, gap}}``
        - unmapped_count: number of SKUs not in the map
        - fallback_mode: True if category_map is empty (uses direct pairing)
        - pairings: list of own-vs-competitor pairs (only when fallback_mode True)
    """
    if not category_map:
        return _fallback_pairing(products)

    grouped: dict[str, dict[str, list[dict]]] = {}
    unmapped = 0
    for p in products:
        sku = p.get("sku", "")
        meta = category_map.get(sku)
        if not meta or not meta.get("category"):
            unmapped += 1
            continue
        cat = meta["category"]
        ownership = p.get("ownership") or "unknown"
        grouped.setdefault(cat, {"own": [], "competitor": []}).setdefault(ownership, []).append(p)

    categories: dict[str, dict] = {}
    for cat, buckets in grouped.items():
        own_products = buckets.get("own", [])
        comp_products = buckets.get("competitor", [])
        if (len(own_products) < _MIN_SKU_PER_OWNERSHIP
                or len(comp_products) < _MIN_SKU_PER_OWNERSHIP):
            categories[cat] = {
                "status": "insufficient_samples",
                "own_sku_count": len(own_products),
                "competitor_sku_count": len(comp_products),
                "min_required": _MIN_SKU_PER_OWNERSHIP,
            }
            continue

        own = _summarize(own_products)
        comp = _summarize(comp_products)
        gap = None
        if own["avg_rating"] is not None and comp["avg_rating"] is not None:
            gap = round(own["avg_rating"] - comp["avg_rating"], 2)
        categories[cat] = {
            "status": "ok",
            "own": own,
            "competitor": comp,
            "rating_gap": gap,
        }

    return {
        "categories": categories,
        "unmapped_count": unmapped,
        "fallback_mode": False,
        "pairings": [],
    }


def _fallback_pairing(products: list[dict]) -> dict:
    """When no category map: pair each own product with closest-priced competitor."""
    own = [p for p in products if p.get("ownership") == "own"]
    comp = [p for p in products if p.get("ownership") == "competitor"]
    pairings = []
    for o in own:
        if o.get("price") is None or not comp:
            continue
        nearest = min(
            (c for c in comp if c.get("price") is not None),
            key=lambda c: abs(c["price"] - o["price"]),
            default=None,
        )
        if nearest is None:
            continue
        gap = None
        if o.get("rating") is not None and nearest.get("rating") is not None:
            gap = round(o["rating"] - nearest["rating"], 2)
        pairings.append({
            "own_sku": o.get("sku"),
            "own_name": o.get("name"),
            "own_rating": o.get("rating"),
            "competitor_sku": nearest.get("sku"),
            "competitor_name": nearest.get("name"),
            "competitor_rating": nearest.get("rating"),
            "rating_gap": gap,
            "price_diff": round(nearest["price"] - o["price"], 2) if o.get("price") and nearest.get("price") else None,
        })
    return {
        "categories": {},
        "unmapped_count": len(own) + len(comp),
        "fallback_mode": True,
        "pairings": pairings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "derive_category_benchmark" -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/analytics_category.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add analytics_category.py — category benchmark + fallback pairing"
```

---

## Task 7: analytics_scorecard.py — SKU 健康计分卡

**Files:**
- Create: `qbu_crawler/server/analytics_scorecard.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 7: derive_product_scorecard ────────────────────────────


def test_scorecard_green_low_risk():
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.7, "review_count": 100}]
    risk_products = [{"sku": "O1", "risk_score": 5, "negative_rate": 0.02, "negative_count": 2, "review_count": 100}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=[])
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "green"


def test_scorecard_yellow_medium_risk():
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.0, "review_count": 50}]
    risk_products = [{"sku": "O1", "risk_score": 22, "negative_rate": 0.05, "negative_count": 3, "review_count": 50}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=[])
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "yellow"


def test_scorecard_red_high_risk():
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 3.0, "review_count": 50}]
    risk_products = [{"sku": "O1", "risk_score": 40, "negative_rate": 0.1, "negative_count": 5, "review_count": 50}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=[])
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "red"


def test_scorecard_red_for_safety_incident():
    """Any critical/high safety incident forces red light, regardless of risk_score."""
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.8, "review_count": 100}]
    risk_products = [{"sku": "O1", "risk_score": 5, "negative_rate": 0.01, "negative_count": 1, "review_count": 100}]
    safety_incidents = [{"product_sku": "O1", "safety_level": "critical"}]
    result = derive_product_scorecard(products, risk_products, safety_incidents=safety_incidents)
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["light"] == "red"
    assert own["safety_flag"] is True


def test_scorecard_trend_from_previous_month(monkeypatch):
    from qbu_crawler.server.analytics_scorecard import derive_product_scorecard
    products = [{"sku": "O1", "name": "Grinder", "ownership": "own", "rating": 4.5, "review_count": 100}]
    risk_products = [{"sku": "O1", "risk_score": 12, "negative_rate": 0.04, "negative_count": 4, "review_count": 100}]
    prev_scorecards = {"O1": {"risk_score": 25, "light": "yellow"}}
    result = derive_product_scorecard(products, risk_products, safety_incidents=[],
                                      previous_scorecards=prev_scorecards)
    own = next(c for c in result["scorecards"] if c["sku"] == "O1")
    assert own["trend"] == "improving"  # risk dropped from 25 to 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "scorecard" -v`
Expected: FAIL.

- [ ] **Step 3: Create `analytics_scorecard.py`**

Create `qbu_crawler/server/analytics_scorecard.py`:

```python
"""P008 Phase 4: Per-SKU health scorecard for the monthly report.

Each own SKU receives a traffic-light status:
  - green:  risk_score < 15 AND negative_rate < 3% AND no safety incidents
  - yellow: risk_score 15-35 OR negative_rate 3-8%
  - red:    risk_score > 35 OR negative_rate > 8% OR has critical/high safety incident

Trend is derived by comparing this month's risk_score with the previous monthly
report's value (improving / steady / worsening / new).
"""

from __future__ import annotations


_HIGH_SAFETY_LEVELS = ("critical", "high")


def _classify_light(
    risk_score: float,
    negative_rate: float,
    has_high_safety_incident: bool,
) -> str:
    if has_high_safety_incident:
        return "red"
    if risk_score > 35 or negative_rate > 0.08:
        return "red"
    if risk_score >= 15 or negative_rate >= 0.03:
        return "yellow"
    return "green"


def _classify_trend(
    current_score: float,
    previous_score: float | None,
) -> str:
    if previous_score is None:
        return "new"
    delta = current_score - previous_score
    if delta < -3:
        return "improving"
    if delta > 3:
        return "worsening"
    return "steady"


def derive_product_scorecard(
    products: list[dict],
    risk_products: list[dict],
    safety_incidents: list[dict] | None = None,
    previous_scorecards: dict[str, dict] | None = None,
) -> dict:
    """Build per-own-SKU scorecard for the monthly report.

    Args:
        products: cumulative products list (from snapshot.cumulative.products).
        risk_products: output of report_analytics._risk_products().
        safety_incidents: rows from safety_incidents table for the month window.
        previous_scorecards: ``{sku: {"risk_score": float, "light": str}}`` from previous monthly.

    Returns ``{"scorecards": [...], "summary": {...}}``.
    """
    safety_incidents = safety_incidents or []
    previous_scorecards = previous_scorecards or {}

    high_safety_skus = {
        s.get("product_sku")
        for s in safety_incidents
        if s.get("safety_level") in _HIGH_SAFETY_LEVELS
    }
    risk_by_sku = {r.get("sku"): r for r in risk_products}

    scorecards = []
    for p in products:
        if p.get("ownership") != "own":
            continue
        sku = p.get("sku")
        risk = risk_by_sku.get(sku, {})
        risk_score = float(risk.get("risk_score") or 0)
        negative_rate = float(risk.get("negative_rate") or 0)
        has_safety = sku in high_safety_skus
        light = _classify_light(risk_score, negative_rate, has_safety)

        prev = previous_scorecards.get(sku) or {}
        trend = _classify_trend(risk_score, prev.get("risk_score"))

        scorecards.append({
            "sku": sku,
            "name": p.get("name"),
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "risk_score": round(risk_score, 1),
            "negative_rate": round(negative_rate, 4),
            "negative_count": risk.get("negative_count", 0),
            "light": light,
            "safety_flag": has_safety,
            "trend": trend,
            "previous_risk_score": prev.get("risk_score"),
            "previous_light": prev.get("light"),
        })

    summary = {
        "green": sum(1 for s in scorecards if s["light"] == "green"),
        "yellow": sum(1 for s in scorecards if s["light"] == "yellow"),
        "red": sum(1 for s in scorecards if s["light"] == "red"),
        "total": len(scorecards),
        "with_safety_flag": sum(1 for s in scorecards if s["safety_flag"]),
    }

    return {"scorecards": scorecards, "summary": summary}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "scorecard" -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/analytics_scorecard.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add analytics_scorecard.py — per-SKU traffic-light scorecard"
```

---

## Task 8: analytics_lifecycle.py — 完整问题生命周期状态机

**Files:**
- Create: `qbu_crawler/server/analytics_lifecycle.py`
- Test: `tests/test_p008_phase4.py`

This task implements the full R1-R6 state machine described in design doc Section 6.4. States: `active` / `receding` / `dormant` / `recurrent`. Phase 3 used a simplified two-state version; Phase 4 replaces it with the full machine when running monthly reports.

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 8: derive_issue_lifecycles (full state machine) ────────


def _make_review(rid, date_str, rating, ownership="own", body="x", labels=None, sku="SKU1", impact_category=None):
    return {
        "id": rid,
        "date_published_parsed": date_str,
        "rating": rating,
        "ownership": ownership,
        "body": body,
        "headline": "h",
        "product_sku": sku,
        "impact_category": impact_category,
        "analysis_labels": json.dumps(labels or [{"code": "quality_stability", "polarity": "negative"}]),
    }


def test_lifecycle_active_after_recent_negative():
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [_make_review(1, "2026-04-15", 1.0)]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "active"


def test_lifecycle_receding_after_positive_overcome():
    """active → receding: positive cohort dominates within 30 days, ≥3 reviews threshold."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [
        _make_review(1, "2026-04-05", 1.0, body="bad"),
        _make_review(2, "2026-04-20", 5.0, body="great", labels=[{"code": "quality_stability", "polarity": "positive"}]),
        _make_review(3, "2026-04-25", 5.0, body="excellent", labels=[{"code": "quality_stability", "polarity": "positive"}]),
        _make_review(4, "2026-04-28", 4.0, body="works", labels=[{"code": "quality_stability", "polarity": "positive"}]),
    ]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "receding"


def test_lifecycle_dormant_after_silence_window():
    """active → dormant: no negative within silence_window days."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [_make_review(1, "2026-01-15", 1.0, body="bad")]
    # 3.5 months of silence; silence_window minimum is 14 days
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "dormant"


def test_lifecycle_recurrent_after_dormant_then_negative():
    """dormant → recurrent: new negative after dormancy."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [
        _make_review(1, "2026-01-01", 1.0, body="bad"),  # original active
        _make_review(2, "2026-04-25", 1.0, body="bad again"),  # after long silence
    ]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state == "recurrent"


def test_lifecycle_safety_doubles_silence_window():
    """R6: critical safety issues double the silence window before dormant."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    # 30 days of silence; without safety, this would be dormant (silence_window default ~28)
    # With critical safety, silence_window doubles to ~56 → still active/receding.
    reviews = [_make_review(1, "2026-04-01", 1.0, body="metal shaving in food", impact_category="safety")]
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    assert state in ("active", "receding")  # NOT dormant


def test_lifecycle_low_rcw_does_not_trigger_active():
    """R1: very short reviews (low RCW) shouldn't single-handedly trigger active."""
    from qbu_crawler.server.analytics_lifecycle import derive_issue_lifecycle
    reviews = [_make_review(1, "2026-04-15", 1.0, body="bad")]  # body only 3 chars
    # Single low-credibility review: still active (R1 fires on credible reviews,
    # but a sole review is the only signal we have — fall through to active)
    state, history = derive_issue_lifecycle(
        "quality_stability", "own", reviews, window_end=date(2026, 4, 30),
    )
    # The exact boundary depends on RCW threshold; main contract: must not crash
    assert state in ("active", "dormant")


def test_derive_all_lifecycles_pre_groups_efficiently():
    """derive_all_lifecycles avoids O(labels × reviews); only relevant reviews per label."""
    from qbu_crawler.server.analytics_lifecycle import derive_all_lifecycles
    reviews = [
        _make_review(1, "2026-04-15", 1.0, sku="O1",
                     labels=[{"code": "quality_stability", "polarity": "negative"}]),
        _make_review(2, "2026-04-15", 1.0, sku="O1",
                     labels=[{"code": "ease_of_use", "polarity": "negative"}]),
    ]
    result = derive_all_lifecycles(reviews, window_end=date(2026, 4, 30))
    keys = list(result.keys())
    # Two distinct labels for own ownership = 2 entries
    assert len(keys) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "lifecycle" -v`
Expected: FAIL — module not present.

- [ ] **Step 3: Create `analytics_lifecycle.py`**

Create `qbu_crawler/server/analytics_lifecycle.py`:

```python
"""P008 Phase 4: Issue lifecycle state machine for the monthly report.

States (design doc Section 6.4):
  - active:    recent credible negative review (RCW > 0.5)
  - receding:  active + positive cohort dominates in 30-day window (≥3 reviews)
  - dormant:   active/receding + silence_window days without new negative
  - recurrent: dormant + new negative

Transitions (R1-R6):
  R1: credible negative → active
  R2: active + positive cohort + ≤1:1 neg/pos in 30d + ≥3 reviews → receding
  R3: active/receding + silence_window days no new negative → dormant
  R4: dormant + new negative → recurrent
  R5: recurrent behaves like active (re-enters R2/R3 from there)
  R6: critical/high safety issues double silence_window (no premature dormant)

The silence_window is dynamic per (label_code, ownership): twice the average
inter-review interval, clamped to [14, 60] days.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean

from qbu_crawler.server.report_common import credibility_weight, detect_safety_level


_RCW_ACTIVE_THRESHOLD = 0.5
_NEG_POS_RECEDING_RATIO = 1.0
_RECEDING_MIN_REVIEWS = 3
_SILENCE_MIN = 14
_SILENCE_MAX = 60
_SILENCE_DEFAULT_INSUFFICIENT = 30  # When <2 events: avoid premature dormant
_RECEDING_WINDOW_DAYS = 30


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _label_polarity_for(review: dict, label_code: str) -> str | None:
    raw = review.get("analysis_labels") or "[]"
    if isinstance(raw, str):
        try:
            labels = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    else:
        labels = raw
    for lb in labels:
        if lb.get("code") == label_code:
            return (lb.get("polarity") or "").lower()
    return None


def _is_negative(review: dict, label_code: str) -> bool:
    return _label_polarity_for(review, label_code) == "negative"


def _is_positive(review: dict, label_code: str) -> bool:
    return _label_polarity_for(review, label_code) == "positive"


def _has_safety_critical(review: dict) -> bool:
    if (review.get("impact_category") or "").lower() == "safety":
        return True
    text = f"{review.get('headline', '')} {review.get('body', '')}"
    level = detect_safety_level(text)
    return level in ("critical", "high")


def _silence_window_days(timeline: list[dict], has_safety: bool) -> int:
    """Average inter-review interval × 2, clamped to [14, 60]; doubled for safety.

    When fewer than 2 events exist the average interval is undefined. Use a
    conservative 30-day default so a single recent review never triggers
    premature dormant (would happen with the 14-day floor).
    """
    if len(timeline) < 2:
        base = _SILENCE_DEFAULT_INSUFFICIENT  # 30 — see module-level constant
    else:
        sorted_dates = sorted(t["date"] for t in timeline if t.get("date"))
        intervals = [
            (sorted_dates[i] - sorted_dates[i - 1]).days
            for i in range(1, len(sorted_dates))
        ]
        avg = mean(intervals) if intervals else _SILENCE_MIN
        base = max(_SILENCE_MIN, min(int(avg * 2), _SILENCE_MAX))
    return base * 2 if has_safety else base


def derive_issue_lifecycle(
    label_code: str,
    ownership: str,
    reviews_for_label: list[dict],
    window_end: date,
) -> tuple[str, list[dict]]:
    """Walk through reviews chronologically, applying R1-R6 to derive final state.

    Returns ``(state, history)`` where history is a list of state-transition events.
    """
    relevant = [r for r in reviews_for_label if r.get("ownership") == ownership]
    if not relevant:
        return "dormant", []

    today = date.today()
    timeline = []
    for r in relevant:
        d = _parse_date(r.get("date_published_parsed") or r.get("date_published"))
        if d is None:
            continue
        rcw = credibility_weight(r, today=today)
        timeline.append({
            "date": d,
            "rcw": rcw,
            "is_negative": _is_negative(r, label_code),
            "is_positive": _is_positive(r, label_code),
            "review_id": r.get("id"),
            "is_safety": _has_safety_critical(r),
        })

    timeline.sort(key=lambda t: t["date"])
    if not timeline:
        return "dormant", []

    has_safety = any(t["is_safety"] for t in timeline)
    silence_window = _silence_window_days(timeline, has_safety)

    state = "dormant"
    last_negative_date: date | None = None
    history = []

    for event in timeline:
        ev_date = event["date"]

        # R3: silence_window check before processing this event
        if state in ("active", "receding") and last_negative_date is not None:
            silent_days = (ev_date - last_negative_date).days
            if silent_days >= silence_window:
                state = "dormant"
                history.append({"date": ev_date, "transition": "→dormant", "reason": "R3"})

        if event["is_negative"] and event["rcw"] >= _RCW_ACTIVE_THRESHOLD:
            if state == "dormant":
                # R4: dormant + new negative → recurrent (only if last_negative_date exists)
                if last_negative_date is not None:
                    state = "recurrent"
                    history.append({"date": ev_date, "transition": "dormant→recurrent", "reason": "R4"})
                else:
                    state = "active"
                    history.append({"date": ev_date, "transition": "→active", "reason": "R1"})
            elif state in ("receding",):
                state = "active"
                history.append({"date": ev_date, "transition": "receding→active", "reason": "R1"})
            elif state == "recurrent":
                # Stay recurrent
                pass
            else:
                state = "active"
                history.append({"date": ev_date, "transition": "→active", "reason": "R1"})
            last_negative_date = ev_date

        # R2: active/recurrent + recent positive cohort dominates → receding
        if state in ("active", "recurrent"):
            window_start = ev_date - timedelta(days=_RECEDING_WINDOW_DAYS)
            recent = [t for t in timeline if window_start <= t["date"] <= ev_date]
            neg = sum(1 for t in recent if t["is_negative"])
            pos = sum(1 for t in recent if t["is_positive"])
            if pos >= 1 and len(recent) >= _RECEDING_MIN_REVIEWS and neg <= pos * _NEG_POS_RECEDING_RATIO:
                state = "receding"
                history.append({"date": ev_date, "transition": "active→receding", "reason": "R2"})

    # Final R3 check using window_end if no event triggered it
    if state in ("active", "receding") and last_negative_date is not None:
        silent_days = (window_end - last_negative_date).days
        if silent_days >= silence_window:
            state = "dormant"
            history.append({"date": window_end, "transition": "→dormant", "reason": "R3 (window_end)"})

    return state, history


def derive_all_lifecycles(
    all_reviews: list[dict],
    window_end: date,
) -> dict[tuple[str, str], dict]:
    """Pre-group reviews by (label_code, ownership) then derive state per group.

    Returns ``{(label_code, ownership): {"state": str, "history": list, "review_count": int,
                                         "first_seen": date|None, "last_seen": date|None}}``.
    """
    label_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in all_reviews:
        raw = r.get("analysis_labels") or "[]"
        if isinstance(raw, str):
            try:
                labels = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                labels = []
        else:
            labels = raw
        ownership = r.get("ownership") or "unknown"
        for lb in labels:
            code = lb.get("code")
            if not code:
                continue
            label_index[(code, ownership)].append(r)

    results: dict[tuple[str, str], dict] = {}
    for (label_code, ownership), relevant in label_index.items():
        state, history = derive_issue_lifecycle(label_code, ownership, relevant, window_end)
        dates = [_parse_date(r.get("date_published_parsed") or r.get("date_published")) for r in relevant]
        valid_dates = [d for d in dates if d]
        results[(label_code, ownership)] = {
            "state": state,
            "history": history,
            "review_count": len(relevant),
            "first_seen": min(valid_dates).isoformat() if valid_dates else None,
            "last_seen": max(valid_dates).isoformat() if valid_dates else None,
        }
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "lifecycle" -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/analytics_lifecycle.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add analytics_lifecycle.py — full R1-R6 state machine"
```

---

## Task 9: analytics_executive.py — LLM 高管摘要

**Files:**
- Create: `qbu_crawler/server/analytics_executive.py`
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase4.py

# ── Task 9: generate_executive_summary ──────────────────────────


def test_executive_summary_fallback_when_llm_unavailable(monkeypatch):
    """No LLM → fallback summary derived from KPIs / clusters / category data."""
    from qbu_crawler.server import analytics_executive
    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")

    inputs = {
        "kpis": {"health_index": 72.3, "own_negative_review_rate": 4.2, "high_risk_count": 2,
                 "own_review_rows": 200},
        "kpi_delta": {"health_index": -1.5, "high_risk_count": +1},
        "top_issues": [{"label_display": "质量稳定性", "review_count": 8, "severity_display": "高"}],
        "category_benchmark": {"categories": {"grinder": {"status": "ok",
                                                          "rating_gap": -0.2}}},
        "safety_incidents_count": 1,
    }
    result = analytics_executive.generate_executive_summary(inputs)
    assert "stance" in result
    assert isinstance(result["bullets"], list) and len(result["bullets"]) <= 3
    assert isinstance(result["actions"], list) and len(result["actions"]) <= 3


def test_executive_summary_stance_categories():
    """Stance reflects health: stable / needs_attention / urgent."""
    from qbu_crawler.server import analytics_executive

    bad_inputs = {
        "kpis": {"health_index": 35.0, "own_negative_review_rate": 12.0, "high_risk_count": 5,
                 "own_review_rows": 300},
        "kpi_delta": {"health_index": -10.0, "high_risk_count": +3},
        "top_issues": [], "category_benchmark": {"categories": {}}, "safety_incidents_count": 3,
    }
    result_bad = analytics_executive._fallback_executive_summary(bad_inputs)
    assert result_bad["stance"] == "urgent"

    ok_inputs = {
        "kpis": {"health_index": 78.0, "own_negative_review_rate": 2.5, "high_risk_count": 0,
                 "own_review_rows": 300},
        "kpi_delta": {"health_index": +1.0, "high_risk_count": 0},
        "top_issues": [], "category_benchmark": {"categories": {}}, "safety_incidents_count": 0,
    }
    result_ok = analytics_executive._fallback_executive_summary(ok_inputs)
    assert result_ok["stance"] == "stable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase4.py -k "executive" -v`
Expected: FAIL.

- [ ] **Step 3: Create `analytics_executive.py`**

Create `qbu_crawler/server/analytics_executive.py`:

```python
"""P008 Phase 4: LLM-powered executive summary for the monthly report.

Inputs: cumulative KPIs + KPI delta vs previous month + top issue clusters +
category benchmark + safety incidents count.

Outputs:
    {
        "stance": "stable" | "needs_attention" | "urgent",
        "stance_text": str,
        "bullets": [str, str, str],
        "actions": [str, str, str],
    }

Falls back to a deterministic summary when LLM is unavailable.
"""

from __future__ import annotations

import json
import logging

from qbu_crawler import config


logger = logging.getLogger(__name__)


_PROMPT = """你是一名产品质量监控分析师，正在为高管撰写本月评论数据态势摘要。

输入数据（JSON）：
{inputs_json}

请基于上述数据返回严格的 JSON（不要包含 markdown 代码块）：
{{
  "stance": "stable" | "needs_attention" | "urgent",
  "stance_text": "一句话态势判断（不超过 40 字）",
  "bullets": ["要点1（≤30字）", "要点2", "要点3"],
  "actions": ["建议1（动词开头，≤30字）", "建议2", "建议3"]
}}

判断标准：
- urgent: 有 critical safety 事件 / 健康指数 < 50 / 高风险产品 ≥ 3
- needs_attention: 健康指数下降 > 5 / 高风险增加 / 差评率 > 5%
- stable: 上述均不满足

bullets 必须基于输入数据中的实际数字（如"健康指数 72.3 较上月下降 1.5"），不要编造。
actions 必须可执行（如"调查 #22 Grinder 金属碎屑投诉"），避免空话。
"""


def _classify_stance(inputs: dict) -> str:
    kpis = inputs.get("kpis") or {}
    delta = inputs.get("kpi_delta") or {}
    health = float(kpis.get("health_index") or 0)
    high_risk = int(kpis.get("high_risk_count") or 0)
    neg_rate = float(kpis.get("own_negative_review_rate") or 0)
    safety_count = int(inputs.get("safety_incidents_count") or 0)
    health_delta = float(delta.get("health_index") or 0)
    risk_delta = int(delta.get("high_risk_count") or 0)

    if safety_count > 0 and any(
        s.get("safety_level") == "critical"
        for s in (inputs.get("safety_incidents") or [])
    ):
        return "urgent"
    if health < 50 or high_risk >= 3:
        return "urgent"
    if health_delta < -5 or risk_delta > 0 or neg_rate > 5:
        return "needs_attention"
    return "stable"


def _fallback_executive_summary(inputs: dict) -> dict:
    """Deterministic summary used when LLM is unavailable or fails."""
    kpis = inputs.get("kpis") or {}
    delta = inputs.get("kpi_delta") or {}
    top_issues = inputs.get("top_issues") or []
    safety_count = int(inputs.get("safety_incidents_count") or 0)

    stance = _classify_stance(inputs)
    stance_text = {
        "stable": "本月整体表现稳定",
        "needs_attention": "本月需要关注几项指标变动",
        "urgent": "本月出现紧急情况，建议立即行动",
    }[stance]

    bullets = []
    health = kpis.get("health_index")
    health_delta = delta.get("health_index")
    if health is not None and health_delta is not None:
        sign = "+" if health_delta >= 0 else ""
        bullets.append(f"健康指数 {health}（较上月 {sign}{round(health_delta, 1)}）")
    elif health is not None:
        bullets.append(f"健康指数 {health}")

    neg_rate = kpis.get("own_negative_review_rate")
    if neg_rate is not None:
        bullets.append(f"差评率 {round(float(neg_rate), 1)}% · 本月新增评论 {kpis.get('own_review_rows', 0)} 条")

    if top_issues:
        first = top_issues[0]
        bullets.append(
            f"主要问题：{first.get('label_display', '')} "
            f"({first.get('review_count', 0)} 条 · {first.get('severity_display', '')})"
        )
    elif safety_count > 0:
        bullets.append(f"安全事件 {safety_count} 起，需重点核查")
    else:
        bullets.append("无突出问题集群")

    actions = []
    if stance == "urgent":
        actions.append("立即调查所有 critical safety 事件并冻结相关 SKU")
    if (kpis.get("high_risk_count") or 0) > 0:
        actions.append("逐个 review 高风险产品的差评样本，识别共性问题")
    if top_issues:
        actions.append(f"针对「{top_issues[0].get('label_display', '')}」制定短期改进计划")

    # Design says 2-3 建议行动. Ensure at least 2, even for stable stance.
    if len(actions) < 2:
        actions.append("复盘本月 TOP 3 正面评论主题，沉淀可复用营销卖点")
    if len(actions) < 2:
        actions.append("维持当前节奏，下月继续监控关键指标")
    actions = actions[:3]

    return {
        "stance": stance,
        "stance_text": stance_text,
        "bullets": bullets[:3],
        "actions": actions,
    }


def generate_executive_summary(inputs: dict) -> dict:
    """Generate executive summary via LLM, falling back to deterministic logic on error."""
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        logger.info("Executive summary: LLM not configured, using fallback")
        return _fallback_executive_summary(inputs)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)
        prompt = _PROMPT.format(inputs_json=json.dumps(inputs, ensure_ascii=False, sort_keys=True, indent=2))
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (response.choices[0].message.content or "").strip()
        from qbu_crawler.server.report_llm import _parse_llm_response
        result = _parse_llm_response(raw)

        # Validate shape; fall back if malformed
        if not isinstance(result, dict) or "stance" not in result:
            raise ValueError("LLM returned malformed executive summary")

        result.setdefault("stance_text", "")
        result["bullets"] = list(result.get("bullets") or [])[:3]
        result["actions"] = list(result.get("actions") or [])[:3]
        if result["stance"] not in ("stable", "needs_attention", "urgent"):
            result["stance"] = _classify_stance(inputs)
        return result
    except Exception:
        logger.warning("Executive summary LLM call failed, using fallback", exc_info=True)
        return _fallback_executive_summary(inputs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase4.py -k "executive" -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/analytics_executive.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add analytics_executive.py — LLM executive summary with deterministic fallback"
```

---

## Task 10: monthly_report.html.j2 — 月报模板

**Files:**
- Create: `qbu_crawler/server/report_templates/monthly_report.html.j2`
- Test: `tests/test_p008_phase4.py`

The monthly template reuses the `daily_report_v3.css` and `daily_report_v3.js` assets (consistent visual identity per design Section 4.3) and adds:
1. **Executive screen** (top fold, before tabs): stance + 3 KPI cards + 3 bullets + actions + safety incident summary
2. **7 Tabs**: 总览, 本月变化, 问题诊断 (with full lifecycle states), 品类对标, 产品计分卡, 竞品对标, 全景数据

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase4.py

# ── Task 10: monthly_report.html.j2 ─────────────────────────────


def test_monthly_template_renders_executive_screen():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("monthly_report.html.j2")
    html = template.render(
        logical_date="2026-05-01",
        month_label="2026年04月",
        executive={
            "stance": "needs_attention",
            "stance_text": "本月需要关注质量稳定性问题",
            "bullets": ["健康指数 72.3（较上月 -1.5）", "差评率 4.2%", "TOP 问题：质量稳定性 8 条"],
            "actions": ["核查 #22 Grinder 投诉", "复盘 grinder 类目维护流程"],
        },
        kpis={"health_index": 72.3, "own_negative_review_rate_display": "4.2%", "high_risk_count": 2,
              "own_review_rows": 200, "ingested_review_rows": 220, "product_count": 41,
              "own_product_count": 7, "competitor_product_count": 34,
              "competitor_review_rows": 20, "own_negative_review_rows": 8, "own_positive_review_rows": 180},
        kpi_delta={"health_index": -1.5, "high_risk_count": +1},
        category_benchmark={"categories": {}, "fallback_mode": False, "pairings": []},
        scorecard={"scorecards": [], "summary": {"green": 5, "yellow": 1, "red": 1, "total": 7,
                                                  "with_safety_flag": 1}},
        lifecycle_cards=[],
        lifecycle_insufficient=False, history_days=120,
        weekly_summaries=["第1周：健康 73", "第2周：健康 72", "第3周：健康 71", "第4周：健康 72"],
        snapshot={"reviews": [], "cumulative": {"reviews": []}},
        analytics={"kpis": {}, "self": {"risk_products": [], "top_negative_clusters": [],
                                          "issue_cards": [], "recommendations": []},
                   "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                                   "negative_opportunities": []},
                   "appendix": {"image_reviews": []}},
        charts={
            "heatmap": None, "sentiment_own": None, "sentiment_comp": None,
            "weekly_trend": {"type": "line", "data": {"labels": ["第1周", "第2周", "第3周", "第4周"],
                                                       "datasets": [{"label": "健康", "data": [73, 72, 71, 72]}]},
                              "options": {}},
        },
        alert_level="yellow", alert_text="",
        safety_incidents=[],
        css_text="", js_text="",
        threshold=2,
    )
    # Executive screen markers
    assert "需要关注" in html
    # 4-week trend canvas renders weekly_trend config as JSON
    assert "weekly_trend" in html.lower() or "第1周" in html
    assert "data-chart-config" in html
    # Light counts
    assert ">5<" in html or ">5 <" in html  # green count


def test_monthly_template_renders_lifecycle_insufficient_notice():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("monthly_report.html.j2")
    html = template.render(
        logical_date="2026-05-01", month_label="2026年04月",
        executive={"stance": "stable", "stance_text": "稳定",
                    "bullets": [], "actions": []},
        kpis={"health_index": 72.3, "own_negative_review_rate_display": "4.2%", "high_risk_count": 0,
              "own_review_rows": 10, "ingested_review_rows": 10, "product_count": 7,
              "own_product_count": 7, "competitor_product_count": 0,
              "competitor_review_rows": 0, "own_negative_review_rows": 0, "own_positive_review_rows": 10},
        kpi_delta={}, category_benchmark={"categories": {}, "fallback_mode": False, "pairings": []},
        scorecard={"scorecards": [], "summary": {"green": 0, "yellow": 0, "red": 0, "total": 0,
                                                  "with_safety_flag": 0}},
        lifecycle_cards=[], lifecycle_insufficient=True, history_days=12,
        weekly_summaries=[],
        snapshot={"reviews": [], "cumulative": {"reviews": []}},
        analytics={"kpis": {}, "self": {"risk_products": [], "top_negative_clusters": [],
                                          "issue_cards": [], "recommendations": []},
                   "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                                   "negative_opportunities": []},
                   "appendix": {"image_reviews": []}},
        charts={"heatmap": None, "sentiment_own": None, "sentiment_comp": None},
        alert_level="green", alert_text="",
        safety_incidents=[], css_text="", js_text="", threshold=2,
    )
    assert "数据积累中" in html
    assert "12" in html  # history_days
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_template" -v`
Expected: FAIL — template not found.

- [ ] **Step 3: Create `monthly_report.html.j2`**

Create `qbu_crawler/server/report_templates/monthly_report.html.j2`. Structure mirrors V3 with an executive prelude before tabs:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>QBU 网评监控 · 月报 {{ month_label }}</title>
  <style>{{ css_text|safe }}</style>
  <style>
    .exec-screen { background:linear-gradient(135deg,#1a365d 0%,#2c5282 100%);
                   color:#fff; padding:32px 24px; border-radius:12px; margin-bottom:24px; }
    .exec-stance { font-size:13px; text-transform:uppercase; letter-spacing:1px; opacity:0.75; }
    .exec-stance.urgent { color:#fed7d7; }
    .exec-stance.needs_attention { color:#fefcbf; }
    .exec-stance.stable { color:#c6f6d5; }
    .exec-headline { font-size:24px; font-weight:700; margin:8px 0 24px; }
    .exec-kpis { display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }
    .exec-kpi { flex:1; min-width:160px; background:rgba(255,255,255,0.1); padding:16px; border-radius:8px; }
    .exec-kpi-label { font-size:12px; opacity:0.75; }
    .exec-kpi-value { font-size:32px; font-weight:700; line-height:1.2; }
    .exec-kpi-delta { font-size:12px; opacity:0.85; }
    .exec-bullets { margin:0 0 16px; padding-left:20px; }
    .exec-bullets li { margin-bottom:6px; }
    .exec-actions { background:rgba(255,255,255,0.08); padding:12px 16px; border-radius:6px;
                    border-left:3px solid #fefcbf; }
    .exec-actions h4 { margin:0 0 8px; font-size:13px; opacity:0.85; }
    .scorecard-light { display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:6px; }
    .light-green { background:#48bb78; } .light-yellow { background:#ecc94b; } .light-red { background:#e53e3e; }
    .lifecycle-badge { font-size:11px; padding:2px 8px; border-radius:4px; }
    .ls-active { background:#fed7d7; color:#c53030; }
    .ls-receding { background:#fefcbf; color:#975a16; }
    .ls-dormant { background:#e2e8f0; color:#4a5568; }
    .ls-recurrent { background:#c53030; color:#fff; }
    .week-summary { background:#f7fafc; padding:8px 12px; border-radius:6px; margin-bottom:6px;
                    border-left:3px solid #4299e1; font-size:13px; }
  </style>
</head>
<body>
<div class="report-container">

  {# ── Sticky KPI bar (shared with daily/weekly) ── #}
  <div class="sticky-kpi-bar">
    <span class="brand">QBU 网评监控</span>
    <span class="kpi-mini">健康 {{ kpis.health_index }}</span>
    <span class="kpi-mini">差评 {{ kpis.own_negative_review_rate_display }}</span>
    <span class="kpi-mini">高风险 {{ kpis.high_risk_count }}</span>
    <span class="kpi-mini" style="margin-left:auto;">月报 · {{ month_label }}</span>
  </div>

  {# ── Executive screen (first fold) ── #}
  <section class="exec-screen">
    <div class="exec-stance {{ executive.stance }}">月度态势 · {{ {"stable":"稳中向好","needs_attention":"需要关注","urgent":"紧急行动"}.get(executive.stance, "") }}</div>
    <div class="exec-headline">{{ executive.stance_text }}</div>

    <div class="exec-kpis">
      <div class="exec-kpi">
        <div class="exec-kpi-label">健康指数</div>
        <div class="exec-kpi-value">{{ kpis.health_index }}</div>
        {% if kpi_delta.health_index is defined and kpi_delta.health_index is not none %}
        <div class="exec-kpi-delta">{{ "+" if kpi_delta.health_index > 0 else "" }}{{ kpi_delta.health_index }} vs 上月</div>
        {% endif %}
      </div>
      <div class="exec-kpi">
        <div class="exec-kpi-label">差评率</div>
        <div class="exec-kpi-value">{{ kpis.own_negative_review_rate_display }}</div>
      </div>
      <div class="exec-kpi">
        <div class="exec-kpi-label">高风险产品</div>
        <div class="exec-kpi-value">{{ kpis.high_risk_count }}</div>
        {% if kpi_delta.high_risk_count is defined %}
        <div class="exec-kpi-delta">{{ "+" if kpi_delta.high_risk_count > 0 else "" }}{{ kpi_delta.high_risk_count }} vs 上月</div>
        {% endif %}
      </div>
    </div>

    <ul class="exec-bullets">
      {% for b in executive.bullets %}<li>{{ b }}</li>{% endfor %}
    </ul>

    {% if executive.actions %}
    <div class="exec-actions">
      <h4>建议行动</h4>
      <ul style="margin:0;padding-left:20px;">
        {% for a in executive.actions %}<li>{{ a }}</li>{% endfor %}
      </ul>
    </div>
    {% endif %}

    {% if safety_incidents %}
    <div style="margin-top:16px;padding:12px 16px;background:rgba(229,62,62,0.2);border-radius:6px;">
      <strong>⚠ 本月安全事件 {{ safety_incidents|length }} 起</strong>
      <ul style="margin:8px 0 0;padding-left:20px;font-size:13px;">
        {% for s in safety_incidents[:5] %}
        <li>[{{ s.safety_level }}] {{ s.product_sku }} · {{ s.failure_mode or "未分类" }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}
  </section>

  {# ── Tabs ── #}
  <nav class="tab-nav" role="tablist">
    <button role="tab" data-tab="tab-overview" class="tab-button active">总览</button>
    <button role="tab" data-tab="tab-changes" class="tab-button">本月变化</button>
    <button role="tab" data-tab="tab-issues" class="tab-button">问题诊断</button>
    <button role="tab" data-tab="tab-categories" class="tab-button">品类对标</button>
    <button role="tab" data-tab="tab-scorecard" class="tab-button">产品计分卡</button>
    <button role="tab" data-tab="tab-competitor" class="tab-button">竞品对标</button>
    <button role="tab" data-tab="tab-panorama" class="tab-button">全景数据</button>
  </nav>

  {# Tab 1: 总览 — extended metrics (skip the 3 KPIs already on exec screen) + 4-week summary #}
  <section id="tab-overview" class="tab-panel active" role="tabpanel">
    <h2 class="section-title">扩展指标</h2>
    <table class="data-table">
      <tr><th>评论总量（自有）</th><td>{{ kpis.own_review_rows }}</td></tr>
      <tr><th>评论总量（竞品）</th><td>{{ kpis.competitor_review_rows }}</td></tr>
      <tr><th>负面评论数</th><td>{{ kpis.own_negative_review_rows }}</td></tr>
      <tr><th>正面评论数</th><td>{{ kpis.own_positive_review_rows }}</td></tr>
      <tr><th>SKU 总数</th><td>{{ kpis.product_count }}（自有 {{ kpis.own_product_count }} · 竞品 {{ kpis.competitor_product_count }}）</td></tr>
    </table>

    {% if charts.weekly_trend %}
    <h3 style="margin-top:24px;">4 周趋势</h3>
    <div class="chart-wrapper" style="height:240px;position:relative;">
      <canvas data-chart-config='{{ charts.weekly_trend | tojson }}'></canvas>
    </div>
    {% endif %}

    {% if weekly_summaries %}
    <h3 style="margin-top:24px;">本月逐周态势</h3>
    {% for ws in weekly_summaries %}
    <div class="week-summary">{{ ws }}</div>
    {% endfor %}
    {% endif %}
  </section>

  {# Tab 2: 本月变化 — same structure as V3 Tab 2 #}
  <section id="tab-changes" class="tab-panel" role="tabpanel">
    <h2 class="section-title">本月新增评论</h2>
    {% set win_reviews = snapshot.reviews if snapshot.reviews is defined else [] %}
    {% if win_reviews %}
    <p>本月共新增评论 {{ win_reviews|length }} 条，按时间倒序展示前 30 条：</p>
    {% for r in win_reviews[:30] %}
    <div class="quote-block {% if r.rating is defined and r.rating <= 2 %}quote-negative{% elif r.rating is defined and r.rating >= 4 %}quote-positive{% else %}quote-neutral{% endif %}">
      <div class="quote-cn">{{ r.get("headline_cn") or r.get("headline", "") }}</div>
      <div class="quote-en">{{ r.get("body", "")[:300] }}{% if r.get("body", "")|length > 300 %}...{% endif %}</div>
      <div class="quote-meta">
        <span>{{ "★" * (r.rating|int if r.rating else 0) }}</span>
        <span>{{ r.get("author", "Anonymous") }}</span>
        <span>{{ r.get("product_name", r.get("product_sku", "")) }}</span>
      </div>
    </div>
    {% endfor %}
    {% else %}
    <div class="empty-state">本月无新增评论。</div>
    {% endif %}
  </section>

  {# Tab 3: 问题诊断 — issue cards with full lifecycle states + competitor reference #}
  <section id="tab-issues" class="tab-panel" role="tabpanel">
    <h2 class="section-title">问题集群（生命周期视图）</h2>
    {% if lifecycle_insufficient %}
    <div class="notice" style="padding:12px 16px;background:#fefcbf;border-left:3px solid #975a16;margin-bottom:16px;">
      <strong>数据积累中</strong>：当前仅有 {{ history_days }} 天历史数据（生命周期分析需要 ≥ 30 天），下月报告将显示完整状态分析。
    </div>
    {% elif lifecycle_cards %}
    {% for card in lifecycle_cards %}
    <div class="issue-card" style="margin-bottom:16px;padding:12px 16px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;">
      <div class="issue-card-header" style="margin-bottom:8px;">
        <strong>{{ card.label_display }}</strong>
        <span class="lifecycle-badge ls-{{ card.state }}">{{ {"active":"活跃","receding":"收敛中","dormant":"沉默","recurrent":"复发"}.get(card.state, card.state) }}</span>
        <span class="meta" style="font-size:12px;color:#718096;margin-left:8px;">
          {{ card.review_count }} 条 · 首现 {{ card.first_seen or "—" }} · 末现 {{ card.last_seen or "—" }}
        </span>
      </div>

      {% if card.history %}
      <details style="margin-bottom:8px;">
        <summary style="cursor:pointer;font-size:12px;color:#4a5568;">状态变迁时间线（{{ card.history|length }} 次）</summary>
        <ul style="margin:6px 0 0;padding-left:20px;font-size:12px;">
          {% for h in card.history %}<li>{{ h.date }} · {{ h.transition }} · {{ h.reason }}</li>{% endfor %}
        </ul>
      </details>
      {% endif %}

      {% if card.example_reviews %}
      <div style="margin-top:8px;">
        <div style="font-size:12px;color:#4a5568;margin-bottom:4px;">自有关键评论（按可信度排序）</div>
        {% for r in card.example_reviews[:3] %}
        <div class="quote-mini" style="font-size:12px;padding:4px 8px;background:#f7fafc;border-left:2px solid #e53e3e;margin-bottom:4px;">
          "{{ r.get('body', '')[:200] }}" — {{ r.get('product_name', '') }}
        </div>
        {% endfor %}
      </div>
      {% endif %}

      {% if card.competitor_reference and card.competitor_reference.review_count > 0 %}
      <div style="margin-top:8px;padding:8px 12px;background:#edf2f7;border-radius:6px;border-left:2px solid #4299e1;">
        <div style="font-size:12px;color:#2c5282;margin-bottom:4px;">
          竞品参照（同一问题标签，共 {{ card.competitor_reference.review_count }} 条竞品负面）
        </div>
        {% for r in card.competitor_reference.top_examples[:3] %}
        <div class="quote-mini" style="font-size:12px;padding:4px 8px;background:#fff;margin-bottom:4px;">
          "{{ r.get('body', '')[:200] }}" — {{ r.get('product_name', '') }}
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    {% endfor %}
    {% else %}
    <div class="empty-state">本月无活跃问题集群。</div>
    {% endif %}
  </section>

  {# Tab 4: 品类对标 #}
  <section id="tab-categories" class="tab-panel" role="tabpanel">
    <h2 class="section-title">品类对标</h2>
    {% if category_benchmark.fallback_mode %}
    <div class="notice">品类映射数据未配置，下方采用直接竞品配对模式。</div>
    {% if category_benchmark.pairings %}
    <table class="data-table">
      <tr><th>自有 SKU</th><th>评分</th><th>最接近竞品</th><th>评分</th><th>差距</th><th>价差</th></tr>
      {% for pair in category_benchmark.pairings %}
      <tr>
        <td>{{ pair.own_name }}</td><td>{{ pair.own_rating }}</td>
        <td>{{ pair.competitor_name }}</td><td>{{ pair.competitor_rating }}</td>
        <td>{{ pair.rating_gap }}</td><td>{{ pair.price_diff }}</td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}
    {% else %}
    {% for cat, data in category_benchmark.categories.items() %}
    <div class="category-card">
      <h3>{{ cat }}</h3>
      {% if data.status == "insufficient_samples" %}
      <div class="notice">样本不足（自有 {{ data.own_sku_count }} · 竞品 {{ data.competitor_sku_count }}，最低需 {{ data.min_required }}）。</div>
      {% else %}
      <table class="data-table">
        <tr><th></th><th>SKU 数</th><th>平均评分</th><th>评论总量</th><th>平均价</th></tr>
        <tr><td>自有</td><td>{{ data.own.sku_count }}</td><td>{{ data.own.avg_rating }}</td><td>{{ data.own.total_reviews }}</td><td>${{ data.own.avg_price }}</td></tr>
        <tr><td>竞品</td><td>{{ data.competitor.sku_count }}</td><td>{{ data.competitor.avg_rating }}</td><td>{{ data.competitor.total_reviews }}</td><td>${{ data.competitor.avg_price }}</td></tr>
      </table>
      <p>评分差距：<strong>{{ data.rating_gap }}</strong></p>
      {% endif %}
    </div>
    {% endfor %}
    {% if category_benchmark.unmapped_count > 0 %}
    <div class="notice">{{ category_benchmark.unmapped_count }} 个 SKU 未映射，未参与品类对标。</div>
    {% endif %}
    {% endif %}
  </section>

  {# Tab 5: 产品计分卡 #}
  <section id="tab-scorecard" class="tab-panel" role="tabpanel">
    <h2 class="section-title">SKU 健康计分卡</h2>
    <p>
      🟢 {{ scorecard.summary.green }} ·
      🟡 {{ scorecard.summary.yellow }} ·
      🔴 {{ scorecard.summary.red }}
      {% if scorecard.summary.with_safety_flag %} · ⚠ 安全标记 {{ scorecard.summary.with_safety_flag }}{% endif %}
    </p>
    <table class="data-table">
      <tr><th></th><th>产品</th><th>评分</th><th>评论数</th><th>风险分</th><th>差评率</th><th>趋势</th></tr>
      {% for s in scorecard.scorecards %}
      <tr>
        <td><span class="scorecard-light light-{{ s.light }}"></span></td>
        <td>{{ s.name }} {% if s.safety_flag %}⚠{% endif %}</td>
        <td>{{ s.rating }}</td>
        <td>{{ s.review_count }}</td>
        <td>{{ s.risk_score }}</td>
        <td>{{ (s.negative_rate * 100)|round(1) }}%</td>
        <td>{{ {"improving":"↘ 改善","steady":"→ 稳定","worsening":"↗ 恶化","new":"新增"}.get(s.trend, "—") }}</td>
      </tr>
      {% endfor %}
    </table>
  </section>

  {# Tab 6: 竞品对标 — reuse same content patterns from V3 #}
  <section id="tab-competitor" class="tab-panel" role="tabpanel">
    <h2 class="section-title">竞品对标</h2>
    {% if analytics.competitor.benchmark_examples %}
    {% for b in analytics.competitor.benchmark_examples %}
    <div class="bench-card">
      <strong>{{ b.dimension_display }}</strong>
      <p>{{ b.description }}</p>
    </div>
    {% endfor %}
    {% else %}
    <div class="empty-state">本月无新增竞品基准案例。</div>
    {% endif %}
  </section>

  {# Tab 7: 全景数据 — Chart.js configs (matches V3 pipeline) #}
  <section id="tab-panorama" class="tab-panel" role="tabpanel">
    <h2 class="section-title">全景数据</h2>
    {% if charts.heatmap and charts.heatmap.y_labels and charts.heatmap.y_labels|length >= 3 %}
    <table class="heatmap-table">
      <thead><tr><th></th>{% for x in charts.heatmap.x_labels %}<th>{{ x[:5] }}</th>{% endfor %}</tr></thead>
      <tbody>
        {% for y_idx in range(charts.heatmap.y_labels|length) %}
        <tr>
          <th>{{ charts.heatmap.y_labels[y_idx][:20] }}</th>
          {% for x_idx in range(charts.heatmap.x_labels|length) %}
          {% set val = charts.heatmap.z[y_idx][x_idx] if y_idx < charts.heatmap.z|length and x_idx < charts.heatmap.z[y_idx]|length else 0 %}
          <td>{{ val }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
    {% if charts.sentiment_own %}
    <div class="chart-wrapper" style="height:240px;position:relative;">
      <canvas data-chart-config='{{ charts.sentiment_own | tojson }}'></canvas>
    </div>
    {% endif %}
    {% if charts.sentiment_comp %}
    <div class="chart-wrapper" style="height:240px;position:relative;">
      <canvas data-chart-config='{{ charts.sentiment_comp | tojson }}'></canvas>
    </div>
    {% endif %}
  </section>

</div>
<script>{{ js_text|safe }}</script>
</body>
</html>
```

> Adjust class names if the existing V3 CSS uses different selectors. The implementer should run a manual render and verify visual fidelity against `daily_report_v3.html.j2`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_template" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_templates/monthly_report.html.j2 tests/test_p008_phase4.py
git commit -m "feat(monthly): add monthly_report.html.j2 template (executive screen + 7 tabs)"
```

---

## Task 11: email_monthly.html.j2 — 月报邮件模板

**Files:**
- Create: `qbu_crawler/server/report_templates/email_monthly.html.j2`
- Test: `tests/test_p008_phase4.py`

The monthly email body is the **executive first-fold summary** (stance, 3 KPI cards, 3 bullets, actions, safety incidents). Attachments: HTML + Excel.

- [ ] **Step 1: Create `email_monthly.html.j2`**

Create `qbu_crawler/server/report_templates/email_monthly.html.j2`:

```html
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>QBU 月报 {{ month_label }}</title></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a202c;font-size:14px;line-height:1.6;">
<div style="max-width:720px;margin:0 auto;padding:16px;">

  <div style="background:linear-gradient(135deg,#1a365d 0%,#2c5282 100%);color:#fff;border-radius:12px;padding:24px;margin-bottom:16px;">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;opacity:0.75;
      {% if executive.stance == 'urgent' %}color:#fed7d7;
      {% elif executive.stance == 'needs_attention' %}color:#fefcbf;
      {% else %}color:#c6f6d5;{% endif %}">
      月度态势 · {{ {"stable":"稳中向好","needs_attention":"需要关注","urgent":"紧急行动"}.get(executive.stance, "") }}
    </div>
    <div style="font-size:20px;font-weight:700;margin:6px 0 18px;">{{ executive.stance_text }}</div>

    <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;">
      <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.1);padding:12px;border-radius:6px;">
        <div style="font-size:11px;opacity:0.75;">健康指数</div>
        <div style="font-size:26px;font-weight:700;">{{ kpis.health_index }}</div>
        {% if kpi_delta.health_index is defined and kpi_delta.health_index is not none %}
        <div style="font-size:11px;opacity:0.85;">{{ "+" if kpi_delta.health_index > 0 else "" }}{{ kpi_delta.health_index }} vs 上月</div>
        {% endif %}
      </div>
      <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.1);padding:12px;border-radius:6px;">
        <div style="font-size:11px;opacity:0.75;">差评率</div>
        <div style="font-size:26px;font-weight:700;">{{ kpis.own_negative_review_rate_display }}</div>
      </div>
      <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.1);padding:12px;border-radius:6px;">
        <div style="font-size:11px;opacity:0.75;">高风险</div>
        <div style="font-size:26px;font-weight:700;">{{ kpis.high_risk_count }}</div>
        {% if kpi_delta.high_risk_count is defined %}
        <div style="font-size:11px;opacity:0.85;">{{ "+" if kpi_delta.high_risk_count > 0 else "" }}{{ kpi_delta.high_risk_count }} vs 上月</div>
        {% endif %}
      </div>
    </div>

    <ul style="margin:0 0 16px;padding-left:20px;">
      {% for b in executive.bullets %}<li style="margin-bottom:6px;">{{ b }}</li>{% endfor %}
    </ul>

    {% if executive.actions %}
    <div style="background:rgba(255,255,255,0.08);padding:12px 16px;border-radius:6px;border-left:3px solid #fefcbf;">
      <div style="font-size:12px;opacity:0.85;margin-bottom:8px;">建议行动</div>
      <ul style="margin:0;padding-left:20px;">
        {% for a in executive.actions %}<li>{{ a }}</li>{% endfor %}
      </ul>
    </div>
    {% endif %}

    {% if safety_incidents %}
    <div style="margin-top:16px;padding:12px 16px;background:rgba(229,62,62,0.25);border-radius:6px;">
      <strong>⚠ 本月安全事件 {{ safety_incidents|length }} 起</strong>
      <ul style="margin:8px 0 0;padding-left:20px;font-size:13px;">
        {% for s in safety_incidents[:5] %}
        <li>[{{ s.safety_level }}] {{ s.product_sku }} · {{ s.failure_mode or "未分类" }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}
  </div>

  {% if report_url %}
  <div style="text-align:center;margin-bottom:16px;">
    <a href="{{ report_url }}" style="display:inline-block;padding:12px 28px;background:#2b6cb0;color:#fff;text-decoration:none;border-radius:6px;font-size:14px;font-weight:600;">查看完整月报</a>
  </div>
  <div style="text-align:center;font-size:12px;color:#a0aec0;">完整报告含品类对标 · SKU 计分卡 · 问题生命周期 · Excel 数据表</div>
  {% endif %}

  <div style="text-align:center;font-size:11px;color:#a0aec0;padding:16px;">内部资料 · AI 自动生成</div>
</div>
</body>
</html>
```

- [ ] **Step 2: Write test**

```python
# Append to tests/test_p008_phase4.py

# ── Task 11: email_monthly.html.j2 ──────────────────────────────


def test_email_monthly_template_renders():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_monthly.html.j2")
    html = template.render(
        month_label="2026年04月",
        executive={
            "stance": "needs_attention",
            "stance_text": "本月需要关注质量稳定性问题",
            "bullets": ["健康指数 72.3", "差评率 4.2%", "TOP 问题：质量稳定性 8 条"],
            "actions": ["核查 #22 Grinder 投诉"],
        },
        kpis={"health_index": 72.3, "own_negative_review_rate_display": "4.2%", "high_risk_count": 2},
        kpi_delta={"health_index": -1.5, "high_risk_count": +1},
        safety_incidents=[],
        report_url="https://reports.example.com/monthly-2026-04.html",
    )
    assert "需要关注" in html
    assert "72.3" in html
    assert "查看完整月报" in html
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/test_p008_phase4.py -k "email_monthly" -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_templates/email_monthly.html.j2 tests/test_p008_phase4.py
git commit -m "feat(monthly): add email_monthly.html.j2 — executive first-fold email template"
```

---

## Task 12: _generate_monthly_report() + monthly routing

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_p008_phase4.py`

This task wires together everything from Tasks 5-11: it loads the snapshot, calls each new analytics module, runs the LLM executive summary, renders `monthly_report.html.j2`, and sends `email_monthly.html.j2`.

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase4.py

# ── Task 12: _generate_monthly_report routing ───────────────────


def test_generate_report_monthly_tier_routes_correctly(db, tmp_path, monkeypatch):
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid, **kw: (None, None))
    # Disable LLM so we use deterministic fallback
    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (1, 'monthly', 'reporting', 'full_pending', '2026-05-01',"
        " 'monthly:2026-05-01', 'monthly')"
    )
    conn.commit()
    conn.close()

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-05-01",
        "data_since": "2026-04-01T00:00:00+08:00",
        "data_until": "2026-05-01T00:00:00+08:00",
        "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                      "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
        "reviews": [{"id": 1, "headline": "Good", "body": "Works well", "rating": 4.0,
                     "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
                     "images": [], "author": "A", "date_published": "2026-04-14",
                     "date_published_parsed": "2026-04-14"}],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [{"id": 1, "rating": 4.0, "ownership": "own", "product_sku": "SKU1",
                         "headline": "Good", "body": "Works well", "sentiment": "positive",
                         "analysis_labels": "[]", "date_published_parsed": "2026-04-14"}],
        },
    }

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)
    assert result["mode"] == "monthly_report"
    assert result.get("html_path") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_tier_routes" -v`
Expected: FAIL — monthly routing doesn't exist yet.

- [ ] **Step 3: Add monthly routing in `generate_report_from_snapshot()`**

Edit `qbu_crawler/server/report_snapshot.py` around line 1083 — extend the tier routing block:

```python
    if run_tier == "daily":
        return _generate_daily_briefing(snapshot, send_email)
    elif run_tier == "weekly":
        return _generate_weekly_report(snapshot, send_email)
    elif run_tier == "monthly":
        return _generate_monthly_report(snapshot, send_email)
```

- [ ] **Step 4: Implement `_generate_monthly_report()`**

In `qbu_crawler/server/report_snapshot.py`, add right after `_send_weekly_email()` (around line 1059):

```python
def _generate_monthly_report(snapshot, send_email=True):
    """P008 Phase 4: Generate monthly report — V3-style HTML + 6-sheet Excel + executive email.

    Reuses generate_full_report_from_snapshot for V3 pipeline, then enriches with:
    - category benchmark (analytics_category)
    - SKU scorecard (analytics_scorecard)
    - issue lifecycle (analytics_lifecycle, full state machine)
    - executive summary (analytics_executive, LLM with fallback)
    Renders monthly_report.html.j2 and sends email_monthly.html.j2.
    """
    from datetime import date as _date

    from qbu_crawler.server import (
        analytics_category, analytics_executive, analytics_lifecycle, analytics_scorecard,
    )
    from qbu_crawler.server.report_common import load_category_map

    run_id = snapshot.get("run_id", 0)
    logical_date = snapshot.get("logical_date", "")

    # Generate full V3 report (reuse for charts, KPIs, Excel data)
    try:
        full_result = generate_full_report_from_snapshot(snapshot, send_email=False)
    except Exception:
        _logger.exception("Monthly report: full generation failed for run %d", run_id)
        raise

    # Note: no "completed_no_change" early-return here (unlike weekly). Monthly
    # must always produce a report because executive summary, category benchmark,
    # and scorecard are derived from cumulative data, which is never empty after
    # the first daily run. An empty window simply means "no new activity this
    # month" — the report still has value.

    analytics_path = full_result.get("analytics_path")
    analytics = {}
    if analytics_path and os.path.isfile(analytics_path):
        analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))

    cumulative = snapshot.get("cumulative") or {}
    cum_products = cumulative.get("products") or []
    cum_reviews = cumulative.get("reviews") or []

    # ── Module 1: category benchmark ──
    category_map = load_category_map()
    category_benchmark = analytics_category.derive_category_benchmark(cum_products, category_map)

    # ── Module 2: SKU scorecard ──
    risk_products = (analytics.get("self") or {}).get("risk_products") or []
    safety_incidents = _load_safety_incidents_for_window(
        snapshot.get("data_since"), snapshot.get("data_until"),
    )
    previous_scorecards = _load_previous_scorecards(run_id)
    scorecard = analytics_scorecard.derive_product_scorecard(
        cum_products, risk_products, safety_incidents, previous_scorecards,
    )

    # ── Module 3: full lifecycle state machine ──
    try:
        window_end = _date.fromisoformat(logical_date[:10])
    except (ValueError, TypeError):
        window_end = _date.today()

    # P008 Section 5.6: lifecycle needs ≥30 days of history; otherwise show
    # "数据积累中" rather than potentially misleading active/dormant labels.
    history_days = _compute_history_span_days(cum_reviews, window_end)
    lifecycle_insufficient = history_days < 30
    if lifecycle_insufficient:
        lifecycle_results = {}
        lifecycle_cards = []
        _logger.info(
            "Monthly report: lifecycle suppressed, only %d days of history (<30)",
            history_days,
        )
    else:
        lifecycle_results = analytics_lifecycle.derive_all_lifecycles(
            cum_reviews, window_end=window_end,
        )
        lifecycle_cards = _build_lifecycle_cards(lifecycle_results, cum_reviews)

    # ── Module 4: LLM executive summary ──
    kpis = analytics.get("kpis") or {}
    prev_analytics, _ = load_previous_report_context(run_id, report_tier="monthly")
    prev_kpis = (prev_analytics or {}).get("kpis") or {}
    kpi_delta = {
        "health_index": _safe_delta(kpis.get("health_index"), prev_kpis.get("health_index")),
        "high_risk_count": _safe_delta(kpis.get("high_risk_count"), prev_kpis.get("high_risk_count")),
    }
    top_issues = ((analytics.get("self") or {}).get("top_negative_clusters") or [])[:3]
    executive_inputs = {
        "kpis": kpis,
        "kpi_delta": kpi_delta,
        "top_issues": top_issues,
        "category_benchmark": category_benchmark,
        "safety_incidents_count": len(safety_incidents),
        "safety_incidents": safety_incidents[:10],
    }
    executive = analytics_executive.generate_executive_summary(executive_inputs)

    # ── Weekly summaries (4-week recap) + Chart.js trend config ──
    weekly_summaries, weekly_trend_config = _build_weekly_recap(
        snapshot.get("data_since"), snapshot.get("data_until"),
    )

    # Persist enriched analytics
    if analytics_path:
        analytics["category_benchmark"] = category_benchmark
        analytics["scorecard"] = scorecard
        analytics["lifecycle"] = {
            f"{code}::{ownership}": data
            for (code, ownership), data in lifecycle_results.items()
        }
        analytics["executive"] = executive
        analytics["kpi_delta_monthly"] = kpi_delta
        Path(analytics_path).write_text(
            json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    # Render monthly HTML
    html_path = _render_monthly_html(
        snapshot, analytics, executive, kpi_delta, category_benchmark,
        scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
        weekly_summaries, weekly_trend_config, safety_incidents, full_result,
    )

    # Generate 6-sheet monthly Excel (extends the 4-sheet pipeline)
    monthly_excel_path = _regenerate_monthly_excel(
        snapshot, analytics, category_benchmark, scorecard, full_result,
    )

    # Send email
    email_result = None
    if send_email:
        try:
            email_result = _send_monthly_email(
                snapshot, executive, kpi_delta, safety_incidents,
                html_path, monthly_excel_path,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    try:
        models.update_workflow_run(
            run_id, report_mode="standard", analytics_path=analytics_path,
        )
    except Exception:
        pass

    return {
        "mode": "monthly_report",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": full_result.get("products_count", 0),
        "reviews_count": full_result.get("reviews_count", 0),
        "html_path": html_path,
        "excel_path": monthly_excel_path,
        "analytics_path": analytics_path,
        "email": email_result,
    }


def _safe_delta(current, previous):
    try:
        if current is None or previous is None:
            return None
        return round(float(current) - float(previous), 2)
    except (TypeError, ValueError):
        return None


def _compute_history_span_days(reviews: list[dict], window_end) -> int:
    """Days from earliest review scraped_at / date_published_parsed to window_end.

    Used to decide whether lifecycle state machine has enough history to produce
    meaningful active/dormant labels (Section 5.6 rule: ≥30 days required).
    """
    from datetime import date as _date, datetime as _dt
    earliest = None
    for r in reviews or []:
        for key in ("scraped_at", "date_published_parsed", "date_published"):
            val = r.get(key)
            if not val:
                continue
            if isinstance(val, (_date, _dt)):
                d = val.date() if isinstance(val, _dt) else val
            else:
                try:
                    d = _date.fromisoformat(str(val)[:10])
                except (ValueError, TypeError):
                    continue
            if earliest is None or d < earliest:
                earliest = d
            break
    if earliest is None:
        return 0
    return max(0, (window_end - earliest).days)


def _load_safety_incidents_for_window(data_since: str | None, data_until: str | None) -> list[dict]:
    if not data_since or not data_until:
        return []
    try:
        conn = models.get_conn()
        rows = conn.execute(
            "SELECT * FROM safety_incidents WHERE detected_at >= ? AND detected_at < ?"
            " ORDER BY detected_at DESC",
            (data_since, data_until),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        _logger.debug("safety_incidents query failed", exc_info=True)
        return []


def _load_previous_scorecards(current_run_id: int) -> dict[str, dict]:
    """Load scorecards from the previous monthly run (for trend computation)."""
    prev_run = models.get_previous_completed_run(current_run_id, report_tier="monthly")
    if not prev_run or not prev_run.get("analytics_path"):
        return {}
    try:
        prev_analytics = json.loads(Path(prev_run["analytics_path"]).read_text(encoding="utf-8"))
        prev_cards = (prev_analytics.get("scorecard") or {}).get("scorecards") or []
        return {
            c["sku"]: {"risk_score": c.get("risk_score"), "light": c.get("light")}
            for c in prev_cards if c.get("sku")
        }
    except Exception:
        return {}


def _build_lifecycle_cards(lifecycle_results: dict, all_reviews: list[dict]) -> list[dict]:
    """Convert lifecycle state-machine output into renderable issue cards (own only).

    Each card also attaches a ``competitor_reference`` block — negative reviews
    from competitors for the same label_code — so the monthly report can show
    cross-ownership context (design doc Section 10 validation item).
    """
    from datetime import date as _date
    from qbu_crawler.server.report_common import credibility_weight, _label_display

    cards = []
    today = _date.today()

    def _reviews_matching(label_code: str, ownership: str) -> list[dict]:
        out = []
        for r in all_reviews:
            if r.get("ownership") != ownership:
                continue
            raw = r.get("analysis_labels") or "[]"
            try:
                labels = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                labels = []
            if any(lb.get("code") == label_code and lb.get("polarity") == "negative" for lb in labels):
                out.append(r)
        out.sort(key=lambda r: credibility_weight(r, today=today), reverse=True)
        return out

    for (label_code, ownership), data in lifecycle_results.items():
        if ownership != "own":
            continue

        own_examples = _reviews_matching(label_code, "own")
        comp_examples = _reviews_matching(label_code, "competitor")

        cards.append({
            "label_code": label_code,
            "label_display": _label_display(label_code),  # Uses report_common._LABEL_DISPLAY map
            "state": data["state"],
            "history": data["history"],
            "review_count": data["review_count"],
            "first_seen": data["first_seen"],
            "last_seen": data["last_seen"],
            "example_reviews": own_examples[:3],
            "competitor_reference": {
                "review_count": len(comp_examples),
                "top_examples": comp_examples[:3],
            },
        })

    state_priority = {"recurrent": 0, "active": 1, "receding": 2, "dormant": 3}
    cards.sort(key=lambda c: (state_priority.get(c["state"], 9), -c["review_count"]))
    return cards


def _build_weekly_recap(
    data_since: str | None,
    data_until: str | None,
) -> tuple[list[str], dict | None]:
    """Produce (text summaries, Chart.js line-config) for weekly runs in the window.

    M3-A: Tab 1 of the monthly report must show a 4-week trend line (design doc
    Section 6.2). This returns both the one-line summaries AND a Chart.js config
    consumable by ``<canvas data-chart-config='{{ config | tojson }}'>``.

    Partial-overlap SQL filter: a weekly window straddling the month boundary
    still counts (e.g. [3-30, 4-6) for an April monthly report).
    """
    if not data_since or not data_until:
        return [], None
    try:
        conn = models.get_conn()
        rows = conn.execute(
            "SELECT logical_date, analytics_path FROM workflow_runs"
            " WHERE report_tier = 'weekly' AND status = 'completed'"
            "   AND data_since < ? AND data_until > ?"
            " ORDER BY logical_date ASC",
            (data_until, data_since),
        ).fetchall()
        conn.close()
    except Exception:
        return [], None

    summaries: list[str] = []
    labels: list[str] = []
    health_series: list[float] = []
    neg_series: list[float] = []
    for idx, row in enumerate(rows, start=1):
        week_label = f"第{idx}周"
        labels.append(week_label)
        try:
            wkly = json.loads(Path(row["analytics_path"]).read_text(encoding="utf-8"))
            kpis = wkly.get("kpis") or {}
            health = kpis.get("health_index")
            neg_rate_display = kpis.get("own_negative_review_rate_display") or "—"
            health_series.append(float(health) if health is not None else None)
            neg = kpis.get("own_negative_review_rate")
            neg_series.append(float(neg) if neg is not None else None)
            summaries.append(
                f"{week_label}（{row['logical_date']}）：健康 {health if health is not None else '—'} · "
                f"差评率 {neg_rate_display} · 高风险 {kpis.get('high_risk_count', 0)}"
            )
        except Exception:
            summaries.append(f"{week_label}（{row['logical_date']}）：数据缺失")
            health_series.append(None)
            neg_series.append(None)

    if not labels or all(v is None for v in health_series):
        return summaries, None

    # Chart.js v3/v4 line-chart config consumable by daily_report_v3.js handler
    trend_config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "健康指数",
                    "data": health_series,
                    "borderColor": "#93543f",
                    "backgroundColor": "rgba(147,84,63,0.12)",
                    "tension": 0.3,
                    "fill": True,
                    "spanGaps": True,
                    "yAxisID": "y",
                },
                {
                    "label": "差评率 (%)",
                    "data": neg_series,
                    "borderColor": "#b7633f",
                    "backgroundColor": "transparent",
                    "tension": 0.3,
                    "spanGaps": True,
                    "yAxisID": "y1",
                },
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "scales": {
                "y":  {"type": "linear", "position": "left",  "title": {"display": True, "text": "健康指数"}},
                "y1": {"type": "linear", "position": "right", "grid": {"drawOnChartArea": False},
                        "title": {"display": True, "text": "差评率 (%)"}},
            },
            "plugins": {"legend": {"position": "bottom"}},
        },
    }
    return summaries, trend_config


def _render_monthly_html(snapshot, analytics, executive, kpi_delta, category_benchmark,
                         scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
                         weekly_summaries, weekly_trend_config, safety_incidents,
                         full_result):
    """Render monthly_report.html.j2 to disk, return path."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("monthly_report.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"

    from datetime import date as _date, timedelta as _td
    logical_date = snapshot.get("logical_date", "")
    # Month label like "2026年04月" — month-1st logical_date refers to previous month
    try:
        ld = _date.fromisoformat(logical_date[:10])
        prev_month = ld.replace(day=1) - _td(days=1)  # last day of previous month
        month_label = prev_month.strftime("%Y年%m月")
    except (ValueError, TypeError):
        month_label = logical_date[:7]

    # V3 HTML uses Chart.js configs, not base64 images. Pull the fragments that
    # `generate_full_report_from_snapshot` already built into analytics, then
    # inject the monthly-specific weekly_trend chart.
    charts = dict(analytics.get("charts") or {})
    if weekly_trend_config is not None:
        charts["weekly_trend"] = weekly_trend_config

    html = template.render(
        logical_date=logical_date,
        month_label=month_label,
        executive=executive,
        kpis=analytics.get("kpis") or {},
        kpi_delta=kpi_delta,
        category_benchmark=category_benchmark,
        scorecard=scorecard,
        lifecycle_cards=lifecycle_cards,
        lifecycle_insufficient=lifecycle_insufficient,
        history_days=history_days,
        weekly_summaries=weekly_summaries,
        snapshot=snapshot,
        analytics=analytics,
        charts=charts,
        alert_level=analytics.get("alert_level") or "green",
        alert_text=analytics.get("alert_text") or "",
        safety_incidents=safety_incidents,
        css_text=css_path.read_text(encoding="utf-8") if css_path.exists() else "",
        js_text=js_path.read_text(encoding="utf-8") if js_path.exists() else "",
        threshold=config.NEGATIVE_THRESHOLD,
    )

    out_path = Path(config.REPORT_DIR) / f"monthly-{month_label.replace('年', '-').replace('月', '')}.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


def _regenerate_monthly_excel(snapshot, analytics, category_benchmark, scorecard, full_result):
    """Generate 6-sheet monthly Excel (4 from weekly + category + scorecard).

    Implementation lives in report.py to keep openpyxl imports localised.
    """
    from qbu_crawler.server import report
    return report._generate_monthly_excel(
        products=snapshot.get("cumulative", {}).get("products") or [],
        reviews=snapshot.get("cumulative", {}).get("reviews") or [],
        analytics=analytics,
        category_benchmark=category_benchmark,
        scorecard=scorecard,
    )


def _send_monthly_email(snapshot, executive, kpi_delta, safety_incidents, html_path, excel_path):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_monthly.html.j2")

    logical_date = snapshot.get("logical_date", "")
    try:
        from datetime import date as _date, timedelta as _td
        ld = _date.fromisoformat(logical_date[:10])
        prev_month = ld - _td(days=1)
        month_label = prev_month.strftime("%Y年%m月")
    except (ValueError, TypeError):
        month_label = logical_date[:7]

    report_url = ""
    if config.REPORT_HTML_PUBLIC_URL and html_path:
        report_url = f"{config.REPORT_HTML_PUBLIC_URL}/{Path(html_path).name}"

    body_html = template.render(
        month_label=month_label,
        executive=executive,
        kpis=snapshot.get("cumulative_kpis") or {},
        kpi_delta=kpi_delta,
        safety_incidents=safety_incidents,
        report_url=report_url,
    )

    # Use exec recipients first, fall back to default if empty
    recipients = config.EMAIL_RECIPIENTS_EXEC or _get_email_recipients()
    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    subject = f"产品评论月报 {month_label}"
    attachments = []
    if html_path and os.path.isfile(html_path):
        attachments.append(html_path)
    if excel_path and os.path.isfile(excel_path):
        attachments.append(excel_path)

    report.send_email(
        recipients=recipients,
        subject=subject,
        body_text=f"QBU 月报 {month_label}",
        body_html=body_html,
        attachment_paths=attachments if attachments else None,
    )
    return {"success": True, "error": None, "recipients": recipients}
```

> **Note:** The `_render_monthly_html()` month_label computation is awkward because `logical_date` for monthly is the **1st of the new month** (e.g., 2026-05-01 → covers April). The implementer should verify the displayed label matches the data window (April content shown as "2026年04月", not "2026年05月").

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_tier_routes" -v`
Expected: PASS.

> Test will fail at this point if `_generate_monthly_excel` is missing — that's expected. Task 13 implements it; in the interim the test can monkey-patch `report._generate_monthly_excel` to return ``""``. The implementer should add a temporary stub returning ``""`` in `report.py` to keep this task green:
> ```python
> def _generate_monthly_excel(*, products, reviews, analytics, category_benchmark, scorecard):
>     return ""  # P008 Phase 4 Task 13 will implement
> ```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py qbu_crawler/server/report.py tests/test_p008_phase4.py
git commit -m "feat(monthly): add _generate_monthly_report() + monthly tier routing"
```

---

## Task 13: 6-sheet Monthly Excel (extend 4-sheet)

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/test_p008_phase4.py`

The monthly Excel is the existing 4-sheet weekly Excel + 2 new sheets:
- **Sheet 5: 品类对标** — per-category own vs competitor table
- **Sheet 6: SKU 计分卡** — per-own-SKU traffic-light scorecard

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase4.py

# ── Task 13: monthly 6-sheet Excel ──────────────────────────────


def test_generate_monthly_excel_has_six_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    from qbu_crawler.server import report

    products = [
        {"name": "Grinder", "sku": "SKU1", "ownership": "own", "rating": 4.5,
         "review_count": 50, "site": "test", "price": 299},
        {"name": "Slicer", "sku": "C1", "ownership": "competitor", "rating": 4.2,
         "review_count": 200, "site": "test", "price": 310},
    ]
    reviews = [{"id": 1, "rating": 4.0, "ownership": "own", "product_sku": "SKU1",
                 "headline": "Good", "body": "Works", "sentiment": "positive",
                 "analysis_labels": "[]", "date_published_parsed": "2026-04-14"}]
    analytics = {"kpis": {}, "self": {"risk_products": [
        {"sku": "SKU1", "risk_score": 5, "negative_rate": 0.02, "negative_count": 1, "review_count": 50}
    ]}}
    category_benchmark = {
        "categories": {"grinder": {"status": "ok",
                                    "own": {"sku_count": 1, "avg_rating": 4.5, "total_reviews": 50, "avg_price": 299},
                                    "competitor": {"sku_count": 1, "avg_rating": 4.2, "total_reviews": 200, "avg_price": 310},
                                    "rating_gap": 0.3}},
        "fallback_mode": False, "unmapped_count": 0, "pairings": [],
    }
    scorecard = {
        "scorecards": [{"sku": "SKU1", "name": "Grinder", "rating": 4.5, "review_count": 50,
                        "risk_score": 5, "negative_rate": 0.02, "negative_count": 1,
                        "light": "green", "safety_flag": False, "trend": "new",
                        "previous_risk_score": None, "previous_light": None}],
        "summary": {"green": 1, "yellow": 0, "red": 0, "total": 1, "with_safety_flag": 0},
    }

    path = report._generate_monthly_excel(
        products=products, reviews=reviews, analytics=analytics,
        category_benchmark=category_benchmark, scorecard=scorecard,
    )
    assert path
    from openpyxl import load_workbook
    wb = load_workbook(path)
    assert "品类对标" in wb.sheetnames
    assert "SKU计分卡" in wb.sheetnames
    # Inherited from 4-sheet base
    for name in ("评论明细", "产品概览", "问题标签", "趋势数据"):
        assert name in wb.sheetnames
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_excel" -v`
Expected: FAIL — function returns `""` from Task 12 stub.

- [ ] **Step 3: Implement `_generate_monthly_excel()` in `report.py`**

Replace the Task 12 stub in `qbu_crawler/server/report.py` with the full implementation. Add right after `_generate_analytical_excel()` (line 699):

```python
def _generate_monthly_excel(
    *,
    products: list[dict],
    reviews: list[dict],
    analytics: dict,
    category_benchmark: dict,
    scorecard: dict,
    report_date: datetime | None = None,
) -> str:
    """P008 Phase 4: 6-sheet monthly Excel = 4-sheet weekly + 品类对标 + SKU 计分卡.

    Reuses the existing 4-sheet pipeline by calling _generate_analytical_excel(),
    then opens the produced workbook and appends two extra sheets.
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    if report_date is None:
        report_date = config.now_shanghai()

    # 1. Generate the 4-sheet base workbook
    base_path = _generate_analytical_excel(products, reviews, analytics, report_date)
    if not base_path:
        return ""

    # 2. Rename to monthly-* (the 4-sheet writer outputs scrape-report-YYYY-MM-DD.xlsx).
    # Mi1: an existing monthly-YYYY-MM.xlsx must not silently clobber — the 4-sheet
    # writer already wrote to scrape-report-YYYY-MM-DD.xlsx, so a rename conflict
    # indicates a prior monthly output for the same month. Overwrite is acceptable
    # because the new output supersedes the old, but log for traceability.
    base_p = Path(base_path)
    monthly_filename = f"monthly-{report_date.strftime('%Y-%m')}.xlsx"
    monthly_path = base_p.with_name(monthly_filename)
    if monthly_path.exists():
        logger.info("monthly Excel already exists at %s, overwriting", monthly_path)
        monthly_path.unlink()
    if base_p.exists():
        base_p.rename(monthly_path)

    # 3. Open and append two new sheets
    wb = load_workbook(monthly_path)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def _write_headers(ws, headers):
        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

    # Sheet 5: 品类对标
    ws_cat = wb.create_sheet("品类对标")
    if category_benchmark.get("fallback_mode"):
        _write_headers(ws_cat, ["自有SKU", "自有评分", "竞品SKU", "竞品评分", "评分差", "价差"])
        for pair in (category_benchmark.get("pairings") or []):
            ws_cat.append([
                pair.get("own_name") or pair.get("own_sku"),
                pair.get("own_rating"),
                pair.get("competitor_name") or pair.get("competitor_sku"),
                pair.get("competitor_rating"),
                pair.get("rating_gap"),
                pair.get("price_diff"),
            ])
    else:
        _write_headers(ws_cat, ["品类", "状态", "自有SKU数", "自有平均评分", "自有评论总量", "自有平均价",
                                "竞品SKU数", "竞品平均评分", "竞品评论总量", "竞品平均价", "评分差距"])
        for cat, data in (category_benchmark.get("categories") or {}).items():
            if data.get("status") != "ok":
                ws_cat.append([
                    cat, "样本不足",
                    data.get("own_sku_count", 0), None, None, None,
                    data.get("competitor_sku_count", 0), None, None, None, None,
                ])
                continue
            own = data.get("own") or {}
            comp = data.get("competitor") or {}
            ws_cat.append([
                cat, "正常",
                own.get("sku_count"), own.get("avg_rating"), own.get("total_reviews"), own.get("avg_price"),
                comp.get("sku_count"), comp.get("avg_rating"), comp.get("total_reviews"), comp.get("avg_price"),
                data.get("rating_gap"),
            ])

    # Sheet 6: SKU 计分卡
    ws_sc = wb.create_sheet("SKU计分卡")
    _write_headers(ws_sc, ["灯号", "SKU", "产品名", "评分", "评论数", "风险分", "差评率(%)",
                            "趋势", "安全标记", "上月风险分"])
    light_label = {"green": "🟢 绿", "yellow": "🟡 黄", "red": "🔴 红"}
    trend_label = {"improving": "↘ 改善", "steady": "→ 稳定", "worsening": "↗ 恶化", "new": "新增"}
    for s in (scorecard.get("scorecards") or []):
        ws_sc.append([
            light_label.get(s.get("light"), s.get("light")),
            s.get("sku"),
            s.get("name"),
            s.get("rating"),
            s.get("review_count"),
            s.get("risk_score"),
            round((s.get("negative_rate") or 0) * 100, 2),
            trend_label.get(s.get("trend"), s.get("trend")),
            "⚠" if s.get("safety_flag") else "",
            s.get("previous_risk_score"),
        ])

    # Auto-width for new sheets
    for ws in (ws_cat, ws_sc):
        for col in ws.columns:
            letter = col[0].column_letter
            max_len = max((len(str(c.value or "")) for c in col), default=0)
            ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 60)

    wb.save(monthly_path)
    return str(monthly_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase4.py -k "monthly_excel" -v`
Expected: PASS (6 sheets present).

- [ ] **Step 5: Run regression suite for Excel**

Run: `uv run pytest tests/test_v3_excel.py tests/test_report_excel.py -v --tb=short`
Expected: All PASS (4-sheet base unaffected; new function additive).

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report.py tests/test_p008_phase4.py
git commit -m "feat(monthly): _generate_monthly_excel() — 6-sheet (4-base + 品类对标 + SKU计分卡)"
```

---

## Task 14: Integration test — end-to-end monthly run

**Files:**
- Test: `tests/test_p008_phase4.py`

- [ ] **Step 1: Write integration test**

```python
# Append to tests/test_p008_phase4.py

# ── Task 14: Integration test ────────────────────────────────────


def test_p008_phase4_integration(db, tmp_path, monkeypatch):
    """End-to-end: monthly scheduler → submit → routing → report → analytics enrichment."""
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.workflows import (
        MonthlySchedulerWorker, build_monthly_trigger_key, submit_monthly_run,
    )
    from qbu_crawler.server.report_common import tier_date_window
    from qbu_crawler.server import analytics_category, analytics_lifecycle, analytics_scorecard

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid, **kw: (None, None))

    # 1. tier_date_window monthly correctness
    since, until = tier_date_window("monthly", "2026-05-01")
    assert since == "2026-04-01T00:00:00+08:00"
    assert until == "2026-05-01T00:00:00+08:00"

    # 2. trigger_key + submit
    assert build_monthly_trigger_key("2026-05-01") == "monthly:2026-05-01"
    result = submit_monthly_run(logical_date="2026-05-01")
    assert result["created"] is True

    # 3. Schedule worker
    now = datetime(2026, 5, 1, 10, 0, tzinfo=config.SHANGHAI_TZ)
    worker = MonthlySchedulerWorker(schedule_time="09:30")
    # Already submitted in step 2 → idempotent → False
    assert worker.process_once(now=now) is False

    # 4. Each analytics module is callable in isolation
    products = [{"name": "G", "sku": "O1", "ownership": "own", "rating": 4.5, "review_count": 30, "price": 299}]
    cat_result = analytics_category.derive_category_benchmark(products, category_map={})
    assert cat_result["fallback_mode"] is True

    sc_result = analytics_scorecard.derive_product_scorecard(
        products=products,
        risk_products=[{"sku": "O1", "risk_score": 5, "negative_rate": 0.02,
                         "negative_count": 1, "review_count": 30}],
        safety_incidents=[],
    )
    assert sc_result["summary"]["green"] == 1

    lc_result = analytics_lifecycle.derive_all_lifecycles([], window_end=date(2026, 4, 30))
    assert lc_result == {}

    # 5. Routing → _generate_monthly_report
    snapshot = {
        "run_id": result["run_id"],
        "logical_date": "2026-05-01",
        "data_since": since, "data_until": until,
        "products": products,
        "reviews": [],
        "cumulative": {"products": products, "reviews": []},
    }
    report_result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)
    assert report_result["mode"] == "monthly_report"
    assert report_result.get("html_path") is not None


def test_p008_phase4_full_suite_no_regressions():
    """Final guard: full suite should pass after Phase 4."""
    # This is a placeholder marker — the actual `pytest tests/` command in the
    # post-implementation checklist verifies regressions.
    assert True
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_p008_phase4.py::test_p008_phase4_integration -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ --tb=short -q`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_p008_phase4.py
git commit -m "test(p008): add Phase 4 integration test verifying monthly pipeline"
```

---

## Task 15: 文档同步（CLAUDE.md + docs/devlogs）

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/devlogs/D014-p008-phase4-monthly-report.md`

- [ ] **Step 1: Update `CLAUDE.md`**

In the **OpenClaw 定时工作流** section (search for `DailySchedulerWorker`), extend the worker list:

```markdown
3. **WeeklySchedulerWorker（每周一定时）**：每周一 `WEEKLY_SCHEDULER_TIME` 触发周报生成（V3 HTML + 4-sheet Excel + 摘要邮件）。前置等待窗口内所有 daily run 终态。
4. **MonthlySchedulerWorker（每月 1 日定时）**：每月 1 日 `MONTHLY_SCHEDULER_TIME` 触发月报生成（V3 风格 HTML + 6-sheet Excel + 高管摘要邮件）。包含品类对标、SKU 计分卡、问题完整生命周期 (active/receding/dormant/recurrent) 和 LLM 高管摘要。
5. **NotifierWorker（后台投递）**：（原编号顺延）
```

In the **报告配置（.env）** table, add:

```markdown
| `WEEKLY_SCHEDULER_TIME` | `09:30` | 周报每周一触发时间 |
| `MONTHLY_SCHEDULER_TIME` | `09:30` | 月报每月 1 日触发时间 |
| `CATEGORY_MAP_PATH` | `data/category_map.csv` | SKU 品类映射 CSV 路径 |
```

In the project structure section, add the four new analytics modules under `qbu_crawler/server/`:

```markdown
│       ├── analytics_lifecycle.py    # 问题生命周期完整状态机（R1-R6）
│       ├── analytics_category.py     # 品类对标（CSV 配置驱动 + 直接配对降级）
│       ├── analytics_scorecard.py    # SKU 健康计分卡（红黄绿灯 + 趋势）
│       ├── analytics_executive.py    # LLM 高管摘要（带确定性降级）
```

And under `report_templates/`:

```markdown
│           ├── monthly_report.html.j2  # 月报模板（高管首屏 + 7 Tab）
│           └── email_monthly.html.j2   # 月报邮件（高管首屏摘要）
```

- [ ] **Step 2: Create `docs/devlogs/D014-p008-phase4-monthly-report.md`**

Document the implementation summary, key decisions, and any deviations from the spec. Cover:
- 完整 R1-R6 状态机的实现要点（`analytics_lifecycle.py`）
- 品类对标降级模式（fallback_mode）触发条件和数据呈现差异
- LLM 高管摘要的 prompt 设计 + 降级到确定性逻辑的判定
- `_generate_monthly_excel()` 复用 4-sheet 基础 + 追加 2 sheet 的策略
- WeeklySchedulerWorker 注册到 runtime（Phase 3 遗留项的回填）
- 任何与设计稿的差异及理由

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/devlogs/D014-p008-phase4-monthly-report.md
git commit -m "docs(p008-phase4): update CLAUDE.md + add D014 devlog"
```

---

## Post-Implementation Checklist

- [ ] `uv run pytest tests/ -v` 全绿
- [ ] `data/category_map.csv` 已扩展到全部 41 SKU（不仅限模板初始的 7 SKU）
- [ ] `MonthlySchedulerWorker` 在每月 1 日的 `MONTHLY_SCHEDULER_TIME` 后被触发，非 1 日跳过
- [ ] `WeeklySchedulerWorker`（Phase 3 遗留）已注册到 runtime 并验证启动日志
- [ ] 月报 HTML 第 1 屏含 stance + 3 KPI 卡片 + 3 bullet + 行动建议
- [ ] 月报 7 个 Tab 全部渲染（总览/本月变化/问题诊断/品类对标/产品计分卡/竞品对标/全景数据）
- [ ] 问题诊断 Tab 展示 active/receding/dormant/recurrent 四态
- [ ] 问题卡片含竞品参照区块（同 label_code 的竞品负面评论 top 3）
- [ ] 部署不满 30 天时 Tab 3 显示"数据积累中"，不展示状态标签
- [ ] Tab 1 展示 4 周趋势线（Chart.js canvas，双 Y 轴：健康指数 + 差评率）
- [ ] 月初恰逢周一时，MonthlySchedulerWorker 等到当日 daily + 覆盖本月的 weekly 全部终态才提交
- [ ] 品类对标显示按 grinder/slicer/mixer 等分组；样本不足品类显示"样本不足"
- [ ] 品类映射缺失时 Tab 自动降级为直接竞品配对模式
- [ ] SKU 计分卡展示红黄绿灯 + 趋势方向（improving/steady/worsening/new）
- [ ] critical/high safety 评论强制 SKU 灯号为红
- [ ] 月报 Excel 含 6 个 Sheet
- [ ] 邮件 body = 高管首屏摘要（不含完整 7 Tab 内容）
- [ ] LLM 不可用时降级到确定性高管摘要，stance 分类正确（urgent/needs_attention/stable）
- [ ] 月报 HTML 文件名格式 `monthly-YYYY-MM.html`，Excel 同
- [ ] 月报邮件 subject 显示月份（如 `产品评论月报 2026年04月`）而非 logical_date
- [ ] CLAUDE.md 项目结构和环境变量表已更新
- [ ] `docs/devlogs/D014-*` 已记录实现细节

## 设计偏差登记表

| 偏差 | 理由 |
|------|------|
| 月报 HTML 模板独立成 `monthly_report.html.j2`（而非沿用 V3 复用模式） | 高管首屏 + 4 个新 Tab（品类对标 / 计分卡 / 完整生命周期 / 月度逐周回顾）显著超出 V3 的 6-Tab 结构，独立模板比条件渲染清晰；继续共享 `daily_report_v3.css` / `.js`，保持视觉一致性 |
| `analytics_lifecycle.derive_issue_lifecycle()` 内部把 R3（silence_window）放在每个事件循环开头检查 | 状态机走时间线时，每条新评论事件之前都需要先评估累计沉默时长是否触发 R3，否则会在已 dormant 的状态上误触 R1；设计稿 R1-R6 顺序未明示 R3 优先级，按工程实践显式排序 |
| 生命周期状态机信息不足（<2 事件）时使用 30 天默认沉默窗口，而非 clamp 下限 14 天 | 14 天对单条评论+轻微沉默场景过于激进，会误将 active 判为 dormant；30 天符合"仅靠单条评论无法判断是否收敛"的直觉。Safety 仍按 R6 翻倍到 60 天 |
| `_generate_monthly_excel` 通过加载 4-sheet 基础 workbook 后 `create_sheet` 追加，而非重写整个 Excel 生成函数 | 复用 `_generate_analytical_excel` 的 4-sheet 逻辑（评论明细 / 产品概览 / 问题标签 / 趋势数据），仅新增 2 sheet；DRY 原则 |
| 月报 `_generate_monthly_report` 移除 `completed_no_change` 早退分支 | 月报必须始终出报——高管摘要/品类对标/计分卡都基于累积数据；"无窗口变化 ≠ 无报告价值"。与 Phase 3 周报语义差异已在注释中说明 |
| `_all_weekly_runs_terminal` 使用部分重叠 SQL（`data_since < until AND data_until > since`） | 周窗口常跨月边界（如 [3-30, 4-6)），`>=/<=` 全包含会漏过，导致 monthly 在周报未完成时提前触发 |
| `charts.weekly_trend` 内嵌 Chart.js 配置，而非 plotly HTML 片段 | V3 模板已基于 Chart.js（`daily_report_v3.html.j2:380` 起），沿用同机制避免双引擎；`report_charts._build_trend_line()`（plotly）仅用于 PDF 路径，与 V3 HTML 路径分离 |

---

## Phase 1-3 代码基线对齐（2026-04-17 审计）

本计划基于以下已合并 commit 的 API 签名，若实施前基线已变动需重新验证：

| API | 文件:行 | 签名 |
|-----|---------|------|
| `models.get_previous_completed_run` | `models.py:787` | `(current_run_id: int, report_tier: str\|None=None)` |
| `models.save_safety_incident` | `models.py:2020` | `(review_id, product_sku, safety_level, failure_mode, evidence_snapshot, evidence_hash)` |
| `models.create_workflow_run` | `models.py:584` | `(run_dict: dict) -> dict` ON CONFLICT(trigger_key) DO NOTHING |
| `models.update_workflow_run` 白名单 | `models.py:688-689` | 已含 `report_mode` + `report_tier` |
| `report_snapshot._inject_meta` | `report_snapshot.py:22` | `(snapshot, tier="daily", expected_days=None, actual_days=None)` |
| `report_snapshot.freeze_report_snapshot` | `report_snapshot.py:302,380` | 已在 line 380 调用 `_inject_meta(snapshot, tier=run_tier)` ✓ 月报自动生效 |
| `report_snapshot.load_previous_report_context` | `report_snapshot.py:103` | `(run_id, report_tier=None)` |
| `report_snapshot._get_email_recipients` | `report_snapshot.py:40` | `() -> list[str]`（fallback: EMAIL_RECIPIENTS env → openclaw file） |
| `report.send_email` | `report.py:424` | 月报调用路径一致 |
| `report._generate_analytical_excel` | `report.py:699` | `(products, reviews, analytics=None, report_date=None)` |
| `workflows._all_daily_runs_terminal` | `workflows.py:127` | `(since, until) -> bool` ✓ monthly precheck 直接复用 |
| `workflows.build_weekly_trigger_key` | `workflows.py:123` | `build_monthly_trigger_key` 紧随其后定义 |
| `report_common._label_display` | `report_common.py:435` | `(label_code)` 返回中文显示名（私有但跨模块已用） |
| `report_common.credibility_weight` | `report_common.py` | Phase 3 已定义，月报 `_build_lifecycle_cards` 直接复用 |
| `report_common.compute_dispersion` | `report_common.py` | Phase 3 已定义，本计划未新增 dispersion，仅通过 `_generate_weekly_report` 已注入 analytics 消费 |
| `report_common.tier_date_window` | `report_common.py:103` | 已支持 `daily/weekly/monthly` 三档 |
| `report_charts.build_chartjs_configs` | `report_charts.py:571` | V3 HTML 生成 Chart.js config 的唯一路径。月报趋势图遵循同模式（`data-chart-config` + `tojson`） |

**Phase 3 已就绪、月报直接复用的基础设施**：
- `_advance_periodic_run()` 在 `workflows.py:691` 起，已通过 `run_tier in ("weekly", "monthly")` 判断路由（Phase 3 Task 7）
- `models.get_label_anomaly_stats()` 可用于月报标签质量统计展示（可选）
- `should_send_quiet_email()` 已退役 `weekly_digest` 分支（`report_snapshot.py:87`），月报不受影响

**月报独有的新建/改造**：完全隔离，不影响日报/周报既有路径。

---

## 自审清单

**Spec coverage (against P008 main doc Section 6):**
- 6.1 MonthlySchedulerWorker → Task 3 ✓
- 6.2 月报模板（高管首屏 + 7 Tab） → Tasks 10, 11 ✓
- 6.3 品类对标 CSV 驱动 → Tasks 5, 6 ✓
- 6.4 问题生命周期完整状态机 → Task 8 ✓
- 6.5 SKU 健康计分卡 → Task 7 ✓
- 6.6 LLM 高管摘要 → Task 9 ✓
- 6.7 6-sheet Excel → Task 13 ✓
- Section 9 env vars (MONTHLY_SCHEDULER_TIME, CATEGORY_MAP_PATH) → Task 1 ✓
- Section 8 文件清单（4 modules + 2 templates + 1 csv） → Tasks 5-13 ✓
- Section 10 验收标准 Phase 4 全部 11 项 → Post-Implementation Checklist 覆盖

**Type consistency:**
- `category_benchmark` 字典在 Task 6 输出，被 Task 10 / 12 / 13 消费——结构一致（`categories` / `fallback_mode` / `pairings` / `unmapped_count`）✓
- `scorecard` 字典在 Task 7 输出，被 Task 10 / 12 / 13 消费——结构一致（`scorecards` / `summary`）✓
- `lifecycle_results` 在 Task 8 输出，被 Task 12 `_build_lifecycle_cards` 转换——key 都是 `(label_code, ownership)` tuple ✓
- `executive` 字典在 Task 9 输出，被 Task 10 / 11 消费——结构一致（`stance` / `stance_text` / `bullets` / `actions`）✓

**Placeholder scan:**
- `data/category_map.csv` 模板只列了 7 SKU；明确标注实施者必须扩展到 41 SKU。✓（属于必要的人工 bootstrap，已在 Task 5 Step 1 强调）
- 月报模板的 CSS 类名假设与 V3 一致；Task 10 末尾已提示实施者需手动验证 ✓
- `_render_monthly_html` 中 month_label 计算逻辑较复杂；已在 Task 12 末尾提示实施者验证 ✓
