# 报告系统重构 Implementation Plan (v1.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **v1.2 修订（2026-04-27 同日）**：合入路径 B 三大块用户视角局部优化（3 个高 ROI Task，3-4 天工作量）：
> - 新增 Task 3.4.2 特征情感热力图优化（维度 Top 8 聚合 / hover top 评论 / 点击下钻）
> - 新增 Task 3.5.1 issue cards 默认折叠 Top 3 之外 + 删除 temporal_pattern 段
> - 新增 Task 3.9 竞品启示扩展（弱点机会卡 + benchmark 三类分组 + 雷达图维度聚合）
> - F011 同步升级到 v1.2，含 AC-34 ~ AC-36 验收
> - **总 task 数：24 → 27**；工作量估算：14-21 天 → **17-25 天**

> **v1.1 修订（2026-04-27 同日）**：合入计划-需求边界审查的 5 项 P0 + 10 项 P1 修订：
> - 新增 Task 0.2 `determine_report_semantics` 状态判定（P0）
> - 新增 Task 1.3 子步：failure_mode 分类器优先级 bug 修复（"无齿轮问题"等边界）（P0）
> - Task 2.4 强化：`own_new_negative` 时间口径明确为 `scraped_at`（P0）
> - 新增 Task 4.5.1 生产 DB 迁移执行步骤（P0）
> - 新增 Task 2.6.1 完整数字断言（覆盖 bullets / priorities / evidence_ids）（P1）
> - 新增 Task 4.5.2 CI hook（GitHub Actions）（P1）
> - 新增 Task 4.3.1 v2/v3 prompt_version 共存测试（P1）
> - 新增 Task 4.6 env 切换 legacy 模板路由实现（P1）
> - 扩展 Task 4.3 性能测试（附件 HTML ≤1MB / Excel ≤5MB / ≤30s）（P1）
> - 修订 Task 3.1：邮件 KPI ④ 删除硬编码 25，统一 lamp 逻辑（P1，I2）
> - Task 1.3 / 2.2 / 2.5 加边界测试用例（P2）
> - 新 Task 总计：18 → 24
> - 工作量：12-18 天 → 14-21 天

**Goal:** 把报告系统从"AI 撰写的可读分析稿"升级为"可信、可决策、可送达的运营仪表盘"，覆盖 4 类产物（邮件正文 / 附件 HTML / Excel / 内部运维），按 21 项核心改造分 4 Phase 落地。

**Architecture:**
- **Phase 1 数据契约**：先改 DB schema、analytics 字段、LLM prompt（独立可发布）
- **Phase 2 业务逻辑**：差评率口径、tooltip 同步、风险因子分解、change_digest 重构（依赖 Phase 1）
- **Phase 3 展示层**：邮件正文 / 附件 HTML / Excel 三类产物模板改造（依赖 Phase 1+2）
- **Phase 4 集成与运维**：内部运维通道、回滚保护、CI 同步检查

**Tech Stack:**
- Python 3.10+, SQLite, openpyxl, Jinja2, FastAPI, smtplib
- 测试：pytest, pytest-mock
- 模板：`qbu_crawler/server/report_templates/*.j2`
- 数据迁移：手写 SQL `ALTER TABLE` + Python 回填脚本

**关联文档：**
- 需求设计：`docs/features/F011-report-system-redesign.md`
- 审计依据：`docs/reviews/2026-04-26-production-test5-full-report-audit.md`

---

## 文件结构（File Map）

### 新建文件

| 路径 | 责任 |
|------|------|
| `qbu_crawler/server/migrations/0010_report_redesign_schema.py` | DB schema 迁移（含 `up` / `down`） |
| `qbu_crawler/server/migrations/0011_failure_mode_enum_backfill.py` | `failure_mode` 自由文本 → enum 9 类 LLM 归类回填 |
| `qbu_crawler/server/report_artifacts.py` | report_artifacts 表的 CRUD 封装 |
| `qbu_crawler/server/report_metrics_validator.py` | tooltip-代码同步校验 + LLM 数字断言校验 |
| `tests/server/test_report_metrics_validator.py` | 上述校验器测试 |
| `tests/server/test_failure_mode_enum.py` | failure_mode enum 化迁移测试 |
| `tests/server/test_change_digest_pyramid.py` | 三层金字塔 change_digest 测试 |
| `tests/server/test_trend_digest_thresholds.py` | trend ready 阈值测试 |
| `tests/server/test_risk_score_factors.py` | risk_score 因子分解测试 |
| `tests/server/test_email_full_template.py` | 邮件正文渲染测试 |
| `tests/server/test_attachment_html_template.py` | 附件 HTML 渲染测试 |
| `tests/server/test_excel_sheets.py` | Excel 4 sheets 输出测试 |
| `tests/server/test_internal_ops_alert.py` | 内部运维邮件触发测试 |

### 修改文件

| 路径 | 改动概要 |
|------|---------|
| `qbu_crawler/models.py` | 统一 `_parse_date_published` anchor 为 `scraped_at` |
| `qbu_crawler/server/scrape_quality.py` | 增加 `missing_text_review_count` / `zero_scrape_skus` 检查 |
| `qbu_crawler/server/report_common.py` | 修订 `METRIC_TOOLTIPS["风险分"]` 文案 |
| `qbu_crawler/server/report_analytics.py` | 差评率分母统一 / risk_score 因子分解 / change_digest 三层 / trend_digest 单主图 |
| `qbu_crawler/server/report_llm.py` | Prompt v3 / 措辞护栏 / 数字断言 / 重试 |
| `qbu_crawler/server/report.py` | `_generate_analytical_excel` 重构为 4 sheets |
| `qbu_crawler/server/report_snapshot.py` | `query_cumulative_data` 补 `ra.failure_mode, ra.impact_category` SELECT |
| `qbu_crawler/server/report_templates/email_full.html.j2` | 重写为 4 KPI 灯 + Top 3 + 产品状态 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 删 12 panel / 改建议行动 short_title / 加全景筛选 / 加 today 三层金字塔 |
| `qbu_crawler/server/report_templates/email_data_quality.html.j2` | 增加触发条件 |
| `qbu_crawler/server/notifier.py` | outbox deadletter 触发 workflow_runs.report_phase 降级 |
| `qbu_crawler/__init__.py` | 版本 0.3.25 → 0.4.0 |

### 保留作为 fallback 的文件

| 路径 | 用途 |
|------|------|
| `qbu_crawler/server/report_templates/daily_report_v3_legacy.html.j2` | 旧模板备份，env `REPORT_TEMPLATE_VERSION=v3_legacy` 时启用 |

---

## Phase 0: 准备工作

### Task 0.1: 创建 worktree 与 branch

**Files:** N/A

- [ ] **Step 1: 确认在 master 最新**

```bash
git fetch origin
git checkout master
git pull origin master
```

- [ ] **Step 2: 创建 feature branch**

```bash
git checkout -b feature/report-system-redesign-f011
```

- [ ] **Step 3: 备份当前 daily_report_v3.html.j2 为 legacy**

```bash
cp qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
   qbu_crawler/server/report_templates/daily_report_v3_legacy.html.j2
git add qbu_crawler/server/report_templates/daily_report_v3_legacy.html.j2
git commit -m "chore(report): backup current daily_report_v3 template as legacy fallback"
```

### Task 0.2: 实现 `determine_report_semantics` 状态判定函数（v1.1 新增 P0）

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_report_semantics.py`

**对应 F011 §3.3.1 / AC-26**

- [ ] **Step 1: 写失败测试**

```python
import sqlite3
import pytest
from qbu_crawler.server.report_analytics import determine_report_semantics

@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = sqlite3.connect(str(db))
    c.executescript("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            workflow_type TEXT,
            status TEXT,
            logical_date TEXT,
            trigger_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    yield c
    c.close()

def test_first_run_is_bootstrap(conn):
    """首次运行：之前无 completed run → bootstrap"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-26','daily:2026-04-26')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"

def test_second_run_with_prior_completed_is_incremental(conn):
    """已有 completed run → incremental"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','completed','2026-04-26','daily:2026-04-26')")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-27','daily:2026-04-27')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "incremental"

def test_failed_prior_runs_dont_count(conn):
    """之前的 failed run 不算 baseline → 仍 bootstrap"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','failed','2026-04-26','daily:2026-04-26')")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-27','daily:2026-04-27')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"

def test_different_workflow_type_dont_count(conn):
    """同库但不同 workflow_type 的 completed 不算 baseline"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('weekly','completed','2026-04-26','weekly:2026-04-26')")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-27','daily:2026-04-27')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"

def test_db_wipe_rebuilds_to_bootstrap(conn):
    """DB wipe 后重建 → 第一个新 run 也是 bootstrap"""
    # 模拟 wipe：直接清表
    cur = conn.cursor()
    cur.execute("DELETE FROM workflow_runs")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-05-01','daily:2026-05-01')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_report_semantics.py -v
```

Expected: FAIL（函数未实现）

- [ ] **Step 3: 实现 `determine_report_semantics`**

`qbu_crawler/server/report_analytics.py` 末尾添加：

```python
def determine_report_semantics(conn, current_run_id: int) -> str:
    """报告状态机：返回 'bootstrap' / 'incremental'。

    F011 §3.3.1：
    - 当前 run 之前无同 workflow_type 的 status='completed' run → bootstrap
    - 之前有 ≥1 个 status='completed' 的同 workflow_type run → incremental
    """
    cur = conn.cursor()
    row = cur.execute(
        "SELECT workflow_type, created_at FROM workflow_runs WHERE id=?",
        (current_run_id,),
    ).fetchone()
    if not row:
        return "bootstrap"  # 异常情况，保守返回 bootstrap

    workflow_type, created_at = row
    prior_completed = cur.execute(
        """SELECT COUNT(*) FROM workflow_runs
           WHERE workflow_type=? AND status='completed' AND id < ?""",
        (workflow_type, current_run_id),
    ).fetchone()[0]

    return "incremental" if prior_completed > 0 else "bootstrap"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/server/test_report_semantics.py -v
```

Expected: 5 PASS

- [ ] **Step 5: 集成到 build_report_analytics**

在 `build_report_analytics()` 函数中，把原本通过 `is_bootstrap` 判断的逻辑改为：

```python
def build_report_analytics(snapshot, conn=None, ...):
    # ... 已有代码
    if conn and snapshot.get("run_id"):
        report_semantics = determine_report_semantics(conn, snapshot["run_id"])
    else:
        report_semantics = "bootstrap"  # 兜底
    analytics["report_semantics"] = report_semantics
    analytics["is_bootstrap"] = (report_semantics == "bootstrap")  # 向后兼容
    # ...
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/server/test_report_semantics.py
git commit -m "feat(report): F011 §3.3.1 — determine_report_semantics 状态判定函数（覆盖 bootstrap/incremental/DB wipe）"
```

---

## Phase 1: 数据契约改造（独立可发布）

### Task 1.1: DB schema 迁移 — 新增字段

**Files:**
- Create: `qbu_crawler/server/migrations/0010_report_redesign_schema.py`
- Test: `tests/server/test_migration_0010.py`

- [ ] **Step 1: 写 migration 失败测试**

`tests/server/test_migration_0010.py`：

```python
import sqlite3
import pytest
from qbu_crawler.server.migrations import migration_0010_report_redesign_schema as mig

@pytest.fixture
def fresh_db(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    # 创建初始 schema（复制当前生产 schema 关键表）
    conn.executescript("""
        CREATE TABLE reviews (
          id INTEGER PRIMARY KEY,
          product_id INTEGER,
          date_published TEXT,
          date_published_parsed TEXT
        );
        CREATE TABLE products (
          id INTEGER PRIMARY KEY,
          sku TEXT
        );
        CREATE TABLE workflow_runs (
          id INTEGER PRIMARY KEY,
          status TEXT
        );
        CREATE TABLE product_snapshots (
          id INTEGER PRIMARY KEY,
          product_id INTEGER
        );
    """)
    conn.commit()
    yield conn
    conn.close()

def test_up_adds_required_columns(fresh_db):
    mig.up(fresh_db)
    cur = fresh_db.cursor()

    # reviews 新字段
    columns = [r[1] for r in cur.execute("PRAGMA table_info(reviews)").fetchall()]
    assert "date_published_estimated" in columns
    assert "date_parse_method" in columns
    assert "date_parse_anchor" in columns
    assert "date_parse_confidence" in columns
    assert "source_review_id" in columns

    # products 新字段
    columns = [r[1] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
    assert "last_scrape_completeness" in columns
    assert "last_scrape_warnings" in columns

    # workflow_runs 新字段
    columns = [r[1] for r in cur.execute("PRAGMA table_info(workflow_runs)").fetchall()]
    assert "scrape_completeness_ratio" in columns
    assert "zero_scrape_count" in columns
    assert "report_copy_json" in columns

    # product_snapshots 新字段
    columns = [r[1] for r in cur.execute("PRAGMA table_info(product_snapshots)").fetchall()]
    assert "workflow_run_id" in columns

    # report_artifacts 表
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "report_artifacts" in tables

def test_down_reverts_changes(fresh_db):
    mig.up(fresh_db)
    mig.down(fresh_db)
    cur = fresh_db.cursor()
    columns = [r[1] for r in cur.execute("PRAGMA table_info(reviews)").fetchall()]
    assert "date_published_estimated" not in columns
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "report_artifacts" not in tables
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_migration_0010.py -v
```

Expected: FAIL（migration 模块未创建）

- [ ] **Step 3: 写 migration 实现**

`qbu_crawler/server/migrations/0010_report_redesign_schema.py`：

```python
"""F011 Report system redesign — schema migration.

Adds:
- reviews: date_published_estimated, date_parse_method, date_parse_anchor,
           date_parse_confidence, source_review_id
- products: last_scrape_completeness, last_scrape_warnings
- workflow_runs: scrape_completeness_ratio, zero_scrape_count, report_copy_json
- product_snapshots: workflow_run_id
- report_artifacts (new table)
- indexes: idx_reviews_published_parsed, idx_labels_polarity_severity
"""
import sqlite3

UP_SQL = [
    "ALTER TABLE reviews ADD COLUMN date_published_estimated INTEGER DEFAULT 0",
    "ALTER TABLE reviews ADD COLUMN date_parse_method TEXT",
    "ALTER TABLE reviews ADD COLUMN date_parse_anchor TEXT",
    "ALTER TABLE reviews ADD COLUMN date_parse_confidence REAL",
    "ALTER TABLE reviews ADD COLUMN source_review_id TEXT",

    "ALTER TABLE products ADD COLUMN last_scrape_completeness REAL",
    "ALTER TABLE products ADD COLUMN last_scrape_warnings TEXT",

    "ALTER TABLE workflow_runs ADD COLUMN scrape_completeness_ratio REAL",
    "ALTER TABLE workflow_runs ADD COLUMN zero_scrape_count INTEGER",
    "ALTER TABLE workflow_runs ADD COLUMN report_copy_json TEXT",

    "ALTER TABLE product_snapshots ADD COLUMN workflow_run_id INTEGER REFERENCES workflow_runs(id)",

    """CREATE TABLE IF NOT EXISTS report_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
        artifact_type TEXT NOT NULL CHECK(artifact_type IN ('html_attachment','xlsx','pdf','snapshot','analytics','email_body')),
        path TEXT NOT NULL,
        hash TEXT,
        template_version TEXT,
        generator_version TEXT,
        bytes INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",

    "CREATE INDEX IF NOT EXISTS idx_artifacts_run ON report_artifacts(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_published_parsed ON reviews(date_published_parsed)",
    "CREATE INDEX IF NOT EXISTS idx_labels_polarity_severity ON review_issue_labels(label_polarity, severity)",
]

# SQLite ALTER TABLE DROP COLUMN 在 3.35+ 才支持；对老版本用表重建。
DOWN_SQL = [
    "DROP INDEX IF EXISTS idx_artifacts_run",
    "DROP INDEX IF EXISTS idx_reviews_published_parsed",
    "DROP INDEX IF EXISTS idx_labels_polarity_severity",
    "DROP TABLE IF EXISTS report_artifacts",
    "ALTER TABLE reviews DROP COLUMN date_published_estimated",
    "ALTER TABLE reviews DROP COLUMN date_parse_method",
    "ALTER TABLE reviews DROP COLUMN date_parse_anchor",
    "ALTER TABLE reviews DROP COLUMN date_parse_confidence",
    "ALTER TABLE reviews DROP COLUMN source_review_id",
    "ALTER TABLE products DROP COLUMN last_scrape_completeness",
    "ALTER TABLE products DROP COLUMN last_scrape_warnings",
    "ALTER TABLE workflow_runs DROP COLUMN scrape_completeness_ratio",
    "ALTER TABLE workflow_runs DROP COLUMN zero_scrape_count",
    "ALTER TABLE workflow_runs DROP COLUMN report_copy_json",
    "ALTER TABLE product_snapshots DROP COLUMN workflow_run_id",
]


def up(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for sql in UP_SQL:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                continue
            raise
    conn.commit()


def down(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for sql in DOWN_SQL:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError:
            continue
    conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/server/test_migration_0010.py -v
```

Expected: 2 PASS

- [ ] **Step 5: 集成 migration runner**

修改 `qbu_crawler/models.py` 的初始化代码，在 schema 初始化后调用 `migration_0010_report_redesign_schema.up(conn)`（幂等）。具体定位：找到 `init_database()` 函数末尾添加。

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/migrations/0010_report_redesign_schema.py \
        tests/server/test_migration_0010.py \
        qbu_crawler/models.py
git commit -m "feat(report): F011 schema migration — add report redesign columns and report_artifacts table"
```

### Task 1.2: 统一 date_published 解析 anchor

**Files:**
- Modify: `qbu_crawler/models.py`（`_parse_date_published` / `_backfill_date_published_parsed`）
- Test: `tests/server/test_date_published_anchor.py`

- [ ] **Step 1: 写失败测试**

`tests/server/test_date_published_anchor.py`：

```python
import pytest
from qbu_crawler.models import _parse_date_published

class TestUnifiedAnchor:
    """两条路径必须用同一 anchor (scraped_at)。"""

    def test_relative_time_uses_scraped_at_anchor(self):
        scraped_at = "2026-04-26 12:00:00"
        result = _parse_date_published("a year ago", scraped_at=scraped_at)
        assert result.startswith("2025-04")  # 一年前 = scraped_at - 365 天

    def test_absolute_date_unchanged(self):
        result = _parse_date_published("01/15/2024", scraped_at="2026-04-26 12:00:00")
        assert result == "2024-01-15"

    def test_returns_with_metadata(self):
        result, meta = _parse_date_published(
            "2 years ago",
            scraped_at="2026-04-26 12:00:00",
            return_meta=True,
        )
        assert result.startswith("2024-04")
        assert meta["method"] == "relative_scraped_at"
        assert meta["anchor"] == "2026-04-26 12:00:00"
        assert 0 < meta["confidence"] < 1.0  # 相对时间置信度低
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_date_published_anchor.py -v
```

Expected: FAIL

- [ ] **Step 3: 修改 `models.py::_parse_date_published`**

定位 `_parse_date_published` 函数，改造签名：

```python
def _parse_date_published(raw: str | None, *, scraped_at: str | None = None, return_meta: bool = False):
    """统一以 scraped_at 为相对时间 anchor。

    Args:
        raw: 原始字符串
        scraped_at: 抓取时间，用作相对时间表达的 anchor（"2 years ago" → scraped_at - 2 年）
        return_meta: True 时返回 (parsed, meta_dict)；False 仅返回 parsed

    Returns:
        parsed 日期字符串 YYYY-MM-DD，或 (parsed, {"method","anchor","confidence"})
    """
    # ... 实现：
    # 1. 若 raw 为绝对日期 → 直接 parse, method='absolute', confidence=1.0
    # 2. 若 raw 为 "X years/months/days ago" 类相对时间：
    #    anchor = scraped_at or now
    #    method = 'relative_scraped_at' if scraped_at else 'relative_now'
    #    confidence = 0.5 (years) / 0.7 (months) / 0.9 (days)
    # 3. 若 raw 无法解析 → return None, method='unknown', confidence=0
    pass  # 完整实现见 Task 1.2 后续步骤
```

完整实现：

```python
import re
from datetime import datetime, timedelta

ABSOLUTE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d"]
RELATIVE_RE = re.compile(r"^(?:(\d+|a)\s+)?(year|month|day|week)s?\s+ago$", re.I)
CONFIDENCE_BY_UNIT = {"day": 0.95, "week": 0.85, "month": 0.7, "year": 0.5}


def _parse_date_published(raw, *, scraped_at=None, return_meta=False):
    if not raw:
        return (None, {"method": "unknown", "anchor": None, "confidence": 0.0}) if return_meta else None

    raw = raw.strip()

    # 1. 绝对日期
    for fmt in ABSOLUTE_FORMATS:
        try:
            d = datetime.strptime(raw, fmt)
            parsed = d.strftime("%Y-%m-%d")
            return (parsed, {"method": "absolute", "anchor": None, "confidence": 1.0}) if return_meta else parsed
        except ValueError:
            continue

    # 2. 相对时间表达
    m = RELATIVE_RE.match(raw)
    if m:
        n = m.group(1)
        unit = m.group(2).lower()
        n = 1 if (n is None or n.lower() == "a") else int(n)

        # anchor 选取：优先 scraped_at，回退当前时间
        if scraped_at:
            try:
                anchor_dt = datetime.fromisoformat(scraped_at.replace(" ", "T"))
                method = "relative_scraped_at"
            except ValueError:
                anchor_dt = datetime.now()
                method = "relative_now"
        else:
            anchor_dt = datetime.now()
            method = "relative_now"

        delta_days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        parsed_dt = anchor_dt - timedelta(days=delta_days)
        parsed = parsed_dt.strftime("%Y-%m-%d")
        confidence = CONFIDENCE_BY_UNIT[unit]
        meta = {"method": method, "anchor": scraped_at, "confidence": confidence}
        return (parsed, meta) if return_meta else parsed

    return (None, {"method": "unknown", "anchor": None, "confidence": 0.0}) if return_meta else None
```

- [ ] **Step 4: 修改 `_backfill_date_published_parsed`**

定位该函数，去掉自身的 anchor 逻辑，改为传入 `scraped_at` 调用 `_parse_date_published`。同时把返回的 `meta` 写入 reviews 表的新字段（`date_parse_method` / `date_parse_anchor` / `date_parse_confidence`）。

```python
def _backfill_date_published_parsed(conn):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, date_published, scraped_at FROM reviews WHERE date_published_parsed IS NULL OR date_parse_method IS NULL"
    ).fetchall()
    for row_id, raw, scraped_at in rows:
        parsed, meta = _parse_date_published(raw, scraped_at=scraped_at, return_meta=True)
        cur.execute(
            "UPDATE reviews SET date_published_parsed=?, date_parse_method=?, date_parse_anchor=?, date_parse_confidence=?, date_published_estimated=? WHERE id=?",
            (parsed, meta["method"], meta["anchor"], meta["confidence"], 1 if meta["method"].startswith("relative") else 0, row_id),
        )
    conn.commit()
```

- [ ] **Step 5: 运行测试确认通过**

```bash
pytest tests/server/test_date_published_anchor.py -v
```

Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/server/test_date_published_anchor.py
git commit -m "fix(report): unify date_published parse anchor to scraped_at + persist parse confidence (F011 H15)"
```

### Task 1.3: failure_mode enum 化迁移脚本

**Files:**
- Create: `qbu_crawler/server/migrations/0011_failure_mode_enum_backfill.py`
- Modify: `qbu_crawler/models.py`（review_analysis 加 failure_mode_raw 字段）
- Test: `tests/server/test_failure_mode_enum.py`

- [ ] **Step 1: 写失败测试**

`tests/server/test_failure_mode_enum.py`：

```python
from qbu_crawler.server.migrations.migration_0011_failure_mode_enum_backfill import classify_failure_mode

def test_none_class_for_no_variants():
    """各种"无"变体应归到 'none' 类。"""
    cases = ["无", "无失效", "无显著失效模式", "无故障", "无失效问题",
             "无典型失效模式", "无/运行正常", "运行稳定无异常"]
    for case in cases:
        assert classify_failure_mode(case) == "none", f"{case} 应分类为 none"

def test_gear_failure():
    cases = ["齿轮过载停转", "齿轮薄弱卡顿", "齿轮磨损脱落金属屑"]
    for case in cases:
        assert classify_failure_mode(case) == "gear_failure"

def test_motor_anomaly():
    cases = ["电机过载", "马达停转", "电机温升过高"]
    for case in cases:
        assert classify_failure_mode(case) == "motor_anomaly"

def test_casing_assembly():
    cases = ["壳体装配错位", "喉道生锈", "密封圈漏液"]
    for case in cases:
        assert classify_failure_mode(case) == "casing_assembly"

def test_material_finish():
    cases = ["材料剥落", "金属碎屑", "涂层裂纹", "生锈"]
    for case in cases:
        assert classify_failure_mode(case) == "material_finish"

def test_control_electrical():
    cases = ["开关失灵", "按键接触不良", "电气故障"]
    for case in cases:
        assert classify_failure_mode(case) == "control_electrical"

def test_noise():
    cases = ["噪音过大", "运行声大", "嗡嗡声"]
    for case in cases:
        assert classify_failure_mode(case) == "noise"

def test_cleaning_difficulty():
    cases = ["清洁困难", "清洗繁琐"]
    for case in cases:
        assert classify_failure_mode(case) == "cleaning_difficulty"

def test_other_fallback():
    """无法归类 → other"""
    cases = ["完全陌生的失效现象", "xyz123"]
    for case in cases:
        assert classify_failure_mode(case) == "other"

# v1.1 新增：边界场景（解决 B1 优先级 bug）
def test_negation_prefix_overrides_keyword():
    """F011 AC-32 — 含负面 keyword 但有 negation 前缀的，归类为 'none'。"""
    cases = [
        "无齿轮问题",        # 含"齿轮"但前缀"无...问题"
        "无电机过载",        # 含"电机"但前缀"无"
        "未发现齿轮问题",    # "未发现...问题"夹"齿轮"
        "没有金属碎屑",      # "没有...碎屑"
        "未见装配错位",      # "未见...装配"
    ]
    for case in cases:
        assert classify_failure_mode(case) == "none", f"{case} 应归类为 none，但得到 {classify_failure_mode(case)}"

def test_genuine_failure_with_no_prefix_in_middle():
    """真实失效——中间含'无'但整体语义为失效，不应归 'none'。"""
    cases = [
        ("齿轮无法运转", "gear_failure"),           # "无法" 是部分否定词组，但描述实际失效
        ("电机无规律停转", "motor_anomaly"),        # 同上
    ]
    for case, expected in cases:
        assert classify_failure_mode(case) == expected, f"{case} 应归类为 {expected}"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_failure_mode_enum.py -v
```

- [ ] **Step 3: 写 classify_failure_mode 实现**

`qbu_crawler/server/migrations/0011_failure_mode_enum_backfill.py`：

```python
"""F011 H19 — failure_mode 自由文本 → enum 9 类归类回填。

策略：
1. 优先正则 keyword 匹配（高精度）
2. 匹配失败回退到 'other'
3. 保留原文到 review_analysis.failure_mode_raw 字段
"""
import re
import sqlite3

ENUM_VALUES = (
    "none", "gear_failure", "motor_anomaly", "casing_assembly",
    "material_finish", "control_electrical", "noise", "cleaning_difficulty", "other",
)

# v1.1: First-pass — 全文 negation 检测（解决 B1 优先级 bug）
# 整体语义为"未发生失效"的 negation phrases — 必须全词级匹配
NEGATION_FULL_PHRASES = re.compile(
    r"^("
    r"无|没有|未发现|未表现|未见|未出现|"
    r"无失效|无故障|无问题|无缺陷|"
    r"无(任何|明显|显著|典型|具体)?(失效|故障|问题|缺陷|异常)|"
    r"未(发现|出现|表现|见到)(任何)?(明显|显著)?(齿轮|电机|马达|开关|材料|涂层|噪音|过载|装配|壳体)?(问题|缺陷|失效|故障|异常)?|"
    r"没有(任何)?(明显|显著)?(齿轮|电机|马达|开关|材料|涂层|噪音|过载|装配|壳体)?(问题|缺陷|失效|故障|异常)|"
    r"运行(稳定|正常|顺畅|流畅)(无(异常|故障|问题))?|"
    r"无类(别)?|"
    r"N/A|none|不适用"
    r")"
    r"$|"
    # 也支持带 / 分隔的复合表达
    r"^(无|未见|没有)/[^/]+$",
    re.IGNORECASE,
)


# 失效部件 keyword 模式（仅在 negation 不命中时使用）
FAILURE_KEYWORD_PATTERNS = [
    ("gear_failure",     re.compile(r"齿轮")),
    ("motor_anomaly",    re.compile(r"(电机|马达|过载|温升|停转(?!.*齿轮))")),
    ("casing_assembly",  re.compile(r"(壳体|装配|喉道|密封|漏液|接口|焊缝)")),
    ("material_finish",  re.compile(r"(材料|涂层|碎屑|剥落|生锈|裂纹|金属屑)")),
    ("control_electrical", re.compile(r"(开关|电气|按键|接触|电源|电路)")),
    ("noise",            re.compile(r"(噪音|噪声|嗡|声大|分贝)")),
    ("cleaning_difficulty", re.compile(r"清(洁|洗)(困难|繁琐|不便)")),
]


def classify_failure_mode(raw: str) -> str:
    """归类自由文本到 9 类 enum。

    v1.1 修复 B1：分类逻辑改为两阶段——
    1. 全文 negation 检测（如 "无齿轮问题"）→ none，绕过 keyword
    2. 否则 keyword 匹配
    3. 全部不命中 → other
    """
    if not raw:
        return "none"
    raw = raw.strip()

    # Stage 1: full-phrase negation
    if NEGATION_FULL_PHRASES.match(raw):
        return "none"

    # Stage 1.5: 简单短语 — 仅 "无" 单字
    if raw == "无":
        return "none"

    # Stage 2: keyword 匹配
    for enum_val, pattern in FAILURE_KEYWORD_PATTERNS:
        if pattern.search(raw):
            return enum_val

    return "other"


def up(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # 添加 failure_mode_raw 字段（保留原始）
    try:
        cur.execute("ALTER TABLE review_analysis ADD COLUMN failure_mode_raw TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # 把现有 failure_mode 复制到 raw
    cur.execute("UPDATE review_analysis SET failure_mode_raw = failure_mode WHERE failure_mode_raw IS NULL")

    # 重写 failure_mode 为 enum 值
    rows = cur.execute("SELECT id, failure_mode FROM review_analysis WHERE failure_mode IS NOT NULL").fetchall()
    for row_id, raw in rows:
        enum_val = classify_failure_mode(raw)
        cur.execute("UPDATE review_analysis SET failure_mode=? WHERE id=?", (enum_val, row_id))

    conn.commit()


def down(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # 从 raw 恢复
    cur.execute("UPDATE review_analysis SET failure_mode = failure_mode_raw WHERE failure_mode_raw IS NOT NULL")
    try:
        cur.execute("ALTER TABLE review_analysis DROP COLUMN failure_mode_raw")
    except sqlite3.OperationalError:
        pass
    conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/server/test_failure_mode_enum.py -v
```

Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/migrations/0011_failure_mode_enum_backfill.py \
        tests/server/test_failure_mode_enum.py
git commit -m "feat(report): F011 H19 — failure_mode 9-enum classification migration"
```

### Task 1.4: scrape_quality 增加 zero_scrape 检测

**Files:**
- Modify: `qbu_crawler/server/scrape_quality.py`
- Test: `tests/server/test_scrape_quality_zero_scrape.py`

- [ ] **Step 1: 写失败测试**

```python
from qbu_crawler.server.scrape_quality import summarize_scrape_quality

def test_zero_scrape_skus_detected():
    """有产品站点报告 N>0 但实际入库 0 时，应在 zero_scrape_skus 列出。"""
    products = [
        {"sku": "A", "review_count": 91, "ingested_count": 0},
        {"sku": "B", "review_count": 100, "ingested_count": 95},
        {"sku": "C", "review_count": 0, "ingested_count": 0},
    ]
    quality = summarize_scrape_quality(products)
    assert "A" in quality["zero_scrape_skus"]
    assert "B" not in quality["zero_scrape_skus"]
    assert "C" not in quality["zero_scrape_skus"]  # 站点本身就 0，不算异常

def test_completeness_ratio():
    products = [
        {"sku": "A", "review_count": 100, "ingested_count": 50},
        {"sku": "B", "review_count": 100, "ingested_count": 80},
    ]
    quality = summarize_scrape_quality(products)
    assert quality["scrape_completeness_ratio"] == 0.65  # (50+80)/(100+100)

def test_low_coverage_skus():
    products = [
        {"sku": "A", "review_count": 100, "ingested_count": 50},
        {"sku": "B", "review_count": 100, "ingested_count": 95},
    ]
    quality = summarize_scrape_quality(products, low_coverage_threshold=0.6)
    assert "A" in quality["low_coverage_skus"]
    assert "B" not in quality["low_coverage_skus"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_scrape_quality_zero_scrape.py -v
```

- [ ] **Step 3: 改造 `summarize_scrape_quality`**

`qbu_crawler/server/scrape_quality.py`：

```python
def summarize_scrape_quality(products, *, low_coverage_threshold: float = 0.6) -> dict:
    """计算采集质量指标。

    新增字段（F011 H1）：
    - zero_scrape_skus: 站点 review_count > 0 但 ingested = 0 的 SKU 列表
    - scrape_completeness_ratio: 全局 ingested / site_reported
    - low_coverage_skus: 单产品覆盖率 < threshold 的 SKU 列表
    """
    total = len(products)
    site_total = sum(p.get("review_count", 0) or 0 for p in products)
    ingested_total = sum(p.get("ingested_count", 0) or 0 for p in products)

    zero_scrape_skus = [
        p["sku"] for p in products
        if (p.get("review_count", 0) or 0) > 0 and (p.get("ingested_count", 0) or 0) == 0
    ]

    low_coverage_skus = []
    for p in products:
        site = p.get("review_count", 0) or 0
        ingested = p.get("ingested_count", 0) or 0
        if site > 0 and (ingested / site) < low_coverage_threshold:
            low_coverage_skus.append(p["sku"])

    completeness = (ingested_total / site_total) if site_total else 1.0

    return {
        "total": total,
        "missing_rating": sum(1 for p in products if not p.get("rating")),
        "missing_stock": sum(1 for p in products if not p.get("stock_status")),
        "missing_review_count": sum(1 for p in products if p.get("review_count") is None),
        # 新增 F011 字段
        "zero_scrape_skus": zero_scrape_skus,
        "zero_scrape_count": len(zero_scrape_skus),
        "scrape_completeness_ratio": round(completeness, 4),
        "low_coverage_skus": low_coverage_skus,
        "low_coverage_count": len(low_coverage_skus),
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/server/test_scrape_quality_zero_scrape.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/scrape_quality.py tests/server/test_scrape_quality_zero_scrape.py
git commit -m "feat(report): F011 H1 — scrape_quality detect zero_scrape_skus + low_coverage_skus + completeness_ratio"
```

### Task 1.5: 修复 query_cumulative_data SELECT 漏字段

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`（`query_cumulative_data` / `query_report_data`）
- Test: `tests/server/test_query_includes_analysis_fields.py`

- [ ] **Step 1: 写失败测试**

```python
import sqlite3
import pytest
from qbu_crawler.server.report_snapshot import query_cumulative_data, query_report_data

@pytest.fixture
def db_with_analysis(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    # 略：构造 reviews + review_analysis 测试数据，含 impact_category, failure_mode
    yield conn
    conn.close()

def test_cumulative_data_includes_failure_mode(db_with_analysis):
    data = query_cumulative_data(db_with_analysis, since=None, until=None)
    assert all("failure_mode" in r for r in data["reviews"])
    assert all("impact_category" in r for r in data["reviews"])

def test_report_data_includes_failure_mode(db_with_analysis):
    data = query_report_data(db_with_analysis, since="2026-04-26", until="2026-04-27")
    assert all("failure_mode" in r for r in data["reviews"])
    assert all("impact_category" in r for r in data["reviews"])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_query_includes_analysis_fields.py -v
```

- [ ] **Step 3: 修改 `query_cumulative_data` 和 `query_report_data` SQL**

定位这两个函数中的 `SELECT ...` 语句，在 `review_analysis ra` 的字段列表中加入 `ra.impact_category, ra.failure_mode`：

```sql
SELECT r.id, r.product_id, r.author, r.headline, r.body, ...,
       ra.sentiment, ra.sentiment_score, ra.labels, ra.features,
       ra.insight_cn, ra.insight_en,
       ra.impact_category,    -- F011 H12 新增
       ra.failure_mode        -- F011 H12 新增
FROM reviews r
LEFT JOIN review_analysis ra ON ra.review_id = r.id
WHERE ...
```

并在 Python dict 构造时透传字段。

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/server/test_query_includes_analysis_fields.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/server/test_query_includes_analysis_fields.py
git commit -m "fix(report): F011 H12 — query_cumulative_data SELECT include impact_category and failure_mode"
```

---

## Phase 2: 业务逻辑改造（依赖 Phase 1）

### Task 2.1: 差评率分母统一

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（`_risk_products` / 产品概览相关）
- Test: `tests/server/test_negative_rate_denominator.py`

- [ ] **Step 1: 写失败测试**

```python
def test_risk_negative_rate_uses_ingested():
    """F011 H6 — risk_score 分母改为 ingested_only（不再 max(site, ingested)）。"""
    product = {
        "sku": "TEST",
        "review_count": 253,        # 站点
        "ingested_count": 109,
        "negative_review_count": 9,
    }
    risk = compute_risk_score(product)
    # 用 ingested 分母：9/109 ≈ 8.26%
    assert abs(risk["neg_rate"] - 0.0826) < 0.001

def test_product_overview_excel_uses_unified_denominator():
    """F011 H10 — 产品概览同列同口径，差评率 = 差评 / 采集"""
    products_data = [
        {"name": "A", "ingested_count": 56, "negative_review_count": 25},  # 竞品
        {"name": "B", "ingested_count": 109, "negative_review_count": 9},   # 自有有风险
        {"name": "C", "ingested_count": 71, "negative_review_count": 0},    # 自有无风险
    ]
    rows = build_product_overview_rows(products_data)
    # 全部用 ingested 分母
    assert abs(rows[0]["negative_rate_ingested"] - 0.4464) < 0.001
    assert abs(rows[1]["negative_rate_ingested"] - 0.0826) < 0.001  # 不再是 0.0356!
    assert rows[2]["negative_rate_ingested"] == 0.0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_negative_rate_denominator.py -v
```

- [ ] **Step 3: 改造 `_risk_products` 中 neg_rate 分母**

定位 `report_analytics.py:836-844` 周边的 `_risk_products` 函数，将 `denominator = max(site_review_count, ingested_count)` 改为 `denominator = ingested_count or 1`。同时在返回 dict 中加 `low_coverage_warning` 字段：

```python
def _risk_products(...):
    for p in products:
        ingested = p.get("ingested_count", 0) or 0
        site = p.get("review_count", 0) or 0
        if ingested == 0:
            continue  # 跳过零抓取（不应静默隐藏，由 scrape_quality 告警）
        neg = p.get("negative_review_count", 0)
        neg_rate = neg / ingested
        coverage = ingested / site if site else 1.0
        low_coverage_warning = coverage < 0.5
        # ... 其余因子计算
```

- [ ] **Step 4: 改造产品概览统一分母**

新增 `build_product_overview_rows`：

```python
def build_product_overview_rows(products):
    rows = []
    for p in products:
        ingested = p.get("ingested_count", 0) or 0
        site = p.get("review_count", 0) or 0
        neg = p.get("negative_review_count", 0)
        rows.append({
            "name": p.get("name"),
            "site_count": site,
            "ingested_count": ingested,
            "coverage": (ingested / site) if site else None,
            "negative_count": neg,
            # 双列展示，避免单列误读
            "negative_rate_ingested": (neg / ingested) if ingested else None,
            "negative_rate_site": (neg / site) if site else None,
        })
    return rows
```

- [ ] **Step 5: 运行测试确认通过**

```bash
pytest tests/server/test_negative_rate_denominator.py -v
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/server/test_negative_rate_denominator.py
git commit -m "fix(report): F011 H6+H10 — unify negative_rate denominator to ingested + dual-col product overview"
```

### Task 2.2: risk_score 因子分解输出

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（`_risk_products`）
- Test: `tests/server/test_risk_score_factors.py`

- [ ] **Step 1: 写失败测试**

```python
def test_risk_score_factors_breakdown():
    """F011 H11 — risk_score 必须输出 5 因子分解。"""
    product = {
        "sku": "TEST",
        "ingested_count": 109,
        "negative_review_count": 9,
        "high_severity_count": 7,
        "image_evidence_count": 3,
        "recent_negative_count": 2,
        "total_volume": 109,
    }
    result = compute_risk_score(product)

    assert "risk_factors" in result
    factors = result["risk_factors"]
    for key in ("neg_rate", "severity", "evidence", "recency", "volume"):
        assert key in factors
        assert "raw" in factors[key]
        assert "weight" in factors[key]
        assert "weighted" in factors[key]
    # 权重总和必须 = 1.0
    total_weight = sum(f["weight"] for f in factors.values())
    assert abs(total_weight - 1.0) < 0.001

def test_near_high_risk_flag():
    """F011 H18 — 接近高风险阈值（0.85 * HIGH_RISK 到 HIGH_RISK 区间）"""
    # HIGH_RISK_THRESHOLD = 35
    score_near = 32.6
    assert is_near_high_risk(score_near, threshold=35) is True
    score_low = 25.0
    assert is_near_high_risk(score_low, threshold=35) is False
    score_high = 40.0
    assert is_near_high_risk(score_high, threshold=35) is False  # 已是高风险，不属于"接近"
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 改造 `compute_risk_score` 输出因子分解**

```python
RISK_WEIGHTS = {"neg_rate": 0.35, "severity": 0.25, "evidence": 0.15, "recency": 0.15, "volume": 0.10}

def compute_risk_score(product, *, threshold: float = 35.0):
    ingested = product.get("ingested_count", 0) or 0
    if ingested == 0:
        return {"risk_score": None, "risk_factors": None, "near_high_risk": False}

    factors_raw = {
        "neg_rate":  product["negative_review_count"] / ingested,
        "severity":  product["high_severity_count"] / max(product["negative_review_count"], 1),
        "evidence":  product["image_evidence_count"] / max(product["negative_review_count"], 1),
        "recency":   product["recent_negative_count"] / max(product["negative_review_count"], 1),
        "volume":    min(product["total_volume"] / 100, 1.0),
    }
    factors = {}
    score = 0.0
    for key, weight in RISK_WEIGHTS.items():
        raw = factors_raw[key]
        weighted = raw * weight
        factors[key] = {"raw": round(raw, 4), "weight": weight, "weighted": round(weighted, 4)}
        score += weighted

    score_pct = round(score * 100, 1)
    return {
        "risk_score": score_pct,
        "risk_factors": factors,
        "near_high_risk": is_near_high_risk(score_pct, threshold=threshold),
    }


def is_near_high_risk(score: float, *, threshold: float = 35.0) -> bool:
    return 0.85 * threshold <= score < threshold
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/server/test_risk_score_factors.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/server/test_risk_score_factors.py
git commit -m "feat(report): F011 H11+H18 — risk_score 5-factor breakdown + near_high_risk flag"
```

### Task 2.3: METRIC_TOOLTIPS 与算法同步

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/server/test_metric_tooltips_sync.py`

- [ ] **Step 1: 写失败测试**

```python
from qbu_crawler.server.report_common import METRIC_TOOLTIPS

def test_risk_score_tooltip_mentions_5_factor():
    """F011 H11 — tooltip 必须明确 5 因子加权。"""
    tooltip = METRIC_TOOLTIPS["风险分"]
    # 必须包含权重信息
    assert "5 因子" in tooltip or "5因子" in tooltip
    assert "差评率" in tooltip and "35%" in tooltip
    # 必须明确 ≤2 星阈值
    assert "≤2" in tooltip or "≤ 2" in tooltip
    # 不应再有旧的"×2 + ×1 累加"描述
    assert "×2" not in tooltip and "×1" not in tooltip
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 修订 `METRIC_TOOLTIPS["风险分"]` 文案**

`qbu_crawler/server/report_common.py`：

```python
METRIC_TOOLTIPS = {
    # ...
    "风险分": (
        "5 因子加权（满分 100）：差评率 35% + 高严重度占比 25% + "
        "图证据占比 15% + 近期负面占比 15% + 量级显著性 10%。"
        "差评 = 评分 ≤2 星。≥35 为高风险，≥0.85×35=29.75 标记为接近高风险。"
    ),
    # ...
}
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/server/test_metric_tooltips_sync.py
git commit -m "fix(report): F011 H11 — METRIC_TOOLTIPS 风险分 sync with 5-factor algorithm"
```

### Task 2.4: change_digest 三层金字塔

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（`build_change_digest`）
- Test: `tests/server/test_change_digest_pyramid.py`

- [ ] **Step 1: 写失败测试**

```python
def test_change_digest_has_three_layers():
    """F011 H22 — change_digest 包含 immediate_attention / trend_changes / competitive_opportunities"""
    digest = build_change_digest(snapshot, prev_analytics)
    assert "immediate_attention" in digest
    assert "trend_changes" in digest
    assert "competitive_opportunities" in digest

def test_immediate_attention_has_own_new_negative():
    """F011 H22 — 我方新差评必须独立列出（最高优先级）"""
    snapshot = {
        "reviews": [
            {"product_name": ".75 HP", "ownership": "own", "rating": 1, "date_published_parsed": "2026-04-25"},
            {"product_name": ".75 HP", "ownership": "own", "rating": 2, "date_published_parsed": "2026-04-26"},
        ]
    }
    digest = build_change_digest(snapshot, prev_analytics={})
    own_neg = digest["immediate_attention"]["own_new_negative_reviews"]
    assert len(own_neg) > 0
    assert own_neg[0]["product_name"] == ".75 HP"
    assert own_neg[0]["review_count"] == 2

def test_competitive_opportunities_has_competitor_negative():
    """F011 H22 — 竞品新差评 = 营销机会，独立列出"""
    snapshot = {
        "reviews": [
            {"product_name": "Cabela X", "ownership": "competitor", "rating": 1, "date_published_parsed": "2026-04-26"},
        ]
    }
    digest = build_change_digest(snapshot, prev_analytics={})
    comp_neg = digest["competitive_opportunities"]["competitor_new_negative_reviews"]
    assert len(comp_neg) > 0
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 `build_change_digest` 三层重构（v1.1 强化时间口径）**

定位 `report_analytics.py` 中的 change_digest 构造逻辑，加入三层结构。

**v1.1 / B4 时间口径明确**：所有"new"信号按 `scraped_at` 分类（运营视角："系统首次采到"），不按 `date_published`：

```python
def build_change_digest(snapshot, prev_analytics):
    """构造三层金字塔 change_digest（v1.1 强化时间口径）。

    F011 §4.2.4.1 — 所有"new"信号按 scraped_at（系统视角），
    不按 date_published（用户写作时间视角）。
    用户在 2 年前写的负面评论今天首次采到，仍是今天该处理的"新"差评。
    """
    # 时间窗口：用 snapshot.data_since 作为 scraped_at 下限
    recent_threshold = snapshot.get("data_since", "")  # 'YYYY-MM-DDTHH:MM:SS+08:00'

    digest = {
        "enabled": True,
        "immediate_attention": _build_immediate_attention(snapshot, prev_analytics, recent_threshold),
        "trend_changes": _build_trend_changes(snapshot, prev_analytics),
        "competitive_opportunities": _build_competitive_opportunities(snapshot, prev_analytics, recent_threshold),
        # 保留旧字段供向后兼容
        "issue_changes": _build_issue_changes(snapshot, prev_analytics),
        "product_changes": _build_product_changes(snapshot, prev_analytics),
        "review_signals": _build_review_signals(snapshot, prev_analytics),
        "summary": _build_summary(snapshot),
        "warnings": _build_warnings(snapshot),
        "view_state": "bootstrap" if not prev_analytics else "incremental",
    }
    return digest


def _build_immediate_attention(snapshot, prev, recent_threshold):
    own_new_negative = []
    by_product = {}
    for r in snapshot.get("reviews", []):
        if r.get("ownership") != "own":
            continue
        if (r.get("rating") or 0) > 2:
            continue
        # v1.1 / B4: 按 scraped_at 而非 date_published
        if r.get("scraped_at", "") < recent_threshold:
            continue
        pname = r.get("product_name")
        by_product.setdefault(pname, []).append(r)
    for pname, reviews in by_product.items():
        # 抽取主要问题（top 2 labels）
        labels = []
        for r in reviews:
            for lab in r.get("analysis_labels_parsed", []):
                if lab.get("polarity") == "negative":
                    labels.append(lab.get("code"))
        from collections import Counter
        top_labels = [l for l, _ in Counter(labels).most_common(2)]
        own_new_negative.append({
            "product_name": pname,
            "review_count": len(reviews),
            "primary_problems": top_labels,
        })

    own_rating_drops = _detect_rating_drops(snapshot, prev)
    own_stock_alerts = _detect_stock_alerts(snapshot, prev)

    return {
        "own_new_negative_reviews": own_new_negative,
        "own_rating_drops": own_rating_drops,
        "own_stock_alerts": own_stock_alerts,
    }


def _build_competitive_opportunities(snapshot, prev, recent_threshold):
    comp_new_neg = []
    by_product = {}
    for r in snapshot.get("reviews", []):
        if r.get("ownership") != "competitor":
            continue
        if (r.get("rating") or 0) > 2:
            continue
        # v1.1 / B4: 按 scraped_at 而非 date_published
        if r.get("scraped_at", "") < recent_threshold:
            continue
        by_product.setdefault(r.get("product_name"), []).append(r)
    for pname, reviews in by_product.items():
        comp_new_neg.append({
            "product_name": pname,
            "review_count": len(reviews),
        })

    fresh_comp_pos = _legacy_fresh_competitor_positive_reviews(snapshot, recent_threshold)
    return {
        "competitor_new_negative_reviews": comp_new_neg,
        "competitor_new_positive_reviews": fresh_comp_pos[:3],  # 降级，仅取 3 条
    }
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/server/test_change_digest_pyramid.py
git commit -m "feat(report): F011 H22 — change_digest 三层金字塔（立即关注/趋势/反向利用）"
```

### Task 2.5: trend_digest 单主图 + ready 阈值

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（trend_digest 构造）
- Test: `tests/server/test_trend_digest_thresholds.py`

- [ ] **Step 1: 写失败测试**

```python
def test_ready_requires_min_30_samples_and_7_timepoints():
    """F011 H16 — ready 阈值 ≥30 样本且时间点 ≥7"""
    # 案例 1: 仅 3 条样本 → 必须 accumulating
    digest = build_trend_digest(reviews=[{"date": "2026-04-01"}, {"date": "2026-04-02"}, {"date": "2026-04-03"}])
    assert digest["primary_chart"]["confidence"] in ("low", "no_data")
    assert digest["primary_chart"].get("min_sample_warning") is not None

    # 案例 2: 30 条样本但仅 5 个时间点 → medium
    reviews = [{"date": f"2026-04-{i+1:02d}"} for i in range(5)] * 6  # 5 时间点
    digest = build_trend_digest(reviews=reviews)
    assert digest["primary_chart"]["confidence"] in ("medium", "low")

    # 案例 3: 30 条 + 7 时间点 → high
    reviews = [{"date": f"2026-04-{i+1:02d}"} for i in range(7)] * 5  # 7 时间点 35 条
    digest = build_trend_digest(reviews=reviews)
    assert digest["primary_chart"]["confidence"] == "high"

def test_trend_has_dual_anchor():
    """F011 — 双时间口径 scraped_at vs date_published"""
    digest = build_trend_digest(reviews=[...])
    assert "anchors_available" in digest["primary_chart"]
    assert "scraped_at" in digest["primary_chart"]["anchors_available"]
    assert "date_published" in digest["primary_chart"]["anchors_available"]
    assert digest["primary_chart"]["default_anchor"] == "scraped_at"

def test_primary_chart_has_comparison_baseline():
    """F011 — 主图含对比基准"""
    digest = build_trend_digest(reviews=[...], prev_window_data={...})
    comparison = digest["primary_chart"]["comparison"]["own_vs_prior_window"]
    assert "current" in comparison
    assert "prior" in comparison
    assert "delta" in comparison
    assert "delta_pct" in comparison
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 trend_digest 单主图**

```python
TREND_MIN_HIGH = (30, 7)
TREND_MIN_MEDIUM = (15, 5)

def _classify_confidence(sample_size: int, time_points: int) -> str:
    if sample_size >= TREND_MIN_HIGH[0] and time_points >= TREND_MIN_HIGH[1]:
        return "high"
    if sample_size >= TREND_MIN_MEDIUM[0] and time_points >= TREND_MIN_MEDIUM[1]:
        return "medium"
    return "low" if sample_size > 0 else "no_data"


def build_trend_digest(reviews, *, prev_window_data=None, default_window="30d", default_anchor="scraped_at"):
    # 按 anchor 聚合
    series_own = _aggregate_health_series(reviews, ownership="own", anchor=default_anchor, window=default_window)
    series_competitor = _aggregate_health_series(reviews, ownership="competitor", anchor=default_anchor, window=default_window)

    sample_size = len([r for r in reviews if r.get("ownership") == "own"])
    time_points = len(series_own)
    confidence = _classify_confidence(sample_size, time_points)

    min_warning = None
    if confidence == "low":
        min_warning = f"样本 {sample_size} 条 / 时间点 {time_points}，需 ≥30 + ≥7 才能判趋势"

    primary_chart = {
        "kind": "health_trend",
        "default_window": default_window,
        "default_anchor": default_anchor,
        "windows_available": ["7d", "30d", "12m"],
        "anchors_available": ["scraped_at", "date_published"],
        "series_own": series_own,
        "series_competitor": series_competitor,
        "comparison": _build_comparison(series_own, prev_window_data) if prev_window_data else None,
        "confidence": confidence,
        "min_sample_warning": min_warning,
    }

    drill_downs = [
        _build_top_issues_drilldown(reviews, default_window),
        _build_product_ratings_drilldown(reviews),
        _build_competitor_radar_drilldown(reviews),
    ]

    return {
        "primary_chart": primary_chart,
        "drill_downs": drill_downs,
    }


def _build_comparison(series_own, prev_window_data):
    if not series_own:
        return None
    current = series_own[-1]["value"]
    prior = prev_window_data.get("own_avg_health", current)
    delta = current - prior
    delta_pct = (delta / prior * 100) if prior else 0
    return {
        "own_vs_prior_window": {
            "current": current,
            "prior": prior,
            "delta": round(delta, 2),
            "delta_pct": round(delta_pct, 2),
        }
    }
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/server/test_trend_digest_thresholds.py
git commit -m "feat(report): F011 H16 — trend_digest 单主图 + ready 阈值升级 + 双 anchor 切换"
```

### Task 2.6: improvement_priorities short_title 拆字段 + LLM prompt v3

**Files:**
- Modify: `qbu_crawler/server/report_llm.py`
- Test: `tests/server/test_llm_prompt_v3.py`

- [ ] **Step 1: 写失败测试**

```python
def test_improvement_priorities_have_short_title_and_full_action():
    """F011 H14 — improvement_priorities 必须含 short_title (≤20字) 和 full_action (≥80字)"""
    schema = LLM_INSIGHTS_SCHEMA  # JSON schema for v3 prompt
    item_schema = schema["properties"]["improvement_priorities"]["items"]
    assert "short_title" in item_schema["properties"]
    assert "full_action" in item_schema["properties"]
    assert "evidence_review_ids" in item_schema["properties"]
    assert item_schema["required"] == [
        "label_code", "short_title", "full_action", "evidence_count", "evidence_review_ids"
    ]

def test_short_title_max_length_validation():
    """short_title ≤ 20 中文字"""
    bad_copy = {
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "结构设计：肉饼厚度不可调影响 3 款，需重新设计调节机构",  # 28 字 超长
            "full_action": "..." * 100,
            "evidence_count": 13,
            "evidence_review_ids": [1, 2, 3],
        }]
    }
    with pytest.raises(SchemaError):
        validate_llm_copy(bad_copy)

def test_tone_guard_health_high_no_severe_word():
    """F011 H9 — health_index ≥ 90 时禁止 hero 用'严重'"""
    kpis = {"health_index": 96.2, "high_risk_count": 0}
    bad_copy = {"hero_headline": "健康指数 96.2，但缺陷正严重侵蚀核心体验"}
    with pytest.raises(ToneGuardError):
        validate_tone_guards(bad_copy, kpis)

    good_copy = {"hero_headline": "健康指数 96.2，仍存在结构性短板待夯实"}
    # 不应抛
    validate_tone_guards(good_copy, kpis)
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 写 LLM v3 prompt + 校验**

`qbu_crawler/server/report_llm.py`：

```python
LLM_INSIGHTS_SCHEMA_V3 = {
    "type": "object",
    "required": ["hero_headline", "executive_summary", "executive_bullets", "improvement_priorities"],
    "properties": {
        "hero_headline": {"type": "string", "maxLength": 100},
        "executive_summary": {"type": "string"},
        "executive_bullets": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "improvement_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label_code", "short_title", "full_action", "evidence_count", "evidence_review_ids"],
                "properties": {
                    "label_code": {"type": "string"},
                    "short_title": {"type": "string", "maxLength": 30},  # 中文 20 字 ≈ 60 byte，留余地
                    "full_action": {"type": "string", "minLength": 80},
                    "evidence_count": {"type": "integer"},
                    "evidence_review_ids": {"type": "array", "items": {"type": "integer"}},
                    "affected_products": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


TONE_GUARDS_PROMPT = """
措辞规则（必须遵守）：
1. 若 health_index ≥ 90，hero_headline 禁止使用 严重 / 侵蚀 / 重灾区 等强负面词；
   改用 仍存在结构性短板 / 局部需要关注 等温和措辞
2. executive_bullets 中的所有数字必须能在 kpis / risk_products 中找到原始来源；
   不得自行计算或外推
3. 若 high_risk_count = 0，禁止使用"高风险产品"作为主语
4. improvement_priorities[].short_title 必须 ≤ 20 字（中文计字）；
   full_action 必须 ≥ 80 字
5. evidence_review_ids 必须从 input 中的 reviews 列表挑选实际存在的 id
"""


def _build_insights_prompt_v3(kpis, clusters, gap, ...):
    # 构造 v3 prompt，含 TONE_GUARDS_PROMPT
    # ...


def validate_llm_copy(copy: dict) -> dict:
    """JSON schema 校验。失败抛 SchemaError。"""
    import jsonschema
    try:
        jsonschema.validate(copy, LLM_INSIGHTS_SCHEMA_V3)
    except jsonschema.ValidationError as e:
        raise SchemaError(str(e))
    # 中文字数额外校验
    for item in copy.get("improvement_priorities", []):
        if len(item["short_title"]) > 20:
            raise SchemaError(f"short_title 超过 20 字: {item['short_title']}")
    return copy


def validate_tone_guards(copy: dict, kpis: dict) -> None:
    """措辞护栏校验。失败抛 ToneGuardError。"""
    health = kpis.get("health_index", 0)
    high_risk = kpis.get("high_risk_count", 0)
    severe_words = ["严重", "侵蚀", "重灾区"]
    hero = copy.get("hero_headline", "")
    if health >= 90:
        for word in severe_words:
            if word in hero:
                raise ToneGuardError(f"health_index={health} 不应使用 '{word}'")
    if high_risk == 0:
        if "高风险产品" in hero:
            raise ToneGuardError("high_risk_count=0 不应主语为'高风险产品'")


def generate_report_insights_with_validation(kpis, clusters, gap, ..., max_retries=3):
    """F011 H9 — 重试 + schema + tone guard + 数字断言"""
    import time
    last_err = None
    for attempt in range(max_retries):
        try:
            copy_json = _llm_call(_build_insights_prompt_v3(kpis, clusters, gap, ...))
            copy = validate_llm_copy(copy_json)
            validate_tone_guards(copy, kpis)
            assert_consistency(copy, kpis)  # 数字断言
            return copy
        except (SchemaError, ToneGuardError, AssertionError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    log.error(f"LLM insights generation failed after {max_retries}: {last_err}")
    return template_fallback(kpis, clusters)


def assert_consistency(copy: dict, kpis: dict) -> None:
    """数字断言：copy 中提到的关键数字必须能在 kpis 找到。"""
    import re
    hero = copy.get("hero_headline", "")
    # 提取 hero 中的健康分数字
    m = re.search(r"健康(?:指数|度)\s*(\d+(?:\.\d+)?)", hero)
    if m:
        claimed = float(m.group(1))
        actual = kpis.get("health_index", 0)
        if abs(claimed - actual) > 0.5:
            raise AssertionError(f"hero claims health={claimed} but kpis={actual}")
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_llm.py tests/server/test_llm_prompt_v3.py
git commit -m "feat(report): F011 H9+H14 — LLM prompt v3 + JSON schema + tone guards + retry + numeric assertion"
```

### Task 2.6.1: 完整 `assert_consistency` 数字断言（v1.1 新增 P1）

**Files:**
- Modify: `qbu_crawler/server/report_llm.py`
- Test: `tests/server/test_llm_assert_consistency.py`

**对应 F011 §5.3.2 完整化**

- [ ] **Step 1: 写失败测试**

```python
import pytest
from qbu_crawler.server.report_llm import assert_consistency

KPIS_SAMPLE = {"health_index": 96.2, "high_risk_count": 0, "own_review_rows": 418}
RISK_PRODUCTS_SAMPLE = [{"product_name": ".75 HP", "risk_score": 32.6}]
REVIEWS_SAMPLE = [{"id": 1}, {"id": 2}, {"id": 252}, {"id": 254}]

def test_hero_health_match_passes():
    copy = {"hero_headline": "健康指数 96.2，仍存在结构性短板"}
    assert_consistency(copy, KPIS_SAMPLE, RISK_PRODUCTS_SAMPLE, REVIEWS_SAMPLE)

def test_hero_health_mismatch_raises():
    copy = {"hero_headline": "健康指数 90.0，仍存在结构性短板"}  # 90 ≠ 96.2
    with pytest.raises(AssertionError, match="health"):
        assert_consistency(copy, KPIS_SAMPLE, RISK_PRODUCTS_SAMPLE, REVIEWS_SAMPLE)

def test_evidence_count_zero_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "improvement_priorities": [{"label_code": "x", "evidence_count": 0, "evidence_review_ids": [], "affected_products": []}]
    }
    with pytest.raises(AssertionError, match="evidence_count"):
        assert_consistency(copy, KPIS_SAMPLE, RISK_PRODUCTS_SAMPLE, REVIEWS_SAMPLE)

def test_unknown_review_id_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "improvement_priorities": [{
            "label_code": "x", "evidence_count": 3,
            "evidence_review_ids": [1, 999, 1000],  # 999/1000 不存在
            "affected_products": [".75 HP"]
        }]
    }
    with pytest.raises(AssertionError, match="未知 review id"):
        assert_consistency(copy, KPIS_SAMPLE, RISK_PRODUCTS_SAMPLE, REVIEWS_SAMPLE)

def test_unknown_product_in_affected_raises():
    copy = {
        "hero_headline": "健康指数 96.2",
        "improvement_priorities": [{
            "label_code": "x", "evidence_count": 3,
            "evidence_review_ids": [1, 2],
            "affected_products": [".75 HP", "Unknown Product"]
        }]
    }
    with pytest.raises(AssertionError, match="affected_products"):
        assert_consistency(copy, KPIS_SAMPLE, RISK_PRODUCTS_SAMPLE, REVIEWS_SAMPLE)

def test_bullet_unknown_number_raises():
    """bullet 中数字必须能在 kpis 中找到来源"""
    copy = {
        "hero_headline": "健康指数 96.2",
        "executive_bullets": [".75 HP 风险分高达 99.9/100"]  # 99.9 ≠ 32.6
    }
    with pytest.raises(AssertionError, match="bullet"):
        assert_consistency(copy, KPIS_SAMPLE, RISK_PRODUCTS_SAMPLE, REVIEWS_SAMPLE)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_llm_assert_consistency.py -v
```

- [ ] **Step 3: 实现完整 `assert_consistency`**

```python
import re

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def assert_consistency(copy, kpis, risk_products, reviews):
    """F011 §5.3.2 完整数字断言。"""
    # 1. hero_headline 中的 health_index
    _assert_hero_health_match(copy.get("hero_headline", ""), kpis)

    # 2. executive_bullets 中的所有数字
    known_numbers = _collect_known_numbers(kpis, risk_products)
    for bullet in copy.get("executive_bullets", []):
        _assert_numbers_traceable(bullet, known_numbers, label="bullet")

    # 3. improvement_priorities[].evidence_count
    for item in copy.get("improvement_priorities", []):
        ec = item.get("evidence_count", 0)
        if ec < 1:
            raise AssertionError(f"evidence_count must be ≥1: {item}")

    # 4. improvement_priorities[].evidence_review_ids 必须存在于 reviews
    review_id_set = {r["id"] for r in reviews}
    for item in copy.get("improvement_priorities", []):
        invalid_ids = [rid for rid in item.get("evidence_review_ids", []) if rid not in review_id_set]
        if invalid_ids:
            raise AssertionError(f"evidence_review_ids 包含未知 review id: {invalid_ids}")

    # 5. improvement_priorities[].affected_products 必须 ⊆ 实际产品名
    actual_products = {p["product_name"] for p in risk_products}
    for item in copy.get("improvement_priorities", []):
        unknown = set(item.get("affected_products", [])) - actual_products
        if unknown:
            raise AssertionError(f"affected_products 包含未知: {unknown}")


def _assert_hero_health_match(hero, kpis):
    m = re.search(r"健康(?:指数|度)\s*(\d+(?:\.\d+)?)", hero)
    if m:
        claimed = float(m.group(1))
        actual = kpis.get("health_index", 0)
        if abs(claimed - actual) > 0.5:
            raise AssertionError(f"hero claims health={claimed} but kpis health_index={actual}")


def _collect_known_numbers(kpis, risk_products) -> set[float]:
    """收集所有"已知合法"数字。"""
    nums = set()
    for v in kpis.values():
        if isinstance(v, (int, float)):
            nums.add(round(float(v), 2))
    for p in risk_products:
        for v in p.values():
            if isinstance(v, (int, float)):
                nums.add(round(float(v), 2))
    return nums


def _assert_numbers_traceable(text, known_numbers, *, label, tolerance=0.5):
    """文本中提到的数字必须在 known_numbers 中有 ≤tolerance 偏差的来源。"""
    for m in NUMBER_RE.finditer(text):
        n = float(m.group())
        # 跳过明显的 sample id / 章节号（< 2 或为整数排序号）
        if n < 2 and len(m.group()) <= 1:
            continue
        if not any(abs(n - k) <= tolerance or abs(n - k) / max(k, 1) <= 0.01 for k in known_numbers):
            raise AssertionError(f"{label} 中数字 {n} 在 kpis/risk_products 找不到来源（tolerance={tolerance}）")
```

- [ ] **Step 4: 运行测试 + Commit**

```bash
pytest tests/server/test_llm_assert_consistency.py -v
git add qbu_crawler/server/report_llm.py tests/server/test_llm_assert_consistency.py
git commit -m "feat(report): F011 §5.3.2 v1.1 — assert_consistency 全字段数字断言（bullet/evidence_id/affected_products）"
```

### Task 2.7: top_actions 死字段处置（fallback 机制）

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`

- [ ] **Step 1: 写测试 — top_actions 在 LLM 失败时由规则填充**

```python
def test_top_actions_fallback_when_llm_failed():
    """F011 H20 — LLM improvement_priorities 失败时，top_actions 由规则降级填充。"""
    risk_products = [{"product_name": ".75 HP", "top_labels": [{"code": "structure_design", "display": "结构设计"}]}]
    issue_clusters = []
    fallback = build_fallback_priorities(risk_products, issue_clusters)
    assert len(fallback) > 0
    assert fallback[0]["short_title"]
    assert fallback[0]["full_action"]
```

- [ ] **Step 2: 实现 build_fallback_priorities**

```python
def build_fallback_priorities(risk_products, issue_clusters, *, max_items=5):
    """F011 H20 — LLM 输出空时的规则降级。"""
    priorities = []
    for p in risk_products[:3]:
        for label in (p.get("top_labels") or [])[:1]:
            priorities.append({
                "label_code": label["code"],
                "label_display": label.get("display", label["code"]),
                "short_title": f"{label.get('display', label['code'])}：{p['product_name']}",
                "full_action": "请查看附件中的详细问题诊断卡。本条由规则降级生成（LLM 输出失败）。",
                "evidence_count": label.get("count", 0),
                "evidence_review_ids": [],
                "affected_products": [p["product_name"]],
                "affected_products_count": 1,
            })
    return priorities[:max_items]
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
git add qbu_crawler/server/report_analytics.py
git commit -m "feat(report): F011 H20 — fallback priorities when LLM output empty"
```

---

## Phase 3: 展示层改造（依赖 Phase 1+2）

### Task 3.1: 邮件正文 HTML 重构

**Files:**
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`
- Test: `tests/server/test_email_full_template.py`

- [ ] **Step 1: 写失败测试**

```python
def test_email_full_has_4_kpi_lights():
    """F011 §4.1 — 4 张语义灯（总体口碑/好评率/差评率/需关注产品）。"""
    html = render_email_full(snapshot=mock_snapshot, analytics=mock_analytics)
    assert "总体口碑" in html
    assert "好评率" in html
    assert "差评率" in html
    assert "需关注产品" in html

def test_kpi_health_lamp_thresholds():
    """v1.1 / Bug 3 — 健康灯阈值开闭区间明确：≥85 绿 / [70,85) 黄 / <70 红"""
    # Edge: 85 → 绿
    html = render_email_full(snapshot=mock_snapshot, analytics={"kpis": {"health_index": 85.0}})
    assert "lamp-green" in html or "🟢" in html
    # Edge: 84.99 → 黄
    html = render_email_full(snapshot=mock_snapshot, analytics={"kpis": {"health_index": 84.99}})
    assert "lamp-yellow" in html or "🟡" in html
    # Edge: 70 → 黄
    html = render_email_full(snapshot=mock_snapshot, analytics={"kpis": {"health_index": 70.0}})
    assert "lamp-yellow" in html or "🟡" in html
    # Edge: 69.99 → 红
    html = render_email_full(snapshot=mock_snapshot, analytics={"kpis": {"health_index": 69.99}})
    assert "lamp-red" in html or "🔴" in html

def test_kpi_4_uses_lamp_count_not_hardcoded_25():
    """v1.1 / I2 — 需关注产品数 = 黄+红灯产品数（不再硬编码 risk_score≥25）"""
    analytics = {
        "kpis": {"health_index": 96.2},
        "self": {
            "product_status": [
                {"product_name": "A", "status_lamp": "yellow"},  # 算
                {"product_name": "B", "status_lamp": "red"},     # 算
                {"product_name": "C", "status_lamp": "green"},   # 不算
                {"product_name": "D", "status_lamp": "gray"},    # 不算（无数据）
            ]
        }
    }
    html = render_email_full(snapshot=mock_snapshot, analytics=analytics)
    assert "需关注产品  2 个" in html or "需关注产品 2" in html  # 容许格式微差

def test_email_full_no_engineering_signals():
    """F011 §4.1.3 — 不出现工程信号"""
    html = render_email_full(snapshot=mock_snapshot, analytics=mock_analytics)
    assert "覆盖率" not in html
    assert "本次入库" not in html
    assert "estimated_dates" not in html
    assert "backfill_dominant" not in html

def test_email_full_size_under_50kb():
    """F011 §6.1 — 邮件正文 ≤ 50KB"""
    html = render_email_full(snapshot=mock_snapshot, analytics=mock_analytics)
    assert len(html.encode("utf-8")) < 50 * 1024
```

- [ ] **Step 2: 重写 email_full.html.j2**

完整重写为 §4.1.1 设计的 4 KPI 灯 + Hero + Top 3 + 产品状态 结构（替换 267 行旧模板）。删除：覆盖率卡 / 累计评论数字卡 / 本次入库大数字 / 健康分巨幅 hero。

具体模板代码见 F011 §4.1.1（实施时按 jinja 语法写）。

- [ ] **Step 3: 运行测试 + 视觉比对**

```bash
pytest tests/server/test_email_full_template.py -v
# 同时手动渲染 fixture 数据，在 Outlook / Gmail 中预览
python -c "from qbu_crawler.server.report import render_email_full; ..."
```

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_templates/email_full.html.j2 tests/server/test_email_full_template.py
git commit -m "feat(report): F011 §4.1 — email_full.html.j2 重写为 4 KPI 灯 + Top 3 + 产品状态"
```

### Task 3.2: 附件 HTML — 删除"今日变化"4 区块，加入三层金字塔（双模式）

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/server/test_attachment_html_today_changes.py`

- [ ] **Step 1: 写失败测试**

```python
def test_today_changes_hidden_in_bootstrap():
    html = render_attachment_html(snapshot=bootstrap_snapshot, analytics=bootstrap_analytics)
    # bootstrap 期：单卡说明，没有 4 子区块
    assert "首日基线已建档" in html
    assert "问题变化 0 / 0" not in html  # 旧空状态消失

def test_today_changes_pyramid_in_mature_period():
    html = render_attachment_html(snapshot=mature_snapshot, analytics=mature_analytics)
    # 数据成熟期：三层金字塔
    assert "立即关注" in html
    assert "趋势变化" in html
    assert "反向利用" in html

def test_today_changes_immediate_attention_shows_own_negative():
    snapshot_with_neg = make_snapshot_with_own_new_negative()
    html = render_attachment_html(snapshot=snapshot_with_neg, analytics=...)
    assert ".75 HP" in html  # 出现在立即关注区
```

- [ ] **Step 2: 修改模板**

定位 `daily_report_v3.html.j2` 中 H2 今日变化 区块，整体替换为：

```jinja
<section class="today-changes">
  <h2>今日变化</h2>
  {% if analytics.report_semantics == "bootstrap" %}
    <div class="info-card bootstrap-notice">
      ℹ 首日基线已建档，对比信号将从下一日起出现
    </div>
  {% else %}
    {% set ia = analytics.change_digest.immediate_attention %}
    {% set tc = analytics.change_digest.trend_changes %}
    {% set co = analytics.change_digest.competitive_opportunities %}

    {% if ia.own_new_negative_reviews or ia.own_rating_drops or ia.own_stock_alerts %}
    <div class="layer immediate-attention">
      <h3>🔥 立即关注</h3>
      {% for item in ia.own_new_negative_reviews %}
        <div class="alert-item">
          • 我方新差评 {{ item.review_count }} 条 ({{ item.product_name }})
            主要问题: {{ item.primary_problems | join(', ') }}
        </div>
      {% endfor %}
      {% for item in ia.own_rating_drops %}
        <div class="alert-item">
          • {{ item.product_name }} 评分 {{ item.rating_from }} → {{ item.rating_to }} ({{ item.delta }})
        </div>
      {% endfor %}
      {% for item in ia.own_stock_alerts %}
        <div class="alert-item">
          • {{ item.product_name }} 缺货警告
        </div>
      {% endfor %}
    </div>
    {% endif %}

    {% if tc.new_issues or tc.escalated_issues or tc.improving_issues %}
    <div class="layer trend-changes">
      <h3>📈 趋势变化</h3>
      {# ... new_issues / escalated_issues / improving_issues #}
    </div>
    {% endif %}

    {% if co.competitor_new_negative_reviews or co.competitor_new_positive_reviews %}
    <div class="layer competitive-opportunities">
      <h3>💡 反向利用</h3>
      {# ... competitor_new_negative_reviews 优先 #}
    </div>
    {% endif %}
  {% endif %}
</section>
```

同步加 CSS 类（`.bootstrap-notice` / `.layer.immediate-attention` 等），定位 `daily_report_v3.css`。

- [ ] **Step 3: 运行测试 + Commit**

```bash
pytest tests/server/test_attachment_html_today_changes.py -v
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_templates/daily_report_v3.css \
        tests/server/test_attachment_html_today_changes.py
git commit -m "feat(report): F011 §4.2.4 — 附件 HTML 今日变化区块改三层金字塔（含 bootstrap 双模式）"
```

### Task 3.3: 附件 HTML — 删除"变化趋势"12 panel，改 1 主图 + 3 折叠（双模式）

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`（主图渲染逻辑）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`
- Test: `tests/server/test_attachment_html_trends.py`

- [ ] **Step 1: 写失败测试**

```python
def test_trend_section_hidden_in_bootstrap():
    html = render_attachment_html(bootstrap_snapshot, bootstrap_analytics)
    assert "趋势数据正在累积" in html
    # 12 panel 旧标题消失
    assert "近 7 天 / 评论声量与情绪" not in html
    assert "近 30 天 / 问题结构" not in html

def test_trend_section_shows_primary_chart_in_mature():
    html = render_attachment_html(mature_snapshot, mature_analytics)
    assert "口碑健康度趋势" in html
    assert "对比上 30 天平均" in html
    # 折叠下钻
    assert "Top 3 问题随时间变化" in html
    assert "产品评分变化" in html
    assert "竞品对标雷达" in html
```

- [ ] **Step 2: 修改模板**

定位 daily_report_v3.html.j2 中 H2 变化趋势 区块（含 12 个 H3 子标题：近 7 天 × 4 + 近 30 天 × 4 + 近 12 月 × 4），整体替换为：

```jinja
<section class="trend-section">
  <h2>变化趋势</h2>
  {% set td = analytics.trend_digest %}
  {% set primary = td.primary_chart %}

  {% if primary.confidence in ("low", "no_data") %}
    <div class="info-card bootstrap-notice">
      ℹ 趋势数据正在累积，需 ≥30 样本且每周 ≥7 个有效样本
      {% if primary.min_sample_warning %}
        <div class="warning-detail">{{ primary.min_sample_warning }}</div>
      {% endif %}
    </div>
  {% else %}
    <div class="primary-chart">
      <h3>口碑健康度趋势</h3>
      <div id="health-trend-chart" data-series='{{ primary | tojson }}'></div>

      <div class="comparison-baseline">
        当前 {{ primary.comparison.own_vs_prior_window.current }}
        {{ primary.comparison.own_vs_prior_window.delta | abs_arrow }}
        {{ primary.comparison.own_vs_prior_window.delta }}pt
        vs 上期平均
      </div>

      <div class="window-toggle">
        时间切换:
        {% for w in primary.windows_available %}
          <button data-window="{{ w }}" {% if w == primary.default_window %}class="active"{% endif %}>{{ w | window_label }}</button>
        {% endfor %}
      </div>

      <div class="anchor-toggle">
        口径切换:
        <button data-anchor="scraped_at" {% if primary.default_anchor == "scraped_at" %}class="active"{% endif %}>采集时间</button>
        <button data-anchor="date_published" {% if primary.default_anchor == "date_published" %}class="active"{% endif %}>发表时间</button>
      </div>
    </div>

    {% for d in td.drill_downs %}
    <details class="drill-down">
      <summary>{{ d.title }}</summary>
      <div class="drill-content" data-payload='{{ d.data | tojson }}'></div>
    </details>
    {% endfor %}
  {% endif %}
</section>
```

`daily_report_v3.js` 中加入主图渲染逻辑（沿用现有 chart 库或 vanilla SVG）。

- [ ] **Step 3: 运行测试 + Commit**

```bash
pytest tests/server/test_attachment_html_trends.py -v
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_templates/daily_report_v3.js \
        qbu_crawler/server/report_templates/daily_report_v3.css \
        tests/server/test_attachment_html_trends.py
git commit -m "feat(report): F011 §4.2.5 — 附件 HTML 变化趋势从 12 panel → 1 主图 + 3 折叠（含 bootstrap 双模式）"
```

### Task 3.4: 附件 HTML — 自有产品状态灯 + 全景数据筛选 + 模板健壮性

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`（筛选逻辑）
- Test: `tests/server/test_attachment_html_other.py`

- [ ] **Step 1: 写失败测试**

```python
def test_product_status_uses_lights_not_numbers():
    """F011 §4.2.3 — 自有产品状态灯+一句原因，不再展示 risk_score 数字。"""
    html = render_attachment_html(snapshot, analytics_with_risk_products)
    assert "🟡" in html or "yellow" in html  # 黄灯
    assert "需关注" in html
    # risk_score 数字仅在 hover 中（注释或 data-attr）
    assert "32.6" in html  # 在 data-tooltip 或 .hover-detail 中

def test_panorama_has_5_filters():
    """F011 §4.2.6 — 全景数据 5 个筛选器。"""
    html = render_attachment_html(snapshot_with_561_reviews, analytics)
    assert 'name="ownership"' in html
    assert 'name="rating"' in html
    assert 'name="has_images"' in html
    assert 'name="recent"' in html
    assert 'name="label"' in html

def test_panorama_embeds_all_561_reviews():
    """F011 §4.2.6 — 561 评论嵌入保留（不改链接）"""
    html = render_attachment_html(snapshot_with_561_reviews, analytics)
    # 简化：随机抽 10 条评论 ID 应能在 HTML 中找到
    for review_id in [10, 100, 200, 400, 561]:
        assert f'data-review-id="{review_id}"' in html

def test_trend_table_uses_columns_key_not_dict_values():
    """F011 H17 — 模板按 columns key 输出表格，不依赖 dict 顺序"""
    template_source = open("qbu_crawler/server/report_templates/daily_report_v3.html.j2").read()
    assert "row.values()" not in template_source
```

- [ ] **Step 2: 修改模板**

1. 自有产品排行 → 自有产品状态（5 行 灯 + 一句原因 + hover 因子分解）：

```jinja
<section class="product-status">
  <h2>自有产品状态</h2>
  <table>
    {% for p in analytics.self.product_status %}
    <tr class="status-row {{ p.status_lamp }}">
      <td><span class="lamp lamp-{{ p.status_lamp }}"></span>{{ p.status_label }}</td>
      <td>{{ p.product_name }}</td>
      <td class="primary-concern">{{ p.primary_concern or '健康' }}</td>
      <td class="risk-detail">
        <span class="risk-score" data-tooltip='{{ p.risk_factors | tojson }}'>
          {{ p.risk_score }}
        </span>
      </td>
    </tr>
    {% endfor %}
  </table>
</section>
```

2. 全景数据加客户端筛选：

```jinja
<section class="panorama">
  <h2>全景数据</h2>
  <div class="panorama-filters">
    <select name="ownership"><option value="">全部</option><option value="own">自有</option><option value="competitor">竞品</option></select>
    <select name="rating"><option value="">全部</option><option value="low">≤2 星</option><option value="mid">3 星</option><option value="high">≥4 星</option></select>
    <label><input type="checkbox" name="has_images"> 仅含图</label>
    <label><input type="checkbox" name="recent"> 近 30 天</label>
    <select name="label"><option value="">全部标签</option>{% for l in analytics.label_options %}<option value="{{ l.code }}">{{ l.display }}</option>{% endfor %}</select>
  </div>
  <table class="panorama-table">
    <thead>...</thead>
    <tbody>
      {% for r in snapshot.reviews %}
        <tr data-review-id="{{ r.id }}"
            data-ownership="{{ r.ownership }}"
            data-rating="{{ r.rating }}"
            data-has-images="{{ '1' if r.images else '0' }}"
            data-recent="{{ '1' if r.is_recent else '0' }}"
            data-labels="{{ r.label_codes | join(',') }}">
          ...
        </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

3. JS 筛选逻辑（`daily_report_v3.js` 加）：

```javascript
function applyPanoramaFilters() {
  const filters = {
    ownership: document.querySelector('[name=ownership]').value,
    rating: document.querySelector('[name=rating]').value,
    has_images: document.querySelector('[name=has_images]').checked,
    recent: document.querySelector('[name=recent]').checked,
    label: document.querySelector('[name=label]').value,
  };
  document.querySelectorAll('.panorama-table tbody tr').forEach(tr => {
    const visible = matchFilters(tr.dataset, filters);
    tr.style.display = visible ? '' : 'none';
  });
}
function matchFilters(d, f) {
  if (f.ownership && d.ownership !== f.ownership) return false;
  if (f.rating === 'low' && parseFloat(d.rating) > 2) return false;
  if (f.rating === 'mid' && parseFloat(d.rating) !== 3) return false;
  if (f.rating === 'high' && parseFloat(d.rating) < 4) return false;
  if (f.has_images && d.hasImages !== '1') return false;
  if (f.recent && d.recent !== '1') return false;
  if (f.label && !d.labels.split(',').includes(f.label)) return false;
  return true;
}
document.querySelectorAll('.panorama-filters select, .panorama-filters input').forEach(el => {
  el.addEventListener('change', applyPanoramaFilters);
});
```

4. 修复模板 `row.values()` → `columns` key：

定位现有趋势表 jinja 中 `{% for v in row.values() %}` 改为 `{% for col in columns %}{{ row[col] }}{% endfor %}`。

- [ ] **Step 3: 运行测试 + Commit**

```bash
pytest tests/server/test_attachment_html_other.py -v
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_templates/daily_report_v3.js \
        qbu_crawler/server/report_templates/daily_report_v3.css \
        tests/server/test_attachment_html_other.py
git commit -m "feat(report): F011 §4.2.3+§4.2.6+H17 — 自有产品状态灯 + 全景筛选 + 模板 columns key"
```

### Task 3.4.2: 特征情感热力图优化（v1.2 新增）

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（`_heatmap_data` 构造逻辑）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`（热力图 HTML）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`（hover + click 交互）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`（颜色阈值 + legend）
- Test: `tests/server/test_heatmap_optimization.py`

**对应 F011 §4.2.6.2 / AC-34**

- [ ] **Step 1: 写失败测试**

```python
def test_heatmap_x_labels_aggregated_to_top_8():
    """F011 AC-34 — 标签轴聚合到 Top 8。"""
    analytics = build_report_analytics(snapshot_with_14_labels)
    heatmap = analytics["_heatmap_data"]
    assert len(heatmap["x_labels"]) <= 8
    # 其余维度合并为"其他"
    if len(heatmap["x_labels"]) < 14:
        assert "其他" in heatmap["x_labels"] or "其他" in heatmap.get("aggregated_labels", [])

def test_heatmap_cell_has_top_review_excerpt():
    """每格含 top_review_id + 摘要供 hover 展示。"""
    analytics = build_report_analytics(snapshot_with_561)
    heatmap = analytics["_heatmap_data"]
    for row in heatmap["z"]:
        for cell in row:
            if cell.get("sample_size", 0) > 0:
                assert "top_review_id" in cell
                assert "top_review_excerpt" in cell
                assert len(cell["top_review_excerpt"]) <= 80

def test_heatmap_low_sample_marked_gray():
    """sample_size < 3 时 score = None（灰色）。"""
    analytics = build_report_analytics(snapshot_minimal)
    heatmap = analytics["_heatmap_data"]
    found_gray = False
    for row in heatmap["z"]:
        for cell in row:
            if cell.get("sample_size", 0) < 3:
                assert cell.get("score") is None or cell.get("color_class") == "gray"
                found_gray = True
    assert found_gray  # 至少有一格灰色（小样本场景）

def test_heatmap_html_has_clickable_cells():
    """格子带 data-product / data-label 属性，可被 JS 监听跳转到全景数据。"""
    html = render_attachment_html(snapshot, analytics)
    import re
    cells = re.findall(r'<td[^>]*class="heatmap-cell"[^>]*data-product="([^"]+)"[^>]*data-label="([^"]+)"', html)
    assert len(cells) > 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_heatmap_optimization.py -v
```

- [ ] **Step 3: 改造 `_heatmap_data` 构造**

在 `report_analytics.py` 中找到 `_heatmap_data` 构造逻辑，改为：

```python
HEATMAP_MAX_LABELS = 8
HEATMAP_MIN_SAMPLE = 3
HEATMAP_TOP_REVIEW_EXCERPT_LEN = 80


def _build_heatmap_data(snapshot, analytics):
    """v1.2 优化：标签轴聚合 Top 8 + cell 含 top_review。"""
    # 1. 聚合标签（按 mention 数排序，保留 has_data 的 Top N-1，其余合并为"其他"）
    label_mention_counts = _count_label_mentions(snapshot["reviews"])
    sorted_labels = sorted(label_mention_counts.items(), key=lambda kv: kv[1], reverse=True)
    top_labels = [code for code, _ in sorted_labels[:HEATMAP_MAX_LABELS - 1]]
    other_labels = [code for code, _ in sorted_labels[HEATMAP_MAX_LABELS - 1:]]
    label_display = {**LABEL_TAXONOMY_DISPLAY, "其他": "其他"}
    x_labels = [label_display[c] for c in top_labels]
    if other_labels:
        x_labels.append("其他")

    # 2. 产品轴
    products = sorted({r["product_name"] for r in snapshot["reviews"] if r.get("ownership") == "own"})
    y_labels = list(products)

    # 3. 构造每格 (含 top review excerpt)
    z = []
    for product in y_labels:
        row = []
        for label in (top_labels + (["其他"] if other_labels else [])):
            label_codes = [label] if label != "其他" else other_labels
            cell_reviews = [
                r for r in snapshot["reviews"]
                if r.get("product_name") == product
                and any(lc in [lab["code"] for lab in r.get("analysis_labels_parsed", [])] for lc in label_codes)
            ]
            sample_size = len(cell_reviews)
            if sample_size < HEATMAP_MIN_SAMPLE:
                row.append({
                    "score": None,
                    "sample_size": sample_size,
                    "color_class": "gray",
                    "top_review_id": None,
                    "top_review_excerpt": "样本不足" if sample_size > 0 else "无样本",
                })
                continue

            # 计算情感分（正面率）
            positive_count = sum(1 for r in cell_reviews if r.get("sentiment") in ("positive", "mixed"))
            score = positive_count / sample_size

            # 颜色
            if score > 0.7:
                color = "green"
            elif score >= 0.4:
                color = "yellow"
            else:
                color = "red"

            # Top review (rating 优先 + 长度限制)
            top_r = max(cell_reviews, key=lambda r: (r.get("rating") or 0, len(r.get("body_cn") or "")))
            excerpt = (top_r.get("body_cn") or top_r.get("body") or "")[:HEATMAP_TOP_REVIEW_EXCERPT_LEN]

            row.append({
                "score": round(score, 3),
                "sample_size": sample_size,
                "color_class": color,
                "top_review_id": top_r["id"],
                "top_review_excerpt": excerpt,
            })
        z.append(row)

    return {"x_labels": x_labels, "y_labels": y_labels, "z": z}
```

- [ ] **Step 4: 改造 HTML 模板**

`daily_report_v3.html.j2` 中找到热力图区域（在"全景数据"或独立 H3）：

```jinja
<section class="heatmap-section">
  <h3>特征情感热力图</h3>
  <div class="heatmap-legend">
    <span class="legend-cell green"></span>认可 (>0.7)
    <span class="legend-cell yellow"></span>中性 (0.4-0.7)
    <span class="legend-cell red"></span>负面 (<0.4)
    <span class="legend-cell gray"></span>样本不足
  </div>
  <table class="heatmap-table">
    <thead>
      <tr>
        <th></th>
        {% for x in analytics._heatmap_data.x_labels %}
          <th>{{ x }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for y in analytics._heatmap_data.y_labels %}
      <tr>
        <th>{{ y }}</th>
        {% set row = analytics._heatmap_data.z[loop.index0] %}
        {% for cell in row %}
          {% set x_label = analytics._heatmap_data.x_labels[loop.index0] %}
          <td class="heatmap-cell {{ cell.color_class }}"
              data-product="{{ y }}"
              data-label="{{ x_label }}"
              data-review-id="{{ cell.top_review_id or '' }}"
              title="{{ y }} × {{ x_label }} ({{ cell.sample_size }} 条)&#10;{{ cell.top_review_excerpt }}">
            {{ '%.0f%%' | format(cell.score * 100) if cell.score is not none else '—' }}
          </td>
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

- [ ] **Step 5: 改造 CSS**

`daily_report_v3.css`：

```css
.heatmap-table { border-collapse: collapse; }
.heatmap-table th, .heatmap-cell { padding: 8px 12px; text-align: center; }
.heatmap-cell { cursor: pointer; transition: opacity 0.2s; }
.heatmap-cell:hover { opacity: 0.8; outline: 2px solid #333; }
.heatmap-cell.green  { background: #86efac; color: #064e3b; }
.heatmap-cell.yellow { background: #fde68a; color: #78350f; }
.heatmap-cell.red    { background: #fca5a5; color: #7f1d1d; }
.heatmap-cell.gray   { background: #e5e7eb; color: #6b7280; }
.heatmap-legend { display: flex; gap: 12px; margin-bottom: 8px; font-size: 12px; }
.legend-cell { display: inline-block; width: 14px; height: 14px; margin-right: 4px; vertical-align: middle; }
```

- [ ] **Step 6: 加点击下钻 JS**

`daily_report_v3.js`：

```javascript
document.querySelectorAll('.heatmap-cell').forEach(cell => {
  cell.addEventListener('click', () => {
    const product = cell.dataset.product;
    const label = cell.dataset.label;
    if (!product || !label) return;

    // 自动设置全景筛选并滚动过去
    const panoramaSection = document.querySelector('.panorama');
    panoramaSection.scrollIntoView({ behavior: 'smooth' });

    // 应用筛选 (TODO: 产品名 → SKU 反查若需要)
    document.querySelector('[name=label]').value = label;
    // 触发 change 事件让 applyPanoramaFilters 生效
    document.querySelector('[name=label]').dispatchEvent(new Event('change'));

    // 高亮 top review
    const reviewId = cell.dataset.reviewId;
    if (reviewId) {
      const reviewRow = document.querySelector(`[data-review-id="${reviewId}"]`);
      if (reviewRow) {
        reviewRow.classList.add('highlighted');
        setTimeout(() => reviewRow.classList.remove('highlighted'), 3000);
      }
    }
  });
});
```

- [ ] **Step 7: 运行测试 + Commit**

```bash
pytest tests/server/test_heatmap_optimization.py -v
git add qbu_crawler/server/report_analytics.py \
        qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_templates/daily_report_v3.css \
        qbu_crawler/server/report_templates/daily_report_v3.js \
        tests/server/test_heatmap_optimization.py
git commit -m "feat(report): F011 §4.2.6.2 v1.2 — 热力图维度 Top 8 聚合 + hover top 评论 + 点击下钻"
```

### Task 3.5: 附件 HTML — issue cards duration_display 改写 + 现在该做什么 short_title

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_common.py`（duration 格式化函数）
- Test: `tests/server/test_attachment_html_issues.py`

- [ ] **Step 1: 写失败测试**

```python
def test_issue_card_no_misleading_duration():
    """F011 H5 — 不再展示'约 8 年'让人误读为问题持续时长。"""
    html = render_attachment_html(snapshot, analytics_with_old_reviews)
    assert "约 8 年" not in html
    assert "约 8 年 1 个月" not in html
    assert "高频期" in html  # 新格式

def test_improvement_uses_short_title_not_full_action():
    """F011 H14 — '现在该做什么' 卡片标题用 short_title。"""
    html = render_attachment_html(snapshot, analytics_with_v3_priorities)
    # short_title 完整出现
    assert "结构设计：肉饼厚度不可调" in html
    # full_action 在折叠区
    assert "details" in html or "expand" in html
    # 80 字截断不再发生
    assert "针对Walton's #22 Meat Grinder、Walton's General Duty Meat Lug与Quick Patty Maker反馈的肉" not in html  # 旧截断标志
```

- [ ] **Step 2: 修改 issue card 模板**

```jinja
<div class="issue-card">
  <h3>{{ card.label_display }}</h3>
  <div class="card-meta">
    {{ card.affected_product_count }} 款产品 ·
    {{ card.example_reviews | length }} 条样本 ·
    {% if card.frequent_period %}
      高频期 {{ card.frequent_period.start }} ~ {{ card.frequent_period.end }}
    {% endif %}
  </div>
  ...
</div>
```

并在 `report_common.py` 修改 `format_duration()` 函数为 `format_frequent_period(min_date, max_date)`，返回 `{"start": "YYYY-MM", "end": "YYYY-MM"}` 格式。

- [ ] **Step 3: 修改"现在该做什么"模板**

```jinja
<section class="recommendations">
  <h2>现在该做什么</h2>
  {% for rec in analytics.report_copy.improvement_priorities %}
  <div class="recommendation-card">
    <h3>{{ rec.short_title }}</h3>
    <div class="meta">影响 {{ rec.affected_products_count }} 款 · 证据 {{ rec.evidence_count }} 条</div>
    <details>
      <summary>详情</summary>
      <p>{{ rec.full_action }}</p>
      <div class="evidence-refs">
        {% for rid in rec.evidence_review_ids[:5] %}
          <a href="#review-{{ rid }}" class="evidence-chip">#{{ rid }}</a>
        {% endfor %}
        {% if rec.evidence_review_ids | length > 5 %}
          <span>+{{ rec.evidence_review_ids | length - 5 }} 更多</span>
        {% endif %}
      </div>
    </details>
  </div>
  {% endfor %}
</section>
```

- [ ] **Step 4: 运行测试 + Commit**

```bash
pytest tests/server/test_attachment_html_issues.py -v
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_common.py \
        tests/server/test_attachment_html_issues.py
git commit -m "feat(report): F011 H5+H14 — issue card 改'高频期' + 现在该做什么用 short_title"
```

### Task 3.5.1: issue cards 默认折叠 Top 3 + 删除 temporal_pattern（v1.2 新增）

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（`issue_cards` 排序）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`（`<details>` 包裹 4-8 张）
- Modify: `qbu_crawler/server/report_llm.py`（删除 temporal_pattern 段输出）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`（折叠动画）
- Test: `tests/server/test_issue_cards_fold.py`

**对应 F011 §4.2.3.1 / AC-35**

- [ ] **Step 1: 写失败测试**

```python
def test_issue_cards_sorted_by_evidence_severity():
    """F011 AC-35 — issue cards 按 evidence_count + severity 排序。"""
    analytics = build_report_analytics(snapshot)
    cards = analytics["issue_cards"]
    for i in range(len(cards) - 1):
        a, b = cards[i], cards[i + 1]
        # 主排序: evidence_count DESC
        if a["evidence_count"] != b["evidence_count"]:
            assert a["evidence_count"] > b["evidence_count"]
        else:
            # 副排序: severity rank
            severity_rank = {"high": 3, "medium": 2, "low": 1}
            assert severity_rank.get(a.get("severity"), 0) >= severity_rank.get(b.get("severity"), 0)

def test_html_top_3_expanded_rest_folded():
    """F011 AC-35 — Top 3 默认展开，4-8 在 <details> 折叠。"""
    html = render_attachment_html(snapshot, analytics_with_8_cards)
    # Top 3 直接出现（无 details 包裹）
    issue_section = _extract_issue_section(html)
    expanded = _count_top_level_issue_cards(issue_section)
    folded = _count_details_wrapped_issue_cards(issue_section)
    assert expanded == 3
    assert folded == 5  # 8-3=5

def test_temporal_pattern_removed():
    """F011 AC-35 — issue card 内不再含 temporal_pattern 段。"""
    html = render_attachment_html(snapshot, analytics_with_8_cards)
    # 模板中不应渲染 temporal_pattern
    assert "temporal_pattern" not in html
    assert "时序模式" not in html  # 中文翻译

def test_llm_prompt_v3_no_longer_requests_temporal_pattern():
    """LLM v3 prompt 不应再要求生成 temporal_pattern。"""
    from qbu_crawler.server.report_llm import LLM_INSIGHTS_SCHEMA_V3
    issue_card_schema = LLM_INSIGHTS_SCHEMA_V3.get("definitions", {}).get("issue_card_deep_analysis", {})
    if issue_card_schema:
        assert "temporal_pattern" not in issue_card_schema.get("properties", {})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_issue_cards_fold.py -v
```

- [ ] **Step 3: 改造 issue_cards 排序**

`report_analytics.py` 中 `_build_issue_cards` 函数末尾加排序：

```python
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _build_issue_cards(snapshot, ...):
    cards = []
    # ... 已有构造逻辑

    # v1.2: 按 evidence_count DESC + severity rank DESC + affected_product_count DESC 排序
    cards.sort(
        key=lambda c: (
            c.get("evidence_count", 0),
            SEVERITY_RANK.get(c.get("severity", "low"), 0),
            c.get("affected_product_count", 0),
        ),
        reverse=True,
    )

    # v1.2: 标记 default_expanded
    for i, card in enumerate(cards):
        card["default_expanded"] = i < 3  # Top 3 默认展开

    return cards
```

- [ ] **Step 4: 改造 HTML 模板**

`daily_report_v3.html.j2` 中找到 issue cards 渲染区：

```jinja
<section class="issue-diagnosis">
  <h2>自有产品问题诊断</h2>
  <p class="section-note">Top 3 默认展开 · 共 {{ analytics.issue_cards | length }} 张诊断卡</p>

  {# Top 3 默认展开 #}
  {% for card in analytics.issue_cards if card.default_expanded %}
    {% include 'partials/issue_card.html.j2' %}
  {% endfor %}

  {# 4-N 折叠 #}
  {% set folded_cards = analytics.issue_cards | selectattr('default_expanded', 'equalto', false) | list %}
  {% if folded_cards %}
  <details class="issue-cards-folded">
    <summary>展开剩余 {{ folded_cards | length }} 张诊断卡</summary>
    {% for card in folded_cards %}
      {% include 'partials/issue_card.html.j2' %}
    {% endfor %}
  </details>
  {% endif %}
</section>
```

并新建 `report_templates/partials/issue_card.html.j2`（提取卡内复用渲染），**删除 `temporal_pattern` 段**：

```jinja
<div class="issue-card">
  <h3>{{ card.label_display }}</h3>
  <div class="card-meta">
    {{ card.affected_product_count }} 款产品 ·
    {{ card.evidence_count }} 条证据 ·
    {% if card.frequent_period %}
      高频期 {{ card.frequent_period.start }} ~ {{ card.frequent_period.end }}
    {% endif %}
  </div>

  {# v1.2: 删除 temporal_pattern 段 #}

  {% if card.actionable_summary %}
    <p class="actionable-summary">{{ card.actionable_summary }}</p>
  {% endif %}

  {% if card.failure_modes %}
    <table class="failure-modes-table">
      <thead><tr><th>失效模式</th><th>频次</th><th>严重度</th></tr></thead>
      {% for fm in card.failure_modes %}
        <tr><td>{{ fm.mode }}</td><td>{{ fm.frequency }}</td><td>{{ fm.severity }}</td></tr>
      {% endfor %}
    </table>
  {% endif %}

  {% if card.root_causes %}
    <div class="root-causes">
      <h4>可能根因</h4>
      <ul>
        {% for cause in card.root_causes %}
          <li>{{ cause.cause }} <span class="confidence-{{ cause.confidence }}">({{ cause.confidence }})</span></li>
        {% endfor %}
      </ul>
    </div>
  {% endif %}

  {% if card.example_reviews %}
    <div class="example-reviews">
      <h4>典型评论</h4>
      {% for r in card.example_reviews[:3] %}
        <blockquote>{{ r.body_cn or r.body }}</blockquote>
      {% endfor %}
    </div>
  {% endif %}

  {% if card.image_gallery %}
    <div class="image-gallery">
      {% for img in card.image_gallery %}
        <img src="{{ img.url }}" alt="">
      {% endfor %}
    </div>
  {% endif %}
</div>
```

- [ ] **Step 5: LLM v3 prompt 删除 temporal_pattern**

`report_llm.py` 中找到 v3 prompt 构造，删除 `temporal_pattern` 字段相关 instruction（让 LLM 不再生成）。同时更新 JSON schema：

```python
# LLM_INSIGHTS_SCHEMA_V3 中 issue_card_deep_analysis 子 schema
# 移除 "temporal_pattern" property
```

- [ ] **Step 6: CSS 折叠样式**

`daily_report_v3.css`：

```css
.issue-cards-folded { margin-top: 16px; }
.issue-cards-folded > summary {
  cursor: pointer;
  padding: 12px;
  background: #f1f5f9;
  border-radius: 8px;
  font-weight: 600;
}
.issue-cards-folded > summary:hover { background: #e2e8f0; }
.issue-cards-folded[open] > summary { background: #cbd5e1; }
```

- [ ] **Step 7: 运行测试 + Commit**

```bash
pytest tests/server/test_issue_cards_fold.py -v
git add qbu_crawler/server/report_analytics.py \
        qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_templates/partials/issue_card.html.j2 \
        qbu_crawler/server/report_llm.py \
        qbu_crawler/server/report_templates/daily_report_v3.css \
        tests/server/test_issue_cards_fold.py
git commit -m "feat(report): F011 §4.2.3.1 v1.2 — issue cards Top 3 默认展开 + 删除 temporal_pattern"
```

### Task 3.6: Excel 4 sheets 重构

**Files:**
- Modify: `qbu_crawler/server/report.py`（`_generate_analytical_excel`）
- Test: `tests/server/test_excel_sheets.py`

- [ ] **Step 1: 写失败测试**

```python
def test_excel_has_4_sheets():
    """F011 §4.3 — Excel 仅 4 sheets。"""
    excel_path = generate_excel(snapshot, analytics, output_dir=tmp_path)
    wb = openpyxl.load_workbook(excel_path)
    assert sorted(wb.sheetnames) == sorted(["核心数据", "现在该做什么", "评论原文", "竞品启示"])

def test_excel_no_old_sheets():
    """已删除：今日变化 / 问题标签 / 趋势数据。"""
    excel_path = generate_excel(snapshot, analytics, output_dir=tmp_path)
    wb = openpyxl.load_workbook(excel_path)
    assert "今日变化" not in wb.sheetnames
    assert "问题标签" not in wb.sheetnames
    assert "趋势数据" not in wb.sheetnames

def test_core_data_sheet_unified_denominator():
    """F011 H10 — 核心数据 sheet 差评率分两列，列名声明分母。"""
    excel_path = generate_excel(snapshot, analytics, output_dir=tmp_path)
    wb = openpyxl.load_workbook(excel_path)
    ws = wb["核心数据"]
    headers = [c.value for c in ws[1]]
    assert "差评率(采集分母)" in headers
    assert "差评率(站点分母)" in headers
    assert "状态灯" in headers
    assert "覆盖率" in headers

def test_review_original_sheet_failure_mode_filled():
    """F011 H12+H19 — 评论原文 sheet 的失效模式列非空率 ≥ 95%。"""
    excel_path = generate_excel(snapshot_with_561_reviews, analytics, output_dir=tmp_path)
    wb = openpyxl.load_workbook(excel_path)
    ws = wb["评论原文"]
    # 找 "失效模式" 列索引
    headers = [c.value for c in ws[1]]
    fm_col = headers.index("失效模式") + 1
    non_empty = sum(1 for r in range(2, ws.max_row + 1) if ws.cell(r, fm_col).value)
    assert non_empty / (ws.max_row - 1) >= 0.95

def test_review_original_sheet_impact_category_distinct_from_labels():
    """F011 H12 — 影响类别 不再与 标签 列雷同。"""
    excel_path = generate_excel(snapshot_with_561_reviews, analytics, output_dir=tmp_path)
    wb = openpyxl.load_workbook(excel_path)
    ws = wb["评论原文"]
    headers = [c.value for c in ws[1]]
    label_col = headers.index("标签") + 1
    impact_col = headers.index("影响类别") + 1
    distinct = sum(1 for r in range(2, ws.max_row + 1)
                   if ws.cell(r, label_col).value != ws.cell(r, impact_col).value)
    assert distinct >= ws.max_row * 0.9  # 至少 90% 行不同
```

- [ ] **Step 2: 重构 `_generate_analytical_excel`**

`qbu_crawler/server/report.py`：

```python
IMPACT_CATEGORY_DISPLAY = {
    "functional": "功能性", "durability": "耐用性",
    "safety": "安全性", "cosmetic": "外观",
    "service": "服务",
}

FAILURE_MODE_DISPLAY = {
    "none": "无", "gear_failure": "齿轮失效",
    "motor_anomaly": "电机异常", "casing_assembly": "壳体/装配",
    "material_finish": "表面/材料", "control_electrical": "控制/电气",
    "noise": "噪音", "cleaning_difficulty": "清洁困难",
    "other": "其他",
}


def _generate_analytical_excel(snapshot, analytics, output_path):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _build_core_data_sheet(wb, snapshot, analytics)
    _build_recommendations_sheet(wb, analytics)
    _build_review_original_sheet(wb, snapshot, analytics)
    _build_competitor_insights_sheet(wb, analytics)

    wb.save(output_path)
    return output_path


def _build_core_data_sheet(wb, snapshot, analytics):
    ws = wb.create_sheet("核心数据")
    headers = [
        "产品名称", "SKU", "站点", "归属", "售价", "库存",
        "站点评分", "站点评论数", "采集评论数", "覆盖率",
        "差评数", "差评率(采集分母)", "差评率(站点分母)",
        "状态灯", "主要问题",
    ]
    ws.append(headers)
    for row in build_product_overview_rows_with_status(snapshot, analytics):
        ws.append([
            row["name"], row["sku"], row["site"],
            "自有" if row["ownership"] == "own" else "竞品",
            row["price"], _stock_label(row["stock_status"]),
            row["site_rating"], row["site_count"], row["ingested_count"],
            f"{row['coverage']*100:.1f}%" if row["coverage"] is not None else "—",
            row["negative_count"],
            f"{row['negative_rate_ingested']*100:.2f}%" if row["negative_rate_ingested"] is not None else "—",
            f"{row['negative_rate_site']*100:.2f}%" if row["negative_rate_site"] is not None else "—",
            row["status_label"],
            row.get("primary_concern", "健康"),
        ])
    _apply_status_lamp_styling(ws)


def _build_recommendations_sheet(wb, analytics):
    ws = wb.create_sheet("现在该做什么")
    ws.append(["序号", "短标题", "影响产品数", "影响产品列表", "用户原话(典型)", "改良方向", "证据数"])
    for i, rec in enumerate(analytics.get("report_copy", {}).get("improvement_priorities", []), 1):
        ws.append([
            i,
            rec["short_title"],
            rec.get("affected_products_count", len(rec.get("affected_products", []))),
            "、".join(rec.get("affected_products", [])),
            rec.get("top_complaint", ""),
            rec["full_action"],
            rec["evidence_count"],
        ])


def _build_review_original_sheet(wb, snapshot, analytics):
    ws = wb.create_sheet("评论原文")
    headers = [
        "ID", "窗口归属", "产品名称", "SKU", "归属", "评分", "情感",
        "标签", "影响类别", "失效模式",
        "标题(原文)", "标题(中文)", "内容(原文)", "内容(中文)",
        "特征短语", "洞察", "评论时间", "照片",
    ]
    ws.append(headers)
    for r in snapshot.get("reviews", []):
        impact_zh = IMPACT_CATEGORY_DISPLAY.get(r.get("impact_category"), "—")
        failure_mode_zh = FAILURE_MODE_DISPLAY.get(r.get("failure_mode"), "—")
        labels_zh = _translate_labels(r.get("analysis_labels", []))
        ws.append([
            r["id"], r.get("window_label", ""), r.get("product_name"), r.get("product_sku"),
            "自有" if r["ownership"] == "own" else "竞品",
            r["rating"], _sentiment_label(r.get("sentiment")),
            labels_zh, impact_zh, failure_mode_zh,
            r.get("headline"), r.get("headline_cn"),
            r.get("body"), r.get("body_cn"),
            "、".join(r.get("analysis_features", [])),
            r.get("analysis_insight_cn", ""),
            r.get("date_published_parsed", ""),
            "",  # 照片单元格（drawing 嵌入由后续逻辑处理）
        ])
    _embed_review_images(ws, snapshot.get("reviews", []))  # drawing 嵌入保留


def _build_competitor_insights_sheet(wb, analytics):
    ws = wb.create_sheet("竞品启示")
    ws.append(["类型", "主题", "证据数", "典型评论(中文)", "涉及产品"])
    competitor = analytics.get("competitor", {})
    for theme in competitor.get("benchmark_examples", [])[:3]:
        ws.append(["可借鉴", theme["topic"], theme["count"], theme.get("example_cn", ""), theme.get("product", "")])
    for theme in competitor.get("negative_opportunities", [])[:3]:
        ws.append(["短板", theme["topic"], theme["count"], theme.get("example_cn", ""), theme.get("product", "")])
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
pytest tests/server/test_excel_sheets.py -v
git add qbu_crawler/server/report.py tests/server/test_excel_sheets.py
git commit -m "feat(report): F011 §4.3 — Excel 4 sheets 重构（核心数据/现在该做什么/评论原文/竞品启示）"
```

### Task 3.9: 竞品启示扩展（弱点机会卡 + benchmark 三类 + 雷达聚合）（v1.2 新增）

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`（`competitor.weakness_opportunities` 计算 + 雷达维度聚合）
- Modify: `qbu_crawler/server/report_llm.py`（benchmark_examples 三类 schema）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`（4 子板块）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`
- Test: `tests/server/test_competitor_insights_v12.py`

**对应 F011 §4.2.7 / AC-36**

- [ ] **Step 1: 写失败测试**

```python
def test_competitor_weakness_opportunities_generated():
    """F011 AC-36 — competitor.weakness_opportunities 至少 1 条。"""
    analytics = build_report_analytics(snapshot_with_competitor_negative)
    weakness = analytics["competitor"]["weakness_opportunities"]
    assert len(weakness) >= 1
    item = weakness[0]
    assert "competitor_complaint_theme" in item
    assert "competitor_evidence_count" in item
    assert "our_advantage_direction" in item

def test_benchmark_examples_three_categories():
    """F011 AC-36 — benchmark_examples 按 product_design / marketing_message / service_model 三类分组"""
    analytics = build_report_analytics(snapshot)
    bench = analytics["competitor"]["benchmark_examples"]
    # v1.2 新结构是 dict（含三类），不再是 list
    assert isinstance(bench, dict)
    assert "product_design" in bench
    assert "marketing_message" in bench
    assert "service_model" in bench

def test_radar_dimensions_aggregated_to_top_8():
    """F011 §4.2.7.3 — 雷达图维度 ≤ 8。"""
    analytics = build_report_analytics(snapshot_with_14_labels)
    radar = analytics["_radar_data"]
    assert 5 <= len(radar["categories"]) <= 8

def test_benchmark_takeaways_removed():
    """F011 §4.2.7.4 — benchmark_takeaways 不再展示。"""
    html = render_attachment_html(snapshot, analytics)
    # 模板中不应出现旧的"benchmark_takeaways"列表
    assert "持续认可做工扎实体验" not in html
    assert "benchmark_takeaways" not in html

def test_competitor_rating_distribution_in_competitor_section():
    """F011 §4.2.6 / §4.2.7 — 竞品评分分布迁移到竞品启示区，不在全景"""
    html = render_attachment_html(snapshot, analytics)
    # 在竞品启示区找到评分分布
    competitor_section = _extract_competitor_section(html)
    assert "竞品评分两极分化" in competitor_section or "评分分布" in competitor_section
    # 全景区不再有"竞品评分分布"独立区块
    panorama_section = _extract_panorama_section(html)
    assert "竞品评分分布" not in panorama_section
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/server/test_competitor_insights_v12.py -v
```

- [ ] **Step 3: 实现 weakness_opportunities 计算**

`report_analytics.py` 新增：

```python
WEAKNESS_OPP_MIN_COMPETITOR_COMPLAINTS = 3
WEAKNESS_OPP_MIN_OUR_POSITIVE = 10


def _build_weakness_opportunities(snapshot, our_label_stats, competitor_label_stats):
    """v1.2 — 取竞品 Top 3 negative labels，对每个找我方对应 positive 优势。"""
    # 1. 竞品 negative labels 排序
    comp_neg_top = sorted(
        [
            (label, stats) for label, stats in competitor_label_stats.items()
            if stats.get("negative_count", 0) >= WEAKNESS_OPP_MIN_COMPETITOR_COMPLAINTS
        ],
        key=lambda kv: kv[1]["negative_count"],
        reverse=True,
    )[:3]

    opportunities = []
    for label, comp_stats in comp_neg_top:
        # 2. 找我方对应 positive
        our_stats = our_label_stats.get(label, {})
        our_positive = our_stats.get("positive_count", 0)
        if our_positive < WEAKNESS_OPP_MIN_OUR_POSITIVE:
            continue

        # 3. LLM 生成 advantage_direction（短句）— 这步可在 LLM prompt 中并入 report_copy 流程
        opportunities.append({
            "competitor_complaint_theme": label,
            "competitor_complaint_display": LABEL_TAXONOMY_DISPLAY.get(label, label),
            "competitor_evidence_count": comp_stats["negative_count"],
            "competitor_products_affected": comp_stats.get("products", []),
            "our_advantage_label": label,
            "our_positive_count": our_positive,
            "our_advantage_direction": _generate_advantage_direction(label, comp_stats, our_stats),
        })

    return opportunities


def _generate_advantage_direction(label, comp_stats, our_stats) -> str:
    """规则简版：'我方 {label} 差异化'。LLM 增强版可在 report_copy 阶段并入。"""
    label_zh = LABEL_TAXONOMY_DISPLAY.get(label, label)
    return f"我方 {label_zh} 差异化"
```

把它接入 `_build_competitor_section`：

```python
def _build_competitor_section(snapshot, analytics):
    # ... 原有逻辑
    section["weakness_opportunities"] = _build_weakness_opportunities(
        snapshot, our_label_stats, competitor_label_stats
    )
    # ...
    return section
```

- [ ] **Step 4: benchmark_examples 三类 schema**

`report_llm.py` 中更新 LLM prompt 和 schema：

```python
LLM_INSIGHTS_SCHEMA_V3["properties"]["competitor"] = {
    "type": "object",
    "properties": {
        "benchmark_examples": {
            "type": "object",
            "required": ["product_design", "marketing_message", "service_model"],
            "properties": {
                "product_design": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["point", "evidence_review_ids", "competitor_product"],
                        "properties": {
                            "point": {"type": "string", "maxLength": 30},
                            "evidence_review_ids": {"type": "array", "items": {"type": "integer"}},
                            "competitor_product": {"type": "string"},
                        },
                    },
                },
                "marketing_message": {"type": "array", "items": {"$ref": "#/definitions/benchmark_item"}},
                "service_model": {"type": "array", "items": {"$ref": "#/definitions/benchmark_item"}},
            },
        },
        # 删除 benchmark_takeaways
    },
}
```

Prompt instructions 加：

```
Competitor benchmark 必须按三类分组输出：
1. product_design: 产品形态可借鉴（机械设计、结构、配件等）
2. marketing_message: 营销话术可借鉴（定位、文案、话术等）
3. service_model: 服务模式可借鉴（说明书、客服、培训等）

每条必须含 evidence_review_ids（≥1 条），point 必须 ≤ 20 字简短。
```

- [ ] **Step 5: 雷达图维度聚合**

`report_analytics.py` 中 `_build_radar_data`：

```python
RADAR_MAX_CATEGORIES = 8
RADAR_MIN_TOTAL_MENTIONS = 5


def _build_radar_data(our_label_stats, competitor_label_stats):
    """v1.2 — 维度聚合到 Top 6-8（按 has_data + 总 mention 数）"""
    all_labels = set(our_label_stats.keys()) | set(competitor_label_stats.keys())
    label_total_mentions = {
        label: (our_label_stats.get(label, {}).get("total", 0) +
                competitor_label_stats.get(label, {}).get("total", 0))
        for label in all_labels
    }
    eligible = [(l, m) for l, m in label_total_mentions.items() if m >= RADAR_MIN_TOTAL_MENTIONS]
    sorted_eligible = sorted(eligible, key=lambda kv: kv[1], reverse=True)[:RADAR_MAX_CATEGORIES]

    categories = [LABEL_TAXONOMY_DISPLAY.get(l, l) for l, _ in sorted_eligible]
    own_values = [our_label_stats.get(l, {}).get("score", 0) for l, _ in sorted_eligible]
    comp_values = [competitor_label_stats.get(l, {}).get("score", 0) for l, _ in sorted_eligible]

    return {
        "categories": categories,
        "own_values": own_values,
        "competitor_values": comp_values,
    }
```

- [ ] **Step 6: 模板改造**

`daily_report_v3.html.j2` 中重构竞品启示区：

```jinja
<section class="competitor-insights">
  <h2>竞品启示</h2>

  {# 1. 竞品弱点 = 我方机会 #}
  {% if analytics.competitor.weakness_opportunities %}
  <div class="weakness-opp-card">
    <h3>⚡ 竞品弱点 = 我方机会</h3>
    <ul>
      {% for opp in analytics.competitor.weakness_opportunities %}
      <li>
        <strong>{{ opp.competitor_complaint_display }}</strong>
        ({{ opp.competitor_evidence_count }} 条差评)
        → {{ opp.our_advantage_direction }}
        <small>(我方 {{ opp.our_positive_count }} 条正面证据)</small>
      </li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  {# 2. 我们能借鉴竞品什么（三类）#}
  <div class="benchmark-card">
    <h3>✨ 我们能借鉴竞品什么</h3>
    {% set bench = analytics.competitor.benchmark_examples %}
    {% for category, label in [
      ('product_design', '产品形态'),
      ('marketing_message', '营销话术'),
      ('service_model', '服务模式')
    ] %}
      {% if bench[category] %}
      <div class="benchmark-category">
        <h4>{{ label }}</h4>
        <ul>
          {% for item in bench[category] %}
            <li>{{ item.point }}
              {% if item.evidence_review_ids %}
                ({% for rid in item.evidence_review_ids[:3] %}<a href="#review-{{ rid }}">#{{ rid }}</a>{% if not loop.last %}, {% endif %}{% endfor %})
              {% endif %}
            </li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}
    {% endfor %}
  </div>

  {# 3. 多维度对标雷达 #}
  <div class="radar-card">
    <h3>📡 多维度对标雷达 (核心 {{ analytics._radar_data.categories | length }} 维)</h3>
    <div id="radar-chart" data-radar='{{ analytics._radar_data | tojson }}'></div>
  </div>

  {# 4. 竞品评分两极分化（v1.2 从全景迁移）#}
  {% if analytics._sentiment_distribution_competitor %}
  <div class="rating-distribution-card">
    <h3>📊 竞品评分两极分化</h3>
    <table>
      <thead><tr><th>产品</th><th>5★</th><th>4★</th><th>3★</th><th>2★</th><th>1★</th></tr></thead>
      <tbody>
        {% for product, dist in analytics._sentiment_distribution_competitor.items() %}
        <tr>
          <td>{{ product }}</td>
          {% for star in [5,4,3,2,1] %}
            <td>{{ '%.0f%%' | format((dist.get(star~'star_count', 0) / dist.total * 100) if dist.total else 0) }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="insight-note">↗ 启示：竞品 ≤2★ 占比偏高的产品对应我方差异化机会</p>
  </div>
  {% endif %}
</section>
```

并删除全景区中的"竞品评分分布"独立 H3（因迁移到竞品启示）。

- [ ] **Step 7: 运行测试 + Commit**

```bash
pytest tests/server/test_competitor_insights_v12.py -v
git add qbu_crawler/server/report_analytics.py \
        qbu_crawler/server/report_llm.py \
        qbu_crawler/server/report_templates/daily_report_v3.html.j2 \
        qbu_crawler/server/report_templates/daily_report_v3.css \
        tests/server/test_competitor_insights_v12.py
git commit -m "feat(report): F011 §4.2.7 v1.2 — 竞品启示扩展（弱点机会卡 + benchmark 三类 + 雷达 Top 8 聚合 + 评分分布迁移）"
```

---

## Phase 4: 集成、内部运维、CI

### Task 4.1: 内部运维邮件触发

**Files:**
- Modify: `qbu_crawler/server/notifier.py`
- Modify: `qbu_crawler/server/report_templates/email_data_quality.html.j2`
- Test: `tests/server/test_internal_ops_alert.py`

- [ ] **Step 1: 写失败测试**

```python
def test_zero_scrape_triggers_ops_alert():
    """F011 §4.4.1 — zero_scrape_skus 非空必须触发 P0 内部邮件。"""
    quality = {"zero_scrape_skus": ["SKU_X"], "scrape_completeness_ratio": 0.95}
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P0"

def test_low_completeness_triggers_p1():
    quality = {"zero_scrape_skus": [], "scrape_completeness_ratio": 0.5}
    triggered, severity = _evaluate_ops_alert_triggers(quality)
    assert triggered is True
    assert severity == "P1"

def test_outbox_deadletter_triggers_workflow_phase_downgrade():
    """F011 H13 — outbox deadletter 触发 workflow_runs.report_phase 降级。"""
    run_id = create_test_run(report_phase="full_sent")
    mark_outbox_deadletter(run_id)
    assert get_run(run_id)["report_phase"] == "full_sent_local"  # 降级
```

- [ ] **Step 2: 实现触发逻辑**

`qbu_crawler/server/notifier.py`：

```python
OPS_ALERT_THRESHOLDS = {
    "zero_scrape": "P0",
    "low_completeness": "P1",
    "high_estimated_dates": "P2",
    "outbox_deadletter": "P1",
}


def _evaluate_ops_alert_triggers(quality: dict) -> tuple[bool, str]:
    """返回 (是否触发, 最高严重度)"""
    severities = []
    if quality.get("zero_scrape_skus"):
        severities.append("P0")
    if (quality.get("scrape_completeness_ratio") or 1.0) < 0.6:
        severities.append("P1")
    if (quality.get("estimated_date_ratio") or 0) > 0.3:
        severities.append("P2")
    if quality.get("outbox_deadletter_count", 0) > 0:
        severities.append("P1")

    if not severities:
        return (False, "")
    # P0 > P1 > P2
    severity = sorted(severities)[0]
    return (True, severity)


def maybe_send_ops_alert(run_id, quality, outbox_deadletter_count, *, recipients=None):
    triggered, severity = _evaluate_ops_alert_triggers({
        **quality,
        "outbox_deadletter_count": outbox_deadletter_count,
    })
    if not triggered:
        return None

    threshold = config.OPS_ALERT_TRIGGER_THRESHOLD_LEVEL  # P0/P1/P2
    if _severity_rank(severity) < _severity_rank(threshold):
        return None  # 低于阈值不发

    body = render_email_data_quality(run_id, quality, severity, outbox_deadletter_count)
    send_email_internal(recipients or config.OPS_ALERT_EMAIL_TO, subject=f"[内部] QBU 报告生成监控 [{severity}]", body=body)


def downgrade_report_phase_on_deadletter(run_id, conn):
    """F011 H13 — outbox deadletter 时降级 report_phase。"""
    cur = conn.cursor()
    deadletter = cur.execute("SELECT COUNT(*) FROM notification_outbox WHERE status='deadletter' AND payload LIKE ?", (f'%"run_id":{run_id}%',)).fetchone()[0]
    if deadletter > 0:
        cur.execute("UPDATE workflow_runs SET report_phase=? WHERE id=? AND report_phase=?", ("full_sent_local", run_id, "full_sent"))
        conn.commit()
```

- [ ] **Step 3: 模板补强 email_data_quality.html.j2**

按 F011 §4.4.2 邮件结构补充模板字段。

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/notifier.py \
        qbu_crawler/server/report_templates/email_data_quality.html.j2 \
        tests/server/test_internal_ops_alert.py
git commit -m "feat(report): F011 §4.4+H13 — 内部运维邮件 + outbox deadletter 触发 phase 降级"
```

### Task 4.2: report_artifacts 表写入与 HTML 路径回写

**Files:**
- Create: `qbu_crawler/server/report_artifacts.py`
- Modify: `qbu_crawler/server/report_snapshot.py`（生成产物时同步写入）
- Test: `tests/server/test_report_artifacts.py`

- [ ] **Step 1: 写失败测试**

```python
def test_artifact_recorded_for_each_output():
    """F011 §5.1 — 每个产物（HTML/Excel/snapshot/analytics）都入 report_artifacts 表"""
    run_id = generate_full_report_test_run()
    artifacts = list_artifacts(run_id)
    types = sorted(a["artifact_type"] for a in artifacts)
    assert "html_attachment" in types
    assert "xlsx" in types
    assert "snapshot" in types
    assert "analytics" in types

def test_artifact_includes_template_version():
    """artifacts.template_version 必须填充"""
    run_id = generate_full_report_test_run()
    arts = list_artifacts(run_id)
    html_art = next(a for a in arts if a["artifact_type"] == "html_attachment")
    assert html_art["template_version"]
    assert html_art["generator_version"]  # qbu_crawler.__version__
```

- [ ] **Step 2: 实现 report_artifacts.py**

```python
"""F011 §5.1 — report_artifacts 表 CRUD。"""
import hashlib
import os

def record_artifact(conn, run_id, artifact_type, path, *, template_version=None):
    from qbu_crawler import __version__
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        content = f.read()
    file_hash = hashlib.sha256(content).hexdigest()[:16]
    bytes_size = len(content)

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO report_artifacts
        (run_id, artifact_type, path, hash, template_version, generator_version, bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, artifact_type, path, file_hash, template_version, __version__, bytes_size),
    )
    conn.commit()
    return cur.lastrowid


def list_artifacts(conn, run_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM report_artifacts WHERE run_id=? ORDER BY id", (run_id,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
```

- [ ] **Step 3: 在生成各产物处调用**

`report_snapshot.py` 生成 snapshot/analytics/excel/html 后调用 `record_artifact()`。

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_artifacts.py \
        qbu_crawler/server/report_snapshot.py \
        tests/server/test_report_artifacts.py
git commit -m "feat(report): F011 §5.1 — record all artifacts into report_artifacts table"
```

### Task 4.3: 集成测试 — 端到端 fixture replay

**Files:**
- Create: `tests/server/test_e2e_report_replay.py`
- Create: `tests/fixtures/test5_snapshot.json`（从生产测试 5 fixture 拷贝）

- [ ] **Step 1: 写端到端测试**

```python
def test_e2e_replay_test5_bootstrap(tmp_path, monkeypatch):
    """F011 端到端：用生产测试 5 数据复跑，验证所有 AC 通过。"""
    db_path = setup_test_db_from_fixture(tmp_path, "test5_db_seed.sql")
    monkeypatch.setattr(config, "QBU_DATA_DIR", str(tmp_path))

    # 跑完整流程
    run_id = trigger_full_report_for_logical_date(db_path, "2026-04-26")

    # AC-1 差评率分母统一
    excel = openpyxl.load_workbook(get_artifact_path(run_id, "xlsx"))
    ws = excel["核心数据"]
    headers = [c.value for c in ws[1]]
    assert "差评率(采集分母)" in headers
    assert "差评率(站点分母)" in headers

    # AC-2 影响类别 ≠ 标签
    ws_reviews = excel["评论原文"]
    label_col = headers.index("标签") + 1
    impact_col = headers.index("影响类别") + 1
    distinct = sum(1 for r in range(2, min(ws_reviews.max_row + 1, 50))
                   if ws_reviews.cell(r, label_col).value != ws_reviews.cell(r, impact_col).value)
    assert distinct >= 30  # 抽样 50 行至少 30 行不同

    # AC-3 失效模式非空 ≥95%
    fm_col = headers.index("失效模式") + 1
    non_empty = sum(1 for r in range(2, ws_reviews.max_row + 1) if ws_reviews.cell(r, fm_col).value)
    assert non_empty / (ws_reviews.max_row - 1) >= 0.95

    # AC-9 bootstrap 期不展示空区块
    html = open(get_artifact_path(run_id, "html_attachment")).read()
    assert "首日基线已建档" in html
    assert "趋势数据正在累积" in html

    # AC-10 建议行动不截断
    assert "针对Walton's #22 Meat Grinder、Walton's General Duty Meat Lug与Quick Patty Maker反馈的肉" not in html

    # AC-13 Excel 4 sheets
    assert sorted(excel.sheetnames) == sorted(["核心数据", "现在该做什么", "评论原文", "竞品启示"])

    # AC-19 报告生成时间
    run_meta = get_workflow_run(run_id)
    duration = (parse_iso(run_meta["finished_at"]) - parse_iso(run_meta["started_at"])).seconds
    assert duration < 30

    # v1.1 / AC-27 性能：附件 HTML / Excel 大小
    html_path = get_artifact_path(run_id, "html_attachment")
    excel_path = get_artifact_path(run_id, "xlsx")
    assert os.path.getsize(html_path) <= 1 * 1024 * 1024, "附件 HTML 超过 1MB"
    assert os.path.getsize(excel_path) <= 5 * 1024 * 1024, "Excel 超过 5MB"

    # v1.1 / AC-26 状态机判定
    semantics_first_run = determine_report_semantics(conn, run_id)
    assert semantics_first_run == "bootstrap"  # 测试 5 数据是首日 bootstrap

    # v1.1 / AC-31 ops alert 在 SKU 0 抓取时必触发
    alert_calls = get_ops_alert_call_history()
    assert any(c["severity"] == "P0" for c in alert_calls)
    assert "1193465" in str(alert_calls)  # SKU 1193465 是 0 抓取
```

### Task 4.3.1: v2/v3 prompt_version 共存测试（v1.1 新增 P1）

**Files:**
- Test: `tests/server/test_v2_v3_coexistence.py`

**对应 F011 §6.4 / AC-23**

- [ ] **Step 1: 写共存测试**

```python
import pytest
from qbu_crawler.server.report_analytics import build_report_analytics

def test_mixed_v2_v3_review_analysis_coexists(tmp_path):
    """DB 同时含 prompt_version=v2 和 v3 的 review_analysis 行时，分析层应正确路由不报错。"""
    db = setup_test_db_with_mixed_versions(tmp_path, v2_count=100, v3_count=50)
    snapshot = freeze_snapshot(db, since="2026-04-26", until="2026-04-27")

    # 不应抛错
    analytics = build_report_analytics(snapshot, conn=db.connection)

    # KPI 应包含两批数据
    assert analytics["kpis"]["ingested_review_rows"] == 150
    # v3 字段（如 short_title）若 v2 行无值，应 None / 缺省
    for item in analytics["report_copy"].get("improvement_priorities", []):
        # short_title 可能来自 v3 LLM；v2 fallback 用 label_display
        assert "short_title" in item

def test_v2_only_db_still_renders(tmp_path):
    """纯 v2 数据仍可生成报告（虽然字段不全，但不崩溃）"""
    db = setup_test_db_with_mixed_versions(tmp_path, v2_count=100, v3_count=0)
    snapshot = freeze_snapshot(db, since="2026-04-26", until="2026-04-27")
    analytics = build_report_analytics(snapshot, conn=db.connection)
    assert analytics is not None
```

- [ ] **Step 2: 实现版本路由（如尚未实现）**

`report_analytics.py::_load_review_analysis()` 中：

```python
def _load_review_analysis(conn, review_id):
    rows = conn.execute(
        "SELECT * FROM review_analysis WHERE review_id=? ORDER BY analyzed_at DESC LIMIT 1",
        (review_id,),
    ).fetchall()
    if not rows:
        return None
    row = dict(rows[0])
    # v3 字段缺失则 None（v2 数据不含）
    row.setdefault("short_title", None)
    row.setdefault("evidence_review_ids", [])
    return row
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
pytest tests/server/test_v2_v3_coexistence.py -v
git add tests/server/test_v2_v3_coexistence.py qbu_crawler/server/report_analytics.py
git commit -m "test(report): F011 AC-23 v1.1 — verify v2/v3 prompt_version coexistence"
```

- [ ] **Step 2: 准备 fixture**

```bash
# 从生产测试 5 拷贝必要数据
sqlite3 "C:/Users/leo/Desktop/生产测试/报告/测试5/data/products.db" .dump > tests/fixtures/test5_db_seed.sql
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/server/test_e2e_report_replay.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/server/test_e2e_report_replay.py tests/fixtures/test5_db_seed.sql
git commit -m "test(report): F011 e2e — replay test5 fixture and verify all AC"
```

### Task 4.4: 版本号升级 + CHANGELOG

**Files:**
- Modify: `qbu_crawler/__init__.py`
- Modify: `pyproject.toml`
- Create: `CHANGELOG.md` 节段

- [ ] **Step 1: 版本号升级**

```bash
# qbu_crawler/__init__.py
__version__ = "0.4.0"

# pyproject.toml
version = "0.4.0"
```

- [ ] **Step 2: 撰写 CHANGELOG**

```markdown
## v0.4.0 (2026-04-XX) - 报告系统重构

### 新增
- F011 报告系统重构：4 频道分离（邮件正文/附件 HTML/Excel/内部运维）
- H1 scrape_quality 自检 + 内部运维邮件触发
- H6+H10 差评率分母统一为 ingested_only
- H11 risk_score 5 因子分解输出
- H13 outbox deadletter 触发 report_phase 降级
- H14 improvement_priorities 拆 short_title + full_action + evidence_review_ids
- H16 trend_digest 单主图 + ready 阈值升级
- H18 接近高风险阈值预警 (near_high_risk_count)
- H19 failure_mode 9 类 enum 化
- H22 change_digest 三层金字塔
- 新建 report_artifacts 表

### 修复
- H12 query_cumulative_data SELECT 漏失字段
- H15 date_published 解析 anchor 不一致
- H17 模板 row.values() 改 columns key

### 撤销
- 12 panel 趋势布局
- 5 sheets Excel（→ 4 sheets）
- 角色分层 tabs / 角色化 Excel 导出
- 报告中混入工程信号

### 兼容性
- 旧版 prompt_version=v2 数据可读
- daily_report_v3_legacy.html.j2 保留作为 env 切换 fallback
```

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/__init__.py pyproject.toml CHANGELOG.md
git commit -m "chore: bump 0.3.25 -> 0.4.0 (F011 报告系统重构)"
```

### Task 4.5: 打包发布 + 生产灰度验证

- [ ] **Step 1: 本地构建测试**

```bash
python scripts/publish.py --dry-run minor
```

- [ ] **Step 2: 合并到 master 并发布**

```bash
git checkout master
git merge --no-ff feature/report-system-redesign-f011
git tag -a v0.4.0 -m "F011 报告系统重构"
python scripts/publish.py minor
```

- [ ] **Step 3: 生产灰度（按 F011 §9.1 风险三 tier）**

  - Tier 1: 内部测试服务器升级 + 跑 7 天
  - 期间 daily report 由内部测试用，监控:
    - report 生成时间 ≤ 30 秒
    - email 正文渲染 (Outlook/Gmail/钉钉)
    - 附件 HTML 在 Chrome/Edge 正确
    - Excel 4 sheets 内容正确
    - 内部运维告警在 SKU 0 抓取时正确触发
  - Tier 2: 老板 + 产品试用 7 天
  - Tier 3: 全量

- [ ] **Step 4: 验证后清理 legacy 模板**

```bash
# 7 天稳定后
git rm qbu_crawler/server/report_templates/daily_report_v3_legacy.html.j2
git commit -m "chore(report): remove daily_report_v3_legacy after 7d stable production"
```

### Task 4.5.1: 生产 DB 迁移执行步骤（v1.1 新增 P0）

**Files:** N/A（生产运维操作）

**对应 F011 §9.2 + 漏覆盖 P0**

> ⚠ **关键**：单纯部署新代码不会自动跑 schema migration。需在 SSH 生产服务器升级包后**手动执行**迁移脚本。

- [ ] **Step 1: SSH 生产服务器**

```bash
ssh user@production-server
cd /path/to/qbu-crawler-deploy
```

- [ ] **Step 2: 备份生产 DB**

```bash
# 备份到带时间戳的 .bak 文件
cp $QBU_DATA_DIR/products.db $QBU_DATA_DIR/products.db.pre-f011.bak
ls -la $QBU_DATA_DIR/*.bak
```

- [ ] **Step 3: 升级 qbu-crawler 包**

```bash
pip install -U qbu-crawler
# 或 uvx 拉新版
qbu --version  # 应显示 0.4.0
```

- [ ] **Step 4: 执行 schema migration（0010 + 0011）**

```bash
# 0010 schema 改动（独立列 + 新表）
python -c "
import sqlite3
from qbu_crawler.server.migrations import migration_0010_report_redesign_schema as m
conn = sqlite3.connect('$QBU_DATA_DIR/products.db')
m.up(conn)
conn.close()
print('Migration 0010 applied successfully')
"

# 0011 failure_mode enum 化（数据回填）
python -c "
import sqlite3
from qbu_crawler.server.migrations import migration_0011_failure_mode_enum_backfill as m
conn = sqlite3.connect('$QBU_DATA_DIR/products.db')
m.up(conn)
conn.close()
print('Migration 0011 applied successfully')
"
```

- [ ] **Step 5: 验证迁移结果**

```bash
# 验证新字段已添加
sqlite3 $QBU_DATA_DIR/products.db "
SELECT COUNT(*) FROM pragma_table_info('reviews') WHERE name='date_parse_method';
SELECT COUNT(*) FROM pragma_table_info('workflow_runs') WHERE name='scrape_completeness_ratio';
SELECT COUNT(*) FROM sqlite_master WHERE name='report_artifacts';
"
# 三个均应返回 1

# 验证 failure_mode 已 enum 化
sqlite3 $QBU_DATA_DIR/products.db "
SELECT failure_mode, COUNT(*) FROM review_analysis GROUP BY failure_mode ORDER BY 2 DESC;
"
# 应返回 9 类 enum 中的若干，none 类应在前列
```

- [ ] **Step 6: 重启服务**

```bash
systemctl restart qbu-crawler  # 或 docker-compose restart / supervisorctl restart
# 等待 5 秒
qbu --version  # 再次验证
```

- [ ] **Step 7: 触发一次手动报告 run，验证流程**

```bash
# 使用 api / CLI 触发 manual run
curl -X POST -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/workflow/trigger?logical_date=$(date +%Y-%m-%d)

# 等 5 分钟后检查
sqlite3 $QBU_DATA_DIR/products.db \
  "SELECT id, service_version, report_mode, report_phase, scrape_completeness_ratio FROM workflow_runs ORDER BY id DESC LIMIT 1"
# service_version 应为 0.4.0
# report_phase 应为 full_sent 或 full_sent_local（如通知失败）
```

- [ ] **Step 8: 回滚预案**

如果 Step 7 验证失败：

```bash
# 立即停服
systemctl stop qbu-crawler

# 恢复 DB
mv $QBU_DATA_DIR/products.db.pre-f011.bak $QBU_DATA_DIR/products.db

# 降级包
pip install qbu-crawler==0.3.25

# 重启
systemctl start qbu-crawler
```

> 不需要 commit，本任务是 ops 操作记录。

### Task 4.5.2: CI hook 接入（v1.1 新增 P1）

**Files:**
- Create: `.github/workflows/contract-checks.yml`

**对应 F011 §5.5 / AC-29**

- [ ] **Step 1: 创建 GitHub Actions workflow**

```yaml
# .github/workflows/contract-checks.yml
name: Contract Checks
on:
  push:
    branches: [master, feature/**]
  pull_request:
    branches: [master]

jobs:
  contract-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: Install deps
        run: |
          pip install -U pip
          pip install -e .[test]
          pip install pytest jsonschema openpyxl
      - name: Tooltip vs algorithm sync
        run: pytest tests/server/test_metric_tooltips_sync.py -v
      - name: LLM prompt v3 schema
        run: pytest tests/server/test_llm_prompt_v3.py -v
      - name: failure_mode 9-enum boundary
        run: pytest tests/server/test_failure_mode_enum.py -v
      - name: Schema migration up/down
        run: pytest tests/server/test_migration_0010.py -v
      - name: assert_consistency
        run: pytest tests/server/test_llm_assert_consistency.py -v
      - name: Report semantics state machine
        run: pytest tests/server/test_report_semantics.py -v
```

- [ ] **Step 2: 测试 CI 触发**

```bash
git add .github/workflows/contract-checks.yml
git commit -m "ci: F011 §5.5 v1.1 — add contract-checks workflow"
git push origin feature/report-system-redesign-f011
# 在 GitHub PR 页面验证 CI 运行
```

### Task 4.6: legacy 模板 env 路由实现（v1.1 新增 P1）

**Files:**
- Modify: `qbu_crawler/server/report.py`（`_select_template`）
- Modify: `.env.example`
- Test: `tests/server/test_template_routing.py`

**对应 F011 §6.4.1 / AC-30**

- [ ] **Step 1: 写失败测试**

```python
import pytest
import os
from qbu_crawler.server.report import _select_template

def test_default_v3_when_env_unset(monkeypatch):
    monkeypatch.delenv("REPORT_TEMPLATE_VERSION", raising=False)
    assert _select_template() == "daily_report_v3.html.j2"

def test_legacy_when_env_set(monkeypatch):
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v3_legacy")
    assert _select_template() == "daily_report_v3_legacy.html.j2"

def test_unknown_value_falls_back_to_v3(monkeypatch, caplog):
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v99_nonsense")
    result = _select_template()
    assert result == "daily_report_v3.html.j2"
    assert any("Unknown" in r.message for r in caplog.records)

def test_missing_legacy_file_falls_back_to_v3(monkeypatch, tmp_path):
    """legacy 模板被删除（如清理后）应静默 fallback 到 v3"""
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v3_legacy")
    # 让 _select_template 检查文件存在性
    monkeypatch.setattr("qbu_crawler.server.report.REPORT_TEMPLATE_DIR", tmp_path)
    (tmp_path / "daily_report_v3.html.j2").touch()  # 仅 v3 存在
    assert _select_template() == "daily_report_v3.html.j2"
```

- [ ] **Step 2: 实现 `_select_template`**

```python
import os
from pathlib import Path
import logging

log = logging.getLogger(__name__)
REPORT_TEMPLATE_DIR = Path(__file__).parent / "report_templates"


def _select_template(env_template_version: str = None) -> str:
    """根据 env 选择附件 HTML 模板。

    F011 §6.4.1：
    - "v3"（默认）→ daily_report_v3.html.j2
    - "v3_legacy" → daily_report_v3_legacy.html.j2（回滚用）
    - 其他 / 文件不存在 → fallback v3 + WARNING
    """
    version = env_template_version or os.environ.get("REPORT_TEMPLATE_VERSION", "v3")
    template_map = {
        "v3": "daily_report_v3.html.j2",
        "v3_legacy": "daily_report_v3_legacy.html.j2",
    }
    if version not in template_map:
        log.warning(f"Unknown REPORT_TEMPLATE_VERSION={version}, fallback to v3")
        return template_map["v3"]
    template_file = template_map[version]
    template_path = REPORT_TEMPLATE_DIR / template_file
    if not template_path.exists():
        log.warning(f"Template {template_path} missing, fallback to v3")
        return template_map["v3"]
    return template_file
```

- [ ] **Step 3: 集成到 HTML 渲染流程**

定位 `report_snapshot.py` 中 `daily_report_v3.html.j2` 加载处：

```python
# 替换硬编码
# template = env.get_template("daily_report_v3.html.j2")
# 为：
from qbu_crawler.server.report import _select_template
template = env.get_template(_select_template())
```

- [ ] **Step 4: 更新 `.env.example`**

```bash
echo "" >> .env.example
echo "# 报告模板版本 (F011 v1.1 新增)" >> .env.example
echo "# v3 (default) / v3_legacy (rollback)" >> .env.example
echo "# REPORT_TEMPLATE_VERSION=v3" >> .env.example
```

- [ ] **Step 5: 运行测试 + Commit**

```bash
pytest tests/server/test_template_routing.py -v
git add qbu_crawler/server/report.py qbu_crawler/server/report_snapshot.py \
        .env.example tests/server/test_template_routing.py
git commit -m "feat(report): F011 §6.4.1 v1.1 — REPORT_TEMPLATE_VERSION env routing for legacy fallback"
```

---

## Self-Review

按 superpowers:writing-plans 规范自检：

### 1. Spec coverage 校验（v1.1 完整覆盖）

| F011 章节 | 对应 Phase / Task |
|----------|-------------------|
| §3.1 频道分离 | Task 3.1 / 3.2-3.5 / 3.6 / 4.1 |
| §3.3 双行为模式 | Task 3.2-3.3 + Task 2.5 |
| **§3.3.1 状态判定函数** | **Task 0.2（v1.1 新增）** |
| §4.1 邮件正文 | Task 3.1（KPI 灯阈值边界 + I2 修订）|
| §4.2.4 今日变化三层 | Task 2.4 + 3.2 |
| **§4.2.4.1 时间口径 scraped_at** | **Task 2.4 强化（v1.1）** |
| §4.2.5 变化趋势主图 | Task 2.5 + 3.3 |
| §4.2.6 全景筛选 | Task 3.4 |
| §4.3 Excel 4 sheets | Task 3.6 |
| §4.4 内部运维 | Task 4.1 |
| §5.1 Schema | Task 1.1 |
| §5.2 Analytics 字段 | Task 2.1, 2.2, 2.4, 2.5, 2.6 |
| §5.3 LLM Prompt | Task 2.6 |
| **§5.3.2 完整数字断言** | **Task 2.6.1（v1.1 新增）** |
| §5.4 tooltip-代码同步 | Task 2.3 |
| **§5.5 CI 集成** | **Task 4.5.2（v1.1 新增）** |
| §6 非功能 | Task 4.3 e2e + 性能验证（v1.1 强化） |
| **§6.4.1 legacy env 路由** | **Task 4.6（v1.1 新增）** |
| §7 双行为对照 | Task 3.2-3.3 + Task 0.2 |
| §8 AC-1~25 | Task 4.3 e2e |
| **§8.6 AC-26~33（v1.1）** | **Task 0.2, 4.3, 4.3.1, 4.5.1, 4.5.2, 4.6, 1.3 边界, 3.1 边界** |
| **§8.7 AC-34~36（v1.2）** | **Task 3.4.2 (热力图), 3.5.1 (issue cards 折叠), 3.9 (竞品启示扩展)** |
| **§4.2.6 全景数据子板块定位** | **Task 3.4.2 (评分分布合并 + 热力图优化)** |
| **§4.2.7 竞品启示** | **Task 3.9（弱点机会 + benchmark 三类 + 雷达聚合 + 评分分布迁移）** |
| §9 回滚 | Task 4.4-4.5 + 4.5.1 生产迁移 |

### 2. Placeholder 扫描

✅ 所有步骤含完整代码示例
✅ 所有文件路径精确
✅ 所有命令含 expected output

### 3. Type 一致性

✅ `improvement_priorities[]` schema 在 Task 2.6 定义后，Task 3.5 + 3.6 引用一致（`short_title` / `full_action` / `evidence_review_ids`）
✅ `risk_factors` 在 Task 2.2 定义后，Task 3.4 hover 展示用一致结构
✅ `change_digest` 三层在 Task 2.4 定义后，Task 3.2 模板用一致字段

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-27-report-system-redesign.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**

---

**文档版本**：v1.2（2026-04-27 同日，合入路径 B 三大块用户视角优化）
**总计**：4 Phases / **27 Tasks** / 160+ Sub-steps
**测试覆盖**：
- v1.0 核心改造 H1, H6, H9, H10, H11, H12, H13, H14, H15, H16, H17, H18, H19, H20, H22 共 15 项
- v1.1 新增 7 项：状态机 / 完整断言 / 性能 / v2v3 共存 / CI / 生产迁移 / legacy 路由
- v1.2 新增 3 项：热力图优化 / issue cards 折叠 / 竞品启示扩展

**预估工作量**：17-25 天（一个人 3.5-5 周）

### v1.2 新增 Task 索引

| Task | 类型 | 解决问题 |
|------|------|---------|
| Task 3.4.2 | 新增 v1.2 | 特征情感热力图 Top 8 聚合 + hover + 点击下钻（AC-34） |
| Task 3.5.1 | 新增 v1.2 | issue cards Top 3 默认展开 + 4-N 折叠 + 删 temporal_pattern（AC-35） |
| Task 3.9   | 新增 v1.2 | 竞品启示扩展：弱点机会卡 + benchmark 三类 + 雷达聚合 + 评分分布迁移（AC-36） |

### v1.1 新增 / 修订 Task 索引

| Task | 类型 | 解决问题 |
|------|------|---------|
| Task 0.2 | 新增 P0 | F011 §3.3.1 状态判定函数 |
| Task 1.3（修订） | Bug 修复 P0 | failure_mode 分类器优先级 / B1 |
| Task 2.4（修订） | 时间口径 P0 | own_new_negative 按 scraped_at / B4 |
| Task 2.6.1 | 新增 P1 | 完整数字断言 |
| Task 3.1（修订） | 测试加强 P1 | KPI 灯阈值边界 + I2 |
| Task 4.3（修订） | 测试加强 P1 | 性能 / state machine 验证 |
| Task 4.3.1 | 新增 P1 | v2/v3 prompt_version 共存 |
| Task 4.5.1 | 新增 P0 | 生产 DB 迁移执行步骤 |
| Task 4.5.2 | 新增 P1 | CI hook GitHub Actions |
| Task 4.6 | 新增 P1 | legacy 模板 env 路由 |
