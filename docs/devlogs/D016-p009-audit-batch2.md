# D016 — P009 审计批 2 修复（14 项）

**日期**: 2026-04-17
**关联计划**: `docs/plans/P009-audit-batch2-fixes.md`
**关联 commits**: `4ec9c09`（baseline）→ `d9b5738`（F4），分支 `fix/p009-audit-batch2`，共 19 commits（14 实施 + 5 review 精修）

## 概述

D015 完成 P008 审计的 X1 + 8 🔴 后，对项目做第二轮端到端审计（4 并行 agent 覆盖每日任务核心 / 未提交改动 / P008 报告系统遗留 / 跨链路盲点），发现 **4 🔴 + 6 🟡 + 4 P008 D015-follow-up** 共 14 项需修复。本批采用 TDD + subagent-driven-development 流水线逐 Task 实施：每 Task 走 implementer → spec reviewer → code-quality reviewer，5 个 Task 触发 reviewer 反馈追加精修 commit。最终 147 个 P008 测试全绿，全套 **714 passed / 0 failed**（`test_v3_modes.py` 2 个 pre-existing 失败独立回归，与 P009 无关）。

## 已修复清单

| # | ID | 文件:行 | 症状 | 修复要点 |
|---|-----|--------|-----|----------|
| 1 | B1 | `models.py:571` | `mark_task_lost` 把 `_NOW_SHANGHAI` SQL 表达式当 param 绑定，存入字面值 | 改用 `now_shanghai().isoformat()` 作为 fallback（D015 遗留 #1 闭环） |
| 2 | B4 | `scrapers/base.py` `_launch_with_user_data` | `stderr=PIPE` 无消费者，Chrome 写满 64KB buffer 后阻塞 `poll()` | 加 daemon drain 线程 + 1 MB 环形缓冲；早退诊断取尾 500 字节 |
| 3 | B5 | `workflows.py:932` + `models.py` migration | 服务重启后 `sync_new_skus` 重跑耗 LLM | 加 `workflow_runs.category_synced` 列 + `_maybe_sync_category_map` 幂等辅助；`finally` 保证 flag 置位 |
| 4 | B6 | `workflows.py` stalled 分支 | 翻译 stalled 强行出报告，无覆盖率保护 | 新增 `TRANSLATION_COVERAGE_MIN=0.7` + `_translation_coverage_acceptable`/`_translation_progress_snapshot`；不达阈值 → `_move_run_to_attention` |
| 5 | I1 | `category_inferrer.py` `infer_categories` | 单批 LLM 异常阻断整个循环，丢失已成功批次 | 每批 `try/except` + `logger.exception`；失败 SKU 走下游 "other" 降级 |
| 6 | I2 | `category_inferrer._append_csv` | CLI 与服务并发写 CSV 无锁 | O_CREAT\|O_EXCL 哨兵文件锁 + `CategoryMapLocked(TimeoutError)`；50 ms 轮询，默认 5 s 超时；`sync_new_skus` 显式 `except` 降噪为 WARNING |
| 7 | I3 | `models.cleanup_old_notifications` + `NotifierWorker` | 函数存在但从未调用，表无限增长；且 cutoff 用 UTC 与 Shanghai 约定偏 8 h | 改用 `now_shanghai() - timedelta(days=...)`；`NotifierWorker._maybe_cleanup` 每 `NOTIFICATION_CLEANUP_INTERVAL_S=3600s` 一次（monotonic gating，失败不致命） |
| 8 | I4 | `mark_notification_failure` + `tasks` 表 | `notified_at` 仅写成功，失败 task 的"未尝试"vs"已失败"不可区分 | 新列 `tasks.notified_attempt_at`；每次失败（含 retryable 分支）都写入；`notified_at` 保留成功语义 |
| 9 | I5 | `workflows._logical_date_window` | 返回硬编码 `+08:00` 字面串 | 改返回 `tuple[datetime, datetime]` tzinfo-aware（`config.SHANGHAI_TZ`）；单一 caller 在 use-site `.isoformat()`；DB 格式字节相同 |
| 10 | I6 | `WorkflowWorker._run` 内循环 | 紧自旋 `while process_once()` 无 min sleep | `stop_event.wait(0.05)` 可中断 sleep；测试双边界断言 `5 ≤ iters ≤ 20 / 0.6s` |
| 11 | F1 | `generate_full_report_from_snapshot` / `_render_full_email_html` | D015 X1 用 `_meta` fallback 可维护性差（D015 #3） | 添加 kw-only `report_tier: str \| None = None`；优先级：显式 > `_meta` > WARNING+默认 `"daily"`（WARNING 含 run_id/logical_date 上下文）；3 个 known-tier 调用点迁移 |
| 12 | F2 | `tests/test_p008_phase4.py` | R2 `recurrent→receding` / R3 `recurrent→dormant` 缺单测（D015 #4） | 增 2 + 1 显式 lifecycle 测试，断言 `state` + `history[].reason` 双维度 |
| 13 | F3 | `models.py` + `report_snapshot._inject_meta` | `actual==expected` 下 `is_partial` 从不触发（D015 #5） | 新 `get_earliest_review_scraped_at()`；cold-start 判定：空表 or earliest > window_start → `is_partial=True`；`_meta.earliest_review_scraped_at` 写入；calendar 回退保留 |
| 14 | F4 | `category_inferrer._build_messages` + `analytics_executive._PROMPT` | confidence / neg_rate 单位歧义（D015 #6） | `confidence` 明示 `[0.0, 1.0] NOT a percentage`；`own_negative_review_rate` 明示 `fraction`，阈值改 `> 0.05（即 > 5%）` |

## 关键设计决策

- **T3 幂等标志位于 workflow_runs 而非状态推断**：原 `if run["status"] != "reporting"` 在进程重启 + 状态回退场景会漏执行；`category_synced` 列是权威标志，`finally` 保证即便 sync 抛出也置位，杜绝"sync 失败 → 下轮重跑 → 再失败"的重试风暴。
- **T4 覆盖率 gate 只在 stalled 时触发**：翻译仍在等待窗口内时 gate 透明放行（避免过早拦截）；只有等待超时（`_translation_wait_expired`）后才检查覆盖率，不达则 `_move_run_to_attention` 让人介入。
- **T6 锁策略：sentinel-file + TimeoutError**：跨平台（Win/Linux 不用 `fcntl`/`msvcrt` 分叉）；`CategoryMapLocked` 继承 `TimeoutError`，`sync_new_skus` 专门 `except` 降噪为 WARNING（避免 traceback 噪音），一般 `Exception` 继续走 `logger.exception`。**遗留**：无 stale-lock recovery，进程 KILL 后需人工 `rm` 哨兵——低频（每日一次）风险可接受，列入 follow-up。
- **T7 tz 对齐**：`cleanup_old_notifications` 从 `datetime.now(timezone.utc)` 改 `now_shanghai()`。语义是**更正确**（`notification_outbox.updated_at` 就是 Shanghai-local 字符串），不是 regression；diff 上看是 UTC→Shanghai 的 8 h 切换，本意是让字符串比较对齐。
- **T9 tzinfo-aware 而非字符串**：`_logical_date_window` 单一 caller，改动最小；所有调用点在 use-site `.isoformat()`，DB 列字节相同但 Python 端从此没有 naive/aware 混用。
- **T11 Option A (显式参数) 替代 D015 Option B (_meta fallback)**：`_meta` 读取逻辑保留以向后兼容，但 3 个 known-tier 调用点显式传参后，意图清晰，未来 grep 有据可依。
- **T13 cold-start 真正检测**：`calendar.monthrange` 计算 expected 不足以侦测部署未满期场景；引入 `earliest_review_scraped_at`，若 earliest > window_start 则 `is_partial=True`。影响：首次部署后的每个 run 会被标记 partial，模板已在 P008 D015 下有冷周提示，暂不需要额外 UI 改动。

## 审计流程与收益

- **4 并行探查 agent**（每日任务核心 / 未提交改动 / P008 遗留 / 端到端盲点）交叉产出 14 个候选，细读核验时**驳回 2 个伪报**：B2（`update_workflow_run` 其实支持 `report_tier`）、B3（`task_manager.py:195/281` 实际从 task.params 写入 ownership）。审计报告初稿必须二次核验，不能直接入计划。
- **subagent-driven-development 流水线**：每 Task 三段式 implementer → spec reviewer → code-quality reviewer。14 个 Task 中 **5 个**触发 reviewer 反馈精修（I1 下游 contract 注释、I2 模块级 import + TimeoutError + 静默降噪、I3 模块级 time + docstring、I4 retryable-path 测试、F1 WARNING 加 run_id 上下文 + 优先级链测试）。reviewer 反馈命中率 ~36%，低于 P008 的 67%——成熟度提升，但仍值得两阶段 review。
- **TDD 严格**：每 Task 必写失败测试 → 最小补丁 → 验证 → commit。测试基线从 684 增长到 714（+30 个 P009 专属 + 3 个 lifecycle R2/R3）。

## 测试

- 新增 30 tests 覆盖 14 项修复（pure 函数 + DB 集成 + 行为边界）
- P009 suite: `tests/test_p009_audit_batch2.py` 24/24 pass
- P008 phase4 R2/R3: 3/3 新增 pass，49/49 全部 pass
- 全套: **714 passed / 0 failed**（`test_v3_modes.py` 2 个 pre-existing 失败与 P009 无关，已登记）
- 回归无新增失败

## 文件清单

| 文件 | 操作 |
|------|------|
| `docs/plans/P009-audit-batch2-fixes.md` | 新增（plan 本身） |
| `qbu_crawler/config.py` | 修改（+`TRANSLATION_COVERAGE_MIN`、`NOTIFICATION_RETENTION_DAYS`、`NOTIFICATION_CLEANUP_INTERVAL_S`） |
| `qbu_crawler/models.py` | 修改（mark_task_lost 时间戳、+`category_synced` 迁移、+`notified_attempt_at` 迁移、`cleanup_old_notifications` Shanghai tz、+`get_earliest_review_scraped_at`、`mark_notification_failure` 联动 tasks） |
| `qbu_crawler/scrapers/base.py` | 修改（Chrome stderr drain 线程） |
| `qbu_crawler/server/category_inferrer.py` | 修改（批次异常隔离、CSV 文件锁、prompt 单位澄清、I2 review 精修） |
| `qbu_crawler/server/workflows.py` | 修改（`_maybe_sync_category_map`、翻译覆盖率 gate、`_logical_date_window` tzinfo、`_run` min sleep） |
| `qbu_crawler/server/report_snapshot.py` | 修改（显式 `report_tier` 参数 + WARNING 上下文、cold-start `is_partial` 经 earliest_review） |
| `qbu_crawler/server/notifier.py` | 修改（`NotifierWorker._maybe_cleanup` + 模块级 `time` 导入） |
| `qbu_crawler/server/analytics_executive.py` | 修改（`_PROMPT` 差评率单位澄清） |
| `tests/test_p009_audit_batch2.py` | 新增（24 tests） |
| `tests/test_p008_phase4.py` | 修改（+3 R2/R3 lifecycle tests） |
| `tests/test_p008_phase3.py` | 修改（2 legacy tests 追加 pre-window review 种子，适配 cold-start 新语义） |
| `tests/test_notifier.py` | 修改（+3 cleanup/notified_attempt_at tests） |
| `tests/test_v3_modes.py` | 修改（lambda mocks 接收 `**kwargs` 以适配 `report_tier` 新参数） |
| `CLAUDE.md` | 修改（新增 3 个 env 配置行） |
| `docs/devlogs/D016-p009-audit-batch2.md` | 新增（本文件） |

## 遗留事项 / Follow-ups

下一批次处理（超出本计划范围）：

1. **`product_snapshots` 写入从未读**：需先决策保留（对账用）vs 删除
2. **`REPORT_DIR` 不跟随 `QBU_DATA_DIR`**：生产环境若仅设 `QBU_DATA_DIR`，报告会生成到项目目录
3. **Cross-tier severity 不一致**：daily/weekly/monthly 均从 `reviews` 独立聚合，同一 issue 在不同 tier 可能 severity 矛盾；`product_snapshots` 未被跨 tier 消费
4. **Translation worker DB-as-Queue 无 claim/lease**：worker 崩溃重启会重复翻译
5. **DST 边界防护**：Shanghai 无 DST，短期可忽略；跨国部署时再处理
6. **I2 stale-lock recovery**：`category_map.csv.lock` 无 staleness 检测（低频可接受）
7. **I6 min-sleep 50ms hardcoded**：若需调优可提为配置常量
8. **`dual-perspective` 混合版本审计**：`_meta` 未记录 cumulative vs window 数据来源差异
9. P008 原始审计推迟的 10 🟡 + 9 🟢 observable 项（详见 `docs/plans/P008-audit-fixes-implementation.md` § Out of scope）

## 数据正确性复核清单（生产前手动 verify）

- `mark_task_lost` 被调用后：DB 中 `tasks.finished_at` 为 ISO-8601 时间戳（非 `"datetime('now', '+8 hours')"` 字面值）
- 服务进程重启后：同一个 run 的 `sync_new_skus` 不会再次 LLM 调用（查 `workflow_runs.category_synced=1`）
- 翻译 worker 手动停止 15 分钟后触发 daily run：`translated / total < 0.7` 时 run 状态为 `needs_attention`
- 首次部署后次日 run 的 `_meta.is_partial == True`（cold-start 检测）
- 首次 monthly run 结束 30 天后：`notification_outbox` 中 delivered 记录被清理
- `mark_notification_failure(retryable=True)` 和 `retryable=False` 都更新 `tasks.notified_attempt_at`
- Chrome 用户数据启动失败时：RuntimeError 消息包含 stderr 尾 500 字节（非空）
- 并发调用 CSV 追加：其中一方 raise `CategoryMapLocked`（继承自 `TimeoutError`）
- 月报 LLM 差评率 bullet："差评率 X.Y%" 不再出现 0.0% 漂移（prompt 单位明确）
