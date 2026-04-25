# Phase 2 T9 · trend_digest 数据层扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 1 已稳定的 `trend_digest.data[view][dim]` 块基础上，**只动数据层**（`report_analytics.py` 聚合 + `report_charts.py` Chart.js 配置生成）补齐两个新字段：每块至少 2 条 `secondary_charts`、每块固定 3 段 `comparison`（period_over_period / year_over_year / start_vs_end），并把 accumulating 状态下被砍到 0 条的 `kpis.items` 统一回填到 4 条占位（保持 ready/accumulating 同 schema）。**坚决不动 HTML 模板 / Excel / 邮件 / LLM prompt** — 那是 T10/T11 的范畴。

**Architecture:**
- **新字段全部下沉到 `data[view][dim]` 子层**：`secondary_charts: list[dict]` 与 `comparison: dict` 加在 Phase 1 已有的 `{kpis, primary_chart, status, status_message, table}` 旁边，**不新增任何 trend_digest 顶层键**（契约冻结期硬约束）。schema 永远存在（即便 accumulating），只是 series/labels 在样本不足时为空。
- **secondary_charts 每块至少 2 条，shape 与 primary_chart 同构**：`{status, chart_type, title, labels, series}`。每条都带独立 `status`，符合 spec §8.5「竞品维度允许混合状态」的要求；模板 / 前端 future code 用同一套 chart_ready 判断即可消费。
- **comparison 三段 shape 永远固定，值缺失时 null**：`period_over_period / year_over_year / start_vs_end` 三个 key 永远存在；当窗口数据不足以算出 previous / start / end 时填 `null`，change_pct 同步置 null。这样模板和 LLM 的 future contract 是稳定的，数据填充随历史增长而完善（与"基线后失明"修复同思路：契约稳定优先，数据样本演进）。
- **每个 \_build\_\*\_trend 内部抽出 \_build\_secondary\_charts\_\* 与 \_build\_comparison\_\* 两个 helper**：`_build_sentiment_trend` 等主函数仅负责调度，secondary_charts / comparison 各有独立 helper，便于单独测试，也避免主函数复杂度膨胀。
- **Chart.js 配置兼容已有命名**：`build_chartjs_configs` 现已生成 `trend_{view}_{dim}` 一类 key 给主图；T9 加一组 `trend_{view}_{dim}_secondary_{idx}`（idx 从 0 起），仅对 `secondary_charts[idx].status == "ready"` 的图生成。其余键名、生成顺序 0 改动，保证 Phase 1 模板调用方 `charts[chart_key]` 仍命中老主图。
- **accumulating 状态 KPI 占位**：`_empty_trend_dimension` 拿到一份 `default_kpi_labels: list[str]`（4 个 dimension-specific 标签），自动产出 4 个 `{label, value: "—"}` 占位。`_build_*_trend` 内每个 accumulating 早返回路径都改用此 helper，`kpis.items` 长度始终 = 4（不是 0）。

**Tech Stack:** Python 3.10+, pytest, Chart.js (config dict only — 无 JS/HTML 改动)

**Spec:**
- `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md` §14 Phase 2 验收标准
- `docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md` Chunk 3 Task 9（原始 7 步骨架，本 plan 在其上做 TDD bite-sized 细化）

**Source findings:**
- `docs/reviews/2026-04-24-report-upgrade-phase2-audit.md` §6.1（T9 落地建议：4 KPI / secondary_charts / comparison）+ §4.1（accumulating 维度 4 个占位 KPI）
- `docs/reviews/2026-04-24-report-upgrade-execution-plan.md` 第 6 段（T9 entry/scope/exit + 禁动模板/Excel/邮件）
- `docs/reviews/2026-04-24-report-upgrade-continuity.md` §🧊 Phase 2 进行中禁改清单（不得引入 `kpis_v2` / `metric_new_*`，模板不得绕过 trend_digest 直接读 analytics.window）

**Entry assumption:**
- `HEAD = d7a538e`（Stage B 完成 · `v0.3.19-stage-b` 已打 tag）
- 契约冻结期 Day 5 已通过（连续 3 个 daily run 健康指数三处口径一致 / 月-产品有 KPI / bullet 不出现领跑 / `今日新增` 0 命中）
- `secondary_charts / secondary_chart` / `comparison`（作为 trend_digest 字段）当前 0 命中，全仓 grep 锁住
- Stage B 与 T9 文件不重叠：T9 不动 `report_snapshot.py / workflows.py / report_common.py / report_llm.py / report_templates/*`，**仅** 改 `report_analytics.py` + `report_charts.py` + 上述两个文件对应的 4 个测试

---

## File Map

| File | Responsibility | Tasks |
|------|----------------|-------|
| `qbu_crawler/server/report_analytics.py` | `_trend_dimension_payload` / `_empty_trend_dimension` 接收新字段；4 个 `_build_*_trend` 主函数加 secondary_charts + comparison；新增 4 组 `_build_secondary_charts_*` + `_build_comparison_*` helper | T1, T2, T3, T4, T5, T6 |
| `qbu_crawler/server/report_charts.py` | `build_chartjs_configs` 末段消费 `trend_digest.data[view][dim].secondary_charts` 生成 `trend_{view}_{dim}_secondary_{idx}` 配置 | T7 |
| `tests/test_report_analytics.py` | schema 锁（四块同 schema）+ KPI 4 项占位 + 4 组 secondary_charts 内容 + 4 组 comparison 内容 + 时间口径回归 | T1, T2, T3, T4, T5, T6, T8 |
| `tests/test_report_charts.py`（新建或追加） | secondary chart Chart.js 配置生成回归 | T7 |
| `tests/test_metric_semantics.py` | grep 门禁：禁止 `kpis_v2` / `metric_new_*` / `secondary_chart` 单数误用 / `secondary_charts` 字段在模板 / Excel 中出现（T9 阶段必须 0） | T8 |
| `pyproject.toml` / `qbu_crawler/__init__.py` / `uv.lock` | 版本号 bump 0.3.19 → 0.3.20 | T9 |
| `docs/reviews/2026-04-24-report-upgrade-continuity.md` | next_action / status pointer 更新到 T9 完成 / T10 准备 | T9 |

---

## Task 1: 锁定 schema · 给 \_trend\_dimension\_payload 与 \_empty\_trend\_dimension 增加 secondary\_charts / comparison 占位

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1402-1429` (`_trend_dimension_payload` + `_empty_trend_dimension`)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1.1: 写失败测试 — 12 块 schema 一致**

加到 `tests/test_report_analytics.py` 末尾（紧跟 `test_build_trend_digest_emits_year_view_note`）：

```python
def test_trend_digest_blocks_all_have_phase2_schema():
    """Phase 2 T9: 每块 (view × dim) 必须同时具备 Phase 1 5 键 + Phase 2 2 键，
    无论 status 是 ready / accumulating / degraded。
    schema 永远齐全，缺数据时 series 为空、comparison 三段为 null。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest

    snapshot = {
        "logical_date": "2026-04-25",
        "products": [],
        "reviews": [],
    }
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    expected_keys = {
        "status", "status_message", "kpis", "primary_chart",
        "secondary_charts", "comparison", "table",
    }
    for view in digest["views"]:
        for dim in digest["dimensions"]:
            block = digest["data"][view][dim]
            missing = expected_keys - set(block.keys())
            assert not missing, f"{view}/{dim} missing keys: {missing}"
            assert isinstance(block["secondary_charts"], list), \
                f"{view}/{dim} secondary_charts must be list, got {type(block['secondary_charts'])}"
            assert isinstance(block["comparison"], dict), \
                f"{view}/{dim} comparison must be dict, got {type(block['comparison'])}"
            # comparison 三段固定 key
            assert set(block["comparison"].keys()) == {
                "period_over_period", "year_over_year", "start_vs_end",
            }, f"{view}/{dim} comparison keys mismatch: {block['comparison'].keys()}"
```

- [ ] **Step 1.2: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py::test_trend_digest_blocks_all_have_phase2_schema -v`
Expected: FAIL（KeyError on `secondary_charts` 或 `comparison`，因为 `_empty_trend_dimension` 与 `_trend_dimension_payload` 还没产出这两个键）

- [ ] **Step 1.3: 修改 `_trend_dimension_payload` 与 `_empty_trend_dimension`**

替换 `qbu_crawler/server/report_analytics.py:1402-1429`：

```python
def _empty_comparison():
    """Phase 2 T9: comparison 永远是稳定 3 段 shape，
    数据不足时 current/previous/start/end 为 None，change_pct 同步 None。"""
    return {
        "period_over_period": {
            "label": "",
            "current": None,
            "previous": None,
            "change_pct": None,
        },
        "year_over_year": {
            "label": "",
            "current": None,
            "previous": None,
            "change_pct": None,
        },
        "start_vs_end": {
            "label": "",
            "start": None,
            "end": None,
            "change_pct": None,
        },
    }


def _trend_dimension_payload(
    *,
    status,
    message,
    kpis,
    primary_chart,
    table,
    secondary_charts=None,
    comparison=None,
):
    return {
        "status": status,
        "status_message": message,
        "kpis": kpis,
        "primary_chart": primary_chart,
        # Phase 2 T9: schema 永远齐全；ready 状态由各 _build_*_trend 主函数填充
        "secondary_charts": list(secondary_charts) if secondary_charts else [],
        "comparison": comparison if comparison is not None else _empty_comparison(),
        "table": table,
    }


def _empty_trend_dimension(status, message, chart_title, table_columns,
                            kpi_placeholder_labels=None):
    """Phase 2 T9: accumulating / degraded 状态也必须给出 4 个 KPI 占位项（label 固定，
    value 显示 "—"），不再返回空 items 列表。"""
    placeholder_labels = list(kpi_placeholder_labels or ["—", "—", "—", "—"])
    # 兜底：长度不足 4 时用 "—" 补齐
    while len(placeholder_labels) < 4:
        placeholder_labels.append("—")
    placeholder_items = [
        {"label": label, "value": "—"} for label in placeholder_labels[:4]
    ]
    return _trend_dimension_payload(
        status=status,
        message=message,
        kpis={"status": status, "items": placeholder_items},
        primary_chart={
            "status": status,
            "chart_type": "line",
            "title": chart_title,
            "labels": [],
            "series": [],
        },
        table={
            "status": status,
            "columns": table_columns,
            "rows": [],
        },
        secondary_charts=[],
        comparison=_empty_comparison(),
    )
```

注意：所有调用 `_empty_trend_dimension(...)` 的地方都还没传 `kpi_placeholder_labels`，所以默认 4 个 "—" 占位。Task 2 会逐个改成 dimension-specific 标签。

- [ ] **Step 1.4: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py::test_trend_digest_blocks_all_have_phase2_schema -v`
Expected: PASS

- [ ] **Step 1.5: 跑既有 trend 相关测试，确保未破坏 Phase 1 契约**

Run: `uv run pytest tests/test_report_analytics.py -v -k "trend"`
Expected: ALL PASS（既有 `test_build_dual_trend_digest_has_mixed_ready_and_accumulating_states` / `test_sentiment_trend_bucket_health_is_bayesian_shrunk` / `test_competition_trend_mixed_state_keeps_ready_table_when_chart_accumulating` / `test_build_trend_digest_emits_year_view_note` 四条都不应受影响）

- [ ] **Step 1.6: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report_analytics): trend_digest 块加 secondary_charts/comparison 占位 (T9 step 1)"
```

---

## Task 2: KPI 占位齐 4 项 · 修 audit §4.1（week/sentiment, week/issues, week/competition, month/competition）

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1474-1481, 1554-1561, 1572-1579, 1658-1683, 1753-1760`（5 个 accumulating 早返回路径）
- Test: `tests/test_report_analytics.py`

**Why:** phase2-audit §4.1 已点名 4 个组合（week/sentiment, week/issues, week/competition, month/competition）`kpis.items=[]`。T9 入口前必须先把 accumulating 路径下的 KPI 占位补齐，不然 secondary_charts 加完仍然违反"功能不砍"。

- [ ] **Step 2.1: 写失败测试 — KPI 永远 4 项**

加到 `tests/test_report_analytics.py`：

```python
def test_trend_digest_blocks_always_have_four_kpi_items():
    """Phase 2 T9 + audit §4.1: 任何 view × dim 组合的 kpis.items 必须恰好 4 条，
    accumulating 状态用 "—" 占位（保留指标骨架，避免前端空白卡片）。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest

    # 空 snapshot → 12 块全部 accumulating（除非有快照）
    snapshot = {"logical_date": "2026-04-25", "products": [], "reviews": []}
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    for view in digest["views"]:
        for dim in digest["dimensions"]:
            block = digest["data"][view][dim]
            items = (block.get("kpis") or {}).get("items") or []
            assert len(items) == 4, \
                f"{view}/{dim} kpis.items must have 4 entries, got {len(items)}"
            # 占位时 label 与 value 不能都是空字符串
            for it in items:
                assert it.get("label"), \
                    f"{view}/{dim} kpis.items[*].label must be non-empty"
```

- [ ] **Step 2.2: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py::test_trend_digest_blocks_always_have_four_kpi_items -v`
Expected: FAIL（部分 accumulating 块的 `items=[]`）

- [ ] **Step 2.3: 改 sentiment 早返回路径**

替换 `qbu_crawler/server/report_analytics.py:1475-1481`（`_build_sentiment_trend` 中 `if not ready` 块）：

```python
    if not ready:
        return _empty_trend_dimension(
            "accumulating",
            "评论发布时间样本仍在积累，当前不足以形成稳定趋势。",
            "舆情趋势",
            ["日期", "评论量", "自有差评", "自有差评率", "健康分"],
            kpi_placeholder_labels=["窗口评论量", "自有差评数", "自有差评率", "健康分"],
        )
```

- [ ] **Step 2.4: 改 issues 两处早返回**

替换 `qbu_crawler/server/report_analytics.py:1555-1561` 与 `1573-1579`：

```python
    if not counts_by_label:
        return _empty_trend_dimension(
            "accumulating",
            "问题标签样本仍在积累，当前不足以形成稳定趋势。",
            "问题趋势",
            ["问题", "评论数", "影响产品数"],
            kpi_placeholder_labels=["问题信号数", "活跃问题数", "头号问题", "涉及产品数"],
        )
```

```python
    if not ready:
        return _empty_trend_dimension(
            "accumulating",
            "问题标签时间分布仍在积累，当前不足以形成年度趋势。",
            "问题趋势",
            ["问题", "评论数", "影响产品数"],
            kpi_placeholder_labels=["问题信号数", "活跃问题数", "头号问题", "涉及产品数"],
        )
```

- [ ] **Step 2.5: 改 products 早返回（已有 4 条 KPI 但用的是 `_trend_dimension_payload` 直填，确认即可）**

`_build_product_trend` 在 `1658-1683` 已经显式给了 4 个 KPI（"跟踪产品数 / 有快照产品数 / 可成图产品数 / 快照点数"），无需改。但要把外层调用改用新签名 — 由于已经走的是 `_trend_dimension_payload` 不是 `_empty_trend_dimension`，schema 默认不影响。**跳过此步**，但要在测试中确认 12 块的 products dim 也满足 4 KPI。

- [ ] **Step 2.6: 改 competition 早返回**

替换 `qbu_crawler/server/report_analytics.py:1755-1760`：

```python
    if not any_side_has_data:
        # Neither side has data → integral accumulating is correct.
        return _empty_trend_dimension(
            "accumulating",
            "自有与竞品的可比样本仍在积累，当前不足以形成稳定趋势。",
            "竞品趋势",
            ["日期", "自有均分", "竞品均分", "自有差评率", "竞品好评率"],
            kpi_placeholder_labels=["可比时间点", "最新评分差", "最新自有差评率", "最新竞品好评率"],
        )
```

- [ ] **Step 2.7: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py::test_trend_digest_blocks_always_have_four_kpi_items -v`
Expected: PASS

- [ ] **Step 2.8: 跑 trend 全量回归**

Run: `uv run pytest tests/test_report_analytics.py -v -k "trend"`
Expected: ALL PASS

- [ ] **Step 2.9: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "fix(report_analytics): accumulating 状态 KPI 永远 4 占位 (T9 step 2 / audit §4.1)"
```

---

## Task 3: sentiment 维度 · secondary\_charts (差评率 + 健康分) + comparison (start\_vs\_end 差评率)

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1432-1530`（`_build_sentiment_trend` 主函数）
- Add: `qbu_crawler/server/report_analytics.py`（新增 `_build_sentiment_secondary_charts` + `_build_sentiment_comparison`）
- Test: `tests/test_report_analytics.py`

- [ ] **Step 3.1: 写失败测试 — secondary\_charts 内容**

```python
def test_sentiment_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: sentiment dim 在 ready 时必须输出 2 张辅图：
    1) 自有差评率趋势 (line)
    2) 健康分趋势 (line)
    每张图都带独立 status，labels 与主图同 buckets，series 至少 1 条。"""
    from qbu_crawler.server.report_analytics import _build_sentiment_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-10"}},
        {"review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-04-11"}},
        {"review": {"ownership": "own", "rating": 2, "date_published_parsed": "2026-04-12"}},
    ]
    result = _build_sentiment_trend("month", logical_day, labeled_reviews)

    assert result["status"] == "ready"
    secondary = result["secondary_charts"]
    assert isinstance(secondary, list) and len(secondary) >= 2, \
        f"expected >=2 secondary charts, got {len(secondary)}"

    titles = {chart["title"] for chart in secondary}
    assert any("差评率" in t for t in titles), f"missing 差评率 chart: {titles}"
    assert any("健康" in t for t in titles), f"missing 健康分 chart: {titles}"

    for chart in secondary:
        assert set(chart.keys()) >= {"status", "chart_type", "title", "labels", "series"}
        assert chart["status"] in {"ready", "accumulating", "degraded"}
        if chart["status"] == "ready":
            assert chart["labels"], "ready chart must have non-empty labels"
            assert chart["series"], "ready chart must have non-empty series"
```

- [ ] **Step 3.2: 写失败测试 — comparison 内容**

```python
def test_sentiment_trend_emits_comparison_with_start_vs_end():
    """Phase 2 T9: sentiment dim ready 时 comparison.start_vs_end 必须有
    start / end / change_pct 三个非 null 值（差评率，单位 %）；
    period_over_period / year_over_year 在数据不足时填 null 但 key 必须存在。"""
    from qbu_crawler.server.report_analytics import _build_sentiment_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    # 构造首尾两个 bucket 都有数据的场景
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-03-26"}},  # 月初
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-22"}},  # 月末
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-23"}},
    ]
    result = _build_sentiment_trend("month", logical_day, labeled_reviews)
    comp = result["comparison"]

    # shape 永远齐全
    assert set(comp.keys()) == {"period_over_period", "year_over_year", "start_vs_end"}

    # start_vs_end 在有首尾数据时必须可计算
    sve = comp["start_vs_end"]
    assert sve["start"] is not None, "start_vs_end.start should be computable"
    assert sve["end"] is not None, "start_vs_end.end should be computable"
    # 月初 1/2 = 50% 差评率，月末 0/2 = 0% → end < start
    assert sve["end"] < sve["start"], f"end={sve['end']} should be < start={sve['start']}"
```

- [ ] **Step 3.3: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py -v -k "sentiment_trend_emits"`
Expected: FAIL（secondary_charts 为空 / comparison 全 null）

- [ ] **Step 3.4: 新增 helper · sentiment 辅图**

在 `qbu_crawler/server/report_analytics.py` 中 `_build_sentiment_trend` 函数下方加：

```python
def _build_sentiment_secondary_charts(labels, own_negative_rates, health_scores):
    """Phase 2 T9: sentiment dim 辅图 — 差评率与健康分独立走势。
    各自带 status：当 series 全 None / 全 0 / 全空时降级到 accumulating。"""
    def _ready(values):
        return any(v is not None for v in values)

    own_neg_status = "ready" if _ready(own_negative_rates) else "accumulating"
    health_status = "ready" if _ready(health_scores) else "accumulating"

    return [
        {
            "status": own_neg_status,
            "chart_type": "line",
            "title": "自有差评率趋势",
            "labels": labels if own_neg_status == "ready" else [],
            "series": [
                {"name": "自有差评率(%)", "data": own_negative_rates},
            ] if own_neg_status == "ready" else [],
        },
        {
            "status": health_status,
            "chart_type": "line",
            "title": "健康分趋势",
            "labels": labels if health_status == "ready" else [],
            "series": [
                {"name": "健康分", "data": health_scores},
            ] if health_status == "ready" else [],
        },
    ]


def _build_sentiment_comparison(labels, own_negative_rates):
    """Phase 2 T9: sentiment dim comparison — 度量统一为「自有差评率」。
    start_vs_end: 第一个非 null bucket vs 最后一个非 null bucket
    period_over_period / year_over_year: 当前实现填 null（待 Phase 2 后续历史扩展）"""
    pairs = [
        (label, value)
        for label, value in zip(labels, own_negative_rates)
        if value is not None
    ]
    start_value = pairs[0][1] if pairs else None
    end_value = pairs[-1][1] if pairs else None
    change_pct = None
    if (
        start_value is not None
        and end_value is not None
        and start_value != 0
    ):
        change_pct = round((end_value - start_value) / start_value * 100, 1)

    comparison = _empty_comparison()
    comparison["start_vs_end"]["label"] = "首尾差评率对比"
    comparison["start_vs_end"]["start"] = start_value
    comparison["start_vs_end"]["end"] = end_value
    comparison["start_vs_end"]["change_pct"] = change_pct
    return comparison
```

- [ ] **Step 3.5: 改主函数拼装**

替换 `_build_sentiment_trend` 函数末尾 `return _trend_dimension_payload(...)` 块（约 1501-1529 行），把 `_trend_dimension_payload(...)` 调用从：

```python
    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={...},
        primary_chart={...},
        table={...},
    )
```

改为：

```python
    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={
            "status": "ready",
            "items": [
                {"label": "窗口评论量", "value": sum(review_counts)},
                {"label": "自有差评数", "value": total_own_negative},
                {"label": "自有差评率", "value": f"{total_own_negative_rate:.1f}%"},
                {"label": "有效时间点", "value": non_zero_points},
            ],
        },
        primary_chart={
            "status": "ready",
            "chart_type": "line",
            "title": "舆情趋势",
            "labels": labels,
            "series": [
                {"name": "评论量", "data": review_counts},
                {"name": "自有差评数", "data": own_negative_counts},
                {"name": "健康分", "data": health_scores},
            ],
        },
        secondary_charts=_build_sentiment_secondary_charts(
            labels, own_negative_rates, health_scores,
        ),
        comparison=_build_sentiment_comparison(labels, own_negative_rates),
        table={
            "status": "ready",
            "columns": ["日期", "评论量", "自有差评", "自有差评率", "健康分"],
            "rows": rows,
        },
    )
```

- [ ] **Step 3.6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py -v -k "sentiment_trend_emits"`
Expected: PASS

- [ ] **Step 3.7: 跑 sentiment 既有测试**

Run: `uv run pytest tests/test_report_analytics.py -v -k "sentiment"`
Expected: ALL PASS（含贝叶斯收缩既有测试）

- [ ] **Step 3.8: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report_analytics): sentiment 维度 secondary_charts + comparison (T9 step 3)"
```

---

## Task 4: issues 维度 · secondary\_charts (Top 3 问题热度堆叠 + 影响 SKU 数) + comparison (start\_vs\_end 头号问题热度)

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1532-1623`（`_build_issue_trend` 主函数）
- Add: `qbu_crawler/server/report_analytics.py`（新增 `_build_issue_secondary_charts` + `_build_issue_comparison`）
- Test: `tests/test_report_analytics.py`

- [ ] **Step 4.1: 写失败测试 — secondary\_charts 内容**

```python
def test_issue_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: issues dim ready 时必须输出 2 张辅图：
    1) Top 3 问题分时段堆叠 (stacked_bar)
    2) Top 3 问题影响 SKU 数 (bar)"""
    from qbu_crawler.server.report_analytics import _build_issue_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        {
            "review": {"ownership": "own", "rating": 1, "product_sku": "A1",
                       "date_published_parsed": "2026-04-10"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "rating": 1, "product_sku": "B2",
                       "date_published_parsed": "2026-04-12"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "rating": 2, "product_sku": "C3",
                       "date_published_parsed": "2026-04-15"},
            "labels": [{"label_code": "shipping_delay", "label_polarity": "negative"}],
        },
    ]
    result = _build_issue_trend("month", logical_day, labeled_reviews)

    assert result["status"] == "ready"
    secondary = result["secondary_charts"]
    assert len(secondary) >= 2

    chart_types = {chart["chart_type"] for chart in secondary}
    assert "stacked_bar" in chart_types or "bar" in chart_types, \
        f"expected stacked_bar/bar, got {chart_types}"

    titles = {chart["title"] for chart in secondary}
    assert any("SKU" in t or "产品" in t for t in titles), \
        f"missing affected-SKU chart: {titles}"
```

- [ ] **Step 4.2: 写失败测试 — comparison 内容**

```python
def test_issue_trend_emits_comparison_with_top_issue_heat():
    """Phase 2 T9: issues dim comparison.start_vs_end 度量为「头号问题在窗口首尾的评论数」。"""
    from qbu_crawler.server.report_analytics import _build_issue_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        {
            "review": {"ownership": "own", "product_sku": "A1",
                       "date_published_parsed": "2026-03-26"},  # 月初
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "product_sku": "B2",
                       "date_published_parsed": "2026-04-23"},  # 月末
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
    ]
    result = _build_issue_trend("month", logical_day, labeled_reviews)
    comp = result["comparison"]
    assert set(comp.keys()) == {"period_over_period", "year_over_year", "start_vs_end"}
    sve = comp["start_vs_end"]
    assert sve["start"] is not None
    assert sve["end"] is not None
```

- [ ] **Step 4.3: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py -v -k "issue_trend_emits"`
Expected: FAIL

- [ ] **Step 4.4: 新增 helper**

在 `_build_issue_trend` 函数下方加：

```python
def _build_issue_secondary_charts(labels, ranked_codes, counts_by_label, affected_products):
    """Phase 2 T9: issues dim 辅图 —
    1) Top 3 问题在 buckets 上的分时段堆叠 (stacked_bar)，复用 primary 数据但展示形态不同
    2) Top 3 问题受影响 SKU 数 (bar，x=问题，y=affected SKU 数)"""
    from qbu_crawler.server.report_common import _label_display

    if not ranked_codes:
        return []

    stacked_status = "ready"
    stacked = {
        "status": stacked_status,
        "chart_type": "stacked_bar",
        "title": "Top3 问题分时段堆叠",
        "labels": labels,
        "series": [
            {
                "name": _label_display(code),
                "data": [counts_by_label[code].get(label, 0) for label in labels],
            }
            for code in ranked_codes
        ],
    }

    affected_status = "ready"
    affected = {
        "status": affected_status,
        "chart_type": "bar",
        "title": "Top3 问题影响 SKU 数",
        "labels": [_label_display(code) for code in ranked_codes],
        "series": [
            {
                "name": "影响 SKU 数",
                "data": [
                    len([name for name in affected_products.get(code, set()) if name])
                    for code in ranked_codes
                ],
            },
        ],
    }
    return [stacked, affected]


def _build_issue_comparison(labels, ranked_codes, counts_by_label):
    """Phase 2 T9: issues dim comparison — 度量「头号问题在 bucket 上的评论数」。
    start_vs_end: 第一个非 0 bucket vs 最后一个非 0 bucket"""
    comparison = _empty_comparison()
    if not ranked_codes:
        return comparison

    top_code = ranked_codes[0]
    bucket_counts = [counts_by_label[top_code].get(label, 0) for label in labels]
    pairs = [(label, count) for label, count in zip(labels, bucket_counts) if count > 0]
    start_value = pairs[0][1] if pairs else None
    end_value = pairs[-1][1] if pairs else None
    change_pct = None
    if start_value is not None and end_value is not None and start_value != 0:
        change_pct = round((end_value - start_value) / start_value * 100, 1)

    comparison["start_vs_end"]["label"] = "头号问题首尾热度对比"
    comparison["start_vs_end"]["start"] = start_value
    comparison["start_vs_end"]["end"] = end_value
    comparison["start_vs_end"]["change_pct"] = change_pct
    return comparison
```

- [ ] **Step 4.5: 改主函数拼装**

把 `_build_issue_trend` 末尾 ready 分支的 `return _trend_dimension_payload(...)` 改为传入新字段：

```python
    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={
            "status": "ready",
            "items": [
                {"label": "问题信号数", "value": sum(sum(counts_by_label[code].values()) for code in ranked_codes)},
                {"label": "活跃问题数", "value": len(ranked_codes)},
                {"label": "头号问题", "value": _label_display(top_code)},
                {"label": "涉及产品数", "value": rows[0]["affected_product_count"]},
            ],
        },
        primary_chart={
            "status": "ready",
            "chart_type": "line",
            "title": "问题趋势",
            "labels": labels,
            "series": [
                {
                    "name": _label_display(code),
                    "data": [counts_by_label[code].get(label, 0) for label in labels],
                }
                for code in ranked_codes
            ],
        },
        secondary_charts=_build_issue_secondary_charts(
            labels, ranked_codes, counts_by_label, affected_products,
        ),
        comparison=_build_issue_comparison(labels, ranked_codes, counts_by_label),
        table={
            "status": "ready",
            "columns": ["问题", "评论数", "影响产品数"],
            "rows": rows,
        },
    )
```

- [ ] **Step 4.6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py -v -k "issue_trend_emits"`
Expected: PASS

- [ ] **Step 4.7: 跑 issues 既有测试**

Run: `uv run pytest tests/test_report_analytics.py -v -k "issue"`
Expected: ALL PASS

- [ ] **Step 4.8: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report_analytics): issues 维度 secondary_charts + comparison (T9 step 4)"
```

---

## Task 5: products 维度 · secondary\_charts (评论总数 + 价格) + comparison (start\_vs\_end 重点 SKU 评分)

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1626-1718`（`_build_product_trend` 主函数）
- Add: `qbu_crawler/server/report_analytics.py`（新增 `_build_product_secondary_charts` + `_build_product_comparison`）
- Test: `tests/test_report_analytics.py`

- [ ] **Step 5.1: 写失败测试 — secondary\_charts**

```python
def test_product_trend_emits_two_secondary_charts_when_ready(analytics_db):
    """Phase 2 T9: products dim ready 时辅图 2 张：
    1) 重点 SKU 评论总数趋势 (line)
    2) 重点 SKU 价格趋势 (line)
    依赖 product_snapshots 已有 >=2 个时间点。"""
    from qbu_crawler.server.report_analytics import _build_product_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    snapshot_products = [
        {"sku": "A1", "name": "Prod A", "ownership": "own", "rating": 4.2,
         "review_count": 200, "scraped_at": "2026-04-24T08:00:00+08:00"},
    ]
    # 模拟 trend_series 提供 >=2 个时间点
    trend_series = [
        {
            "product_sku": "A1",
            "series": [
                {"date": "2026-04-01", "rating": 4.0, "review_count": 180, "price": 99.0},
                {"date": "2026-04-15", "rating": 4.2, "review_count": 200, "price": 95.0},
            ],
        },
    ]
    result = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    assert result["status"] == "ready"

    secondary = result["secondary_charts"]
    assert len(secondary) >= 2
    titles = {c["title"] for c in secondary}
    assert any("评论" in t for t in titles), titles
    assert any("价格" in t or "price" in t.lower() for t in titles), titles
```

- [ ] **Step 5.2: 写失败测试 — comparison**

```python
def test_product_trend_emits_comparison_with_focus_sku_rating(analytics_db):
    """Phase 2 T9: products dim comparison.start_vs_end 度量为「重点 SKU 评分」。
    使用 trend_series 首尾点。"""
    from qbu_crawler.server.report_analytics import _build_product_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    snapshot_products = [
        {"sku": "A1", "name": "Prod A", "ownership": "own", "rating": 4.2,
         "review_count": 200, "scraped_at": "2026-04-24T08:00:00+08:00"},
    ]
    trend_series = [
        {
            "product_sku": "A1",
            "series": [
                {"date": "2026-04-01", "rating": 3.8, "review_count": 100, "price": 99.0},
                {"date": "2026-04-23", "rating": 4.2, "review_count": 200, "price": 95.0},
            ],
        },
    ]
    result = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    sve = result["comparison"]["start_vs_end"]
    assert sve["start"] == 3.8
    assert sve["end"] == 4.2
    assert sve["change_pct"] is not None
```

- [ ] **Step 5.3: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py -v -k "product_trend_emits"`
Expected: FAIL

- [ ] **Step 5.4: 新增 helper**

在 `_build_product_trend` 下方：

```python
def _build_product_secondary_charts(labels, ready_series, bucket_to_review_count):
    """Phase 2 T9: products dim 辅图 —
    1) 重点 SKU 评论总数走势 (line)
    2) 重点 SKU 价格走势 (line) — series 用 trend_series 中的 price"""
    if ready_series is None:
        return []

    bucket_to_price = {label: None for label in labels}
    for point in ready_series.get("points") or []:
        bucket = point.get("bucket")
        if bucket and bucket in bucket_to_price:
            bucket_to_price[bucket] = point.get("price")

    review_status = "ready"
    review_chart = {
        "status": review_status,
        "chart_type": "line",
        "title": f"重点 SKU 评论总数 - {ready_series['product_name']}",
        "labels": labels,
        "series": [
            {"name": "评论总数", "data": [bucket_to_review_count[label] for label in labels]},
        ],
    }

    has_price = any(v is not None for v in bucket_to_price.values())
    price_status = "ready" if has_price else "accumulating"
    price_chart = {
        "status": price_status,
        "chart_type": "line",
        "title": f"重点 SKU 价格 - {ready_series['product_name']}",
        "labels": labels if has_price else [],
        "series": [
            {"name": "价格", "data": [bucket_to_price[label] for label in labels]},
        ] if has_price else [],
    }
    return [review_chart, price_chart]


def _build_product_comparison(ready_series):
    """Phase 2 T9: products dim comparison — 度量「重点 SKU 评分」。
    start_vs_end: trend_series 第一个 / 最后一个有 rating 的 point。
    helper 内部按 bucket 排序作防御 — 生产路径 _build_trend_data 已 ORDER BY scraped_at ASC，
    但单测/未来调用方传入乱序 points 时这层排序保证语义不被静默颠倒。"""
    comparison = _empty_comparison()
    if ready_series is None:
        return comparison

    points = ready_series.get("points") or []
    rating_points = sorted(
        [p for p in points if p.get("rating") is not None],
        key=lambda p: p.get("bucket") or "",
    )
    if len(rating_points) < 2:
        return comparison

    start_value = rating_points[0]["rating"]
    end_value = rating_points[-1]["rating"]
    change_pct = None
    if start_value not in (None, 0):
        change_pct = round((end_value - start_value) / start_value * 100, 1)

    comparison["start_vs_end"]["label"] = "重点 SKU 评分首尾对比"
    comparison["start_vs_end"]["start"] = start_value
    comparison["start_vs_end"]["end"] = end_value
    comparison["start_vs_end"]["change_pct"] = change_pct
    return comparison
```

- [ ] **Step 5.5: 改主函数拼装**

替换 `_build_product_trend` 末尾 ready 分支 `return _trend_dimension_payload(...)`：

```python
    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={
            "status": "ready",
            "items": [
                {"label": "跟踪产品数", "value": len(own_products)},
                {"label": "有快照产品数", "value": sum(1 for row in rows if row["snapshot_points"] > 0)},
                {"label": "可成图产品数", "value": 1},
                {"label": "快照点数", "value": len(ready_series["points"])},
            ],
        },
        primary_chart={
            "status": "ready",
            "chart_type": "line",
            "title": f"产品趋势 - {ready_series['product_name']}",
            "labels": labels,
            "series": [
                {"name": "评分", "data": [bucket_to_rating[label] for label in labels]},
                {"name": "评论总数", "data": [bucket_to_review_count[label] for label in labels]},
            ],
        },
        secondary_charts=_build_product_secondary_charts(
            labels, ready_series, bucket_to_review_count,
        ),
        comparison=_build_product_comparison(ready_series),
        table={
            "status": "ready",
            "columns": ["SKU", "产品", "当前评分", "当前评论总数", "快照点数", "最新抓取时间"],
            "rows": rows,
        },
    )
```

- [ ] **Step 5.6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py -v -k "product_trend_emits"`
Expected: PASS

- [ ] **Step 5.7: 跑 product 既有测试**

Run: `uv run pytest tests/test_report_analytics.py -v -k "product or trend_digest"`
Expected: ALL PASS

- [ ] **Step 5.8: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report_analytics): products 维度 secondary_charts + comparison (T9 step 5)"
```

---

## Task 6: competition 维度 · secondary\_charts (评分差 + 差/好评率对比) + comparison (start\_vs\_end 评分差)

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1721-1833`（`_build_competition_trend` 主函数）
- Add: `qbu_crawler/server/report_analytics.py`（新增 `_build_competition_secondary_charts` + `_build_competition_comparison`）
- Test: `tests/test_report_analytics.py`

- [ ] **Step 6.1: 写失败测试 — secondary\_charts**

```python
def test_competition_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: competition dim ready 时辅图 2 张：
    1) 评分差趋势 (line, 单 series = competitor_avg - own_avg)
    2) 差/好评率对比 (line, series = own_negative_rate, competitor_positive_rate)"""
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = []
    for d in ["2026-04-10", "2026-04-12", "2026-04-15"]:
        labeled_reviews.append({"review": {"ownership": "own", "rating": 3,
                                            "date_published_parsed": d}})
        labeled_reviews.append({"review": {"ownership": "competitor", "rating": 4,
                                            "date_published_parsed": d}})
    result = _build_competition_trend("month", logical_day, labeled_reviews)
    assert result["status"] == "ready"

    secondary = result["secondary_charts"]
    assert len(secondary) >= 2

    titles = {c["title"] for c in secondary}
    assert any("评分差" in t or "差距" in t for t in titles), titles
    assert any("差评" in t or "好评" in t for t in titles), titles
```

- [ ] **Step 6.2: 写失败测试 — comparison**

```python
def test_competition_trend_emits_comparison_with_rating_gap():
    """Phase 2 T9: competition dim comparison.start_vs_end 度量为「评分差 (competitor - own)」。"""
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 4, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "competitor", "rating": 4.5, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "own", "rating": 3, "date_published_parsed": "2026-04-22"}},
        {"review": {"ownership": "competitor", "rating": 4, "date_published_parsed": "2026-04-22"}},
    ]
    result = _build_competition_trend("month", logical_day, labeled_reviews)
    sve = result["comparison"]["start_vs_end"]
    assert sve["start"] is not None
    assert sve["end"] is not None
```

- [ ] **Step 6.3: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py -v -k "competition_trend_emits"`
Expected: FAIL

- [ ] **Step 6.4: 新增 helper**

在 `_build_competition_trend` 下方：

```python
def _build_competition_secondary_charts(labels, own_avg_rating, competitor_avg_rating,
                                         own_negative_rate, competitor_positive_rate):
    """Phase 2 T9: competition dim 辅图 —
    1) 评分差趋势 (line, competitor - own，None 透传)
    2) 差/好评率对比 (line, series=own_neg_rate + competitor_pos_rate)"""
    gap_data = []
    for own_v, comp_v in zip(own_avg_rating, competitor_avg_rating):
        if own_v is None or comp_v is None:
            gap_data.append(None)
        else:
            gap_data.append(round(comp_v - own_v, 2))
    gap_status = "ready" if any(v is not None for v in gap_data) else "accumulating"

    rate_status = "ready" if (
        any(v is not None for v in own_negative_rate)
        or any(v is not None for v in competitor_positive_rate)
    ) else "accumulating"

    return [
        {
            "status": gap_status,
            "chart_type": "line",
            "title": "评分差趋势 (竞品 − 自有)",
            "labels": labels if gap_status == "ready" else [],
            "series": [
                {"name": "评分差", "data": gap_data},
            ] if gap_status == "ready" else [],
        },
        {
            "status": rate_status,
            "chart_type": "line",
            "title": "差/好评率对比",
            "labels": labels if rate_status == "ready" else [],
            "series": [
                {"name": "自有差评率(%)", "data": own_negative_rate},
                {"name": "竞品好评率(%)", "data": competitor_positive_rate},
            ] if rate_status == "ready" else [],
        },
    ]


def _build_competition_comparison(labels, own_avg_rating, competitor_avg_rating):
    """Phase 2 T9: competition dim comparison — 度量「评分差 (competitor - own)」。
    start_vs_end: 第一个 / 最后一个 own & comp 都非 None 的 bucket"""
    comparison = _empty_comparison()
    pairs = []
    for label, own_v, comp_v in zip(labels, own_avg_rating, competitor_avg_rating):
        if own_v is not None and comp_v is not None:
            pairs.append((label, round(comp_v - own_v, 2)))
    if len(pairs) < 1:
        return comparison

    start_value = pairs[0][1]
    end_value = pairs[-1][1]
    change_pct = None
    if start_value not in (None, 0):
        change_pct = round((end_value - start_value) / abs(start_value) * 100, 1)

    comparison["start_vs_end"]["label"] = "评分差首尾对比"
    comparison["start_vs_end"]["start"] = start_value
    comparison["start_vs_end"]["end"] = end_value
    comparison["start_vs_end"]["change_pct"] = change_pct
    return comparison
```

- [ ] **Step 6.5: 改主函数拼装**

替换 `_build_competition_trend` 末尾 `return _trend_dimension_payload(...)`：

```python
    return _trend_dimension_payload(
        status=top_status,
        message=top_message,
        kpis={
            "status": kpi_status,
            "items": [
                {"label": "可比时间点", "value": shared_points},
                {"label": "最新评分差", "value": rating_gap if rating_gap is not None else "—"},
                {"label": "最新自有差评率", "value": f"{_own_neg:.1f}%" if _own_neg is not None else "—"},
                {"label": "最新竞品好评率", "value": f"{_comp_pos:.1f}%" if _comp_pos is not None else "—"},
            ],
        },
        primary_chart={
            "status": "ready" if chart_ready else "accumulating",
            "chart_type": "line",
            "title": "竞品趋势",
            "labels": labels if chart_ready else [],
            "series": [
                {"name": "自有均分", "data": own_avg_rating},
                {"name": "竞品均分", "data": competitor_avg_rating},
            ] if chart_ready else [],
        },
        secondary_charts=_build_competition_secondary_charts(
            labels, own_avg_rating, competitor_avg_rating,
            own_negative_rate, competitor_positive_rate,
        ),
        comparison=_build_competition_comparison(
            labels, own_avg_rating, competitor_avg_rating,
        ),
        table={
            "status": "ready" if any_side_has_data else "accumulating",
            "columns": ["日期", "自有均分", "竞品均分", "自有差评率", "竞品好评率"],
            "rows": rows,
        },
    )
```

- [ ] **Step 6.6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py -v -k "competition_trend_emits"`
Expected: PASS

- [ ] **Step 6.7: 跑 competition 既有测试**

Run: `uv run pytest tests/test_report_analytics.py -v -k "competition"`
Expected: ALL PASS

- [ ] **Step 6.8: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report_analytics): competition 维度 secondary_charts + comparison (T9 step 6)"
```

---

## Task 7: report\_charts.py · build\_chartjs\_configs 输出 secondary chart 配置

**Files:**
- Modify: `qbu_crawler/server/report_charts.py:601-613`（`build_chartjs_configs` 末段）
- Test: `tests/test_report_charts.py`（如不存在则新建）

- [ ] **Step 7.1: 检查 tests/test_report_charts.py 是否存在**

Run: `ls tests/test_report_charts.py 2>/dev/null && echo EXISTS || echo MISSING`

如 MISSING → 新建文件，加 import 框架；如 EXISTS → 直接追加。

- [ ] **Step 7.2: 写失败测试 — secondary chart 配置生成**

如新建：

```python
"""Tests for qbu_crawler.server.report_charts."""
from __future__ import annotations


def test_build_chartjs_configs_emits_secondary_chart_keys():
    """Phase 2 T9: trend_digest.data[view][dim].secondary_charts 中
    每个 status='ready' 的辅图都必须在 build_chartjs_configs 输出中
    生成一个独立 key: trend_{view}_{dim}_secondary_{idx}。"""
    from qbu_crawler.server.report_charts import build_chartjs_configs

    analytics = {
        "trend_digest": {
            "data": {
                "month": {
                    "sentiment": {
                        "status": "ready",
                        "primary_chart": {
                            "status": "ready",
                            "chart_type": "line",
                            "labels": ["2026-04-01", "2026-04-02"],
                            "series": [{"name": "评论量", "data": [3, 5]}],
                        },
                        "secondary_charts": [
                            {
                                "status": "ready",
                                "chart_type": "line",
                                "title": "自有差评率趋势",
                                "labels": ["2026-04-01", "2026-04-02"],
                                "series": [{"name": "自有差评率(%)", "data": [10.0, 5.0]}],
                            },
                            {
                                "status": "accumulating",  # 应被跳过
                                "chart_type": "line",
                                "title": "健康分趋势",
                                "labels": [],
                                "series": [],
                            },
                        ],
                    }
                }
            }
        }
    }
    configs = build_chartjs_configs(analytics)

    # 主图仍存在
    assert "trend_month_sentiment" in configs
    # ready 辅图生成 _secondary_0
    assert "trend_month_sentiment_secondary_0" in configs
    # accumulating 辅图被跳过 → _secondary_1 不存在
    assert "trend_month_sentiment_secondary_1" not in configs
    # 主图 key 与辅图 key 内容互不污染
    assert configs["trend_month_sentiment_secondary_0"]["type"] == "line"


def test_build_chartjs_configs_skips_secondary_when_primary_not_ready():
    """primary 不 ready 时连同辅图整体跳过（与 Phase 1 老逻辑一致：
    模板 chart_ready 判断会先看 trend_block.status，再看 chart 自身 status）"""
    from qbu_crawler.server.report_charts import build_chartjs_configs

    analytics = {
        "trend_digest": {
            "data": {
                "week": {
                    "sentiment": {
                        "status": "accumulating",
                        "primary_chart": {"status": "accumulating", "chart_type": "line",
                                           "labels": [], "series": []},
                        "secondary_charts": [
                            {
                                "status": "ready",  # 即便 secondary 单独 ready，块整体 accumulating
                                "chart_type": "line",
                                "title": "自有差评率趋势",
                                "labels": ["a", "b"],
                                "series": [{"name": "x", "data": [1, 2]}],
                            },
                        ],
                    }
                }
            }
        }
    }
    configs = build_chartjs_configs(analytics)
    # 块 accumulating → 主图与辅图都不出
    assert "trend_week_sentiment" not in configs
    assert "trend_week_sentiment_secondary_0" not in configs


def test_build_chartjs_configs_supports_stacked_bar_secondary():
    """Phase 2 T9: issues dim 的 secondary_chart 可能是 stacked_bar，
    Chart.js config 仍要能生成（fallback 到 _chartjs_trend_line，输出 type=line）。
    T10 模板侧再细分样式；这里锁住"不抛异常 + secondary key 必须存在 + 类型保持 line（fallback）"。"""
    from qbu_crawler.server.report_charts import build_chartjs_configs

    analytics = {
        "trend_digest": {
            "data": {
                "month": {
                    "issues": {
                        "status": "ready",
                        "primary_chart": {
                            "status": "ready",
                            "chart_type": "line",
                            "labels": ["a", "b"],
                            "series": [{"name": "x", "data": [1, 2]}],
                        },
                        "secondary_charts": [
                            {
                                "status": "ready",
                                "chart_type": "stacked_bar",
                                "title": "Top3 问题分时段堆叠",
                                "labels": ["a", "b"],
                                "series": [{"name": "issue_a", "data": [3, 2]}],
                            },
                        ],
                    }
                }
            }
        }
    }
    configs = build_chartjs_configs(analytics)
    # 主图存在
    assert "trend_month_issues" in configs
    # stacked_bar secondary fallback 为 line 配置生成（不抛异常且 key 存在）
    assert "trend_month_issues_secondary_0" in configs
    # T9 阶段 fallback 为 line type；T10 模板侧落地时再细分 stacked_bar 渲染
    assert configs["trend_month_issues_secondary_0"]["type"] == "line"
```

- [ ] **Step 7.3: 跑测试确认失败**

Run: `uv run pytest tests/test_report_charts.py -v`
Expected: FAIL（`trend_month_sentiment_secondary_0` 不存在）

- [ ] **Step 7.4: 改 build\_chartjs\_configs**

替换 `qbu_crawler/server/report_charts.py:601-613`：

```python
    trend_digest = analytics.get("trend_digest") or {}
    for view, dimensions in (trend_digest.get("data") or {}).items():
        for dimension, payload in (dimensions or {}).items():
            if (payload or {}).get("status") != "ready":
                continue
            primary_chart = (payload or {}).get("primary_chart") or {}
            if (
                primary_chart.get("status") == "ready"
                and primary_chart.get("chart_type") == "line"
                and primary_chart.get("labels")
                and primary_chart.get("series")
            ):
                configs[f"trend_{view}_{dimension}"] = _chartjs_trend_line(primary_chart)

            # Phase 2 T9: secondary_charts (索引顺序保留)
            for idx, sec_chart in enumerate((payload or {}).get("secondary_charts") or []):
                if not sec_chart:
                    continue
                if sec_chart.get("status") != "ready":
                    continue
                chart_type = sec_chart.get("chart_type")
                # 当前 Chart.js builder 仅稳妥处理 line；stacked_bar/bar 也走 line 模板（多 series），
                # 视觉上仍然可读。后续 T10 模板侧再细化样式。
                if chart_type not in {"line", "bar", "stacked_bar"}:
                    continue
                if not sec_chart.get("labels") or not sec_chart.get("series"):
                    continue
                configs[f"trend_{view}_{dimension}_secondary_{idx}"] = _chartjs_trend_line(sec_chart)

    return configs
```

- [ ] **Step 7.5: 跑测试确认通过**

Run: `uv run pytest tests/test_report_charts.py -v`
Expected: PASS

- [ ] **Step 7.6: 跑 v3 html 既有测试，确保模板调用方未受影响**

Run: `uv run pytest tests/test_v3_html.py -v -k "trend or chart"`
Expected: ALL PASS（既有 `chart_key in charts` 判断的 primary chart key 仍以同名生成）

- [ ] **Step 7.7: 提交**

```bash
git add qbu_crawler/server/report_charts.py tests/test_report_charts.py
git commit -m "feat(report_charts): build_chartjs_configs 输出 secondary chart 配置 (T9 step 7)"
```

---

## Task 8: 契约不变量 + grep 门禁 + 时间口径回归

**Files:**
- Modify: `tests/test_metric_semantics.py`（新增 4 条 grep 门禁）
- Modify: `tests/test_report_analytics.py`（新增 1 条时间口径断言）
- Test: 全量 trend / report 套件

**目的：** 锁住 Phase 2 进行中的禁改清单（Continuity §🧊），以及 audit §6.1 / 原始 plan T9 step 2 要求的时间口径分离。

- [ ] **Step 8.1: 写时间口径回归测试**

加到 `tests/test_report_analytics.py`：

```python
def test_trend_dimensions_use_correct_time_field():
    """Phase 2 T9 + 原始 plan T9 step 2:
    sentiment / issues / competition 必须基于 review.date_published_parsed (评论发布时间);
    products 必须基于 product_snapshot.scraped_at (抓取时间).

    关键防御：构造一条评论 date_published_parsed 在月窗口内、date_published 落到窗口外，
    若实现误用 date_published 而非 date_published_parsed，桶为空 → sentiment 变 accumulating。"""
    from qbu_crawler.server.report_analytics import (
        _build_sentiment_trend, _build_issue_trend,
        _build_product_trend,
    )
    from datetime import date

    logical_day = date(2026, 4, 24)

    # case 1: parsed 在窗口内 (2026-04-10)，原始 date_published 字段在窗口外 (2026-01-01)
    # 这能区分实现是用 date_published_parsed 还是 fallback 到 date_published
    review_published_parsed = {
        "ownership": "own",
        "rating": 1,
        "date_published_parsed": "2026-04-10",  # 月窗口内
        "date_published": "2026-01-01",          # 月窗口外（陷阱字段）
    }
    labeled_reviews = [
        {"review": review_published_parsed,
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}]},
    ]

    sentiment = _build_sentiment_trend("month", logical_day, labeled_reviews)
    assert sentiment["status"] == "ready", \
        "sentiment 必须优先用 date_published_parsed 落桶 → 落入 4 月 → ready；" \
        "若误读 date_published 会落到 1 月窗口外 → accumulating"

    issues = _build_issue_trend("month", logical_day, labeled_reviews)
    assert issues["status"] == "ready", \
        "issues 必须优先用 date_published_parsed 落桶（同 sentiment 口径）"

    # case 2: products 应基于 scraped_at（snapshot 字段），评论时间字段不影响
    snapshot_products = [
        {"sku": "A1", "name": "Prod A", "ownership": "own", "rating": 4.0,
         "review_count": 100, "scraped_at": "2026-04-24T08:00:00+08:00"},
    ]
    trend_series = [
        {
            "product_sku": "A1",
            # series 用的 date 字段对应 product_snapshots.scraped_at
            "series": [
                {"date": "2026-04-01", "rating": 3.8, "review_count": 90, "price": 99.0},
                {"date": "2026-04-23", "rating": 4.0, "review_count": 100, "price": 95.0},
            ],
        },
    ]
    products = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    assert products["status"] == "ready", \
        "products 必须按 scraped_at（即 series[*].date）落桶"
```

- [ ] **Step 8.2: 跑时间口径测试**

Run: `uv run pytest tests/test_report_analytics.py::test_trend_dimensions_use_correct_time_field -v`
Expected: PASS（已有实现已经按正确字段，本测试只是回归锁）

- [ ] **Step 8.3: 写契约 grep 门禁**

加到 `tests/test_metric_semantics.py`：

```python
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
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root))
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
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    # 用相对仓库根的 pathspec，避免 Windows 绝对路径让 git grep 报 returncode=128
    targets = ["qbu_crawler/", "tests/"]

    for pattern in ("kpis_v2", "metric_new_"):
        offending, _ = _git_grep(repo_root, pattern, targets)
        offending = [f for f in offending if "test_metric_semantics.py" not in f]
        assert not offending, \
            f"Phase 2 禁止引入第二套 KPI 命名 {pattern!r}，违规文件: {offending}"


def test_phase2_t9_template_does_not_consume_secondary_charts_yet():
    """Phase 2 T9 阶段：HTML 模板 / Excel / 邮件不得消费 secondary_charts 字段
    （T9 仅扩数据层，T10 才落地展示层；提前消费会让 T9 单独验收时观测到模板异常）。"""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    targets_disallowed = [
        "qbu_crawler/server/report_templates/",
        "qbu_crawler/server/report.py",  # Excel 入口
    ]
    offending, _ = _git_grep(repo_root, "secondary_charts", targets_disallowed)
    assert not offending, \
        f"T9 阶段模板/Excel 不得消费 secondary_charts，违规: {offending}"


def test_phase2_t9_template_does_not_bypass_trend_digest():
    """Phase 2 进行中禁改清单 (Continuity §🧊):
    模板不得绕过 trend_digest 直接读 analytics.window / analytics._trend_series / cumulative_kpis。"""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    targets = ["qbu_crawler/server/report_templates/"]

    for pattern in (r"analytics\.window", r"analytics\._trend_series", r"cumulative_kpis"):
        offending, _ = _git_grep(repo_root, pattern, targets, use_extended_regex=True)
        assert not offending, \
            f"模板禁止直接读 {pattern!r}（必须经 trend_digest），违规: {offending}"


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
```

- [ ] **Step 8.4: 跑全部 4 条门禁**

Run: `uv run pytest tests/test_metric_semantics.py -v -k "phase2_t9"`
Expected: ALL PASS

- [ ] **Step 8.5: 跑全量 report 测试套件**

Run:

```bash
uv run pytest \
  tests/test_report.py \
  tests/test_report_snapshot.py \
  tests/test_report_analytics.py \
  tests/test_report_common.py \
  tests/test_report_llm.py \
  tests/test_report_charts.py \
  tests/test_v3_llm.py \
  tests/test_v3_html.py \
  tests/test_v3_excel.py \
  tests/test_report_integration.py \
  tests/test_metric_semantics.py \
  tests/test_v3_modes.py -v
```

Expected: ALL PASS（pre-existing 失败 ≤ Stage B 已记录的 2 条）

- [ ] **Step 8.6: 提交**

```bash
git add tests/test_report_analytics.py tests/test_metric_semantics.py
git commit -m "test(report): T9 契约不变量 + 时间口径回归 + grep 门禁 (T9 step 8)"
```

---

## Task 9: 版本号 bump + Continuity 推进 + tag

**Files:**
- Modify: `pyproject.toml`（version: `0.3.19` → `0.3.20`）
- Modify: `qbu_crawler/__init__.py`（`__version__ = "0.3.20"`）
- Modify: `uv.lock`（lock 同步）
- Modify: `docs/reviews/2026-04-24-report-upgrade-continuity.md`

- [ ] **Step 9.1: 版本号 bump**

```bash
# 在 pyproject.toml 把 version = "0.3.19" 改为 version = "0.3.20"
# 在 qbu_crawler/__init__.py 把 __version__ = "0.3.19" 改为 __version__ = "0.3.20"
uv lock
```

- [ ] **Step 9.2: 更新 Continuity.md 当前 Stage 指针**

替换文件头部 `## 🧭 当前 Stage 指针` 块为：

```markdown
## 🧭 当前 Stage 指针

```
status:         Phase2-T9-COMPLETE · Phase2-T10-NOT-STARTED
last_updated:   2026-04-25
last_commit:    <填入 T9 step 9 提交哈希>
last_tag:       v0.3.20-phase2-t9
next_action:    Phase 2 T10 implementation plan via superpowers:writing-plans (HTML 模板辅图槽位 + Excel 趋势数据 sheet 分块)
next_stage:     Phase 2 T10 · HTML + Excel 阅读体验
blocked_by:     T9 上线后跑 1 个 daily run 验证 trend_digest 扩展数据层产出无回归
```
```

（last_commit 在 step 9.4 commit 之后回填实际哈希）

- [ ] **Step 9.3: 追加 Continuity.md 进度日志**

在 `## 📝 进度日志` 紧跟标题下方插入新一条（最新置顶）：

```markdown
### 2026-04-25 第 3 session (Phase 2 T9 执行)
- **Who**：Claude (Opus 4.7 1M · subagent-driven-development 或 executing-plans)
- **Done**：
  - Task 1 (T9-S1): trend_dimension_payload / _empty_trend_dimension 加 secondary_charts + comparison 占位
  - Task 2 (T9-S2): accumulating 状态 KPI 永远 4 占位（修 audit §4.1）
  - Task 3-6 (T9-S3~S6): sentiment / issues / products / competition 4 维度各加 2 张 secondary_charts + comparison.start_vs_end
  - Task 7 (T9-S7): build_chartjs_configs 输出 trend_{view}_{dim}_secondary_{idx} 配置
  - Task 8 (T9-S8): 契约不变量 + grep 门禁 4 条 + 时间口径回归
  - Task 9 (T9-S9): 版本号 bump 0.3.19 → 0.3.20 + Continuity 推进 + tag v0.3.20-phase2-t9
  - 全量 report 套件全绿；模板 0 改动（T10 territory）；Phase 1 顶层 / 子层契约 0 改动
- **Carry-over（follow-up，不阻塞 T10）**：
  - period_over_period / year_over_year 当前固定 null，待历史数据扩展（Phase 2 后续 task / Phase 3）
  - secondary chart stacked_bar/bar 在 Chart.js 渲染端目前共享 line builder，T10 需要按 chart_type 细分
- **Next**：T9 上线后跑 1 个 daily run 验证 trend_digest 扩展数据层产出无回归 → 写 Phase 2 T10 implementation plan
```

- [ ] **Step 9.4: 提交 + tag**

```bash
git add pyproject.toml qbu_crawler/__init__.py uv.lock docs/reviews/2026-04-24-report-upgrade-continuity.md
git commit -m "chore: bump version 0.3.19 -> 0.3.20 (Phase 2 T9 完成 · trend_digest 数据层扩展)"

# 回填 step 9.2 中 last_commit 的实际哈希到 Continuity.md
git log -1 --format=%h
# 把上一步输出的哈希填入 Continuity.md last_commit 字段，再 amend 当前 commit:
git add docs/reviews/2026-04-24-report-upgrade-continuity.md
git commit --amend --no-edit

git tag -a v0.3.20-phase2-t9 -m "Phase 2 T9 完成 · trend_digest 数据层扩展"
```

- [ ] **Step 9.5: 最后跑一遍全量回归 + grep 门禁**

```bash
# 全量 report 套件
uv run pytest \
  tests/test_report.py \
  tests/test_report_snapshot.py \
  tests/test_report_analytics.py \
  tests/test_report_common.py \
  tests/test_report_llm.py \
  tests/test_report_charts.py \
  tests/test_v3_llm.py \
  tests/test_v3_html.py \
  tests/test_v3_excel.py \
  tests/test_report_integration.py \
  tests/test_metric_semantics.py \
  tests/test_v3_modes.py -v

# grep 门禁手工复核
git grep -n "kpis_v2\|metric_new_" -- qbu_crawler/ tests/ | grep -v test_metric_semantics.py
# 上一行应当为空输出

git grep -n "secondary_charts" -- qbu_crawler/server/report_templates/ qbu_crawler/server/report.py
# 上一行应当为空输出（T10 之前模板/Excel 不消费）

git grep -nE "analytics\.window|analytics\._trend_series|cumulative_kpis" -- qbu_crawler/server/report_templates/
# 上一行应当为空输出
```

Expected: 全绿 + 三段 grep 全部 0 命中。

---

## 实施顺序

严格按 Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 顺序执行。Task 3-6 之间技术上文件不冲突，但依赖 Task 1 的 helper 已落位 + Task 2 的 KPI 占位策略已确定，所以**仍按顺序串行执行**，避免 commit 顺序混乱。

---

## Definition of Done · Phase 2 T9 Exit

按 execution-plan §2 / phase2-audit §6.1 / Continuity §🎯 收口验收：

1. **secondary_charts 至少 2 条 / 维度 / 视角**：12 块 (3 view × 4 dim) 在 ready 状态下都有 ≥2 条 secondary_charts，每条具备 `status / chart_type / labels / series / title` 5 个键 — 已被 Task 1 + Task 3-6 测试覆盖。
2. **kpis.items 长度恒为 4**：12 块在任何 status 下 kpis.items 都恰好 4 条 — 已被 Task 2 测试覆盖。
3. **comparison 三段 shape 永远存在**：`period_over_period / year_over_year / start_vs_end` 三个 key 永不缺，缺数据时填 null — 已被 Task 1 + Task 3-6 测试覆盖。
4. **Phase 1 契约不变**：trend_digest 顶层 4 个键 + data 子层 5 个 Phase 1 键全数保留 — 已被 Task 8.4 (`test_phase2_t9_phase1_trend_digest_keys_unchanged`) 测试覆盖。
5. **不引入第二套 KPI**：grep `kpis_v2` / `metric_new_` 在 qbu_crawler/ 与 tests/ 下 0 命中（test_metric_semantics.py 自身允许）— 已被 Task 8.4 测试覆盖。
6. **模板 / Excel / 邮件 0 改动**：grep `secondary_charts` 在 report_templates/ 与 report.py 下 0 命中 — 已被 Task 8.4 测试覆盖。
7. **时间口径分离**：sentiment/issues/competition 走 `date_published_parsed`，products 走 `scraped_at` — 已被 Task 8.1 测试覆盖。
8. **全量 pytest report 套件全绿**（Stage B 已记录的 2 条 pre-existing 失败可接受）— Task 9.5 执行。
9. **版本号 bump + tag**：0.3.19 → 0.3.20，tag `v0.3.20-phase2-t9` — Task 9.4 执行。
10. **Continuity 推进**：status 改成 `Phase2-T9-COMPLETE · Phase2-T10-NOT-STARTED`，next_action 指向 T10 plan — Task 9.2-9.3 执行。

---

## 自检 · 与 spec 对齐

| Phase 2 验收（spec §14） | 本 plan 覆盖 | 备注 |
|---|---|---|
| V1: trend_digest 四维度具备稳定扩展图表和基础表格 | T3-T6 + T2 | 4 维度 × 2 secondary + 4 KPI 占位齐 |
| V2: 周/月/年 视角清晰的环比/同比/期初期末表达 | T1 + T3-T6（部分） | shape 全部到位；start_vs_end 实计；period_over_period / year_over_year shape 稳定但暂时 null（待 Phase 2 后续 task 扩展，本 T9 范围契约优先） |
| V3: HTML/Excel 趋势页主图、辅图、表格组合 | **不在 T9 范围**（T10） | T9 仅数据层；HTML/Excel 改动由 T10 落地 |
| V4: 没引入第二套 KPI / 趋势口径 / 模板侧重算 | T8 grep 门禁 | 含 kpis_v2 + metric_new_ + 模板绕过 trend_digest 三条门禁 |

**已知不完全覆盖项**：V2 的 period_over_period / year_over_year 留 shape 占位、值为 null。这是审慎决策（避免把 7-day window 强行扩成 14-day window 引入未知边界），后续 task 扩展数据窗口时再补；本 plan 不抢工作量。已在 Continuity carry-over 记录。

---

## 不在本 plan 范围

以下事项明确放在 T9 之外，prevent scope creep：

1. **HTML 模板渲染 secondary_charts**：T10 范围
2. **Excel `趋势数据` sheet 重写**：T10 范围
3. **邮件 `daily_report_email.html.j2` 任何改动**：T10 范围
4. **LLM prompt 提及 secondary_charts / comparison 数据**：T11 范围（且需先在 T10 落地稳定的展示后才能让 LLM 引用）
5. **period_over_period / year_over_year 实际数值计算**：留 shape，值为 null；待后续 task 扩展（需要把 labeled_reviews 查询窗口扩展到 2× / 13 月，带额外数据库读放大）
6. **stacked_bar / bar 在 Chart.js 渲染端的细分样式**：T9 共享 line builder；T10 模板侧落地时再细分

---

## 回滚预案

T9 全部产物向下兼容（trend_digest 子层只**加**字段、不**改**字段，模板/Excel 不消费新字段，所以未识别字段被自然忽略）。回滚步骤：

```bash
# 1. revert T9 commit 序列
git revert --no-commit v0.3.19-stage-b..v0.3.20-phase2-t9
git commit -m "revert: rollback Phase 2 T9 trend_digest 数据层扩展"

# 2. 删除 tag
git tag -d v0.3.20-phase2-t9

# 3. 版本号回退
# 手工把 pyproject.toml / __init__.py / uv.lock 改回 0.3.19
uv lock
git commit -am "chore: revert version 0.3.20 -> 0.3.19"
```

无需迁移任何 DB 字段（artifact 表 schema 0 改动）。
