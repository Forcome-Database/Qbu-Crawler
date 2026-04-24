# 报告升级治理 · 跨会话 Continuity

**目的**：保证在多个 Claude Code / Codex 会话之间无缝接力。新会话开场第一件事就是读此文件。

**仓库根**：`E:\Project\ForcomeAiTools\Qbu-Crawler`
**主分支**：`master`
**版本号基线**：`0.3.17`（T0 已合入；Stage A 合入后 bump 到 0.3.18）

---

## 🧭 当前 Stage 指针

```
status:         Stage-A-PLAN-WRITTEN · READY-TO-EXECUTE
last_updated:   2026-04-24 23:xx
last_commit:    (即将 commit) docs: continuity + Stage A plan
last_tag:       v0.3.17-t0-hotfix
next_action:    执行 Stage A · 调用 superpowers:subagent-driven-development
                （基于 docs/superpowers/plans/2026-04-24-stage-a-p1-remediation.md）
next_stage:     Stage A · 6 Task · 预计 1-2 天完成
blocked_by:     无（Task 5 Step 5.6 测试已核对真实入口 _render_full_email_html）
```

---

## 🚪 新 Session 开场 SOP

**开场 3 分钟标准动作**（严格按序）：

1. **读本文件**（`docs/reviews/2026-04-24-report-upgrade-continuity.md`）— 从 "当前 Stage 指针" 和 "进度日志" 最新 3 条入手
2. **读执行编排**（`docs/reviews/2026-04-24-report-upgrade-execution-plan.md`）— 回忆整体路线和已锁定的决策
3. **读 Stage 对应的指南**：
   - 如果 `next_stage` 是 Stage A → 读 `docs/reviews/2026-04-24-report-upgrade-best-practice.md` §1-§3（必修清单 + 代码补丁）
   - 如果 `next_stage` 是 Stage B → 读 best-practice §4（建议修清单）
   - 如果 `next_stage` 是 Phase 2 T9 → 读 `docs/reviews/2026-04-24-report-upgrade-phase2-audit.md` §6（Phase 2 实施建议）
4. **按 `next_action` 调用对应 superpowers skill**：
   - `next_action` 含 "写 plan" → `superpowers:writing-plans`
   - `next_action` 含 "执行 plan" → `superpowers:subagent-driven-development`
   - `next_action` 含 "review" → `superpowers:requesting-code-review`
   - `next_action` 含 "commit/tag/merge" → `superpowers:finishing-a-development-branch`
5. **读遗留事项**（本文件 §5）确认有没有需要先解决的阻塞

**3 分钟内应该能回答**：
- 当前在整条路线的第几步
- 下一条命令该打什么
- 有没有契约冻结中的禁改项

---

## 🎯 各 Stage Entry / Exit 验收（抄自 execution-plan）

### T0 · LLM 关系词 hotfix ✅ 已完成
- Commit: `dadaf81`
- Tag: `v0.3.17-t0-hotfix`
- 产物：`_check_relation_claims` + 6 个新测试，30/30 全绿，生产产物回放精确命中 2 条已知幻觉

### Stage A · Phase 1 P1 必修 ⏳ 下一步
- **Entry**：本文件 `next_action` = 写 Stage A plan
- **Scope**（6 修，文件清单）：
  - `qbu_crawler/server/report_llm.py`（修 4 清理 L531-541 重复段 + 修 5 扩大违禁词）
  - `qbu_crawler/server/report_common.py`（修 1 健康指数 tooltip + 修 6 fallback 感知 semantics）
  - `qbu_crawler/server/report_analytics.py`（修 1 趋势页健康分同公式 + 修 2 competition 组件级 status）
  - `qbu_crawler/server/report_templates/daily_report_v3.html.j2`（修 2 模板组件级 if）
  - `qbu_crawler/server/report_templates/email_full.html.j2`（修 6 邮件 fallback）
- **Exit**：
  - best-practice §5 的 5 条 grep 门禁全绿
  - 新增 13 条单测全绿
  - 预发 1 bootstrap + 1 fake incremental 验收
  - 人工肉眼：tooltip vs 卡片 vs 趋势页健康指数**口径一致**
  - 合入后打 `v0.3.18-stage-a`

### Stage B · Phase 1 P2 建议修
- **Entry**：Stage A 合入并稳定 24h
- **Scope**：
  - `qbu_crawler/server/report_snapshot.py` + `qbu_crawler/server/workflows.py`（修 7 artifact 路径）
  - `qbu_crawler/server/report_analytics.py`（修 8 kpis 消歧）
  - `qbu_crawler/server/report_templates/daily_report_v3.html.j2`（修 9 year banner）
  - `qbu_crawler/server/report_llm.py`（修 10 low-sample 口径）
- **Exit**：artifact 路径迁移回归通过；全量 pytest 绿；tag `v0.3.19-stage-b`
- **Note**：**Stage B 与 Phase 2 T9 可并行**（文件不重叠）

### 契约冻结期 · Day 5-7
- **Entry**：Stage A 合入后立即开始
- **Duration**：3 个完整 daily run 周期
- **禁改**：
  - `change_digest / trend_digest / kpis` 的顶层键名
  - `report_semantics / is_bootstrap` 语义
  - `warnings` 的三个稳定键（`translation_incomplete / estimated_dates / backfill_dominant`）
- **观测项**（连续 3 天 daily run 均满足）：
  - 健康指数三处（卡片/tooltip/趋势）同口径
  - month/products 有 KPI + 表格渲染
  - bullet 不出现"领跑/最高/第一"指向非 `risk_products[0]`
  - `今日新增` 全局 0 命中
- **失败则**：回 Stage A 排查，禁止推进 Phase 2

### Phase 2 T9 · trend_digest 数据层扩展
- **Entry**：Day 5（契约冻结期通过）
- **Scope**：`report_analytics.py` + `report_charts.py`；**禁动**模板 / Excel / 邮件
- **Exit**：`trend_digest.data.[view].[dim].secondary_charts` 至少 2 条；Phase 1 键未被改名

### Phase 2 T10 · HTML + Excel 阅读体验
- **Entry**：T9 合入后
- **Scope**：HTML 模板 + Excel `趋势数据` sheet；**禁动**`trend_digest` schema

### Phase 2 T11 · 回归 + 文档
- **Entry**：T9+T10 合入并线上跑 1 daily 周期
- **Scope**：`tests/test_*` 补全 + `D019-phase2-trend-deepening.md`

---

## 📝 进度日志（追加型，最新 3 条 → 最上方）

### 2026-04-24 第 1 session
- **Who**：Claude（Opus 4.7 1M）+ Codex（失败 1 次后完成 1 次）
- **Done**：
  - 完成 Claude 独立审查（22 KB）
  - 完成 Codex 独立审查（24 KB）— 补出 3 条 Claude 遗漏 P1（健康指数三公式、模板吞数据、LLM 关系词漂移）
  - 完成 best-practice V2（27 KB）— 合并 6 条 P1 + 4 条 P2
  - 完成 Phase 2 独立审查 — 确认未开发
  - 完成 execution-plan — 6 段式落地路线
  - 用户决策锁定：T0 今晚、健康指数统一方案 A、Phase 2 Day 5 启动
  - 完成 T0 实现（`_check_relation_claims` + 6 测试）
  - 3-layer commit + tag：`d9e311c docs / 926d615 Phase 1 / dadaf81 T0` + `v0.3.17-t0-hotfix`
  - 完成 continuity 文件（本文件）
  - 完成 Stage A implementation plan（`docs/superpowers/plans/2026-04-24-stage-a-p1-remediation.md`，6 Task · TDD 步骤完整 · 代码可直接用）
- **Next**：新 session 开场读本文件 → 读 Stage A plan 头部 → 调用 `superpowers:subagent-driven-development` 执行 Task 1

---

## ⚠️ 遗留事项 / 需决策项

- **Stage A "修 1" 健康指数统一策略细节未敲定**：
  - best-practice §3 给了 A/B 两个方案（A = 趋势页重算为贝叶斯、B = 改名"反差评率"）
  - 用户已选 A，但趋势桶位（可能 1-2 条评论）的贝叶斯小样本收缩在实操层面可能遇到边界问题（0 条评论如何显示？先验 50？null？）
  - 写 plan 时需在 Task 1 的 Step 1 解决
- **artifact 路径迁移回归的预发数据库**：Stage B 修 7 需要预发一条失效 `analytics_path`，当前生产数据库是真实数据，回归前需要准备影子数据库或挑一个废弃 run_id
- **`competitive_gap_index` 口径问题**（best-practice P2-K）：顶层 `kpis.competitive_gap_index = 5` 与 `gap_analysis[0].gap_rate = 13` 并存，Phase 2 前需定义单一来源。**不是 Stage A 范畴**，但 Phase 2 T9 开工前必须明确

---

## 🧊 禁止改动清单（随 stage 更新）

### Stage A 进行中时
- ✅ 所有 Phase 1 合入的文件都可改
- ❌ 禁止改 Stage B 涉及的 `workflows.py` 的 artifact 路径写入部分（避免 Stage A/B 混淆回滚）

### 契约冻结期（Stage A 合入后 → Phase 2 T9 开工前）
- ❌ `change_digest` / `trend_digest` / `kpis` 顶层键名
- ❌ `report_semantics / is_bootstrap` 语义
- ❌ `warnings` 三键
- ✅ 纯文案（HTML 文字 / 邮件 copywriting）
- ✅ 新爬虫站点接入
- ✅ OpenClaw workspace 等周边

### Phase 2 进行中时
- ❌ 不得新增第二套 KPI（`kpis_v2` / `metric_new_*` 等）
- ❌ 模板不得绕过 `trend_digest` 直接读 `analytics.window` / `analytics._trend_series` / `cumulative_kpis`
- ❌ 不得改 Phase 1 已稳定的 `change_digest` / `kpis` 键名

---

## 🔗 关联文档索引

| 文件 | 作用 |
|---|---|
| `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md` | 原始设计契约 |
| `docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md` | Phase 1 原始开发计划 |
| `docs/devlogs/D018-report-change-trend-governance.md` | Phase 1 开发日志 |
| `docs/reviews/2026-04-24-report-upgrade-claude-review.md` | Claude 审查 |
| `docs/reviews/2026-04-24-report-upgrade-codex-review.md` | Codex 审查 |
| `docs/reviews/2026-04-24-report-upgrade-best-practice.md` | 合并最佳实践 V2（修 1-10 代码补丁 + 测试清单） |
| `docs/reviews/2026-04-24-report-upgrade-phase2-audit.md` | Phase 2 开发状态与前置条件 |
| `docs/reviews/2026-04-24-report-upgrade-execution-plan.md` | 6 段式落地编排 |
| `docs/reviews/2026-04-24-report-upgrade-continuity.md` | **本文件** · 跨会话接力 |

---

## 🔄 如何更新本文件

每个 session 结束时必须做 3 件事：

1. **更新 "当前 Stage 指针"**（status / last_commit / last_tag / next_action）
2. **追加 "进度日志"**（新一行在最上方，记录 Who / Done / Next）
3. **清理 "遗留事项"**（已解决的打 ✅ 或删除）

**规则**：**本文件永远不超 300 行**。超了就精简"进度日志"（保留最近 3 条 session），老的 session 摘要到 `docs/devlogs/` 对应条目。
