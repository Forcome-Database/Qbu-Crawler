# P008 Audit Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2026-04-17 P008 Phase 1-4 审计中发现的 9 项必须修复级别 Bug（1 跨 Phase + 8 单 Phase），保证月报/周报/日报数据单位、基线选择、安全链路和冷启动标记正确。

**Architecture:** 以最小侵入修补已有函数签名和调用点，不新增模块。遵循 TDD：每个 Task 先写失败测试 → 打补丁 → 验证通过 → 提交。

**Tech Stack:** Python 3.10+ / SQLite / Jinja2 / pytest

**Scope (本计划覆盖)**:

- **X1** — `load_previous_report_context` 4 个调用点漏传 `report_tier`（跨 Phase）
- **P4-B1** — `_classify_stance` 里 `neg_rate > 5` 死代码（单位：分数 vs 百分比）
- **P4-B2** — `_fallback_executive_summary` bullet 漏 `*100`
- **P4-B3** — `_build_weekly_trend_chart` 的 `neg_series` 漏 `*100`
- **P1-C1** — `safety_incidents` 缺 UNIQUE + `INSERT OR IGNORE`
- **P1-C2** — `safety_incidents.detected_at/created_at` 用 UTC（应为 Shanghai）
- **P2-F2** — 安全信号未分发到 `EMAIL_RECIPIENTS_SAFETY`
- **P3-I2** — `_inject_meta` 的冷启动 `expected_days/actual_days` 从未传入
- **P3-I3** — V3 模板缺冷周提示

**Out of scope（留作后续批次）**:

- 🟡 P1-I1 DB timeout / P1-I2/I3/I4 测试覆盖 / P2-F3/F4/F5/F6/F7 / P3-I4 scheduler 超时 / P4-I5/I6
- 🟢 全部 observable 项

**Source:** 审计报告来自 2026-04-17 4 agent 并行对账结果（见 session 记忆）。

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `qbu_crawler/models.py` | DDL + migration + INSERT 时区修正 |
| Modify | `qbu_crawler/server/report_snapshot.py` | X1 (4 调用点)、P3-I2 freeze、P2-F2 safety 分发 |
| Modify | `qbu_crawler/server/analytics_executive.py` | P4-B1 stance 阈值、P4-B2 bullet 百分比 |
| Modify | `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | P3-I3 冷周提示 |
| Modify | `tests/test_p008_phase1.py` | 安全表幂等 + 时区 |
| Modify | `tests/test_p008_phase2.py` | 安全通道分发 |
| Modify | `tests/test_p008_phase3.py` | 冷启动 meta + 冷周提示 + tier 基线 |
| Modify | `tests/test_p008_phase4.py` | 单位修正 + stance 阈值 |

---

## Task 1: P4-B1 修正 `_classify_stance` 里 `neg_rate > 5` 单位错

**Files:**
- Modify: `qbu_crawler/server/analytics_executive.py:68`
- Test: `tests/test_p008_phase4.py`

问题：`own_negative_review_rate` 在 pipeline 里是 **分数**（`neg_count / total`，范围 0–1），不是百分比。当前判断 `neg_rate > 5` 要求 500% 才触发，永远为假。`needs_attention` 分支实际由 `health_delta < -5` 或 `risk_delta > 0` 承担，差评率维度失效。

- [ ] **Step 1: Write failing test**

在 `tests/test_p008_phase4.py` 追加：

```python
def test_classify_stance_needs_attention_on_fraction_neg_rate():
    """neg_rate is a fraction (0.0-1.0), not percentage. 6% should trigger needs_attention."""
    from qbu_crawler.server.analytics_executive import _classify_stance
    inputs = {
        "kpis": {
            "health_index": 75.0,
            "high_risk_count": 1,
            "own_negative_review_rate": 0.06,  # 6% 分数形式
        },
        "kpi_delta": {"health_index": -1.0, "high_risk_count": 0},
        "safety_incidents": [],
        "safety_incidents_count": 0,
    }
    assert _classify_stance(inputs) == "needs_attention"


def test_classify_stance_stable_below_threshold():
    from qbu_crawler.server.analytics_executive import _classify_stance
    inputs = {
        "kpis": {
            "health_index": 80.0,
            "high_risk_count": 1,
            "own_negative_review_rate": 0.04,  # 4% 低于 5% 阈值
        },
        "kpi_delta": {"health_index": -1.0, "high_risk_count": 0},
        "safety_incidents": [],
        "safety_incidents_count": 0,
    }
    assert _classify_stance(inputs) == "stable"
```

注意：文件中已有的 `test_executive_summary_stance_categories` 用 `12.0`（误以为是百分比整数）作为输入——这个测试属于漂移产物，需要一并修正。

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_p008_phase4.py::test_classify_stance_needs_attention_on_fraction_neg_rate -v
```

Expected: FAIL — 返回 "stable" 而非 "needs_attention"。

- [ ] **Step 3: Fix threshold in `_classify_stance`**

`qbu_crawler/server/analytics_executive.py:68`，将：

```python
if health_delta < -5 or risk_delta > 0 or neg_rate > 5:
```

改为：

```python
if health_delta < -5 or risk_delta > 0 or neg_rate > 0.05:
```

- [ ] **Step 4: 修正已有的漂移测试**

在 `tests/test_p008_phase4.py` 中找 `test_executive_summary_stance_categories`，把传入的 `"own_negative_review_rate": 12.0` 改为 `"own_negative_review_rate": 0.12`，其它 `> 5`/`= 4.0` 类似伪造值统一转为分数。

- [ ] **Step 5: Run all Phase 4 tests**

```bash
uv run pytest tests/test_p008_phase4.py -v
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/analytics_executive.py tests/test_p008_phase4.py
git commit -m "fix(executive): correct neg_rate threshold to fraction (0.05), not percentage (5)"
```

---

## Task 2: P4-B2 修正 executive bullet 的百分比渲染

**Files:**
- Modify: `qbu_crawler/server/analytics_executive.py:98`
- Test: `tests/test_p008_phase4.py`

问题：`neg_rate` 为 0.042 时，`round(float(neg_rate), 1)` 输出 "差评率 0.0%" 而非 "4.2%"。

- [ ] **Step 1: Write failing test**

```python
def test_fallback_bullet_renders_neg_rate_as_percentage():
    from qbu_crawler.server.analytics_executive import _fallback_executive_summary
    inputs = {
        "kpis": {
            "health_index": 72.3,
            "high_risk_count": 1,
            "own_negative_review_rate": 0.042,
            "own_review_rows": 150,
        },
        "kpi_delta": {"health_index": -1.5, "high_risk_count": 0},
        "safety_incidents": [],
        "safety_incidents_count": 0,
        "top_issues": [],
    }
    result = _fallback_executive_summary(inputs)
    bullets_text = " ".join(result["bullets"])
    assert "差评率 4.2%" in bullets_text
    assert "差评率 0.0%" not in bullets_text
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/test_p008_phase4.py::test_fallback_bullet_renders_neg_rate_as_percentage -v
```

- [ ] **Step 3: Fix bullet rendering**

`qbu_crawler/server/analytics_executive.py:96-98`，把：

```python
neg_rate = kpis.get("own_negative_review_rate")
if neg_rate is not None:
    bullets.append(f"差评率 {round(float(neg_rate), 1)}% · 本月新增评论 {kpis.get('own_review_rows', 0)} 条")
```

改为：

```python
neg_rate = kpis.get("own_negative_review_rate")
if neg_rate is not None:
    bullets.append(
        f"差评率 {round(float(neg_rate) * 100, 1)}% · "
        f"本月新增评论 {kpis.get('own_review_rows', 0)} 条"
    )
```

- [ ] **Step 4: Run test, verify PASS + no regressions**

```bash
uv run pytest tests/test_p008_phase4.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/analytics_executive.py tests/test_p008_phase4.py
git commit -m "fix(executive): scale fraction neg_rate to percentage in fallback bullet"
```

---

## Task 3: P4-B3 修正周报趋势图 `neg_series` 单位

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:1380-1381, 1410`
- Test: `tests/test_p008_phase3.py`

问题：`neg_series` 存的是分数（0.02-0.08），但 Y 轴标签是"差评率 (%)"。图表显示数值是真实值的 1/100。

- [ ] **Step 1: 定位精确行号**

先读 `report_snapshot.py:1370-1420` 确认 `_build_weekly_trend_chart`（或同名函数）的上下文，以便 Step 3 精准替换。

```bash
uv run python -c "import re,sys; \
  print(open('qbu_crawler/server/report_snapshot.py').read()[38000:44000])" | head -200
```

- [ ] **Step 2: Write failing test**

在 `tests/test_p008_phase3.py` 追加：

```python
def test_weekly_trend_chart_neg_series_is_percentage():
    """neg_series 必须为百分比值（0-100），与 Y 轴标签 '差评率 (%)' 对齐。"""
    from qbu_crawler.server.report_snapshot import _build_weekly_trend_chart
    fake_runs = [
        {
            "logical_date": "2026-04-07",
            "analytics_path": None,
            # 模拟 inline KPI
            "kpis": {"own_negative_review_rate": 0.04, "health_index": 70.0},
        },
        {
            "logical_date": "2026-04-14",
            "analytics_path": None,
            "kpis": {"own_negative_review_rate": 0.06, "health_index": 68.0},
        },
    ]
    chart = _build_weekly_trend_chart(fake_runs)
    neg_values = [p for p in chart["datasets"]
                  if "差评率" in p.get("label", "")][0]["data"]
    # 分数 0.04 → 百分比 4.0
    assert any(v is not None and 3.5 <= v <= 4.5 for v in neg_values), \
        f"neg_series should contain 4.0, got {neg_values}"
```

**注意**：如果 `_build_weekly_trend_chart` 的签名与 fake_runs 结构不同（例如从 DB 查询而非接收 runs 列表），调整 fixture。Task 前先阅读函数源码。

- [ ] **Step 3: Fix scaling in `_build_weekly_trend_chart`**

找到 `neg_series.append(float(neg) if neg is not None else None)` 两行（约在 1380-1381 和 1410），改为：

```python
neg_series.append(float(neg) * 100 if neg is not None else None)
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/test_p008_phase3.py::test_weekly_trend_chart_neg_series_is_percentage -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase3.py
git commit -m "fix(weekly): scale neg_series fraction to percentage for '%' axis"
```

---

## Task 4: X1 修复 `load_previous_report_context` 跨 tier 基线污染（4 个调用点）

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:454, 734, 1646, 1807`
- Test: `tests/test_p008_phase3.py`

问题：`get_previous_completed_run` 在 Phase 3 移除了 `workflow_type='daily'` 硬编码过滤。4 个调用点未同步传 `report_tier`，导致：

| 行 | 函数 | 错误表现 |
|---|------|---------|
| 454 | `_render_quiet_or_change_html` | quiet/change 日报"上次报告"链接指到周报 |
| 734 | `_generate_daily_briefing` | 日报 attention_signals 把周报变动算成日变动 |
| 1646 | `_render_full_email_html` | full 邮件变动表跨 tier |
| 1807 | `generate_full_report_from_snapshot` | 周报 Tab 2 对比上一周报而非上一日报 |

月报路径（`_generate_monthly_report` line 1134）已正确传参，可作参考。

- [ ] **Step 1: 用 Grep 确认当前 4 个调用点**

```
Grep pattern: "load_previous_report_context\("
path: qbu_crawler/server/report_snapshot.py
output_mode: content
-n: true
```

Expected: 5 个结果（1 个定义 + 4 个调用点）。核对行号。

- [ ] **Step 2: Write failing test (weekly 场景)**

在 `tests/test_p008_phase3.py` 追加：

```python
def test_weekly_report_does_not_use_daily_run_as_baseline(db, tmp_path, monkeypatch):
    """
    场景：DB 中存在近期已完成的 daily run（id=1, 分析文件存在）和上周已完成的 weekly run
    （id=2, 分析文件存在）。当生成本周 weekly 报告时，baseline 必须取 id=2（上周报），不能取 id=1（日报）。
    """
    import json
    from qbu_crawler.server.report_snapshot import load_previous_report_context

    daily_analytics = tmp_path / "daily.json"
    daily_analytics.write_text(json.dumps({"kpis": {"health_index": 70}}))
    weekly_analytics = tmp_path / "weekly.json"
    weekly_analytics.write_text(json.dumps({"kpis": {"health_index": 80}}))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-19',"
        " 'daily:2026-04-19', 'daily', ?)",
        (str(daily_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-13',"
        " 'weekly:2026-04-13', 'weekly', ?)",
        (str(weekly_analytics),),
    )
    # 当前新 weekly run id=3
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'weekly', 'reporting', 'none', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly')"
    )
    conn.commit()
    conn.close()

    # 不传 tier: 返回 id=1（daily）—— 这是修复前的错误行为
    prev_no_tier, _ = load_previous_report_context(3)
    # 传 weekly: 必须返回 id=2 内容（health_index=80）
    prev_weekly, _ = load_previous_report_context(3, report_tier="weekly")
    assert prev_weekly is not None
    assert prev_weekly["kpis"]["health_index"] == 80
```

- [ ] **Step 3: Write failing test (daily 场景，防反向污染)**

继续追加：

```python
def test_daily_briefing_does_not_use_weekly_run_as_baseline(db, tmp_path, monkeypatch):
    """Reverse: 生成 daily briefing 时若 DB 里最新已完成的是 weekly，不能取周报作基线。"""
    import json
    from qbu_crawler.server.report_snapshot import load_previous_report_context

    daily_analytics = tmp_path / "daily.json"
    daily_analytics.write_text(json.dumps({"kpis": {"health_index": 70}}))
    weekly_analytics = tmp_path / "weekly.json"
    weekly_analytics.write_text(json.dumps({"kpis": {"health_index": 80}}))

    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (1, 'daily', 'completed', 'full_sent', '2026-04-18',"
        " 'daily:2026-04-18', 'daily', ?)",
        (str(daily_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier, analytics_path)"
        " VALUES (2, 'weekly', 'completed', 'full_sent', '2026-04-20',"
        " 'weekly:2026-04-20', 'weekly', ?)",
        (str(weekly_analytics),),
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_type, status, report_phase, logical_date,"
        " trigger_key, report_tier)"
        " VALUES (3, 'daily', 'reporting', 'none', '2026-04-21',"
        " 'daily:2026-04-21', 'daily')"
    )
    conn.commit()
    conn.close()

    prev_daily, _ = load_previous_report_context(3, report_tier="daily")
    assert prev_daily is not None
    assert prev_daily["kpis"]["health_index"] == 70  # daily 基线，不是 80
```

- [ ] **Step 4: Run tests, verify FAIL on second test**

```bash
uv run pytest tests/test_p008_phase3.py -k "does_not_use_" -v
```

Expected: `test_daily_briefing_does_not_use_weekly_run_as_baseline` 验证 `load_previous_report_context` 本身正确（这是回归护栏）。此处两个测试都应 PASS——它们只检验 `load_previous_report_context(tier=)` 的正确性，并暴露"所有调用点都必须传 tier"的契约。

**真正验证修复的"集成级契约"**：在修改调用点前后对比集成测试是否稳定。

- [ ] **Step 5: Fix 4 call sites in `report_snapshot.py`**

**5a. Line 454 (`_render_quiet_or_change_html`)**：

找到：
```python
prev_run = models.get_previous_completed_run(run_id_for_lookup)
```

改为：
```python
# X1: 限定同 tier 避免跨 tier 污染 "上次报告" 链接
run_tier = run.get("report_tier") if isinstance(run, dict) else None
prev_run = models.get_previous_completed_run(run_id_for_lookup, report_tier=run_tier or "daily")
```

**5b. Line 734 (`_generate_daily_briefing`)**：

找到：
```python
prev_analytics, prev_snapshot = load_previous_report_context(run_id)
```

改为：
```python
prev_analytics, prev_snapshot = load_previous_report_context(run_id, report_tier="daily")
```

**5c. Line 1646 (`_render_full_email_html`)**：

该函数的 run 上下文里应该知道 tier。读 1640-1660 行确认 `run_tier` 变量是否在作用域内；若不在，从 `run["report_tier"]`（或 `run.get("report_tier", "daily")`) 取。

找到：
```python
prev_analytics, prev_snapshot = load_previous_report_context(run_id)
```

改为：
```python
# X1
_tier = (run.get("report_tier") if isinstance(run, dict) else None) or "daily"
prev_analytics, prev_snapshot = load_previous_report_context(run_id, report_tier=_tier)
```

**5d. Line 1807 (`generate_full_report_from_snapshot`)**：

该函数是被 daily/weekly/monthly 共享的核心路径。需要接受 `report_tier` 作为参数（新增），默认 `None`→向后兼容。检查其签名并：

1. 在函数参数里加 `report_tier: str | None = None`
2. 内部调用 `load_previous_report_context(run_id, report_tier=report_tier)`
3. 所有上游调用者（`_generate_weekly_report`、`_generate_monthly_report`、`_generate_daily_briefing` 等）显式传入各自 tier

以 `_generate_weekly_report` 为例：

```python
# 在调用 generate_full_report_from_snapshot 的地方补 report_tier="weekly"
full_result = generate_full_report_from_snapshot(
    snapshot, send_email=False, report_tier="weekly", ...
)
```

月报同理传 `"monthly"`。如调用点接近但语义不同，保持与上下文一致。

- [ ] **Step 6: Run Phase 2/3/4 全部测试**

```bash
uv run pytest tests/test_p008_phase2.py tests/test_p008_phase3.py tests/test_p008_phase4.py -v
```

Expected: 全部 PASS。如有已有集成测试因新参数失败，同步修复测试中的调用签名。

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase3.py
git commit -m "fix(baseline): thread report_tier through load_previous_report_context 4 call sites"
```

---

## Task 5: P1-C1 `safety_incidents` UNIQUE 约束 + `INSERT OR IGNORE`

**Files:**
- Modify: `qbu_crawler/models.py` (DDL + migrations + `save_safety_incident`)
- Test: `tests/test_p008_phase1.py`

问题：translator 对失败评论最多重试 3 次，每次都会完整跑 safety pipeline，`save_safety_incident` 没有去重，产生重复记录。`evidence_hash` 字段本应是去重锚但未作为 UNIQUE。

- [ ] **Step 1: Write failing test**

在 `tests/test_p008_phase1.py` 追加：

```python
def test_save_safety_incident_is_idempotent(fresh_db):
    """重复调用相同 review_id + evidence_hash 不应产生多行。"""
    import hashlib, json
    evidence = {"review_id": 1, "text": "metal shaving"}
    payload = json.dumps(evidence, sort_keys=True)
    h = hashlib.sha256(payload.encode()).hexdigest()

    # 插入 review 先满足 FK
    conn = models.get_conn()
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://t/p1", "P", "S1", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'a', 'h', 'b', 1.0)")
    conn.commit()
    conn.close()

    for _ in range(3):
        models.save_safety_incident(
            review_id=1, product_sku="S1", safety_level="critical",
            failure_mode="metal", evidence_snapshot=payload, evidence_hash=h,
        )
    conn = models.get_conn()
    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM safety_incidents WHERE review_id = 1"
    ).fetchone()
    conn.close()
    assert rows["c"] == 1
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/test_p008_phase1.py::test_save_safety_incident_is_idempotent -v
```

Expected: FAIL（count = 3）。

- [ ] **Step 3: Add UNIQUE index migration**

`qbu_crawler/models.py` 的 migrations 列表中（找已有的 `ALTER TABLE review_analysis ADD COLUMN label_anomaly_flags TEXT` 附近）追加：

```python
"CREATE UNIQUE INDEX IF NOT EXISTS idx_safety_incidents_hash ON safety_incidents(evidence_hash)",
```

同时修改原始 DDL（找到 `CREATE TABLE IF NOT EXISTS safety_incidents (...)`），在 `evidence_hash TEXT NOT NULL` 后加 `UNIQUE` 以确保新建库也生效：

```sql
evidence_hash TEXT NOT NULL UNIQUE,
```

- [ ] **Step 4: Change `INSERT` to `INSERT OR IGNORE`**

`qbu_crawler/models.py:2026-2034`：

```python
cur = conn.execute(
    """INSERT OR IGNORE INTO safety_incidents
       (review_id, product_sku, safety_level, failure_mode,
        evidence_snapshot, evidence_hash, detected_at)
       VALUES (?, ?, ?, ?, ?, ?, datetime('now', '+8 hours'))""",
    (review_id, product_sku, safety_level, failure_mode,
     evidence_snapshot, evidence_hash),
)
conn.commit()
return cur.lastrowid  # 重复时 lastrowid = 0 或上次 rowid，这是 SQLite 行为
```

注意 `datetime('now', '+8 hours')` 同时顺带解决 P1-C2——我们会在 Task 6 专门为 DDL default 也做这个修正。此处 INSERT 侧已对齐。

- [ ] **Step 5: Run test, verify PASS**

```bash
uv run pytest tests/test_p008_phase1.py::test_save_safety_incident_is_idempotent -v
```

- [ ] **Step 6: 全量回归**

```bash
uv run pytest tests/ -x --tb=short
```

Expected: 全部 PASS。如有现存 safety 相关测试因时区改动失败，转入 Task 6 一并处理。

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/models.py tests/test_p008_phase1.py
git commit -m "fix(safety): dedupe safety_incidents via UNIQUE(evidence_hash) + INSERT OR IGNORE"
```

---

## Task 6: P1-C2 `safety_incidents` 时区统一为 Shanghai (+8h)

**Files:**
- Modify: `qbu_crawler/models.py` (DDL default + save_safety_incident INSERT 已在 Task 5 修)
- Test: `tests/test_p008_phase1.py`

问题：项目约定 `_NOW_SHANGHAI = "datetime('now', '+8 hours')"`，其它表全部遵循；`safety_incidents.detected_at` 和 `created_at` 用 `datetime('now')` = UTC，与其他时间相差 8 小时，跨表 JOIN 按时间排序会错。Task 5 已修 INSERT 侧，此 Task 修 DDL `DEFAULT`。

- [ ] **Step 1: Write failing test**

在 `tests/test_p008_phase1.py` 追加：

```python
def test_safety_incidents_timestamps_are_shanghai(fresh_db):
    """detected_at 和 created_at 必须与其它表对齐使用 Shanghai 时区。"""
    import hashlib, json
    from datetime import datetime, timedelta

    evidence = json.dumps({"x": 1}, sort_keys=True)
    h = hashlib.sha256(evidence.encode()).hexdigest()
    conn = models.get_conn()
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://t/p1", "P", "S1", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'a', 'h', 'b', 1.0)")
    conn.commit()
    conn.close()

    models.save_safety_incident(
        review_id=1, product_sku="S1", safety_level="critical",
        failure_mode=None, evidence_snapshot=evidence, evidence_hash=h,
    )
    conn = models.get_conn()
    row = conn.execute(
        "SELECT detected_at, created_at FROM safety_incidents WHERE review_id=1"
    ).fetchone()
    conn.close()

    det = datetime.fromisoformat(row["detected_at"])
    now_utc = datetime.utcnow()
    # Shanghai 时间应比 UTC 快 ~8h；允许 ±5 分钟
    delta = det - now_utc
    assert timedelta(hours=7, minutes=55) <= delta <= timedelta(hours=8, minutes=5), \
        f"detected_at drift vs UTC: {delta}"
```

- [ ] **Step 2: Run test, verify behavior**

```bash
uv run pytest tests/test_p008_phase1.py::test_safety_incidents_timestamps_are_shanghai -v
```

如 Task 5 已经改好 `save_safety_incident` 的 INSERT，此测试已经 PASS。若未，FAIL 预期 "drift -0h"。

- [ ] **Step 3: Fix DDL `created_at` default**

`qbu_crawler/models.py` 找 `CREATE TABLE IF NOT EXISTS safety_incidents (...)`，把：

```sql
created_at TEXT NOT NULL DEFAULT (datetime('now'))
```

改为：

```sql
created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
```

已有库的迁移：DDL 的 `DEFAULT` 改动对 SQLite 不影响已存在行（CREATE TABLE IF NOT EXISTS 只在建表时生效）。对已有行 `created_at`，不做历史回填（已是 UTC 数据记录，不应重写）。

- [ ] **Step 4: Run test, verify PASS + 全量回归**

```bash
uv run pytest tests/test_p008_phase1.py::test_safety_incidents_timestamps_are_shanghai -v
uv run pytest tests/ -x --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/models.py tests/test_p008_phase1.py
git commit -m "fix(safety): use Shanghai (+8h) for safety_incidents timestamps to match project convention"
```

---

## Task 7: P2-F2 安全信号分发到 `EMAIL_RECIPIENTS_SAFETY`

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:872-881` (`_send_daily_briefing_email`)
- Test: `tests/test_p008_phase2.py`

问题：检测到 `safety_keyword` 信号时只给标题加 `[安全]` 前缀，收件人不变。配置项 `EMAIL_RECIPIENTS_SAFETY` 已在 Phase 2 Task 2 声明但从未消费。

- [ ] **Step 1: Write failing test**

在 `tests/test_p008_phase2.py` 追加（mock `report.send_email` 统计调用）：

```python
def test_daily_briefing_cc_safety_channel_on_safety_signal(monkeypatch, db):
    """含 safety_keyword attention signal 时必须额外分发到 EMAIL_RECIPIENTS_SAFETY。"""
    from qbu_crawler.server import report_snapshot
    from qbu_crawler import config as cfg

    monkeypatch.setattr(cfg, "EMAIL_RECIPIENTS", ["ops@example.com"])
    monkeypatch.setattr(cfg, "EMAIL_RECIPIENTS_SAFETY", ["safety@example.com"])

    calls = []
    def fake_send(*, recipients, subject, body_html, **kw):
        calls.append({"recipients": list(recipients), "subject": subject})
    monkeypatch.setattr(report_snapshot.report, "send_email", fake_send)

    # 构造最小 run + briefing 数据
    briefing = {
        "window_reviews": [],
        "attention_signals": [
            {"type": "safety_keyword", "level": "critical", "review_id": 42,
             "summary": "metal shaving"},
        ],
        "cumulative_kpis": {"health_index": 70},
        "logical_date": "2026-04-18",
    }
    run = {"id": 999, "logical_date": "2026-04-18", "report_tier": "daily"}

    report_snapshot._send_daily_briefing_email(run, briefing, html_path="/tmp/x.html")

    assert any("[安全]" in c["subject"] for c in calls)
    all_recipients = {r for c in calls for r in c["recipients"]}
    assert "safety@example.com" in all_recipients
    assert "ops@example.com" in all_recipients
```

**注意**：`_send_daily_briefing_email` 的实际签名可能与上文不同。Step 3 之前读代码确认签名，相应调整测试。

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/test_p008_phase2.py::test_daily_briefing_cc_safety_channel_on_safety_signal -v
```

Expected: FAIL — safety@example.com 不在收件人中。

- [ ] **Step 3: Add safety channel dispatch in `_send_daily_briefing_email`**

`qbu_crawler/server/report_snapshot.py` 找 `_send_daily_briefing_email`（大约 860-885 行），在现有 `report.send_email(...)` 之后追加：

```python
# P2-F2: 安全信号独立分发至 SAFETY 通道（避免告警被日常收件人淹没）
if has_safety and getattr(config, "EMAIL_RECIPIENTS_SAFETY", None):
    extra = [
        r for r in config.EMAIL_RECIPIENTS_SAFETY
        if r and r not in recipients
    ]
    if extra:
        report.send_email(
            recipients=extra,
            subject=subject,
            body_html=body_html,
        )
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/test_p008_phase2.py::test_daily_briefing_cc_safety_channel_on_safety_signal -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase2.py
git commit -m "fix(safety): dispatch safety signals to EMAIL_RECIPIENTS_SAFETY channel"
```

---

## Task 8: P3-I2 `freeze_report_snapshot` 传入冷启动 `expected_days/actual_days`

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:378-380` (`freeze_report_snapshot`)
- Test: `tests/test_p008_phase3.py`

问题：`_inject_meta` 已支持 `expected_days`/`actual_days`（line 22-37），但 `freeze_report_snapshot` 只调用 `_inject_meta(snapshot, tier=run_tier)`，cold start 标记永远不会产生。

- [ ] **Step 1: 阅读 `freeze_report_snapshot` 周围代码（370-400 行）**

确认以下变量在 `_inject_meta` 调用前可用：
- `run_tier`（已有）
- `run["data_since"]` / `run["data_until"]`（已有，ISO 字符串）

若 `data_since/data_until` 字段命名不同，调整下文示例。

- [ ] **Step 2: Write failing test**

在 `tests/test_p008_phase3.py` 追加：

```python
def test_freeze_snapshot_sets_is_partial_on_short_weekly(db, tmp_path, monkeypatch):
    """Weekly run 数据不足 7 天时，_meta.is_partial 应为 True 并含 expected/actual days。"""
    from qbu_crawler.server import report_snapshot

    # 4 天窗口的周报（冷启动）
    run = {
        "id": 1, "workflow_type": "weekly", "report_tier": "weekly",
        "logical_date": "2026-04-13",
        "data_since": "2026-04-09T00:00:00+08:00",
        "data_until": "2026-04-13T00:00:00+08:00",
    }

    # 桩 models 与 report 的查询返回空
    monkeypatch.setattr(report_snapshot.models, "get_workflow_run", lambda rid: run)
    monkeypatch.setattr(report_snapshot.report, "query_report_data",
                        lambda since, until: ([], []))
    monkeypatch.setattr(report_snapshot.report, "query_cumulative_data",
                        lambda: ([], []))
    monkeypatch.setattr(report_snapshot, "_enrich_reviews_with_analysis",
                        lambda revs, ids: None)

    out_path = tmp_path / "snap.json"
    snapshot = report_snapshot.freeze_report_snapshot(run["id"], str(out_path))

    assert snapshot["_meta"]["report_tier"] == "weekly"
    assert snapshot["_meta"].get("is_partial") is True
    assert snapshot["_meta"]["expected_days"] == 7
    assert snapshot["_meta"]["actual_days"] == 4


def test_freeze_snapshot_full_week_has_no_is_partial(db, tmp_path, monkeypatch):
    """满 7 天的 weekly run 不应带 is_partial。"""
    from qbu_crawler.server import report_snapshot

    run = {
        "id": 1, "workflow_type": "weekly", "report_tier": "weekly",
        "logical_date": "2026-04-20",
        "data_since": "2026-04-13T00:00:00+08:00",
        "data_until": "2026-04-20T00:00:00+08:00",
    }
    monkeypatch.setattr(report_snapshot.models, "get_workflow_run", lambda rid: run)
    monkeypatch.setattr(report_snapshot.report, "query_report_data",
                        lambda since, until: ([], []))
    monkeypatch.setattr(report_snapshot.report, "query_cumulative_data",
                        lambda: ([], []))
    monkeypatch.setattr(report_snapshot, "_enrich_reviews_with_analysis",
                        lambda revs, ids: None)

    out_path = tmp_path / "snap.json"
    snapshot = report_snapshot.freeze_report_snapshot(run["id"], str(out_path))

    assert snapshot["_meta"].get("is_partial") is not True
```

**注意**：monkeypatch 的函数名要与 `freeze_report_snapshot` 实际依赖的调用对应。读 Step 1 源码确认，必要时替换为真实桩点。

- [ ] **Step 3: Run tests, verify FAIL**

```bash
uv run pytest tests/test_p008_phase3.py -k "is_partial" -v
```

- [ ] **Step 4: Fix `freeze_report_snapshot`**

找到 line 378-380：

```python
run_tier = run.get("report_tier", "daily")
_inject_meta(snapshot, tier=run_tier)
```

替换为：

```python
from datetime import datetime

run_tier = run.get("report_tier", "daily")
_EXPECTED_DAYS = {"weekly": 7, "monthly": 30}
expected = _EXPECTED_DAYS.get(run_tier)
if expected and run.get("data_since") and run.get("data_until"):
    try:
        since_d = datetime.fromisoformat(run["data_since"]).date()
        until_d = datetime.fromisoformat(run["data_until"]).date()
        actual = (until_d - since_d).days
    except (TypeError, ValueError):
        actual = None
    if actual is not None:
        _inject_meta(snapshot, tier=run_tier,
                     expected_days=expected, actual_days=actual)
    else:
        _inject_meta(snapshot, tier=run_tier)
else:
    _inject_meta(snapshot, tier=run_tier)
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
uv run pytest tests/test_p008_phase3.py -k "is_partial" -v
uv run pytest tests/test_p008_phase3.py tests/test_p008_phase4.py -v
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase3.py
git commit -m "fix(cold-start): compute actual vs expected days and inject is_partial meta"
```

---

## Task 9: P3-I3 V3 模板冷周提示

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/test_p008_phase3.py`

问题：周报共享 V3 HTML 模板，冷周（7 天 0 新评论）仍按正常排版渲染 Tabs，用户无法感知"这是累积数据，不是本周增量"。Task 11 Step 3 的要求未落地。

- [ ] **Step 1: 确认模板当前结构**

```
Read file: qbu_crawler/server/report_templates/daily_report_v3.html.j2
```

重点查 Issues Tab 的起始位置（搜 `id="tab-issues"` 或 `problem clusters`）。记下插入点行号。

- [ ] **Step 2: Write failing test**

在 `tests/test_p008_phase3.py` 追加：

```python
def test_v3_html_shows_cold_week_notice_when_window_empty(tmp_path):
    """窗口期无新评论 + is_partial=False 但零 reviews 时，issues tab 开头应提示冷周。"""
    from qbu_crawler.server.report_html import render_v3_html

    snapshot = {
        "logical_date": "2026-04-20",
        "data_since": "2026-04-13T00:00:00+08:00",
        "data_until": "2026-04-20T00:00:00+08:00",
        "products": [],
        "reviews": [],
        "cumulative": {
            "products": [{"name": "X", "sku": "S1", "ownership": "own",
                           "rating": 4.5, "review_count": 10, "site": "t",
                           "price": 100, "stock_status": "in_stock"}],
            "reviews": [],
        },
        "_meta": {"report_tier": "weekly", "schema_version": "3"},
    }
    analytics = {"mode": "incremental", "kpis": {},
                 "self": {"risk_products": [], "top_negative_clusters": []}}
    out = render_v3_html(snapshot, analytics, output_path=str(tmp_path / "r.html"))
    html = open(out, encoding="utf-8").read()
    assert "本周无新数据变动" in html or "累积分析" in html
```

- [ ] **Step 3: Run test, verify FAIL**

```bash
uv run pytest tests/test_p008_phase3.py::test_v3_html_shows_cold_week_notice_when_window_empty -v
```

- [ ] **Step 4: Insert cold-week banner in template**

`qbu_crawler/server/report_templates/daily_report_v3.html.j2` 找 Issues Tab panel 起始（例如 `<section id="tab-issues" ...>`），在 `<h2 class="section-title">` 后加：

```html
{% set _win_reviews = snapshot.reviews if snapshot.reviews is defined else [] %}
{% if _win_reviews|length == 0 %}
<div class="empty-state" style="margin-bottom:var(--sp-md);background:var(--surface-muted,#f7fafc);padding:var(--sp-md);border-left:3px solid var(--text-muted,#a0aec0);color:var(--text-muted,#4a5568);font-size:13px;">
  本期窗口内无新评论变动，以下为累积分析。
</div>
{% endif %}
```

- [ ] **Step 5: Run test, verify PASS**

```bash
uv run pytest tests/test_p008_phase3.py::test_v3_html_shows_cold_week_notice_when_window_empty -v
```

同时运行 V3 模板相关测试以确保无回归：

```bash
uv run pytest tests/test_v3_html.py tests/test_v3_modes.py tests/test_p008_phase1.py -v
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 tests/test_p008_phase3.py
git commit -m "feat(v3): render cold-week notice in Issues tab when window has no reviews"
```

---

## Post-Implementation Checklist

- [ ] `uv run pytest tests/ -v` — 全绿，无 regression
- [ ] 抓一个最近完成的 daily + weekly run（生产或 dev DB），人工跑一次 report 生成：
  - daily briefing 的 attention_signals 和 email "上次链接" 都只引用前一日报
  - weekly 的 Tab 2 变化对比前一周报
  - monthly 如已有 run，确认 stance 计算正确（造一个 0.06 neg_rate 场景，应进入 needs_attention）
  - 若存在 4-7 天数据的 weekly snapshot JSON，`_meta.is_partial == True`
  - 空窗口 weekly HTML 显示冷周提示条
  - safety_incidents 表抽一行看 `detected_at` 时区（UTC+8）
  - 触发两次相同 review 的 safety 写入，确认 `COUNT(*) == 1`
- [ ] 手动触发一条 safety_keyword 日报，检查 `EMAIL_RECIPIENTS_SAFETY` 收件人确实收到邮件
- [ ] 写 devlog：`docs/devlogs/D015-p008-audit-fixes.md`，记录本次 9 项修复对账 + 余留 🟡/🟢 清单

---

## Follow-up (下一批修复建议)

本计划完成后建议开下一 plan 覆盖 🟡 级：

- P1-I1 DB timeout / P1-I3-I4 测试覆盖
- P2-F3 attention_signals 去重 / P2-F4 7d 连续差评窗口 / P2-F5 monkeypatch 签名
- P3-I4 scheduler 超时降级 / P3-I5 跨 tier prev_run 语义
- P4-I5 lifecycle R2 history label / P4-I6 MonthlySchedulerWorker 轮询 interval

以及 🟢 级作为 tech debt backlog。
