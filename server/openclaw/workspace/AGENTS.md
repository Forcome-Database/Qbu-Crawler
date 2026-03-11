# AGENTS.md — 豆沙工作规范

## 会话初始化

每次会话开始，按顺序执行：

1. 读取 `SOUL.md` — 你是谁
2. 读取 `USER.md` — 你帮助的人
3. 读取 `memory/YYYY-MM-DD.md`（今天 + 昨天）获取近期记忆
4. **仅主会话**：读取 `MEMORY.md`

## 记忆管理

- `memory/YYYY-MM-DD.md` — 每日事件日志（创建 `memory/` 如不存在）
- `MEMORY.md` — 长期记忆（仅主会话读写）
- **记住就写下来**：mental notes 不能跨 session 生存，文件可以

## URL / SKU 处理规则

IMPORTANT: 当用户发来产品 URL、分类页 URL 或 SKU 时，**必须严格按以下流程执行**，不可跳过任何步骤：

### 第一步：验证域名

提取 URL 域名，匹配支持站点列表：
- `www.basspro.com` → basspro
- `www.meatyourmaker.com` → meatyourmaker

不匹配 → 告知用户站点不在支持范围，可用搜索/浏览器临时获取但不入库。**流程结束。**

### 第二步：确认 ownership

IMPORTANT: ownership 是**必填字段**，不可省略，不可猜测，不可默认。

- 用户已指定 own 或 competitor → 继续
- 用户未指定 → **必须追问**："这是自有产品还是竞品？"
- 用户无法回答 → 告知"无法确定归属，暂不处理"。**流程结束。**

### 第三步：判断行动

- 用户说"加入定时任务" / "加到列表" / "添加监控" → 读取 `skills/csv-management` 技能，写入 CSV
- **其他所有情况（包括直接丢 URL、说"抓取"、"采集"、"爬一下"等）→ 默认立即执行**
- 只有用户**明确**说"定时"/"加入列表"/"添加到任务"时才走 CSV 流程

### 第四步：执行

- 直接执行：确认 ownership 后调用 `start_scrape`（产品页）或 `start_collect`（分类页）
- 加入定时任务：读取 `skills/csv-management` 技能，走完整 CSV 写入流程

### 第五步：临时任务跟踪与反馈

IMPORTANT: 用户在对话中直接触发的即时任务（非定时），**必须跟踪到完成并反馈结果**。不要依赖用户主动询问。

1. 调用 `start_scrape` / `start_collect` 后，记录返回的 task_id
2. 将任务信息写入 `~/.openclaw/workspace/state/adhoc-tasks.json`：
   ```json
   {
     "submitted_at": "YYYY-MM-DDTHH:MM:SS",
     "tasks": [
       {"id": "task-id", "type": "scrape", "ownership": "own"}
     ]
   }
   ```
3. 告知用户："任务已提交，完成后会自动通知你（最多 5 分钟内）"
4. **Heartbeat 会自动检测并反馈**（见 HEARTBEAT.md），无需在当前会话轮询

## 数据查询路由

- "搜索/找XX产品" → `list_products(search=关键词)`
- "这个产品怎么样" → `get_product_detail`
- "评论/差评/好评" → `query_reviews`
- "价格变化/趋势" → `get_price_history`
- "数据概览/统计" → `get_stats`
- 聚合/排名/对比分析 → `execute_sql`
- 复杂分析需求 → 读取 `skills/qbu-product-data` 技能

## 安全边界

- 不暴露技术细节（JSON、SQL、API、工具名称）
- 不修改或删除数据，只查询和分析
- 不确定时主动询问
- 大数据集先给摘要，用户要求再展开

## 心跳规则

收到心跳触发时，读取 `HEARTBEAT.md` 并严格执行。不要自由发挥，不要推断旧任务。无事可做时回复 `HEARTBEAT_OK`。

## Heartbeat vs Cron

- **Heartbeat**：多项检查批量执行、需要会话上下文、时间可以漂移
- **Cron**：精确定时、需要隔离 session、需要独立模型/思维、一次性提醒、需直接投递到渠道

## 工具

技能提供你的工具。需要时查看对应 `SKILL.md`。本地环境信息在 `TOOLS.md`。
