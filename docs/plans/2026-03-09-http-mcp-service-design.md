# HTTP API + MCP 服务设计方案

> 日期：2026-03-09
> 状态：已确认

## 1. 需求摘要

为 Qbu-Crawler 项目添加 HTTP API 和 MCP 服务能力：

- 通过 HTTP / MCP 启动爬虫任务、查询状态、取消任务
- 通过 MCP 查询各类采集数据（产品、评论、快照、统计）
- 保留现有 CLI 模式不受影响

## 2. 决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 部署方式 | 单进程 + CLI 保留 | `main.py serve` 启动服务，`main.py <url>` 直接抓取 |
| MCP 传输 | Streamable HTTP | 最新规范，与 HTTP API 共用 ASGI 进程 |
| 任务管理 | 基础队列 + 取消 + 历史记录 | 满足当前规模，不过度设计 |
| 数据查询 | 语义化 Tool + 只读 SQL + Resources 元数据 | 三层递进，覆盖从简单到复杂的查询场景 |
| 认证 | API Key（Header: Authorization: Bearer） | 内部使用，简单够用 |
| HTTP 框架 | FastAPI | 已有经验，OpenAPI 文档，async 原生，与 FastMCP mount 天然契合 |

## 3. 整体架构

```
main.py serve [--host 0.0.0.0] [--port 8000]
    │
    Uvicorn (ASGI)
    │
    ├── FastAPI app                    ← /api/*
    │   ├── /api/tasks      (POST/GET/DELETE)
    │   ├── /api/products   (GET)
    │   ├── /api/reviews    (GET)
    │   └── /api/snapshots  (GET)
    │
    ├── FastMCP app                    ← /mcp (Streamable HTTP)
    │   ├── Tools: 任务操作（start_scrape, cancel_task, ...）
    │   ├── Tools: 数据查询（list_products, query_reviews, ...）
    │   ├── Tools: execute_sql（只读高级查询）
    │   └── Resources: db://schema/* （表结构元数据）
    │
    └── TaskManager (单例，共享)
        ├── ThreadPoolExecutor (爬虫执行)
        ├── tasks: dict[str, Task]  (内存活跃任务)
        ├── _cancel_flags: dict[str, Event]  (取消信号)
        └── SQLite tasks 表 (持久化历史)
```

CLI 模式（`main.py <url>` / `-f` / `-c`）完全保留，不经过 server 层。

## 4. 新增文件结构

```
Qbu-Crawler/
├── main.py                 # 改：增加 serve 子命令
├── server/
│   ├── __init__.py
│   ├── app.py              # FastAPI app + FastMCP mount + Uvicorn 启动
│   ├── task_manager.py     # TaskManager 单例
│   ├── api/
│   │   ├── __init__.py
│   │   ├── tasks.py        # 任务相关 HTTP endpoints
│   │   ├── products.py     # 产品数据查询 endpoints
│   │   └── auth.py         # API Key 中间件
│   └── mcp/
│       ├── __init__.py
│       ├── tools.py        # MCP Tools 定义
│       └── resources.py    # MCP Resources 定义
├── models.py               # 改：增加 tasks 表 + 查询函数
└── config.py               # 改：增加服务器相关配置
```

## 5. 任务模型

### 状态机

```
pending → running → completed
                  → failed
         → cancelled（用户取消）
```

### Task 数据结构

```python
class TaskStatus(str, Enum):
    pending   = "pending"
    running   = "running"
    completed = "completed"
    failed    = "failed"
    cancelled = "cancelled"

class Task:
    id: str                    # UUID
    type: "scrape" | "collect"
    status: TaskStatus
    params: dict               # {urls: [...]} 或 {category_url, max_pages}
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: dict             # {total: 10, completed: 3, failed: 1, current_url: "..."}
    result: dict | None        # {products_saved: 8, reviews_saved: 45}
    error: str | None
```

### tasks 表（SQLite 持久化）

```sql
CREATE TABLE tasks (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    status       TEXT NOT NULL,
    params       TEXT NOT NULL,      -- JSON
    progress     TEXT,               -- JSON
    result       TEXT,               -- JSON
    error        TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP
);
```

### TaskManager 核心接口

```python
class TaskManager:
    _executor: ThreadPoolExecutor     # max_workers=3
    _tasks: dict[str, Task]           # 内存活跃任务
    _cancel_flags: dict[str, Event]   # 取消信号

    submit_task(type, params) → Task
    cancel_task(task_id) → bool
    get_task(task_id) → Task | None
    list_tasks(status?) → list[Task]
```

### 取消机制

在 URL 粒度实现：`_run_scrape` 循环中每个 URL 前检查 `Event.is_set()`，当前 URL 跑完后停止后续执行。不侵入 scraper 内部。

## 6. HTTP API

### 认证

所有 `/api/*` 需 Header：`Authorization: Bearer <API_KEY>`

### 任务管理

```
POST   /api/tasks/scrape
  Body: { "urls": ["https://..."] }
  Resp: { "task_id": "uuid", "status": "pending", "total": N }

POST   /api/tasks/collect
  Body: { "category_url": "https://...", "max_pages": 3 }
  Resp: { "task_id": "uuid", "status": "pending" }

GET    /api/tasks
  Query: ?status=running&limit=20&offset=0
  Resp: { "tasks": [...], "total": N }

GET    /api/tasks/{task_id}
  Resp: { "id", "type", "status", "progress", "result", "error", ... }

DELETE /api/tasks/{task_id}
  Resp: { "task_id": "uuid", "status": "cancelled" }
```

### 数据查询

```
GET    /api/products
  Query: ?site=basspro&search=rod&min_price=10&max_price=100
         &sort_by=price&order=desc&limit=20&offset=0
  Resp: { "items": [...], "total": N }

GET    /api/products/{product_id}
  Resp: { ...product, "reviews": [...], "snapshots": [...] }

GET    /api/products/{product_id}/reviews
  Query: ?min_rating=3&sort_by=date&limit=20&offset=0
  Resp: { "items": [...], "total": N }

GET    /api/products/{product_id}/snapshots
  Query: ?start_date=2026-01-01&end_date=2026-03-09
  Resp: { "items": [...], "total": N }

GET    /api/stats
  Resp: { "total_products": N, "by_site": {...}, "total_reviews": N, ... }
```

## 7. MCP Tools

### 任务操作组

| Tool | 参数 | 描述 |
|------|------|------|
| `start_scrape` | `urls: list[str]` | 提交一个或多个产品页 URL 开始爬取，返回任务 ID。支持 Bass Pro Shops 和 Meat Your Maker 站点，URL 会自动识别站点。 |
| `start_collect` | `category_url: str, max_pages?: int` | 从分类页自动采集所有产品 URL 并逐一爬取。max_pages 限制翻页数，0 或不传表示全部采集。 |
| `get_task_status` | `task_id: str` | 查询爬虫任务的实时状态，返回进度（已完成/总数）、当前正在处理的 URL、耗时等。 |
| `list_tasks` | `status?: enum, limit?: int` | 列出任务记录。可按状态筛选：pending/running/completed/failed/cancelled。默认返回最近 20 条。 |
| `cancel_task` | `task_id: str` | 取消正在运行的爬虫任务。当前 URL 会完成处理，后续 URL 不再执行。 |

### 数据查询组

| Tool | 参数 | 描述 |
|------|------|------|
| `list_products` | `site?, search?, min_price?, max_price?, stock_status?, sort_by?, limit?, offset?` | 搜索和筛选已采集的产品。可按站点、名称关键词、价格区间、库存状态过滤，支持按 price/rating/review_count/scraped_at 排序。 |
| `get_product_detail` | `product_id?, url?, sku?` | 获取单个产品完整信息，含最新价格、库存、评分及最近 5 条评论摘要。支持通过 ID、URL 或 SKU 查找。 |
| `query_reviews` | `product_id?, site?, min_rating?, max_rating?, author?, keyword?, has_images?, sort_by?, limit?, offset?` | 查询产品评论。可跨产品按站点搜索，支持评分区间、作者、关键词、是否有图片等过滤。 |
| `get_price_history` | `product_id: int, days?: int` | 获取产品价格和库存变化历史。默认最近 30 天，返回时间序列数据。 |
| `get_stats` | 无 | 数据库整体统计：各站点产品数、评论数、最近采集时间、价格分布概览。 |

### 高级查询组

| Tool | 参数 | 描述 |
|------|------|------|
| `execute_sql` | `sql: str` | 对采集数据库执行只读 SQL 查询。仅允许 SELECT，超时 5 秒，最多 500 行。适合聚合分析、多表 JOIN 等语义化工具无法覆盖的场景。执行前请先通过 Resources 了解表结构。 |

## 8. MCP Resources

暴露数据库元数据，让 LLM 写 SQL 前了解表结构：

| Resource URI | 内容 |
|-------------|------|
| `db://schema/overview` | 所有表概览 + 表间关系 + 业务说明 |
| `db://schema/products` | products 表结构 + 列说明 + 业务语义 |
| `db://schema/product_snapshots` | product_snapshots 表结构 + 列说明 |
| `db://schema/reviews` | reviews 表结构 + 列说明 |
| `db://schema/tasks` | tasks 表结构 + 列说明 |

每个 Resource 包含：表名、列（名称/类型/约束/业务说明）、关联关系、示例查询。

## 9. 新增依赖

```toml
dependencies = [
    "drissionpage",
    "minio",
    "python-dotenv",
    "requests",
    # 新增
    "fastapi",
    "uvicorn[standard]",
    "mcp[cli]",
]
```

## 10. 新增配置

```python
# config.py 新增
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))
SQL_QUERY_TIMEOUT = 5
SQL_QUERY_MAX_ROWS = 500
```

```env
# .env 新增
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
API_KEY=your-secret-key
MAX_WORKERS=3
```

## 11. CLI 入口变更

```bash
# 新增
uv run python main.py serve [--host HOST] [--port PORT]

# 不变
uv run python main.py <url>
uv run python main.py -f urls.txt
uv run python main.py -c <category-url> [max_pages]
```
