# P006 报告系统 Bug 修复 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复每日报告系统的 7 个已知 bug，包括：激活 change/quiet 报告模式、统一 LLM 数据上下文、健康指数样本量修正、激活 KPI Delta 计算、修复基线退出条件、竞品差距指数样本保护、统一邮件收件人来源。

**Architecture:** 纯后端变更 + 邮件模板微调。每个 Fix 独立可测试，按依赖顺序逐个合入。Fix-7 最简单放第一个，Fix-1 最复杂放最后。

**Tech Stack:** Python 3.10+, pytest, SQLite, Jinja2 templates, uv

**Spec Reference:** `docs/plans/P006-report-bugfixes.md`（含审查修正节）

**Baseline:** 508 tests passing. Test command: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/server/report_snapshot.py` | Modify | Fix-7: 统一邮件收件人；Fix-1: change/quiet 补 snapshot_hash |
| `qbu_crawler/server/report_analytics.py` | Modify | Fix-5: 基线退出条件 SQL；Fix-4: 在 build 末尾调用 _compute_kpi_deltas |
| `qbu_crawler/server/report_common.py` | Modify | Fix-3: compute_health_index 返回 tuple；Fix-6: 样本保护（调用方） |
| `qbu_crawler/server/report_llm.py` | Modify | Fix-2: _select_insight_samples 改为 snapshot-only |
| `qbu_crawler/server/workflows.py` | Modify | Fix-1: 移除 early return + _should_send_workflow_email 改为始终 True |
| `qbu_crawler/server/notifier.py` | Modify | Fix-1: DingTalk 通知模板处理 excel_path=None |
| `qbu_crawler/server/report_templates/email_full.html.j2` | Modify | Fix-3: health_confidence 条件渲染；Fix-6: None 值保护 |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | Modify | Fix-6: competitive_gap_index None 值保护 |
| `tests/test_report_common.py` | Modify | Fix-3, Fix-6: 更新现有测试 + 新增测试 |
| `tests/test_report_analytics.py` | Modify | Fix-5: 基线退出条件测试；Fix-4: KPI delta 集成测试 |
| `tests/test_report_llm.py` | Modify | Fix-2: 新增 snapshot-only 采样测试 |
| `tests/test_report_snapshot.py` | Modify | Fix-7: 收件人统一测试；Fix-1: workflow 邮件逻辑测试 |

---

### Task 1: Fix-7 — 统一邮件收件人来源

**目标**：full/change/quiet 三种模式统一使用 `_get_email_recipients()` 函数获取收件人，优先 `config.EMAIL_RECIPIENTS`（环境变量），fallback 到 `openclaw/.../email_recipients.txt` 文件。

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (line 482-485, 761)
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for _get_email_recipients (Fix-7: unified recipient source)
# ---------------------------------------------------------------------------


def test_get_email_recipients_prefers_env_var(monkeypatch):
    """When config.EMAIL_RECIPIENTS is set, it should be returned directly."""
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr("qbu_crawler.config.EMAIL_RECIPIENTS", ["a@test.com", "b@test.com"])
    result = report_snapshot._get_email_recipients()
    assert result == ["a@test.com", "b@test.com"]


def test_get_email_recipients_falls_back_to_file(monkeypatch, tmp_path):
    """When config.EMAIL_RECIPIENTS is empty, read from file."""
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr("qbu_crawler.config.EMAIL_RECIPIENTS", [])
    # Create a temp recipients file
    recipients_file = tmp_path / "email_recipients.txt"
    recipients_file.write_text("c@test.com\n# comment\nd@test.com\n", encoding="utf-8")
    monkeypatch.setattr(
        report_snapshot, "_RECIPIENTS_FILE_PATH",
        str(recipients_file),
    )
    result = report_snapshot._get_email_recipients()
    assert result == ["c@test.com", "d@test.com"]


def test_get_email_recipients_returns_empty_when_no_source(monkeypatch, tmp_path):
    """When both sources are empty, return empty list."""
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr("qbu_crawler.config.EMAIL_RECIPIENTS", [])
    monkeypatch.setattr(
        report_snapshot, "_RECIPIENTS_FILE_PATH",
        str(tmp_path / "nonexistent.txt"),
    )
    result = report_snapshot._get_email_recipients()
    assert result == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_snapshot.py::test_get_email_recipients_prefers_env_var -v`
Expected: FAIL — `AttributeError: module 'qbu_crawler.server.report_snapshot' has no attribute '_get_email_recipients'`

- [ ] **Step 3: 实现 `_get_email_recipients()` 函数**

在 `qbu_crawler/server/report_snapshot.py` 中，在模块顶部（import 区域后、函数定义前）添加模块级常量，然后添加函数。

首先找到 report_snapshot.py 的 import 区域末尾，在适当位置添加常量：

```python
# old_string (在文件中找一个合适的位置，在 import 之后的常量定义区域)
_logger = logging.getLogger(__name__)

# new_string
_logger = logging.getLogger(__name__)

_RECIPIENTS_FILE_PATH = os.path.join(
    os.path.dirname(__file__), "openclaw", "workspace", "config", "email_recipients.txt"
)


def _get_email_recipients() -> list[str]:
    """Unified email recipient loader.

    Priority: config.EMAIL_RECIPIENTS (env var) > openclaw file > empty list.
    """
    if config.EMAIL_RECIPIENTS:
        return list(config.EMAIL_RECIPIENTS)

    if os.path.exists(_RECIPIENTS_FILE_PATH):
        return report.load_email_recipients(_RECIPIENTS_FILE_PATH)
    return []
```

- [ ] **Step 4: 替换 change/quiet 模式中的文件读取**

在 `_send_mode_email()` 函数中（约 line 481-485），将：

```python
    # Load recipients and send
    recipients_file = os.path.join(
        os.path.dirname(__file__), "openclaw", "workspace", "config", "email_recipients.txt"
    )
    recipients = report.load_email_recipients(recipients_file) if os.path.exists(recipients_file) else []
```

替换为：

```python
    # Load recipients and send
    recipients = _get_email_recipients()
```

- [ ] **Step 5: 替换 full 模式中的环境变量读取**

在 `generate_full_report_from_snapshot()` 函数中（约 line 761），将：

```python
            email_result = report.send_email(
                recipients=config.EMAIL_RECIPIENTS,
```

替换为：

```python
            email_result = report.send_email(
                recipients=_get_email_recipients(),
```

- [ ] **Step 6: 替换 generate_report_from_snapshot 异常通知中的文件读取**

在 `generate_report_from_snapshot()` 的异常处理块中（约 line 625-628），将：

```python
            recipients_file = os.path.join(
                os.path.dirname(__file__), "openclaw", "workspace", "config", "email_recipients.txt"
            )
            recipients = report.load_email_recipients(recipients_file) if os.path.exists(recipients_file) else []
```

替换为：

```python
            recipients = _get_email_recipients()
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest tests/test_report_snapshot.py::test_get_email_recipients_prefers_env_var tests/test_report_snapshot.py::test_get_email_recipients_falls_back_to_file tests/test_report_snapshot.py::test_get_email_recipients_returns_empty_when_no_source -v`
Expected: 3 passed

- [ ] **Step 8: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 511+ passed

- [ ] **Step 9: 提交**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "fix(report): unify email recipient source across all report modes (Fix-7)"
```

---

### Task 2: Fix-5 — 放宽基线模式退出条件

**目标**：`detect_report_mode()` 的 SQL 不再要求 `analytics_path IS NOT NULL`，所有已完成的 daily run（含 quiet/skipped）都计入 3 次阈值，避免系统长期停留在 baseline 模式。

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (line 493-522)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_analytics.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for detect_report_mode baseline exit condition (Fix-5)
# ---------------------------------------------------------------------------


def test_detect_report_mode_counts_quiet_runs(analytics_db):
    """Quiet runs (no analytics_path) should count toward the 3-run baseline threshold."""
    from qbu_crawler.server.report_analytics import detect_report_mode

    # Create 2 completed runs WITH analytics + 1 WITHOUT (quiet/skipped)
    _create_daily_run("2026-04-01", status="completed", analytics_path="/tmp/a1.json")
    _create_daily_run("2026-04-02", status="completed", analytics_path=None)  # quiet run
    _create_daily_run("2026-04-03", status="completed", analytics_path="/tmp/a3.json")

    # Current run
    current = _create_daily_run("2026-04-04", status="reporting")

    result = detect_report_mode(current["id"], "2026-04-04")
    # 3 completed runs exist → should be incremental, not baseline
    assert result["mode"] == "incremental", (
        f"Expected incremental with 3 completed runs (1 quiet), got {result['mode']} "
        f"with baseline_sample_days={result['baseline_sample_days']}"
    )


def test_detect_report_mode_baseline_with_fewer_than_3(analytics_db):
    """Fewer than 3 completed runs should remain baseline."""
    from qbu_crawler.server.report_analytics import detect_report_mode

    _create_daily_run("2026-04-01", status="completed", analytics_path=None)
    _create_daily_run("2026-04-02", status="completed", analytics_path=None)

    current = _create_daily_run("2026-04-04", status="reporting")

    result = detect_report_mode(current["id"], "2026-04-04")
    assert result["mode"] == "baseline"
    assert result["baseline_sample_days"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py::test_detect_report_mode_counts_quiet_runs -v`
Expected: FAIL — `assert result["mode"] == "incremental"` (currently returns "baseline" because quiet runs have no analytics_path)

- [ ] **Step 3: 修改 SQL 移除 analytics_path 过滤**

在 `qbu_crawler/server/report_analytics.py` 中（line 498-511），将：

```python
        rows = conn.execute(
            """
            SELECT id, logical_date
            FROM workflow_runs
            WHERE workflow_type = 'daily'
              AND status = 'completed'
              AND analytics_path IS NOT NULL
              AND analytics_path != ''
              AND logical_date >= ?
              AND logical_date < ?
              AND id != ?
            ORDER BY logical_date ASC, id ASC
            """,
            (since_date, logical_date, run_id),
        ).fetchall()
```

替换为：

```python
        rows = conn.execute(
            """
            SELECT id, logical_date
            FROM workflow_runs
            WHERE workflow_type = 'daily'
              AND status = 'completed'
              AND logical_date >= ?
              AND logical_date < ?
              AND id != ?
            ORDER BY logical_date ASC, id ASC
            """,
            (since_date, logical_date, run_id),
        ).fetchall()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py::test_detect_report_mode_counts_quiet_runs tests/test_report_analytics.py::test_detect_report_mode_baseline_with_fewer_than_3 -v`
Expected: 2 passed

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 513+ passed

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "fix(report): relax baseline exit condition to count quiet/skipped runs (Fix-5)"
```

---

### Task 3: Fix-6 — 竞品差距指数最小样本保护

**目标**：当自有+竞品总评论数 < 20 时，`competitive_gap_index` 设为 `None` 而非放大噪声。模板中正确处理 `None` 值显示为 "---" 而非文字 "None"。

**重要**：不修改 `compute_competitive_gap_index()` 的签名和实现，仅在调用方 `normalize_deep_report_analytics()` 中做样本量检查。

**Files:**
- Modify: `qbu_crawler/server/report_common.py` (line 867-870)
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2` (line 91)
- Modify: `qbu_crawler/server/report_templates/daily_report_email.html.j2` (line 121)
- Test: `tests/test_report_common.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_common.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for competitive_gap_index sample protection (Fix-6)
# ---------------------------------------------------------------------------


def test_normalize_sets_gap_index_none_when_low_sample():
    """When total reviews < 20, competitive_gap_index should be None."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 5,
            "negative_review_rows": 1,
            "translated_count": 5,
            "own_product_count": 1,
            "own_avg_rating": 4.5,
            "own_review_rows": 3,
            "competitor_review_rows": 2,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 2, "own_negative_count": 1,
                 "competitor_total": 2, "own_total": 3},
            ],
        },
    }
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["competitive_gap_index"] is None


def test_normalize_computes_gap_index_when_sufficient_sample():
    """When total reviews >= 20, competitive_gap_index should be computed normally."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 40,
            "negative_review_rows": 5,
            "translated_count": 40,
            "own_product_count": 2,
            "own_avg_rating": 4.0,
            "own_review_rows": 20,
            "competitor_review_rows": 20,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 10, "own_negative_count": 5,
                 "competitor_total": 20, "own_total": 20},
            ],
        },
    }
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["competitive_gap_index"] is not None
    assert isinstance(result["kpis"]["competitive_gap_index"], (int, float))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_common.py::test_normalize_sets_gap_index_none_when_low_sample -v`
Expected: FAIL — `assert result["kpis"]["competitive_gap_index"] is None` (currently returns an int even with 5 reviews)

- [ ] **Step 3: 在调用方添加样本量检查**

在 `qbu_crawler/server/report_common.py` 中（line 867-870），将：

```python
    # ── Compute health_index, competitive_gap_index, high_risk_count ─────
    normalized["kpis"]["health_index"] = compute_health_index(normalized)
    normalized["kpis"]["competitive_gap_index"] = compute_competitive_gap_index(
        normalized.get("competitor", {}).get("gap_analysis") or []
    )
```

替换为：

```python
    # ── Compute health_index, competitive_gap_index, high_risk_count ─────
    normalized["kpis"]["health_index"] = compute_health_index(normalized)

    _total_reviews_for_gap = (
        normalized.get("kpis", {}).get("own_review_rows", 0)
        + normalized.get("kpis", {}).get("competitor_review_rows", 0)
    )
    _MIN_GAP_SAMPLE = 20
    if _total_reviews_for_gap < _MIN_GAP_SAMPLE:
        normalized["kpis"]["competitive_gap_index"] = None
    else:
        normalized["kpis"]["competitive_gap_index"] = compute_competitive_gap_index(
            normalized.get("competitor", {}).get("gap_analysis") or []
        )
```

- [ ] **Step 4: 修复 email_full.html.j2 模板中 None 值渲染**

在 `qbu_crawler/server/report_templates/email_full.html.j2` 中（line 91），将：

```html
            <div style="font-size:24px;font-weight:800;color:#047857;line-height:1;">{{ _kpis.get("competitive_gap_index", "—") if _kpis else "—" }}</div>
```

替换为：

```html
            <div style="font-size:24px;font-weight:800;color:#047857;line-height:1;">{% if _kpis.get("competitive_gap_index") is not none %}{{ _kpis.get("competitive_gap_index") }}{% else %}—{% endif %}</div>
```

- [ ] **Step 5: 修复 daily_report_email.html.j2 模板中 None 值渲染**

在 `qbu_crawler/server/report_templates/daily_report_email.html.j2` 中（line 121），将：

```html
            <div style="font-size:26px;font-weight:800;color:#345f57;line-height:1;">{{ analytics.kpis.competitive_gap_index | default('—') }}</div>
```

替换为：

```html
            <div style="font-size:26px;font-weight:800;color:#345f57;line-height:1;">{% if analytics.kpis.competitive_gap_index is not none %}{{ analytics.kpis.competitive_gap_index }}{% else %}—{% endif %}</div>
```

- [ ] **Step 6: 修复 kpi_cards 构建器中的 None 处理**

在 `qbu_crawler/server/report_common.py` 中，kpi_cards 构建区域（约 line 922）使用 `kpis.get("competitive_gap_index", "—")` 来获取值。但当 key 存在且值为 `None` 时，`.get()` 返回 `None` 而非默认值 `"—"`。这会导致 V3 HTML 报告中显示文字 `"None"`。

找到 kpi_cards 中竞品差距指数卡片的构建代码，将 `"value"` 的取值逻辑改为显式处理 None：

```python
# old_string (在 kpi_cards 构建区域，约 line 920-925 附近)
"value": kpis.get("competitive_gap_index", "—"),

# new_string
"value": kpis.get("competitive_gap_index") if kpis.get("competitive_gap_index") is not None else "—",
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest tests/test_report_common.py::test_normalize_sets_gap_index_none_when_low_sample tests/test_report_common.py::test_normalize_computes_gap_index_when_sufficient_sample -v`
Expected: 2 passed

- [ ] **Step 8: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 515+ passed

- [ ] **Step 9: 提交**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_templates/email_full.html.j2 qbu_crawler/server/report_templates/daily_report_email.html.j2 tests/test_report_common.py
git commit -m "fix(report): protect competitive gap index against low sample sizes (Fix-6)"
```

---

### Task 4: Fix-3 — 健康指数增加贝叶斯样本量修正

**目标**：`compute_health_index()` 返回 `(float, str)` 元组（health, confidence），调用方解包后分别存 `health_index` 和 `health_confidence`。样本不足时向先验值 50.0 收缩。

**重要**：不改变 `health_index` 字段类型（始终 float），新增 `health_confidence` 字段。模板只需在 full 模式和 V3 报告中展示 confidence 信息。

**Files:**
- Modify: `qbu_crawler/server/report_common.py` (line 493-514, 867)
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2` (line 36)
- Test: `tests/test_report_common.py` (update existing + add new)

- [ ] **Step 1: 写新测试（不改现有测试）**

在 `tests/test_report_common.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for compute_health_index Bayesian shrinkage (Fix-3)
# ---------------------------------------------------------------------------


def test_compute_health_index_returns_tuple():
    """compute_health_index should return (health, confidence) tuple."""
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    result = report_common.compute_health_index(analytics)
    assert isinstance(result, tuple)
    assert len(result) == 2
    health, confidence = result
    assert isinstance(health, float)
    assert confidence in ("high", "medium", "low", "no_data")


def test_compute_health_index_shrinks_small_sample():
    """1 perfect review: raw=100, but should shrink toward 50."""
    analytics = {
        "kpis": {
            "own_review_rows": 1,
            "own_positive_review_rows": 1,
            "own_negative_review_rows": 0,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight = 1/30, health = 1/30 * 100 + 29/30 * 50 = 51.67
    assert 51.0 <= health <= 52.5
    assert confidence == "low"


def test_compute_health_index_medium_confidence():
    """10 reviews: medium confidence, partial shrinkage."""
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight = 10/30, health = 10/30 * 100 + 20/30 * 50 = 66.67
    assert 66.0 <= health <= 67.5
    assert confidence == "medium"


def test_compute_health_index_high_confidence():
    """30+ reviews: no shrinkage, high confidence."""
    analytics = {
        "kpis": {
            "own_review_rows": 100,
            "own_positive_review_rows": 90,
            "own_negative_review_rows": 5,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # NPS = (90-5)/100 * 100 = 85, health = (85+100)/2 = 92.5
    assert health == 92.5
    assert confidence == "high"


def test_compute_health_index_no_data():
    analytics = {"kpis": {"own_review_rows": 0}}
    health, confidence = report_common.compute_health_index(analytics)
    assert health == 50.0
    assert confidence == "no_data"


def test_normalize_injects_health_confidence():
    """normalize_deep_report_analytics should set health_confidence alongside health_index."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 2,
            "negative_review_rows": 1,
            "translated_count": 2,
            "own_product_count": 1,
            "own_avg_rating": 3.0,
            "own_review_rows": 2,
            "competitor_review_rows": 0,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "health_confidence" in result["kpis"]
    assert result["kpis"]["health_confidence"] in ("low", "medium", "high", "no_data")
    assert isinstance(result["kpis"]["health_index"], float)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_common.py::test_compute_health_index_returns_tuple -v`
Expected: FAIL — `assert isinstance(result, tuple)` (currently returns float)

- [ ] **Step 3: 修改 compute_health_index 返回 tuple**

在 `qbu_crawler/server/report_common.py` 中（line 493-514），将：

```python
def compute_health_index(analytics: dict) -> float:
    """NPS-proxy health index.

    Maps Net Promoter Score (-100..+100) to a 0..100 scale:
        promoters (rating >= 4) minus detractors (rating <= NEGATIVE_THRESHOLD),
        divided by total own reviews, times 100, then linearly mapped.

    Industry benchmarks for consumer products:
        > 75 excellent, 60-75 good, 50-60 needs attention, < 50 critical.
    """
    kpis = analytics.get("kpis", {}) if isinstance(analytics, dict) else {}
    own_reviews = kpis.get("own_review_rows", 0)
    if own_reviews == 0:
        return 50.0  # No data → neutral sentinel

    promoters = kpis.get("own_positive_review_rows", 0)
    detractors = kpis.get("own_negative_review_rows", 0)

    nps = ((promoters - detractors) / own_reviews) * 100
    health = (nps + 100) / 2

    return round(max(0.0, min(100.0, health)), 1)
```

替换为：

```python
def compute_health_index(analytics: dict) -> tuple[float, str]:
    """NPS-proxy health index with Bayesian shrinkage for small samples.

    Returns (health_index, confidence) where:
        health_index: 0-100 scale (shrunk toward 50.0 prior when sample < 30)
        confidence: "high" (>=30), "medium" (5-29), "low" (<5), "no_data" (0)

    Maps Net Promoter Score (-100..+100) to a 0..100 scale:
        promoters (rating >= 4) minus detractors (rating <= NEGATIVE_THRESHOLD),
        divided by total own reviews, times 100, then linearly mapped.

    Industry benchmarks for consumer products:
        > 75 excellent, 60-75 good, 50-60 needs attention, < 50 critical.
    """
    kpis = analytics.get("kpis", {}) if isinstance(analytics, dict) else {}
    own_reviews = kpis.get("own_review_rows", 0)
    if own_reviews == 0:
        return 50.0, "no_data"

    promoters = kpis.get("own_positive_review_rows", 0)
    detractors = kpis.get("own_negative_review_rows", 0)

    nps = ((promoters - detractors) / own_reviews) * 100
    raw_health = (nps + 100) / 2

    # Bayesian shrinkage: pull toward prior (50.0) when sample is small
    MIN_RELIABLE = 30
    PRIOR = 50.0
    if own_reviews < MIN_RELIABLE:
        weight = own_reviews / MIN_RELIABLE
        health = weight * raw_health + (1 - weight) * PRIOR
        confidence = "low" if own_reviews < 5 else "medium"
    else:
        health = raw_health
        confidence = "high"

    return round(max(0.0, min(100.0, health)), 1), confidence
```

- [ ] **Step 4: 修改调用方解包 tuple**

在 `qbu_crawler/server/report_common.py` 中（line 867），将：

```python
    normalized["kpis"]["health_index"] = compute_health_index(normalized)
```

替换为：

```python
    _health, _health_confidence = compute_health_index(normalized)
    normalized["kpis"]["health_index"] = _health
    normalized["kpis"]["health_confidence"] = _health_confidence
```

- [ ] **Step 5: 更新现有测试以解包 tuple**

在 `tests/test_report_common.py` 中，更新 `test_compute_health_index_perfect`（line 411-420），将：

```python
def test_compute_health_index_perfect():
    # NPS-proxy: all promoters → NPS=100, health=100
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    assert report_common.compute_health_index(analytics) == 100.0
```

替换为：

```python
def test_compute_health_index_perfect():
    # NPS-proxy: all promoters → NPS=100 — but only 10 reviews so shrinkage applies
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight=10/30, health = 10/30*100 + 20/30*50 = 66.67
    assert 66.0 <= health <= 67.5
    assert confidence == "medium"
```

更新 `test_compute_health_index_worst`（line 423-432），将：

```python
def test_compute_health_index_worst():
    # NPS-proxy: all detractors → NPS=-100, health=0
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 0,
            "own_negative_review_rows": 10,
        },
    }
    assert report_common.compute_health_index(analytics) == 0.0
```

替换为：

```python
def test_compute_health_index_worst():
    # NPS-proxy: all detractors → NPS=-100 — but only 10 reviews so shrinkage applies
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 0,
            "own_negative_review_rows": 10,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight=10/30, health = 10/30*0 + 20/30*50 = 33.33
    assert 33.0 <= health <= 34.0
    assert confidence == "medium"
```

- [ ] **Step 6: 修复 test_normalize_injects_health_index（如果 assert 值依赖旧返回值）**

检查 `test_normalize_injects_health_index`（约 line 476-489）。当前测试只检查 `"health_index" in result["kpis"]`，不检查具体数值，因此调用方改用解包后 float 值仍然通过，无需修改。

- [ ] **Step 7: 在 email_full.html.j2 hero 区添加 confidence 信息**

在 `qbu_crawler/server/report_templates/email_full.html.j2` 中（line 36-37），将：

```html
      <div style="font-size:52px;font-weight:900;color:{{ hero_color }};line-height:1;margin-bottom:6px;">{{ _kpis.get("health_index", "—") if _kpis else "—" }}</div>
      <div style="font-size:12px;color:{{ hero_color }};opacity:0.6;">/ 100 · 深度日报</div>
```

替换为：

```html
      <div style="font-size:52px;font-weight:900;color:{{ hero_color }};line-height:1;margin-bottom:6px;">{{ _kpis.get("health_index", "—") if _kpis else "—" }}</div>
      {% if _kpis.get("health_confidence") == "low" %}
      <div style="font-size:11px;color:{{ hero_color }};opacity:0.7;margin-bottom:4px;">&#9888; 样本仅 {{ _kpis.get("own_review_rows", 0) }} 条，置信度低</div>
      {% elif _kpis.get("health_confidence") == "medium" %}
      <div style="font-size:11px;color:{{ hero_color }};opacity:0.7;margin-bottom:4px;">样本 {{ _kpis.get("own_review_rows", 0) }} 条</div>
      {% endif %}
      <div style="font-size:12px;color:{{ hero_color }};opacity:0.6;">/ 100 · 深度日报</div>
```

- [ ] **Step 8: 运行新测试确认通过**

Run: `uv run pytest tests/test_report_common.py::test_compute_health_index_returns_tuple tests/test_report_common.py::test_compute_health_index_shrinks_small_sample tests/test_report_common.py::test_compute_health_index_medium_confidence tests/test_report_common.py::test_compute_health_index_high_confidence tests/test_report_common.py::test_compute_health_index_no_data tests/test_report_common.py::test_normalize_injects_health_confidence -v`
Expected: 6 passed

- [ ] **Step 9: 修复 test_v3_algorithms.py 中的 6 个测试**

`tests/test_v3_algorithms.py` 中的 `TestHealthIndexV3` 类有 6 个测试直接调用 `compute_health_index()` 并期望返回 float。改为 tuple 后全部 break。需要：
1. 更新所有 `compute_health_index(...)` 调用为解包形式 `compute_health_index(...)[0]` 或 `health, conf = compute_health_index(...)`
2. 部分期望值因贝叶斯收缩而改变（如 `test_all_promoters` 的 10 条评论：旧值 100.0 → 新值 66.7）

```python
# 对每个测试方法，将：
#   result = compute_health_index({"kpis": kpis})
#   assert result == 100.0
# 改为：
#   health, confidence = compute_health_index({"kpis": kpis})
#   assert confidence == "medium"  # 10 reviews < 30
#   # 检查收缩后的值而非原始值

# test_all_promoters (10 reviews, all positive):
#   raw=100, weight=10/30=0.333, health=0.333*100+0.667*50=66.7
#   old: assert result == 100.0 → new: assert health == 66.7

# test_all_detractors (10 reviews, all negative):
#   raw=0, weight=10/30=0.333, health=0.333*0+0.667*50=33.3
#   old: assert result == 0.0 → new: assert health == 33.3

# test_zero_own_reviews_returns_neutral:
#   old: assert result == 50.0 → new: assert health == 50.0, confidence == "no_data"

# test_balanced_reviews (10 reviews, 5 pos + 5 neg):
#   raw=50, weight=0.333, health=0.333*50+0.667*50=50.0
#   old and new both 50.0 (收缩无效因为 raw==prior)

# test_clamped_to_0_100:
#   assert 0 <= health <= 100  (仍然成立)

# test_missing_kpis_returns_neutral:
#   old: assert result == 50.0 → new: assert health == 50.0, confidence == "no_data"
```

- [ ] **Step 10: 修复 test_report_common.py 中的 test_health_index_sensitive_to_negative_spike**

此测试在 `tests/test_report_common.py` 约 line 1008 调用 `compute_health_index()` 并对返回值做算术运算 `idx_baseline - idx_spiked > 15`。需要解包 tuple：

```python
# old:
#   idx_baseline = compute_health_index(analytics_baseline)
#   idx_spiked = compute_health_index(analytics_spiked)
#   assert idx_baseline - idx_spiked > 15

# new:
#   idx_baseline, _ = compute_health_index(analytics_baseline)
#   idx_spiked, _ = compute_health_index(analytics_spiked)
#   assert idx_baseline - idx_spiked > 15
```

注意：贝叶斯收缩会缩小两者的差距。如果 baseline 和 spiked 的 own_reviews 都 >= 30，则无收缩，差距不变。如果 < 30，差距会缩小。需要检查测试的输入数据并调整阈值。

- [ ] **Step 11: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 521+ passed

- [ ] **Step 12: 提交**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_templates/email_full.html.j2 tests/test_report_common.py tests/test_v3_algorithms.py
git commit -m "fix(report): add Bayesian shrinkage to health index for small samples (Fix-3)"
```

---

### Task 5: Fix-4 — 激活 KPI Delta 计算

**目标**：在 `build_report_analytics()` 末尾调用已实现但从未使用的 `_compute_kpi_deltas()`，为增量模式的 KPI 卡片添加环比箭头。

**关键审查修正**：
- 第二个参数必须传完整 `prev_analytics` dict（不是 `prev_analytics["kpis"]`），因为函数内部会 `.get("kpis", {})`
- `run_id` 不是局部变量，用 `snapshot.get("run_id", 0)`
- 必须在函数体内懒导入 `load_previous_report_context` 避免循环导入

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (line ~1523, end of build_report_analytics)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_analytics.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for KPI delta activation (Fix-4)
# ---------------------------------------------------------------------------

import json
from pathlib import Path


def test_build_report_analytics_includes_kpi_deltas(analytics_db, tmp_path, monkeypatch):
    """In incremental mode, analytics should include KPI deltas from previous run."""
    from qbu_crawler.server import report_analytics

    # Create 3 completed prior runs to exit baseline mode
    for i, date in enumerate(["2026-04-01", "2026-04-02", "2026-04-03"]):
        analytics_path = str(tmp_path / f"analytics-{date}.json")
        prev_analytics = {
            "kpis": {
                "negative_review_rows": 10 + i,
                "own_negative_review_rows": 5 + i,
                "ingested_review_rows": 100 + i * 10,
                "product_count": 5,
                "health_index": 70.0 + i,
                "recently_published_count": 3,
            }
        }
        Path(analytics_path).write_text(
            json.dumps(prev_analytics, ensure_ascii=False),
            encoding="utf-8",
        )
        _create_daily_run(date, status="completed", analytics_path=analytics_path)

    # Current run snapshot
    current_run = _create_daily_run("2026-04-04", status="reporting")
    snapshot = _build_snapshot(current_run["id"], "2026-04-04")

    analytics = report_analytics.build_report_analytics(snapshot)

    # Should be incremental (3+ prior runs)
    assert analytics.get("mode") == "incremental" or analytics.get("mode_info", {}).get("mode") == "incremental"

    # Should have delta keys
    kpis = analytics["kpis"]
    assert "negative_review_rows_delta" in kpis, f"Missing delta keys. KPI keys: {list(kpis.keys())}"
    assert "negative_review_rows_delta_display" in kpis


def test_build_report_analytics_baseline_has_no_deltas(analytics_db, monkeypatch):
    """In baseline mode, KPI deltas should not be present."""
    from qbu_crawler.server import report_analytics

    current_run = _create_daily_run("2026-04-04", status="reporting")
    snapshot = _build_snapshot(current_run["id"], "2026-04-04")

    analytics = report_analytics.build_report_analytics(snapshot)

    kpis = analytics["kpis"]
    assert "negative_review_rows_delta" not in kpis
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py::test_build_report_analytics_includes_kpi_deltas -v`
Expected: FAIL — `assert "negative_review_rows_delta" in kpis`

- [ ] **Step 3: 在 build_report_analytics 末尾追加 KPI delta 计算**

在 `qbu_crawler/server/report_analytics.py` 的 `build_report_analytics()` 函数末尾（line ~1522，`return` 语句之前），找到函数的最后 return 语句。当前 return 在大约 line 1523，即：

```python
        **chart_data,
        "_trend_series": _trend_series,
    }
```

在这个 return 语句**之前**（即在构建 analytics dict 之后、return 之前）插入 delta 计算。将：

```python
        **chart_data,
        "_trend_series": _trend_series,
    }
```

替换为：

```python
        **chart_data,
        "_trend_series": _trend_series,
    }

    # ── KPI delta computation (Fix-4) ────────────────────────────────────
    if mode_info["mode"] != "baseline":
        from .report_snapshot import load_previous_report_context  # lazy import to avoid circular
        from .report_common import _compute_kpi_deltas

        _run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(_run_id)
        if prev_analytics:
            deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)
            analytics["kpis"].update(deltas)

    return analytics
```

**注意**：这意味着原来的 `return analytics` 是隐含在 dict 构造中的（Python 的 `analytics = { ... }` 后紧跟 `return analytics` 或者直接 `return { ... }`）。需要确认原代码的结构。

如果原代码是直接 `return { ... }`（没有先赋值给 `analytics` 变量），需要先将 return 改为赋值，再追加 delta 计算。根据读取到的代码，`build_report_analytics` 的 return 是直接返回一个 dict literal（line ~1467-1523），所以需要改为先赋值：

将函数末尾的 return dict 从：

```python
    return {
        "mode": mode_info["mode"],
        ...（中间所有内容保持不变）...
        **chart_data,
        "_trend_series": _trend_series,
    }
```

改为：

```python
    analytics = {
        "mode": mode_info["mode"],
        ...（中间所有内容保持不变）...
        **chart_data,
        "_trend_series": _trend_series,
    }

    # ── KPI delta computation (Fix-4) ────────────────────────────────────
    if mode_info["mode"] != "baseline":
        from .report_snapshot import load_previous_report_context  # lazy import to avoid circular
        from .report_common import _compute_kpi_deltas

        _run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(_run_id)
        if prev_analytics:
            deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)
            analytics["kpis"].update(deltas)

    return analytics
```

具体操作：找到函数末尾的 `return {` 并将 `return` 改为 `analytics =`，然后在闭括号 `}` 后追加 delta 代码块和 `return analytics`。

实际编辑：将文件中（约 line 1462 起的）：

```python
    return {
```

替换为：

```python
    analytics = {
```

然后将文件中（约 line 1523 的）：

```python
        "_trend_series": _trend_series,
    }
```

替换为：

```python
        "_trend_series": _trend_series,
    }

    # ── KPI delta computation (Fix-4) ────────────────────────────────────
    if mode_info["mode"] != "baseline":
        from .report_snapshot import load_previous_report_context  # lazy import to avoid circular
        from .report_common import _compute_kpi_deltas

        _run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(_run_id)
        if prev_analytics:
            deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)
            analytics["kpis"].update(deltas)

    return analytics
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py::test_build_report_analytics_includes_kpi_deltas tests/test_report_analytics.py::test_build_report_analytics_baseline_has_no_deltas -v`
Expected: 2 passed

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 523+ passed

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report): activate KPI delta computation for incremental reports (Fix-4)"
```

---

### Task 6: Fix-2 — 统一 LLM 分析的数据上下文

**目标**：`_select_insight_samples()` 不再查询全量数据库，改为仅从 `snapshot["reviews"]` 中选取样本，确保 LLM 看到的数据与 KPI 卡片一致。同时在评论极少时在 prompt 中添加样本不足提示。

**关键审查修正**：
- 参数顺序是 `(snapshot, analytics)` 不是 `(analytics, snapshot)`
- 实际是 3 次 DB 查询 + 2 次 snapshot 过滤，改后全部变为 snapshot 过滤

**Files:**
- Modify: `qbu_crawler/server/report_llm.py` (line 273-343, 470-485)
- Test: `tests/test_report_llm.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_llm.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for _select_insight_samples snapshot-only mode (Fix-2)
# ---------------------------------------------------------------------------


def test_select_insight_samples_uses_only_snapshot_data():
    """_select_insight_samples should select from snapshot reviews, not query DB."""
    from qbu_crawler.server.report_llm import _select_insight_samples

    snapshot = _snapshot()
    analytics = _analytics()

    samples = _select_insight_samples(snapshot, analytics)

    # All returned sample IDs must be from the snapshot reviews
    snapshot_ids = {r["id"] for r in snapshot["reviews"]}
    sample_ids = {s["id"] for s in samples}
    assert sample_ids.issubset(snapshot_ids), (
        f"Samples contain IDs not in snapshot: {sample_ids - snapshot_ids}"
    )


def test_select_insight_samples_no_reviews():
    """Empty snapshot reviews should return empty samples."""
    from qbu_crawler.server.report_llm import _select_insight_samples

    snapshot = {**_snapshot(), "reviews": []}
    analytics = _analytics()

    samples = _select_insight_samples(snapshot, analytics)
    assert samples == []


def test_select_insight_samples_includes_risk_product_negatives():
    """Should include negative reviews from risk products."""
    from qbu_crawler.server.report_llm import _select_insight_samples

    snapshot = _snapshot()
    analytics = _analytics()

    samples = _select_insight_samples(snapshot, analytics)

    # Review 101 is a 1-star own negative for risk product OWN-1
    sample_ids = {s["id"] for s in samples}
    assert 101 in sample_ids, "Should include negative review from risk product"


def test_select_insight_samples_includes_competitor_positives():
    """Should include competitor positive reviews."""
    from qbu_crawler.server.report_llm import _select_insight_samples

    snapshot = _snapshot()
    analytics = _analytics()

    samples = _select_insight_samples(snapshot, analytics)

    sample_ids = {s["id"] for s in samples}
    assert 201 in sample_ids, "Should include 5-star competitor review"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_llm.py::test_select_insight_samples_uses_only_snapshot_data -v`
Expected: FAIL — samples may contain IDs from DB but not in snapshot (the current implementation queries the DB for reviews 1-3, which may fail if DB is not set up, or pass if the test DB happens to match)

Note: If the test passes because the test fixture snapshot happens to overlap with DB results, we still need to verify the implementation change is correct. A more robust approach is to also check that `models.query_reviews` is NOT called:

Replace the first test with a monkeypatched version:

```python
def test_select_insight_samples_does_not_query_db(monkeypatch):
    """_select_insight_samples should NOT call models.query_reviews."""
    from qbu_crawler.server import report_llm
    from qbu_crawler import models

    call_count = 0
    original_query = models.query_reviews

    def _spy(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_query(*args, **kwargs)

    monkeypatch.setattr(models, "query_reviews", _spy)

    snapshot = _snapshot()
    analytics = _analytics()

    samples = report_llm._select_insight_samples(snapshot, analytics)

    assert call_count == 0, f"query_reviews was called {call_count} times, expected 0"
    # All returned sample IDs must be from the snapshot reviews
    snapshot_ids = {r["id"] for r in snapshot["reviews"]}
    sample_ids = {s["id"] for s in samples}
    assert sample_ids.issubset(snapshot_ids)
```

- [ ] **Step 3: 重写 `_select_insight_samples` 为 snapshot-only**

在 `qbu_crawler/server/report_llm.py` 中（line 273-343），将整个函数替换。

将：

```python
def _select_insight_samples(snapshot, analytics):
    """Select 15-20 diverse reviews for LLM synthesis from the full DB corpus.

    Strategy: worst per risk product, image-bearing negatives, top competitor,
    mixed sentiment, most recent.
    """
    risk_products = analytics.get("self", {}).get("risk_products", [])
    samples = []
    seen_ids = set()

    def _add(review_list, limit):
        added = 0
        for r in review_list:
            rid = r.get("id")
            if rid and rid not in seen_ids and len(samples) < 20:
                seen_ids.add(rid)
                samples.append(r)
                added += 1
                if added >= limit:
                    break

    # 1. Worst reviews per risk product (these are OWN products)
    for product in risk_products[:3]:
        sku = product.get("product_sku", "")
        if not sku:
            continue
        worst, _ = models.query_reviews(
            sku=sku, max_rating=config.NEGATIVE_THRESHOLD,
            sort_by="rating", order="asc", limit=5,
        )
        for r in worst:
            r.setdefault("ownership", "own")
        _add(worst, 2)

    # 2. Image-bearing own negatives — explicitly OWN
    img_neg, _ = models.query_reviews(
        ownership="own", has_images=True, max_rating=config.NEGATIVE_THRESHOLD,
        sort_by="rating", order="asc", limit=10,
    )
    for r in img_neg:
        r.setdefault("ownership", "own")
    _add([r for r in img_neg if r.get("id") not in seen_ids], 3)

    # 3. Top competitor reviews — explicitly COMPETITOR
    comp_best, _ = models.query_reviews(
        ownership="competitor", min_rating=5,
        sort_by="scraped_at", order="desc", limit=10,
    )
    for r in comp_best:
        r.setdefault("ownership", "competitor")
    _add([r for r in comp_best if r.get("id") not in seen_ids], 3)

    # 4. Mixed sentiment from snapshot (only if sentiment field available)
    mixed_count = 0
    for r in snapshot.get("reviews", []):
        if r.get("sentiment") == "mixed" and r.get("id") not in seen_ids and len(samples) < 20:
            seen_ids.add(r["id"])
            samples.append(r)
            mixed_count += 1
            if mixed_count >= 2:
                break

    # 5. Most recent from snapshot
    recent = sorted(
        [r for r in snapshot.get("reviews", []) if r.get("id") not in seen_ids],
        key=lambda r: r.get("date_published_parsed") or "",
        reverse=True,
    )
    _add(recent, 2)

    return samples[:20]
```

替换为：

```python
def _select_insight_samples(snapshot, analytics):
    """Select 15-20 diverse reviews for LLM synthesis from snapshot only.

    All samples come from snapshot["reviews"] to ensure consistency with KPI cards.
    Strategy: worst per risk product, image-bearing negatives, top competitor,
    mixed sentiment, most recent.
    """
    reviews = snapshot.get("reviews", [])
    if not reviews:
        return []

    risk_products = analytics.get("self", {}).get("risk_products", [])
    samples = []
    seen_ids = set()

    def _add(review_list, limit):
        added = 0
        for r in review_list:
            rid = r.get("id")
            if rid and rid not in seen_ids and len(samples) < 20:
                seen_ids.add(rid)
                samples.append(r)
                added += 1
                if added >= limit:
                    break

    # 1. Worst reviews per risk product (OWN products)
    risk_skus = [p.get("product_sku", "") for p in risk_products[:3] if p.get("product_sku")]
    for sku in risk_skus:
        sku_neg = sorted(
            [r for r in reviews
             if r.get("product_sku") == sku
             and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD],
            key=lambda r: r.get("rating") or 5,
        )
        _add(sku_neg, 2)

    # 2. Image-bearing own negatives
    img_neg = sorted(
        [r for r in reviews
         if r.get("ownership") == "own"
         and r.get("images")
         and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD],
        key=lambda r: r.get("rating") or 5,
    )
    _add(img_neg, 3)

    # 3. Top competitor reviews (5-star, most recent)
    comp_pos = sorted(
        [r for r in reviews
         if r.get("ownership") == "competitor"
         and (r.get("rating") or 0) >= 5],
        key=lambda r: r.get("scraped_at") or "",
        reverse=True,
    )
    _add(comp_pos, 3)

    # 4. Mixed sentiment
    mixed = [r for r in reviews if r.get("sentiment") == "mixed"]
    _add(mixed, 2)

    # 5. Most recent
    recent = sorted(
        reviews,
        key=lambda r: r.get("date_published_parsed") or "",
        reverse=True,
    )
    _add(recent, 2)

    return samples[:20]
```

- [ ] **Step 4: 在 prompt 中添加低样本量提示**

在 `_build_insights_prompt()` 函数中（约 line 484-487，`return prompt` 之前），将：

```python
            prompt += (
                f"\n\n关键评论原文（{len(lines)}条，用于提炼洞察和引用客户语言）：\n"
                + "\n".join(lines)
                + "\n\n补充要求：hero_headline 必须反映评论中的核心客户体验痛点，不要只堆砌数字。"
            )

    return prompt
```

替换为：

```python
            prompt += (
                f"\n\n关键评论原文（{len(lines)}条，用于提炼洞察和引用客户语言）：\n"
                + "\n".join(lines)
                + "\n\n补充要求：hero_headline 必须反映评论中的核心客户体验痛点，不要只堆砌数字。"
            )

    # Low sample warning — tell LLM to be conservative
    ingested = kpis.get("ingested_review_rows", 0)
    if ingested < 5:
        prompt += (
            f"\n\n重要：本期新增评论仅 {ingested} 条，样本极少。"
            "请仅基于上述数据做事实性记录，禁止做趋势推断或问题严重度判定。"
            "hero_headline 应体现'样本不足'。"
        )

    return prompt
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_report_llm.py::test_select_insight_samples_does_not_query_db tests/test_report_llm.py::test_select_insight_samples_no_reviews tests/test_report_llm.py::test_select_insight_samples_includes_risk_product_negatives tests/test_report_llm.py::test_select_insight_samples_includes_competitor_positives -v`
Expected: 4 passed

- [ ] **Step 6: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 527+ passed

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "fix(report): restrict LLM insight samples to snapshot data only (Fix-2)"
```

---

### Task 7: Fix-1 — 激活 Change/Quiet 报告模式

**目标**：移除 workflows.py 中 reviews_count==0 时的 early return，让 `generate_report_from_snapshot()` 正确路由到 change/quiet 模式。同时修复 `_should_send_workflow_email()` 始终返回 True（让下游决定是否发邮件）、DingTalk 通知模板处理 excel_path=None、change/quiet 返回值补充 snapshot_hash。

**这是最复杂的 Fix，依赖 Fix-7 已完成（收件人统一）。**

**Files:**
- Modify: `qbu_crawler/server/workflows.py` (line 632-659, 823-829)
- Modify: `qbu_crawler/server/notifier.py` (line 104-128)
- Modify: `qbu_crawler/server/report_snapshot.py` (change/quiet return dicts)
- Test: `tests/test_report_snapshot.py`

#### Sub-step A: 修复 change/quiet 返回值缺少 snapshot_hash

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for change/quiet report snapshot_hash (Fix-1C)
# ---------------------------------------------------------------------------


def test_generate_change_report_includes_snapshot_hash():
    """_generate_change_report return dict should include snapshot_hash."""
    from qbu_crawler.server.report_snapshot import _generate_change_report

    snapshot = {
        "run_id": 99,
        "snapshot_hash": "abc123",
        "products_count": 5,
        "reviews_count": 0,
        "logical_date": "2026-04-15",
        "products": [],
        "reviews": [],
    }
    prev_analytics = {"kpis": {"health_index": 70.0}}
    context = {"changes": {"has_changes": True, "price_changes": [{"sku": "A", "old": 10, "new": 12}]}}

    result = _generate_change_report(snapshot, send_email=False, prev_analytics=prev_analytics, context=context)
    assert result.get("snapshot_hash") == "abc123"


def test_generate_quiet_report_includes_snapshot_hash(monkeypatch):
    """_generate_quiet_report return dict should include snapshot_hash."""
    from qbu_crawler.server import report_snapshot

    # Mock should_send_quiet_email to avoid DB dependency
    monkeypatch.setattr(
        report_snapshot, "should_send_quiet_email",
        lambda run_id: (False, "skip", 0),
    )

    snapshot = {
        "run_id": 99,
        "snapshot_hash": "def456",
        "products_count": 5,
        "reviews_count": 0,
        "logical_date": "2026-04-15",
        "products": [],
        "reviews": [],
    }
    prev_analytics = {"kpis": {"health_index": 70.0}}

    result = report_snapshot._generate_quiet_report(snapshot, send_email=False, prev_analytics=prev_analytics)
    assert result.get("snapshot_hash") == "def456"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_snapshot.py::test_generate_change_report_includes_snapshot_hash -v`
Expected: FAIL — `assert result.get("snapshot_hash") == "abc123"` (key not present in return dict)

- [ ] **Step 3: 在 _generate_change_report 返回值中添加 snapshot_hash**

在 `qbu_crawler/server/report_snapshot.py` 的 `_generate_change_report()` 函数中（约 line 523-533），将：

```python
    return {
        "mode": "change",
        "status": "completed",
        "run_id": run_id,
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": None,
        "email": email_result,
    }
```

替换为：

```python
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

- [ ] **Step 4: 在 _generate_quiet_report 返回值中添加 snapshot_hash**

在 `qbu_crawler/server/report_snapshot.py` 的 `_generate_quiet_report()` 函数中（约 line 562-574），将：

```python
    return {
        "mode": "quiet",
        "status": "completed_no_change",
        "run_id": run_id,
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

替换为：

```python
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

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_report_snapshot.py::test_generate_change_report_includes_snapshot_hash tests/test_report_snapshot.py::test_generate_quiet_report_includes_snapshot_hash -v`
Expected: 2 passed

#### Sub-step B: 修改 _should_send_workflow_email 始终返回 True

- [ ] **Step 6: 写失败测试**

在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for _should_send_workflow_email (Fix-1A)
# ---------------------------------------------------------------------------


def test_should_send_workflow_email_returns_true_for_zero_reviews():
    """_should_send_workflow_email should return True even with 0 reviews.

    The downstream generate_report_from_snapshot decides whether to actually send.
    """
    from qbu_crawler.server.workflows import _should_send_workflow_email

    task_rows = [{"result": {"reviews_saved": 0}}]
    snapshot = {"reviews_count": 0}
    assert _should_send_workflow_email(task_rows, snapshot) is True


def test_should_send_workflow_email_returns_true_for_positive_reviews():
    """_should_send_workflow_email should also return True with reviews."""
    from qbu_crawler.server.workflows import _should_send_workflow_email

    task_rows = [{"result": {"reviews_saved": 10}}]
    snapshot = {"reviews_count": 10}
    assert _should_send_workflow_email(task_rows, snapshot) is True
```

- [ ] **Step 7: 运行测试确认失败**

Run: `uv run pytest tests/test_report_snapshot.py::test_should_send_workflow_email_returns_true_for_zero_reviews -v`
Expected: FAIL — `assert ... is True` (currently returns False when reviews_saved == 0)

- [ ] **Step 8: 修改 _should_send_workflow_email**

在 `qbu_crawler/server/workflows.py` 中（line 823-829），将：

```python
def _should_send_workflow_email(task_rows: list[dict], snapshot: dict) -> bool:
    reviews_saved = _workflow_reviews_saved(task_rows)
    if reviews_saved is not None:
        return reviews_saved > 0
    if snapshot.get("reviews_count") is None:
        return True
    return int(snapshot.get("reviews_count") or 0) > 0
```

替换为：

```python
def _should_send_workflow_email(task_rows: list[dict], snapshot: dict) -> bool:
    """Always return True — let generate_report_from_snapshot decide per mode.

    Full mode: sends daily deep report email.
    Change mode: sends price/stock change notification.
    Quiet mode: has its own frequency control (should_send_quiet_email).
    """
    return True
```

- [ ] **Step 9: 运行测试确认通过**

Run: `uv run pytest tests/test_report_snapshot.py::test_should_send_workflow_email_returns_true_for_zero_reviews tests/test_report_snapshot.py::test_should_send_workflow_email_returns_true_for_positive_reviews -v`
Expected: 2 passed

#### Sub-step C: 修改 DingTalk 通知模板处理 excel_path=None

- [ ] **Step 10: 写失败测试**

在 `tests/test_notifier.py` 中（如果存在），或在 `tests/test_report_snapshot.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Tests for notifier template vars with None excel_path (Fix-1B)
# ---------------------------------------------------------------------------


def test_notifier_template_vars_handles_none_excel_path():
    """When report_mode is change/quiet, excel_path=None should not render as 'None'."""
    from qbu_crawler.server.notifier import OpenClawNotificationSender

    sender = OpenClawNotificationSender.__new__(OpenClawNotificationSender)
    notification = {
        "kind": "workflow_full_report",
        "payload": {
            "run_id": 1,
            "logical_date": "2026-04-15",
            "excel_path": None,
            "analytics_path": None,
            "report_mode": "change",
        },
    }
    result = sender._template_vars_for(notification)
    # The excel_path value should NOT be the string "None"
    excel_val = result.get("excel_path", "")
    assert excel_val != "None", f"excel_path should not be the string 'None', got: {excel_val!r}"
```

- [ ] **Step 11: 运行测试确认失败**

Run: `uv run pytest tests/test_report_snapshot.py::test_notifier_template_vars_handles_none_excel_path -v`
Expected: FAIL — current `_template_vars_for` returns `dict(payload)` for `workflow_full_report`, so `excel_path=None` is passed through to template which renders as "None"

- [ ] **Step 12: 修改 notifier.py _template_vars_for**

在 `qbu_crawler/server/notifier.py` 的 `_template_vars_for()` 方法中（line 104-128），将：

```python
        return dict(payload)
```

替换为：

```python
        # Sanitize None values for template rendering (Fix-1B)
        # change/quiet modes have excel_path=None which renders as "None" in DingTalk
        vars = dict(payload)
        if vars.get("report_mode") in ("change", "quiet"):
            for key in ("excel_path", "analytics_path", "pdf_path"):
                if vars.get(key) is None:
                    vars[key] = ""
        return vars
```

- [ ] **Step 13: 运行测试确认通过**

Run: `uv run pytest tests/test_report_snapshot.py::test_notifier_template_vars_handles_none_excel_path -v`
Expected: 1 passed

#### Sub-step D: 移除 workflows.py 中 reviews_count==0 的 early return

- [ ] **Step 14: 修改 _advance_run 中的 early return 逻辑**

在 `qbu_crawler/server/workflows.py` 中（line 632-661），将：

```python
        if run.get("report_phase") == "none":
            snapshot = load_report_snapshot(run["snapshot_path"])
            if snapshot.get("reviews_count", 0) == 0:
                # No new reviews — skip fast/full report entirely.
                # Only send a single "report skipped" notification.
                _clear_translation_progress(run_id)
                _enqueue_workflow_notification(
                    kind="workflow_report_skipped",
                    target=config.WORKFLOW_NOTIFICATION_TARGET,
                    payload={
                        "run_id": run_id,
                        "logical_date": run["logical_date"],
                        "snapshot_hash": run.get("snapshot_hash", ""),
                        "products_count": snapshot.get("products_count", 0),
                        "reviews_count": 0,
                        "reason": "no_new_reviews",
                    },
                    dedupe_key=f"workflow:{run_id}:report-skipped",
                )
                models.update_workflow_run(
                    run_id,
                    status="completed",
                    report_phase="skipped_no_reviews",
                    report_mode="skipped",
                    finished_at=now,
                    error=None,
                )
                return True
            run = models.update_workflow_run(run_id, report_phase="fast_pending")
            changed = True
```

替换为：

```python
        if run.get("report_phase") == "none":
            snapshot = load_report_snapshot(run["snapshot_path"])
            if snapshot.get("reviews_count", 0) == 0:
                # No new reviews — skip fast report (meaningless without reviews),
                # jump directly to full_pending where generate_report_from_snapshot
                # will route to change or quiet mode.
                _clear_translation_progress(run_id)
                run = models.update_workflow_run(run_id, report_phase="full_pending")
            else:
                run = models.update_workflow_run(run_id, report_phase="fast_pending")
            changed = True
```

- [ ] **Step 15: 运行全量测试确认无回归**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 535+ passed (all prior tests + new ones from this task)

注意：如果有现有测试依赖 `report_mode="skipped"` 或 `report_phase="skipped_no_reviews"` 的行为，需要同步更新。全量测试会暴露这些。

- [ ] **Step 16: 提交**

```bash
git add qbu_crawler/server/workflows.py qbu_crawler/server/notifier.py qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "fix(report): activate change/quiet report modes by removing early return (Fix-1)"
```

---

## 最终验证

- [ ] **运行全量测试套件**

```bash
uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py
```

Expected: 535+ passed, 0 failed

- [ ] **检查所有 Fix 是否已提交**

```bash
git log --oneline -7
```

Expected 输出（最新在上）：
```
xxxxxxx fix(report): activate change/quiet report modes by removing early return (Fix-1)
xxxxxxx fix(report): restrict LLM insight samples to snapshot data only (Fix-2)
xxxxxxx feat(report): activate KPI delta computation for incremental reports (Fix-4)
xxxxxxx fix(report): add Bayesian shrinkage to health index for small samples (Fix-3)
xxxxxxx fix(report): protect competitive gap index against low sample sizes (Fix-6)
xxxxxxx fix(report): relax baseline exit condition to count quiet/skipped runs (Fix-5)
xxxxxxx fix(report): unify email recipient source across all report modes (Fix-7)
```
