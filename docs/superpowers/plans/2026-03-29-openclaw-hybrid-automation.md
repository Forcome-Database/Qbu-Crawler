# OpenClaw 混合自动化重构 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将每日提交、临时任务回执、报表生成改造成基于 Crawler Host 的确定性工作流，同时把 OpenClaw 固定在“自然语言入口 + 消息能力 + 智能摘要”角色上。

**Architecture:** 不再新增公开 workflow 写接口；daily-submit 由 Crawler Host 上的 `qbu-crawler serve` 内嵌 scheduler 触发。服务端新增 task liveness、workflow idempotency、immutable report snapshot、notification outbox。OpenClaw Host 提供 hardened bridge 和 AI sidecar，并通过版本化 `openclaw.json` 模板消除配置漂移。

**Tech Stack:** Python (FastAPI, SQLite, background workers, openpyxl), OpenClaw CLI, DingTalk channel, in-process scheduler, Markdown docs, shell deployment assets

---

## File Structure

**Create:**
- `qbu_crawler/server/workflows.py` — workflow orchestration、reconcile、run 推进
- `qbu_crawler/server/notifier.py` — outbox worker、claim/reclaim、bridge sender
- `qbu_crawler/server/daily_inputs.py` — CSV 读取、校验、分组、错误归档
- `qbu_crawler/server/report_snapshot.py` — report snapshot 生成与加载
- `qbu_crawler/server/runtime.py` — 管理 TaskManager / notifier / workflow worker 的统一生命周期
- `qbu_crawler/server/openclaw/bridge/app.py` — OpenClaw Host 上的 hardened notify bridge
- `deploy/openclaw/systemd/qbu-openclaw-notify-bridge.service` — OpenClaw Host bridge service
- `deploy/openclaw/openclaw.json5.template` — OpenClaw 主配置模板
- `deploy/openclaw/sync_openclaw_assets.sh` — 同步 `openclaw.json` / workspace / plugin 的脚本
- `deploy/openclaw/README.md` — OpenClaw 部署与校验文档
- `tests/test_workflows.py` — workflow、幂等、reconcile 测试
- `tests/test_notifier.py` — outbox、bridge、reclaim 测试
- `tests/test_daily_inputs.py` — CSV 解析与分组测试
- `tests/test_report_snapshot.py` — snapshot 与 fast/full report 一致性测试

**Modify:**
- `qbu_crawler/config.py` — 新增路径、feature flag、worker、bridge、snapshot 配置
- `qbu_crawler/models.py` — 扩展 `tasks`，新增 `workflow_runs`、`workflow_run_tasks`、`notification_outbox`
- `qbu_crawler/server/task_manager.py` — 写 liveness，改为 outbox 入队，不再假成功
- `qbu_crawler/server/report.py` — 从 snapshot 生成 fast/full report
- `qbu_crawler/server/app.py` — 使用统一 runtime / lifespan
- `qbu_crawler/server/mcp/tools.py` — 新增只读 workflow / notification 查询工具，收敛兼容路径
- `qbu_crawler/server/openclaw/README.md` — 更新职责边界与部署方式
- `qbu_crawler/server/openclaw/workspace/AGENTS.md` — 更新为“入口 + 分析 + 非关键 AI sidecar”
- `qbu_crawler/server/openclaw/workspace/HEARTBEAT.md` — 只做巡检、补偿、异常摘要
- `qbu_crawler/server/openclaw/workspace/TOOLS.md` — 新增 run/snapshot/outbox 查询说明
- `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md` — 改为手动兜底 skill
- `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-report/SKILL.md` — 改为 AI digest skill
- `.env.example` — 新增 feature flag、snapshot、bridge、worker 配置
- `main.py` — 增加本机 CLI 子命令：`workflow daily-submit`
- `AGENTS.md` — 更新项目架构说明
- `tests/test_report.py` — 修复现有断裂基线
- `tests/test_translator.py` — 修复现有断裂基线

**Compatibility, but behind explicit flags:**
- `check_pending_completions`
- `mark_notified`
- `active-tasks.json`

要求：

- 兼容路径只能在 `legacy` 或 `shadow` 模式下启用
- 生产同一时刻只允许一个 authoritative sender

---

## Chunk 0: 前置清障

### Task 1: 修复现有测试基线

**Files:**
- Modify: `tests/test_report.py`
- Modify: `tests/test_translator.py`

- [ ] **Step 1: 运行现有相关测试，记录失败基线**

Run:

`uv run pytest tests/test_report.py tests/test_translator.py -v`

Expected:

- 明确记录当前失败用例和断裂原因。

- [ ] **Step 2: 修正 `tests/test_report.py`**

修正方向：

- 去掉对真实图片 URL 的依赖
- 更新已过时的列号/结构断言
- 把图片相关断言改为 mock + snapshot 友好的断言

- [ ] **Step 3: 修正 `tests/test_translator.py`**

修正方向：

- 从不存在的 `_process_batch()` 切换到当前实现暴露的方法
- 按 `_process_round()` / `_translate_batch()` 的现状更新断言

- [ ] **Step 4: 重新运行基线测试**

Run:

`uv run pytest tests/test_report.py tests/test_translator.py -v`

Expected:

- 现有基线恢复为绿。

### Task 2: 明确部署前提与 feature flag

**Files:**
- Modify: `qbu_crawler/config.py`
- Modify: `.env.example`
- Modify: `qbu_crawler/server/openclaw/README.md`

- [ ] **Step 1: 新增 feature flag**

最少加入：

- `NOTIFICATION_MODE=legacy|shadow|outbox`
- `DAILY_SUBMIT_MODE=openclaw|embedded`
- `REPORT_MODE=legacy|snapshot_fast_full`
- `AI_DIGEST_MODE=off|async`

- [ ] **Step 2: 明确网络与部署前提**

在 README 中写清：

- daily-submit 只允许在 Crawler Host 本机执行
- bridge 只允许私网来源
- `/mcp` 与 `/api` 的访问边界是上线前提

- [ ] **Step 3: 写配置测试**

Run:

`uv run pytest tests/test_workflows.py -k config -v`

Expected:

- feature flag 默认值与解析逻辑通过。

---

## Chunk 1: 数据模型、幂等与恢复骨架

### Task 3: 扩展 `tasks` 表的活性字段

**Files:**
- Modify: `qbu_crawler/models.py`
- Modify: `qbu_crawler/server/task_manager.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: 为 `tasks` 增加恢复相关字段**

新增迁移字段：

- `updated_at`
- `last_progress_at`
- `worker_token`
- `system_error_code`

- [ ] **Step 2: 在 `TaskManager` 持久化路径中更新 liveness**

要求：

- 任务开始时写 `worker_token`
- 每次进度持久化刷新 `updated_at`
- 任务终态写 `finished_at`

- [ ] **Step 3: 新增 stale running task 的 reconcile 查询与更新函数**

例如：

- `list_stale_running_tasks(...)`
- `mark_task_lost(...)`

- [ ] **Step 4: 写测试**

覆盖：

- `running` 任务超过阈值后可被标记为系统失败
- reconcile 后任务不再永久悬挂

- [ ] **Step 5: 运行测试**

Run:

`uv run pytest tests/test_workflows.py -k task_liveness -v`

Expected:

- stale task 恢复测试通过。

### Task 4: 设计 `workflow_runs` / `workflow_run_tasks` / `notification_outbox`

**Files:**
- Modify: `qbu_crawler/models.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: 创建 `workflow_runs` 并加入幂等字段**

必须包含：

- `logical_date`
- `trigger_key`
- `data_since`
- `data_until`
- `snapshot_at`
- `snapshot_path`
- `snapshot_hash`
- `excel_path`
- `requested_by`
- `service_version`

并给 `trigger_key` 建唯一约束。

- [ ] **Step 2: 创建 `workflow_run_tasks` 并加入唯一约束/FK**

要求：

- `UNIQUE(run_id, task_id)`
- 明确 FK 关系

- [ ] **Step 3: 创建 `notification_outbox` 并加入 claim/reclaim 字段**

必须包含：

- `dedupe_key`
- `payload_hash`
- `claimed_at`
- `claim_token`
- `lease_until`
- `bridge_request_id`
- `last_http_status`
- `last_exit_code`
- `created_at`
- `updated_at`

- [ ] **Step 4: 写模型测试**

覆盖：

- 同一 `trigger_key` 不可重复建 run
- 同一 `dedupe_key` 不可重复入队
- claim/reclaim 字段可正常流转

- [ ] **Step 5: 运行测试**

Run:

`uv run pytest tests/test_workflows.py tests/test_notifier.py -k \"idempotency or outbox\" -v`

Expected:

- 幂等与 outbox 模型测试通过。

---

## Chunk 2: Crawler Host 本机调度

### Task 5: 抽离 daily input 解析

**Files:**
- Create: `qbu_crawler/server/daily_inputs.py`
- Test: `tests/test_daily_inputs.py`

- [ ] **Step 1: 实现 CSV 读取与校验**

能力包括：

- 读取两个 CSV
- 校验表头
- 校验 URL 与 ownership
- 分类页/产品页分组
- 对无效行生成错误摘要

- [ ] **Step 2: 写测试**

覆盖：

- 空文件
- 非法 ownership
- 混合站点
- 按 ownership / 任务类型分组

- [ ] **Step 3: 运行测试**

Run:

`uv run pytest tests/test_daily_inputs.py -v`

Expected:

- 输入解析测试通过。

### Task 6: 用本机 CLI 替代 workflow 写 API

**Files:**
- Modify: `main.py`
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `qbu_crawler/server/runtime.py`
- Modify: `qbu_crawler/config.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: 给 CLI 增加 `workflow daily-submit` 子命令**

命令必须支持：

- `--logical-date`
- 幂等返回已有 run
- dry-run

- [ ] **Step 2: 在 `workflows.py` 中实现 `submit_daily_run()`**

流程：

1. 生成 `trigger_key`
2. 检查已有 run
3. 读取 daily inputs
4. 提交任务
5. 写 `workflow_runs` / `workflow_run_tasks`
6. 入队“启动通知”

- [ ] **Step 3: 将 daily scheduler 内嵌到 `qbu-crawler serve`**

要求：

- 仅在 Crawler Host 上生效
- 由 `.env` 控制开关和时间
- 通过 `workflow_runs.trigger_key` 保证幂等

- [ ] **Step 4: 写测试**

覆盖：

- 重复执行同一 `logical_date` 只返回已有 run
- CSV 错误不生成半残 run

- [ ] **Step 5: 运行测试**

Run:

`uv run pytest tests/test_workflows.py -k daily_submit -v`

Expected:

- 本机调度路径测试通过。

---

## Chunk 3: Outbox 与 Hardened Bridge

### Task 7: 用 outbox 替换 `/hooks/agent` 假成功

**Files:**
- Modify: `qbu_crawler/server/task_manager.py`
- Modify: `qbu_crawler/server/mcp/tools.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: 将任务完成通知改为 outbox 入队**

要求：

- 不再直接调用 `/hooks/agent`
- 为任务完成生成稳定 `dedupe_key`
- 仅入队，不标记 `notified_at`

- [ ] **Step 2: 为兼容路径加 authoritative gate**

要求：

- `legacy` 模式下旧路径 authoritative
- `shadow` 模式下新 outbox 只演练
- `outbox` 模式下旧 heartbeat 通知完全关闭

- [ ] **Step 3: 写测试**

覆盖：

- `legacy` / `shadow` / `outbox` 三种模式的行为
- 避免双发

- [ ] **Step 4: 运行测试**

Run:

`uv run pytest tests/test_notifier.py -k cutover -v`

Expected:

- authoritative path 测试通过。

### Task 8: 实现 notifier worker 的 claim/reclaim 语义

**Files:**
- Create: `qbu_crawler/server/notifier.py`
- Create: `qbu_crawler/server/runtime.py`
- Modify: `qbu_crawler/server/app.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: 实现 `claim_pending_notifications()` 和 reclaim**

要求：

- `sending` 项有 lease
- 超时后可 reclaim
- claim 需要 `claim_token`

- [ ] **Step 2: 区分 sent / failed / deadletter**

要求：

- 可重试错误进入 `failed`
- 达到最大重试进入 `deadletter`
- 成功后写 `delivered_at`

- [ ] **Step 3: worker 与 report 线程池隔离**

要求：

- notifier 不与 full report 共用执行器
- 通知 SLA 不被图片/Excel 拖慢

- [ ] **Step 4: 在统一 runtime 中接入 worker 生命周期**

避免直接与 `mcp_app.lifespan` 冲突。

- [ ] **Step 5: 写测试**

覆盖：

- claim 后崩溃可 reclaim
- 成功后不会重复发送
- 可重试错误与 deadletter 正常流转

- [ ] **Step 6: 运行测试**

Run:

`uv run pytest tests/test_notifier.py -v`

Expected:

- outbox worker 测试通过。

### Task 9: 编写 Hardened Bridge

**Files:**
- Create: `qbu_crawler/server/openclaw/bridge/app.py`
- Create: `deploy/openclaw/systemd/qbu-openclaw-notify-bridge.service`
- Create: `deploy/openclaw/README.md`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: bridge 只暴露单一受限 `POST /notify`**

入参必须至少包括：

- `target`
- `template_key`
- `template_vars`
- `dedupe_key`

不允许原样透传任意 message body。

- [ ] **Step 2: bridge 强制校验**

要求：

- token/HMAC
- source allowlist
- target allowlist
- template allowlist
- 长度限制
- 速率限制

- [ ] **Step 3: 调用 `openclaw message send --channel dingtalk --json`**

要求：

- 解析成功/失败结果
- 返回最小必要 JSON
- 不透传敏感 stderr

- [ ] **Step 4: 写测试**

覆盖：

- allowlist 拒绝
- 认证失败
- CLI 成功
- CLI 失败

- [ ] **Step 5: 运行测试**

Run:

`uv run pytest tests/test_notifier.py -k bridge -v`

Expected:

- bridge 测试通过。

---

## Chunk 4: Snapshot 驱动的快报 / 慢报

### Task 10: 构建 immutable report snapshot

**Files:**
- Create: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: 设计 snapshot artifact**

至少包含：

- `run_id`
- `snapshot_at`
- `data_since`
- `data_until`
- 产品行集合
- 评论行集合
- 翻译统计
- 快报统计

- [ ] **Step 2: 在 run 进入 reporting 时冻结 snapshot**

要求：

- 只生成一次
- 写 `snapshot_path` 和 `snapshot_hash`
- 后续补发复用同一 artifact

- [ ] **Step 3: 写测试**

覆盖：

- snapshot 重复生成幂等
- 同一 run 的 snapshot 内容稳定

- [ ] **Step 4: 运行测试**

Run:

`uv run pytest tests/test_report_snapshot.py -v`

Expected:

- snapshot 测试通过。

### Task 11: 用 snapshot 重写 fast/full report

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `tests/test_report.py`
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: fast report 只读取 snapshot**

输出：

- 成功/失败统计
- 产品数
- 评论数
- 翻译进度
- “完整版生成中”

- [ ] **Step 2: full report 也只读取同一 snapshot**

要求：

- 不再直接按 `since` 查右侧无界窗口
- `excel_path` 写回 `workflow_runs`

- [ ] **Step 3: 图片与翻译策略收敛**

要求：

- 图片数量限制
- 失败回退为 URL
- 可配置翻译等待阈值

- [ ] **Step 4: 写测试**

覆盖：

- fast/full 使用相同 `snapshot_hash`
- 慢报晚跑也不漂移
- 慢报失败不影响快报已发送

- [ ] **Step 5: 运行测试**

Run:

`uv run pytest tests/test_report.py tests/test_report_snapshot.py -v`

Expected:

- 报表一致性测试通过。

### Task 12: 实现 workflow reconcile 与 run 推进

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `qbu_crawler/server/runtime.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: 加入 stale task reconcile**

要求：

- 先 reconcile 任务
- 再推进 runs

- [ ] **Step 2: run 状态推进**

至少覆盖：

- `running -> reporting`
- `reporting -> fast_sent -> full_pending -> full_sent`
- 遇到不可收敛错误进入 `needs_attention`

- [ ] **Step 3: 写测试**

覆盖：

- 服务重启后 reconcile 生效
- run 不会永久卡在 `running`

- [ ] **Step 4: 运行测试**

Run:

`uv run pytest tests/test_workflows.py -k reconcile -v`

Expected:

- 恢复与推进测试通过。

---

## Chunk 5: OpenClaw 对齐与价值回接

### Task 13: 把 `openclaw.json` 纳入配置即代码

**Files:**
- Create: `deploy/openclaw/openclaw.json5.template`
- Create: `deploy/openclaw/sync_openclaw_assets.sh`
- Modify: `qbu_crawler/server/openclaw/README.md`

- [ ] **Step 1: 编写 `openclaw.json` 模板**

模板至少要显式定义：

- `primary + fallbacks`
- heartbeat `target:none`
- `mcp-products` endpoint
- hooks allowlist
- main / ops agent

- [ ] **Step 2: 编写同步与校验脚本**

能力包括：

- 渲染模板
- 同步 workspace/plugin/config
- 写版本号 / checksum
- 重启 gateway
- 执行校验命令

- [ ] **Step 3: 写部署文档**

说明：

- 如何部署到 OpenClaw Host
- 如何验证无漂移
- 如何回滚

### Task 14: 更新 workspace 与 multi-agent 行为

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/HEARTBEAT.md`
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-report/SKILL.md`
- Modify: `qbu_crawler/server/mcp/tools.py`

- [ ] **Step 1: heartbeat 只保留巡检职责**

覆盖：

- stale run
- failed notification
- 翻译积压
- 差评异常

- [ ] **Step 2: 增加只读 workflow / notification 工具**

例如：

- `get_workflow_status`
- `list_workflow_runs`
- `list_pending_notifications`

- [ ] **Step 3: 重写 daily skills 定位**

- `daily-scrape-submit` 只做手动兜底
- `daily-scrape-report` 改为 AI digest

- [ ] **Step 4: 手工验证**

验证：

- OpenClaw 还能自然语言发起临时抓取
- OpenClaw 能读 run 状态和 outbox 状态
- heartbeat 不会误投到最后联系人

### Task 15: 把 AI digest 明确接回自动化链路

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `qbu_crawler/server/mcp/tools.py`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-report/SKILL.md`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: 在 full report 后增加可选 AI sidecar 触发点**

要求：

- 受 `AI_DIGEST_MODE` 控制
- 非关键，不影响主链路成功

- [ ] **Step 2: AI sidecar 基于 snapshot 做解释**

目标：

- 今日异常原因
- 差评主题
- 竞品变化提醒

- [ ] **Step 3: 写测试或 dry-run 验证**

至少验证：

- 主链路成功时 sidecar 可独立失败
- sidecar 不会回写主链路终态

---

## Chunk 6: Rollout、回滚与最终验收

### Task 16: 定义 cutover 与回滚

**Files:**
- Modify: `deploy/openclaw/README.md`
- Modify: `qbu_crawler/server/openclaw/README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 写清 authoritative path 切换规则**

必须包括：

- `legacy`
- `shadow`
- `outbox`

- [ ] **Step 2: 写清回滚步骤**

必须包括：

- 通知链路回滚
- scheduler 回滚
- OpenClaw config 回滚

- [ ] **Step 3: 写清检查点**

包括：

- 没有双发
- 没有卡死的 `sending`
- 没有卡死的 `running`

### Task 17: 最终测试与手工验收

**Files:**
- Modify: `docs/devlogs/D007-openclaw-hybrid-automation.md`
- Test: `tests/test_report.py`
- Test: `tests/test_translator.py`
- Test: `tests/test_daily_inputs.py`
- Test: `tests/test_workflows.py`
- Test: `tests/test_notifier.py`
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: 跑最终测试集**

Run:

`uv run pytest tests/test_report.py tests/test_translator.py tests/test_daily_inputs.py tests/test_workflows.py tests/test_notifier.py tests/test_report_snapshot.py -v`

Expected:

- 全部通过。

- [ ] **Step 2: 做端到端手工验证**

场景：

1. 提交一个临时任务
2. bridge 成功发送回执
3. 断开 OpenClaw Host，验证 outbox 不写假成功
4. 恢复 OpenClaw Host，验证 outbox 补发
5. 手工触发 daily-submit 两次，验证幂等
6. 验证快报与慢报 `snapshot_hash` 一致
7. 验证 AI digest 失败不影响主链路

- [ ] **Step 3: 记录开发日志**

内容包括：

- 为什么 scheduler 迁到 Crawler Host
- 为什么必须冻结 snapshot
- 为什么 bridge 必须 hardened
- 怎样避免双发与漂移

---

## Manual Verification Checklist

- [ ] daily-submit 在 Crawler Host 本机调度
- [ ] 同一 logical date 不会生成重复 run
- [ ] stale running task 会被 reconcile
- [ ] outbox `sending` 超时可 reclaim
- [ ] fast/full report 共享同一 snapshot
- [ ] OpenClaw Host 挂掉时不会写假成功
- [ ] OpenClaw 恢复后 pending notification 会补发
- [ ] heartbeat 不会误发给最后联系人
- [ ] `openclaw.json` 模板与线上配置一致
- [ ] AI digest 是 sidecar，不影响主链路

---

## Rollout Strategy

1. 先修测试基线。
2. 再上线 schema + liveness + feature flag。
3. 再上线 hardened bridge，但先跑 `shadow`。
4. 再切 `NOTIFICATION_MODE=outbox`。
5. 再将 daily-submit 切到 `qbu-crawler serve` 内嵌 scheduler。
6. 再切 `REPORT_MODE=snapshot_fast_full`。
7. 最后打开 `AI_DIGEST_MODE=async`。

---

Plan complete and saved to `docs/superpowers/plans/2026-03-29-openclaw-hybrid-automation.md`. Ready to execute?
