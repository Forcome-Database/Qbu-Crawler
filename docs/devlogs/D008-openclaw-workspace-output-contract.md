# D008 OpenClaw Workspace Output Contract

## 背景

在 `openclaw-hybrid-automation` 分支中，workspace 已经完成了新的 deterministic workflow 切换：

- daily 主路径改为 embedded scheduler + workflow
- 通知主路径改为 outbox
- heartbeat 改为 inspection-only

但在这次切换过程中，旧版 workspace 里一部分高价值的“输出格式契约”和“任务表达纪律”被弱化了，导致：

- 任务提交、进度、完成反馈的格式不稳定
- task / notification / report 三种状态容易混淆
- 数据分析回复缺少统一模板

## 本次调整

本次不恢复旧版控制流，只恢复并重组旧版中真正有价值的内容：

1. `workspace/TOOLS.md`
   - 增加 authoritative path 说明
   - 增加对外输出契约
   - 增加任务、daily、产品分析、差评分析、竞品对比模板

2. `workspace/AGENTS.md`
   - 强化 ad-hoc 提交 SOP
   - 明确 query routing
   - 强化 task / notification / report 状态拆分表达
   - 明确 structured business output 必须遵循 `TOOLS.md`

3. `skills/csv-management/SKILL.md`
   - 保留新 schema：`max_pages`、`review_limit`
   - 吸收旧版更清晰的 SOP 结构：
     输入类型判断 -> ownership 确认 -> CSV 路由 -> 去重更新 -> 输出确认

## 刻意不恢复的旧内容

- heartbeat 驱动 daily/report 主流程
- `active-tasks.json` 作为 authoritative state
- `memory/*.md` 作为任务追踪主机制
- 旧版 cron-authoritative `daily-scrape-submit`
- 旧版 state-driven `daily-scrape-report`

## 结果

workspace 现在的分层更清晰：

- `AGENTS.md`
  只放角色、硬规则、路由、任务纪律
- `TOOLS.md`
  只放工具速查、状态解释、输出契约、模板
- `HEARTBEAT.md`
  只放 inspection checklist
- skills
  只放具体 SOP

这样既保留了旧版中“表达稳定、格式统一”的优点，又不把已经淘汰的控制流重新带回来。
