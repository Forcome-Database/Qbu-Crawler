# P009 — Audit Batch 2 Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 D015 之后 2026-04-17 第二轮端到端审计发现的 **4 🔴 + 6 🟡 + 4 P008 follow-up** 共 14 项 Bug / 缺陷，保证任务状态时间戳、翻译覆盖率、调度器时区、通知清理与 P008 后续事项正确。

**Architecture:** TDD — 每 Task 先写失败测试 → 最小补丁 → 验证通过 → commit。所有修改限定在已存在模块，不新建包。未提交改动（`category_inferrer.py` / `base.py` 等）会在本计划首若干 Task 合并硬化再进入发布链路。

**Tech Stack:** Python 3.10+ / SQLite / pytest / DrissionPage / FastAPI

**Scope (本计划覆盖)**:
- **B1** — `mark_task_lost` 把 SQL 表达式 `_NOW_SHANGHAI` 当字面值绑定（D015 遗留 #1）
- **B4** — `_launch_with_user_data` 的 `stderr=PIPE` 无消费者，Chrome 写满 64KB 缓冲区阻塞
- **B5** — `sync_new_skus` 仅在 `status != "reporting"` 分支调用，进程重启后 run 恢复为 `reporting` 会重复 LLM 请求
- **B6** — 翻译 stalled 后强行生成报告无覆盖率阈值保护
- **I1** — `_infer_one_batch` 单批 LLM 异常阻断后续全部批次
- **I2** — `category_inferrer._append_csv` CLI 与服务并发写无文件锁
- **I3** — `cleanup_old_notifications` 定义但从未被调用，`notification_outbox` 无限增长；且用 UTC 与项目 Shanghai 约定冲突
- **I4** — `mark_notification_failure` 不更新 `tasks.notified_at`，失败通知与"未尝试"无法区分
- **I5** — `_logical_date_window` 返回 ISO 字符串硬编码 `+08:00` 字面串而非 tzinfo-aware 对象
- **I6** — `WorkflowWorker._run` 紧自旋 `while process_once()`，无最小 sleep 防 CPU 飙升
- **F1 (D015#3)** — `generate_full_report_from_snapshot` 加显式 `report_tier` 参数，替换 `_meta` fallback
- **F2 (D015#4)** — `recurrent → receding (R2)` / `recurrent → dormant (R3)` 无显式单测
- **F3 (D015#5)** — 真正冷启动 `is_partial` 检测引入 `earliest_review_scraped_at`
- **F4 (D015#6)** — `category_inferrer` 与 `_PROMPT` 的差评率 / confidence 单位歧义澄清

**Out of scope（下一批次处理）**:
- 🟡 `product_snapshots` 写入从未读（需要先决策：保留 vs 删除）
- 🟡 `REPORT_DIR` 不跟随 `QBU_DATA_DIR`
- 🟡 Cross-tier 数据聚合分歧（daily vs weekly vs monthly severity 不一致）
- 🟡 Translation worker DB-as-Queue 无 claim/lease
- 🟡 DST 边界防护（Shanghai 无 DST，短期可忽略）
- P008 审计推迟的 10🟡+9🟢 observable 类 issue（详见 `docs/plans/P008-audit-fixes-implementation.md` § Out of scope）

**Source:** 端到端审计来自 2026-04-17 4 agent 并行对账结果 + D015 devlog § "遗留事项 / Follow-ups"。

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `qbu_crawler/models.py` | B1 `mark_task_lost` 实际时间戳；I4 `mark_notification_failure` tasks 状态联动；F3 `earliest_review_scraped_at` 查询 |
| Modify | `qbu_crawler/scrapers/base.py` | B4 stderr 消费线程 / DEVNULL |
| Modify | `qbu_crawler/server/category_inferrer.py` | I1 per-batch 异常隔离；I2 文件锁；F4 prompt 单位澄清 |
| Modify | `qbu_crawler/server/workflows.py` | B5 `sync_new_skus` 幂等 flag；I5 `_logical_date_window` tzinfo；I6 min sleep |
| Modify | `qbu_crawler/server/report_snapshot.py` | B6 翻译覆盖率 gate；F1 显式 `report_tier` 参数；F3 真正冷启动逻辑 |
| Modify | `qbu_crawler/server/notifier.py` | I3 启动时调用 `cleanup_old_notifications` |
| Modify | `qbu_crawler/config.py` | I3 `NOTIFICATION_RETENTION_DAYS` 配置项；B6 `TRANSLATION_COVERAGE_MIN` 配置项 |
| Modify | `tests/test_notifier.py` | I3/I4 测试 |
| Modify | `tests/test_p008_phase4.py` | F2 R2/R3 显式单测 |
| Create | `tests/test_p009_audit_batch2.py` | B1/B4/B5/B6/I1/I2/I5/I6/F1/F3/F4 综合测试 |

---

## Phase 1 — Critical data correctness

### Task 1: B1 修正 `mark_task_lost` SQL 字面值绑定

**Files:**
- Modify: `qbu_crawler/models.py:562-588`
- Test: `tests/test_p009_audit_batch2.py`

问题：`models.py:571` 使用 `finished_at = finished_at or _NOW_SHANGHAI`。`_NOW_SHANGHAI` 是 SQL 表达式字符串 `"datetime('now', '+8 hours')"`，在 `conn.execute(..., (error_message, error_code, finished_at, ...))` 里它作为 **参数值** 被绑定，存入 DB 的是字面值字符串而非计算后的时间戳。后果：所有丢失任务的 `finished_at` 字段是一模一样的字面文本，历史审计彻底失效。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_p009_audit_batch2.py`：

```python
"""P009 audit batch 2 — TDD test suite."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

from qbu_crawler import config, models


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """独立 DB，避免污染 data/products.db。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    models.init_db()
    return str(db_path)


def test_mark_task_lost_writes_real_timestamp_not_sql_literal(fresh_db):
    """finished_at 字段必须是可解析的 ISO 时间戳，不是字面的 SQL 表达式文本。"""
    models.save_task({
        "id": "T1",
        "kind": "scrape",
        "status": "running",
        "params": {"urls": []},
        "created_at": config.now_shanghai().isoformat(),
    })
    ok = models.mark_task_lost("T1")
    assert ok
    row = models.get_task("T1")
    ft = row["finished_at"]
    # 不能是 SQL 表达式字面值
    assert "datetime(" not in ft
    assert "+8 hours" not in ft
    # 必须是可解析的时间戳
    parsed = datetime.fromisoformat(ft)
    assert parsed is not None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_p009_audit_batch2.py::test_mark_task_lost_writes_real_timestamp_not_sql_literal -v
```

Expected: FAIL — finished_at 等于 `"datetime('now', '+8 hours')"` 字符串。

- [ ] **Step 3: 修正实现**

修改 `qbu_crawler/models.py:571`：

```python
def mark_task_lost(
    task_id: str,
    error_code: str = "worker_lost",
    error_message: str = "Task lost during execution",
    finished_at: str | None = None,
) -> bool:
    """Mark a stale running task as failed so it can be reconciled."""
    conn = get_conn()
    try:
        finished_at = finished_at or now_shanghai().isoformat()
        cursor = conn.execute(
            """
            UPDATE tasks
            SET status = 'failed',
                error = ?,
                system_error_code = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
            """,
            (error_message, error_code, finished_at, finished_at, task_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_mark_task_lost_writes_real_timestamp_not_sql_literal -v
```

Expected: PASS

- [ ] **Step 5: 回归全套**

```bash
uv run pytest tests/ -x --ignore=tests/test_v3_modes.py -q
```

Expected: 无新增失败（`test_v3_modes.py` 2 个 pre-existing 失败已在 D015 登记）。

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/test_p009_audit_batch2.py
git commit -m "fix(models): mark_task_lost writes real timestamp instead of SQL literal (B1)"
```

---

### Task 2: B4 Chrome stderr PIPE deadlock

**Files:**
- Modify: `qbu_crawler/scrapers/base.py:181-196`（当前未提交改动）
- Test: `tests/test_p009_audit_batch2.py`

问题：未提交改动里 `_launch_with_user_data` 把 `stderr=subprocess.PIPE`，但正常路径下从不 `read()`；只有在 `proc.poll() is not None` 后才读 500 字节。Chrome 启动时向 stderr 写入可观数据（GPU/networking/扩展日志），pipe buffer 默认 64KB，写满后 Chrome 阻塞在 `write()` 系统调用，`proc.poll()` 永返 `None` 直到 60s 超时——掩盖了早退诊断初衷。

解决方案：后台 drain 线程持续消费 stderr，进程退出后线程自然结束，`.read()` 时可取到累积内容。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_p009_audit_batch2.py`：

```python
def test_chrome_stderr_does_not_block_on_64kb_output(tmp_path):
    """模拟：子进程往 stderr 写 >64KB 数据，父进程不显式读取，进程不能被 pipe buffer 阻塞。"""
    import subprocess
    import sys
    import threading
    import time as _time

    # 子进程脚本：写 100KB 到 stderr 然后 sleep 5s。
    script = (
        "import sys; sys.stderr.write('X' * 102400); sys.stderr.flush(); "
        "import time; time.sleep(5)"
    )

    # 模仿 base.py 修复后的用法：后台 drain 线程消费 stderr
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    buf: list[bytes] = []

    def _drain():
        try:
            for chunk in iter(lambda: proc.stderr.read(4096), b""):
                buf.append(chunk)
        except Exception:
            pass

    t = threading.Thread(target=_drain, daemon=True)
    t.start()

    # 等 1 秒，在未排空 pipe 的情况下，Chrome-like 子进程应该仍在 sleep；
    # 如果 drain 正确工作，poll() 应该返回 None 且不 hang。
    _time.sleep(1.5)
    assert proc.poll() is None, "子进程应仍在 sleep，不应崩溃"

    proc.terminate()
    proc.wait(timeout=3)
    t.join(timeout=2)
    assert not t.is_alive()
    assert len(b"".join(buf)) >= 102400, "drain 线程必须完整读到 stderr 数据"
```

- [ ] **Step 2: 运行测试（当前通过，仅验证 drain 模式可用）**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_chrome_stderr_does_not_block_on_64kb_output -v
```

Expected: PASS（此测试验证正确模式；失败说明环境/threading 有坑）。

- [ ] **Step 3: 修改 `base.py` 采用 drain 模式**

修改 `qbu_crawler/scrapers/base.py` `_launch_with_user_data` 相关代码块（即未提交 diff 中使用 `stderr=subprocess.PIPE` 的位置）：

```python
        # 启动 Chrome（用 drain 线程持续消费 stderr，避免 pipe buffer 阻塞）
        import threading as _threading

        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        _stderr_buf: list[bytes] = []

        def _drain_stderr(pipe, buf):
            try:
                for chunk in iter(lambda: pipe.read(4096), b""):
                    buf.append(chunk)
                    # 限制总量防内存泄漏
                    if sum(len(c) for c in buf) > 1_000_000:
                        buf.clear()
            except Exception:
                pass

        _drain_thread = _threading.Thread(
            target=_drain_stderr,
            args=(proc.stderr, _stderr_buf),
            daemon=True,
        )
        _drain_thread.start()

        for _ in range(60):
            time.sleep(1)
            if proc.poll() is not None:
                _drain_thread.join(timeout=1)
                stderr = (b"".join(_stderr_buf) or b"").decode(
                    "utf-8", errors="ignore",
                )[-500:]
                raise RuntimeError(
                    f"Chrome exited early (code={proc.returncode}). "
                    f"Likely cause: user_data_dir locked by another Chrome instance. "
                    f"Close all Chrome windows using profile "
                    f"{CHROME_USER_DATA_PATH!r} and retry. stderr: {stderr}"
                )
            browser = cls._try_connect_chrome(port)
            if browser is not None:
                return browser
        raise RuntimeError(
            f"Chrome with user data failed to start on port {port} within 60s. "
            f"Profile may be too large; check {CHROME_USER_DATA_PATH!r}."
        )
```

注意：
- 保留 Chrome 正常运行时后台 drain 线程（daemon）不会阻塞主流程
- 超过 1MB 丢弃旧数据防止内存泄漏（长时间运行场景）
- stderr 取后 500 字节（最近错误）而非前 500 字节——崩溃信息通常在末尾

- [ ] **Step 4: 运行测试确认 drain 模式不改变 base.py 外部行为**

```bash
uv run pytest tests/ -x --ignore=tests/test_v3_modes.py -k "not integration" -q
```

Expected: 无新增失败。

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/scrapers/base.py tests/test_p009_audit_batch2.py
git commit -m "fix(base): drain chrome stderr in background thread to prevent pipe buffer deadlock (B4)"
```

---

### Task 3: B5 `sync_new_skus` 重启幂等

**Files:**
- Modify: `qbu_crawler/models.py`（DDL + 迁移 + update_workflow_run 允许 `category_synced`）
- Modify: `qbu_crawler/server/workflows.py:932-943`（未提交改动）
- Test: `tests/test_p009_audit_batch2.py`

问题：当前钩子 `if run["status"] != "reporting": sync_new_skus(); run = ... status="reporting"`。如果服务进程在 `sync_new_skus` 调用后、报告生成失败重试期间重启，DB 中 run.status 已是 "reporting"，分支不再执行——表面上 OK。但若 run.status 写入成功而后续 `update_workflow_run` 失败（罕见，但可能），或手动重置 status 为 "running"，会导致 LLM 重复调用。更核心的是：**`sync_new_skus` 的成功应幂等标记在 workflow_runs 上**，让 run 生命周期对"本轮是否已 sync 过"有权威记录。

- [ ] **Step 1: 在 `workflow_runs` 表增加 `category_synced` 布尔列**

修改 `qbu_crawler/models.py` MIGRATIONS 列表（当前 `"ALTER TABLE workflow_runs ADD COLUMN report_tier TEXT"` 之后新加一行）：

```python
        "ALTER TABLE workflow_runs ADD COLUMN category_synced INTEGER NOT NULL DEFAULT 0",
```

同时在 `update_workflow_run` 的 `allowed` 集合（`models.py:678-697`）追加：

```python
        "category_synced",
```

- [ ] **Step 2: 写失败测试**

追加：

```python
def test_sync_new_skus_is_skipped_when_category_synced_flag_is_set(fresh_db, monkeypatch):
    """workflow_runs.category_synced=1 时，sync_new_skus 不得被调用。"""
    from qbu_crawler.server import workflows

    # 造一个 reporting 之前的 run
    run = models.create_workflow_run({
        "workflow_type": "daily",
        "logical_date": "2026-04-17",
        "trigger_key": "daily:2026-04-17",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "status": "running",
        "created_at": config.now_shanghai().isoformat(),
        "updated_at": config.now_shanghai().isoformat(),
    })
    models.update_workflow_run(run["id"], category_synced=1)

    called = {"count": 0}

    def _fake_sync(*a, **kw):
        called["count"] += 1
        return 0

    monkeypatch.setattr(
        "qbu_crawler.server.category_inferrer.sync_new_skus", _fake_sync,
    )

    # 直接触发只包含 sync 段的辅助函数
    workflows._maybe_sync_category_map(run["id"])
    assert called["count"] == 0


def test_sync_new_skus_runs_once_and_sets_flag(fresh_db, monkeypatch):
    from qbu_crawler.server import workflows

    run = models.create_workflow_run({
        "workflow_type": "daily",
        "logical_date": "2026-04-17",
        "trigger_key": "daily:2026-04-18",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "status": "running",
        "created_at": config.now_shanghai().isoformat(),
        "updated_at": config.now_shanghai().isoformat(),
    })

    calls = {"n": 0}

    def _fake_sync(*a, **kw):
        calls["n"] += 1
        return 3

    monkeypatch.setattr(
        "qbu_crawler.server.category_inferrer.sync_new_skus", _fake_sync,
    )

    workflows._maybe_sync_category_map(run["id"])
    workflows._maybe_sync_category_map(run["id"])  # 第二次应被 flag 跳过

    assert calls["n"] == 1
    refreshed = models.get_workflow_run(run["id"])
    assert refreshed["category_synced"] == 1
```

- [ ] **Step 3: 抽出 `_maybe_sync_category_map` 辅助函数**

在 `qbu_crawler/server/workflows.py` 顶部（imports 之后、`WorkflowWorker` 类之前）新增：

```python
def _maybe_sync_category_map(run_id: int) -> None:
    """Idempotently sync new SKUs into category_map.csv for this workflow run.

    Uses workflow_runs.category_synced as the authoritative idempotency flag so
    that process restarts or status regressions never cause duplicate LLM calls.
    All errors are swallowed — this must never block the workflow.
    """
    try:
        run = models.get_workflow_run(run_id)
        if not run or run.get("category_synced"):
            return
        from qbu_crawler.server.category_inferrer import sync_new_skus
        sync_new_skus()
    except Exception:
        logger.exception("sync_new_skus failed; marking synced anyway to avoid retry-storm")
    finally:
        try:
            models.update_workflow_run(run_id, category_synced=1)
        except Exception:
            logger.exception("failed to set category_synced flag for run %s", run_id)
```

然后替换 `workflows.py:932-936` 中当前的内联调用：

```python
        changed = False
        if run["status"] != "reporting":
            _maybe_sync_category_map(run_id)
            run = models.update_workflow_run(
                run_id,
                status="reporting",
                started_at=run.get("started_at") or now,
                error=None,
            )
            changed = True
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_sync_new_skus_is_skipped_when_category_synced_flag_is_set tests/test_p009_audit_batch2.py::test_sync_new_skus_runs_once_and_sets_flag -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/models.py qbu_crawler/server/workflows.py tests/test_p009_audit_batch2.py
git commit -m "fix(workflow): idempotent sync_new_skus via category_synced flag (B5)"
```

---

### Task 4: B6 翻译覆盖率 gate

**Files:**
- Modify: `qbu_crawler/config.py`（新配置项）
- Modify: `qbu_crawler/server/workflows.py`（stalled 分支内加阈值）
- Test: `tests/test_p009_audit_batch2.py`

问题：`workflows.py:958-963` 翻译停滞时仅 `logger.warning` 然后继续生成报告。若翻译 worker 完全宕机，报告里会有大量未翻译中文字段，邮件质量崩塌。应在强行继续前检查覆盖率：`translated / total_in_window >= TRANSLATION_COVERAGE_MIN`（默认 0.7）。未达则 `_move_run_to_attention` 让人工介入，而非发出劣质报告。

- [ ] **Step 1: 加配置项**

修改 `qbu_crawler/config.py` 新增：

```python
# 翻译覆盖率下限（百分比形式 0-1）。低于此值且翻译已停滞时，
# 报告改走 needs_attention 分支而非强行生成不完整报告。
TRANSLATION_COVERAGE_MIN = float(os.getenv("TRANSLATION_COVERAGE_MIN", "0.7"))
```

- [ ] **Step 2: 写失败测试**

追加：

```python
def test_translation_coverage_below_threshold_blocks_full_report(fresh_db, monkeypatch):
    """翻译停滞且覆盖率 < TRANSLATION_COVERAGE_MIN 时，报告阶段不得继续。"""
    from qbu_crawler.server import workflows

    monkeypatch.setattr(config, "TRANSLATION_COVERAGE_MIN", 0.7)

    # 覆盖率 30% 的场景应阻断
    assert workflows._translation_coverage_acceptable(
        translated=3, total=10, stalled=True,
    ) is False
    # 覆盖率 80% 的场景通过
    assert workflows._translation_coverage_acceptable(
        translated=8, total=10, stalled=True,
    ) is True
    # 未 stalled（仍在等待）时不考察覆盖率，返回 True（保留等待流程）
    assert workflows._translation_coverage_acceptable(
        translated=0, total=10, stalled=False,
    ) is True
    # total=0（无可翻译评论）总是 True
    assert workflows._translation_coverage_acceptable(
        translated=0, total=0, stalled=True,
    ) is True
```

- [ ] **Step 3: 实现辅助函数 + 接入分支**

在 `qbu_crawler/server/workflows.py` 顶部附近新增：

```python
def _translation_coverage_acceptable(
    translated: int, total: int, stalled: bool,
) -> bool:
    """Return True if current coverage is acceptable to proceed with full report.

    - Coverage gate only triggers when translation worker is confirmed stalled.
    - total=0 (no translatable reviews) always passes.
    """
    if not stalled or total <= 0:
        return True
    ratio = translated / total
    return ratio >= config.TRANSLATION_COVERAGE_MIN
```

然后修改 `workflows.py:945-966` 的 stalled 分支，在 `_clear_translation_progress(run_id)` 之前插入：

```python
        if not run.get("snapshot_path"):
            pending_translations = _count_pending_translations_for_window(
                run["data_since"],
                run["data_until"],
            )
            if pending_translations > 0 and not _translation_wait_expired(run, now, pending=pending_translations):
                if changed:
                    logger.info(
                        "WorkflowWorker: waiting for %d translations before reporting run %s",
                        pending_translations,
                        run_id,
                    )
                return changed
            if pending_translations > 0:
                # 翻译 stalled —— 先检查覆盖率门槛
                translated, total = _translation_progress_snapshot(
                    run["data_since"], run["data_until"],
                )
                if not _translation_coverage_acceptable(
                    translated=translated, total=total, stalled=True,
                ):
                    logger.error(
                        "WorkflowWorker: translation coverage %d/%d below threshold "
                        "(min=%.2f) for run %s; routing to needs_attention",
                        translated, total, config.TRANSLATION_COVERAGE_MIN, run_id,
                    )
                    self._move_run_to_attention(
                        run, now,
                        f"Translation coverage {translated}/{total} below "
                        f"{config.TRANSLATION_COVERAGE_MIN:.0%}",
                    )
                    return True
                logger.warning(
                    "WorkflowWorker: translation stalled for run %s; continuing "
                    "with %d/%d translated (coverage=%.2f)",
                    run_id, translated, total,
                    translated / max(total, 1),
                )
            _clear_translation_progress(run_id)
            run = freeze_report_snapshot(run_id, now=now)
            changed = True
```

`_translation_progress_snapshot(since, until)` 辅助函数放到 `workflows.py` 中：

```python
def _translation_progress_snapshot(since: str, until: str) -> tuple[int, int]:
    """Return (translated_count, total_in_window) for the given data window."""
    conn = models.get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN translation_status = 'translated' THEN 1 ELSE 0 END) AS tr,
                COUNT(*) AS total
            FROM reviews
            WHERE scraped_at >= ? AND scraped_at < ?
            """,
            (since, until),
        ).fetchone()
        if not row:
            return (0, 0)
        return (int(row["tr"] or 0), int(row["total"] or 0))
    finally:
        conn.close()
```

注意：`translation_status` 列名须与 `translator.py` 内写入的状态值匹配，执行前 `grep translation_status` 核对。

- [ ] **Step 4: 运行测试**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_translation_coverage_below_threshold_blocks_full_report -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/config.py qbu_crawler/server/workflows.py tests/test_p009_audit_batch2.py
git commit -m "feat(workflow): translation coverage gate routes incomplete runs to needs_attention (B6)"
```

---

## Phase 2 — Uncommitted change hardening

### Task 5: I1 `_infer_one_batch` 异常隔离

**Files:**
- Modify: `qbu_crawler/server/category_inferrer.py:131-169`
- Test: `tests/test_p009_audit_batch2.py`

问题：`_infer_one_batch` 抛异常会传播到 `infer_categories` 的 for-loop，导致后续批次全部跳过；顶层 `sync_new_skus` 再吞掉异常时，已成功批次结果也一并丢失。修复：在批次循环内加 try/except，失败批次全标 `other` + confidence 0.0 并继续。

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_infer_categories_isolates_failed_batches(monkeypatch):
    """一个批次 LLM 异常不应影响其他批次的结果。"""
    from qbu_crawler.server import category_inferrer

    class _FakeClient:
        call_count = 0

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    _FakeClient.call_count += 1
                    if _FakeClient.call_count == 1:
                        raise RuntimeError("simulated LLM timeout")

                    class _R:
                        choices = [
                            type("C", (), {
                                "finish_reason": "stop",
                                "message": type("M", (), {
                                    "content": '{"results":[{"sku":"X","category":"grinder","sub_category":"","confidence":0.95}]}',
                                })(),
                            })(),
                        ]
                    return _R()

    monkeypatch.setattr(
        category_inferrer, "_BATCH_SIZE", 1,
    )
    products = [
        {"sku": "A", "name": "Kitchen Grinder #22", "url": ""},
        {"sku": "X", "name": "Meat Grinder", "url": ""},
    ]
    results = category_inferrer.infer_categories(products, client=_FakeClient())

    assert len(results) == 2
    # A 对应的批次失败 → fallback other
    a = [r for r in results if r["sku"] == "A"][0]
    assert a["category"] == "other"
    # X 对应的批次成功
    x = [r for r in results if r["sku"] == "X"][0]
    assert x["category"] == "grinder"
```

- [ ] **Step 2: 修实现**

修改 `qbu_crawler/server/category_inferrer.py` `infer_categories` 的批次循环：

```python
    by_sku: dict[str, dict] = {}
    for i in range(0, len(products), _BATCH_SIZE):
        batch = products[i:i + _BATCH_SIZE]
        logger.info("Inferring batch %d-%d (size=%d)", i, i + len(batch), len(batch))
        try:
            by_sku.update(_infer_one_batch(batch, client))
        except Exception:
            logger.exception(
                "Batch %d-%d LLM call failed; items will fallback to 'other'",
                i, i + len(batch),
            )
            # Continue with other batches — partial data better than nothing
```

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_infer_categories_isolates_failed_batches -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/category_inferrer.py tests/test_p009_audit_batch2.py
git commit -m "fix(category_inferrer): isolate per-batch LLM failures (I1)"
```

---

### Task 6: I2 CSV 追加文件锁

**Files:**
- Modify: `qbu_crawler/server/category_inferrer.py:181-191`
- Test: `tests/test_p009_audit_batch2.py`

问题：`_append_csv` 用 `open(path, "a")` 无锁。CLI 手动跑与服务内 `sync_new_skus` 可能并发。`msvcrt` (Windows) / `fcntl` (Linux) 平台不同，简化方案：用 `.lock` 哨兵文件（`os.O_CREAT | os.O_EXCL`）做跨平台排他锁。

- [ ] **Step 1: 写失败测试（skip 如果难以可靠模拟并发）**

追加：

```python
def test_append_csv_uses_exclusive_lock(tmp_path):
    """并发写 CSV 时使用 exclusive lock 序列化。"""
    from qbu_crawler.server import category_inferrer

    csv_path = tmp_path / "cat.csv"
    # 预先占住 lock 文件
    lock_path = csv_path.with_suffix(".csv.lock")
    lock_path.write_text("held")

    with pytest.raises(category_inferrer.CategoryMapLocked):
        category_inferrer._append_csv(
            [{"sku": "A", "category": "grinder", "sub_category": "", "confidence": 0.9}],
            str(csv_path),
            lock_timeout=0.5,
        )

    lock_path.unlink()
    # 释放后应成功
    category_inferrer._append_csv(
        [{"sku": "A", "category": "grinder", "sub_category": "", "confidence": 0.9}],
        str(csv_path),
        lock_timeout=0.5,
    )
    assert csv_path.exists()
```

- [ ] **Step 2: 修实现**

修改 `qbu_crawler/server/category_inferrer.py`，新增异常类与锁：

```python
class CategoryMapLocked(RuntimeError):
    """Raised when the CSV lock cannot be acquired within timeout."""


def _acquire_lock(csv_path: str, timeout: float) -> Path:
    """Cross-platform exclusive lock using O_CREAT|O_EXCL sentinel file."""
    import time as _time
    lock_path = Path(csv_path).with_suffix(Path(csv_path).suffix + ".lock")
    deadline = _time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock_path
        except FileExistsError:
            if _time.monotonic() >= deadline:
                raise CategoryMapLocked(
                    f"Could not acquire {lock_path} within {timeout}s"
                )
            _time.sleep(0.05)


def _append_csv(
    results: list[CategoryResult],
    csv_path: str,
    lock_timeout: float = 5.0,
) -> None:
    """Append rows to csv under exclusive lock. Preserves existing manual edits."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _acquire_lock(csv_path, lock_timeout)
    try:
        file_exists = path.exists()
        with open(path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["sku", "category", "sub_category", "price_band_override"])
            for r in results:
                writer.writerow([r["sku"], r["category"], r["sub_category"], ""])
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
```

需要文件顶部增加 `import os`。

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_append_csv_uses_exclusive_lock -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/category_inferrer.py tests/test_p009_audit_batch2.py
git commit -m "fix(category_inferrer): cross-platform file lock on csv append (I2)"
```

---

### Task 7: I3 启动时调用 `cleanup_old_notifications` + 改 Shanghai 时区

**Files:**
- Modify: `qbu_crawler/config.py`（新配置项）
- Modify: `qbu_crawler/models.py:1841-1856`（`cleanup_old_notifications` 改 Shanghai 时区）
- Modify: `qbu_crawler/server/notifier.py`（NotifierWorker 定期调用）
- Test: `tests/test_notifier.py`

问题：`cleanup_old_notifications` 已实现但 `grep` 全仓库**无任何调用点**，`notification_outbox` 永远增长。且 cutoff 用 `datetime.now(timezone.utc)`——项目其他 notification 字段用 Shanghai 时区，直接字符串比较会错位 8h（在 UTC 时间靠近 cutoff 的记录会被当成过期）。

- [ ] **Step 1: 加配置项**

`qbu_crawler/config.py` 新增：

```python
NOTIFICATION_RETENTION_DAYS = int(os.getenv("NOTIFICATION_RETENTION_DAYS", "30"))
NOTIFICATION_CLEANUP_INTERVAL_S = int(os.getenv("NOTIFICATION_CLEANUP_INTERVAL_S", "3600"))
```

- [ ] **Step 2: 改 `cleanup_old_notifications` 为 Shanghai 时区**

```python
def cleanup_old_notifications(retention_days: int = 30) -> int:
    cutoff_dt = now_shanghai() - timedelta(days=retention_days)
    cutoff = cutoff_dt.isoformat()
    conn = get_conn()
    try:
        cursor = conn.execute(
            """
            DELETE FROM notification_outbox
            WHERE status IN ('delivered', 'deadletter')
              AND updated_at < ?
            """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
```

（确保 `from datetime import timedelta` 已在文件顶部导入，当前文件已有 `datetime.timezone` 等导入，核对后移除不再需要的 `timezone.utc`。）

- [ ] **Step 3: 在 `NotifierWorker` 中挂钩**

修改 `qbu_crawler/server/notifier.py`：`NotifierWorker._run` 的主循环里，按 `NOTIFICATION_CLEANUP_INTERVAL_S` 间隔调用 cleanup。

```python
class NotifierWorker:
    def __init__(self, ...):
        ...
        self._last_cleanup_ts = 0.0

    def _maybe_cleanup(self):
        import time as _time
        now = _time.monotonic()
        if now - self._last_cleanup_ts < config.NOTIFICATION_CLEANUP_INTERVAL_S:
            return
        try:
            n = models.cleanup_old_notifications(
                retention_days=config.NOTIFICATION_RETENTION_DAYS,
            )
            if n > 0:
                logger.info("NotifierWorker: cleaned %d old notifications", n)
        except Exception:
            logger.exception("NotifierWorker: cleanup failed (non-fatal)")
        finally:
            self._last_cleanup_ts = now
```

`_run` 循环内每轮先调 `self._maybe_cleanup()` 再处理队列。

- [ ] **Step 4: 测试**

追加到 `tests/test_notifier.py`：

```python
def test_cleanup_old_notifications_removes_expired_delivered_rows(tmp_path, monkeypatch):
    from qbu_crawler import config, models

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    models.init_db()

    # 造一行 31 天前的 delivered notification + 一行今天的
    now = config.now_shanghai()
    old_ts = (now - timedelta(days=31)).isoformat()
    fresh_ts = now.isoformat()

    models.enqueue_notification({
        "kind": "test", "target": "A", "payload": {}, "dedupe_key": "k1",
        "created_at": old_ts, "updated_at": old_ts,
        "status": "delivered",
    })
    models.enqueue_notification({
        "kind": "test", "target": "A", "payload": {}, "dedupe_key": "k2",
        "created_at": fresh_ts, "updated_at": fresh_ts,
        "status": "delivered",
    })

    # 手动 tweak updated_at 为历史值
    with models.get_conn() as conn:
        conn.execute(
            "UPDATE notification_outbox SET updated_at = ? WHERE dedupe_key = 'k1'",
            (old_ts,),
        )
        conn.commit()

    removed = models.cleanup_old_notifications(retention_days=30)
    assert removed == 1
    assert models.get_notification_by_dedupe_key("k2") is not None
    assert models.get_notification_by_dedupe_key("k1") is None
```

注意 `enqueue_notification` / `get_notification_by_dedupe_key` 签名若与真实 API 不符，调整为项目实际函数名。

- [ ] **Step 5: 运行回归**

```bash
uv run pytest tests/test_notifier.py -v
```

Expected: 新测试 PASS，旧测试无回归。

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/config.py qbu_crawler/models.py qbu_crawler/server/notifier.py tests/test_notifier.py
git commit -m "fix(notifier): schedule cleanup_old_notifications + use Shanghai tz (I3)"
```

---

## Phase 3 — Observability & semantics

### Task 8: I4 `notified_at` 语义：区分"未尝试" vs "尝试失败"

**Files:**
- Modify: `qbu_crawler/models.py`（DDL 加 `notified_attempt_at` 列 + 迁移 + `mark_notification_failure` 联动 tasks）
- Test: `tests/test_notifier.py`

问题：`tasks.notified_at` 仅在通知成功时写入；失败（attempts 达上限 → deadletter）的任务 `notified_at` 永远为 NULL，与"从未尝试过"不可区分。

修复：新增 `tasks.notified_attempt_at` 列，`mark_notification_failure` 把对应 task_id 的该字段设为当前时刻。

- [ ] **Step 1: 迁移 + DDL**

`models.py` MIGRATIONS 增加：

```python
        "ALTER TABLE tasks ADD COLUMN notified_attempt_at TIMESTAMP",
```

- [ ] **Step 2: 修改 `mark_notification_failure` 联动**

`models.py:1802-1838`：在 UPDATE notification_outbox 之后，用 notification 的 `payload.task_id`（若存在）更新 tasks：

```python
def mark_notification_failure(
    notification_id: int,
    failed_at: str,
    error_message: str,
    retryable: bool,
    max_attempts: int,
    http_status: int | None = None,
    exit_code: int | None = None,
) -> str:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT attempts, payload FROM notification_outbox WHERE id = ?",
            (notification_id,),
        ).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        next_status = "failed" if retryable and attempts < max_attempts else "deadletter"
        conn.execute(
            """
            UPDATE notification_outbox
            SET status = ?, attempts = ?, last_error = ?,
                last_http_status = ?, last_exit_code = ?,
                claim_token = NULL, claimed_at = NULL, lease_until = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (next_status, attempts, error_message, http_status, exit_code, failed_at, notification_id),
        )
        # 联动 tasks.notified_attempt_at
        try:
            payload = json.loads(row["payload"]) if row and row["payload"] else {}
            task_id = payload.get("task_id")
            if task_id:
                conn.execute(
                    "UPDATE tasks SET notified_attempt_at = ? WHERE id = ?",
                    (failed_at, task_id),
                )
        except Exception:
            logger.exception("mark_notification_failure: task linkage update failed")
        conn.commit()
        return next_status
    finally:
        conn.close()
```

- [ ] **Step 3: 测试**

追加到 `tests/test_notifier.py`：

```python
def test_mark_notification_failure_sets_task_notified_attempt_at(tmp_path, monkeypatch):
    from qbu_crawler import config, models

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    models.init_db()

    models.save_task({
        "id": "T-FAIL", "kind": "scrape", "status": "completed",
        "params": {}, "created_at": config.now_shanghai().isoformat(),
    })
    nid = models.enqueue_notification({
        "kind": "task_done", "target": "A",
        "payload": {"task_id": "T-FAIL"}, "dedupe_key": "T-FAIL:done",
        "status": "failed",
    })

    ts = config.now_shanghai().isoformat()
    result = models.mark_notification_failure(
        nid, failed_at=ts, error_message="net",
        retryable=False, max_attempts=3,
    )
    assert result == "deadletter"

    t = models.get_task("T-FAIL")
    assert t["notified_attempt_at"] == ts
    assert t["notified_at"] is None  # 未成功，不写 notified_at
```

`enqueue_notification` 若参数不对，调整为实际 API。

- [ ] **Step 4: 运行测试 + Commit**

```bash
uv run pytest tests/test_notifier.py::test_mark_notification_failure_sets_task_notified_attempt_at -v
git add qbu_crawler/models.py tests/test_notifier.py
git commit -m "feat(notifier): track notified_attempt_at to distinguish failed vs unattempted (I4)"
```

---

### Task 9: I5 `_logical_date_window` 改 tzinfo-aware datetime

**Files:**
- Modify: `qbu_crawler/server/workflows.py:370 附近`
- Test: `tests/test_p009_audit_batch2.py`

问题：当前函数 return f-string `"{start.date().isoformat()}T00:00:00+08:00"`。下游 `datetime.fromisoformat()` 可以解析带 `+08:00` 的字符串，但中间比较容易滋生 naive vs aware 混合。规范做法：在源头就返回 tzinfo-aware `datetime` 对象，由序列化层在最后时刻 `.isoformat()`。

- [ ] **Step 1: 找到当前函数签名**

读 `workflows.py` 查找 `_logical_date_window` 定义，确认返回类型。

- [ ] **Step 2: 写失败测试**

```python
def test_logical_date_window_returns_tzinfo_aware_datetimes():
    """_logical_date_window 应返回 tzinfo-aware datetime，不是 naive 也不是字符串。"""
    from qbu_crawler.server.workflows import _logical_date_window

    since, until = _logical_date_window("2026-04-17")
    # 必须是 datetime
    assert isinstance(since, datetime)
    assert isinstance(until, datetime)
    # 必须有 tzinfo
    assert since.tzinfo is not None
    assert until.tzinfo is not None
    # 必须是 +08:00 偏移
    assert since.utcoffset() == timedelta(hours=8)
```

- [ ] **Step 3: 修实现**

把返回类型改为 `tuple[datetime, datetime]`，所有调用点的接收方若直接传给 DB 比较，需要 `.isoformat()`。这是跨文件改动——执行前先 `grep _logical_date_window` 列出所有调用点：

```bash
rg "_logical_date_window" qbu_crawler/
```

每个调用点要么立即 `.isoformat()`，要么改为接收 datetime。Make sure 调用点的 DB 列语义与 ISO 字符串一致。

- [ ] **Step 4: 运行全套测试**

```bash
uv run pytest tests/ -x --ignore=tests/test_v3_modes.py -q
```

Expected: 无回归。

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p009_audit_batch2.py
git commit -m "refactor(workflow): _logical_date_window returns tz-aware datetime (I5)"
```

---

### Task 10: I6 `WorkflowWorker` 最小 sleep

**Files:**
- Modify: `qbu_crawler/server/workflows.py:802` 附近
- Test: `tests/test_p009_audit_batch2.py`

问题：`_run` 的内循环 `while self.process_once() and not self._stop_event.is_set(): continue` 若 `process_once()` 返回 True 持续为真，无 sleep 会占 100% CPU。

修复：在每轮真推进后插入 `self._stop_event.wait(0.05)`（最小 50ms sleep，但可被 stop_event 立即打断）。

- [ ] **Step 1: 写失败测试**

```python
def test_workflow_worker_inner_loop_has_min_sleep(monkeypatch):
    """模拟 process_once 一直返回 True，确保循环每轮至少 sleep 50ms，不占 CPU 100%。"""
    from qbu_crawler.server import workflows
    import threading
    import time as _time

    worker = workflows.WorkflowWorker.__new__(workflows.WorkflowWorker)
    worker._stop_event = threading.Event()
    worker._interval = 60  # 不走外循环

    calls = {"n": 0}

    def _fake_process_once():
        calls["n"] += 1
        return True

    worker.process_once = _fake_process_once

    thread = threading.Thread(target=worker._run, daemon=True)
    start = _time.monotonic()
    thread.start()
    _time.sleep(0.6)
    worker._stop_event.set()
    thread.join(timeout=2)

    # 0.6s 内循环次数应受 50ms min sleep 限制，上限 ~12 次
    assert calls["n"] <= 20, f"无 min sleep 防护，0.6s 内执行 {calls['n']} 次"
    assert calls["n"] >= 5, f"sleep 过长，0.6s 内才执行 {calls['n']} 次"
```

- [ ] **Step 2: 修 `_run`**

找到 `workflows.py` 内循环处（`while self.process_once() and not self._stop_event.is_set(): continue`），改为：

```python
            while not self._stop_event.is_set():
                if not self.process_once():
                    break
                # min sleep to avoid pegging CPU if process_once keeps returning True
                if self._stop_event.wait(0.05):
                    break
```

- [ ] **Step 3: 测试 + Commit**

```bash
uv run pytest tests/test_p009_audit_batch2.py::test_workflow_worker_inner_loop_has_min_sleep -v
git add qbu_crawler/server/workflows.py tests/test_p009_audit_batch2.py
git commit -m "fix(workflow): add min sleep to WorkflowWorker inner loop (I6)"
```

---

## Phase 4 — P008 D015 follow-ups

### Task 11: F1 (D015#3) 显式 `report_tier` 参数

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` — `generate_full_report_from_snapshot` / `_render_full_email_html`
- Test: 跨 tier 的既有 `tests/test_p008_phase4.py` / `tests/test_p008_phase3.py`

问题：当前 X1 修复用 `snapshot["_meta"]["report_tier"]` fallback 读 tier，可维护性差：调用者看不出这是关键参数，容易漏传。F1 方案：在两个函数签名加 `report_tier: str | None = None`，若显式传入则优先；否则 fallback `_meta`；都没有则 WARNING + 默认 `"daily"`（现 D015 行为）。

- [ ] **Step 1: 写失败测试**

追加 `tests/test_p009_audit_batch2.py`：

```python
def test_generate_full_report_from_snapshot_accepts_explicit_report_tier():
    from qbu_crawler.server import report_snapshot
    import inspect

    sig = inspect.signature(report_snapshot.generate_full_report_from_snapshot)
    assert "report_tier" in sig.parameters
    # 默认为 None（向后兼容 _meta fallback）
    assert sig.parameters["report_tier"].default is None
```

- [ ] **Step 2: 改签名 + 优先级逻辑**

找到 `generate_full_report_from_snapshot` 与 `_render_full_email_html`，加 `report_tier` 形参，在函数内：

```python
def generate_full_report_from_snapshot(
    snapshot: dict,
    *,
    send_email: bool = True,
    report_tier: str | None = None,
    ...
):
    if report_tier is None:
        report_tier = (snapshot.get("_meta") or {}).get("report_tier")
    if report_tier is None:
        logger.warning(
            "generate_full_report_from_snapshot: report_tier missing "
            "(snapshot._meta absent); defaulting to 'daily'"
        )
        report_tier = "daily"
    ...
```

- [ ] **Step 3: 运行既有 P008 tests + Commit**

```bash
uv run pytest tests/test_p008_phase3.py tests/test_p008_phase4.py tests/test_p009_audit_batch2.py -v
git add qbu_crawler/server/report_snapshot.py tests/test_p009_audit_batch2.py
git commit -m "refactor(report): explicit report_tier parameter (D015 #3, F1)"
```

---

### Task 12: F2 (D015#4) R2/R3 recurrent 过渡单测

**Files:**
- Modify: `tests/test_p008_phase4.py`

问题：`analytics_lifecycle.py` 的 `recurrent → receding (R2)` 和 `recurrent → dormant (R3)` 路径仅靠集成覆盖，无显式单测，一旦重构容易回归。

- [ ] **Step 1: 读 lifecycle 模块找到状态机入口**

```bash
rg "R2|R3|recurrent.*(receding|dormant)" qbu_crawler/server/analytics_lifecycle.py
```

- [ ] **Step 2: 写 R2 / R3 单测**

追加到 `tests/test_p008_phase4.py`：

```python
def test_lifecycle_R2_recurrent_to_receding():
    """R2: issue 处于 recurrent 状态，本期 neg_rate 回落至 warning 阈值下 → receding。"""
    from qbu_crawler.server.analytics_lifecycle import classify_issue_lifecycle

    prior_state = {"status": "recurrent", "last_seen_cycle": 1}
    current_metrics = {
        "neg_count": 2, "total_count": 50, "neg_rate": 0.04,
        "first_seen_days_ago": 90,
    }
    result = classify_issue_lifecycle(prior_state, current_metrics, cycle_index=3)
    assert result["status"] == "receding"


def test_lifecycle_R3_recurrent_to_dormant():
    """R3: issue 处于 recurrent 状态，本期无新增评论 → dormant。"""
    from qbu_crawler.server.analytics_lifecycle import classify_issue_lifecycle

    prior_state = {"status": "recurrent", "last_seen_cycle": 1}
    current_metrics = {
        "neg_count": 0, "total_count": 0, "neg_rate": 0.0,
        "first_seen_days_ago": 90,
    }
    result = classify_issue_lifecycle(prior_state, current_metrics, cycle_index=3)
    assert result["status"] == "dormant"
```

函数名 `classify_issue_lifecycle` 为示意，执行时请按实际 API 调整参数结构。

- [ ] **Step 3: 运行 + Commit**

```bash
uv run pytest tests/test_p008_phase4.py::test_lifecycle_R2_recurrent_to_receding tests/test_p008_phase4.py::test_lifecycle_R3_recurrent_to_dormant -v
git add tests/test_p008_phase4.py
git commit -m "test(lifecycle): add explicit R2/R3 recurrent transition tests (D015 #4, F2)"
```

---

### Task 13: F3 (D015#5) 真正冷启动 `is_partial`

**Files:**
- Modify: `qbu_crawler/models.py`（新增 `get_earliest_review_scraped_at(since_ownership=None)`）
- Modify: `qbu_crawler/server/report_snapshot.py`（`_inject_meta` 用 earliest_review 判断 partial）
- Test: `tests/test_p009_audit_batch2.py`

问题：D015 用 `calendar.monthrange` 只修 Feb 误判，但 `actual == expected` 在完整窗口下永远成立，真正冷启动（部署不满期）从未被标记。需 `earliest_review_scraped_at`：若最早评论 `scraped_at > window.start`，说明有数据缺口。

- [ ] **Step 1: 新增 models helper**

`qbu_crawler/models.py` 追加：

```python
def get_earliest_review_scraped_at() -> str | None:
    """Return the earliest scraped_at across all reviews, or None if empty."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MIN(scraped_at) AS earliest FROM reviews"
        ).fetchone()
        return row["earliest"] if row else None
    finally:
        conn.close()
```

- [ ] **Step 2: 修 `_inject_meta`**

读 `qbu_crawler/server/report_snapshot.py` 找到 `_inject_meta` 定义，在 `is_partial` 判定处增加：

```python
    earliest = models.get_earliest_review_scraped_at()
    if earliest:
        earliest_dt = datetime.fromisoformat(earliest)
        if window_start_dt > earliest_dt:
            # 部署已够久，window 完整（常规路径）
            is_partial = (actual_days < expected_days)
        else:
            # 最早评论晚于窗口开始 → 真正的冷启动缺口
            is_partial = True
    else:
        # 无任何评论 → 全空窗口，也算 partial
        is_partial = True
```

保留原 `calendar.monthrange` 为上界 expected_days 计算，不移除。

- [ ] **Step 3: 写失败测试**

```python
def test_is_partial_true_when_earliest_review_later_than_window_start(
    fresh_db, monkeypatch,
):
    """冷启动：最早评论晚于窗口开始 → is_partial=True，即便 actual==expected。"""
    from qbu_crawler.server import report_snapshot

    # 窗口：2026-04-01 到 2026-05-01（完整月 = 30 天）
    # 最早评论：2026-04-15 → 真正冷启动
    # 造数据省略（用 monkeypatch 替换 get_earliest_review_scraped_at）
    monkeypatch.setattr(
        "qbu_crawler.models.get_earliest_review_scraped_at",
        lambda: "2026-04-15T00:00:00+08:00",
    )
    meta = report_snapshot._compute_meta_partial(
        window_start="2026-04-01T00:00:00+08:00",
        window_end="2026-05-01T00:00:00+08:00",
        tier="monthly",
    )
    assert meta["is_partial"] is True
    assert meta["earliest_review_scraped_at"] == "2026-04-15T00:00:00+08:00"


def test_is_partial_false_when_earliest_predates_window(fresh_db, monkeypatch):
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(
        "qbu_crawler.models.get_earliest_review_scraped_at",
        lambda: "2026-01-01T00:00:00+08:00",
    )
    meta = report_snapshot._compute_meta_partial(
        window_start="2026-04-01T00:00:00+08:00",
        window_end="2026-05-01T00:00:00+08:00",
        tier="monthly",
    )
    assert meta["is_partial"] is False
```

`_compute_meta_partial` 为示意函数名，若实际代码直接内联在 `_inject_meta`，需先抽出纯函数再测。

- [ ] **Step 4: 运行 + Commit**

```bash
uv run pytest tests/test_p009_audit_batch2.py -k is_partial -v
git add qbu_crawler/models.py qbu_crawler/server/report_snapshot.py tests/test_p009_audit_batch2.py
git commit -m "feat(report): true cold-start detection via earliest_review_scraped_at (D015 #5, F3)"
```

---

### Task 14: F4 (D015#6) LLM prompt 单位澄清

**Files:**
- Modify: `qbu_crawler/server/category_inferrer.py`（system prompt confidence 措辞）
- Modify: `qbu_crawler/server/analytics_executive.py`（`_PROMPT` 中差评率单位）

问题：D015 #6 列出两处单位歧义：
- `category_inferrer._build_messages` system prompt 写 `confidence < 0.7`，但变量名是 `_CONFIDENCE_FLOOR` 容易让人以为是百分比
- `analytics_executive._PROMPT` 差评率判定阈值 `> 5%`，实际传入 LLM 的数值是分数 0-1

- [ ] **Step 1: 修 `category_inferrer`**

在 `qbu_crawler/server/category_inferrer.py` system prompt 修改：

```python
        "- Use 'other' if confidence < 0.70 (float 0.0–1.0, "
        "NOT a percentage). NEVER invent new categories.\n\n"
```

- [ ] **Step 2: 修 `analytics_executive._PROMPT`**

读 `qbu_crawler/server/analytics_executive.py` 找到 `_PROMPT`，在提到差评率阈值处增加单位说明：

```python
# 示意（执行前先定位实际文本）
"""
- own_negative_review_rate 以 fraction (0.0-1.0) 传入，例如 0.05 == 5%。
  判定 needs_attention 阈值：neg_rate > 0.05。
"""
```

- [ ] **Step 3: 人工 smoke-test LLM 响应**

```bash
# 可选：手动触发一次 monthly 报告确认 LLM 输出 bullets 的百分比仍显示 X.Y%，而非 0.0%
uv run python -c "from qbu_crawler.server.report import test_generate_monthly_report; test_generate_monthly_report()"
```

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/category_inferrer.py qbu_crawler/server/analytics_executive.py
git commit -m "docs(llm): clarify confidence and neg_rate unit semantics in prompts (D015 #6, F4)"
```

---

## 最终验证

- [ ] **Step 1: 全套测试**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/ -v --ignore=tests/test_v3_modes.py
```

Expected: 所有新增 P009 test 通过，既有 P008 test 无回归，`test_v3_modes.py` 2 个 pre-existing 失败照旧。

- [ ] **Step 2: 手动回归关键路径**

```bash
# 启动服务，触发一次 daily run，观察日志：
# - sync_new_skus 只调用一次（即使重启后 run 仍为 reporting）
# - 翻译覆盖率 log 输出
# - NotifierWorker 每小时一次 "cleaned N old notifications"
uv run python main.py serve
```

- [ ] **Step 3: 写 devlog**

创建 `docs/devlogs/D016-p009-audit-batch2.md`，按 D015 模板记录修复清单、关键决策、测试统计、生产前 verify 清单。

- [ ] **Step 4: 版本 bump + 发布**

```bash
python scripts/publish.py patch
```

`pyproject.toml` / `qbu_crawler/__init__.py` 从 `0.1.58` → `0.1.59`。

---

## 遗留事项 / Follow-ups（超出本计划）

1. `product_snapshots` 写入从未读——需决策保留（作为对账参考）vs 删除
2. `REPORT_DIR` 不跟随 `QBU_DATA_DIR`：生产若仅设 `QBU_DATA_DIR` 报告会写项目目录
3. Cross-tier severity 不一致：daily/weekly/monthly 均从 `reviews` 独立聚合，同一 issue 分类分歧
4. Translation worker DB-as-Queue 无 claim/lease，worker 崩溃会重复翻译
5. `body_hash` 在 `waltons.py:338` 有独立实现（intra-scraper 用途），非 bug 但长期可统一到 `models._body_hash`
6. DST 边界防护：Shanghai 无 DST，短期可忽略；跨国部署时再处理
7. P008 原始审计推迟的 10🟡+9🟢 observable 项（详见 `P008-audit-fixes-implementation.md` § Out of scope）
