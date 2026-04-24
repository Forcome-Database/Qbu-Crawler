# 升级后续推进的执行编排（防乱版）

**日期**：2026-04-24
**前置阅读**：`claude-review.md` / `codex-review.md` / `best-practice.md` / `phase2-audit.md`
**定位**：把上述 4 份文档里的修复项和 Phase 2 拆成**可逐个落地、可独立验收、可独立回滚**的 6 个 Stage。

---

## 0. 五条"不乱"原则

1. **单 PR 单关注点**：schema / prompt / 模板 / Excel / 文档四类改动不得合在同一个 PR。
2. **契约先冻结再扩展**：顶层 `report_semantics / is_bootstrap / change_digest / trend_digest / kpis` 的键名与业务含义在 Stage A-B 期间**禁止变更**；Phase 2 只能在这些已有键下加子字段。
3. **CI grep 门禁前置**：每个 Stage 把对应的 grep 白/黑名单加进 CI，一旦合入后续改动违反立即阻断。
4. **每 Stage 独立回滚点**：Stage A 合入后立即打 tag `v0.2.6-stage-a`；Stage B 打 `v0.2.7-stage-b`；每个 Phase 2 PR 打 `v0.3.x` 系列。回滚只回上一 tag，不半路回滚。
5. **生产 daily run 不停**：整条治理期间线上 daily 继续跑，但**T0 (hotfix) 必须在 24h 内上**，否则用户会持续被 LLM 排序错误误导。

---

## 1. 时间线总览

```
Day 0 ──► T0 hotfix            ◀── 今天 / 明天 ·  仅 1 文件 · 2-4 小时
            │
            ▼
Day 1-2 ──► Stage A · Phase 1 P1 必修 (6 修)    · 5-6 文件 · 1-2 天
            │ 合入 → tag v0.2.6-stage-a → 生产灰度 24h
            ▼
Day 3-4 ──► Stage B · Phase 1 P2 建议修 (4 修)  · 4 文件   · 1 天
            │ 合入 → tag v0.2.7-stage-b → 契约冻结开始
            ▼
Day 5-7 ──► 契约冻结期 · 生产 daily 跑 3 个完整周期
            │ 期间不允许改 change_digest / trend_digest schema
            ▼
Day 8-10 ──► Phase 2 T9 · trend_digest 数据层扩展
             │ 合入 → tag v0.3.0-t9
             ▼
Day 11-13 ──► Phase 2 T10 · HTML + Excel 阅读体验
             │ 合入 → tag v0.3.1-t10
             ▼
Day 14 ──► Phase 2 T11 · 回归 + 文档
             │ 合入 → tag v0.3.2-phase2-complete
             ▼
Day 15+ ──► 常态维护 + Phase 3 规划
```

---

## 2. 每个 Stage 的四要素（Trigger / Scope / Exit / Rollback）

### T0 · LLM 排序错误 hotfix（P1-C 紧急止血）

- **Trigger**：**立即**。已在用户可见产物里出现"29.6 分领跑"这种误导最高风险 SKU 的幻觉，等不到 Stage A。
- **Scope**：**只改一个文件** `qbu_crawler/server/report_llm.py`
  - 方案 A（保守，推荐先上）：把 `_validate_insights` 追加关系词对账（best-practice.md 修 3），命中即 `_fallback_insights`。**此改动有副作用**：可能导致 bootstrap 产物 executive_bullets 退化成 fallback 模板；可接受。
  - 方案 B（更彻底，可后续上）：Hero / Top-3 bullets 模板化生成，不让 LLM 自由发挥。
- **Exit**：`pytest tests/test_report_llm.py -v`（新增 `test_report_copy_relation_word_cross_check`）全绿 + 本地跑一次 bootstrap 场景验证 bullet[0] 不再把非 top SKU 说成"领跑"。
- **Rollback**：若误伤率过高（fallback 占比 >20%），把 `_validate_insights` 里关系词检测改为**日志告警不 fallback**；保留 grep 统计能观察漂移。

### Stage A · Phase 1 P1 必修（6 条一起合）

- **Trigger**：T0 合入后 24h
- **Scope**：
  - `report_llm.py`（修 4/5，清理 L531-541 重复段 + 扩大违禁词）
  - `report_common.py`（修 1 健康指数统一 + 修 6 fallback 感知 semantics）
  - `report_analytics.py`（修 1 趋势页健康分同公式 + 修 2 competition 组件级 status）
  - `report_templates/daily_report_v3.html.j2`（修 2 模板按 kpis/chart/table 独立渲染）
  - `report_templates/email_full.html.j2`（修 6 邮件 fallback）
- **Exit**：
  - best-practice.md §5 的 5 条 grep 门禁全绿
  - 新增 13 条单测全绿（见 best-practice.md §4）
  - 预发跑 1 次真实 bootstrap + 1 次 fake incremental（手动改 mode）
  - 人工肉眼验收：HTML 总览卡片 vs tooltip vs 趋势页健康指数**口径一致**；`月/产品` 区能看到 KPI + 表；bullet 不再把非 top SKU 说"领跑"
- **Rollback**：`git revert` 到 `v0.2.6-stage-a` 之前的 commit；保留 T0 hotfix

### Stage B · Phase 1 P2 建议修（1 PR）

- **Trigger**：Stage A 上线并稳定 24h
- **Scope**：
  - `report_snapshot.py` + `workflows.py`（修 7 artifact 路径全部经 `_artifact_db_value`）
  - `report_analytics.py`（修 8 kpis 消歧：`negative_review_rate` 迁走）
  - `report_templates/daily_report_v3.html.j2`（修 9 year 视角 banner）
  - `report_llm.py`（修 10 low-sample 改 `fresh_review_count`）
- **Exit**：
  - artifact 路径迁移回归：预发数据库里手动把一条 `analytics_path` 改成失效绝对路径，确认 next run 能恢复
  - 全量 pytest
- **Rollback**：`git revert`；artifact 路径改动因涉及 DB，需要同步回滚 schema 默认值，因此回滚前先跑一次"把相对路径改回绝对路径"的迁移脚本

### 契约冻结期（Day 5-7，强制 3 个 daily 周期）

- **Freeze 对象**：
  - `change_digest` / `trend_digest` 顶层键名
  - `kpis` 的所有 key（不允许新增、不允许改名）
  - `report_semantics / is_bootstrap` 语义
- **允许改**：
  - 纯文案（HTML 文字 / 邮件 copywriting）
  - 新爬虫站点接入
  - 数据质量邮件模板
  - OpenClaw workspace 等周边
- **观测项**：连续 3 天 daily run 产出 HTML 均满足：
  - 健康指数三处（卡片/tooltip/趋势）同口径
  - month/products 能看到 KPI + 表格（不只是"样本不足"文案）
  - 任一 bullet 不出现"领跑/最高/第一"指向非 `risk_products[0]`
  - `今日新增` 全局 0 命中

若任一项连续 3 天失败 → 回到 Stage A 排查，不允许推进 Phase 2。

### Phase 2 T9 · `trend_digest` 数据层扩展

- **Trigger**：契约冻结期通过
- **Scope**：
  - `report_analytics.py`（新增 `_build_secondary_charts`、每维度扩 KPI 到 4 条、加 `comparison` 字段：period_over_period / year_over_year / start_vs_end）
  - `report_charts.py`（辅图 Chart.js 配置生成）
  - **禁止动** HTML 模板 / email 模板 / Excel 导出
- **Exit**：
  - `trend_digest.data.month.sentiment.secondary_charts` 至少 2 条，每条有 `chart_type / labels / series / status / title`
  - grep `primary_chart` 数量 = grep `secondary_charts` 外层数量（对称结构）
  - schema 回归测试：确认 Phase 1 已有键（kpis/primary_chart/status/status_message/table）**未被改名或删除**
- **Rollback**：revert 一个 PR 即可，产物向下兼容（前端/Excel 忽略未识别 `secondary_charts` 字段）

### Phase 2 T10 · HTML + Excel 阅读体验

- **Trigger**：T9 合入并产物验证
- **Scope**：
  - `report_templates/daily_report_v3.html.j2` + `.js` + `.css`（辅图槽位 + print 展开）
  - `report.py` Excel `趋势数据` sheet 重写（按 view × dimension 分块）
  - **禁止动** `trend_digest` schema / analytics 层
- **Exit**：
  - HTML 每个维度 × 视角显示：4 KPI + 1 主图 + 2 辅图 + 1 表（accumulating 时至少 placeholder）
  - Excel `趋势数据` sheet 行数显著增加，按维度-视角分块可读
  - Print 样式回归
- **Rollback**：revert 一个 PR，模板与 Excel 独立

### Phase 2 T11 · 回归 + 文档

- **Trigger**：T9+T10 合入并线上跑 1 个 daily 周期
- **Scope**：
  - `tests/test_metric_semantics.py` / `tests/test_v3_modes.py` 补全量回归
  - `docs/devlogs/D019-phase2-trend-deepening.md` 新建
  - `AGENTS.md` 同步 Phase 2 约束
- **Exit**：全量 pytest + 文档 review 通过
- **Rollback**：不涉及代码行为，只 revert 文档

---

## 3. 阻塞关系矩阵（谁卡谁）

| 要做的事 | 必须先做完 |
|---|---|
| Stage A 修 2（模板组件级 status） | 修 1（健康指数统一）+ 后端 competition 组件级产出 |
| Stage A 修 3（关系词对账） | T0 已上（这是 hotfix 的延续加固） |
| Stage A 修 6（fallback 感知 semantics） | 修 5（扩大违禁词）— 因为 fallback 文案也要接受同一检测 |
| Stage B 修 7（artifact 路径） | Stage A 完成（避免路径改动与 schema 改动混淆回滚） |
| Phase 2 T9 | Stage A + Stage B + 契约冻结期 3 天 |
| Phase 2 T10 | T9 |
| Phase 2 T11 | T9 + T10 + 1 个 daily 周期验证 |

---

## 4. 常见翻车点 + 规避

| 翻车点 | 规避动作 |
|---|---|
| "顺手" 在 Stage A 改了 `change_digest.summary` 的字段名 | **锁死 schema**：把 `summary` 的 key 名在 `tests/test_report_snapshot.py` 里硬断言，改名立即测试红 |
| T9 扩展趋势 KPI 时新建了一套 `kpis_v2` 字段 | grep `kpis_v2` 阻断；Phase 2 验收标准明文 "Phase 2 的增强没有引入第二套 KPI" |
| 模板为了 UI 美观直接从 `analytics.window.new_reviews` 取数 | CI grep `analytics\.window` / `analytics\._trend_series` / `cumulative_kpis` 在模板目录必须 0 命中 |
| Phase 2 Chart.js 渲染 36 图导致页面卡死 | 用 IntersectionObserver 或 tab 切换时再实例化 Chart.js；T10 里必须跑一次 devtools profiling |
| 本地数据库不是生产生活数据，Stage B artifact resolver 回归拿不到真实"旧绝对路径" | 预发环境直接 SQL 改一条 `workflow_runs.analytics_path = 'C:\旧机器\不存在\xxx.json'` 模拟失效 |
| LLM API 故障连续命中 fallback，用户以为 Stage A 没修好 | Stage A 合入后立即跑一次"空 API KEY + bootstrap" 冒烟，确认 fallback 输出不含"今日新增"/"新增评论" |
| 跨机器路径迁移测试忘了 Linux 容器 | 本地 Windows 测试 + Docker 容器里跑一次 `_resolve_artifact_path` + `_artifact_db_value`，断言 `/` 和 `\` 都能处理 |

---

## 5. 每日节奏建议

| 工作日 | 动作 |
|---|---|
| 每天早 10:00 | 查昨天 daily run 产物：KPI 一致？LLM 排序词正常？无 "今日新增" / "新增评论"？|
| 每天下午收尾 | 本 Stage 的 grep 门禁全跑一次 |
| 周五 | 周回顾：Stage 进度 vs 规划；是否需要改下周节奏 |
| 周末 | 不做 schema / prompt 改动，只允许改周边（CSV / 站点规则 / 文档） |

---

## 6. 决策（已锁定 · 2026-04-24）

| # | 决策 | 选择 | 影响 |
|---|---|---|---|
| 1 | T0 hotfix 时间 | **今晚**（Day 0 内） | 生产当晚止血；Stage A Day 1 照常推进 |
| 2 | 健康指数统一方案 | **A · 统一贝叶斯** | Stage A 修 1 需同步改 tooltip + 趋势聚合 + 小样本收缩；工作量大但用户侧口径干净 |
| 3 | Phase 2 启动时机 | **Day 5** | Stage A 合入后契约冻结期压缩到 3 daily 周期完成即启动 T9，不等 Stage B 完全稳定 |

衍生的节奏调整：
- **Stage B 与 Phase 2 T9 可并行**（Stage B 改 `workflows.py` / `report_snapshot.py` 的 artifact 路径和 kpi 消歧；T9 改 `report_analytics.py` 的 `_build_trend_digest` 扩展——两者文件不重叠）
- **契约冻结仍然覆盖 change_digest / trend_digest / kpis 的键名**；Stage B 的 kpis 消歧（`negative_review_rate` 迁走）属于键名变更，**必须在 Stage A 合入后立即完成**，避免冻结期内破例

---

## 7. 最终交付清单

Phase 2 完成后，`docs/reviews/` 目录应有：

- `claude-review.md`（已存在）
- `codex-review.md`（已存在）
- `best-practice.md`（已存在）
- `phase2-audit.md`（已存在）
- `execution-plan.md`（本文）
- `D019-phase2-trend-deepening.md`（Phase 2 完成时新建）
- `post-mortem.md`（如 Phase 2 过程中有意外 rollback，需新建）

`AGENTS.md` 同步 Phase 2 新增约束（辅图来源 / kpis 不得第二套 / 关系词对账器必开启）。
