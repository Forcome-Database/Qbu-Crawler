# OpenClaw 混合自动化重构设计文档

> 日期：2026-03-29
> 状态：已纳入多代理审查并修订

## 概述

本方案将 Qbu-Crawler 的自动化体系重构为“**Crawler Server 负责确定性执行，OpenClaw 负责智能交互与分析**”的混合架构。

修订后的核心判断是：

1. **有 SLA 的动作必须落在 Crawler Server 自身**：每日提交、任务状态、工作流推进、报表冻结、邮件发送、通知入队与补偿。
2. **OpenClaw 不再承担关键链路的最终责任**：它负责自然语言入口、消息通道能力、数据解释、主动洞察、非关键 AI 摘要。
3. **新的不确定性必须被显式治理**：不能只是把风险从 LLM turn 挪到 systemd、outbox、重启恢复、幂等和配置漂移上。

---

## 设计目标

### 业务目标

- 每日定时任务必须稳定提交，且调度器物理上不依赖 OpenClaw 主机存活。
- 临时任务完成回执必须“真实送达后再标记成功”，不再出现假成功。
- 快报和慢报必须基于同一批冻结数据，不能前后漂移。
- OpenClaw 仍然要比普通通知机器人更智能，能做解释、提醒、总结和人工入口。

### 技术目标

- Crawler Server 成为唯一事实源。
- 所有关键状态持久化到 SQLite 或明确的 snapshot artifact。
- 通知链路从“假确定性”改为“幂等 + 可恢复 + 可审计”。
- OpenClaw 的配置、workspace、plugin、部署脚本全部纳入版本化治理。

### 非目标

- 不重写 Scraper 采集逻辑。
- 不把系统做成多节点分布式调度平台。
- 不要求通知链路达到严格意义上的底层 exactly-once；目标是**应用层幂等、可恢复、无假成功**。

---

## 前置约束

### 1. 调度归属

每日提交的调度器必须运行在 **Crawler Server 主机**，而不是 OpenClaw 主机。

原因：

- daily-submit 属于爬虫业务控制面
- OpenClaw 主机故障不应阻断每日采集
- OpenClaw 只应该影响“消息与智能层”，不应影响“提交与状态层”

### 2. 控制面边界

本方案**不新增公开暴露的工作流写接口**。每日提交流程改为本机 CLI / 本机 systemd timer，不通过公网 HTTP 入口触发。

已有 `/api` 与 `/mcp` 的网络边界必须被视为部署前提：

- `/mcp` 只应暴露给受信任来源
- `/api` 只应暴露给受信任来源
- 新的写控制面不复用现有公开 API key

### 3. OpenClaw host 的角色

OpenClaw 主机只承担：

- DingTalk 发送能力
- 用户对话
- 智能摘要与解释
- 低时效巡检

它不负责：

- 每日提交流程
- 工作流主状态推进
- 报表边界冻结

---

## 当前问题诊断

### 1. 每日定时提交不稳定

当前每日任务链路是：

`OpenClaw cron -> isolated agent turn -> 读 skill -> 调 MCP -> 写 active-tasks.json -> DingTalk announce`

问题在于，**精确定时的是 cron，不是技能执行结果**。模型过载、偏航、工具调用中断，都会让 cron 看起来触发了，但业务未真正完成。

### 2. 临时任务回执存在假成功

当前服务端任务完成后调用 `/hooks/agent` 请求 OpenClaw 发回执；只要 HTTP 返回成功，就立即写 `notified_at`。

这意味着：

- `/hooks/agent` 只表示“开始了一次 isolated agent turn”
- 不表示 DingTalk 一定送达
- 一旦模型 429、会话漂移、投递失败，数据库就会被错误标记为已通知

### 3. 报表快慢不一致风险

现有报表查询本质是“`since >= t` 的右侧无界时间窗”。如果慢报晚于快报很多时间才生成，它就可能把后续任务的数据也带进去，导致前后口径不一致。

### 4. 重启恢复没有闭环

现有任务执行使用进程内 `ThreadPoolExecutor` 与内存态 `_tasks`。服务重启后：

- 运行中的任务可能永久留在 `running`
- 外层 workflow 不知道该继续、失败还是重试
- 报表与通知都可能卡住

### 5. OpenClaw 运行态配置漂移

当前漂移不只发生在 workspace 文档，还发生在真正决定行为的 `~/.openclaw/openclaw.json`：

- heartbeat `target:last`
- 默认模型只有 `kimi-coding/k2p5`
- `mcp-products` endpoint
- hooks / plugins / channel 行为

如果不把 `openclaw.json` 本身纳入治理，所谓“配置即代码”只是半套。

---

## 目标架构

### A. Crawler Server Host

负责：

- 每日 scheduler
- 任务提交与状态更新
- workflow orchestration
- run 幂等与恢复
- report snapshot 冻结
- fast/full report
- email
- notification outbox

### B. OpenClaw Host

负责：

- `openclaw message send` 的 DingTalk 发送能力
- 用户自然语言入口
- MCP 查询与解释
- 非关键 AI 摘要 sidecar
- heartbeat 巡检与主动提醒

### C. Host 间关系

- Crawler Host 不依赖 OpenClaw Host 才能“提交任务”
- OpenClaw Host 宕机时，Crawler Host 继续跑采集与 workflow，只是通知暂时积压到 outbox
- OpenClaw Host 恢复后，pending outbox 会继续发送，不会写假成功

---

## 核心组件设计

### 1. Scheduler 与控制面

每日 scheduler 改为 **Crawler Host 本机 systemd timer + 本机 CLI 命令**：

`systemd timer -> qbu-crawler workflow daily-submit --logical-date YYYY-MM-DD`

不走：

- OpenClaw cron
- 远程 HTTP 写接口
- `/hooks/agent`

优点：

- 不扩大公开攻击面
- 不再把 daily-submit 绑在 OpenClaw 主机
- 本机调用天然更容易做幂等和审计

### 2. Task Liveness 与 Recovery

现有 `tasks` 表需要补充“活性”信息，至少包括：

- `updated_at`
- `worker_token`
- `last_progress_at`
- `system_error_code`

恢复规则：

- 任务运行中时，周期性刷新 `updated_at`
- 服务启动时执行 reconcile
- 超过 stale threshold 的 `running` 任务，统一转为系统失败态，而不是永久悬挂
- 外层 workflow 只依赖“终态集合”，不依赖内存对象

这里不追求“崩溃后自动接管线程继续跑”，而是追求：

- 不丢状态
- 不假成功
- 能自动收敛到可处理状态

### 3. Workflow Orchestrator

新增 `workflow_runs`，并明确幂等字段与报表边界字段。

#### `workflow_runs`

- `id`
- `kind`：`daily` / `adhoc`
- `logical_date`：每日批次的逻辑日期
- `trigger_key`：如 `daily:2026-03-29`
- `status`：`pending` / `running` / `reporting` / `completed` / `failed` / `needs_attention`
- `source`：`systemd` / `openclaw` / `api` / `manual`
- `requested_by`
- `reply_to`
- `submitted_at`
- `started_at`
- `finished_at`
- `data_since`
- `data_until`
- `snapshot_at`
- `snapshot_path`
- `snapshot_hash`
- `report_phase`：`none` / `fast_pending` / `fast_sent` / `full_pending` / `full_sent`
- `report_status`
- `fast_report_sent_at`
- `full_report_started_at`
- `full_report_sent_at`
- `excel_path`
- `metadata_json`
- `service_version`
- `last_error`

约束：

- `trigger_key` 全局唯一
- 同一逻辑日期的 daily-submit 只能存在一个 authoritative run

#### `workflow_run_tasks`

- `run_id`
- `task_id`
- `task_type`
- `ownership`
- `site`
- `created_at`

约束：

- `UNIQUE(run_id, task_id)`
- 必须有 FK 约束

### 4. Immutable Report Snapshot

快报和慢报不能直接基于“当前数据库状态”各算各的，而必须共用同一个冻结快照。

冻结时机：

- 当 workflow 进入 `reporting`
- 所有子任务都已终态
- 立即生成 snapshot artifact

快照内容：

- `data_since`
- `data_until`
- 产品行集合
- 评论行集合
- 快报统计摘要
- 翻译进度摘要

落地形式：

- 以 JSON artifact 持久化到 `snapshot_path`
- `snapshot_hash` 写入 `workflow_runs`
- fast/full report 都只读取该 snapshot，不再直接走“右侧无界 since 查询”

这样即使慢报晚几个小时生成，口径也不会漂。

### 5. Notification Outbox

通知链路改为“**应用层幂等 + 可恢复的 outbox**”。

#### `notification_outbox`

- `id`
- `dedupe_key`
- `scope_type`：`task` / `workflow` / `report`
- `scope_id`
- `channel`
- `target`
- `template_key`
- `payload_json`
- `payload_hash`
- `requested_by`
- `status`：`pending` / `sending` / `sent` / `failed` / `deadletter`
- `attempts`
- `claimed_at`
- `claim_token`
- `lease_until`
- `next_retry_at`
- `delivered_at`
- `bridge_request_id`
- `provider_message_id`
- `last_http_status`
- `last_exit_code`
- `last_error`
- `created_at`
- `updated_at`

语义：

- `dedupe_key` 保证同一逻辑事件只入队一次
- `sending` 必须有 lease 回收机制
- worker 崩溃后，超时的 `sending` 项可安全 reclaim
- 传输层容忍 at-least-once，但应用层不允许“同一逻辑事件重复生成新记录”

### 6. Hardened Direct-Send Bridge

Bridge 方案保留，但必须收紧。

#### 必须满足的硬要求

- 只部署在 OpenClaw Host
- 只监听私网地址
- 主机防火墙仅允许 Crawler Host 访问
- Bearer token 或 HMAC 鉴权
- `channel` 固定为 `dingtalk`
- `target` 必须走精确 allowlist，不是前缀校验
- `template_key` 必须走 allowlist
- 消息长度、频率、并发必须有限制
- 不透传原始 CLI 敏感输出
- 生成 `bridge_request_id` 并写审计日志

它的职责仅限：

- 将受控模板消息转成 `openclaw message send --channel dingtalk`

它不是通用消息代理，更不是任意文本转发器。

### 7. OpenClaw Config as Code

本次治理对象必须包括：

- `openclaw.json` 模板
- workspace 文档
- plugin 代码
- bridge service
- systemd unit
- 部署与校验脚本

`openclaw.json` 模板至少要显式治理：

- `agents.defaults.model` 的 `primary + fallbacks`
- `heartbeat.target = none`
- `plugins.entries.mcp-products.config.endpoint`
- `hooks.allowedAgentIds`
- multi-agent 配置
- channel / plugin allowlist

部署后必须校验：

- 目标机器上的 `openclaw.json` 与模板渲染结果一致
- workspace 版本号 / checksum 一致
- `openclaw status`、`openclaw channels list`、`openclaw message send --dry-run` 正常

### 8. OpenClaw 的智能价值

OpenClaw 不只是“入口壳”，还需要有明确的自动化价值，但这些都属于**非关键 sidecar**：

- fast report 发出后，触发可选 `AI digest`
- full report 发出后，触发可选“今日异常解释”
- heartbeat 检查 stale run、failed notification、翻译积压、差评暴增
- 用户可以追问“为什么今天评论波动大”“哪些竞品值得跟进”

这些 sidecar 可以失败、可以延迟，但不能反向影响：

- daily-submit
- task completion truth
- report snapshot
- email / must-deliver notification

---

## 关键业务流程

### 每日定时流程

1. Crawler Host 的 systemd timer 调用本机 CLI：`workflow daily-submit`
2. CLI 计算 `trigger_key = daily:<logical_date>`
3. 若已存在该 run，则直接返回 existing run，不重复提交
4. 读取 CSV，校验并分组
5. 提交 `start_collect` / `start_scrape`
6. 写入 `workflow_runs` 和 `workflow_run_tasks`
7. 写 outbox，发送“任务已启动”
8. worker 推进 run 状态
9. 全部终态后冻结 snapshot
10. 先发 fast report
11. 再异步生成 full report
12. 成功后发送最终通知
13. 可选触发 OpenClaw AI digest sidecar

### 临时任务流程

1. 用户通过 OpenClaw 或 HTTP 提交 URL
2. 服务端保存 `reply_to`
3. Task 完成时仅入队 outbox，不直接调用 `/hooks/agent`
4. outbox worker 通过 bridge 发送 DingTalk
5. 仅在 bridge 成功并落库后更新 `notified_at`
6. 若 bridge 不可用，通知留在 outbox pending/retry，不写假成功

### 恢复流程

1. 服务启动时先 reconcile stale `running` tasks
2. 再 reclaim 超时 `sending` outbox
3. 再推进 active `workflow_runs`
4. 对无法自动收敛的 run，置为 `needs_attention`
5. heartbeat / OpenClaw 对 `needs_attention` 做告警与解释

### AI Sidecar 流程

1. deterministic fast/full report 已发送
2. 触发专用 `ops-summary` agent 或受限 `/hooks/agent`
3. 使用 snapshot 数据与统计结果做解释
4. 输出到固定目标

该流程失败不影响主链路成功状态。

---

## OpenClaw 最佳实践落地

### 1. 不把 hard SLA 交给 heartbeat 或 `/hooks/agent`

- heartbeat 只做巡检、补偿、摘要
- `/hooks/agent` 只做 AI sidecar
- must-deliver 走 `message send` + bridge + outbox

### 2. `openclaw.json` 才是运行态真相

workspace 只是提示词层，真正决定运行行为的是：

- model
- heartbeat
- plugin endpoint
- hooks
- agent routing

所以它必须纳入版本化治理。

### 3. Multi-agent 必须落到可部署配置

至少包含：

- `main`：用户对话 / 数据分析
- `ops`：heartbeat / 运维巡检 / AI digest

不是口头角色，而是模板化配置对象。

### 4. 心跳目标默认 `none`

不允许沿用现网 `target:last`，否则巡检类告警会误投给最后一个聊天对象。

---

## 迁移与回滚策略

必须用 feature flag 切换 authoritative path，不能新旧并发直连生产。

建议最少有：

- `NOTIFICATION_MODE = legacy | shadow | outbox`
- `DAILY_SUBMIT_MODE = openclaw | crawler_systemd`
- `REPORT_MODE = legacy | snapshot_fast_full`
- `AI_DIGEST_MODE = off | async`

约束：

- `legacy`：旧链路唯一 authoritative
- `shadow`：新链路只演练，不真实发消息
- `outbox`：新链路 authoritative，旧 heartbeat 通知关闭

回滚时：

- 不得依赖 24 小时窗口的旧 pending scan 去兜底所有历史事件
- 必须有明确的一键切回 authoritative path 的步骤

---

## 风险与缓解

### 风险 1：工作流重构范围大

缓解：

- 先修测试基线
- 先上幂等与恢复骨架
- 再切通知
- 再切 daily-submit
- 最后切 snapshot 报表与 AI sidecar

### 风险 2：Bridge 扩大攻击面

缓解：

- 私网监听
- IP allowlist
- template allowlist
- token/HMAC
- 速率限制
- 本地审计日志

### 风险 3：快报/慢报边界处理不当

缓解：

- 强制 snapshot
- fast/full 共享 `snapshot_hash`
- 补发、重试均基于同一 snapshot

### 风险 4：OpenClaw 价值被削弱

缓解：

- 把 AI digest 明确接回 workflow
- 保留自然语言入口
- 保留 heartbeat 主动洞察

---

## 验收标准

### 稳定性

- daily-submit 运行在 Crawler Host，本机调度不依赖 OpenClaw Host 存活
- 同一 `logical_date` 的 daily run 只会生成一个 authoritative run
- 任务完成通知仅在真实送达后标记成功
- stale `running` task 可在阈值内被 reconcile，不会永久悬挂
- 超时 `sending` outbox 可被 reclaim，不会永久卡死

### 一致性

- fast report 与 full report 使用同一 `snapshot_hash`
- full report 不会吃进后续 run 的数据
- 重试/补发不会改变本次 run 的统计口径

### OpenClaw

- `openclaw.json` 模板、workspace、plugin、部署脚本与线上一致
- heartbeat `target` 为 `none`
- automation agent 配置了 `primary + fallbacks`
- OpenClaw 仍能自然语言发起任务、查询数据、解释异常

### 运维

- 至少有一条 authoritative notification path
- 新旧路径切换由 feature flag 控制
- 有自动化测试覆盖幂等、恢复、snapshot、bridge、cutover

---

## 推荐实施顺序

1. 先修测试基线与部署边界。
2. 再补 tasks/outbox/workflow 的幂等与恢复骨架。
3. 再上线 hardened bridge 和 outbox。
4. 再把 daily-submit 切到 Crawler Host 本机 scheduler。
5. 再做 snapshot fast/full report。
6. 最后做 OpenClaw config-as-code、multi-agent 与 AI digest。
