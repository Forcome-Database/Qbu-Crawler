# 生产测试3产物对齐审查（Phase 1 ~ Phase 2）

**日期**：2026-04-25
**审查对象**：`C:\Users\leo\Desktop\生产测试\报告\测试3`
**产物范围**：
- `reports/workflow-run-1-analytics-2026-04-25.json`
- `reports/workflow-run-1-full-report.html`
- `reports/workflow-run-1-full-report.xlsx`
- `reports/workflow-run-1-snapshot-2026-04-25.json`

**对标文档**：
- `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md`
- `docs/reviews/2026-04-24-report-upgrade-execution-plan.md`
- `docs/reviews/2026-04-24-report-upgrade-continuity.md`
- `docs/superpowers/plans/2026-04-25-phase2-t9-trend-digest-extension.md`

---

## 1. 一句话结论

这批生产测试产物**整体符合当前阶段指针 `Phase2-T9-COMPLETE · Phase2-T10-NOT-STARTED`**，没有出现明显的 Phase 1 回退；但仍有 **2 个值得认定为“偏离/未收口”** 的点：

1. `competitive_gap_index` 仍未收敛为单一来源，顶层 KPI、`gap_analysis` 与 `report_copy` 仍在混用不同语义。
2. `products` 维度在 `trend_digest` 数据层没有补齐 T9 计划中承诺的 `secondary_charts`，对称性弱于 T9 实施计划。

除这两点外，其余主要差距大多属于 **T10 计划内未开始**，不应误判为回归。

---

## 2. 当前产物与阶段定位是否一致

### 2.1 与 Continuity 指针一致

当前 Continuity 明确写的是：

- `status: Phase2-T9-COMPLETE · Phase2-T10-NOT-STARTED`
- `next_stage: Phase 2 T10 · HTML + Excel 阅读体验`
- `blocked_by: T9 上线后跑 1 个 daily run 验证 trend_digest 扩展数据层产出无回归`

见 `docs/reviews/2026-04-24-report-upgrade-continuity.md:14-20`。

本次测试产物的表现与这一定义**大体一致**：

- `analytics` 中已经出现 T9 才会有的 `secondary_charts` / `comparison`
- HTML 和 Excel 仍未消费这些新字段
- `趋势数据` sheet 仍是旧式快照表，而不是 T10 目标里的按 `view × dimension` 分块结构

这意味着它更接近“**T9 数据层已落地，T10 展示层未开始**”的真实状态，而不是“Phase 2 已完成”。

### 2.2 与 T10 范围边界一致

执行编排文档对 T10 的定义是：

- HTML 模板增加辅图槽位
- Excel `趋势数据` sheet 按 `view × dimension` 分块重写
- **禁止动** `trend_digest` schema / analytics 层

见 `docs/reviews/2026-04-24-report-upgrade-execution-plan.md:120-130`。

本次产物中：

- HTML 全文未出现 `secondary_charts` 消费痕迹
- Excel `趋势数据` 仍只有 9 行、7 列的产品快照表

这两点都说明：**T10 还没做，不是回退，是阶段未到。**

---

## 3. 已对齐项（不是问题）

### 3.1 bootstrap 语义没有回退

设计要求 `bootstrap` 下必须使用“监控起点 / 首次建档 / 当前截面”话术，禁止写成“今日新增”。见 `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md:417-425,555-571`。

本次 HTML 中：

- `监控起点`：`workflow-run-1-full-report.html:1748`
- `首次建档/基线切面`：`workflow-run-1-full-report.html:1749`
- `本次入库 561 条评论`：`workflow-run-1-full-report.html:1751`
- `新近 3 / 补采 558`：`workflow-run-1-full-report.html:1752`
- `本次入库以历史补采为主，占比 99%`：`workflow-run-1-full-report.html:1760`

`analytics` 的 warning 侧也保留了稳定三键，且 `backfill_dominant` / `estimated_dates` 已按预期触发：`workflow-run-1-analytics-2026-04-25.json:645-656`。

结论：**Phase 1 的“今日变化 / bootstrap 语义治理”在这批生产产物里是稳住的。**

### 3.2 健康指数口径已统一

Stage A 验收要求之一是“HTML 总览卡片 vs tooltip vs 趋势页健康指数口径一致”。见 `docs/reviews/2026-04-24-report-upgrade-execution-plan.md:70-72`。

本次产物中：

- KPI 卡片健康指数为 `96.2`：`workflow-run-1-full-report.html:1629-1631`
- tooltip 文案已经是贝叶斯/NPS 代理版本：`workflow-run-1-full-report.html:1630`
- `analytics.kpi_cards` 的 tooltip 与值同步：`workflow-run-1-analytics-2026-04-25.json:3599-3603`
- `analytics.tooltips["健康指数"]` 同样已更新：`workflow-run-1-analytics-2026-04-25.json:11925-11930`

结论：**此前 P1-A 的三套公式分裂问题，在本次生产测试产物中没有复发。**

### 3.3 默认趋势视图正确

设计要求默认视图固定为 `月 + 舆情趋势`。见 `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md:438-447`。

本次产物中：

- `analytics.trend_digest.default_dimension = "sentiment"`：`workflow-run-1-analytics-2026-04-25.json:13904`
- `analytics.trend_digest.default_view = "month"`：`workflow-run-1-analytics-2026-04-25.json:13905`
- HTML 默认按钮激活也一致：`workflow-run-1-full-report.html:1853,1860`

### 3.4 Stage A 的 mixed-state 展示修复仍然有效

当前 HTML 已经不是“整块 accumulating 就把 KPI/表全部吞掉”的旧行为。

证据：

- `月 / 产品趋势` 虽然整体 `accumulating`，但仍展示了 KPI 和表：`workflow-run-1-full-report.html:2277-2324`
- `月 / 竞品趋势` 虽然主图仍在积累，但表格仍展示：`workflow-run-1-full-report.html:2438-2460`

这说明 Stage A 修复的“组件级 status 渲染”仍在生效，没有回退回 4 月 24 日审查前的坏状态。

### 3.5 T9 数据层已部分落地

`analytics` 中已经出现多个维度的 `secondary_charts` 与 `comparison`：

- `month.sentiment`：`workflow-run-1-analytics-2026-04-25.json:12576,12650`
- `year.issues`：`workflow-run-1-analytics-2026-04-25.json:13458`
- `month.competition`：`workflow-run-1-analytics-2026-04-25.json:12001,12110,12114`
- `year.competition`：`workflow-run-1-analytics-2026-04-25.json:13123,13178`

结论：**这批产物已经不是 Phase 1 基线，而是带有 T9 数据层增强的版本。**

---

## 4. 偏离项 / 未收口项

### 4.1 `competitive_gap_index` 仍未定义单一来源

这是本次审查里最明确的未收口项。

Continuity 里把它列为 Phase 2 前必须明确的遗留事项：

- `competitive_gap_index` 与 `gap_analysis[0].gap_rate` 并存，必须定义单一来源

见 `docs/reviews/2026-04-24-report-upgrade-continuity.md:214`。

本次产物里仍然是多套语义并存：

- 顶层 KPI `competitive_gap_index = 5`：`workflow-run-1-analytics-2026-04-25.json:3656`
- HTML 卡片展示 `竞品差距指数 = 5`：`workflow-run-1-full-report.html:1660-1661`
- `gap_analysis[0].gap_rate = 15`：`workflow-run-1-analytics-2026-04-25.json:760`
- `report_copy.competitive_insight` 又在写“差距指数为15”“差距指数跃升至8”：`workflow-run-1-analytics-2026-04-25.json:3697`

这会导致两个问题：

- 用户在总览卡片看到的是 5，但在叙述里读到的是 15/8/6，无法判断哪个才是“系统定义的差距指数”
- 一旦 T10/T11 开始把 trend / Excel / 邮件都进一步强化，这个口径分裂会继续放大

结论：**这是当前最需要明确归属和口径的偏离项。**

### 4.2 `products` 维度未补齐 T9 计划中的 `secondary_charts`

T9 实施计划在设计层明确写了：

- 每块至少 2 条 `secondary_charts`
- `products` 维度要补“评论总数趋势 + 价格趋势”

见 `docs/superpowers/plans/2026-04-25-phase2-t9-trend-digest-extension.md:5-13,750-954,1675-1680`。

但本次生产测试产物里，`products` 三个视图都仍然是：

- `secondary_charts: []`
- `primary_chart.status = accumulating`
- 只有 KPI + 表在展示

证据：

- `week.products`：`workflow-run-1-analytics-2026-04-25.json:12253-12263`
- `month.products`：`workflow-run-1-analytics-2026-04-25.json:12859-12869`
- `year.products`：`workflow-run-1-analytics-2026-04-25.json:25225-25234`

这和 sentiment / issues / competition 的表现明显不对称：

- sentiment 已有 `自有差评率趋势` / `健康分趋势`
- issues 已有 `Top3 问题分时段堆叠`
- competition 已有 `评分差趋势 (竞品 − 自有)` / `差/好评率对比`

对应证据：

- `workflow-run-1-analytics-2026-04-25.json:12576,12650`
- `workflow-run-1-analytics-2026-04-25.json:13458`
- `workflow-run-1-analytics-2026-04-25.json:12001,12110,13123,13178`

这里要注意区分两层判断：

- 从 `execution-plan` 的 T9 最低退出条件看，它没有强制要求所有块都 ready，只要求数据层扩展落地
- 但从 **T9 详细 implementation plan** 看，`products` 维度本来是承诺要补这两张辅图的

所以这更准确地说是：**低于 T9 详细实施计划的完成度，不一定构成 T9 阶段失败，但确实是未收口项。**

---

## 5. 计划内未完成，但不应算偏离

### 5.1 HTML 还没渲染辅图，属于 T10 未开始

当前 HTML 中能看到 partial note、KPI、主图占位和表格，但**没有任何一张 T9 新增辅图被真正渲染出来**。

全文检索未命中：

- `自有差评率趋势`
- `健康分趋势`
- `Top3 问题分时段堆叠`
- `评分差趋势 (竞品 − 自有)`
- `差/好评率对比`
- `trend_*_secondary_*`

同时，执行编排已明确把“辅图槽位 + print 展开”归到 T10：`docs/reviews/2026-04-24-report-upgrade-execution-plan.md:123-130`。

结论：**这是计划内未开始，不是偏离。**

### 5.2 Excel `趋势数据` sheet 仍是旧式快照表，属于 T10 未开始

本次 Excel 中 `趋势数据` sheet 仍然只有产品级快照列：

- `日期 / SKU / 产品名称 / 价格 / 评分 / 评论数 / 库存状态`

通过 `openpyxl` 检查可见，该 sheet 当前仅 9 行、7 列，仍是旧式快照结构，而非 T10 要求的 `view × dimension` 分块趋势表。

这与 T10 定义完全一致：

- `report.py` Excel `趋势数据` sheet 重写（按 view × dimension 分块）

见 `docs/reviews/2026-04-24-report-upgrade-execution-plan.md:123-129`。

结论：**这是 T10 未开始的正常现象，不应当作回归。**

### 5.3 `period_over_period / year_over_year` 仍为 null，是已记录的 carry-over

本次 `comparison` 结构已经稳定存在，但多数 `period_over_period / year_over_year` 仍为 null。

这和 Continuity 的现状记录一致：

- `period_over_period / year_over_year 当前固定 null shape，待历史数据扩展`

见 `docs/reviews/2026-04-24-report-upgrade-continuity.md:127`。

结论：**这不是偏离，是当前计划承认的留空状态。**

---

## 6. 观察项（建议跟踪，但暂不定性为偏离）

### 6.1 LLM 主风险聚焦对象仍值得人工复核

当前 `executive_bullets[0]` 已经不再使用“领跑 / 第一 / 并列首位”这类明确关系词，这是好的。

但它仍把 `.75 HP Grinder (#12)` 作为“核心风险高度集中”的主对象：`workflow-run-1-analytics-2026-04-25.json:3698-3701`。

与此同时，`risk_products[0]` 其实是 `Walton's Quick Patty Maker`：

- `Walton's Quick Patty Maker` `risk_score = 35.1`：`workflow-run-1-analytics-2026-04-25.json:4598-4603`
- `.75 HP Grinder (#12)` `risk_score = 32.6`：`workflow-run-1-analytics-2026-04-25.json:16627-16632`

这不构成当前硬门禁违规，因为 bullet 没再直接宣称“第一/最高/领跑”；但从业务理解上，仍建议在下一轮验收里人工复核“LLM 聚焦对象是否与系统排序一致”。

---

## 7. 建议动作

### 必做

1. 在 T10 开工前，先定掉 `competitive_gap_index` 的单一来源。
2. 明确 `products.secondary_charts` 缺失是“故意降级”还是 “T9 收口不完整”。
3. 如果是故意降级，需要同步更新 T9 计划/Continuity，避免后续误判。

### 建议

1. T10 计划里显式写清 `competition` mixed-state 的展示决策，回应 Continuity 中 I-2 的设计分歧。
2. 把“LLM 聚焦对象 vs risk_products[0]”加入后续 daily run 人工验收清单，但先不升格为硬门禁。

---

## 8. 最终判断

如果按“**当前应该处于哪个阶段**”来判断，这批产物**没有明显偏离**，它就是一个典型的：

- Phase 1 语义治理已稳住
- Phase 2 T9 数据层已部分落地
- Phase 2 T10 展示层尚未开始

但如果按“**T9 详细实施计划是否完全收口**”来判断，则还存在两个未收口点：

1. `competitive_gap_index` 口径分裂仍在
2. `products` 维度 `secondary_charts` 未补齐

因此更准确的结论应该是：

> **产物总体符合当前阶段边界，但还不能算“Phase 1~2 全面对齐完成”；它更像是“Phase 1 稳定 + T9 部分完成 + T10 待开工”的中间态。**
