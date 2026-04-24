# Phase 2 审查 — 当前开发状态与前置条件

**日期**：2026-04-24
**审查范围**：`docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md` 的 Chunk 3（T9 / T10 / T11）— "趋势深化与阅读增强"
**对标验收**：spec §14 Phase 2 验收标准
**参考**：`claude-review.md / codex-review.md / best-practice.md`（这三份只覆盖 Phase 1）

---

## 1. 一句话结论

> **Phase 2 尚未开发**。当前实现停留在 Phase 1 基线集合，且 Phase 1 自身还有 4 处局部违规（见 §4），必须先完成 Phase 1 全部收口 + Stage A P1 修复，才能启动 Phase 2。

---

## 2. Phase 2 开发状态核查

### 2.1 代码层

全仓 grep `secondary_charts`：**只命中 1 处**，就是 plan 文件本身：

```
docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md:726
  - `secondary_charts`
```

→ 代码与测试里 0 命中 `secondary_charts` / `secondary_chart`，`report_analytics._build_trend_digest` / `report_charts.py` / `daily_report_v3.html.j2` 均无扩展实现。

### 2.2 产物层

测试2 的 `trend_digest.data[view][dim]` 每个块键集 =
`{kpis, primary_chart, status, status_message, table}`

对比 Phase 2 §8.4 要求的"顶部 4 KPI + 1 主图 + 2 辅图 + 1 表"：
- ✅ KPIs 键存在
- ✅ `primary_chart` 键存在
- ❌ **`secondary_charts` 键完全缺失**
- ✅ `table` 键存在

### 2.3 测试层

`tests/test_report_analytics.py` / `tests/test_v3_html.py` / `tests/test_v3_excel.py` / `tests/test_report_integration.py` 均无 `secondary_charts` / `辅图` / `secondary` 相关断言。

### 2.4 Devlog 层

- D018（2026-04-23）明确标题 "今日变化与变化趋势语义治理"，内容收口在 Phase 1（5-sheet Excel、change_digest/trend_digest 契约、artifact resolver）
- 结尾一句：*"后续继续深化趋势页时，只能在 trend_digest 这层增强，不能再让展示层绕过归一化字段各自解释原始数据。"* — 明确把深化工作推给未来
- `docs/devlogs/` 里无 Phase 2 开发日志

**结论**：Phase 2（T9 / T10 / T11）**未启动**，按计划应由单独一轮 PR 承接。

---

## 3. Phase 2 验收标准回顾（对齐 spec §14）

| # | Phase 2 验收标准 | 当前差距 |
|---|---|---|
| V1 | `trend_digest` 四个维度均具备**稳定的扩展图表和基础表格** | 主图 + 表已有；**辅图 0**；扩展图表 0 |
| V2 | `变化趋势` 的 `周\|月\|年` 视角均有清晰的**环比 / 同比 / 期初期末表达** | 未实现环比 / 同比 / 期初期末字段 |
| V3 | HTML / Excel 趋势页具备更完整的**主图、辅图、表格组合** | HTML 主图 + 表已渲染；辅图槽位未开；Excel `趋势数据` sheet 仍是原始快照，未按维度分主图/辅图 |
| V4 | Phase 2 的增强**没有引入第二套 KPI、第二套趋势口径或模板侧重算逻辑** | 尚无代码可审，但 P1-A（健康指数分裂）+ P1-B（模板一刀切）在 Phase 1 就已埋下隐患，启动 Phase 2 前必须先把这两条根治，否则 V4 天然不可能达成 |

---

## 4. Phase 1 未完全达标项（直接影响 Phase 2 可否开工）

按 Phase 1 §8.4 "每维度最少一组稳定 KPI + 一张主图 + 一张基础表" 核对 12 个 `view × dimension` 组合：

| view/dimension | KPI items | primary_chart status | table rows | Phase 1 合规 |
|---|---:|---|---:|---|
| week/sentiment | 0 | accumulating | 0 | ❌ |
| week/issues | 0 | accumulating | 0 | ❌ |
| week/products | 4 | accumulating | 5 | ✅ |
| week/competition | 0 | accumulating | 0 | ❌ |
| month/sentiment | 4 | ready | 4 | ✅ |
| month/issues | 4 | ready | 1 | ✅ |
| month/products | 4 | accumulating | 5 | ✅ |
| month/competition | 0 | accumulating | 0 | ❌ |
| year/sentiment | 4 | ready | 11 | ✅ |
| year/issues | 4 | ready | 3 | ✅ |
| year/products | 4 | accumulating | 5 | ✅ |
| year/competition | 4 | ready | 11 | ✅ |

**违规：4 / 12 个组合**（week/sentiment、week/issues、week/competition、month/competition）。

### 4.1 week 粒度的三处违规（sentiment / issues / competition）

首日下 week 粒度确实数据不足（spec §8.5 允许 `sentiment / issues` 首日可 ready，但**未强制**），因此 `accumulating` 状态本身可以接受。违规点在于**后端产物没给任何 KPI item**（`kpis.items = []`）。

- spec §8.4 原话："每个可视组件必须显式携带 `status = ready | accumulating | degraded`" — 只要求 status，不要求 items 非空
- 但 §8.4 又说"每个维度至少提供 1 组稳定 KPI" — 与上一条字面冲突
- Codex 的"组件级 status"修复（P1-B）建议在 accumulating 下也展示占位 KPI，更贴近"功能不砍"的精神

**建议**：后端在所有 accumulating 维度至少产出 4 个占位 KPI（值为 `-` 或"暂无数据"），让前端可以展示"跟踪中但数据不足"。

### 4.2 month/competition 的违规（整维度一刀切，spec §8.5 明确禁止）

`report_analytics.py:1734-1742` 只要 `shared_points == 0` 就整块 `_empty_trend_dimension("accumulating", ...)`，直接跟 spec §8.5 **"竞品趋势 允许按子组件混合状态输出，不能整维度一刀切成同一状态"** 相反。

**这条在 Codex P1-B 已经点名**，属于 Phase 1 必修，不是 Phase 2 范畴。

---

## 5. Phase 2 启动前置条件（阻塞项）

按严重度倒序：

| # | 前置条件 | 为什么阻塞 Phase 2 |
|---|---|---|
| B1 | Stage A 的 6 条 P1 全部合入（best-practice.md §3 修 1-6） | 不修就会把漂移扩散到 Phase 2 的辅图文案 / 扩展 KPI / Excel 趋势表 |
| B2 | P1-A 健康指数口径统一 | Phase 2 sentiment 辅图大概率要展示"健康指数变化"，口径不统一 → 辅图与顶层 KPI 对不上 |
| B3 | P1-B 模板按组件级 status 渲染 | 否则 Phase 2 新加的 2 张辅图同样会被现在的整块 if 吞掉 |
| B4 | `competition` 维度改组件级 mixed-state（Phase 1 补救） | month/competition 的整块 accumulating 会让 Phase 2 的 4 KPI + 主图 + 2 辅图 + 1 表全部被一次性置空 |
| B5 | P1-C LLM 关系词对账器落地 | Phase 2 会在 `trend_digest` 生成"Top N 问题簇热度趋势 / 重点 SKU 评分趋势"等派生 Top 排名，LLM 叙述这些数据时同样会出现"领跑/并列/最高"关系词漂移，没有对账器就等于把 P1-C 的问题平铺到所有趋势维度 |
| B6 | `competitive_gap_index` 单一口径（P2 前置，非严重） | 顶层 `kpis.competitive_gap_index=5` 与 `gap_analysis[0].gap_rate=13` 并存；Phase 2 `competition` 维度必然要选择其中一个作为趋势主轴，口径分裂会让辅图/主图不可对账 |

---

## 6. Phase 2 实施建议（在 B1-B6 全部就绪后）

### 6.1 分 Task 落地（严格按 plan T9 → T10 → T11）

#### T9 · `trend_digest` 扩展数据层

- 为每维度在 `kpis.items` 上稳定输出 4 条（现在部分是 0 或 1）
- 为每维度新增 `secondary_charts: [<chart_1>, <chart_2>]`
- 在每维度新增"环比 / 同比 / 期初期末"字段（例如 `comparison: {period_over_period, year_over_year, start_vs_end}`）

#### T10 · HTML / Excel 阅读体验

- HTML：在修 2（组件级 status）基础上增加辅图槽位，默认两张横排（加 CSS flex），对 print 模式整段展开
- Excel：`趋势数据` sheet 从原始 `_trend_series` 扩展为按 `{view, dimension}` 分块，每块内 KPI + 主图数据 + 辅图数据 + 表

#### T11 · 回归 + 文档

- 断言 Phase 2 没有新增第二套 KPI（grep `new_health_metric` / 对比 KPI 键数）
- 断言 `trend_digest.views / dimensions / default_view / default_dimension` 与 Phase 1 完全一致（契约兼容性）
- 更新 `D019-phase2-trend-deepening.md`

### 6.2 Phase 2 风险预警

| 风险 | 缓解 |
|---|---|
| 深化后 Chart.js 渲染体量翻倍（每维度从 1 图 → 3 图，共 12 × 3 = 36 图，外加 Excel） | 延迟渲染 / 懒加载 / 在 tab 切换前不实例化 Chart.js |
| 辅图数据来源再次绕过 `trend_digest`，直接从 analytics 根取字段（Phase 1 一开始就踩过坑） | CI 加 grep `daily_report_v3.html.j2` 内的 `analytics.window` / `analytics.cumulative_kpis` / `analytics._trend_series`（应全部为 0） |
| 年视角辅图落入"历史时间回顾"陷阱（Claude P2-I） | 启动 Phase 2 前把 Year 视角语义 banner 合入 |
| LLM 洞察围绕扩展趋势时生成"同比去年增长 X%"类措辞，但实际去年样本可能是 backfill → 再次漂移 | Phase 2 同步扩展违禁词表 `新增`、`暴增`、`同比`、`环比`等检测面，并增加"backfill占比 / 样本数不足时禁止趋势断言"的 prompt 约束 |

---

## 7. 推荐落地节奏

```
                      当前
                        │
                        ▼
Phase 1 Stage A ──► 6 条 P1 必修 + B4/B6 Phase 1 补救 (1 个 PR)
                        │ 验收：CI 门禁 + 预发回归 + 产物对账
                        ▼
Phase 1 Stage B ──► 4 条 P2 建议修 (1 个 PR)
                        │ 验收：artifact 路径迁移回归 / 邮件 fallback / kpi 消歧
                        ▼
Phase 2 T9 ────► trend_digest 数据层扩展 (1 个 PR)
                        │ 验收：secondary_charts / 环比同比字段 / KPI 到 4 条
                        ▼
Phase 2 T10 ──► HTML + Excel 阅读体验增强 (1 个 PR)
                        │ 验收：辅图渲染、print 展开、Excel 分块
                        ▼
Phase 2 T11 ──► 回归 + 文档 (1 个 PR)
                        │ 验收：全量 pytest + D019 开发日志
                        ▼
                       完成
```

每个阶段**独立 PR、独立上线验收**，禁止把 Phase 2 和 Phase 1 收口改动混在同一个 PR 里，否则回滚粒度过粗。

---

## 8. 总结

| 问题 | 回答 |
|---|---|
| Phase 2 开发了吗？ | **没开发**。代码、产物、测试、devlog 全部 0 迹象 |
| 之前的三份审查是不是只看了 Phase 1？ | 是。Claude + Codex + Best-practice V2 全部针对 Phase 1 |
| Phase 1 自己有没有遗留违规？ | 有 4 处（week × 3 + month/competition），其中 `competition` 维度的整块 accumulating 已被 Codex P1-B 列入必修 |
| Phase 2 现在能不能开工？ | **不能**。需先完成 B1-B6 这 6 条前置条件（5 条来自 Phase 1 收口、1 条 `competitive_gap_index` 口径） |
| 建议时间窗口？ | Stage A 小 PR（1-2 天）→ Stage B 小 PR（1 天）→ Phase 2 拆 3 个 PR（各 2-3 天），合计 ≈ 7-10 工作日，不要合并 |
