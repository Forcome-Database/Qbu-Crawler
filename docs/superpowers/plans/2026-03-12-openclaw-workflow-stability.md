# OpenClaw 工作流稳定性全面改造 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 LLM 状态文件依赖，实现服务端任务追踪 + 工作流步骤自检，确保临时任务不丢失、不堆积、不漏报。

**Architecture:** 服务端 tasks 表新增 `reply_to` + `notified_at` 列，新增 `check_pending_completions` / `mark_notified` MCP 工具。Heartbeat 从"读文件+轮询"简化为"一次 MCP 调用"。AGENTS.md 重组为硬规则前置+步骤自检模式。删除 adhoc-tasks.json 机制，output-formats 合并到 TOOLS.md。

**Tech Stack:** Python (models.py, task_manager.py, tools.py), JavaScript (plugin/index.js), Markdown (workspace/*.md)

---

## File Structure

**Modify:**
- `models.py:60-71` — tasks 表加 `reply_to TEXT`, `notified_at TIMESTAMP` 列
- `models.py:217-246` — save_task 支持新字段
- `models.py` 末尾 — 新增 `get_pending_completions()`, `mark_task_notified()`
- `server/task_manager.py:30-55` — Task 类加 `reply_to` 字段
- `server/task_manager.py:65-81` — submit 方法加 `reply_to` 参数
- `server/mcp/tools.py:28-61` — start_scrape/start_collect 加 `reply_to` 参数
- `server/mcp/tools.py` 末尾 — 新增 `check_pending_completions`, `mark_notified` 工具
- `server/openclaw/plugin/index.js:206-382` — TOOLS 数组更新
- `server/openclaw/workspace/AGENTS.md` — 完全重写
- `server/openclaw/workspace/HEARTBEAT.md` — 完全重写
- `server/openclaw/workspace/TOOLS.md` — 重写，合并 output-formats
- `server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md` — 更新（传 reply_to）
- `server/openclaw/workspace/skills/daily-scrape-report/SKILL.md` — 更新（用 mark_notified）

**Delete:**
- `server/openclaw/workspace/skills/output-formats/` — 整个目录

---

## Task 1: 服务端 — tasks 表加列 + 数据层函数

**Files:**
- Modify: `models.py:60-71` (tasks 表定义)
- Modify: `models.py:73-88` (migrations 数组)
- Modify: `models.py:217-246` (save_task)
- Modify: `models.py` 末尾 (新增函数)

- [ ] **Step 1: tasks 表添加 reply_to 和 notified_at 列**

在 `models.py` 的 migrations 数组中添加两条迁移：

```python
"ALTER TABLE tasks ADD COLUMN reply_to TEXT",
"ALTER TABLE tasks ADD COLUMN notified_at TIMESTAMP",
```

- [ ] **Step 2: save_task 支持新字段**

修改 `save_task()` 函数，INSERT 和 UPDATE 都包含 `reply_to` 和 `notified_at`：

```python
def save_task(task_dict: dict) -> None:
    """INSERT or UPDATE a task record."""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO tasks (id, type, status, params, progress, result, error,
                                  created_at, started_at, finished_at, reply_to, notified_at)
               VALUES (:id, :type, :status, :params, :progress, :result, :error,
                       :created_at, :started_at, :finished_at, :reply_to, :notified_at)
               ON CONFLICT(id) DO UPDATE SET
                   status=excluded.status, progress=excluded.progress,
                   result=excluded.result, error=excluded.error,
                   started_at=excluded.started_at, finished_at=excluded.finished_at,
                   notified_at=excluded.notified_at
            """,
            {
                "id": task_dict["id"],
                "type": task_dict["type"],
                "status": task_dict["status"],
                "params": _json.dumps(task_dict.get("params")),
                "progress": _json.dumps(task_dict.get("progress")),
                "result": _json.dumps(task_dict.get("result")),
                "error": task_dict.get("error"),
                "created_at": task_dict.get("created_at"),
                "started_at": task_dict.get("started_at"),
                "finished_at": task_dict.get("finished_at"),
                "reply_to": task_dict.get("reply_to"),
                "notified_at": task_dict.get("notified_at"),
            },
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 3: 新增 get_pending_completions 函数**

在 `models.py` 末尾添加：

```python
def get_pending_completions() -> list[dict]:
    """Return terminal tasks that have reply_to set but notified_at is NULL.
    These are tasks that completed but the agent hasn't reported yet."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, type, status, params, result, error,
                      created_at, finished_at, reply_to
               FROM tasks
               WHERE status IN ('completed', 'failed', 'cancelled')
                 AND reply_to IS NOT NULL AND reply_to != ''
                 AND notified_at IS NULL
               ORDER BY finished_at ASC""",
        ).fetchall()
        tasks = []
        for row in rows:
            d = dict(row)
            for k in ("params", "result"):
                if d.get(k):
                    d[k] = _json.loads(d[k])
            tasks.append(d)
        return tasks
    finally:
        conn.close()


def mark_task_notified(task_ids: list[str]) -> int:
    """Mark tasks as notified. Returns count of updated rows."""
    if not task_ids:
        return 0
    conn = get_conn()
    try:
        placeholders = ",".join("?" for _ in task_ids)
        cursor = conn.execute(
            f"UPDATE tasks SET notified_at = {_NOW_SHANGHAI} WHERE id IN ({placeholders})",
            task_ids,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
```

- [ ] **Step 4: get_task 返回结果包含 reply_to 和 notified_at**

确认 `get_task()` 使用 `SELECT *`，已自动包含新列，无需改动。确认 `list_tasks()` 同理。

- [ ] **Step 5: 验证数据库迁移**

```bash
uv run python -c "import models; models.init_db(); print('DB migration OK')"
```

Expected: `DB migration OK`，无报错。

---

## Task 2: TaskManager — 传递 reply_to

**Files:**
- Modify: `server/task_manager.py:30-55` (Task 类)
- Modify: `server/task_manager.py:65-81` (submit 方法)

- [ ] **Step 1: Task 类添加 reply_to**

```python
class Task:
    def __init__(self, type: str, params: dict, reply_to: str = ""):
        self.id = uuid.uuid4().hex
        self.type = type
        self.status = TaskStatus.pending
        self.params = params
        self.reply_to = reply_to
        self.created_at = config.now_shanghai().isoformat()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.progress: dict = {}
        self.result: dict | None = None
        self.error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "params": self.params,
            "reply_to": self.reply_to,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "notified_at": None,
        }
```

- [ ] **Step 2: submit_scrape 和 submit_collect 接受 reply_to**

```python
def submit_scrape(self, urls: list[str], ownership: str = "competitor", reply_to: str = "") -> Task:
    task = Task(type="scrape", params={"urls": urls, "ownership": ownership}, reply_to=reply_to)
    # ... rest unchanged

def submit_collect(self, category_url: str, max_pages: int = 0, ownership: str = "competitor", reply_to: str = "") -> Task:
    task = Task(type="collect", params={"category_url": category_url, "max_pages": max_pages, "ownership": ownership}, reply_to=reply_to)
    # ... rest unchanged
```

---

## Task 3: MCP Tools — 新参数 + 新工具

**Files:**
- Modify: `server/mcp/tools.py:28-61` (start_scrape, start_collect)
- Modify: `server/mcp/tools.py` 末尾 (新工具)

- [ ] **Step 1: start_scrape 和 start_collect 添加 reply_to 参数**

```python
@mcp.tool
def start_scrape(urls: list[str], ownership: str, reply_to: str = "") -> str:
    """提交一个或多个产品页 URL 开始爬取，返回任务 ID 用于后续查询进度。
    支持 Bass Pro Shops (www.basspro.com) 和 Meat Your Maker (www.meatyourmaker.com) 站点。
    ownership: 产品归属，own 表示自有产品，competitor 表示竞品。
    reply_to: 可选，任务完成后的通知目标（如钉钉群/用户 ID），由心跳自动检测并投递。"""
    if ownership not in ("own", "competitor"):
        return _json.dumps({"error": "ownership must be 'own' or 'competitor'"})
    tm = _get_tm()
    task = tm.submit_scrape(urls, ownership=ownership, reply_to=reply_to)
    return _json.dumps({
        "message": f"任务启动成功，共 {len(urls)} 个产品待抓取。使用 get_task_status 查询进度。",
        "task_id": task.id,
        "status": task.status.value,
        "total": len(urls),
    })

@mcp.tool
def start_collect(category_url: str, ownership: str, max_pages: int = 0, reply_to: str = "") -> str:
    """从分类/列表页自动采集所有产品 URL 并逐一爬取详情。
    ownership 必填：own（自有产品）或 competitor（竞品）。
    reply_to: 可选，任务完成后的通知目标。"""
    if ownership not in ("own", "competitor"):
        return _json.dumps({"error": "ownership must be 'own' or 'competitor'"})
    tm = _get_tm()
    task = tm.submit_collect(category_url, max_pages, ownership=ownership, reply_to=reply_to)
    pages_info = f"最多 {max_pages} 页" if max_pages > 0 else "全部页"
    return _json.dumps({
        "message": f"采集任务启动成功，将从分类页采集产品（{pages_info}）并逐一抓取。使用 get_task_status 查询进度。",
        "task_id": task.id,
        "status": task.status.value,
    })
```

- [ ] **Step 2: 新增 check_pending_completions 工具**

```python
@mcp.tool
def check_pending_completions() -> str:
    """检查已完成但尚未通知的任务。返回所有终态（completed/failed/cancelled）且设置了 reply_to 但未标记 notified_at 的任务。
    心跳调用此工具可一次性获取所有待通知任务，无需逐个轮询。
    返回列表中每个任务包含：id, type, status, result, error, reply_to, finished_at。"""
    tasks = models.get_pending_completions()
    return _json.dumps({"tasks": tasks, "count": len(tasks)}, default=str)
```

- [ ] **Step 3: 新增 mark_notified 工具**

```python
@mcp.tool
def mark_notified(task_ids: list[str]) -> str:
    """将任务标记为已通知。在心跳成功投递完成通知后调用。
    task_ids: 要标记的任务 ID 列表。
    标记后这些任务不会再出现在 check_pending_completions 结果中。"""
    count = models.mark_task_notified(task_ids)
    return _json.dumps({"marked": count})
```

---

## Task 4: MCP Plugin — index.js 工具注册

**Files:**
- Modify: `server/openclaw/plugin/index.js:206-382` (TOOLS 数组)

- [ ] **Step 1: start_scrape 和 start_collect 添加 reply_to 参数**

在 TOOLS 数组的 start_scrape 和 start_collect 的 properties 中添加：

```javascript
reply_to: { type: "string", description: "Optional: notification target when task completes (DingTalk user/chat ID)" }
```

注意：reply_to 不加入 required 数组（保持可选）。

- [ ] **Step 2: 添加 check_pending_completions 工具**

```javascript
{
  name: "check_pending_completions",
  description: "Check for completed tasks that haven't been notified yet. Returns tasks with terminal status (completed/failed/cancelled) that have reply_to set but not yet marked as notified. Call this in heartbeat to discover tasks needing notification.",
  parameters: {
    type: "object",
    properties: {}
  }
},
```

- [ ] **Step 3: 添加 mark_notified 工具**

```javascript
{
  name: "mark_notified",
  description: "Mark tasks as notified after successfully delivering completion notification. Prevents duplicate notifications. Params: task_ids (array of task ID strings).",
  parameters: {
    type: "object",
    properties: {
      task_ids: { type: "array", items: { type: "string" }, description: "Task IDs to mark as notified" }
    },
    required: ["task_ids"]
  }
}
```

- [ ] **Step 4: 更新 openclaw.json 的 alsoAllow**

确认 `openclaw.json` 的 `tools.alsoAllow` 数组中添加 `"check_pending_completions"` 和 `"mark_notified"`。

---

## Task 5: AGENTS.md — 完全重写

**Files:**
- Rewrite: `server/openclaw/workspace/AGENTS.md`

- [ ] **Step 1: 写入新的 AGENTS.md**

```markdown
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
```

---

## Task 6: HEARTBEAT.md — 完全重写

**Files:**
- Rewrite: `server/openclaw/workspace/HEARTBEAT.md`

- [ ] **Step 1: 写入新的 HEARTBEAT.md**

```markdown
# 心跳检查

严格按以下步骤执行，不要自由发挥。

## 第一步：检查待通知任务

调用 `check_pending_completions()`。

如果返回 `count: 0` 且无定时任务待检查 → 回复 HEARTBEAT_OK，结束。

## 第二步：处理临时任务通知

对 `check_pending_completions` 返回的每个任务：

1. 读取任务的 `reply_to`、`status`、`result`、`error`
2. 汇总结果（成功/失败、产品数、评论数）
3. 通过 cron 投递通知到 `reply_to`（心跳输出对用户不可见）：

```bash
openclaw cron add --name "task-done-{task_id前8位}" --at 1m --session isolated --message "向用户汇报爬虫任务完成：{汇总}。如需生成报告并发送邮件，请回复「发邮件」。" --announce --to "{reply_to}" --delete-after-run
```

4. 投递后调用 `mark_notified(task_ids=[任务ID])`

IMPORTANT: 必须先投递通知，再调用 mark_notified。如果 cron add 失败，不要 mark_notified（下次心跳会重试）。

**自检**：每个任务处理后确认：
- ✅ cron add 命令已执行
- ✅ mark_notified 已调用

## 第三步：检查定时任务

读取 `~/.openclaw/workspace/state/active-tasks.json`。

如果文件不存在、为空、或内容为 `{}` → 跳过。

仅当 `tasks` 数组非空时：

1. 如果存在 `"status": "reporting"`：
   - `reporting_at` 距今超过 30 分钟 → 清空文件为 `{}`
   - 距今不超过 30 分钟 → 跳过
2. 无 reporting 状态时，对每个 task_id 调用 `get_task_status`：
   - 返回 "not found" → 视为 failed
   - 仍有 pending 或 running → 跳过
   - 全部终态 → 更新文件添加 `"status": "reporting"` 和 `"reporting_at"`，然后执行：

```bash
openclaw cron add --name "scrape-report" --at 1m --session isolated --message "执行爬虫任务汇报，读取 skills/daily-scrape-report 技能并严格执行。你的 MCP 工具（get_task_status, generate_report, get_translate_status, mark_notified）已可直接调用。按以下格式输出完成通知：🚀 标题 + 列表形式的关键数据（成功/失败数、新增评论、翻译进度、邮件状态）。" --announce --to "chat:cidoOQUuAEydsdghncIE5INqg==" --delete-after-run
```

## 结束

回复 HEARTBEAT_OK。
```

---

## Task 7: TOOLS.md — 重写，合并 output-formats

**Files:**
- Rewrite: `server/openclaw/workspace/TOOLS.md`

- [ ] **Step 1: 写入新的 TOOLS.md**

```markdown
# 工具参考

## 支持站点

- 🏪 **Bass Pro Shops**（basspro）— `www.basspro.com`
- 🥩 **Meat Your Maker**（meatyourmaker）— `www.meatyourmaker.com`

## 工具参数速查

### 任务管理

| 工具 | 必填参数 | 可选参数 |
|------|---------|---------|
| `start_scrape` | urls, ownership | reply_to |
| `start_collect` | category_url, ownership | max_pages（0=全部）, reply_to |
| `get_task_status` | task_id | — |
| `list_tasks` | — | status, limit |
| `cancel_task` | task_id | — |
| `check_pending_completions` | — | — |
| `mark_notified` | task_ids | — |

### 数据查询

| 工具 | 必填参数 | 可选参数 |
|------|---------|---------|
| `list_products` | — | site, search, min_price, max_price, stock_status, ownership, sort_by, order, limit, offset |
| `get_product_detail` | product_id 或 url 或 sku | — |
| `query_reviews` | — | product_id, sku, site, ownership, min_rating, max_rating, author, keyword, has_images, sort_by, order, limit, offset |
| `get_price_history` | product_id | days（默认30） |
| `get_stats` | — | — |
| `execute_sql` | sql | — |
| `generate_report` | since | send_email（默认 true） |
| `trigger_translate` | — | reset_skipped（默认 false） |
| `get_translate_status` | — | since（可选） |

### 参数说明

- `ownership`：`own`（自有）或 `competitor`（竞品），start_scrape/start_collect 中**必填**
- `reply_to`：任务完成后通知目标。格式 `user:{id}` 或 `chat:{id}`。传入后服务端自动追踪，心跳自动通知
- `min_price`/`max_price`/`min_rating`/`max_rating`：`-1` 表示不限制
- `max_pages`：`0` 表示采集全部页
- `has_images`：字符串 `"true"` 或 `"false"`
- `execute_sql`：仅 SELECT，500 行上限，5 秒超时
- `generate_report`：`since` 为上海时间戳（`YYYY-MM-DDTHH:MM:SS`）
- `check_pending_completions`：无参数，返回已完成但未通知的任务列表
- `mark_notified`：`task_ids` 为字符串数组，标记后任务不再出现在 pending completions 中
- 所有时间戳统一使用**上海时间**（Asia/Shanghai），格式 `YYYY-MM-DDTHH:MM:SS`，无时区后缀

## 服务端能力概览

服务端（FastAPI + FastMCP）提供以下自动化能力，agent 应充分利用：

1. **任务自动追踪**：`start_scrape`/`start_collect` 传入 `reply_to` 后，任务完成状态自动持久化到 SQLite tasks 表。不需要 agent 写状态文件。
2. **待通知任务发现**：`check_pending_completions` 一次调用返回所有"已完成但未通知"的任务，无需逐个轮询 task_id。
3. **通知标记**：`mark_notified` 防止重复通知。
4. **后台翻译**：TranslationWorker 守护线程自动翻译新评论，`get_translate_status` 查进度。
5. **报告生成**：`generate_report` 在服务端完成查询+翻译+Excel+邮件，agent 只需传 since 时间。

## CSV 文件

- 分类页：`~/.openclaw/workspace/data/sku-list-source.csv`
- 产品页：`~/.openclaw/workspace/data/sku-product-details.csv`
- 格式：`url,ownership`（有表头），一行一条

## 邮件收件人

`~/.openclaw/workspace/config/email-recipients.txt`（一行一个邮箱，`#` 为注释）

## 状态文件

- `~/.openclaw/workspace/state/active-tasks.json` — 定时任务状态（仅定时工作流使用）

注：临时任务不再使用状态文件，通过服务端 `reply_to` + `check_pending_completions` 追踪。

---

## 输出格式规范

向钉钉输出结构化内容时必须遵守以下规范。

### 基本原则

- **绝不**向用户展示 JSON、SQL、代码或工具名称
- 价格：**$XX.XX** | 评分：**X.X/5** ⭐ | 库存：✅ 有货 / ❌ 缺货
- 任务状态：⏳ 进行中 / ✔️ 完成 / ❌ 失败 / 🚫 已取消
- 给完结果后**主动建议下一步**

### 钉钉排版

**支持**：标题（# ## ###）、加粗、列表（- 和 1.）、嵌套列表、引用（>）、链接、分隔线、代码块
**不支持**：❌ 表格 | ❌ 删除线

**规则**：禁止表格用列表代替、标题分隔板块、加粗关键数据、一段不超 3 行

### 产品列表

```
## 🔍 搜索结果：共 **15** 个产品

### 1. Product Name A
- **价格**：$129.99
- **评分**：4.5/5 ⭐（128 条评论）
- **库存**：✅ 有货
- **站点**：Bass Pro Shops
```

### 任务状态

```
## 🚀 任务已启动

- **任务 ID**：xxxxxxxx
- **类型**：产品抓取（3 个产品）
- **状态**：⏳ 等待执行

完成后会自动通知。
```

### 定时任务启动通知

```
🚀 每日爬虫任务已启动

- **提交时间**：YYYY-MM-DD HH:MM
- **分类采集**：N 个任务
- **产品抓取**：N 个任务（N 个产品）
- **任务 ID**：xxx, yyy

将自动监控任务进度，完成后汇报。
```

### 定时任务完成通知

```
✅ 每日爬虫任务已完成

- **完成时间**：YYYY-MM-DD HH:MM
- **产品抓取**：成功 N，失败 N
- **新增评论**：N 条
- **翻译进度**：N/M 已完成
- **自有产品**：N 个 | **竞品**：N 个
- **邮件发送**：✅ 已发送至 N 位收件人
- **报告文件**：scrape-report-YYYY-MM-DD.xlsx
```

### 数据总览

```
## 📊 数据总览

- 📦 **产品总数**：245
- 💬 **评论总数**：3,842
- 💰 **平均价格**：$87.50
- ⭐ **平均评分**：4.1/5

---

### 站点分布
- 🏪 **Bass Pro Shops**：180 个产品
- 🥩 **Meat Your Maker**：65 个产品

### 产品归属
- 🏠 **自有产品**：N 个
- 🎯 **竞品**：N 个
```

### 评分分布

```
## 📊 评分分布（共 573 条）

- ⭐⭐⭐⭐⭐ **5星**：334 条（58.3%）████████████
- ⭐⭐⭐⭐ **4星**：87 条（15.2%）█████
- ⭐⭐⭐ **3星**：36 条（6.3%）██
- ⭐⭐ **2星**：37 条（6.5%）██
- ⭐ **1星**：79 条（13.8%）████
```
```

---

## Task 8: Skills 更新 + 删除 output-formats

**Files:**
- Modify: `server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md`
- Modify: `server/openclaw/workspace/skills/daily-scrape-report/SKILL.md`
- Delete: `server/openclaw/workspace/skills/output-formats/`

- [ ] **Step 1: 更新 daily-scrape-submit**

```markdown
---
name: daily-scrape-submit
description: 每日定时爬虫任务提交技能。由 Cron Job 触发，读取 CSV 文件提交爬虫任务并保存状态。
---

# 每日爬虫任务提交

定时 Cron Job 触发此技能，读取 CSV 文件并提交爬虫任务。

IMPORTANT: 严格按以下步骤执行，不要做任何步骤之外的事。

**你需要使用的工具**（均为已加载的 MCP 工具，直接调用即可）：
- `start_collect` — 提交分类页采集任务
- `start_scrape` — 提交产品页抓取任务

**禁止**：不要搜索命令行入口、不要探索代码库、不要寻找替代方案。工具已就绪。

## 步骤 1：读取并提交分类页任务

读取 `~/.openclaw/workspace/data/sku-list-source.csv`（格式：`url,ownership`，有表头）。

如果文件不存在或只有表头 → 跳过此步。

对每一行调用 `start_collect(category_url=url, ownership=ownership, reply_to="chat:cidoOQUuAEydsdghncIE5INqg==")`，记录返回的 task_id。

- 无效行（缺少 ownership 或 URL 为空）→ 跳过并记录

## 步骤 2：读取并提交产品页任务

读取 `~/.openclaw/workspace/data/sku-product-details.csv`（格式同上）。

如果文件不存在或只有表头 → 跳过此步。

按 ownership 分组，对每组调用 `start_scrape(urls=[该组所有URL], ownership=ownership, reply_to="chat:cidoOQUuAEydsdghncIE5INqg==")`，记录 task_id。

## 步骤 3：保存状态并汇报

如果两个 CSV 都为空 → 输出"无待采集 URL，跳过今日任务"，**流程结束**。

将所有 task_id 写入 `~/.openclaw/workspace/state/active-tasks.json`：

```json
{
  "submitted_at": "YYYY-MM-DDTHH:MM:SS",
  "tasks": [
    {"id": "task_id_1", "type": "collect", "ownership": "own"},
    {"id": "task_id_2", "type": "scrape", "ownership": "competitor"}
  ]
}
```

`submitted_at` 使用上海时间（Asia/Shanghai），格式 `YYYY-MM-DDTHH:MM:SS`（无时区后缀）。

按 TOOLS.md「定时任务启动通知」模板输出。

**自检**：
- ✅ 所有 start_collect/start_scrape 调用都传入了 reply_to
- ✅ active-tasks.json 已写入
- ✅ 启动通知已输出
```

- [ ] **Step 2: 更新 daily-scrape-report**

```markdown
---
name: daily-scrape-report
description: 爬虫任务完成后的汇报技能。由 Heartbeat 检测到所有定时任务终态后触发。汇总结果、生成报告、发送邮件、通知完成。
---

# 每日爬虫任务汇报

由 Heartbeat 检测到定时任务完成后触发。

IMPORTANT: 严格按以下步骤执行，不可跳过。

## 步骤 0：前置校验（防重复执行）

读取 `~/.openclaw/workspace/state/active-tasks.json`。

如果文件不存在、为空、内容为 `{}`、或缺少 `submitted_at` 字段、或 `tasks` 数组为空 → **静默退出，不输出任何内容**。

## 步骤 1：汇总任务结果

从 `active-tasks.json` 获取 `submitted_at` 和 `tasks` 列表。

对每个 task_id 调用 `get_task_status`，统计：
- 成功数（status = completed）
- 失败数（status = failed / cancelled / not found）
- 产品数和评论数（从 result 中提取）

## 步骤 2：生成报告并发送邮件

**可选：检查翻译完成度**

调用 `get_translate_status(since=submitted_at)` 查看翻译进度。如果 `pending > 0`，可等待 1-2 分钟后再生成。最多等 3 轮，超时直接生成。

调用 `generate_report(since=submitted_at, send_email="true")`。

从返回结果中提取：新增产品数、评论数、翻译成功数、Excel 文件路径、邮件发送状态。

## 步骤 3：通知 + 清理

按 TOOLS.md「定时任务完成通知」模板输出完成通知。

清空 `~/.openclaw/workspace/state/active-tasks.json` 为 `{}`。

## 异常处理

- `generate_report` 返回错误 → 通知中标注失败原因，仍然清理状态
- 部分任务失败 → 仍然生成报告（汇报成功任务数据）

**自检**：
- ✅ generate_report 已调用
- ✅ 完成通知已输出
- ✅ active-tasks.json 已清空为 {}
```

- [ ] **Step 3: 删除 output-formats 目录**

```bash
rm -rf server/openclaw/workspace/skills/output-formats/
```

- [ ] **Step 4: AGENTS.md 技能列表中移除 output-formats**

确认新 AGENTS.md 的技能列表中不包含 output-formats（已在 Task 5 中处理）。

---

## Task 9: 更新 CLAUDE.md 项目结构和文档

**Files:**
- Modify: `CLAUDE.md` (项目结构图、OpenClaw 工作流描述)

- [ ] **Step 1: 更新项目结构图中的 skills 列表**

移除 `output-formats/`，确认文件列表准确。

- [ ] **Step 2: 更新 OpenClaw 工作流描述**

将 CLAUDE.md 中 "OpenClaw 定时工作流" 部分更新为：

```
三阶段架构：
1. **Cron Job（每日定时，isolated）**：读取 CSV → 提交 start_scrape/start_collect（带 reply_to）→ 存 task_id 到 active-tasks.json → DingTalk 通知
2. **Heartbeat（每 5 分钟，main session，lightContext）**：调用 check_pending_completions → 有待通知任务则投递 → mark_notified；检查 active-tasks.json → 全部完成则触发阶段 3
3. **Cron Job（一次性，isolated）**：调用 generate_report → DingTalk 汇报 → 清除状态

临时任务追踪：start_scrape/start_collect 传入 reply_to 参数，服务端自动持久化到 tasks 表。心跳通过 check_pending_completions 发现已完成任务并投递通知，不再依赖 adhoc-tasks.json 文件。
```

- [ ] **Step 3: 更新 Workspace 文件体系描述**

```
- `TOOLS.md` — 工具参数参考 + 输出格式模板（钉钉 Markdown 规范）
```

---

## Task 10: 端到端验证

- [ ] **Step 1: 启动服务验证数据库迁移**

```bash
uv run python -c "
import models
models.init_db()
import sqlite3
conn = sqlite3.connect('data/products.db')
cols = [row[1] for row in conn.execute('PRAGMA table_info(tasks)').fetchall()]
assert 'reply_to' in cols, 'reply_to column missing'
assert 'notified_at' in cols, 'notified_at column missing'
print('✅ DB schema OK:', cols)
conn.close()
"
```

- [ ] **Step 2: 验证 MCP 工具注册**

```bash
uv run python -c "
from server.app import mcp
tools = [t.name for t in mcp._tool_manager.list_tools()]
assert 'check_pending_completions' in tools
assert 'mark_notified' in tools
assert 'start_scrape' in tools
print('✅ MCP tools OK:', len(tools), 'tools registered')
print(tools)
"
```

- [ ] **Step 3: 验证 check_pending_completions 返回空**

```bash
uv run python -c "
import json, models
models.init_db()
result = models.get_pending_completions()
print('✅ Pending completions:', len(result))
"
```

- [ ] **Step 4: 验证 start_scrape 传入 reply_to 后持久化**

```bash
uv run python -c "
import json, models
models.init_db()
from server.task_manager import TaskManager
tm = TaskManager(max_workers=1)
# 不实际运行，只验证 Task 对象
from server.task_manager import Task
t = Task(type='scrape', params={'urls': ['test'], 'ownership': 'own'}, reply_to='chat:test123')
assert t.reply_to == 'chat:test123'
d = t.to_dict()
assert d['reply_to'] == 'chat:test123'
print('✅ Task reply_to OK')
"
```

- [ ] **Step 5: 验证所有 workspace 文件语法正确**

```bash
# 确认所有 .md 文件存在且非空
ls -la server/openclaw/workspace/AGENTS.md
ls -la server/openclaw/workspace/HEARTBEAT.md
ls -la server/openclaw/workspace/TOOLS.md
ls -la server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md
ls -la server/openclaw/workspace/skills/daily-scrape-report/SKILL.md
ls -la server/openclaw/workspace/skills/csv-management/SKILL.md
# 确认 output-formats 已删除
test ! -d server/openclaw/workspace/skills/output-formats && echo "✅ output-formats deleted"
```
