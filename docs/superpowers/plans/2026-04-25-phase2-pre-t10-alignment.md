# Phase 2 Pre-T10 Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在进入 T10 之前，先收口生产测试3暴露的两条数据/语义问题：统一 `competitive_gap_index` 的用户可见语义来源，并补齐 `products` 维度在 `accumulating` 路径下的 `secondary_charts` 占位，让 T10 只处理 HTML / Excel 阅读体验。

**Architecture:** 保持主线不变，继续沿 `2026-04-24-report-upgrade-continuity.md` 推进，但在 T10 前插入一个小型 alignment patch。该 patch 只动 `report_llm.py`、`report_analytics.py`、相关测试和文档；不改 `trend_digest` 顶层 schema，不改 HTML / Excel / 邮件模板，不提前做 T10 展示层工作。

**Tech Stack:** Python 3.10+, pytest, 现有 report analytics / llm pipeline

---

## Chunk 1: 语义收口

### Task 1: 把“竞品差距指数”收口为唯一用户可见来源

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:519-529,570-584`
- Test: `tests/test_report_llm.py`

**Why:** 生产测试3产物里，顶层 KPI / HTML 卡片显示的是 `competitive_gap_index = 5`，但 LLM `competitive_insight` 又把 `gap_analysis[*].gap_rate` 写成“差距指数 15 / 8 / 6”。这会让用户误以为系统同时存在多套“竞品差距指数”。

- [ ] **Step 1: 写失败测试，锁定 prompt 语义**

在 `tests/test_report_llm.py` 追加：

```python
def test_build_insights_prompt_reserves_competitive_gap_index_for_top_level_kpi():
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "competitive_gap_index": 5,
            "health_index": 96.2,
            "own_product_count": 5,
            "competitor_product_count": 3,
            "own_review_rows": 418,
            "competitor_review_rows": 143,
            "own_negative_review_rate": 0.074,
            "own_negative_review_rate_display": "7.4%",
        },
        "change_digest": {"summary": {}},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "gap_analysis": [
                {
                    "label_display": "做工与质量",
                    "competitor_positive_rate": 22.4,
                    "competitor_positive_count": 32,
                    "competitor_total": 143,
                    "own_negative_rate": 7.4,
                    "own_negative_count": 31,
                    "own_total": 418,
                    "gap_rate": 15,
                }
            ],
            "benchmark_examples": [],
        },
    }

    prompt = _build_insights_prompt(analytics)
    assert "竞品差距指数（总览KPI） 5" in prompt
    assert "维度差距值 15" in prompt
    assert "差距指数 15" not in prompt
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
uv run pytest tests/test_report_llm.py::test_build_insights_prompt_reserves_competitive_gap_index_for_top_level_kpi -v
```

Expected: FAIL，因为当前 prompt 里仍会把 `gap_rate` 直接写成“差距指数”。

- [ ] **Step 3: 最小实现，只改 LLM prompt 语义**

在 `qbu_crawler/server/report_llm.py`：

1. 在 gap summary 段落前增加顶层 KPI 明示：

```python
overall_gap_index = (analytics.get("kpis") or {}).get("competitive_gap_index")
overall_gap_line = (
    f"竞品差距指数（总览KPI） {overall_gap_index}"
    if overall_gap_index is not None else
    "竞品差距指数（总览KPI） 暂无"
)
```

2. 把 `gap_analysis` 行文从：

```python
f"差距指数 {g.get('gap_rate', 0)}"
```

改为：

```python
f"维度差距值 {g.get('gap_rate', 0)}"
```

3. 把 prompt instruction 中“必须引用差距指数和比率数据”改成更严格的约束：

```python
"只能把顶层 kpis.competitive_gap_index 称为“竞品差距指数”；"
"gap_analysis[*].gap_rate 只能称为“维度差距值”或“维度差距率”，"
"不得把维度值说成总览 KPI。"
```

- [ ] **Step 4: 跑目标测试确认通过**

Run:

```bash
uv run pytest tests/test_report_llm.py::test_build_insights_prompt_reserves_competitive_gap_index_for_top_level_kpi -v
```

Expected: PASS

- [ ] **Step 5: 跑 LLM 相关回归，确认没有误伤已有语义门禁**

Run:

```bash
uv run pytest tests/test_report_llm.py -v -k "competitive_gap_index or build_insights_prompt or relation or bootstrap_violation"
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tests/test_report_llm.py qbu_crawler/server/report_llm.py
git commit -m "修复报表：收口竞品差距指数语义"
```

---

### Task 2: 给 `products` 维度的 accumulating 路径补齐两张辅图占位

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1816-1955`
- Test: `tests/test_report_analytics.py`
- Optional verify: `tests/test_report_charts.py`

**Why:** 当前 `products` 维度在 `ready` 路径下已经会产出 2 条 `secondary_charts`，但一旦 `ready_series is None` 就直接返回空列表，导致生产测试3里的 `week/month/year × products` 三块都只剩 KPI + 表，不再满足 T9 详细计划里“每块至少 2 条辅图 schema”的对称目标。

- [ ] **Step 1: 写失败测试，锁定 accumulating 路径下的辅图占位**

在 `tests/test_report_analytics.py` 追加：

```python
def test_product_trend_accumulating_path_emits_two_secondary_chart_placeholders():
    from qbu_crawler.server.report_analytics import _build_product_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    snapshot_products = [
        {
            "sku": "A1",
            "name": "Prod A",
            "ownership": "own",
            "rating": 4.2,
            "review_count": 200,
            "scraped_at": "2026-04-24T08:00:00+08:00",
        }
    ]
    trend_series = [
        {
            "product_sku": "A1",
            "series": [
                {"date": "2026-04-23", "rating": 4.2, "review_count": 200, "price": 95.0},
            ],
        }
    ]

    result = _build_product_trend("month", logical_day, trend_series, snapshot_products)

    assert result["status"] == "accumulating"
    secondary = result["secondary_charts"]
    assert len(secondary) == 2
    assert [chart["status"] for chart in secondary] == ["accumulating", "accumulating"]
    assert secondary[0]["labels"] == []
    assert secondary[0]["series"] == []
    assert secondary[1]["labels"] == []
    assert secondary[1]["series"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
uv run pytest tests/test_report_analytics.py::test_product_trend_accumulating_path_emits_two_secondary_chart_placeholders -v
```

Expected: FAIL，因为当前 accumulating 路径返回的还是 `secondary_charts=[]`。

- [ ] **Step 3: 最小实现，给 products 维度增加占位辅图 helper**

在 `qbu_crawler/server/report_analytics.py` 中：

1. 新增一个 products 专用 placeholder helper，例如：

```python
def _empty_product_secondary_charts():
    return [
        {
            "status": "accumulating",
            "chart_type": "line",
            "title": "重点 SKU 评论总数趋势",
            "labels": [],
            "series": [],
        },
        {
            "status": "accumulating",
            "chart_type": "line",
            "title": "重点 SKU 价格趋势",
            "labels": [],
            "series": [],
        },
    ]
```

2. 在 `_build_product_trend()` 的 `ready_series is None` 分支里，把：

```python
return _trend_dimension_payload(
    ...
    table={...},
)
```

改成：

```python
return _trend_dimension_payload(
    ...
    secondary_charts=_empty_product_secondary_charts(),
    table={...},
)
```

注意：

- 不要改 `trend_digest` 顶层结构
- 不要让 accumulating 的 placeholder 图提前变成 ready
- 不要顺手动 HTML / Excel / `report_charts.py`

- [ ] **Step 4: 跑目标测试确认通过**

Run:

```bash
uv run pytest tests/test_report_analytics.py::test_product_trend_accumulating_path_emits_two_secondary_chart_placeholders -v
```

Expected: PASS

- [ ] **Step 5: 跑 products / trend 相关回归**

Run:

```bash
uv run pytest tests/test_report_analytics.py -v -k "product_trend or trend_digest_blocks_all_have_phase2_schema or trend_dimensions_use_correct_time_field"
```

Expected: PASS

- [ ] **Step 6: 可选跑一条 Chart.js 防回归**

Run:

```bash
uv run pytest tests/test_report_charts.py -v -k "skips_secondary_when_block_not_ready"
```

Expected: PASS（products accumulating 仍不应在 T9 阶段生成展示层辅图配置）

- [ ] **Step 7: 提交**

```bash
git add tests/test_report_analytics.py qbu_crawler/server/report_analytics.py
git commit -m "修复报表：补齐产品趋势辅图占位"
```

---

## Chunk 2: 文档与收口

### Task 3: 更新 continuity / devlog，并做一轮 pre-T10 验证收口

**Files:**
- Modify: `docs/reviews/2026-04-24-report-upgrade-continuity.md`
- Modify: `docs/devlogs/D018-report-change-trend-governance.md`
- Reference only: `docs/reviews/2026-04-25-production-test3-phase1-phase2-alignment-review.md`

**Why:** 这次 patch 的目的不是另开新路线，而是把生产验证发现的问题收回 continuity 主线里。实现完成后，必须把“为什么先做这个 patch、做完后下一步是什么”写回 continuity，避免后续 session 又直接跳去 T10。

- [ ] **Step 1: 更新 continuity 当前指针**

在 `docs/reviews/2026-04-24-report-upgrade-continuity.md`：

1. 在“当前 Stage 指针”中把状态改成类似：

```text
status:         Phase2-T9-COMPLETE · PRE-T10-ALIGNMENT-COMPLETE · Phase2-T10-NOT-STARTED
next_action:    Phase 2 T10 implementation plan via superpowers:writing-plans (...)
blocked_by:     none
```

2. 在“进度日志”最上方追加一条 session，说明：

- 收口了 `competitive_gap_index` 的用户可见语义
- 补齐了 `products` 维度 accumulating 路径的 `secondary_charts` 占位
- T10 仍未开始，下一步才是 HTML + Excel 计划

3. 清理本次已经解决的 carry-over / 遗留项。

- [ ] **Step 2: 给 D018 追加一个短的 follow-up 小节**

在 `docs/devlogs/D018-report-change-trend-governance.md` 末尾增加一个短节，例如：

```md
## 2026-04-25 生产验证 follow-up

- 生产测试3确认 Phase 1 语义治理没有回退
- 但发现 `competitive_gap_index` 与 `gap_analysis.gap_rate` 在用户可见文案层混用
- 同时确认 `products` 维度在 accumulating 路径下丢失 `secondary_charts` 占位
- 本次 pre-T10 alignment patch 先收口这两个问题，确保 T10 只承担展示层工作
```

不要新建 `D019`，避免和 Continuity 中 T11 预留的 `D019-phase2-trend-deepening.md` 冲突。

- [ ] **Step 3: 跑一轮 pre-T10 最小验证**

Run:

```bash
uv run pytest tests/test_report_llm.py tests/test_report_analytics.py tests/test_report_charts.py -v -k "competitive_gap_index or build_insights_prompt or product_trend or skips_secondary_when_block_not_ready"
```

Expected: PASS

- [ ] **Step 4: 跑一轮更宽的报表回归**

Run:

```bash
uv run pytest tests/test_report_common.py tests/test_report_llm.py tests/test_report_analytics.py tests/test_report_charts.py tests/test_metric_semantics.py -v
```

Expected: PASS（若存在与本 patch 无关的 pre-existing 失败，需在 continuity 日志中明确标注，不得含糊带过）

- [ ] **Step 5: 提交**

```bash
git add docs/reviews/2026-04-24-report-upgrade-continuity.md docs/devlogs/D018-report-change-trend-governance.md
git commit -m "文档：推进 pre-T10 对齐收口状态"
```

---

## 非目标

这份 pre-T10 计划明确**不做**下面这些事：

1. 不改 `report_templates/daily_report_v3.html.j2/.js/.css`
2. 不改 `report.py` 的 Excel `趋势数据` sheet 渲染
3. 不改邮件模板
4. 不把 `period_over_period / year_over_year` 从 `null` 填成真实数值
5. 不在这个 patch 里重新定义 T10 的 mixed-state 展示策略

这些都留给后续的 T10 / T11 计划处理。

---

## 完成标准

1. `competitive_gap_index` 在用户可见语义层只剩一个来源：
   - 顶层 KPI / 卡片 / prompt 中的“竞品差距指数”只指 `kpis.competitive_gap_index`
   - `gap_analysis[*].gap_rate` 不再被 prompt 叫做“差距指数”
2. `products` 维度在 accumulating 路径下也有 2 条 `secondary_charts` placeholder
3. 不引入新的顶层 schema 变化
4. 不提前做 T10 的 HTML / Excel 工作
5. continuity 明确回到 “下一步写 T10 计划” 的主线

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-phase2-pre-t10-alignment.md`. Ready to execute?**
