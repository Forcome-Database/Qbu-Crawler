# 测试7报告 P3 状态模型与旧 fallback 下线 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将报告生成、业务邮件送达、workflow 通知送达从 `report_phase` 中拆出为正式 DB 状态，并让用户可见渲染主路径只消费 `report_user_contract`。

**Architecture:** 新增幂等 migration 和状态同步 helper，workflow/notifier/manifest 统一读写 DB 状态；旧 analytics 字段只允许在 adapter 层转换为 contract，renderer 和模板使用 contract-first strict mode。P3 不做视觉改版，也不新增运维 UI。

**Tech Stack:** Python 3.10+, SQLite migrations, pytest, Jinja2, openpyxl, existing workflow/notifier/report_contract/report_manifest pipeline.

---

## Entry Context

- 设计文档：`docs/superpowers/specs/2026-04-28-test7-report-p3-state-and-fallback-design.md`
- 审计文档：`docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- P2 devlog：`docs/devlogs/D023-test9-run-log-and-p2-manifest.md`
- P3 原则：
  - `report_phase` 不再被解释为 delivery 成功。
  - 用户业务报告不展示运维诊断。
  - 旧 analytics 字段只能在 adapter 层消费。
  - migration/backfill 必须幂等。

---

## File Map

| File | Responsibility | Tasks |
|---|---|---|
| `qbu_crawler/server/migrations/migration_0012_report_status_columns.py` | 新增状态列与 backfill | T1 |
| `qbu_crawler/models.py` | init_db 接入 migration，新增状态读写 helper | T1, T2 |
| `qbu_crawler/server/report_status.py` | 从 artifacts/outbox/email result 推导并同步 DB 状态 | T2 |
| `qbu_crawler/server/workflows.py` | 报告生成、邮件结果、通知入队时写状态 | T3 |
| `qbu_crawler/server/notifier.py` | outbox sent/deadletter 后同步通知状态 | T3 |
| `qbu_crawler/server/report_manifest.py` | manifest 优先消费 DB 状态 | T3 |
| `qbu_crawler/config.py` | 新增 `REPORT_CONTRACT_STRICT_MODE` | T4 |
| `qbu_crawler/server/report_common.py` | 明确 legacy adapter 边界 | T4 |
| `qbu_crawler/server/report_html.py` | strict contract 渲染入口 | T4 |
| `qbu_crawler/server/report.py` | Excel / 邮件 strict contract guard | T4 |
| `tests/server/test_report_status_migration.py` | migration/backfill 测试 | T1 |
| `tests/server/test_report_status_sync.py` | workflow/notifier 状态同步测试 | T2, T3 |
| `tests/server/test_report_manifest.py` | DB status 优先级补强 | T3 |
| `tests/server/test_report_contract_strict_mode.py` | strict mode 与旧 fallback 下线测试 | T4 |
| `tests/server/test_test7_artifact_replay.py` | 测试7 replay 状态/用户报告隔离断言 | T5 |
| `docs/devlogs/D024-test7-report-p3-state-and-fallback.md` | P3 实施记录 | T6 |

---

## Chunk 1: DB 状态列与 Backfill

### Task 1: 新增 workflow report status migration

**Files:**
- Create: `qbu_crawler/server/migrations/migration_0012_report_status_columns.py`
- Modify: `qbu_crawler/models.py`
- Test: `tests/server/test_report_status_migration.py`

- [ ] **Step 1.1: 写失败测试：旧库 migration 增加状态列**

Create `tests/server/test_report_status_migration.py`:

```python
import sqlite3

from qbu_crawler.server.migrations import migration_0012_report_status_columns as mig


def test_migration_0012_adds_report_status_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            status TEXT,
            report_phase TEXT,
            logical_date TEXT,
            excel_path TEXT,
            analytics_path TEXT,
            error TEXT
        )
    """)

    mig.up(conn)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
    assert "report_generation_status" in cols
    assert "email_delivery_status" in cols
    assert "workflow_notification_status" in cols
    assert "delivery_last_error" in cols
    assert "delivery_checked_at" in cols
```

- [ ] **Step 1.2: 运行测试确认失败**

Run:

```bash
uv run --frozen pytest tests/server/test_report_status_migration.py::test_migration_0012_adds_report_status_columns -q
```

Expected: FAIL，migration 文件不存在。

- [ ] **Step 1.3: 实现 migration up/down**

Create `qbu_crawler/server/migrations/migration_0012_report_status_columns.py`:

```python
UP_SQL = [
    "ALTER TABLE workflow_runs ADD COLUMN report_generation_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE workflow_runs ADD COLUMN email_delivery_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE workflow_runs ADD COLUMN workflow_notification_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE workflow_runs ADD COLUMN delivery_last_error TEXT",
    "ALTER TABLE workflow_runs ADD COLUMN delivery_checked_at TEXT",
]
```

规则：
- duplicate column 时跳过。
- down() 尽力 drop column，旧 SQLite 不支持时 warning 后跳过。

- [ ] **Step 1.4: 接入 `models.init_db()`**

在 `models.init_db()` 的 versioned migration 区域导入并执行 `migration_0012_report_status_columns.up(conn)`。

- [ ] **Step 1.5: 写失败测试：backfill 从 artifact/outbox 推导状态**

```python
def test_migration_0012_backfills_generated_and_deadletter():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            status TEXT,
            report_phase TEXT,
            logical_date TEXT,
            excel_path TEXT,
            analytics_path TEXT,
            error TEXT
        );
        CREATE TABLE report_artifacts (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            artifact_type TEXT,
            path TEXT
        );
        CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY,
            kind TEXT,
            status TEXT,
            payload TEXT,
            last_error TEXT
        );
        INSERT INTO workflow_runs VALUES (1, 'completed', 'full_sent', '2026-04-28', 'report.xlsx', 'analytics.json', NULL);
        INSERT INTO report_artifacts (run_id, artifact_type, path) VALUES (1, 'xlsx', 'report.xlsx');
        INSERT INTO notification_outbox (kind, status, payload, last_error)
        VALUES ('workflow_full_report', 'deadletter', '{"run_id": 1, "email_status": "success"}', 'bridge returned HTTP 401');
    """)

    mig.up(conn)
    mig.backfill(conn)

    row = conn.execute("SELECT * FROM workflow_runs WHERE id=1").fetchone()
    assert row["report_generation_status"] == "generated"
    assert row["email_delivery_status"] == "sent"
    assert row["workflow_notification_status"] == "deadletter"
    assert "bridge returned HTTP 401" in row["delivery_last_error"]
```

- [ ] **Step 1.6: 实现 `backfill(conn, force=False)`**

实现要求：
- 只更新 `unknown` 状态，除非 `force=True`。
- 使用 JSON1 时通过 `json_extract(payload, '$.run_id')` 精准匹配 run id。
- JSON1 不可用时降级 Python JSON 解析。

- [ ] **Step 1.7: 跑 migration 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_status_migration.py -q
```

Expected: PASS。

---

## Chunk 2: 状态同步 Helper

### Task 2: 新增 report status 同步层

**Files:**
- Create: `qbu_crawler/server/report_status.py`
- Modify: `qbu_crawler/models.py`
- Test: `tests/server/test_report_status_sync.py`

- [ ] **Step 2.1: 写失败测试：models 可更新状态字段**

```python
from qbu_crawler import models


def test_update_workflow_report_status_persists_columns(tmp_path, monkeypatch):
    from qbu_crawler import config

    db = tmp_path / "status.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()
    run = models.create_workflow_run({
        "workflow_type": "daily",
        "status": "reporting",
        "logical_date": "2026-04-28",
        "trigger_key": "daily:2026-04-28",
    })

    models.update_workflow_report_status(
        run["id"],
        report_generation_status="generated",
        email_delivery_status="sent",
        workflow_notification_status="deadletter",
        delivery_last_error="bridge returned HTTP 401",
    )

    loaded = models.get_workflow_run(run["id"])
    assert loaded["report_generation_status"] == "generated"
    assert loaded["email_delivery_status"] == "sent"
    assert loaded["workflow_notification_status"] == "deadletter"
```

- [ ] **Step 2.2: 实现 `models.update_workflow_report_status()`**

只允许更新 P3 状态列：

```python
def update_workflow_report_status(run_id: int, **fields) -> dict:
    allowed = {
        "report_generation_status",
        "email_delivery_status",
        "workflow_notification_status",
        "delivery_last_error",
        "delivery_checked_at",
    }
```

- [ ] **Step 2.3: 写失败测试：从 outbox 推导 workflow 通知状态**

Create `tests/server/test_report_status_sync.py`:

```python
from qbu_crawler.server.report_status import derive_workflow_notification_status


def test_derive_workflow_notification_status_deadletter_wins():
    status = derive_workflow_notification_status([
        {"kind": "workflow_started", "status": "sent"},
        {"kind": "workflow_full_report", "status": "deadletter", "last_error": "401"},
    ])

    assert status["workflow_notification_status"] == "deadletter"
    assert status["delivery_last_error"] == "401"
```

- [ ] **Step 2.4: 实现 `report_status.py`**

函数：
- `derive_email_delivery_status(full_report_email: dict | None, payload: dict | None) -> str`
- `derive_workflow_notification_status(notifications: list[dict]) -> dict`
- `sync_workflow_report_status(conn, run_id: int) -> dict`

不要发送邮件，不要访问网络，只做 DB 状态推导与写入。

- [ ] **Step 2.5: 跑状态同步测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_status_sync.py -q
```

Expected: PASS。

---

## Chunk 3: Workflow / Notifier / Manifest 接线

### Task 3: 将状态同步接入生产链路

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `qbu_crawler/server/notifier.py`
- Modify: `qbu_crawler/server/report_manifest.py`
- Test: `tests/server/test_report_status_sync.py`
- Test: `tests/server/test_report_manifest.py`

- [ ] **Step 3.1: 写失败测试：full report 成功后 DB 状态为 generated/pending**

在 `tests/server/test_report_status_sync.py` 增加 workflow 最小测试：

```python
def test_workflow_full_report_sets_generation_and_pending_notification(...):
    # 使用现有 workflow test helper seed run/task/snapshot
    # monkeypatch generate_report_from_snapshot 返回 email success + paths
    # 调用 worker._advance_run()
    # 断言 report_generation_status == "generated"
    # 断言 email_delivery_status == "sent"
    # 断言 workflow_notification_status == "pending"
```

- [ ] **Step 3.2: 修改 `WorkflowWorker` 写状态**

接线点：
- snapshot freeze 后：`report_generation_status="pending"`。
- full report 成功后：`report_generation_status="generated"`。
- email success/failure/skipped：写 `email_delivery_status`。
- enqueue `workflow_full_report` 后：写 `workflow_notification_status="pending"`。
- report generation 最终失败：写 `report_generation_status="failed"` 和 `delivery_last_error`。

- [ ] **Step 3.3: 写失败测试：deadletter 后状态同步**

```python
def test_deadletter_updates_db_status_and_manifest(tmp_path, monkeypatch):
    # seed workflow_runs with full_sent + generated/sent/pending
    # seed notification_outbox deadletter
    # call downgrade_report_phase_on_deadletter(conn, run_id)
    # assert workflow_notification_status == "deadletter"
    # assert report_phase == "full_sent_local"
```

- [ ] **Step 3.4: 修改 `notifier.downgrade_report_phase_on_deadletter()`**

在降级后调用 `sync_workflow_report_status(conn, run_id)`，再刷新 analytics manifest。

- [ ] **Step 3.5: 修改 `report_manifest.build_report_manifest()`**

优先读 DB 字段：

```python
db_status = {
    "report_generation_status": run.get("report_generation_status") or "unknown",
    "email_delivery_status": run.get("email_delivery_status") or "unknown",
    "workflow_notification_status": run.get("workflow_notification_status") or "unknown",
}
```

布尔字段从 DB 状态派生：
- `report_generated = report_generation_status == "generated"`，unknown 时再回退 artifact 推导。
- `email_delivered = email_delivery_status == "sent"`。
- `workflow_notification_delivered = workflow_notification_status == "sent"`。

- [ ] **Step 3.6: 跑 workflow/manifest 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_status_sync.py tests/server/test_report_manifest.py tests/server/test_internal_ops_alert.py tests/server/test_workflow_ops_alert_wiring.py -q
```

Expected: PASS。

---

## Chunk 4: Contract Strict Mode 与旧 fallback 下线

### Task 4: renderer 主路径只消费 contract

**Files:**
- Modify: `qbu_crawler/config.py`
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_report_contract_strict_mode.py`
- Test: `tests/server/test_report_contract_renderers.py`

- [ ] **Step 4.1: 写失败测试：strict mode 下旧 analytics 通过 adapter 进入 contract**

Create `tests/server/test_report_contract_strict_mode.py`:

```python
from qbu_crawler.server.report_common import normalize_deep_report_analytics


def test_strict_mode_adapts_legacy_analytics_once():
    analytics = {
        "report_semantics": "bootstrap",
        "self": {
            "top_negative_clusters": [{
                "label_code": "structure_design",
                "label_display": "结构设计",
                "review_count": 3,
                "example_reviews": [{"id": 1, "body_cn": "尺寸不合适"}],
            }]
        },
        "report_copy": {
            "improvement_priorities": [{
                "label_code": "structure_design",
                "full_action": "复核结构尺寸",
                "evidence_review_ids": [1],
                "affected_products": ["A"],
            }]
        },
    }

    normalized = normalize_deep_report_analytics(analytics)

    assert normalized["report_user_contract"]["action_priorities"][0]["full_action"] == "复核结构尺寸"
    assert normalized["report_user_contract"]["issue_diagnostics"][0]["label_code"] == "structure_design"
```

- [ ] **Step 4.2: 新增配置 `REPORT_CONTRACT_STRICT_MODE`**

在 `config.py` 增加：

```python
REPORT_CONTRACT_STRICT_MODE = _env_bool("REPORT_CONTRACT_STRICT_MODE", True)
```

- [ ] **Step 4.3: 标记 contract source**

`build_report_user_contract()` 增加：

```json
"contract_source": "provided|legacy_adapter|generated"
```

渲染入口如果 contract 缺少真实 snapshot context，应刷新并保留 source。

- [ ] **Step 4.4: 写失败测试：用户报告不展示运维诊断**

```python
def test_business_html_does_not_render_ops_diagnostics():
    analytics = {
        "report_semantics": "bootstrap",
        "report_user_contract": {
            "bootstrap_digest": {
                "baseline_summary": {"headline": "监控起点已建立", "product_count": 1, "review_count": 2},
                "immediate_attention": [],
            },
            "delivery": {
                "deadletter_count": 3,
                "workflow_notification_delivered": False,
            },
        },
        "data_quality": {"low_coverage_products": ["SKU-X"]},
    }

    html = _render_v3_html_string({"logical_date": "2026-04-28", "products": [], "reviews": []}, analytics)

    assert "deadletter" not in html
    assert "低覆盖产品" not in html
    assert "SKU-X" not in html
```

- [ ] **Step 4.5: 禁止新增模板直接消费旧字段**

添加静态测试，扫描主模板：

```python
def test_v3_template_does_not_render_ops_diagnostics():
    text = Path("qbu_crawler/server/report_templates/daily_report_v3.html.j2").read_text(encoding="utf-8")
    assert "low_coverage_products" not in text
    assert "deadletter_count" not in text
    assert "estimated_date_ratio" not in text
```

对于 `top_negative_clusters` 等仍在 normalize 内部使用的字段，不做模板级硬禁用，避免误伤 chart 数据。

- [ ] **Step 4.6: 跑 strict mode 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_contract_strict_mode.py tests/server/test_report_contract_renderers.py tests/server/test_attachment_html_issues.py -q
```

Expected: PASS。

---

## Chunk 5: 测试7 Replay 与全量回归

### Task 5: 补测试7状态/展示隔离 replay

**Files:**
- Modify: `tests/server/test_test7_artifact_replay.py`
- Test: `tests/server/test_test7_artifact_replay.py`

- [ ] **Step 5.1: 写 replay 断言：业务 HTML 不展示 ops 状态**

```python
def test_test7_replay_business_html_hides_ops_diagnostics():
    html = render_attachment_html(snapshot, analytics_with_deadletter_and_low_coverage)
    assert "deadletter" not in html
    assert "低覆盖产品" not in html
    assert "估算日期占比" not in html
```

- [ ] **Step 5.2: 写 replay 断言：analytics manifest 显示 DB delivery 状态**

```python
def test_test7_replay_manifest_includes_db_status(tmp_path):
    # seed workflow run + artifact + deadletter
    # update_analytics_delivery_from_db()
    # assert report_user_contract.delivery.db_status.workflow_notification_status == "deadletter"
```

- [ ] **Step 5.3: 跑 replay 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_test7_artifact_replay.py -q
```

Expected: PASS。

---

## Chunk 6: 文档与最终验证

### Task 6: 文档、审查、全量测试

**Files:**
- Create: `docs/devlogs/D024-test7-report-p3-state-and-fallback.md`
- Modify: `AGENTS.md`

- [ ] **Step 6.1: 写 devlog**

记录：
- migration 字段和 backfill 规则。
- workflow/notifier 状态同步点。
- strict contract mode 的边界。
- 为什么运维诊断不进入业务报告。

- [ ] **Step 6.2: 更新 `AGENTS.md` 报表治理增量**

补充：
- `qbu_crawler/server/report_status.py`
- `qbu_crawler/server/migrations/migration_0012_report_status_columns.py`
- P3 状态字段语义。

- [ ] **Step 6.3: 跑定向测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_status_migration.py tests/server/test_report_status_sync.py tests/server/test_report_manifest.py tests/server/test_report_contract_strict_mode.py tests/server/test_test7_artifact_replay.py -q
```

Expected: PASS。

- [ ] **Step 6.4: 跑全量测试**

Run:

```bash
uv run --frozen pytest -q
```

Expected: PASS。

- [ ] **Step 6.5: 代码审查**

检查点：
- 是否有用户业务报告渲染 deadletter / 低覆盖 SKU / 估算日期占比。
- 是否还有模板直接依赖旧字段新增逻辑。
- migration 是否可重复执行。
- deadletter 后 DB、manifest、analytics delivery 是否一致。

- [ ] **Step 6.6: 提交**

Run:

```bash
git add qbu_crawler/server/migrations/migration_0012_report_status_columns.py qbu_crawler/server/report_status.py qbu_crawler/models.py qbu_crawler/server/workflows.py qbu_crawler/server/notifier.py qbu_crawler/server/report_manifest.py qbu_crawler/server/report_common.py qbu_crawler/server/report_html.py qbu_crawler/server/report.py qbu_crawler/config.py tests/server/test_report_status_migration.py tests/server/test_report_status_sync.py tests/server/test_report_manifest.py tests/server/test_report_contract_strict_mode.py tests/server/test_test7_artifact_replay.py docs/devlogs/D024-test7-report-p3-state-and-fallback.md AGENTS.md
git commit -m "修复：测试7 P3报告状态模型与契约收口"
```

---

## Review Checklist

- [ ] P3 没有把运维诊断重新放回用户业务报告。
- [ ] DB 状态字段能独立回答：本地产物是否生成、业务邮件是否送达、workflow 通知是否送达。
- [ ] `report_phase` 不再作为 delivery 成功判断。
- [ ] `report_manifest` 与 DB 状态一致。
- [ ] 旧 analytics fallback 只在 adapter 层出现。
- [ ] 全量测试通过。
