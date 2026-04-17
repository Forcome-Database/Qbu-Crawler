# 报告模拟脚本 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改业务代码的前提下，通过构造 SQLite 数据 + 时间冻结 + 调用业务模块，生成 Qbu-Crawler 每一种日/周/月报形态的真实产物，并附带逐场景 debug 产物 + 期望/实际对照 + 可视索引，便于分析与改代码后复验。

**Architecture:** 独立子包 `scripts/simulate_reports/` —— env 先设再 import 业务模块（`REPORT_DIR`/`DB_PATH` 是 import-time cache）；`freezegun` 包住每次业务调用；daily 绕过 submitter 直接 `create_workflow_run(status='reporting')` + `WorkflowWorker._advance_run` 推进；weekly/monthly 用业务原生 `submit_*_run`。Notifier 不启线程，由 `notifier_stub` 从 outbox 抽 payload 落盘。

**Tech Stack:** Python 3.10+, sqlite3, freezegun, Jinja2（业务自带）, openpyxl（业务自带）, pytest。

**Spec:** `docs/superpowers/specs/2026-04-17-report-simulation-design.md`

---

## 文件结构

```
scripts/simulate_reports/
├── __init__.py                  # 空
├── __main__.py                  # CLI 子命令分发
├── config.py                    # 路径、时间轴常量、SID 列表
├── env_bootstrap.py             # set_env() + delayed_import()
├── clock.py                     # freeze_time wrapper
├── db.py                        # simulation.db 直连 helpers（不依赖业务 models）
├── body_pool.py                 # 评论文本复用池
├── data_builder.py              # 数据事件注入 ops
├── runner.py                    # call_daily / call_weekly / call_monthly
├── notifier_stub.py             # drain_outbox_for_run
├── checkpoint.py                # 逐日 DB 快照
├── debug_dump.py                # debug/ 9 文件生成
├── manifest.py                  # expected / actual / verdict
├── scenarios.py                 # 场景 SID → 事件 + expected
├── timeline.py                  # 42 天事件编排
├── index_page.py                # 顶层 index.html
├── issues_page.py               # issues.md
├── cmd/
│   ├── __init__.py
│   ├── prepare.py
│   ├── run.py
│   ├── run_one.py
│   ├── rerun.py
│   ├── show.py
│   ├── diff.py
│   ├── verify.py
│   ├── index.py
│   └── reset.py
└── README.md

tests/simulate_reports/           # 纯函数单元测试
├── test_data_builder.py
├── test_manifest.py
├── test_body_pool.py
├── test_scraped_at_redistribute.py
└── test_checkpoint.py
```

**职责分离原则**：
- `config.py`：纯常量
- `db.py`：与业务完全解耦的 sqlite3 adapter（prepare 阶段用）
- `env_bootstrap.py`：唯一允许修改 `os.environ` 的地方，并规定 import 顺序
- `runner.py`：唯一 import 业务 `workflows`/`report_snapshot`/`models` 的地方
- `cmd/*.py`：每个 CLI 子命令一个文件，由 `__main__.py` dispatch

---

## Phase 1 — Foundation

### Task 1: 创建包骨架 + 加 freezegun 依赖

**Files:**
- Create: `scripts/__init__.py`, `scripts/simulate_reports/__init__.py`, `scripts/simulate_reports/__main__.py`, `scripts/simulate_reports/config.py`
- Create: `scripts/simulate_reports/cmd/__init__.py`
- Modify: `pyproject.toml` (加 freezegun 到 dev deps)
- Modify: `.gitignore` (加 `data/sim/`)

- [ ] **Step 1: 创建包目录与空文件**

```bash
mkdir -p scripts/simulate_reports/cmd
touch scripts/__init__.py
touch scripts/simulate_reports/__init__.py
touch scripts/simulate_reports/cmd/__init__.py
```

- [ ] **Step 2: 写 `scripts/simulate_reports/config.py`**

```python
"""Simulation-wide constants: paths, timeline, scenario IDs."""
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Baseline DB (read-only)
BASELINE_DB = Path(r"C:\Users\leo\Desktop\报告\data\products.db")

# Working DB (writable, in project)
SIM_DATA_DIR = PROJECT_ROOT / "data" / "sim"
SIM_DB = SIM_DATA_DIR / "simulation.db"
CHECKPOINT_DIR = SIM_DATA_DIR / "checkpoints"

# Report outputs (on desktop)
REPORT_ROOT = Path(r"C:\Users\leo\Desktop\报告\reports")
SCENARIOS_DIR = REPORT_ROOT / "scenarios"
LEGACY_DIR = REPORT_ROOT / "_legacy"
INDEX_HTML = REPORT_ROOT / "index.html"
ISSUES_MD = REPORT_ROOT / "issues.md"

# Temp REPORT_DIR used by business code during a run
# (all emitted files are then copied to scenario dir)
REPORT_WORK_DIR = SIM_DATA_DIR / "reports_raw"

# Timeline
TIMELINE_START = date(2026, 3, 20)
TIMELINE_END = date(2026, 5, 1)

# Scenario IDs (11 named + variants defined in scenarios.py)
NAMED_SCENARIOS = [
    "S01", "S02", "S03", "S04", "S05",
    "S06", "S07", "S08a", "S08b", "S08c",
    "S09a", "S09b", "S09c", "S10", "S11",
    "W0", "W1", "W2", "W3", "W4", "W5",
    "M1",
]
```

- [ ] **Step 3: 写 `scripts/simulate_reports/__main__.py`（dispatch 骨架）**

```python
"""CLI entrypoint: python -m scripts.simulate_reports <subcommand>"""
import sys

SUBCOMMANDS = {
    "prepare":  "scripts.simulate_reports.cmd.prepare",
    "run":      "scripts.simulate_reports.cmd.run",
    "run-one":  "scripts.simulate_reports.cmd.run_one",
    "rerun-after-fix": "scripts.simulate_reports.cmd.rerun",
    "show":     "scripts.simulate_reports.cmd.show",
    "diff":     "scripts.simulate_reports.cmd.diff",
    "verify":   "scripts.simulate_reports.cmd.verify",
    "issues":   "scripts.simulate_reports.cmd.verify",  # alias
    "index":    "scripts.simulate_reports.cmd.index",
    "reset":    "scripts.simulate_reports.cmd.reset",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m scripts.simulate_reports <subcommand> [args...]")
        print("Subcommands: " + ", ".join(SUBCOMMANDS))
        return 0
    cmd = sys.argv[1]
    if cmd not in SUBCOMMANDS:
        print(f"Unknown subcommand: {cmd}", file=sys.stderr)
        return 2
    import importlib
    module = importlib.import_module(SUBCOMMANDS[cmd])
    return module.run(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main() or 0)
```

- [ ] **Step 4: 更新 `pyproject.toml` 的 dev deps（加 freezegun）**

先读 pyproject.toml 的 `[project.optional-dependencies]` / `dev` 段。根据实际结构追加 `freezegun>=1.4.0`。执行 `uv sync --dev` 确认装上。

- [ ] **Step 5: 更新 `.gitignore`**

追加：
```
# Simulation working data
data/sim/
```

- [ ] **Step 6: 冒烟测试 CLI**

```bash
uv run python -m scripts.simulate_reports --help
```
预期：打印 subcommands 列表。

- [ ] **Step 7: Commit**

```bash
git add scripts/ pyproject.toml uv.lock .gitignore
git commit -m "feat(sim): skeleton + freezegun dep + gitignore"
```

---

### Task 2: env_bootstrap —— 统一 env 设置与业务 import 顺序

**Files:**
- Create: `scripts/simulate_reports/env_bootstrap.py`

- [ ] **Step 1: 写 `env_bootstrap.py`**

```python
"""
统一管理：
1. 在 import 业务模块之前设置所有 env
2. 提供 load_business() 懒加载业务模块并返回所需对象
3. 保证业务模块在整个进程生命周期内只 import 一次
"""
import os
from pathlib import Path
from . import config


_LOADED = None


def set_env():
    """Must be called BEFORE first business import. Idempotent."""
    config.SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_WORK_DIR.mkdir(parents=True, exist_ok=True)
    config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # QBU_DATA_DIR drives DB_PATH resolution in qbu_crawler/config.py
    os.environ["QBU_DATA_DIR"] = str(config.SIM_DATA_DIR)
    os.environ["REPORT_DIR"] = str(config.REPORT_WORK_DIR)

    # Ensure DB file exists at expected path before business imports
    # (qbu_crawler may create its own if missing, which we don't want here)


def load_business():
    """Lazy import business modules and return a namespace handle."""
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    set_env()
    from qbu_crawler import config as qbu_config
    from qbu_crawler import models
    from qbu_crawler.server import workflows, report_snapshot

    # Sanity check: business cached DB_PATH must equal our sim DB
    expected = str(config.SIM_DB)
    if str(qbu_config.DB_PATH) != expected:
        raise RuntimeError(
            f"Business DB_PATH={qbu_config.DB_PATH!r} != simulation DB={expected!r}. "
            "env_bootstrap must run before any qbu_crawler import."
        )

    _LOADED = type("Business", (), {
        "config": qbu_config,
        "models": models,
        "workflows": workflows,
        "report_snapshot": report_snapshot,
    })
    return _LOADED
```

- [ ] **Step 2: 不 commit（下任务一起）**

---

### Task 3: db.py —— 独立 sqlite3 adapter（prepare 阶段用，不依赖业务）

**Files:**
- Create: `scripts/simulate_reports/db.py`

- [ ] **Step 1: 写 `db.py`**

```python
"""Simple sqlite3 adapter for simulation.db.
Used by prepare/data_builder which run BEFORE business modules import.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def open_db(path: Path):
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_counts(conn: sqlite3.Connection) -> dict:
    tables = [
        "products", "product_snapshots", "reviews",
        "review_analysis", "review_issue_labels",
        "safety_incidents", "tasks", "workflow_runs",
        "notification_outbox",
    ]
    out = {}
    for t in tables:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None  # table missing
    return out
```

- [ ] **Step 2: Commit Task 2+3**

```bash
git add scripts/simulate_reports/env_bootstrap.py scripts/simulate_reports/db.py
git commit -m "feat(sim): env bootstrap + sqlite adapter"
```

---

### Task 4: clock.py —— freezegun 封装

**Files:**
- Create: `scripts/simulate_reports/clock.py`

- [ ] **Step 1: 写 `clock.py`**

```python
"""Freezegun wrapper for simulating 'today' during business code calls."""
from contextlib import contextmanager
from datetime import datetime, date, time
from freezegun import freeze_time


@contextmanager
def frozen_today(d: date, at: time = time(9, 30)):
    """Freeze time to `d at`. Use around business report calls."""
    dt = datetime.combine(d, at)
    with freeze_time(dt):
        yield dt
```

- [ ] **Step 2: 冒烟测试**

```bash
uv run python -c "from datetime import date; from scripts.simulate_reports.clock import frozen_today; import datetime as dt
with frozen_today(date(2026,3,20)):
    print(dt.datetime.now())
"
```
预期输出：`2026-03-20 09:30:00`

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/clock.py
git commit -m "feat(sim): clock freezing helper"
```

---

## Phase 2 — Prepare & Data Construction

### Task 5: prepare 命令 —— clone 基线 DB

**Files:**
- Create: `scripts/simulate_reports/cmd/prepare.py`

- [ ] **Step 1: 写 `cmd/prepare.py` 初版（仅 clone）**

```python
"""python -m scripts.simulate_reports prepare
克隆基线 DB + 重分布 scraped_at + 回填 review_issue_labels + 清空 workflow_runs/outbox。
"""
import shutil
import sys
from .. import config
from ..db import open_db


def run(argv):
    if not config.BASELINE_DB.exists():
        print(f"ERROR: baseline DB not found: {config.BASELINE_DB}", file=sys.stderr)
        return 1
    config.SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.BASELINE_DB, config.SIM_DB)
    print(f"Cloned baseline → {config.SIM_DB}")

    with open_db(config.SIM_DB) as conn:
        conn.execute("DELETE FROM workflow_runs")
        conn.execute("DELETE FROM workflow_run_tasks")
        conn.execute("DELETE FROM notification_outbox")
        print("Cleared workflow_runs / workflow_run_tasks / notification_outbox")
    return 0
```

- [ ] **Step 2: 跑一次确认**

```bash
uv run python -m scripts.simulate_reports prepare
```
预期：`data/sim/simulation.db` 出现；无错误。

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/cmd/prepare.py
git commit -m "feat(sim): prepare clones baseline db"
```

---

### Task 6: scraped_at 重分布（TDD）

**Files:**
- Create: `tests/simulate_reports/__init__.py`, `tests/simulate_reports/test_scraped_at_redistribute.py`
- Modify: `scripts/simulate_reports/data_builder.py`（新建）
- Modify: `scripts/simulate_reports/cmd/prepare.py`

- [ ] **Step 1: 写失败的测试 `tests/simulate_reports/test_scraped_at_redistribute.py`**

```python
from datetime import date, datetime
from scripts.simulate_reports.data_builder import redistribute_scraped_at


def test_redistribute_keeps_count():
    reviews = [
        {"id": i, "date_published_parsed": f"2025-01-{(i%28)+1:02d}T10:00:00"}
        for i in range(20)
    ]
    out = redistribute_scraped_at(reviews, timeline_start=date(2026, 3, 20))
    assert len(out) == 20


def test_redistribute_respects_not_before_publish_date():
    reviews = [
        {"id": 1, "date_published_parsed": "2026-04-10T00:00:00"},  # 发布晚于 timeline start
    ]
    out = redistribute_scraped_at(reviews, timeline_start=date(2026, 3, 20))
    scraped = datetime.fromisoformat(out[0]["scraped_at"])
    pub = datetime.fromisoformat(out[0]["date_published_parsed"])
    assert scraped >= pub, "scraped_at must not precede publish date"


def test_redistribute_15pct_on_day1():
    """Earliest 15% should be stamped at timeline_start (cold-start)."""
    reviews = [
        {"id": i, "date_published_parsed": f"2024-0{(i%9)+1}-15T10:00:00"}
        for i in range(100)
    ]
    out = redistribute_scraped_at(reviews, timeline_start=date(2026, 3, 20))
    day1 = sum(
        1 for r in out
        if r["scraped_at"].startswith("2026-03-20")
    )
    assert 12 <= day1 <= 18, f"expected ~15, got {day1}"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/simulate_reports/test_scraped_at_redistribute.py -v
```
预期：ImportError / ModuleNotFoundError。

- [ ] **Step 3: 实现 `scripts/simulate_reports/data_builder.py`**

```python
"""Data-construction operations that mutate simulation.db or derive mutations."""
from datetime import date, datetime, timedelta
from typing import Iterable


# Fraction of reviews that land on the timeline start day (cold-start batch)
COLD_START_FRACTION = 0.15

# Remaining reviews spread across these relative offsets (days from timeline_start)
SPREAD_OFFSETS = (4, 8, 12, 18, 22, 26, 28)


def redistribute_scraped_at(
    reviews: list[dict],
    *,
    timeline_start: date,
) -> list[dict]:
    """Return a new list of reviews with scraped_at rewritten.

    Rules:
      - Earliest 15% (by date_published_parsed) → timeline_start 09:00
      - Remaining reviews sliced evenly across SPREAD_OFFSETS day-buckets
      - Always clamp: scraped_at >= date_published_parsed
    """
    sorted_reviews = sorted(
        reviews, key=lambda r: r.get("date_published_parsed") or ""
    )
    total = len(sorted_reviews)
    cold_n = max(1, int(total * COLD_START_FRACTION))

    out = []
    for i, r in enumerate(sorted_reviews):
        if i < cold_n:
            stamp = datetime.combine(timeline_start, datetime.min.time()).replace(hour=9)
        else:
            bucket_idx = (i - cold_n) % len(SPREAD_OFFSETS)
            offset = SPREAD_OFFSETS[bucket_idx]
            stamp = datetime.combine(
                timeline_start + timedelta(days=offset),
                datetime.min.time(),
            ).replace(hour=9, minute=15)
        # Enforce not-before-publish invariant
        pub_raw = r.get("date_published_parsed")
        if pub_raw:
            pub = datetime.fromisoformat(pub_raw.replace("Z", "+00:00").split("+")[0])
            if stamp < pub:
                stamp = pub
        new_r = dict(r)
        new_r["scraped_at"] = stamp.strftime("%Y-%m-%dT%H:%M:%S")
        out.append(new_r)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/simulate_reports/test_scraped_at_redistribute.py -v
```
预期：3 passed.

- [ ] **Step 5: 连到 prepare 命令**

追加到 `cmd/prepare.py`：

```python
def _apply_scraped_at_redistribution(conn):
    from ..data_builder import redistribute_scraped_at
    from datetime import date
    rows = [dict(r) for r in conn.execute(
        "SELECT id, date_published_parsed, scraped_at FROM reviews"
    ).fetchall()]
    new_rows = redistribute_scraped_at(rows, timeline_start=date(2026, 3, 20))
    conn.executemany(
        "UPDATE reviews SET scraped_at=? WHERE id=?",
        [(r["scraped_at"], r["id"]) for r in new_rows],
    )
    print(f"Redistributed scraped_at for {len(new_rows)} reviews")
```

并在 `run()` 里 `with open_db(SIM_DB) as conn:` 块里调 `_apply_scraped_at_redistribution(conn)`。

- [ ] **Step 6: 冒烟**

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -c "import sqlite3; c=sqlite3.connect('data/sim/simulation.db'); print(c.execute('SELECT MIN(scraped_at), MAX(scraped_at) FROM reviews').fetchone())"
```
预期：min≈`2026-03-20T09:00:00`，max 散落在 4 月中下旬。

- [ ] **Step 7: Commit**

```bash
git add scripts/simulate_reports/data_builder.py scripts/simulate_reports/cmd/prepare.py tests/
git commit -m "feat(sim): scraped_at redistribution (TDD)"
```

---

### Task 7: 回填 review_issue_labels（TDD）

**Files:**
- Create: `tests/simulate_reports/test_seed_labels.py`
- Modify: `scripts/simulate_reports/data_builder.py`
- Modify: `scripts/simulate_reports/cmd/prepare.py`

- [ ] **Step 1: 写测试**

```python
# tests/simulate_reports/test_seed_labels.py
import json
from scripts.simulate_reports.data_builder import expand_labels_rows


def test_expand_labels_basic():
    review_analysis_rows = [
        {"review_id": 1, "labels": json.dumps([
            {"code": "quality_stability", "polarity": "negative",
             "severity": "medium", "confidence": 0.85}
        ])},
        {"review_id": 2, "labels": json.dumps([
            {"code": "shipping", "polarity": "negative", "severity": "low", "confidence": 0.6},
            {"code": "price", "polarity": "positive", "severity": "low", "confidence": 0.5},
        ])},
    ]
    rows = expand_labels_rows(review_analysis_rows)
    assert len(rows) == 3
    assert rows[0]["review_id"] == 1
    assert rows[0]["label_code"] == "quality_stability"
    assert rows[0]["label_polarity"] == "negative"


def test_expand_labels_skip_invalid():
    review_analysis_rows = [
        {"review_id": 1, "labels": "{not json}"},
        {"review_id": 2, "labels": None},
        {"review_id": 3, "labels": "[]"},
    ]
    assert expand_labels_rows(review_analysis_rows) == []
```

- [ ] **Step 2: 跑测试，确认失败 (ImportError)**

- [ ] **Step 3: 加到 `data_builder.py`**

```python
import json


def expand_labels_rows(review_analysis_rows: list[dict]) -> list[dict]:
    """Flatten review_analysis.labels JSON into review_issue_labels rows."""
    out = []
    for ra in review_analysis_rows:
        labels_raw = ra.get("labels")
        if not labels_raw:
            continue
        try:
            labels = json.loads(labels_raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(labels, list):
            continue
        for lbl in labels:
            if not isinstance(lbl, dict) or "code" not in lbl:
                continue
            out.append({
                "review_id": ra["review_id"],
                "label_code": lbl.get("code"),
                "label_polarity": lbl.get("polarity", "neutral"),
                "severity": lbl.get("severity", "low"),
                "confidence": float(lbl.get("confidence", 0.5) or 0.5),
                "source": "seed_from_review_analysis",
                "taxonomy_version": "v1",
            })
    return out
```

- [ ] **Step 4: 跑测试通过**

- [ ] **Step 5: 写 `seed_issue_labels` 接入 prepare**

追加到 `data_builder.py`：

```python
def seed_issue_labels(conn) -> int:
    """Populate review_issue_labels from review_analysis.labels JSON."""
    rows = [dict(r) for r in conn.execute(
        "SELECT review_id, labels FROM review_analysis"
    ).fetchall()]
    to_insert = expand_labels_rows(rows)
    # Clear existing to be idempotent
    conn.execute("DELETE FROM review_issue_labels")
    now = "2026-03-20T09:00:00"
    conn.executemany(
        """INSERT INTO review_issue_labels
           (review_id, label_code, label_polarity, severity, confidence,
            source, taxonomy_version, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r["review_id"], r["label_code"], r["label_polarity"],
                r["severity"], r["confidence"], r["source"],
                r["taxonomy_version"], now, now,
            )
            for r in to_insert
        ],
    )
    return len(to_insert)
```

更新 `cmd/prepare.py` 的 run()：

```python
from ..data_builder import seed_issue_labels
# ...in the `with open_db(...)` block:
n = seed_issue_labels(conn)
print(f"Seeded review_issue_labels: {n} rows")
```

- [ ] **Step 6: 冒烟 + 验证**

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -c "import sqlite3; c=sqlite3.connect('data/sim/simulation.db'); print('labels:', c.execute('SELECT COUNT(*) FROM review_issue_labels').fetchone()[0])"
```
预期：labels 数量 >0（基于 review_analysis 的 labels JSON 展开数）。

- [ ] **Step 7: Commit**

```bash
git add scripts/simulate_reports/data_builder.py scripts/simulate_reports/cmd/prepare.py tests/simulate_reports/test_seed_labels.py
git commit -m "feat(sim): seed review_issue_labels from review_analysis (TDD)"
```

---

### Task 8: body_pool —— 按 label/polarity 索引真实评论文本

**Files:**
- Create: `tests/simulate_reports/test_body_pool.py`
- Create: `scripts/simulate_reports/body_pool.py`

- [ ] **Step 1: 写测试**

```python
# tests/simulate_reports/test_body_pool.py
import sqlite3
import pytest
from scripts.simulate_reports.body_pool import BodyPool


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(str(p))
    c.executescript("""
        CREATE TABLE reviews (id INTEGER PRIMARY KEY, body TEXT, headline TEXT, rating REAL, body_hash TEXT);
        CREATE TABLE review_issue_labels (id INTEGER PRIMARY KEY, review_id INT, label_code TEXT, label_polarity TEXT);
        INSERT INTO reviews VALUES
            (1, 'great quality', 'Love it', 5.0, 'h1'),
            (2, 'fell apart', 'Garbage', 1.0, 'h2'),
            (3, 'arrived late', 'Bad shipping', 2.0, 'h3');
        INSERT INTO review_issue_labels (review_id, label_code, label_polarity) VALUES
            (1, 'quality_stability', 'positive'),
            (2, 'quality_stability', 'negative'),
            (3, 'shipping', 'negative');
    """)
    c.commit()
    return p


def test_pool_sample_negative_quality(db):
    pool = BodyPool(db)
    sample = pool.sample("quality_stability", "negative", n=1)
    assert len(sample) == 1
    assert sample[0]["body"] == "fell apart"


def test_pool_sample_more_than_available(db):
    pool = BodyPool(db)
    sample = pool.sample("quality_stability", "negative", n=5)  # only 1 exists
    assert len(sample) >= 1  # reuses allowed
```

- [ ] **Step 2: 跑测试，失败**

- [ ] **Step 3: 实现 `body_pool.py`**

```python
"""Index real review texts keyed by (label_code, polarity) for cloning."""
import random
import sqlite3
from pathlib import Path


class BodyPool:
    def __init__(self, db_path: Path, *, seed: int = 42):
        self._rng = random.Random(seed)
        self._by_key: dict[tuple, list[dict]] = {}
        with sqlite3.connect(str(db_path)) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""
                SELECT r.id, r.body, r.headline, r.rating, r.body_hash,
                       l.label_code, l.label_polarity
                FROM reviews r
                JOIN review_issue_labels l ON l.review_id = r.id
            """).fetchall()
        for r in rows:
            key = (r["label_code"], r["label_polarity"])
            self._by_key.setdefault(key, []).append({
                "body": r["body"],
                "headline": r["headline"],
                "rating": r["rating"],
                "body_hash": r["body_hash"],
            })

    def sample(self, label_code: str, polarity: str, n: int) -> list[dict]:
        """Return n rows with replacement (always returns n items if pool non-empty)."""
        key = (label_code, polarity)
        pool = self._by_key.get(key, [])
        if not pool:
            # Fallback: sample any review with matching polarity
            for (lc, pol), rows in self._by_key.items():
                if pol == polarity and rows:
                    pool = rows
                    break
        if not pool:
            return []
        return [self._rng.choice(pool) for _ in range(n)]
```

- [ ] **Step 4: 测试通过**

- [ ] **Step 5: Commit**

```bash
git add scripts/simulate_reports/body_pool.py tests/simulate_reports/test_body_pool.py
git commit -m "feat(sim): body_pool for review-text cloning (TDD)"
```

---

### Task 9: data_builder —— inject_new_reviews 核心

**Files:**
- Modify: `scripts/simulate_reports/data_builder.py`

- [ ] **Step 1: 追加到 `data_builder.py`**

```python
import hashlib
from datetime import datetime, date as date_cls
from .body_pool import BodyPool


def _synthetic_hash(base_hash: str, salt: str) -> str:
    return hashlib.md5((base_hash + "|" + salt).encode()).hexdigest()[:16]


def inject_new_reviews(
    conn,
    *,
    pool: BodyPool,
    product_id: int,
    logical_date: date_cls,
    count: int,
    label_code: str,
    polarity: str,
    rating_range: tuple[float, float] = (1.0, 5.0),
    scraped_time_hhmm: str = "09:15",
) -> list[int]:
    """Clone reviews from pool and insert as new rows on `logical_date`.
    Returns inserted review IDs."""
    samples = pool.sample(label_code, polarity, count)
    if not samples:
        raise RuntimeError(
            f"BodyPool empty for ({label_code}, {polarity}); "
            "seed review_issue_labels first"
        )
    date_iso = logical_date.strftime("%Y-%m-%d")
    scraped_at = f"{date_iso}T{scraped_time_hhmm}:00"
    published = f"{date_iso}T08:00:00"

    inserted_ids = []
    for idx, s in enumerate(samples):
        salt = f"sim-{date_iso}-{product_id}-{idx}"
        body_hash = _synthetic_hash(s["body_hash"] or s["body"][:32], salt)
        # Choose rating from range based on polarity
        if polarity == "negative":
            rating = max(rating_range[0], min(2.0, s["rating"] or 2.0))
        else:
            rating = min(rating_range[1], max(4.0, s["rating"] or 4.0))
        cur = conn.execute(
            """INSERT INTO reviews
               (product_id, author, headline, body, body_hash, rating,
                date_published, date_published_parsed, scraped_at,
                translate_status, translate_retries, headline_cn, body_cn)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', 0, ?, ?)""",
            (
                product_id, f"SimUser{idx}", s["headline"], s["body"],
                body_hash, rating, date_iso, published, scraped_at,
                # reuse the pool's headline/body as "translation" for determinism
                (s["headline"] or "")[:200], (s["body"] or "")[:1000],
            ),
        )
        review_id = cur.lastrowid
        inserted_ids.append(review_id)
        # Mirror into review_analysis (minimal row)
        labels_json = (
            '[{"code":"' + label_code + '","polarity":"' + polarity +
            '","severity":"medium","confidence":0.8}]'
        )
        conn.execute(
            """INSERT INTO review_analysis
               (review_id, sentiment, sentiment_score, labels, insight_cn,
                prompt_version, analyzed_at, impact_category)
               VALUES (?, ?, ?, ?, ?, 'sim-v1', ?, ?)""",
            (
                review_id,
                "negative" if polarity == "negative" else "positive",
                -0.7 if polarity == "negative" else 0.7,
                labels_json, s["body"][:200], scraped_at,
                "experience",
            ),
        )
        # Mirror into review_issue_labels
        conn.execute(
            """INSERT INTO review_issue_labels
               (review_id, label_code, label_polarity, severity, confidence,
                source, taxonomy_version, created_at, updated_at)
               VALUES (?, ?, ?, 'medium', 0.8, 'sim', 'v1', ?, ?)""",
            (review_id, label_code, polarity, scraped_at, scraped_at),
        )
    return inserted_ids
```

- [ ] **Step 2: 冒烟 —— 用 python REPL 试调一次**

```bash
uv run python << 'EOF'
from pathlib import Path
from datetime import date
from scripts.simulate_reports.db import open_db
from scripts.simulate_reports.body_pool import BodyPool
from scripts.simulate_reports.data_builder import inject_new_reviews
import scripts.simulate_reports.config as cfg
pool = BodyPool(cfg.SIM_DB)
with open_db(cfg.SIM_DB) as c:
    pid = c.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
    ids = inject_new_reviews(c, pool=pool, product_id=pid,
                             logical_date=date(2026,3,21),
                             count=3,
                             label_code="quality_stability", polarity="negative")
    print("inserted", ids)
    c.execute("DELETE FROM reviews WHERE id IN ({})".format(",".join("?"*len(ids))), ids)
    c.execute("DELETE FROM review_analysis WHERE review_id IN ({})".format(",".join("?"*len(ids))), ids)
    c.execute("DELETE FROM review_issue_labels WHERE review_id IN ({})".format(",".join("?"*len(ids))), ids)
EOF
```
预期：`inserted [...]`，三行 ID。随即清理。

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/data_builder.py
git commit -m "feat(sim): inject_new_reviews with real-text cloning"
```

---

### Task 10: data_builder —— 其它事件（mutate/safety/translation/historical）

**Files:**
- Modify: `scripts/simulate_reports/data_builder.py`

- [ ] **Step 1: 追加 mutate_product**

```python
def mutate_product(
    conn,
    *,
    product_id: int,
    logical_date: date_cls,
    price_delta_pct: float | None = None,
    stock_status: str | None = None,
    rating_delta: float | None = None,
) -> None:
    """Update products + append product_snapshots row on logical_date."""
    row = conn.execute(
        "SELECT price, stock_status, rating, review_count FROM products WHERE id=?",
        (product_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"product {product_id} not found")
    price, stock, rating, rc = row
    new_price = price * (1 + price_delta_pct) if price_delta_pct else price
    new_stock = stock_status or stock
    new_rating = (rating or 0) + (rating_delta or 0) if rating_delta else rating
    scraped_at = logical_date.strftime("%Y-%m-%dT09:15:00")
    conn.execute(
        """UPDATE products SET price=?, stock_status=?, rating=?, scraped_at=?
           WHERE id=?""",
        (new_price, new_stock, new_rating, scraped_at, product_id),
    )
    conn.execute(
        """INSERT INTO product_snapshots
           (product_id, price, stock_status, review_count, rating, scraped_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (product_id, new_price, new_stock, rc, new_rating, scraped_at),
    )
```

- [ ] **Step 2: 追加 inject_safety_incidents**

```python
def inject_safety_incidents(
    conn,
    *,
    review_ids: list[int],
    safety_level: str = "critical",
    failure_mode: str = "foreign_object",
) -> None:
    for rid in review_ids:
        rsku = conn.execute(
            "SELECT p.sku FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.id=?",
            (rid,),
        ).fetchone()
        sku = rsku[0] if rsku else None
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            """INSERT INTO safety_incidents
               (review_id, product_sku, safety_level, failure_mode,
                evidence_snapshot, evidence_hash, detected_at, created_at)
               VALUES (?, ?, ?, ?, 'sim-evidence', 'sim-hash', ?, ?)""",
            (rid, sku, safety_level, failure_mode, ts, ts),
        )
```

- [ ] **Step 3: 追加 force_translation_stall**

```python
def force_translation_stall(
    conn,
    *,
    logical_date: date_cls,
    pending_fraction: float = 0.3,
) -> int:
    """Mark `pending_fraction` of reviews scraped on this date as stalled."""
    date_prefix = logical_date.strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT id FROM reviews WHERE scraped_at LIKE ? || '%'",
        (date_prefix,),
    ).fetchall()
    if not rows:
        return 0
    n = max(1, int(len(rows) * pending_fraction))
    ids = [r[0] for r in rows[:n]]
    conn.execute(
        f"""UPDATE reviews SET translate_status='pending', translate_retries=3
            WHERE id IN ({','.join('?'*len(ids))})""",
        ids,
    )
    return len(ids)
```

- [ ] **Step 4: 追加 seed_historical_pattern（R1-R4 预热）**

```python
def seed_historical_pattern(
    conn,
    *,
    pool: BodyPool,
    product_id: int,
    label_code: str,
    polarity: str,
    dates: list[date_cls],
    count_per_date: int = 1,
) -> list[int]:
    """Inject N reviews per date for a label, establishing history
    so that avg_interval and silence_window make sense for R3/R4 triggers."""
    all_ids = []
    for d in dates:
        ids = inject_new_reviews(
            conn, pool=pool, product_id=product_id,
            logical_date=d, count=count_per_date,
            label_code=label_code, polarity=polarity,
        )
        all_ids.extend(ids)
    return all_ids
```

- [ ] **Step 5: Commit**

```bash
git add scripts/simulate_reports/data_builder.py
git commit -m "feat(sim): mutate_product + safety + translation_stall + historical pattern"
```

---

## Phase 3 — Runner & Notifier Stub

### Task 11: runner.call_daily —— 绕过 submitter 直接 advance

**Files:**
- Create: `scripts/simulate_reports/runner.py`

- [ ] **Step 1: 写 runner.py**

```python
"""Call business report pipeline bypassing scheduler workers.

Uses:
  - models.create_workflow_run (directly INSERT with status='reporting')
  - WorkflowWorker._advance_run loop until terminal
  - notifier_stub for outbox drain
"""
from datetime import date, datetime, timedelta
from .env_bootstrap import load_business
from .clock import frozen_today


TERMINAL = {"completed", "needs_attention", "failed"}


def _advance_until_terminal(run_id: int, logical_date: date, *, max_iters: int = 20):
    biz = load_business()
    # Construct a minimal WorkflowWorker — reuse the class but we drive it manually
    # so no background thread is started.
    worker = biz.workflows.WorkflowWorker.__new__(biz.workflows.WorkflowWorker)
    # Minimal init — replicate what the class expects if __init__ starts a thread.
    # Fallback: call private method via bound method machinery.
    worker._running = False  # prevent any loop
    worker._translation_progress = {}  # if attribute exists

    now_iso = datetime.now().isoformat(timespec="seconds")
    for _ in range(max_iters):
        changed = worker._advance_run(run_id, now_iso)
        row = biz.models.get_conn().execute(
            "SELECT status FROM workflow_runs WHERE id=?", (run_id,),
        ).fetchone()
        if row and row[0] in TERMINAL:
            return row[0]
        if not changed:
            break
    # One more read for final status
    row = biz.models.get_conn().execute(
        "SELECT status FROM workflow_runs WHERE id=?", (run_id,),
    ).fetchone()
    return row[0] if row else "unknown"


def call_daily(logical_date: date) -> int:
    """Create daily workflow_run(status='reporting') + advance to terminal.
    Returns run_id."""
    biz = load_business()
    data_since = datetime.combine(logical_date, datetime.min.time()).isoformat()
    data_until = datetime.combine(
        logical_date + timedelta(days=1), datetime.min.time()
    ).isoformat()
    # Direct INSERT — bypass submit_daily_run's task orchestration
    with biz.models.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO workflow_runs
               (workflow_type, status, report_phase, logical_date,
                trigger_key, data_since, data_until, report_tier,
                created_at, updated_at, requested_by)
               VALUES ('daily', 'reporting', 'none', ?, ?, ?, ?, 'daily',
                       ?, ?, 'simulator')""",
            (
                logical_date.isoformat(),
                f"sim-daily:{logical_date.isoformat()}",
                data_since, data_until,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )
        run_id = cur.lastrowid
        conn.commit()
    with frozen_today(logical_date):
        _advance_until_terminal(run_id, logical_date)
    return run_id


def call_weekly(logical_date: date) -> int:
    biz = load_business()
    with frozen_today(logical_date):
        result = biz.workflows.submit_weekly_run(
            logical_date=logical_date.isoformat()
        )
        run_id = result["run"]["id"] if result.get("created") else result["run"]["id"]
        _advance_until_terminal(run_id, logical_date)
    return run_id


def call_monthly(logical_date: date) -> int:
    biz = load_business()
    with frozen_today(logical_date):
        result = biz.workflows.submit_monthly_run(
            logical_date=logical_date.isoformat()
        )
        run_id = result["run"]["id"]
        _advance_until_terminal(run_id, logical_date)
    return run_id
```

- [ ] **Step 2: 首轮冒烟（有可能失败，记录失败原因）**

```bash
uv run python << 'EOF'
from datetime import date
from scripts.simulate_reports.runner import call_daily
run_id = call_daily(date(2026, 3, 21))
print("daily run", run_id)
EOF
```

预期：如果 `WorkflowWorker._advance_run` 对 `__init__` 未完成的实例不容忍，会报错。此时需要打补丁：读 `workflows.py` 的 `WorkflowWorker.__init__` 看需要哪些属性，在 runner 里补齐最小集。

**处理策略**：失败时把 stacktrace 贴到本任务末尾注释，切到"plan B"：改用正常 `WorkflowWorker(config=..., models=...)` 构造但立即停止线程（`worker.stop()` 或不调 `start()`）。

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/runner.py
git commit -m "feat(sim): runner bypassing submitter + scheduler"
```

---

### Task 12: notifier_stub —— drain outbox 写邮件文件

**Files:**
- Create: `scripts/simulate_reports/notifier_stub.py`

- [ ] **Step 1: 写 notifier_stub.py**

```python
"""Read `notification_outbox` rows produced by a business run and
serialize their payloads to HTML/Markdown files under the scenario dir.
Mark drained rows as 'delivered' so they're not re-processed."""
import json
from datetime import datetime
from pathlib import Path
from .env_bootstrap import load_business


def drain_outbox_for_run(run_id: int, scenario_dir: Path) -> list[dict]:
    biz = load_business()
    emails_dir = scenario_dir / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    drained = []
    with biz.models.get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM notification_outbox
               WHERE status IN ('pending','claimed','deadletter','sent')
               ORDER BY id"""
        ).fetchall()
        for r in rows:
            try:
                payload = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                payload = {"_raw": r["payload"]}
            # Filter by run_id if present in payload
            if payload.get("run_id") not in (None, run_id):
                continue
            kind = r["kind"] or "unknown"
            fname_base = f"{kind}-outbox{r['id']}"
            # Write JSON sidecar always
            (emails_dir / f"{fname_base}.json").write_text(
                json.dumps(dict(r), default=str, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # If payload has html/body, write it as .html
            if isinstance(payload, dict):
                body = payload.get("html") or payload.get("body") or payload.get("markdown")
                if body:
                    ext = "html" if "html" in payload else "md"
                    (emails_dir / f"{fname_base}.{ext}").write_text(
                        body, encoding="utf-8",
                    )
            now_iso = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE notification_outbox SET status='delivered', delivered_at=? WHERE id=?",
                (now_iso, r["id"]),
            )
            drained.append({
                "id": r["id"], "kind": kind, "channel": r["channel"],
                "status_before": r["status"],
            })
        conn.commit()
    return drained
```

- [ ] **Step 2: Commit**

```bash
git add scripts/simulate_reports/notifier_stub.py
git commit -m "feat(sim): notifier_stub drains outbox to files"
```

---

### Task 13: checkpoint —— 逐日 DB 快照

**Files:**
- Create: `tests/simulate_reports/test_checkpoint.py`
- Create: `scripts/simulate_reports/checkpoint.py`

- [ ] **Step 1: 写测试**

```python
# tests/simulate_reports/test_checkpoint.py
from datetime import date
from scripts.simulate_reports.checkpoint import checkpoint_name, parse_checkpoint_name


def test_name_roundtrip():
    assert checkpoint_name(date(2026, 3, 20)) == "2026-03-20.db"
    assert parse_checkpoint_name("2026-03-20.db") == date(2026, 3, 20)
```

- [ ] **Step 2: 失败 → 实现 `checkpoint.py`**

```python
"""Per-day snapshot of simulation.db for fast single-scenario replay."""
import shutil
from datetime import date, datetime
from pathlib import Path
from . import config


def checkpoint_name(d: date) -> str:
    return f"{d.isoformat()}.db"


def parse_checkpoint_name(fname: str) -> date:
    stem = fname.rsplit(".db", 1)[0]
    return datetime.strptime(stem, "%Y-%m-%d").date()


def save(d: date) -> Path:
    config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    dst = config.CHECKPOINT_DIR / checkpoint_name(d)
    shutil.copy2(config.SIM_DB, dst)
    return dst


def restore_before(d: date) -> date | None:
    """Copy the latest checkpoint strictly before `d` into SIM_DB. Return its date."""
    if not config.CHECKPOINT_DIR.exists():
        return None
    candidates = sorted(
        (parse_checkpoint_name(p.name), p)
        for p in config.CHECKPOINT_DIR.glob("*.db")
    )
    valid = [(cd, cp) for cd, cp in candidates if cd < d]
    if not valid:
        return None
    latest_date, latest_path = valid[-1]
    shutil.copy2(latest_path, config.SIM_DB)
    return latest_date
```

- [ ] **Step 3: 测试通过 → Commit**

```bash
git add scripts/simulate_reports/checkpoint.py tests/simulate_reports/test_checkpoint.py
git commit -m "feat(sim): per-day db checkpoint helpers (TDD)"
```

---

### Task 14: runner + notifier 端到端烟测（S02 单日）

**Files:**
- Create: `scripts/simulate_reports/dev_smoke.py`（临时脚本，完成后删除或移 tests/）

- [ ] **Step 1: 写 `dev_smoke.py`**

```python
"""Run: uv run python -m scripts.simulate_reports.dev_smoke
Goal: prepare DB + run one daily on 2026-03-21 end-to-end."""
from datetime import date
from pathlib import Path
import shutil
from .env_bootstrap import set_env
from . import config

def main():
    set_env()
    from .runner import call_daily
    from .notifier_stub import drain_outbox_for_run

    scenario_dir = config.SCENARIOS_DIR / "_smoke-2026-03-21"
    shutil.rmtree(scenario_dir, ignore_errors=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    run_id = call_daily(date(2026, 3, 21))
    print("run_id =", run_id)

    # Copy business outputs
    for p in config.REPORT_WORK_DIR.glob("*.html"):
        shutil.copy2(p, scenario_dir / p.name)
    for p in config.REPORT_WORK_DIR.glob("*.xlsx"):
        shutil.copy2(p, scenario_dir / p.name)
    for p in config.REPORT_WORK_DIR.glob("*.json"):
        shutil.copy2(p, scenario_dir / p.name)

    drained = drain_outbox_for_run(run_id, scenario_dir)
    print("drained outbox:", drained)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 先 prepare，再 smoke**

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -m scripts.simulate_reports.dev_smoke
ls "C:/Users/leo/Desktop/报告/reports/scenarios/_smoke-2026-03-21/"
```

预期：至少 1 份 HTML 产物。若失败，按 runner 任务 2 里 plan B 的指示调整。

- [ ] **Step 3: 冒烟过了，Commit 并移除 smoke 脚本**

```bash
git rm scripts/simulate_reports/dev_smoke.py
git commit -m "chore(sim): e2e smoke passed, remove dev_smoke"
```

---

## Phase 4 — Debug Artifacts, Manifest, Scenarios

### Task 15: debug_dump —— 9 个 debug 文件

**Files:**
- Create: `scripts/simulate_reports/debug_dump.py`

- [ ] **Step 1: 写 `debug_dump.py`**

```python
"""Write per-scenario debug/ artifacts."""
import hashlib
import json
import re
import shutil
from pathlib import Path
from .env_bootstrap import load_business
from .db import open_db, row_counts
from . import config


def _json_dump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dump_db_state(kind: str, scenario_dir: Path):
    """kind = 'before' | 'after'"""
    with open_db(config.SIM_DB) as conn:
        counts = row_counts(conn)
        samples = {
            "products_by_site_ownership": [
                dict(r) for r in conn.execute(
                    "SELECT site, ownership, COUNT(*) n FROM products GROUP BY site, ownership"
                ).fetchall()
            ],
            "reviews_by_scraped_date": [
                dict(r) for r in conn.execute(
                    "SELECT substr(scraped_at,1,10) d, COUNT(*) n "
                    "FROM reviews GROUP BY d ORDER BY d DESC LIMIT 10"
                ).fetchall()
            ],
            "labels_top": [
                dict(r) for r in conn.execute(
                    "SELECT label_code, label_polarity, COUNT(*) n "
                    "FROM review_issue_labels GROUP BY label_code, label_polarity "
                    "ORDER BY n DESC LIMIT 10"
                ).fetchall()
            ],
        }
    _json_dump({"counts": counts, "samples": samples},
               scenario_dir / "debug" / f"db_state_{kind}.json")


def dump_workflow_run(run_id: int, scenario_dir: Path):
    biz = load_business()
    with biz.models.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()
    _json_dump(dict(row) if row else None,
               scenario_dir / "debug" / "workflow_run.json")


def dump_outbox_rows(run_id: int, scenario_dir: Path):
    biz = load_business()
    with biz.models.get_conn() as conn:
        rows = conn.execute(
            """SELECT id, kind, channel, status, attempts, delivered_at,
                      last_error, created_at, payload
               FROM notification_outbox ORDER BY id"""
        ).fetchall()
    parsed = []
    for r in rows:
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            pl = None
        d = dict(r)
        d["payload_parsed"] = pl
        if isinstance(pl, dict) and pl.get("run_id") not in (None, run_id):
            continue
        parsed.append(d)
    _json_dump(parsed, scenario_dir / "debug" / "outbox_rows.json")


def dump_analytics_tree(run_id: int, scenario_dir: Path):
    biz = load_business()
    with biz.models.get_conn() as conn:
        row = conn.execute(
            "SELECT analytics_path FROM workflow_runs WHERE id=?", (run_id,),
        ).fetchone()
    if row and row["analytics_path"] and Path(row["analytics_path"]).exists():
        shutil.copy2(row["analytics_path"],
                     scenario_dir / "debug" / "analytics_tree.json")


def dump_top_reviews(run_id: int, scenario_dir: Path, *, limit: int = 20):
    """Dump the top reviews (by scraped_at desc within window) for this run."""
    biz = load_business()
    with biz.models.get_conn() as conn:
        run = conn.execute(
            "SELECT data_since, data_until FROM workflow_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if not run or not run["data_since"]:
            _json_dump([], scenario_dir / "debug" / "top_reviews.json")
            return
        rows = conn.execute(
            """SELECT r.id, r.product_id, p.sku, r.rating, r.headline,
                      substr(r.body,1,120) body_preview, r.scraped_at,
                      ra.sentiment, ra.labels, ra.insight_cn
               FROM reviews r
               LEFT JOIN products p ON p.id=r.product_id
               LEFT JOIN review_analysis ra ON ra.review_id=r.id
               WHERE r.scraped_at >= ? AND r.scraped_at < ?
               ORDER BY r.scraped_at DESC LIMIT ?""",
            (run["data_since"], run["data_until"], limit),
        ).fetchall()
    _json_dump([dict(r) for r in rows],
               scenario_dir / "debug" / "top_reviews.json")


def dump_html_checksum(scenario_dir: Path):
    """Structural fingerprint of any .html in scenario root."""
    summary = {}
    for html in scenario_dir.glob("*.html"):
        raw = html.read_text(encoding="utf-8", errors="ignore")
        tags = re.findall(r"<(\w+)", raw)
        tag_counts = {}
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        summary[html.name] = {
            "byte_len": len(raw),
            "sha1_first32": hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32],
            "tag_counts": dict(sorted(tag_counts.items(), key=lambda kv: -kv[1])[:15]),
        }
    (scenario_dir / "debug").mkdir(exist_ok=True)
    (scenario_dir / "debug" / "html_checksum.txt").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def dump_excel_structure(scenario_dir: Path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        return
    summary = {}
    for xlsx in scenario_dir.glob("*.xlsx"):
        try:
            wb = load_workbook(xlsx, read_only=True)
            summary[xlsx.name] = {
                name: {"max_row": wb[name].max_row, "max_col": wb[name].max_column}
                for name in wb.sheetnames
            }
        except Exception as e:
            summary[xlsx.name] = {"_error": str(e)}
    _json_dump(summary, scenario_dir / "debug" / "excel_structure.json")


def dump_events_applied(events: list, scenario_dir: Path):
    _json_dump(events, scenario_dir / "debug" / "events_applied.json")
```

- [ ] **Step 2: Commit**

```bash
git add scripts/simulate_reports/debug_dump.py
git commit -m "feat(sim): debug/ artifact dumpers (9 files)"
```

---

### Task 16: manifest —— expected/actual/verdict（TDD）

**Files:**
- Create: `tests/simulate_reports/test_manifest.py`
- Create: `scripts/simulate_reports/manifest.py`

- [ ] **Step 1: 写测试**

```python
# tests/simulate_reports/test_manifest.py
from scripts.simulate_reports.manifest import compute_verdict


def test_verdict_pass():
    expected = {"report_mode": "standard", "lifecycle_states_must_include": ["active"]}
    actual = {"report_mode": "standard", "lifecycle_states_seen": ["active", "dormant"]}
    v, failures, warnings = compute_verdict(expected, actual)
    assert v == "PASS"
    assert failures == []


def test_verdict_fail_on_mode():
    expected = {"report_mode": "change"}
    actual = {"report_mode": "standard"}
    v, failures, _ = compute_verdict(expected, actual)
    assert v == "FAIL"
    assert any("report_mode" in f for f in failures)


def test_verdict_fail_lifecycle_missing():
    expected = {"lifecycle_states_must_include": ["recurrent"]}
    actual = {"lifecycle_states_seen": ["active"]}
    v, failures, _ = compute_verdict(expected, actual)
    assert v == "FAIL"
    assert any("recurrent" in f for f in failures)


def test_verdict_html_contains():
    expected = {"html_must_contain": ["复发"]}
    actual = {"html_contains": {"复发": False}}
    v, failures, _ = compute_verdict(expected, actual)
    assert v == "FAIL"
```

- [ ] **Step 2: 失败 → 实现 `manifest.py`**

```python
"""Build per-scenario manifest: expected / actual / verdict."""
import json
import subprocess
from datetime import datetime
from pathlib import Path


def compute_verdict(expected: dict, actual: dict) -> tuple[str, list[str], list[str]]:
    failures, warnings = [], []
    # report_mode exact match
    if "report_mode" in expected and expected["report_mode"] != actual.get("report_mode"):
        failures.append(
            f"report_mode: expected={expected['report_mode']}, actual={actual.get('report_mode')}"
        )
    if "tier" in expected and expected["tier"] != actual.get("tier"):
        failures.append(f"tier: expected={expected['tier']}, actual={actual.get('tier')}")
    if "is_partial" in expected and expected["is_partial"] != actual.get("is_partial"):
        failures.append(
            f"is_partial: expected={expected['is_partial']}, actual={actual.get('is_partial')}"
        )
    # lifecycle must include
    must = set(expected.get("lifecycle_states_must_include", []))
    seen = set(actual.get("lifecycle_states_seen", []))
    missing = must - seen
    if missing:
        failures.append(f"lifecycle missing: {sorted(missing)}")
    # html contains
    for token in expected.get("html_must_contain", []):
        if not actual.get("html_contains", {}).get(token):
            failures.append(f"html missing token: {token!r}")
    # excel sheets
    for sheet in expected.get("excel_must_have_sheets", []):
        if sheet not in actual.get("excel_sheets", []):
            failures.append(f"excel missing sheet: {sheet!r}")
    # email counts
    if "email_count_min" in expected:
        if actual.get("email_count", 0) < expected["email_count_min"]:
            warnings.append(
                f"email_count {actual.get('email_count')} < min {expected['email_count_min']}"
            )
    if "email_count_max" in expected:
        if actual.get("email_count", 0) > expected["email_count_max"]:
            warnings.append(
                f"email_count {actual.get('email_count')} > max {expected['email_count_max']}"
            )
    if failures:
        return "FAIL", failures, warnings
    if warnings:
        return "WARN", failures, warnings
    return "PASS", failures, warnings


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def build_manifest(
    *,
    scenario_id: str,
    logical_date,
    phase: str,
    description: str,
    tier: str,
    expected: dict,
    actual: dict,
    artifacts: list[str],
) -> dict:
    verdict, failures, warnings = compute_verdict(expected, actual)
    return {
        "scenario_id": scenario_id,
        "logical_date": logical_date.isoformat() if hasattr(logical_date, "isoformat") else str(logical_date),
        "phase": phase,
        "description": description,
        "tier": tier,
        "expected": expected,
        "actual": actual,
        "verdict": verdict,
        "failures": failures,
        "warnings": warnings,
        "artifacts": artifacts,
        "git_sha": _git_sha(),
        "spec_version": "2026-04-17",
        "executed_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_manifest(scenario_dir: Path, manifest: dict):
    (scenario_dir / "manifest.json").write_text(
        json.dumps(manifest, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_manifest(scenario_dir: Path) -> dict | None:
    p = scenario_dir / "manifest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def collect_actual(
    *,
    run_id: int,
    scenario_dir: Path,
    expected: dict,
) -> dict:
    """Inspect business output + scenario files to populate `actual` dict."""
    from .env_bootstrap import load_business
    biz = load_business()
    actual: dict = {}
    with biz.models.get_conn() as conn:
        run = conn.execute(
            "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()
    if run:
        actual["tier"] = run["report_tier"]
        actual["report_mode"] = run["report_mode"]
        actual["status"] = run["status"]
        actual["report_phase"] = run["report_phase"]
    # is_partial / lifecycle_states_seen: pull from analytics json
    analytics_path = scenario_dir / "debug" / "analytics_tree.json"
    if analytics_path.exists():
        try:
            tree = json.loads(analytics_path.read_text(encoding="utf-8"))
            actual["is_partial"] = bool(tree.get("is_partial"))
            states = set()
            for lc in (tree.get("lifecycle") or {}).values():
                if isinstance(lc, dict) and lc.get("state"):
                    states.add(lc["state"])
            actual["lifecycle_states_seen"] = sorted(states)
        except Exception:
            pass
    # html contains
    html_checks = {}
    html_files = list(scenario_dir.glob("*.html"))
    combined_html = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore") for f in html_files
    )
    for token in expected.get("html_must_contain", []):
        html_checks[token] = token in combined_html
    actual["html_contains"] = html_checks
    # excel sheets
    xl_struct = scenario_dir / "debug" / "excel_structure.json"
    sheets = set()
    if xl_struct.exists():
        try:
            s = json.loads(xl_struct.read_text(encoding="utf-8"))
            for sheet_map in s.values():
                if isinstance(sheet_map, dict):
                    sheets.update(sheet_map.keys())
        except Exception:
            pass
    actual["excel_sheets"] = sorted(sheets)
    # email count
    emails_dir = scenario_dir / "emails"
    actual["email_count"] = (
        len(list(emails_dir.glob("*.html"))) + len(list(emails_dir.glob("*.md")))
        if emails_dir.exists() else 0
    )
    return actual
```

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/manifest.py tests/simulate_reports/test_manifest.py
git commit -m "feat(sim): manifest expected/actual/verdict (TDD)"
```

---

### Task 17: scenarios.py —— 11 个 named + S02 变体 + W/M

**Files:**
- Create: `scripts/simulate_reports/scenarios.py`

- [ ] **Step 1: 写 `scenarios.py`**

```python
"""Scenario definitions: SID → {description, events, expected}.

`events` is a list of structured dicts applied by timeline.apply_events().
`expected` feeds manifest.compute_verdict().
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable


@dataclass
class Scenario:
    sid: str
    logical_date: date
    phase: str
    tier: str             # 'daily' | 'weekly' | 'monthly'
    description: str
    events: list[dict] = field(default_factory=list)
    expected: dict = field(default_factory=dict)


# Helper constructors ---------------------------------------------------------

def _ev(op: str, **kwargs) -> dict:
    return {"op": op, **kwargs}


# Named scenarios -------------------------------------------------------------

SCENARIOS: dict[str, Scenario] = {}


def _add(s: Scenario):
    SCENARIOS[s.sid] = s


# S01 cold-start: D01 = 2026-03-20
_add(Scenario(
    sid="S01", logical_date=date(2026, 3, 20), phase="P1", tier="daily",
    description="首日部署冷启动 (is_partial=true)",
    events=[],  # prepare 已把 scraped_at 重分布好
    expected={
        "tier": "daily", "report_mode": "standard",
        "is_partial": True,
        "html_must_contain": [],
    },
))

# S02 normal Full (仅声明一次作为代表；时间轴会多天复用 S02 变体)
_add(Scenario(
    sid="S02", logical_date=date(2026, 3, 21), phase="P1", tier="daily",
    description="常规 Full 模式",
    events=[
        _ev("inject_new_reviews", count=8, polarity="positive",
            label="quality_stability"),
        _ev("inject_new_reviews", count=3, polarity="negative",
            label="shipping"),
    ],
    expected={"tier": "daily", "report_mode": "standard", "is_partial": False},
))

# S03 safety doubled (D07 = 2026-03-26)
_add(Scenario(
    sid="S03", logical_date=date(2026, 3, 26), phase="P1", tier="daily",
    description="Safety incidents 集中注入，触发 R6 silence×2",
    events=[
        _ev("inject_new_reviews", count=6, polarity="negative",
            label="safety"),
        _ev("inject_safety_incidents_from_today", level="critical",
            failure_mode="foreign_object"),
    ],
    expected={"tier": "daily", "report_mode": "standard"},
))

# S04 R1 active (D08 = 2026-03-27)
_add(Scenario(
    sid="S04", logical_date=date(2026, 3, 27), phase="P2", tier="daily",
    description="quality_stability 集中差评 → R1 active",
    events=[
        _ev("inject_new_reviews", count=6, polarity="negative",
            label="quality_stability"),
    ],
    expected={
        "tier": "daily", "report_mode": "standard",
        "lifecycle_states_must_include": ["active"],
    },
))

# S05 R2 receding (D12 = 2026-03-31)
_add(Scenario(
    sid="S05", logical_date=date(2026, 3, 31), phase="P2", tier="daily",
    description="quality_stability 正负比回落 → R2 receding",
    events=[
        _ev("inject_new_reviews", count=8, polarity="positive",
            label="quality_stability"),
    ],
    expected={
        "tier": "daily",
        "lifecycle_states_must_include": ["receding"],
    },
))

# S06 R3 dormant (D15 = 2026-04-03) — no events, just static over silence window
_add(Scenario(
    sid="S06", logical_date=date(2026, 4, 3), phase="P3", tier="daily",
    description="quality_stability 进入静默（背景）",
    events=[
        _ev("inject_new_reviews", count=3, polarity="negative",
            label="shipping"),  # 其他 label 照常
    ],
    expected={"tier": "daily"},
))

# S07 daily-change (D16 = 2026-04-04)
_add(Scenario(
    sid="S07", logical_date=date(2026, 4, 4), phase="P3", tier="daily",
    description="0 新评论 + 价格-15% + 库存 out_of_stock → Change 模式",
    events=[
        _ev("mutate_random_product", price_delta_pct=-0.15,
            stock_status="out_of_stock"),
    ],
    expected={"tier": "daily", "report_mode": "change"},
))

# S08 quiet email days (D17-D19)
for sid, d, n in [("S08a", date(2026, 4, 5), 1),
                  ("S08b", date(2026, 4, 6), 2),
                  ("S08c", date(2026, 4, 7), 3)]:
    _add(Scenario(
        sid=sid, logical_date=d, phase="P3", tier="daily",
        description=f"Quiet 模式第 {n} 天（发邮件）",
        events=[],
        expected={
            "tier": "daily", "report_mode": "quiet",
            "email_count_min": 1,
        },
    ))

# S09 quiet silent days (D20-D22)
for sid, d in [("S09a", date(2026, 4, 8)),
               ("S09b", date(2026, 4, 9)),
               ("S09c", date(2026, 4, 10))]:
    _add(Scenario(
        sid=sid, logical_date=d, phase="P3", tier="daily",
        description="Quiet 模式持续静默（不发邮件）",
        events=[],
        expected={
            "tier": "daily", "report_mode": "quiet",
            "email_count_max": 0,
        },
    ))

# S10 R4 recurrent (D26 = 2026-04-14) — 距 D11 last-active 15 天 ≥ silence_window 14
_add(Scenario(
    sid="S10", logical_date=date(2026, 4, 14), phase="P4", tier="daily",
    description="quality_stability 复发 → R4 recurrent",
    events=[
        _ev("inject_new_reviews", count=4, polarity="negative",
            label="quality_stability"),
    ],
    expected={
        "tier": "daily",
        "lifecycle_states_must_include": ["recurrent"],
    },
))

# S11 needs-attention (D27 = 2026-04-15)
_add(Scenario(
    sid="S11", logical_date=date(2026, 4, 15), phase="P4", tier="daily",
    description="30% 当日评论翻译 stalled → needs_attention",
    events=[
        _ev("inject_new_reviews", count=10, polarity="positive",
            label="shipping"),
        _ev("force_translation_stall", pending_fraction=0.3),
    ],
    expected={
        "tier": "daily",
        "email_count_max": 0,
    },
))

# Weekly & monthly ------------------------------------------------------------
for wid, d, phase in [
    ("W0", date(2026, 3, 23), "P1"),
    ("W1", date(2026, 3, 30), "P2"),
    ("W2", date(2026, 4, 6),  "P3"),
    ("W3", date(2026, 4, 13), "P4"),
    ("W4", date(2026, 4, 20), "P5"),
    ("W5", date(2026, 4, 27), "P5"),
]:
    _add(Scenario(
        sid=wid, logical_date=d, phase=phase, tier="weekly",
        description=f"周报 {d.isocalendar().year}W{d.isocalendar().week:02d}",
        events=[],
        expected={"tier": "weekly"},
    ))

_add(Scenario(
    sid="M1", logical_date=date(2026, 5, 1), phase="P5", tier="monthly",
    description="月报 2026-04（含品类对标 + LLM 高管摘要）",
    events=[],
    expected={
        "tier": "monthly",
        "excel_must_have_sheets": ["评论明细", "产品概览"],
    },
))
```

- [ ] **Step 2: Commit**

```bash
git add scripts/simulate_reports/scenarios.py
git commit -m "feat(sim): 15 daily + 6 weekly + 1 monthly scenarios"
```

---

### Task 18: timeline.py —— 42 天事件编排 + apply

**Files:**
- Create: `scripts/simulate_reports/timeline.py`

- [ ] **Step 1: 写 `timeline.py`**

```python
"""42-day timeline: date → list of scenario IDs scheduled that day.
Plus apply_events() that translates event specs into data_builder calls."""
import random
from datetime import date, timedelta
from .scenarios import SCENARIOS, Scenario
from . import config


# One day may have multiple scenarios (e.g. daily + weekly + monthly on 2026-05-01).
TIMELINE: dict[date, list[str]] = {}


def _build():
    for sid, sc in SCENARIOS.items():
        TIMELINE.setdefault(sc.logical_date, []).append(sid)
    # Fill "gap days" with S02-variant daily so the timeline is contiguous
    cur = config.TIMELINE_START
    while cur <= config.TIMELINE_END:
        if cur not in TIMELINE or not any(
            SCENARIOS[s].tier == "daily" for s in TIMELINE[cur]
        ):
            variant_sid = f"S02_{cur.isoformat()}"
            SCENARIOS[variant_sid] = Scenario(
                sid=variant_sid, logical_date=cur, phase="P*", tier="daily",
                description="常规 Full 模式 (gap filler)",
                events=[
                    {"op": "inject_new_reviews", "count": 5,
                     "polarity": "positive", "label": "quality_stability"},
                    {"op": "inject_new_reviews", "count": 2,
                     "polarity": "negative", "label": "shipping"},
                ],
                expected={"tier": "daily", "report_mode": "standard"},
            )
            TIMELINE.setdefault(cur, []).append(variant_sid)
        cur += timedelta(days=1)


_build()


def apply_events(conn, *, logical_date: date, events: list[dict]) -> list[dict]:
    """Translate event specs into data_builder calls.
    Returns the applied events for logging."""
    from .body_pool import BodyPool
    from . import data_builder as db
    pool = BodyPool(config.SIM_DB)
    rng = random.Random(42 + logical_date.toordinal())
    product_ids = [
        r[0] for r in conn.execute("SELECT id FROM products ORDER BY id").fetchall()
    ]
    applied = []
    for ev in events:
        op = ev["op"]
        if op == "inject_new_reviews":
            pid = rng.choice(product_ids)
            ids = db.inject_new_reviews(
                conn, pool=pool, product_id=pid, logical_date=logical_date,
                count=ev["count"], label_code=ev["label"],
                polarity=ev["polarity"],
            )
            applied.append({**ev, "_product_id": pid, "_review_ids": ids})
        elif op == "inject_safety_incidents_from_today":
            # Use reviews scraped today that already have negative polarity
            today = logical_date.strftime("%Y-%m-%d")
            rids = [r[0] for r in conn.execute(
                "SELECT id FROM reviews WHERE scraped_at LIKE ? || '%' "
                "AND rating <= 2", (today,),
            ).fetchall()]
            db.inject_safety_incidents(
                conn, review_ids=rids,
                safety_level=ev.get("level", "critical"),
                failure_mode=ev.get("failure_mode", "foreign_object"),
            )
            applied.append({**ev, "_review_ids": rids})
        elif op == "mutate_random_product":
            pid = rng.choice(product_ids)
            db.mutate_product(
                conn, product_id=pid, logical_date=logical_date,
                price_delta_pct=ev.get("price_delta_pct"),
                stock_status=ev.get("stock_status"),
                rating_delta=ev.get("rating_delta"),
            )
            applied.append({**ev, "_product_id": pid})
        elif op == "force_translation_stall":
            n = db.force_translation_stall(
                conn, logical_date=logical_date,
                pending_fraction=ev.get("pending_fraction", 0.3),
            )
            applied.append({**ev, "_marked": n})
        else:
            raise ValueError(f"Unknown event op: {op!r}")
    conn.commit()
    return applied
```

- [ ] **Step 2: Commit**

```bash
git add scripts/simulate_reports/timeline.py
git commit -m "feat(sim): 42-day timeline + event applier"
```

---

## Phase 5 — Run Commands

### Task 19: cmd/run.py —— 主时间轴 runner

**Files:**
- Create: `scripts/simulate_reports/cmd/run.py`

- [ ] **Step 1: 写 `cmd/run.py`**

```python
"""python -m scripts.simulate_reports run"""
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from .. import config
from ..env_bootstrap import set_env
from ..db import open_db


def _scenario_dirname(sid, sc):
    slug = sc.description.split("（")[0].split(" —")[0]
    slug = (slug.replace(" ", "-").replace("/", "-").replace(":", "-"))[:40]
    return f"{sid}-{sc.logical_date.isoformat()}-{slug}"


def _copy_business_outputs(scenario_dir: Path):
    for src in config.REPORT_WORK_DIR.glob("*"):
        if src.is_file():
            shutil.copy2(src, scenario_dir / src.name)
    # Purge REPORT_WORK_DIR so next scenario starts clean
    for p in config.REPORT_WORK_DIR.glob("*"):
        if p.is_file():
            p.unlink()


def run(argv):
    set_env()
    from ..timeline import TIMELINE, apply_events
    from ..scenarios import SCENARIOS
    from ..runner import call_daily, call_weekly, call_monthly
    from ..notifier_stub import drain_outbox_for_run
    from ..debug_dump import (
        dump_db_state, dump_workflow_run, dump_outbox_rows,
        dump_analytics_tree, dump_top_reviews, dump_html_checksum,
        dump_excel_structure, dump_events_applied,
    )
    from ..manifest import build_manifest, write_manifest, collect_actual
    from ..checkpoint import save as save_checkpoint

    config.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    # Move legacy products in reports/
    config.LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    for p in config.REPORT_ROOT.glob("daily-*.*"):
        shutil.move(str(p), config.LEGACY_DIR / p.name)
    for p in config.REPORT_ROOT.glob("workflow-run-*.*"):
        shutil.move(str(p), config.LEGACY_DIR / p.name)

    cur = config.TIMELINE_START
    while cur <= config.TIMELINE_END:
        sids_today = TIMELINE.get(cur, [])
        if not sids_today:
            cur += timedelta(days=1)
            continue
        # Apply all events for the day once (accumulated across scenarios)
        all_events_applied = []
        # Dump BEFORE state once
        _sample_sid = sids_today[0]
        _tmp_dir = config.SCENARIOS_DIR / f"_day-{cur.isoformat()}"
        _tmp_dir.mkdir(parents=True, exist_ok=True)
        dump_db_state("before", _tmp_dir)

        with open_db(config.SIM_DB) as conn:
            for sid in sids_today:
                sc = SCENARIOS[sid]
                if sc.events:
                    applied = apply_events(conn,
                                           logical_date=cur,
                                           events=sc.events)
                    all_events_applied.extend(applied)
        # Dump AFTER state (once per day)
        dump_db_state("after", _tmp_dir)

        for sid in sids_today:
            sc = SCENARIOS[sid]
            scenario_dir = config.SCENARIOS_DIR / _scenario_dirname(sid, sc)
            shutil.rmtree(scenario_dir, ignore_errors=True)
            scenario_dir.mkdir(parents=True, exist_ok=True)
            # Copy day-level debug into each scenario that day
            shutil.copytree(_tmp_dir / "debug", scenario_dir / "debug",
                            dirs_exist_ok=True)
            dump_events_applied(all_events_applied, scenario_dir)

            print(f"\n=== {sid} {sc.logical_date} ({sc.tier}) ===")
            try:
                if sc.tier == "daily":
                    run_id = call_daily(sc.logical_date)
                elif sc.tier == "weekly":
                    run_id = call_weekly(sc.logical_date)
                elif sc.tier == "monthly":
                    run_id = call_monthly(sc.logical_date)
                else:
                    continue
            except Exception as e:
                import traceback
                (scenario_dir / "ERROR.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
                print(f"  ERROR: {e}", file=sys.stderr)
                continue

            _copy_business_outputs(scenario_dir)
            dump_workflow_run(run_id, scenario_dir)
            dump_outbox_rows(run_id, scenario_dir)
            dump_analytics_tree(run_id, scenario_dir)
            dump_top_reviews(run_id, scenario_dir)
            dump_html_checksum(scenario_dir)
            dump_excel_structure(scenario_dir)
            drain_outbox_for_run(run_id, scenario_dir)

            actual = collect_actual(run_id=run_id, scenario_dir=scenario_dir,
                                    expected=sc.expected)
            manifest = build_manifest(
                scenario_id=sid, logical_date=sc.logical_date,
                phase=sc.phase, description=sc.description, tier=sc.tier,
                expected=sc.expected, actual=actual,
                artifacts=[p.name for p in scenario_dir.iterdir() if p.is_file()],
            )
            write_manifest(scenario_dir, manifest)
            print(f"  verdict: {manifest['verdict']}")

        # Cleanup day-level tmp
        shutil.rmtree(_tmp_dir, ignore_errors=True)
        # Checkpoint
        save_checkpoint(cur)
        cur += timedelta(days=1)

    print("\nAll done. Run 'index' to build index.html, 'verify' to summarize issues.")
    return 0
```

- [ ] **Step 2: Commit**

```bash
git add scripts/simulate_reports/cmd/run.py
git commit -m "feat(sim): main 42-day run command orchestrator"
```

---

### Task 20: cmd/run_one.py + cmd/rerun.py + cmd/reset.py

**Files:**
- Create: `scripts/simulate_reports/cmd/run_one.py`, `cmd/rerun.py`, `cmd/reset.py`

- [ ] **Step 1: 写 `cmd/run_one.py`**

```python
"""python -m scripts.simulate_reports run-one <SID>"""
from datetime import timedelta
from .. import config


def run(argv):
    if not argv:
        print("Usage: run-one <SID>"); return 2
    sid = argv[0]
    # Lazy imports
    from ..scenarios import SCENARIOS
    if sid not in SCENARIOS:
        print(f"Unknown SID: {sid}"); return 2
    sc = SCENARIOS[sid]
    target_date = sc.logical_date
    day_before = target_date - timedelta(days=1)

    from ..checkpoint import restore_before
    restored = restore_before(target_date)
    if restored is None:
        print("No checkpoint available; run full 'run' first or run from scratch.")
        return 2
    print(f"Restored checkpoint @ {restored} (target {target_date})")

    # Replay days between restored+1 and day_before using timeline,
    # then run the target day's scenarios.
    from ..timeline import TIMELINE
    from .run import run as run_full  # reuse partial of run logic
    # Simplest approach: monkey-patch TIMELINE_START/END to [restored+1, target]
    orig_start, orig_end = config.TIMELINE_START, config.TIMELINE_END
    config.TIMELINE_START = restored + timedelta(days=1)
    config.TIMELINE_END = target_date
    try:
        run_full([])
    finally:
        config.TIMELINE_START = orig_start
        config.TIMELINE_END = orig_end
    return 0
```

- [ ] **Step 2: 写 `cmd/rerun.py`**

```python
"""python -m scripts.simulate_reports rerun-after-fix
Re-run full timeline but skip prepare (keep data/sim/simulation.db)."""
from .. import config
import shutil


def run(argv):
    # Restart from scratch of timeline but keep the prepared DB baseline
    shutil.rmtree(config.SCENARIOS_DIR, ignore_errors=True)
    shutil.rmtree(config.CHECKPOINT_DIR, ignore_errors=True)
    # Re-clone baseline? No — user wants to keep fix applied to business code,
    # but DB should be fresh. Easiest: re-run prepare.
    from .prepare import run as prepare_run
    from .run import run as run_run
    prepare_run([])
    return run_run([])
```

- [ ] **Step 3: 写 `cmd/reset.py`**

```python
"""python -m scripts.simulate_reports reset — wipe all sim artifacts."""
import shutil
from .. import config


def run(argv):
    shutil.rmtree(config.SIM_DATA_DIR, ignore_errors=True)
    shutil.rmtree(config.SCENARIOS_DIR, ignore_errors=True)
    for p in (config.INDEX_HTML, config.ISSUES_MD):
        if p.exists():
            p.unlink()
    print("Reset complete.")
    return 0
```

- [ ] **Step 4: Commit**

```bash
git add scripts/simulate_reports/cmd/run_one.py scripts/simulate_reports/cmd/rerun.py scripts/simulate_reports/cmd/reset.py
git commit -m "feat(sim): run-one + rerun-after-fix + reset commands"
```

---

## Phase 6 — Analysis UI

### Task 21: cmd/index.py + index_page.py

**Files:**
- Create: `scripts/simulate_reports/index_page.py`, `scripts/simulate_reports/cmd/index.py`

- [ ] **Step 1: 写 `index_page.py`**

```python
"""Build reports/index.html from all scenario manifests."""
import html as _html
import json
from pathlib import Path
from . import config


def _load_all_manifests():
    out = []
    if not config.SCENARIOS_DIR.exists():
        return out
    for sd in sorted(config.SCENARIOS_DIR.iterdir()):
        m = sd / "manifest.json"
        if m.exists():
            try:
                out.append((sd, json.loads(m.read_text(encoding="utf-8"))))
            except Exception:
                continue
    return out


_BADGE = {"PASS": "#2ecc71", "WARN": "#f39c12", "FAIL": "#e74c3c"}


def build_index():
    rows = _load_all_manifests()
    n_pass = sum(1 for _, m in rows if m.get("verdict") == "PASS")
    n_warn = sum(1 for _, m in rows if m.get("verdict") == "WARN")
    n_fail = sum(1 for _, m in rows if m.get("verdict") == "FAIL")
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Report Simulation Index</title>",
        "<style>",
        "body{font-family:-apple-system,Segoe UI,sans-serif;background:#f5f5f7;margin:0;padding:24px}",
        ".summary{font-size:18px;margin-bottom:16px}",
        ".card{background:#fff;border-radius:8px;padding:16px;margin:12px 0;",
        "box-shadow:0 1px 3px rgba(0,0,0,.08)}",
        ".badge{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-size:12px;margin-left:8px}",
        ".meta{color:#666;font-size:13px}",
        "details{margin-top:8px}",
        "pre{background:#f7f7f7;padding:8px;border-radius:4px;overflow-x:auto;font-size:12px}",
        "a{color:#0366d6}",
        ".filter{margin:0 0 20px}",
        ".filter label{margin-right:12px;font-size:13px}",
        "</style></head><body>",
        f"<h1>Report Simulation Index</h1>",
        f"<div class='summary'>✅ {n_pass} PASS &nbsp; ⚠️ {n_warn} WARN &nbsp; ❌ {n_fail} FAIL &nbsp; — 共 {len(rows)} 场景</div>",
        "<div class='filter'>",
        "<label><input type='checkbox' class='vf' value='PASS' checked>PASS</label>",
        "<label><input type='checkbox' class='vf' value='WARN' checked>WARN</label>",
        "<label><input type='checkbox' class='vf' value='FAIL' checked>FAIL</label>",
        "<label>tier: <select id='tf'><option>all</option><option>daily</option><option>weekly</option><option>monthly</option></select></label>",
        "</div>",
    ]
    for sd, m in rows:
        rel = sd.relative_to(config.REPORT_ROOT).as_posix()
        verdict = m.get("verdict", "?")
        badge_color = _BADGE.get(verdict, "#999")
        artifacts_links = "".join(
            f"<a href='{rel}/{_html.escape(a)}'>{_html.escape(a)}</a> "
            for a in m.get("artifacts", [])
        )
        debug_link = f"<a href='{rel}/debug/'>debug/</a>"
        emails_link = f"<a href='{rel}/emails/'>emails/</a>"
        exp_json = json.dumps(m.get("expected", {}), ensure_ascii=False, indent=2)
        act_json = json.dumps(m.get("actual", {}), ensure_ascii=False, indent=2)
        failures = "<ul>" + "".join(
            f"<li>{_html.escape(f)}</li>" for f in m.get("failures", [])
        ) + "</ul>" if m.get("failures") else ""
        parts.append(
            f"<div class='card' data-verdict='{verdict}' data-tier='{m.get('tier','?')}'>"
            f"<strong>{_html.escape(m.get('scenario_id','?'))}</strong>"
            f"<span class='badge' style='background:{badge_color}'>{verdict}</span>"
            f"<div class='meta'>{_html.escape(str(m.get('logical_date','?')))}"
            f" · {_html.escape(m.get('tier','?'))}"
            f" · {_html.escape(m.get('description',''))}</div>"
            f"<div class='meta'>Artifacts: {artifacts_links} {debug_link} {emails_link}</div>"
            f"{failures}"
            f"<details><summary>expected vs actual</summary>"
            f"<div style='display:flex;gap:16px'>"
            f"<div style='flex:1'><h4>expected</h4><pre>{_html.escape(exp_json)}</pre></div>"
            f"<div style='flex:1'><h4>actual</h4><pre>{_html.escape(act_json)}</pre></div>"
            f"</div></details>"
            "</div>"
        )
    parts.append("""
<script>
const vfs=[...document.querySelectorAll('.vf')];
const tf=document.getElementById('tf');
function filter(){
  const allowed=new Set(vfs.filter(c=>c.checked).map(c=>c.value));
  const tier=tf.value;
  document.querySelectorAll('.card').forEach(c=>{
    const v=c.dataset.verdict, t=c.dataset.tier;
    c.style.display=(allowed.has(v)&&(tier==='all'||t===tier))?'':'none';
  });
}
vfs.forEach(c=>c.onchange=filter); tf.onchange=filter;
</script>
</body></html>""")
    config.INDEX_HTML.write_text("\n".join(parts), encoding="utf-8")
    return config.INDEX_HTML
```

- [ ] **Step 2: 写 `cmd/index.py`**

```python
"""python -m scripts.simulate_reports index"""
from ..index_page import build_index


def run(argv):
    p = build_index()
    print(f"index.html → {p}")
    return 0
```

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/index_page.py scripts/simulate_reports/cmd/index.py
git commit -m "feat(sim): index.html with verdict badges + filters + expected/actual"
```

---

### Task 22: cmd/show.py + cmd/diff.py

**Files:**
- Create: `scripts/simulate_reports/cmd/show.py`, `scripts/simulate_reports/cmd/diff.py`

- [ ] **Step 1: 写 `cmd/show.py`**

```python
"""python -m scripts.simulate_reports show <SID>"""
import json
from .. import config
from ..manifest import read_manifest


def _find_dir(sid):
    for sd in config.SCENARIOS_DIR.iterdir():
        if sd.is_dir() and sd.name.startswith(f"{sid}-"):
            return sd
    return None


def run(argv):
    if not argv:
        print("Usage: show <SID>"); return 2
    sid = argv[0]
    sd = _find_dir(sid)
    if not sd:
        print(f"Scenario dir not found for {sid}"); return 2
    m = read_manifest(sd)
    if not m:
        print(f"No manifest in {sd}"); return 2
    print(f"=== {sid} ===")
    print(json.dumps(m, ensure_ascii=False, indent=2))
    # List debug files
    dbg = sd / "debug"
    if dbg.exists():
        print("\ndebug/:")
        for p in sorted(dbg.iterdir()):
            print(f"  {p.name} ({p.stat().st_size} bytes)")
    return 0
```

- [ ] **Step 2: 写 `cmd/diff.py`**

```python
"""python -m scripts.simulate_reports diff <SID1> <SID2>"""
import json
from pathlib import Path
from .. import config
from .show import _find_dir


def _load(sid):
    sd = _find_dir(sid)
    if not sd: return None, None
    m = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))
    return sd, m


def run(argv):
    if len(argv) < 2:
        print("Usage: diff <SID1> <SID2>"); return 2
    sid1, sid2 = argv[0], argv[1]
    d1, m1 = _load(sid1); d2, m2 = _load(sid2)
    if not m1 or not m2:
        print("One or both scenarios missing"); return 2
    print(f"=== {sid1} vs {sid2} ===")
    for key in ("tier","report_mode","status","report_phase","is_partial","email_count"):
        v1 = m1.get("actual", {}).get(key)
        v2 = m2.get("actual", {}).get(key)
        mark = "  " if v1 == v2 else "≠ "
        print(f"  {mark}{key:18s}  {v1!r:30s}  {v2!r}")
    # Analytics high-level keys
    for sd, m in [(d1, m1), (d2, m2)]:
        ap = sd / "debug" / "analytics_tree.json"
        if ap.exists():
            tree = json.loads(ap.read_text(encoding="utf-8"))
            print(f"\n  {m['scenario_id']} analytics keys: {sorted(tree.keys())[:12]}")
    return 0
```

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/cmd/show.py scripts/simulate_reports/cmd/diff.py
git commit -m "feat(sim): show + diff CLI commands"
```

---

### Task 23: cmd/verify.py + issues_page.py

**Files:**
- Create: `scripts/simulate_reports/issues_page.py`, `scripts/simulate_reports/cmd/verify.py`

- [ ] **Step 1: 写 `issues_page.py`**

```python
"""Build issues.md from all manifests with FAIL/WARN."""
import json
from . import config


def build_issues() -> str:
    rows = []
    for sd in sorted(config.SCENARIOS_DIR.iterdir()):
        mp = sd / "manifest.json"
        if not mp.exists(): continue
        try:
            rows.append((sd, json.loads(mp.read_text(encoding="utf-8"))))
        except Exception: continue
    fails = [(sd, m) for sd, m in rows if m.get("verdict") == "FAIL"]
    warns = [(sd, m) for sd, m in rows if m.get("verdict") == "WARN"]
    if not fails and not warns:
        out = "# Simulation Issues\n\n✅ All scenarios PASS.\n"
    else:
        out = "# Simulation Issues\n\n"
        if fails:
            out += f"## ❌ FAIL ({len(fails)})\n\n"
            for sd, m in fails:
                out += f"### {m['scenario_id']} {m.get('description','')} ({m['logical_date']})\n\n"
                for f in m.get("failures", []):
                    out += f"- {f}\n"
                out += f"- 重现：`python -m scripts.simulate_reports run-one {m['scenario_id']}`\n\n"
        if warns:
            out += f"## ⚠️ WARN ({len(warns)})\n\n"
            for sd, m in warns:
                out += f"### {m['scenario_id']} ({m['logical_date']})\n\n"
                for w in m.get("warnings", []):
                    out += f"- {w}\n"
                out += "\n"
    config.ISSUES_MD.write_text(out, encoding="utf-8")
    return out
```

- [ ] **Step 2: 写 `cmd/verify.py`**

```python
"""python -m scripts.simulate_reports verify | issues"""
import json
from .. import config
from ..issues_page import build_issues


def run(argv):
    total = pass_n = warn_n = fail_n = 0
    for sd in sorted(config.SCENARIOS_DIR.iterdir()):
        mp = sd / "manifest.json"
        if not mp.exists(): continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        total += 1
        v = m.get("verdict", "?")
        tag = {"PASS": "\033[32m✅", "WARN": "\033[33m⚠️", "FAIL": "\033[31m❌"}.get(v, "?")
        print(f"{tag} {m['scenario_id']:8s} {v:5s}\033[0m  {m.get('description','')}")
        if v == "PASS": pass_n += 1
        elif v == "WARN": warn_n += 1
        elif v == "FAIL": fail_n += 1
        for f in m.get("failures", []):
            print(f"      · {f}")
    print(f"\n总计 {total} · PASS {pass_n} · WARN {warn_n} · FAIL {fail_n}")
    build_issues()
    print(f"issues.md → {config.ISSUES_MD}")
    return 0 if fail_n == 0 else 1
```

- [ ] **Step 3: Commit**

```bash
git add scripts/simulate_reports/issues_page.py scripts/simulate_reports/cmd/verify.py
git commit -m "feat(sim): verify + issues.md generation"
```

---

### Task 24: README + 第一次完整运行

**Files:**
- Create: `scripts/simulate_reports/README.md`

- [ ] **Step 1: 写 `README.md`**

```markdown
# scripts/simulate_reports

报告系统的离线模拟器。以不改业务代码为前提，生成日/周/月报的所有典型形态产物，并附带逐场景 debug 产物 + 期望 vs 实际对照，用于分析与改代码后复验。

## 快速开始

```bash
# 1. 首次：克隆桌面基线 DB + 重分布 scraped_at + 回填 labels
uv run python -m scripts.simulate_reports prepare

# 2. 跑完整 42 天时间轴（约 10~20 分钟）
uv run python -m scripts.simulate_reports run

# 3. 生成顶层 index.html
uv run python -m scripts.simulate_reports index

# 4. 查 fail 列表 + issues.md
uv run python -m scripts.simulate_reports verify

# 5. 改业务代码后，只重跑一个场景
uv run python -m scripts.simulate_reports run-one S07

# 6. 或全量重跑（保留已 prepare 的 DB 基础）
uv run python -m scripts.simulate_reports rerun-after-fix

# 7. 清零一切
uv run python -m scripts.simulate_reports reset
```

## 产物位置

- 顶层索引：`C:\Users\leo\Desktop\报告\reports\index.html`
- 每场景：`C:\Users\leo\Desktop\报告\reports\scenarios\S01-2026-03-20-.../`
  - `manifest.json` — 期望/实际/verdict
  - `daily.html` / `daily.xlsx` / `snapshot.json` / `analytics.json`
  - `emails/` — 被抽出的邮件 payload
  - `debug/` — 9 个诊断文件

## 隔离保证

见 spec `docs/superpowers/specs/2026-04-17-report-simulation-design.md` 第 9 节。核心：
- `qbu_crawler/` 业务代码零改动
- 工作 DB 在 `data/sim/simulation.db`（已 gitignore）
- 桌面基线 DB 只读
- 不启任何业务后台线程
```

- [ ] **Step 2: 第一次跑完整流水**

```bash
uv run python -m scripts.simulate_reports reset
uv run python -m scripts.simulate_reports prepare
uv run python -m scripts.simulate_reports run
uv run python -m scripts.simulate_reports index
uv run python -m scripts.simulate_reports verify
```

**预期**：
- 所有 27+ 场景产出目录
- `index.html` 打开可见卡片
- `verify` 输出每场景 PASS/WARN/FAIL；有 FAIL 是正常的（时间轴参数可能要调）

- [ ] **Step 3: 若有 FAIL，迭代**

不是 bug fix —— 只调整：
- 时间轴日期（如 silence_window 阈值实测后调整 R4 位置）
- 事件注入的 count/fraction
- scenario 的 expected 字段放宽（例如 lifecycle_states_must_include 改为软期望）

**禁止**：改业务代码（`qbu_crawler/**`）。如确认是业务 bug，单独开 PR 处理。

- [ ] **Step 4: 所有 PASS / 合理 FAIL 后 Commit**

```bash
git add -A
git commit -m "docs(sim): README + first full run green baseline"
```

---

## Phase 7 — Polish

### Task 25: 最终 verify + PR 准备

- [ ] **Step 1: 确认业务代码未改**

```bash
git diff master -- qbu_crawler/
```
预期：空输出。若有差异，回滚（这违反 spec 硬约束）。

- [ ] **Step 2: 跑全测试**

```bash
uv run pytest tests/simulate_reports/ -v
```
预期：全绿。

- [ ] **Step 3: 最终 verify**

```bash
uv run python -m scripts.simulate_reports verify
```

- [ ] **Step 4: 更新 CLAUDE.md 加入模拟器入口说明**

在 CLAUDE.md "常用命令" 节后追加：

```markdown
## 报告模拟器（离线，不改业务代码）

详见 `scripts/simulate_reports/README.md`。

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -m scripts.simulate_reports run
uv run python -m scripts.simulate_reports verify
```
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: reference simulator in CLAUDE.md"
```

---

## 完成标志

- [ ] `git diff master -- qbu_crawler/` 为空
- [ ] `uv run pytest tests/simulate_reports/` 全绿
- [ ] `reports/scenarios/` 下 ≥ 27 个场景目录，每个含 `manifest.json`
- [ ] `reports/index.html` 可在浏览器打开、徽章+过滤正常
- [ ] `verify` 命令输出列表 + 生成 `issues.md`
- [ ] S01 manifest.actual.is_partial = true
- [ ] S07 manifest.actual.report_mode = change
- [ ] S08a/b/c emails/ 非空；S09a/b/c emails/ 为空
- [ ] M1 目录含 monthly.xlsx 且至少 6 sheet
- [ ] 至少有一个 scenario 触发了 needs_attention 状态

## 风险回顾

1. **WorkflowWorker._advance_run 私有 API 依赖**：若运行时报 AttributeError 提示未初始化字段，读源码补全 `__init__` 必要字段，**不要改业务 `__init__`**
2. **freezegun 不覆盖 DrissionPage 等 C 扩展**：本计划全流程不涉及爬虫 + DrissionPage，只动 SQLite 和 Python 报告生成，freezegun 足够
3. **LLM 真调失败**：月报 executive 允许降级，M1 仍 PASS
4. **时间窗口边界**：daily data_since/until 用 `[00:00:00, 次日 00:00:00)` 半开区间，与业务约定一致
5. **场景过多导致 run 时间长**：若单次 run 超 30 分钟，在 Task 24 Step 3 阶段压缩 S02 变体数量（只保留每 2 天 1 个）
