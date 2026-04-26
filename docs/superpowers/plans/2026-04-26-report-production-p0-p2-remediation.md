# Report Production P0-P2 Remediation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复生产测试 4 暴露出的日报语义误导、全景热力图缺失、趋势页价格/库存不可见和趋势分析价值不足问题，让报告从用户视角能清楚区分“累计基线、本次入库、真实趋势”。

**Architecture:** 保持既有顶层契约稳定：`report_semantics` 仍只允许 `bootstrap | incremental`，`kpis`、`change_digest`、`trend_digest` 仍是 HTML / Excel / 邮件唯一展示输入。P0 只在现有字段内部补充展示上下文并修正文案；P1 恢复已经有数据但未渲染的图表；P2 在 `trend_digest.data[view][dimension]` 子层增强产品状态与趋势解释，不让模板绕过 `trend_digest` 读取 `_trend_series`。

**Tech Stack:** Python 3.10+, pytest, Jinja2, Chart.js config dict, openpyxl, Playwright/PDF 渲染链路。

**Entry Context:**
- 生产测试目录：`C:\Users\leo\Desktop\生产测试\报告\测试4`
- 当前关键发现：
  - run2 仍用“首次/监控起点”口吻，原因是 `detect_report_mode()` 要求最近 30 天至少 3 个 completed daily run 才切 incremental。
  - 总览 KPI 的 `自有评论` 是累计口径，但 tooltip 写成本期采集窗口。
  - Excel `评论明细.本次新增` 在 bootstrap 下只按发布时间标 `新近/补采`，无法区分本次 run 入库与历史累计行。
  - `_heatmap_data` 与 `charts.heatmap` 已存在，但 V3 模板没有渲染热力图。
  - T9 已生成 `secondary_charts`，包括产品价格趋势，但模板与 Excel 仍不消费。
  - 产品趋势缺少库存表达，且当前只选第一个有 2 个快照点的 SKU，业务价值偏弱。
  - `week/month/year` 实际是近 7 天 / 近 30 天 / 近 12 个月，名称误导。

---

## File Map

| File | Responsibility | Tasks |
|------|----------------|-------|
| `qbu_crawler/server/report_analytics.py` | 报告模式识别、`trend_digest` 构建、趋势维度数据和产品状态趋势增强 | T1, T6, T7 |
| `qbu_crawler/server/report_snapshot.py` | `change_digest` 的展示上下文、基线期状态、窗口/累计语义输入 | T1 |
| `qbu_crawler/server/report_common.py` | KPI 卡片标签、tooltip、竞品差距指数命名消歧、fallback 文案 | T2, T4 |
| `qbu_crawler/server/report_llm.py` | LLM prompt 与关系词对账继续加固，避免风险排序文案漂移 | T4 |
| `qbu_crawler/server/report_charts.py` | heatmap table payload、mixed-state secondary chart config 输出 | T5 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 今日变化基线期文案、KPI 标签展示、热力图、辅图、趋势标签 | T1, T2, T5, T6, T7 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | 邮件基线期文案与累计/本次口径修正 | T1, T2 |
| `qbu_crawler/server/report_templates/daily_report_v3.css` | heatmap、secondary charts、趋势状态表展示样式 | T5, T6, T7 |
| `qbu_crawler/server/report_templates/daily_report_v3.js` | 如需支持 table 型 chart 配置或辅图懒加载，在这里补最小逻辑 | T5 |
| `qbu_crawler/server/report.py` | Excel `评论明细`、`今日变化`、`趋势数据` 的口径与分块导出 | T3, T6, T8 |
| `tests/test_report_analytics.py` | mode / trend digest / 产品状态趋势单元回归 | T1, T6, T7 |
| `tests/test_report_snapshot.py` | change_digest 基线期、窗口口径、`window_review_ids` 全链路回归 | T1, T3 |
| `tests/test_report_common.py` | KPI 标签、tooltip、竞品差距命名回归 | T2, T4 |
| `tests/test_report_llm.py` | 风险排序关系词、prompt 口径回归 | T4 |
| `tests/test_report_charts.py` | heatmap table 与 secondary chart config 回归 | T5 |
| `tests/test_v3_html.py` | HTML 渲染回归：基线期、热力图、辅图、趋势标签 | T1, T5, T6 |
| `tests/test_v3_excel.py` / `tests/test_report_excel.py` | Excel 窗口归属与趋势数据分块回归 | T3, T8 |
| `tests/test_metric_semantics.py` | grep 门禁更新，禁止模板绕过 `trend_digest` | T5, T6, T8 |

---

## Chunk 1: P0 语义止血

### Task 1: 基线期展示上下文，不再把 run2 写成“首次”

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:493`
- Modify: `qbu_crawler/server/report_snapshot.py:409`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:145`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2:220`
- Modify: `qbu_crawler/server/report.py:1251`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_report_snapshot.py`
- Test: `tests/test_v3_html.py`
- Test: `tests/test_v3_excel.py`

- [ ] **Step 1.1: 写失败测试：baseline 第 2 天仍是 bootstrap，但展示为“基线建立期第2天”**

在 `tests/test_report_analytics.py` 增加测试，构造已有 1 个 completed daily run 的 DB 场景，断言：
- `mode == "baseline"`
- `report_semantics == "bootstrap"`
- `baseline_sample_days == 1`
- 新增展示字段表达当前是第 2 天，不能等同首次。

推荐新增字段放在 `mode_info` / analytics 内部已有上下文里：

```python
assert analytics["baseline_sample_days"] == 1
assert analytics["baseline_day_index"] == 2
assert analytics["baseline_display_state"] == "building"
```

不要把 `report_semantics` 改成第三种值；AGENTS 当前约束要求它仍只允许 `bootstrap | incremental`。

- [ ] **Step 1.2: 跑测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py::test_baseline_second_run_exposes_building_display_state -v`

Expected: FAIL，当前没有 `baseline_day_index` / `baseline_display_state`。

- [ ] **Step 1.3: 最小实现 mode 展示上下文**

在 `detect_report_mode()` 返回值里增加：
- `baseline_day_index = baseline_sample_days + 1`
- `baseline_display_state = "initial"` if day index == 1 else `"building"`

保持：

```python
"mode": "incremental" if baseline_sample_days >= 3 else "baseline"
```

即 P0 不改变 3 天切 incremental 的策略，只修“第 2 天仍说首次”的用户误导。

- [ ] **Step 1.4: 让 `build_change_digest()` 携带展示上下文**

在 `change_digest.summary` 中补：
- `baseline_day_index`
- `baseline_display_state`
- `window_meaning`

建议语义：
- bootstrap initial：`window_meaning = "首次建档，当前结果用于建立监控基线"`
- bootstrap building：`window_meaning = "基线建立期第N天，本次入库用于补足基线，不按今日新增解释"`
- incremental：`window_meaning = "增量监控期，本区块聚焦本次运行变化"`

- [ ] **Step 1.5: 修改 HTML / 邮件 / Excel 文案**

将以下固定文案替换成基于 `change_digest.summary.baseline_day_index` 的文案：
- HTML 今日变化 callout：`监控起点` / `首次建档/基线切面`
- 邮件 fallback：`首次基线已完成`
- Excel 今日变化 sheet 状态说明：`首次建档，当前结果用于建立监控基线。`

目标输出：
- day 1：`监控起点`
- day 2/3：`基线建立期第2天` / `基线建立期第3天`
- day >=4 incremental：现有 `今日变化`

- [ ] **Step 1.6: 增加 HTML / Excel 回归**

`tests/test_v3_html.py`：
- bootstrap + `baseline_day_index=2` 时，HTML 包含 `基线建立期第2天`
- 不包含 `首次建档`
- 不包含 `今日新增`

`tests/test_v3_excel.py`：
- `今日变化` sheet bootstrap day2 包含 `基线建立期第2天`
- 不包含 `首次建档`

- [ ] **Step 1.7: 运行相关测试**

Run:

```bash
uv run pytest tests/test_report_analytics.py tests/test_report_snapshot.py tests/test_v3_html.py tests/test_v3_excel.py -k "baseline or bootstrap or change_digest or 今日变化" -v
```

Expected: PASS。

---

### Task 2: 总览 KPI 与 tooltip 明确“累计”口径

**Files:**
- Modify: `qbu_crawler/server/report_common.py:52`
- Modify: `qbu_crawler/server/report_common.py:968`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2:70`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:117`
- Test: `tests/test_report_common.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 2.1: 写失败测试：KPI 卡片不得把累计评论解释成本期窗口**

在 `tests/test_report_common.py` 增加测试，调用 `normalize_deep_report_analytics()`，断言：
- KPI 卡片标签是 `累计自有评论`，不是 `自有评论`
- KPI 或总览摘要中能看到 `累计竞品评论`
- KPI 或总览摘要中能看到 `本次入库评论`
- KPI 或总览摘要中能看到 `近30天评论`
- tooltip 包含 `累计入库`
- tooltip 不包含 `本期采集窗口`

- [ ] **Step 2.2: 修改 KPI label 和 tooltip**

建议修改：
- `METRIC_TOOLTIPS["自有评论"]` 改成 `累计入库的自有产品评论行数，包含历史补采；本次入库请看“今日变化/本次入库评论”。`
- KPI 卡片 label 从 `自有评论` 改为 `累计自有评论`
- 在总览 KPI 或紧邻 KPI 的摘要区显式展示四类评论指标：
  - `累计自有评论`：来自 `analytics.kpis.own_review_rows`
  - `累计竞品评论`：来自 `analytics.kpis.competitor_review_rows`
  - `本次入库评论`：来自 `analytics.change_digest.summary.ingested_review_count`
  - `近30天评论`：优先来自 `analytics.kpis.recently_published_count`，如缺失则用 `change_digest.summary.fresh_review_count` 兜底
- 如保留 tooltip key 为 `自有评论`，只改展示 label，不引入第二套 KPI key。

邮件首屏：
- `自有评论` 改 `累计自有评论`
- 增加或调整摘要，使邮件首屏也能区分 `累计竞品评论`、`本次入库评论`、`近30天评论`。

报告口径区：
- `自有产品 X · Y 条评论` 改 `自有产品 X · 累计评论 Y 条`
- `竞品 X · Y 条评论` 改 `竞品 X · 累计评论 Y 条`

- [ ] **Step 2.3: 增加 HTML 回归**

`tests/test_v3_html.py` 断言总览 HTML：
- 包含 `累计自有评论`
- 包含 `累计竞品评论`
- 包含 `本次入库评论`
- 包含 `近30天评论`
- 包含 `累计评论`
- 不出现 `本期采集窗口内入库的自有产品评论行数`

- [ ] **Step 2.4: 运行测试**

Run:

```bash
uv run pytest tests/test_report_common.py tests/test_v3_html.py -k "kpi or tooltip or cumulative" -v
```

Expected: PASS。

---

### Task 3: Excel 评论明细从“本次新增”改成“窗口归属”

**Files:**
- Modify: `qbu_crawler/server/report.py:1076`
- Modify: `qbu_crawler/server/report.py:1136`
- Test: `tests/test_v3_excel.py`
- Test: `tests/test_report_excel.py`
- Test: `tests/test_report_snapshot.py`
- Test: `tests/test_metric_semantics.py`

- [ ] **Step 3.1: 写失败测试：bootstrap 下能区分本次入库和历史累计**

在 `tests/test_v3_excel.py` 增加场景：
- analytics 为 `bootstrap`
- `window_review_ids=[2]`
- reviews 有 id=1 和 id=2
- id=1 发布时间近 30 天但不在 window
- id=2 发布时间近 30 天且在 window

断言：
- 表头包含 `窗口归属`
- id=1 值为 `历史累计·新近`
- id=2 值为 `本次入库·新近`

- [ ] **Step 3.2: 修改表头**

将 governed Excel 的表头：

```python
"ID", "本次新增", ...
```

改成：

```python
"ID", "窗口归属", ...
```

不要再使用“新增”作为列名。

- [ ] **Step 3.3: 修改 `_review_new_flag()` 语义**

建议返回值：

| report_semantics | review id in `window_review_ids` | 发布时间近 30 天 | 返回 |
|---|---:|---:|---|
| bootstrap | yes | yes | `本次入库·新近` |
| bootstrap | yes | no | `本次入库·补采` |
| bootstrap | no | yes | `历史累计·新近` |
| bootstrap | no | no | `历史累计·补采` |
| incremental | yes | any | `本次入库` |
| incremental | no | any | `历史累计` |

这样 run2 不会再把累计 593 条都看成“本次新增”。

- [ ] **Step 3.4: 更新既有断言**

搜索并更新测试里对 `本次新增` / `新增` / `新近` / `补采` 的旧断言。

Run:

```bash
rg -n "本次新增|新增|新近|补采" tests/test_v3_excel.py tests/test_report_excel.py tests/test_report_integration.py
```

- [ ] **Step 3.5: 增加 full report 到 Excel 的窗口 ID 集成测试**

当前数据库没有 `reviews.run_id`，窗口归属依赖：
`workflow_runs.data_since/data_until` → `freeze_report_snapshot()` 的窗口 reviews → `analytics.window_review_ids` → `generate_excel()`。

在 `tests/test_report_snapshot.py` 增加集成测试，覆盖：
- snapshot 有 `reviews` 2 条，`cumulative.reviews` 4 条。
- 只有窗口 reviews 的 id 被写入 `analytics["window_review_ids"]`。
- 调用 `generate_full_report_from_snapshot()` 时传给 `report.generate_excel()` 的 analytics 保留 `window_review_ids`。
- Excel 输入 reviews 使用 cumulative reviews，而不是只用窗口 reviews。

断言示例：

```python
assert captured["analytics"]["window_review_ids"] == [2, 4]
assert [r["id"] for r in captured["reviews"]] == [1, 2, 3, 4]
```

这样可以防止 `窗口归属` 只在单元测试里成立，真实 full report 链路却丢失本次窗口 ID。

- [ ] **Step 3.6: 清理或同步旧 Excel 生成函数，增加 `本次新增` 残留门禁**

当前 `qbu_crawler/server/report.py` 中存在两个 `_generate_analytical_excel` 定义；运行时以后一个为准，但前一个仍残留旧 `本次新增` 逻辑。执行时必须二选一：
- 删除前一个死代码定义；或
- 将两个定义都同步成 `窗口归属`，并在后续单独清理重复定义。

在 `tests/test_metric_semantics.py` 增加 grep 门禁：

```python
offending, _ = _git_grep(repo_root, "本次新增", ["qbu_crawler/server/report.py", "qbu_crawler/server/report_templates/"])
assert not offending
```

允许测试文件和历史文档出现 `本次新增`，但生产代码和模板不允许再出现用户可见的旧列名。

- [ ] **Step 3.7: 运行 Excel 测试**

Run:

```bash
uv run pytest tests/test_v3_excel.py tests/test_report_excel.py tests/test_report_integration.py tests/test_report_snapshot.py tests/test_metric_semantics.py -k "excel or 评论明细 or 窗口归属 or window_review_ids or 本次新增" -v
```

Expected: PASS。

---

### Task 4: LLM 文案与竞品差距指数口径对账

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:317`
- Modify: `qbu_crawler/server/report_llm.py:520`
- Modify: `qbu_crawler/server/report_common.py:563`
- Modify: `qbu_crawler/server/report_common.py:1006`
- Test: `tests/test_report_llm.py`
- Test: `tests/test_report_common.py`

- [ ] **Step 4.1: 写失败测试：风险 Top 文案必须绑定 `risk_products[0]`**

在 `tests/test_report_llm.py` 增加测试：
- `risk_products[0] = A，risk_score=35`
- `risk_products[1] = B，risk_score=29`
- LLM 输出里写 `B 风险最高`

断言 `_check_relation_claims()` 返回 violation，`generate_report_insights()` fallback。

现有 `_check_relation_claims()` 已有基础实现，本任务重点补边界词：
- `核心风险`
- `首要风险`
- `重点风险`
- `最值得优先`

- [ ] **Step 4.2: 增强关系词检测词表和测试**

扩展 `_RELATION_TOP_WORDS`，并确保：
- 命中非 top SKU + top 词时 fallback
- 文案同时提到 top SKU 和非 top SKU 时不误杀
- 不含比较关系词时不误杀

- [ ] **Step 4.3: 竞品差距指数命名消歧**

当前总览 KPI `competitive_gap_index` 与 gap_analysis 行级 `gap_rate` 都叫“差距指数”。修改显示文案：
- 总览 KPI：`总体竞品差距指数`
- gap_analysis / prompt 行：`维度差距指数`

不要改字段名，只改 label / tooltip / prompt 文案。

- [ ] **Step 4.4: 增加测试**

`tests/test_report_common.py`：
- KPI 卡片 label 包含 `总体竞品差距指数`
- tooltip 说明是跨维度平均

`tests/test_report_llm.py`：
- prompt 中 gap 行使用 `维度差距指数`
- prompt 中总体指标如出现则叫 `总体竞品差距指数`

- [ ] **Step 4.5: 运行测试**

Run:

```bash
uv run pytest tests/test_report_llm.py tests/test_report_common.py -k "relation or risk or gap or 差距" -v
```

Expected: PASS。

---

## Chunk 2: P1 展示缺失恢复

### Task 5: 恢复全景数据“特征情感热力图”

**Files:**
- Modify: `qbu_crawler/server/report_charts.py:765`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:495`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css:1178`
- Test: `tests/test_report_charts.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 5.1: 写失败测试：HTML 渲染 heatmap table**

在 `tests/test_v3_html.py` 增加测试，构造：

```python
charts = {
    "heatmap": {
        "type": "table",
        "x_labels": ["质量", "结构"],
        "y_labels": ["SKU-A", "SKU-B", "SKU-C"],
        "z": [[0.8, -0.2], [0.1, 0.5], [-0.7, 0.0]],
    }
}
```

断言 HTML：
- 包含 `特征情感热力图`
- 包含 `heatmap-table`
- 包含 `SKU-A`
- 不把 heatmap 渲染成 `<canvas>`

- [ ] **Step 5.2: 让 heatmap payload 更适合模板**

在 `_chartjs_heatmap_table()` 保留现有 `x_labels/y_labels/z`，可选增加 `rows`：

```python
"rows": [
    {"label": y_label, "values": [{"label": x_label, "value": z_value, "tone": "..."}]}
]
```

如果为了最小改动，也可以直接在 Jinja 中按 `y_labels` + `z` 渲染，不强制新增 `rows`。

- [ ] **Step 5.3: 在全景数据区渲染 table**

在 `tab-panorama` 的评分分布图后添加：
- `if charts.heatmap and charts.heatmap.type == "table"`
- 使用 `.heatmap-container` / `.heatmap-table` / `.heatmap-cell`
- 单元格显示数值，颜色表达正负：正向偏绿，负向偏红，0 偏灰。

不要改成 canvas；`daily_report_v3.js` 当前只初始化 `canvas[data-chart-config]`，table 不需要 JS。

- [ ] **Step 5.4: 更新/新增 CSS**

现有 CSS 已有 `.heatmap-container` / `.heatmap-table` / `.heatmap-cell`。只补必要的：
- `.heatmap-cell-positive`
- `.heatmap-cell-negative`
- `.heatmap-cell-neutral`

- [ ] **Step 5.5: 运行测试**

Run:

```bash
uv run pytest tests/test_report_charts.py tests/test_v3_html.py -k "heatmap or panorama" -v
```

Expected: PASS。

---

### Task 6: 趋势页渲染 T9 已生成的 secondary charts，恢复价格趋势

**Files:**
- Modify: `qbu_crawler/server/report_charts.py:601`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:291`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`
- Modify: `tests/test_metric_semantics.py:422`
- Test: `tests/test_report_charts.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 6.1: 写失败测试：mixed-state 下 ready secondary chart 也能生成 config**

在 `tests/test_report_charts.py` 增加测试：
- `payload.status = "accumulating"`
- `payload.secondary_charts[1].status = "ready"`
- 断言 `build_chartjs_configs()` 仍输出 `trend_month_products_secondary_1`

当前 `build_chartjs_configs()` 顶层有：

```python
if payload.get("status") != "ready":
    continue
```

所以测试应先失败。

- [ ] **Step 6.2: 修改 chart config 生成逻辑**

移除“整块 status != ready 就 continue”的顶层跳过，改成：
- primary chart 独立判断 `primary_chart.status == "ready"`
- secondary chart 独立判断 `sec_chart.status == "ready"`

这样产品趋势主图积累中时，价格趋势如果 ready 也能展示。

- [ ] **Step 6.3: 更新 T9 grep 门禁**

`tests/test_metric_semantics.py::test_phase2_t9_template_does_not_consume_secondary_charts_yet` 已经不适用于 T10/P1。

替换为：
- 模板允许消费 `secondary_charts`
- 仍禁止模板直接读 `analytics._trend_series` / `analytics.window` / `cumulative_kpis`
- 断言 secondary charts 的模板读取路径必须是 `trend_block.secondary_charts`

- [ ] **Step 6.4: 在趋势模板中渲染辅图**

在主图之后、表格之前增加：
- 遍历 `trend_block.secondary_charts`
- `chart_key = "trend_" ~ view ~ "_" ~ dimension ~ "_secondary_" ~ loop.index0`
- ready 且 key in `charts` 时渲染 canvas
- accumulating 时渲染小型 placeholder，例如 `价格趋势数据积累中`
- 增加 `_secondary_ready`，并纳入趋势块整体空态判断：

```jinja2
{% set _secondary_ready = false %}
{% for sec_chart in trend_block.secondary_charts or [] %}
  {% set sec_key = "trend_" ~ view ~ "_" ~ dimension ~ "_secondary_" ~ loop.index0 %}
  {% if sec_chart.status == "ready" and sec_key in charts %}
    {% set _secondary_ready = true %}
  {% endif %}
{% endfor %}
```

整体空态判断必须从：

```jinja2
not (_kpi_ready or _chart_ready or _table_ready)
```

改成：

```jinja2
not (_kpi_ready or _chart_ready or _table_ready or _secondary_ready)
```

防止“主图/表格仍在积累，但价格辅图已 ready”的 mixed-state 被整块空态吞掉。

建议容器：
- `.trend-secondary-grid`
- `.trend-secondary-chart`

- [ ] **Step 6.5: 写 HTML 回归**

`tests/test_v3_html.py`：
- 构造 `month/products.secondary_charts[1].title = "重点 SKU 价格 - X"`
- charts 包含 `trend_month_products_secondary_1`
- 断言 HTML 包含 `重点 SKU 价格 - X`
- 断言有 `trend-secondary-grid`
- 增加 mixed-state 场景：
  - `trend_kpis.status = "accumulating"`
  - `primary_chart.status = "accumulating"`
  - `table.status = "accumulating"`
  - `secondary_charts[1].status = "ready"`
  - 断言 HTML 仍渲染 `重点 SKU 价格 - X`，且不显示整块 `trend-status` 空态。

- [ ] **Step 6.6: 运行测试**

Run:

```bash
uv run pytest tests/test_report_charts.py tests/test_v3_html.py tests/test_metric_semantics.py -k "secondary or trend_digest or template" -v
```

Expected: PASS。

---

## Chunk 3: P2 趋势体系重设

**P2 设计原则：**
- `sentiment` / `issues` / `competition` 使用评论发布时间 `date_published(_parsed)`，它们表达的是“用户反馈发生时间分布”，不是爬虫每日运行趋势。
- `products` 使用产品快照时间 `scraped_at`，它表达的是“每日任务实际监控到的产品状态变化”，价格和库存只能放在这里。
- 每个维度都必须回答一个业务问题：是否变热、问题在哪里、商品状态有没有变、竞品对比是否足够可信。不能只为了“有图”而展示低价值指标。
- 样本不足时必须降级为 `accumulating` 或给出样本说明，禁止生成“上涨/下滑/领先/恶化”等强趋势结论。

### Task 7: 趋势视角和维度重命名，明确评论时间轴与产品快照时间轴

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1341`
- Modify: `qbu_crawler/server/report_analytics.py:2196`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:33`
- Modify: `qbu_crawler/server/report.py:1340`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_v3_html.py`
- Test: `tests/test_v3_excel.py`

- [ ] **Step 7.1: 写失败测试：视角显示名必须是“近7天/近30天/近12个月”**

`tests/test_v3_html.py` 断言：
- HTML 包含 `近7天`
- HTML 包含 `近30天`
- HTML 包含 `近12个月`
- 不出现趋势切换按钮文本 `周` / `月` / `年`

注意：内部 key 仍保留 `week/month/year`，不改 schema。

- [ ] **Step 7.2: 修改模板标签**

将：

```jinja2
{"week": "周", "month": "月", "year": "年"}
```

改为：

```jinja2
{"week": "近7天", "month": "近30天", "year": "近12个月"}
```

将维度显示名改为：
- `sentiment`: `评论声量与情绪`
- `issues`: `问题结构`
- `products`: `产品状态`
- `competition`: `竞品对标`

内部 dimension key 不改。

- [ ] **Step 7.3: trend_digest 增加数据口径说明**

在 `trend_digest` 内增加 `dimension_notes`，不要新增第二套趋势结构：

```python
"dimension_notes": {
    "sentiment": "基于评论发布时间 date_published 聚合，反映用户反馈发生时间。",
    "issues": "基于评论发布时间和问题标签聚合，反映问题声量结构。",
    "products": "基于产品快照 scraped_at 聚合，反映每日采集到的价格、库存、评分、评论总数状态。",
    "competition": "基于可比样本聚合；样本不足时仅展示截面差异，不做强趋势判断。",
}
```

- [ ] **Step 7.4: 模板展示当前维度说明**

在 trend panel header 中显示对应 `dimension_notes[dimension]`。避免用户把产品趋势和评论发布时间趋势混成同一个时间轴。

- [ ] **Step 7.5: 定义四维度指标价值契约**

在计划执行时同步检查并固化四个维度的 KPI / 主图 / 辅图 / 表格语义。内部字段仍沿用 `sentiment/issues/products/competition`，但展示名和业务问题按下表执行：

| dimension | 展示名 | 时间轴 | 必须回答的问题 | KPI 最低要求 | 主图 | 辅图 | 表格 |
|---|---|---|---|---|---|---|---|
| `sentiment` | 评论声量与情绪 | `date_published` | 用户反馈在近 7/30 天或近 12 个月是否变热，情绪结构是否恶化 | 评论量、近30天业务新增、自有差评率、健康分 | 评论声量 + 自有差评率 | 差评率、健康分 | 按时间桶列出评论量、差评量、好评量、健康分 |
| `issues` | 问题结构 | `date_published` | 当前最集中的问题是什么，影响多少 SKU，是否只是历史补采堆积 | 问题信号数、活跃问题数、头号问题、涉及产品数 | Top 问题声量 | Top3 问题堆叠、影响 SKU 数 | Top 问题、评论数、影响 SKU、严重度 |
| `products` | 产品状态 | `scraped_at` | 每日任务实际监控到哪些商品状态变化，价格/库存/评分/评论总数有没有变 | 跟踪产品数、有快照产品数、状态变化 SKU 数、快照点数 | 重点 SKU 评分 + 评论总数 | 重点 SKU 价格、评论总数 | 当前价格、当前库存、价格变化次数、库存变化次数、最近变化 |
| `competition` | 竞品对标 | `date_published` + 样本门槛 | 自有和竞品是否有足够可比样本，差距是否能可信表达 | 可比样本数、评分差、好评率差、样本状态 | 自有 vs 竞品平均评分 | 评分差、好评率差 | 时间桶、自有样本、竞品样本、评分差、好评率差 |

降级规则：
- 单个时间桶样本不足时，该桶仍可显示原始计数，但不计算百分比结论。
- 整个维度样本不足时，`status` 为 `accumulating`，KPI 用占位或样本计数，不输出趋势判断。
- `competition` 只有自有和竞品同时有样本时才显示对比趋势；否则显示“可比样本不足”，不做领先/落后判断。

- [ ] **Step 7.6: 写失败测试：四维度都有业务价值契约**

`tests/test_report_analytics.py` 增加测试，调用 `_build_trend_digest()` 后断言：
- `dimension_notes` 四个 key 齐全。
- 每个 `data[view][dimension]` 都有 4 个 KPI item。
- `sentiment/issues/competition` 的 note 包含 `date_published`。
- `products` 的 note 包含 `scraped_at`、`价格`、`库存`。
- `competition` 的 `status_message` 或 note 在样本不足时包含 `可比样本不足`。

- [ ] **Step 7.7: 写失败测试：模板和 Excel 使用新展示名**

`tests/test_v3_html.py`：
- 断言 HTML 包含 `评论声量与情绪 / 问题结构 / 产品状态 / 竞品对标`。
- 断言 HTML 包含 `近7天 / 近30天 / 近12个月`。
- 断言 HTML 不出现趋势切换按钮文本 `周` / `月` / `年`。

`tests/test_v3_excel.py`：
- `趋势数据` sheet 分块标题使用 `近30天 / 产品状态`，而不是 `month / products`。
- `趋势数据` sheet 包含维度口径说明，至少能看到 `date_published` 和 `scraped_at`。

- [ ] **Step 7.8: 测试 `trend_digest` 契约**

`tests/test_report_analytics.py`：
- 断言 `dimension_notes` 存在
- 断言 products note 包含 `scraped_at`
- 断言 sentiment note 包含 `date_published`

Run:

```bash
uv run pytest tests/test_report_analytics.py tests/test_v3_html.py tests/test_v3_excel.py -k "trend or view label or dimension_notes or 趋势数据" -v
```

Expected: PASS。

---

### Task 8: 产品状态趋势补足价格、库存、选择逻辑和 Excel 分块

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1840`
- Modify: `qbu_crawler/server/report_analytics.py:1915`
- Modify: `qbu_crawler/server/report.py:1340`
- Modify: `tests/test_metric_semantics.py:435`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_v3_excel.py`
- Test: `tests/test_report_excel.py`

- [ ] **Step 8.1: 写失败测试：产品状态表必须包含价格与库存字段**

`tests/test_report_analytics.py` 构造 `trend_series`：
- SKU-A 有 3 个点，price 有变化，stock_status 从 `in_stock` 到 `out_of_stock`
- SKU-B 有 2 个点，无变化

断言 `data["month"]["products"]["table"]["columns"]` 包含：
- `当前价格`
- `当前库存`
- `价格变化次数`
- `库存变化次数`
- `最近库存变化`

- [ ] **Step 8.2: 写失败测试：重点 SKU 选择优先有状态变化的 SKU**

当前逻辑选第一个有 2 个快照点的 SKU。新增测试断言：
- SKU-A 有价格/库存变化但排序在 SKU-B 后面
- `_build_product_trend()` 仍选择 SKU-A 作为主图/辅图重点 SKU

建议评分规则：
- 有库存变化 +5
- 有价格变化 +4
- 有评分变化 +3
- 快照点数每点 +1
- 若能拿到风险 SKU 排序，可作为后续增强；本任务先不强依赖 risk_products，避免跨层耦合。

- [ ] **Step 8.3: 实现产品状态表增强**

在 `_build_product_trend()` 的 rows 里补：
- latest price
- latest stock_status
- price_change_count
- stock_change_count
- latest_stock_change，例如 `2026-04-26: in_stock -> out_of_stock`

保持 existing columns 仍能兼容，只追加列。

- [ ] **Step 8.4: 实现产品重点 SKU 选择 helper**

新增内部 helper：

```python
def _score_product_trend_series(points):
    ...
```

只在 `report_analytics.py` 内使用，不暴露公共 API。

注意 AGENTS 约束：不要过度抽象。这里 helper 有明确复用价值：测试独立、选择逻辑可读。

- [ ] **Step 8.5: 库存趋势表达方式**

不要把库存做成连续折线。本任务的硬契约是：
- 库存只进入 `trend_block.table`，展示 `当前库存`、`库存变化次数`、`最近库存变化`。
- `secondary_charts` 不承载库存状态，避免把离散状态伪装成连续数值。
- 如果后续要可视化库存，只能另开任务做离散状态条或事件表，不在本轮实现。

`tests/test_report_analytics.py` 增加断言：
- `products.secondary_charts` 的 title 不包含 `库存`。
- `products.table.rows` 至少一行包含 `当前库存` 对应值和 `库存变化次数`。

- [ ] **Step 8.6: Excel `趋势数据` 改为按 trend_digest 分块**

当前 Excel 只平铺 `_trend_series`，用户看不到趋势页的主图/辅图语义。

新结构建议：
- Sheet 顶部保留原始产品快照明细区，标题 `产品快照明细`，该区允许消费既有 `_trend_series`，只用于明细审计。
- 追加分块：
  - `近30天 / 评论声量与情绪 / KPI`
  - `近30天 / 问题结构 / KPI`
  - `近30天 / 产品状态 / KPI`
  - `近30天 / 产品状态 / 主图`
  - `近30天 / 产品状态 / 辅图：重点 SKU 价格`
  - `近30天 / 产品状态 / 表格`
  - `近30天 / 竞品对标 / KPI`
- 对所有 `view × dimension` 循环导出，但空块只写状态说明，不写大量空行。

严禁 Excel 直接重算趋势；只能消费 `analytics.trend_digest` 和既有 `_trend_series` 的明细区。

- [ ] **Step 8.7: 更新 Excel 测试**

`tests/test_v3_excel.py`：
- `趋势数据` sheet 包含 `近30天 / 评论声量与情绪`
- `趋势数据` sheet 包含 `近30天 / 问题结构`
- `趋势数据` sheet 包含 `近30天 / 产品状态`
- `趋势数据` sheet 包含 `近30天 / 竞品对标`
- 包含 `重点 SKU 价格`
- 包含 `库存变化次数`
- 包含 `产品快照明细`

`tests/test_metric_semantics.py`：
- Excel 允许 `trend_digest`
- 模板仍禁止 `analytics._trend_series`
- 如果 Excel 保留 `_trend_series` 明细区，grep 门禁不要把 `report.py` 中的 `_trend_series` 全禁掉，但要求其只出现在 `产品快照明细` 导出函数附近。
- 模板不得直接使用 `_trend_series`，所有趋势展示只能来自 `trend_digest`。

- [ ] **Step 8.8: 运行测试**

Run:

```bash
uv run pytest tests/test_report_analytics.py tests/test_v3_excel.py tests/test_report_excel.py tests/test_metric_semantics.py -k "products or stock or price or 趋势数据 or trend_digest" -v
```

Expected: PASS。

---

## Chunk 4: 验收与生产产物回归

### Task 9: 全量报告回归和测试 4 产物复核

**Files:**
- No production code changes unless earlier tasks reveal a failing assertion.
- Optional update: `docs/devlogs/D020-report-production-p0-p2-remediation.md`
- Optional update: `docs/reviews/2026-04-24-report-upgrade-continuity.md`

- [ ] **Step 9.1: 运行报告相关测试集**

Run:

```bash
uv run pytest tests/test_metric_semantics.py tests/test_report_analytics.py tests/test_report_charts.py tests/test_report_common.py tests/test_report_llm.py tests/test_report_snapshot.py tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_excel.py tests/test_report_integration.py -v
```

Expected: PASS。

- [ ] **Step 9.2: grep 语义门禁**

Run:

```bash
rg -n "今日新增|今日暴增|较昨日|较上期|首次建档|首次基线" qbu_crawler/server/report_templates qbu_crawler/server/report_common.py qbu_crawler/server/report_llm.py qbu_crawler/server/report.py
```

Expected:
- `今日新增|今日暴增|较昨日|较上期` 不应在 bootstrap 主路径文案中出现。
- `首次建档|首次基线` 只允许出现在 day1 initial 分支或测试说明中，不允许作为 bootstrap day2/day3 默认文案。

- [ ] **Step 9.3: 用测试 4 生产产物做人工验收**

对 `C:\Users\leo\Desktop\生产测试\报告\测试4` 重新生成或复制对照报告，检查：
- run2 HTML 今日变化区显示 `基线建立期第2天`
- run2 HTML 不再说 `首次建档`
- 总览 KPI 明确 `累计自有评论`
- Excel `评论明细` 表头为 `窗口归属`
- Excel 中 run2 的本次 32 条能和历史累计行区分
- 全景数据显示 `特征情感热力图`
- 变化趋势 / 产品状态 能看到 `重点 SKU 价格`
- 产品状态表显示库存字段
- 趋势切换按钮为 `近7天 / 近30天 / 近12个月`

- [ ] **Step 9.4: PDF/HTML 视觉 smoke**

如果本地 Playwright 可用：

```bash
uv run playwright install chromium
uv run pytest tests/test_report_pdf.py -v
```

如果没有专用 PDF 测试，则至少打开 HTML 检查：
- 热力图表格不溢出页面
- secondary charts 不导致趋势页过长或打印遮挡
- 移动宽度下 heatmap 有横向滚动

- [ ] **Step 9.5: 文档记录**

如果代码已执行到这个计划末尾，新增 devlog：

`docs/devlogs/D020-report-production-p0-p2-remediation.md`

记录：
- 本轮修复的问题
- 口径约束：累计 / 本次入库 / 近30天业务新增 / 产品快照趋势
- 测试命令和结果
- 生产测试 4 复核结论

---

## Execution Order

1. **T1-T3 先做**：这是 P0，直接解决用户误读风险。
2. **T4 可与 T2 后半并行，但建议同一人收口文案口径**：避免 KPI 和 LLM 说法再次分裂。
3. **T5-T6 再做**：恢复已存在数据的展示，风险低，用户可立即看到热力图和价格趋势。
4. **T7-T8 最后做**：这是 P2，涉及趋势体系和 Excel 结构，回归面最大。
5. **T9 必做**：没有真实产物复核，不算完成。

---

## Acceptance Criteria

- run2 这类 baseline building 报告不再展示为“首次/首日”，而是“基线建立期第 N 天”。
- 总览累计 KPI 与本次入库 KPI 标签清晰分离。
- Excel 评论明细不再使用“本次新增”，改为“窗口归属”，且能区分本次入库与历史累计。
- 全景数据恢复特征情感热力图。
- 趋势页能渲染 T9 已生成的 secondary charts，产品价格趋势可见。
- 产品状态趋势包含价格和库存状态，库存以状态表/变化次数表达，不伪装成连续折线。
- 趋势视角显示为 `近7天 / 近30天 / 近12个月`。
- 趋势维度显示为 `评论声量与情绪 / 问题结构 / 产品状态 / 竞品对标`。
- 四个趋势维度都有明确业务问题、4 个 KPI、主图/辅图/表格契约；样本不足时降级说明，不输出强趋势判断。
- `sentiment/issues/competition` 明确是 `date_published` 时间轴，`products` 明确是 `scraped_at` 产品快照时间轴。
- `competition` 样本不足时只能展示“可比样本不足”，不能给出领先/落后结论。
- 模板仍然不绕过 `trend_digest` 直接消费 `analytics.window`、`analytics._trend_series`、`cumulative_kpis`。
- 报告相关 pytest 全绿，生产测试 4 产物人工复核通过。
