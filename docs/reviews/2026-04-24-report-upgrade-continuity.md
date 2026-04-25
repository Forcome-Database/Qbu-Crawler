# 报告升级治理 · 跨会话 Continuity

**目的**：保证在多个 Claude Code / Codex 会话之间无缝接力。新会话开场第一件事就是读此文件。

**仓库根**：`E:\Project\ForcomeAiTools\Qbu-Crawler`
**主分支**：`master`
**版本号基线**：`0.3.17`（T0 已合入；Stage A 合入后 bump 到 0.3.18）

---

## 🧭 当前 Stage 指针

```
status:         Phase2-T9-COMPLETE · Phase2-T10-NOT-STARTED
last_updated:   2026-04-25
last_commit:    3b11cd7 chore: bump version 0.3.19 -> 0.3.21 (Phase 2 T9 完成 · trend_digest 数据层扩展)
last_tag:       v0.3.21-phase2-t9
next_action:    Phase 2 T10 implementation plan via superpowers:writing-plans (HTML 模板辅图槽位 + Excel 趋势数据 sheet 分块)
next_stage:     Phase 2 T10 · HTML + Excel 阅读体验
blocked_by:     T9 上线后跑 1 个 daily run 验证 trend_digest 扩展数据层产出无回归
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

### 2026-04-25 第 4 session (Phase 2 T9 执行)
- **Who**：Claude (Opus 4.7 1M · subagent-driven-development)
- **Done**：
  - Task 1 (T9-S1): 4931189→63211fb · trend_dimension_payload / _empty_trend_dimension 加 secondary_charts + comparison 占位 + 内层 shape 测试加固
  - Task 2 (T9-S2): 439bf81→37ec728 · accumulating 状态 KPI 永远 4 占位（修 audit §4.1）+ sentiment label drift fix（ready/accumulating 4 标签对齐）
  - Task 3 (T9-S3): 792301f→522d514 · sentiment dim secondary_charts (差评率 + 健康分) + comparison.start_vs_end + 全维度统一 change_pct 相对百分比语义
  - Task 4 (T9-S4): 1dec3b7→820cc91 · issues dim secondary_charts (Top3 堆叠 + 影响 SKU 数) + comparison + S2 修 _ = labels 误导
  - Task 5 (T9-S5): 27a9d1c · products dim secondary_charts (评论总数 + 价格) + comparison + 防御性 sorted 排序
  - Task 6 (T9-S6): 3c4b156→e7c1017 · competition dim secondary_charts (评分差 + 差/好评率) + comparison（abs(start) 分母防负 gap 翻转）+ Q1 负 gap 回归测试 + Q2 sentiment/competition `< 2` threshold
  - Task 7 (T9-S7): 4683851→fa3f099 · build_chartjs_configs 输出 trend_{view}_{dim}_secondary_{idx} 配置 + payload normalize
  - Task 8 (T9-S8): 0ec151d→9bbf29d · 4 grep 门禁 + 时间口径 trap-field（双向）+ Phase 1 键不变断言（覆盖 ready 路径）+ _git_grep 自测试 + subprocess timeout
  - Task 9 (T9-S9): <本 commit> · 版本号 bump 0.3.19 → 0.3.21 + Continuity 推进 + tag v0.3.21-phase2-t9
  - 全量 report 套件全绿（410+ tests passed）；模板 0 改动（T10 territory）；Phase 1 顶层 / 子层契约 0 改动
  - 每 task 经过 spec compliance review + code quality review 双阶段独立审查
- **Carry-over（follow-up，不阻塞 T10）**：
  - period_over_period / year_over_year 当前固定 null shape，待历史数据扩展（Phase 2 后续 task 或 Phase 3）
  - secondary chart stacked_bar/bar 在 Chart.js 渲染端目前共享 line builder，T10 模板侧需细分
  - test_phase2_t9_* 测试名应改为 test_phase2_contract_*（永久契约门禁，不应带 step 编号）
  - sentiment _ = labels 标记可移除（labels 在 sentiment comparison 中实际未用）— 但保留对未来 PoP/YoY 是预留
  - issues 标签集合 `["问题信号数", "活跃问题数", "头号问题", "涉及产品数"]` 在 ready/accumulating 共出现 3 次，可抽 `_ISSUE_KPI_LABELS` 模块常量；同理 sentiment / competition
  - readiness 模型（每 dim 不同 readiness 信号）值得在模块级 docstring 总结
  - **(I-1, latent)** `_build_trend_dimension` 的 degraded fallback 调 `_empty_trend_dimension` 时**未传** `kpi_placeholder_labels=`，导致 builder 异常时 KPI 退化为 4 个 "—"，违反 audit §4.1 契约。当前测试只覆盖 empty-snapshot accumulating 路径，degraded 是潜在违规。修法：给 `_build_trend_dimension` 加 dim-specific labels 参数，或各 dim 自己 try/except
  - **(I-2, T10 设计决策)** competition `_build_*_secondary_charts` docstring 声称 "mixed-state 解耦"，但 `report_charts.py:605` 用 top-level status gate 把整块吞掉。spec §8.5 要求 mixed-state，二者矛盾。T10 必须明确选边：(a) 保留 collapse + 改 docstring，或 (b) 改 gate 让独立 ready 的 secondary 渲染（且需新增测试）
  - **(M-2)** products dim accumulating path 直接调 `_trend_dimension_payload` 不走 `_empty_trend_dimension`，与其他 3 dim 不对称。当前靠 helper 默认值兜底，但 T10/T11 维护者可能因不一致踩坑。修法：给 `_empty_trend_dimension` 加可选 KPI items kwargs 让 products 也走它，或在模块 docstring 解释不对称
  - **(M-5)** `tests/test_workflows.py::test_config_report_defaults` pre-existing 失败（`.env` 含 `REPORT_LABEL_MODE=hybrid`，测试断言默认 `"rule"`）— env 泄漏，不是 T9 引入。修法：测试加 `monkeypatch.delenv`。与 report-upgrade 无关，独立修
  - **(M-3)** `test_build_chartjs_configs_emits_secondary_chart_keys` 仅覆盖"尾部跳过"场景（idx=0 ready, idx=1 accumulating），未覆盖"中间跳过"（如 idx=0 ready, idx=1 accumulating, idx=2 ready 应得 `_secondary_0` + `_secondary_2`）。enumerate 索引保留契约未充分锁定
- **Next**：T9 上线后跑 1 个 daily run 验证 trend_digest 扩展数据层产出无回归 → 写 Phase 2 T10 implementation plan
  - T10 plan 必须显式回应 I-2 的设计决策

### 2026-04-25 第 3 session (Phase 2 T9 plan 写作)
- **Who**：Claude (Opus 4.7 1M · executing-plans → writing-plans)
- **Done**：
  - 读 Continuity / execution-plan / phase2-audit §6（T9 scope）/ Phase 1 原始 plan Chunk 3 Task 9 / best-practice §7（Phase 2 前置）/ report_analytics.py 现状（_build_*_trend 4 函数 + _empty_trend_dimension + _trend_dimension_payload）/ report_charts.py build_chartjs_configs / report_templates/daily_report_v3.html.j2 trend 消费段
  - 写出 `docs/superpowers/plans/2026-04-25-phase2-t9-trend-digest-extension.md`（约 1100 行，9 Task，每 Task TDD bite-sized 步骤完整、代码可直接 paste、grep 门禁 4 条 + 时间口径回归覆盖）
  - 架构决策：secondary_charts shape 与 primary_chart 同构带独立 status；comparison shape 永远 3 段（PoP/YoY/start_vs_end），值缺失填 null（V2 spec 部分覆盖，PoP/YoY 留待后续 task 扩窗口）；KPI 占位永远 4 项；模板/Excel/邮件/LLM prompt 0 改动（T10/T11 territory）
  - Continuity 指针推进到 `Phase2-T9-PLAN-WRITTEN`
- **Carry-over（plan 内已记录）**：
  - PoP / YoY 实计算待 Phase 2 后续 task 扩 labeled_reviews 查询窗口
  - secondary chart stacked_bar/bar 渲染细分留 T10
- **Next**：契约冻结期 Day 5（2026-04-30）通过 → subagent-driven-development 起步执行 T9 Task 1

### 2026-04-25 第 2 session (Stage B 执行)
- **Who**：Claude (Opus 4.7 1M · subagent-driven-development)
- **Done**：
  - Task 1 (T-B-1): 682574a + 8ee476d · artifact 路径相对化（report_snapshot 三 mode + workflows 单源单 wrap）
  - Task 2 (T-B-2): d493027 + a0de39e · kpis 字段消歧（negative_review_rate → all_sample_negative_rate；模板/LLM 改读 own_*；dead variable + delta block 清理）
  - Task 3 (T-B-3): b9ddeea · trend year 视图语义 banner（trend_digest.view_notes 数据驱动）
  - Task 4 (T-B-4): 88b0bd3 + e54a1df · LLM low-sample 改读 change_digest.summary.fresh_review_count（bootstrap 跳过；fresh=0 平滑措辞；legacy-analytics 测试覆盖）
  - Task 5 (T-B-5): d7a538e · 版本号 bump 0.3.18 → 0.3.19 + Continuity 推进 + tag v0.3.19-stage-b
  - 5 + 2 条 grep 门禁全绿（Stage A 5 条 + Stage B 新增 2 条）
  - report 相关 13 个测试文件全绿
  - subagent-driven → spec compliance review → code quality review → 二阶段 review 全流程
- **Carry-over（follow-up，不阻塞 Phase 2 T9）**：
  - artifact 路径迁移在生产数据库的影子库回归（Continuity §5 遗留事项）
  - LOW_SAMPLE_FRESH_THRESHOLD 常量提取（与 BACKFILL_DOMINANT_RATIO 风格统一）
  - daily_report_v3.css 设计 token 化 banner 颜色（M-1 of T-B-3 review）
- **Next**：契约冻结期 Day 5（连续 3 个 daily run 观测 OK 后）开 Phase 2 T9 implementation plan

### 2026-04-25 第 1 session (Stage A 执行)
- **Who**：Claude（Opus 4.7 1M · subagent-driven-development）
- **Done**：
  - Task 1: 581dfe1 · 贝叶斯健康指数统一
  - Task 2: c1b682b · 趋势页组件级 status
  - Task 3: 14910db + 98270fc (fix weak-Red + extract BACKFILL_DOMINANT_RATIO 常量) · LLM prompt 清理
  - Task 4: 3811266 · bootstrap 违禁词扩面
  - Task 5: ff50479 · fallback 与邮件 semantics
  - Task 6: 0696624 · chore version bump + tag v0.3.18-stage-a
  - 5 条 grep 门禁全绿
  - 报告相关 11 个测试文件全绿（2 pre-existing 失败已核对非本 Stage 引入）
  - subagent-driven → TDD → spec review → code quality review → finishing 全流程
- **Carry-over（follow-up，不阻塞契约冻结）**：
  - POSITIVE_THRESHOLD 常量提取（5 处魔数 4）
  - MIN_RELIABLE / PRIOR 常量提模块级
  - Task 2 template duplicate status_message（289 vs 304）
  - Task 4 `同比` pattern 假阳性风险 + 字符串形式 priority
  - Task 5 纯 Jinja-level email else 分支测试（test fidelity）
- **Next**：新 session 开场读本文件 → 按 next_action 写 Stage B implementation plan

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
- ✅ **artifact 路径迁移回归的预发数据库**（已在 T-B-1 测试覆盖：`tests/test_v3_modes.py::TestLoadPreviousContext::test_handles_missing_file` 已断言失效路径回退；生产影子库回归留作 carry-over）
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

> **契约冻结期启动**：自 `v0.3.18-stage-a` 打 tag 起生效。连续 3 个 daily run 不允许改 `change_digest / trend_digest / kpis` 顶层键名。

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
