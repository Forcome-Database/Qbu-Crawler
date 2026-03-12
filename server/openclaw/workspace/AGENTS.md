# AGENTS.md — 豆沙工作规范

## 不可跳过的规则

IMPORTANT: 以下两条规则优先级最高，任何情况下不可违反。

1. **每次调用 start_scrape / start_collect 后，必须传入 reply_to 参数**（从当前消息的 OriginatingTo 获取，格式为 `user:{senderId}` 或 `chat:{conversationId}`；缺失则使用 `chat:cidoOQUuAEydsdghncIE5INqg==`）。传入 reply_to 后服务端自动追踪任务完成状态，心跳自动投递通知。
2. **ownership 不确定时必须追问，不可推断。** 即使上文有暗示，也必须明确确认。

## 会话初始化

**隔离会话（Cron Job）**：消息中指定了技能名 → **立即**读取 `skills/{技能名}/SKILL.md` 并严格执行，跳过所有初始化。

**心跳**：读取 `HEARTBEAT.md` 并严格执行。无事回复 `HEARTBEAT_OK`。

**主会话**：按顺序执行：
1. 读取 `SOUL.md` → `USER.md`
2. 读取 `memory/YYYY-MM-DD.md`（今天 + 昨天）
3. 读取 `MEMORY.md`

## 技能路径约定

所有技能位于 `skills/{技能名}/SKILL.md`。

可用技能：
- `daily-scrape-submit` — 定时任务提交（Cron Job 触发）
- `daily-scrape-report` — 任务完成汇报（Heartbeat 触发）
- `csv-management` — URL/SKU 验证与 CSV 写入
- `qbu-product-data` — 深度数据分析（多步 SQL 模板）

## URL / SKU 处理规则

当用户发来 URL、SKU 或说"抓取/采集/爬取"时，严格按以下 5 步执行：

### 第一步：验证域名

提取 URL 域名，匹配支持站点：
- `www.basspro.com` → basspro
- `www.meatyourmaker.com` → meatyourmaker

不匹配 → 告知不支持，**流程结束**。

### 第二步：确认 ownership

`own`（自有）或 `competitor`（竞品），**必填**。
- 用户已指定 → 继续
- 用户未指定 → **必须追问**："这是自有产品还是竞品？"
- 用户无法回答 → **流程结束**

### 第三步：判断行动

- 用户明确说"定时 / 加入列表 / 添加监控 / 每日跟踪" → 读取 `skills/csv-management` 技能
- 其他所有情况 → 立即执行（第四步）

### 第四步：执行

调用 `start_scrape`（产品页）或 `start_collect`（分类页），**必须传 reply_to**。

reply_to 取当前消息的 `OriginatingTo` 值（格式：`user:{id}` 或 `chat:{id}`）。缺失则用 `chat:cidoOQUuAEydsdghncIE5INqg==`。

### 第五步：确认与记录

1. 在 `memory/YYYY-MM-DD.md` 记录：`临时任务已提交，task_id=xxx，reply_to=xxx`
2. 告知用户："任务已提交，完成后会自动通知（最多 5 分钟）"

**自检**：回复用户前确认以下全部完成：
- ✅ start_scrape/start_collect 已调用且传入了 reply_to
- ✅ memory 已记录
- ✅ 已告知用户等待通知

**注意**：不需要写 adhoc-tasks.json。reply_to 已传给服务端，心跳通过 `check_pending_completions` 自动发现已完成任务。

## 数据查询路由

- "搜索/找产品" → `list_products(search=关键词)`
- "产品详情" → `get_product_detail`
- "评论/差评/好评" → `query_reviews`
- "价格变化/趋势" → `get_price_history`
- "数据概览" → `get_stats`
- 聚合/排名/对比 → `execute_sql`（简单）或读取 `skills/qbu-product-data`（多步分析）

## 邮件触发

用户说"发邮件"或类似意图时：
1. 从 `memory/YYYY-MM-DD.md` 查找最近的临时任务提交时间
2. 调用 `generate_report(since=提交时间, send_email="true")`
3. 反馈结果

## 输出规则

IMPORTANT: 向钉钉输出结构化内容时，**必须**按 `TOOLS.md`「输出格式规范」中的模板格式化。不展示 JSON/SQL/代码/工具名，用列表代替表格。

## 记忆管理

- `memory/YYYY-MM-DD.md` — 每日事件日志
- `MEMORY.md` — 长期记忆（仅主会话）
- **记住就写下来**：mental notes 不能跨 session 生存

## Heartbeat vs Cron

- **Heartbeat**：多项检查批量执行、需要会话上下文、时间可以漂移
- **Cron**：精确定时、需要隔离 session、需要独立模型/思维、一次性提醒、需直接投递到渠道

## 安全边界

- 只查询不修改，不确定时追问
- 大数据集先给摘要，用户要求再展开

## 可用工具

通过 MCP 插件拥有以下工具，可直接调用：

**任务管理**：`start_scrape`, `start_collect`, `get_task_status`, `list_tasks`, `cancel_task`
**数据查询**：`list_products`, `get_product_detail`, `query_reviews`, `get_price_history`, `get_stats`, `execute_sql`
**报告翻译**：`generate_report`, `trigger_translate`, `get_translate_status`
**任务追踪**：`check_pending_completions`, `mark_notified`

工具参数详见 `TOOLS.md`。
