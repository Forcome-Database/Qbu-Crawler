# D015 — P008 审计 + 9 项必修 Bug 修复

**日期**: 2026-04-17
**关联计划**: `docs/plans/P008-audit-fixes-implementation.md`（本次新增）、`docs/plans/P008-phase{1,2,3,4}-implementation.md`
**关联 commits**: 9f9f12c → 9bb793b（feature 分支 `fix/p008-audit` 已合入 master，共 16 实施 commits + 1 plan + 1 merge）

## 概述

对 P008 Phase 1-4 已交付代码做系统审计（4 个并行 agent 分 Phase 审查），发现 **26 个 issue**（7 🔴 + 10 🟡 + 9 🟢）。本次修复聚焦 **X1 跨 Phase Bug + 8 个 🔴 必修级**，通过 TDD + subagent-driven 流水线逐 Task 实施。每个 Task 走 implementer → spec reviewer → code quality reviewer，6 个 Task 触发 reviewer 反馈并追加精修 commit。最终 147 个 P008 测试全绿，全套 726/728（2 个 pre-existing 失败与本次无关）。

## 已修复清单

| # | Bug ID | 症状 | 修复要点 |
|---|--------|-----|----------|
| 1 | P4-B1 | `_classify_stance` 的 `neg_rate > 5` 永不触发（分数/百分比混淆） | 阈值改 `> 0.05` + 修正 drift 测试数据（`12.0` → `0.12`） |
| 2 | P4-B2 | 高管 bullet 渲染 "差评率 0.0%"（应 4.2%） | `round(neg_rate * 100, 1)` |
| 3 | P4-B3 | 周报趋势图 `neg_series` 存分数但 Y 轴标 `(%)` | `float(neg) * 100` + `round(..., 2)` 避免 IEEE 754 显示噪声 |
| 4 | X1 | `load_previous_report_context` 跨 tier 污染（4+1 个调用点漏传 `report_tier`） | Option B：`generate_full_report_from_snapshot` / `_render_full_email_html` 读 `snapshot["_meta"]["report_tier"]`，其它 3 处显式传参；`_meta`-absent 时加 WARNING log 保证可观测 |
| 5 | P1-C1 | `safety_incidents` translator 重试产生重复行 | `evidence_hash UNIQUE` + `INSERT OR IGNORE` + 迁移前先 `DELETE ... GROUP BY evidence_hash` 防 `IntegrityError` |
| 6 | P1-C2 | `safety_incidents` 用 UTC，与项目 Shanghai 约定偏 8h | DDL default 和 INSERT 均改 `_NOW_SHANGHAI`（`datetime('now', '+8 hours')`）；测试用 `datetime.now(timezone.utc)` 避免 3.12+ 弃用 |
| 7 | P2-F2 | 安全信号仅改标题前缀，`EMAIL_RECIPIENTS_SAFETY` 从未消费 | 追加分发到 SAFETY 通道，去重 primary 已含地址；二次发送失败 try/except + WARNING，不污染 primary 成功态；`recipients` 返回值合并 extra 保证审计完整 |
| 8 | P3-I2 | `_inject_meta` 的冷启动 `is_partial` 参数从未传入 | `freeze_report_snapshot` 按 tier 计算 `expected_days`（weekly 固定 7，monthly 用 `calendar.monthrange` 避免 Feb 误判）、`actual_days`；解析失败 WARNING log |
| 9 | P3-I3 | V3 模板声称冷周提示缺失 | **审计事实纠正**：提示已存在，但措辞锁死"本周"。升级为 tier-neutral 文案"本期窗口内无新评论变动"+ `empty-state` CSS polish |

## 关键设计决策

- **X1 修复选 Option B（`_meta` 读取）而非 Option A（签名加参数）**：避免级联改动 `_generate_weekly_report` / `_generate_monthly_report` / daily 路径等 3+ 个调用者，但需配合 WARNING log 保证 `_meta`-absent 场景可观测
- **`safety_incidents` 去重策略**：UNIQUE `evidence_hash` + `INSERT OR IGNORE` + 迁移前 `DELETE` 先清历史重复。迁移列表顺序严格：先 DELETE 再建索引
- **Task 9 审计事实纠正**：原 audit 报告说冷周提示缺失，实际代码早有渲染。本次改为措辞升级而非新增，记录以校准未来审计
- **Feb false-positive 修复范围**：`calendar.monthrange` 避免 Feb 误标，但暴露了更深问题——现行 `actual=data_until-data_since` 在完整 tier 窗口下永远等于 `expected`，真正 cold-start 检测需引入 `earliest_review_scraped_at`（超出本次范围，列为 follow-up）

## 审计流程与收益

- **4 个并行 Phase agent 审查**：每 agent 独立读 plan + 代码 + 测试，按 🔴/🟡/🟢 分级输出结构化 findings。交叉对照时发现 X1 是跨 Phase 共性问题（4+1 处，审计报告仅列 4 处）
- **subagent-driven 实施流水线**：每 Task 三段式（implementer → spec reviewer → code quality reviewer）。6 个 Task 因 reviewer 反馈触发 2nd commit 精修（IEEE 754 round、观测 log、migration IntegrityError、tz-aware datetime、safety failure 隔离、Feb calendar.monthrange）。review 反馈命中率 67%，说明两阶段 review 投入值得
- **审计事实自检**：3 个 spec reviewer 独立用 `git show` / `grep` 核对实现而非信任 implementer 报告，暴露了审计原始结论里 2 处错报（X1 实际 5 处、Task 9 冷周提示已存在）

## 测试

- 新增 27 tests across P008 phase1-4 文件（含正反两面：dedup、overlap、failure isolation、Feb 完整月、monthly cold-start）
- P008 suite: 147/147 pass
- 全套: 726 pass, 2 pre-existing failures (`test_v3_modes.py::test_change_mode_detected` + `test_change_mode_includes_snapshot_hash`)

## 文件清单

| 文件 | 操作 |
|------|------|
| `docs/plans/P008-audit-fixes-implementation.md` | 新增 |
| `qbu_crawler/models.py` | 修改（UNIQUE index + 迁移 + DDL tz + INSERT OR IGNORE + `_NOW_SHANGHAI`） |
| `qbu_crawler/server/analytics_executive.py` | 修改（stance 阈值 + bullet 百分比） |
| `qbu_crawler/server/report_snapshot.py` | 修改（X1 5 处 tier 传参 + 2 处 WARNING log + 冷启动 meta + 安全通道分发 + neg_series * 100 * round） |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 修改（冷周提示措辞升级 + CSS polish） |
| `tests/test_p008_phase{1,2,3,4}.py` | 追加 27 tests |

## 遗留事项 / Follow-ups

超出本批修复范围，建议起下一 plan 统一处理：

1. **`models.py:571` `mark_task_lost` 的 `_NOW_SHANGHAI` 参数绑定 Bug**：`finished_at = finished_at or _NOW_SHANGHAI` 把 SQLite 表达式字符串当参数绑定，存入 DB 的是字面值而非计算值（confidence 100，既存 Bug，Task 5 review 发现）
2. **V3 modes 2 个 pre-existing 失败**：`test_change_mode_detected` + `test_change_mode_includes_snapshot_hash`，独立回归，不在本次范围
3. **`generate_full_report_from_snapshot` 显式 `report_tier` 参数**：当前 Option B 用 `_meta` fallback，可维护性较弱；加参数可让调用者明确声明意图（原 Task 4 Plan Option A）
4. **`recurrent → receding (R2)` / `recurrent → dormant (R3)` 无显式单测**（D014 已登记）
5. **真正的冷启动 `is_partial` 检测**：当前 `calendar.monthrange` 只修 Feb 误判，但 `actual == expected` 对完整窗口永远成立，从不触发 partial。若需真正冷启动（部署不满期），应引入 `earliest_review_scraped_at`（spec section 6.1 原文）
6. **LLM `_PROMPT` 的差评率单位说明歧义**：prompt 里写 `差评率 > 5%`，实际数据是分数（0-1）。需澄清为 `differential rate (fraction 0-1, e.g. 0.05 == 5%)` 避免 LLM 依据数值与阈值混淆

以及审计报告中未修复的 10 🟡 / 9 🟢 级 issue（详见 `docs/plans/P008-audit-fixes-implementation.md` § "Out of scope"）。

## 数据正确性复核清单（生产前手动 verify）

- 最近一次 weekly run：Tab 2 变化对比前一 **weekly**（非 daily）
- monthly stance：造 `neg_rate = 0.06` 场景应进入 `needs_attention`
- 月报高管摘要 bullet："差评率 X.Y%" 不再显示 "0.0%"
- 月报趋势图：Y 轴显示 2-8% 级数值（非 0.02-0.08）
- `safety_incidents`：抽样行 `detected_at` 应为 Shanghai 时间（北京时区）
- 触发同一 review 重复 safety 写入：`COUNT(*) = 1`
- 含 safety_keyword 信号的日报：`EMAIL_RECIPIENTS_SAFETY` 收件人确实收到
- 首次 monthly run（若窗口不满）：`_meta.is_partial == True`
- 空窗口 weekly HTML：Issues tab 顶部显示"本期窗口内无新评论变动"
