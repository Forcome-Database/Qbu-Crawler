# HTTP API + MCP 服务实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 Qbu-Crawler 添加 FastAPI HTTP 接口和 FastMCP 服务，支持任务管理与数据查询，保留现有 CLI。

**Architecture:** 单进程 ASGI 服务，FastAPI 处理 `/api/*`，FastMCP 挂载到 `/mcp`，共享 TaskManager 单例管理爬虫任务。爬虫在 ThreadPoolExecutor 中同步执行，通过 asyncio.run_in_executor 桥接到 async 层。

**Tech Stack:** FastAPI, uvicorn, FastMCP 3.x (Streamable HTTP), SQLite, ThreadPoolExecutor

**Design Doc:** `docs/plans/2026-03-09-http-mcp-service-design.md`

---

### Task 1: 添加依赖 + 项目配置

**Files:**
- Modify: `pyproject.toml`
- Modify: `config.py`
- Modify: `.env.example`（如存在）或 `.env`

**Step 1: 更新 pyproject.toml 添加新依赖**

在 `dependencies` 列表中添加：

```toml
dependencies = [
    "drissionpage",
    "minio",
    "python-dotenv",
    "requests",
    "fastapi",
    "uvicorn[standard]",
    "fastmcp>=2.0.0",
]
```

**Step 2: 安装依赖**

Run: `uv sync`
Expected: 成功安装 fastapi, uvicorn, fastmcp 及其依赖

**Step 3: 在 config.py 中添加服务器配置**

在 `config.py` 末尾添加：

```python
# ── Server ──────────────────────────────────────────
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")

# ── Task Manager ────────────────────────────────────
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))

# ── SQL Query Limits ────────────────────────────────
SQL_QUERY_TIMEOUT = 5       # execute_sql 超时秒数
SQL_QUERY_MAX_ROWS = 500    # execute_sql 最大返回行数
```

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock config.py
git commit -m "feat: add FastAPI/FastMCP dependencies and server config"
```

---

### Task 2: models.py — 添加 tasks 表 + 查询函数

**Files:**
- Modify: `models.py`

**Step 1: 在 init_db() 中添加 tasks 表创建**

在 `init_db()` 函数的现有 CREATE TABLE 语句之后添加：

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id           TEXT PRIMARY KEY,
        type         TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        params       TEXT NOT NULL,
        progress     TEXT,
        result       TEXT,
        error        TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at   TIMESTAMP,
        finished_at  TIMESTAMP
    )
""")
```

**Step 2: 添加任务持久化函数**

在 `models.py` 末尾添加：

```python
import json as _json

def save_task(task_dict: dict) -> None:
    """INSERT or UPDATE a task record."""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO tasks (id, type, status, params, progress, result, error,
                                  created_at, started_at, finished_at)
               VALUES (:id, :type, :status, :params, :progress, :result, :error,
                       :created_at, :started_at, :finished_at)
               ON CONFLICT(id) DO UPDATE SET
                   status=excluded.status, progress=excluded.progress,
                   result=excluded.result, error=excluded.error,
                   started_at=excluded.started_at, finished_at=excluded.finished_at
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
            },
        )
        conn.commit()
    finally:
        conn.close()


def get_task(task_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("params", "progress", "result"):
            if d.get(k):
                d[k] = _json.loads(d[k])
        return d
    finally:
        conn.close()


def list_tasks(status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        where = "WHERE status = ?" if status else ""
        params = [status] if status else []

        total = conn.execute(f"SELECT COUNT(*) FROM tasks {where}", params).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        tasks = []
        for row in rows:
            d = dict(row)
            for k in ("params", "progress", "result"):
                if d.get(k):
                    d[k] = _json.loads(d[k])
            tasks.append(d)
        return tasks, total
    finally:
        conn.close()
```

**Step 3: 添加数据查询函数**

这些函数供 HTTP API 和 MCP Tools 共用：

```python
def query_products(
    site: str | None = None,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    stock_status: str | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        conditions, params = [], []
        if site:
            conditions.append("site = ?"); params.append(site)
        if search:
            conditions.append("name LIKE ?"); params.append(f"%{search}%")
        if min_price is not None:
            conditions.append("price >= ?"); params.append(min_price)
        if max_price is not None:
            conditions.append("price <= ?"); params.append(max_price)
        if stock_status:
            conditions.append("stock_status = ?"); params.append(stock_status)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        # Whitelist sort columns
        allowed_sorts = {"price", "rating", "review_count", "scraped_at", "name"}
        if sort_by not in allowed_sorts:
            sort_by = "scraped_at"
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        total = conn.execute(f"SELECT COUNT(*) FROM products {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM products {where} ORDER BY {sort_by} {order_dir} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_product_by_id(product_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_product_by_url(url: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_product_by_sku(sku: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def query_reviews(
    product_id: int | None = None,
    site: str | None = None,
    min_rating: float | None = None,
    max_rating: float | None = None,
    author: str | None = None,
    keyword: str | None = None,
    has_images: bool | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        conditions, params = [], []
        if product_id is not None:
            conditions.append("r.product_id = ?"); params.append(product_id)
        if site:
            conditions.append("p.site = ?"); params.append(site)
        if min_rating is not None:
            conditions.append("r.rating >= ?"); params.append(min_rating)
        if max_rating is not None:
            conditions.append("r.rating <= ?"); params.append(max_rating)
        if author:
            conditions.append("r.author LIKE ?"); params.append(f"%{author}%")
        if keyword:
            conditions.append("(r.headline LIKE ? OR r.body LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if has_images is True:
            conditions.append("r.images IS NOT NULL AND r.images != '[]' AND r.images != ''")
        elif has_images is False:
            conditions.append("(r.images IS NULL OR r.images = '[]' OR r.images = '')")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        allowed_sorts = {"rating": "r.rating", "scraped_at": "r.scraped_at", "date_published": "r.date_published"}
        sort_col = allowed_sorts.get(sort_by, "r.scraped_at")
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        total = conn.execute(
            f"SELECT COUNT(*) FROM reviews r JOIN products p ON r.product_id = p.id {where}",
            params,
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT r.*, p.name as product_name, p.site as product_site
                FROM reviews r JOIN products p ON r.product_id = p.id
                {where} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if d.get("images"):
                d["images"] = _json.loads(d["images"]) if isinstance(d["images"], str) else d["images"]
            results.append(d)
        return results, total
    finally:
        conn.close()


def get_snapshots(
    product_id: int,
    days: int = 30,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM product_snapshots WHERE product_id = ? AND scraped_at >= datetime('now', ?)",
            (product_id, f"-{days} days"),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM product_snapshots
               WHERE product_id = ? AND scraped_at >= datetime('now', ?)
               ORDER BY scraped_at ASC LIMIT ? OFFSET ?""",
            (product_id, f"-{days} days", limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_stats() -> dict:
    conn = get_conn()
    try:
        total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        total_reviews = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

        by_site = {}
        for row in conn.execute("SELECT site, COUNT(*) as cnt FROM products GROUP BY site").fetchall():
            by_site[row["site"]] = row["cnt"]

        last_scrape = conn.execute("SELECT MAX(scraped_at) FROM products").fetchone()[0]

        avg_price = conn.execute("SELECT AVG(price) FROM products WHERE price IS NOT NULL").fetchone()[0]
        avg_rating = conn.execute("SELECT AVG(rating) FROM products WHERE rating IS NOT NULL").fetchone()[0]

        return {
            "total_products": total_products,
            "total_reviews": total_reviews,
            "by_site": by_site,
            "last_scrape_at": last_scrape,
            "avg_price": round(avg_price, 2) if avg_price else None,
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
        }
    finally:
        conn.close()


def execute_readonly_sql(sql: str, timeout: int = 5, max_rows: int = 500) -> dict:
    """Execute a read-only SQL query. Raises ValueError for non-SELECT statements."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed")

    conn = get_conn()
    try:
        conn.execute(f"PRAGMA busy_timeout = {timeout * 1000}")
        cursor = conn.execute(stripped)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        conn.close()
```

**Step 4: Commit**

```bash
git add models.py
git commit -m "feat: add tasks table and data query functions to models.py"
```

---

### Task 3: TaskManager — 任务生命周期管理

**Files:**
- Create: `server/__init__.py`
- Create: `server/task_manager.py`

**Step 1: 创建 server 包**

`server/__init__.py` — 空文件

**Step 2: 实现 TaskManager**

`server/task_manager.py`:

```python
"""Crawler task lifecycle manager.

Manages scrape/collect tasks in a thread pool, tracks progress,
supports cancellation, and persists task history to SQLite.
"""

import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import models
from scrapers import get_scraper, get_site_key

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Task:
    def __init__(self, type: str, params: dict):
        self.id = uuid.uuid4().hex
        self.type = type
        self.status = TaskStatus.pending
        self.params = params
        self.created_at = datetime.now(timezone.utc).isoformat()
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
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


class TaskManager:
    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, Task] = {}
        self._cancel_flags: dict[str, Event] = {}

    def submit_scrape(self, urls: list[str]) -> Task:
        task = Task(type="scrape", params={"urls": urls})
        task.progress = {"total": len(urls), "completed": 0, "failed": 0, "current_url": None}
        self._tasks[task.id] = task
        self._cancel_flags[task.id] = Event()
        self._persist(task)
        self._executor.submit(self._run_scrape, task.id)
        return task

    def submit_collect(self, category_url: str, max_pages: int = 0) -> Task:
        task = Task(type="collect", params={"category_url": category_url, "max_pages": max_pages})
        task.progress = {"phase": "collecting", "urls_found": 0, "completed": 0, "failed": 0}
        self._tasks[task.id] = task
        self._cancel_flags[task.id] = Event()
        self._persist(task)
        self._executor.submit(self._run_collect, task.id)
        return task

    def cancel_task(self, task_id: str) -> bool:
        flag = self._cancel_flags.get(task_id)
        task = self._tasks.get(task_id)
        if not flag or not task:
            return False
        if task.status not in (TaskStatus.pending, TaskStatus.running):
            return False
        flag.set()
        task.status = TaskStatus.cancelled
        task.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist(task)
        return True

    def get_task(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        if task:
            return task.to_dict()
        # Fallback to DB for historical tasks
        return models.get_task(task_id)

    def list_tasks(self, status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        return models.list_tasks(status=status, limit=limit, offset=offset)

    # ── Internal runners ──────────────────────────────

    def _run_scrape(self, task_id: str):
        task = self._tasks[task_id]
        flag = self._cancel_flags[task_id]
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc).isoformat()
        self._persist(task)

        urls = task.params["urls"]
        products_saved = 0
        reviews_saved = 0
        scraper = None

        try:
            for i, url in enumerate(urls):
                if flag.is_set():
                    break

                task.progress["current_url"] = url
                self._persist(task)

                try:
                    if scraper is None or get_site_key(url) != getattr(scraper, '_current_site', None):
                        if scraper:
                            scraper.close()
                        scraper = get_scraper(url)
                        scraper._current_site = get_site_key(url)

                    data = scraper.scrape(url)
                    product = data.get("product", {})
                    reviews = data.get("reviews", [])

                    pid = models.save_product(product)
                    models.save_snapshot(pid, product)
                    rc = models.save_reviews(pid, reviews)

                    products_saved += 1
                    reviews_saved += rc
                    task.progress["completed"] = i + 1

                except Exception as e:
                    logger.error(f"[Task {task_id}] Failed {url}: {e}")
                    task.progress["failed"] = task.progress.get("failed", 0) + 1
                    task.progress["completed"] = i + 1

                self._persist(task)

            if flag.is_set():
                task.status = TaskStatus.cancelled
            else:
                task.status = TaskStatus.completed
                task.result = {"products_saved": products_saved, "reviews_saved": reviews_saved}

        except Exception as e:
            task.status = TaskStatus.failed
            task.error = str(e)
            logger.exception(f"[Task {task_id}] Fatal error")
        finally:
            if scraper:
                scraper.close()
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.progress["current_url"] = None
            self._persist(task)

    def _run_collect(self, task_id: str):
        task = self._tasks[task_id]
        flag = self._cancel_flags[task_id]
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc).isoformat()
        self._persist(task)

        category_url = task.params["category_url"]
        max_pages = task.params.get("max_pages", 0)
        scraper = None

        try:
            scraper = get_scraper(category_url)

            # Phase 1: collect URLs
            urls = scraper.collect_product_urls(category_url, max_pages=max_pages)
            task.progress = {
                "phase": "scraping",
                "urls_found": len(urls),
                "total": len(urls),
                "completed": 0,
                "failed": 0,
                "current_url": None,
            }
            self._persist(task)

            if flag.is_set():
                task.status = TaskStatus.cancelled
                return

            # Phase 2: scrape each URL
            products_saved = 0
            reviews_saved = 0

            for i, url in enumerate(urls):
                if flag.is_set():
                    break

                task.progress["current_url"] = url
                self._persist(task)

                try:
                    data = scraper.scrape(url)
                    product = data.get("product", {})
                    reviews = data.get("reviews", [])

                    pid = models.save_product(product)
                    models.save_snapshot(pid, product)
                    rc = models.save_reviews(pid, reviews)

                    products_saved += 1
                    reviews_saved += rc
                    task.progress["completed"] = i + 1

                except Exception as e:
                    logger.error(f"[Task {task_id}] Failed {url}: {e}")
                    task.progress["failed"] = task.progress.get("failed", 0) + 1
                    task.progress["completed"] = i + 1

                self._persist(task)

            if flag.is_set():
                task.status = TaskStatus.cancelled
            else:
                task.status = TaskStatus.completed
                task.result = {"products_saved": products_saved, "reviews_saved": reviews_saved}

        except Exception as e:
            task.status = TaskStatus.failed
            task.error = str(e)
            logger.exception(f"[Task {task_id}] Fatal error")
        finally:
            if scraper:
                scraper.close()
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.progress["current_url"] = None
            self._persist(task)

    def _persist(self, task: Task):
        try:
            models.save_task(task.to_dict())
        except Exception as e:
            logger.error(f"Failed to persist task {task.id}: {e}")
```

**Step 3: Commit**

```bash
git add server/
git commit -m "feat: implement TaskManager with thread pool execution and cancellation"
```

---

### Task 4: HTTP API — 认证中间件 + 任务 endpoints

**Files:**
- Create: `server/api/__init__.py`
- Create: `server/api/auth.py`
- Create: `server/api/tasks.py`

**Step 1: API Key 认证中间件**

`server/api/auth.py`:

```python
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import config

security = HTTPBearer()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    if not config.API_KEY:
        raise HTTPException(500, "API_KEY not configured on server")
    if credentials.credentials != config.API_KEY:
        raise HTTPException(401, "Invalid API key")
```

**Step 2: 任务管理 endpoints**

`server/api/tasks.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.api.auth import verify_api_key

router = APIRouter(prefix="/api/tasks", dependencies=[Depends(verify_api_key)])


class ScrapeRequest(BaseModel):
    urls: list[str]

class CollectRequest(BaseModel):
    category_url: str
    max_pages: int = 0


def _get_tm():
    from server.app import task_manager
    return task_manager


@router.post("/scrape")
async def create_scrape_task(req: ScrapeRequest):
    if not req.urls:
        raise HTTPException(400, "urls cannot be empty")
    tm = _get_tm()
    task = tm.submit_scrape(req.urls)
    return {"task_id": task.id, "status": task.status.value, "total": len(req.urls)}


@router.post("/collect")
async def create_collect_task(req: CollectRequest):
    tm = _get_tm()
    task = tm.submit_collect(req.category_url, req.max_pages)
    return {"task_id": task.id, "status": task.status.value}


@router.get("")
async def list_tasks(status: str | None = None, limit: int = 20, offset: int = 0):
    tm = _get_tm()
    tasks, total = tm.list_tasks(status=status, limit=limit, offset=offset)
    return {"tasks": tasks, "total": total}


@router.get("/{task_id}")
async def get_task(task_id: str):
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    tm = _get_tm()
    ok = tm.cancel_task(task_id)
    if not ok:
        raise HTTPException(404, "Task not found or not cancellable")
    return {"task_id": task_id, "status": "cancelled"}
```

**Step 3: Commit**

```bash
git add server/api/
git commit -m "feat: HTTP API auth middleware and task management endpoints"
```

---

### Task 5: HTTP API — 数据查询 endpoints

**Files:**
- Create: `server/api/products.py`

**Step 1: 实现产品/评论/快照/统计查询**

`server/api/products.py`:

```python
from fastapi import APIRouter, Depends, HTTPException

import models
from server.api.auth import verify_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


@router.get("/products")
async def list_products(
    site: str | None = None,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    stock_status: str | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
):
    items, total = models.query_products(
        site=site, search=search, min_price=min_price, max_price=max_price,
        stock_status=stock_status, sort_by=sort_by, order=order,
        limit=limit, offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/products/{product_id}")
async def get_product(product_id: int):
    product = models.get_product_by_id(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    reviews, _ = models.query_reviews(product_id=product_id, limit=5)
    snapshots, _ = models.get_snapshots(product_id=product_id, days=30, limit=10)
    return {**product, "recent_reviews": reviews, "recent_snapshots": snapshots}


@router.get("/products/{product_id}/reviews")
async def get_product_reviews(
    product_id: int,
    min_rating: float | None = None,
    max_rating: float | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
):
    items, total = models.query_reviews(
        product_id=product_id, min_rating=min_rating, max_rating=max_rating,
        sort_by=sort_by, order=order, limit=limit, offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/products/{product_id}/snapshots")
async def get_product_snapshots(product_id: int, days: int = 30, limit: int = 100, offset: int = 0):
    items, total = models.get_snapshots(product_id=product_id, days=days, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/stats")
async def get_stats():
    return models.get_stats()
```

**Step 2: Commit**

```bash
git add server/api/products.py
git commit -m "feat: HTTP API data query endpoints (products, reviews, snapshots, stats)"
```

---

### Task 6: MCP Resources — 数据库元数据

**Files:**
- Create: `server/mcp/__init__.py`
- Create: `server/mcp/resources.py`

**Step 1: 实现 MCP Resources**

`server/mcp/resources.py`:

```python
"""MCP Resources — expose database schema metadata for LLM context."""

from fastmcp import FastMCP

SCHEMA_OVERVIEW = """
# Qbu-Crawler 数据库结构概览

## 表关系

```
products (产品当前快照)
  ├── product_snapshots (价格/库存/评分历史，FK: product_id)
  └── reviews (用户评论，FK: product_id)
tasks (爬虫任务记录)
```

## 支持的站点
- basspro (Bass Pro Shops)
- meatyourmaker (Meat Your Maker)

## 数据特性
- products 表使用 UPSERT，始终是最新状态
- product_snapshots 每次采集 INSERT，记录变化趋势
- reviews 增量写入，用 (product_id, author, headline, body_hash) 去重
- tasks 记录任务历史，params/progress/result 为 JSON 字段
"""

SCHEMA_PRODUCTS = """
## products 表 — 产品当前快照

每个产品的最新状态，URL 唯一键，每次采集 UPSERT 更新。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 产品 ID |
| url | TEXT | UNIQUE, NOT NULL | 产品页 URL |
| site | TEXT | NOT NULL | 站点标识：basspro, meatyourmaker |
| name | TEXT | | 产品名称 |
| sku | TEXT | | SKU 编号 |
| price | REAL | | 当前价格 (USD) |
| stock_status | TEXT | | 库存状态：in_stock, out_of_stock, unknown |
| review_count | INTEGER | | 评论总数 |
| rating | REAL | | 平均评分 (0-5) |
| scraped_at | TIMESTAMP | | 最后采集时间 |

### 常用查询示例
```sql
-- 按站点查询高评分产品
SELECT * FROM products WHERE site = 'basspro' AND rating >= 4.5 ORDER BY rating DESC;

-- 搜索产品名称
SELECT * FROM products WHERE name LIKE '%fishing%' ORDER BY price ASC;

-- 库存状态统计
SELECT site, stock_status, COUNT(*) FROM products GROUP BY site, stock_status;
```
"""

SCHEMA_SNAPSHOTS = """
## product_snapshots 表 — 价格/库存/评分历史

每次采集 INSERT 一条，用于趋势分析和价格追踪。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 快照 ID |
| product_id | INTEGER | FK → products.id, CASCADE | 关联产品 |
| price | REAL | | 采集时价格 (USD) |
| stock_status | TEXT | | 采集时库存状态 |
| review_count | INTEGER | | 采集时评论数 |
| rating | REAL | | 采集时评分 |
| scraped_at | TIMESTAMP | | 采集时间 |

### 常用查询示例
```sql
-- 产品价格变化趋势
SELECT scraped_at, price FROM product_snapshots WHERE product_id = 1 ORDER BY scraped_at;

-- 过去7天有价格变动的产品
SELECT DISTINCT ps.product_id, p.name
FROM product_snapshots ps JOIN products p ON ps.product_id = p.id
WHERE ps.scraped_at >= datetime('now', '-7 days')
GROUP BY ps.product_id HAVING MAX(ps.price) != MIN(ps.price);
```
"""

SCHEMA_REVIEWS = """
## reviews 表 — 用户评论

增量写入，(product_id, author, headline, body_hash) 联合唯一键去重。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 评论 ID |
| product_id | INTEGER | FK → products.id, CASCADE | 关联产品 |
| author | TEXT | | 评论作者 |
| headline | TEXT | | 评论标题 |
| body | TEXT | | 评论正文 |
| body_hash | TEXT | | MD5(body) 前16位，用于去重 |
| rating | REAL | | 评论评分 (0-5) |
| date_published | TEXT | | 发布日期 |
| images | TEXT | | JSON 数组，MinIO 图片 URL 列表 |
| scraped_at | TIMESTAMP | | 采集时间 |

### 常用查询示例
```sql
-- 某产品所有差评
SELECT * FROM reviews WHERE product_id = 1 AND rating <= 2 ORDER BY date_published DESC;

-- 带图片的评论
SELECT r.*, p.name FROM reviews r JOIN products p ON r.product_id = p.id
WHERE r.images IS NOT NULL AND r.images != '[]';

-- 各产品平均评论评分 vs 产品评分对比
SELECT p.name, p.rating as product_rating, AVG(r.rating) as avg_review_rating
FROM products p JOIN reviews r ON p.id = r.product_id GROUP BY p.id;
```
"""

SCHEMA_TASKS = """
## tasks 表 — 爬虫任务记录

记录所有通过 API/MCP 提交的爬虫任务历史。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | 任务 UUID |
| type | TEXT | NOT NULL | 任务类型：scrape（按URL抓取）, collect（分类页采集） |
| status | TEXT | NOT NULL | 状态：pending, running, completed, failed, cancelled |
| params | TEXT (JSON) | NOT NULL | 任务参数，scrape: {"urls": [...]}, collect: {"category_url": "...", "max_pages": N} |
| progress | TEXT (JSON) | | 进度信息 {"total": N, "completed": N, "failed": N, "current_url": "..."} |
| result | TEXT (JSON) | | 完成结果 {"products_saved": N, "reviews_saved": N} |
| error | TEXT | | 失败时的错误信息 |
| created_at | TIMESTAMP | | 创建时间 |
| started_at | TIMESTAMP | | 开始执行时间 |
| finished_at | TIMESTAMP | | 完成时间 |

### 常用查询示例
```sql
-- 最近的任务
SELECT id, type, status, progress, result, created_at FROM tasks ORDER BY created_at DESC LIMIT 10;

-- 各状态任务数
SELECT status, COUNT(*) FROM tasks GROUP BY status;
```
"""

SCHEMAS = {
    "overview": SCHEMA_OVERVIEW,
    "products": SCHEMA_PRODUCTS,
    "product_snapshots": SCHEMA_SNAPSHOTS,
    "reviews": SCHEMA_REVIEWS,
    "tasks": SCHEMA_TASKS,
}


def register_resources(mcp: FastMCP):
    """Register all schema resources on the MCP server."""

    @mcp.resource("db://schema/{table_name}")
    def get_schema(table_name: str) -> str:
        """获取数据库表的结构说明，包含列定义、约束、业务语义和示例 SQL。
        可用的 table_name: overview, products, product_snapshots, reviews, tasks。
        使用 overview 查看所有表的关系概览。"""
        content = SCHEMAS.get(table_name)
        if not content:
            return f"Unknown table: {table_name}. Available: {', '.join(SCHEMAS.keys())}"
        return content
```

**Step 2: Commit**

```bash
git add server/mcp/
git commit -m "feat: MCP Resources — database schema metadata for LLM context"
```

---

### Task 7: MCP Tools — 任务操作 + 数据查询 + execute_sql

**Files:**
- Create: `server/mcp/tools.py`

**Step 1: 实现所有 MCP Tools**

`server/mcp/tools.py`:

```python
"""MCP Tools — task management, data queries, and advanced SQL execution."""

from enum import Enum
from typing import Annotated

from fastmcp import FastMCP, Context

import models
import config


class SiteEnum(str, Enum):
    basspro = "basspro"
    meatyourmaker = "meatyourmaker"


class TaskStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ProductSortEnum(str, Enum):
    price = "price"
    rating = "rating"
    review_count = "review_count"
    scraped_at = "scraped_at"
    name = "name"


class ReviewSortEnum(str, Enum):
    rating = "rating"
    scraped_at = "scraped_at"
    date_published = "date_published"


class SortOrderEnum(str, Enum):
    asc = "asc"
    desc = "desc"


def _get_tm():
    from server.app import task_manager
    return task_manager


def register_tools(mcp: FastMCP):
    """Register all tools on the MCP server."""

    # ── Task Operations ──────────────────────────────

    @mcp.tool
    def start_scrape(urls: list[str]) -> dict:
        """提交一个或多个产品页 URL 开始爬取，返回任务 ID 用于后续查询进度。
        支持 Bass Pro Shops (www.basspro.com) 和 Meat Your Maker (www.meatyourmaker.com) 站点。
        URL 会自动识别所属站点。可同时提交不同站点的 URL。"""
        tm = _get_tm()
        task = tm.submit_scrape(urls)
        return {"task_id": task.id, "status": task.status.value, "total": len(urls)}

    @mcp.tool
    def start_collect(category_url: str, max_pages: int = 0) -> dict:
        """从分类/列表页自动采集所有产品 URL 并逐一爬取详情。
        先翻页收集产品链接，再逐个抓取产品数据和评论。
        max_pages 限制最多翻几页，0 表示采集所有页。
        返回任务 ID，可用 get_task_status 查询采集进度。"""
        tm = _get_tm()
        task = tm.submit_collect(category_url, max_pages)
        return {"task_id": task.id, "status": task.status.value}

    @mcp.tool
    def get_task_status(task_id: str) -> dict:
        """查询爬虫任务的实时状态。
        返回信息包括：状态（pending/running/completed/failed/cancelled）、
        进度（已完成数/总数、当前正在处理的 URL）、
        结果（成功时的统计）、错误信息（失败时）、耗时等。"""
        tm = _get_tm()
        task = tm.get_task(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}
        return task

    @mcp.tool
    def list_tasks(
        status: TaskStatusEnum | None = None,
        limit: int = 20,
    ) -> dict:
        """列出爬虫任务记录，默认按创建时间倒序返回最近 20 条。
        可按状态筛选：pending（等待中）、running（执行中）、
        completed（已完成）、failed（失败）、cancelled（已取消）。"""
        tm = _get_tm()
        tasks, total = tm.list_tasks(
            status=status.value if status else None, limit=limit,
        )
        return {"tasks": tasks, "total": total}

    @mcp.tool
    def cancel_task(task_id: str) -> dict:
        """取消正在运行或等待中的爬虫任务。
        当前正在处理的 URL 会完成（不会中途打断），但后续 URL 不再执行。
        已完成或已失败的任务无法取消。"""
        tm = _get_tm()
        ok = tm.cancel_task(task_id)
        if not ok:
            return {"error": "Task not found or not cancellable (already completed/failed)"}
        return {"task_id": task_id, "status": "cancelled"}

    # ── Data Queries ─────────────────────────────────

    @mcp.tool
    def list_products(
        site: SiteEnum | None = None,
        search: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        stock_status: str | None = None,
        sort_by: ProductSortEnum = ProductSortEnum.scraped_at,
        order: SortOrderEnum = SortOrderEnum.desc,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """搜索和筛选已采集的产品数据。
        - site: 按站点筛选（basspro 或 meatyourmaker）
        - search: 按产品名称关键词模糊搜索
        - min_price/max_price: 价格区间过滤（美元）
        - stock_status: 库存状态（in_stock, out_of_stock, unknown）
        - sort_by: 排序字段（price/rating/review_count/scraped_at/name）
        - order: 排序方向（asc 升序, desc 降序）
        返回产品列表和总数，支持分页。"""
        items, total = models.query_products(
            site=site.value if site else None,
            search=search, min_price=min_price, max_price=max_price,
            stock_status=stock_status,
            sort_by=sort_by.value, order=order.value,
            limit=limit, offset=offset,
        )
        return {"items": items, "total": total}

    @mcp.tool
    def get_product_detail(
        product_id: int | None = None,
        url: str | None = None,
        sku: str | None = None,
    ) -> dict:
        """获取单个产品的完整信息，包含最新价格、库存状态、评分，
        以及最近 5 条评论摘要和最近 10 条价格快照。
        支持三种查找方式（任选其一）：product_id, url, 或 sku。"""
        product = None
        if product_id is not None:
            product = models.get_product_by_id(product_id)
        elif url:
            product = models.get_product_by_url(url)
        elif sku:
            product = models.get_product_by_sku(sku)
        else:
            return {"error": "Provide at least one of: product_id, url, or sku"}

        if not product:
            return {"error": "Product not found"}

        reviews, _ = models.query_reviews(product_id=product["id"], limit=5)
        snapshots, _ = models.get_snapshots(product_id=product["id"], days=30, limit=10)
        return {**product, "recent_reviews": reviews, "recent_snapshots": snapshots}

    @mcp.tool
    def query_reviews(
        product_id: int | None = None,
        site: SiteEnum | None = None,
        min_rating: float | None = None,
        max_rating: float | None = None,
        author: str | None = None,
        keyword: str | None = None,
        has_images: bool | None = None,
        sort_by: ReviewSortEnum = ReviewSortEnum.scraped_at,
        order: SortOrderEnum = SortOrderEnum.desc,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """查询产品评论，支持多维度筛选。
        - product_id: 指定产品的评论
        - site: 按站点筛选（不指定 product_id 时可跨产品搜索）
        - min_rating/max_rating: 评分区间（0-5）
        - author: 作者名模糊匹配
        - keyword: 在标题和正文中搜索关键词
        - has_images: 是否有图片（true 只看有图评论，false 只看无图）
        返回评论列表（含产品名称和站点）和总数。"""
        items, total = models.query_reviews(
            product_id=product_id,
            site=site.value if site else None,
            min_rating=min_rating, max_rating=max_rating,
            author=author, keyword=keyword, has_images=has_images,
            sort_by=sort_by.value, order=order.value,
            limit=limit, offset=offset,
        )
        return {"items": items, "total": total}

    @mcp.tool
    def get_price_history(product_id: int, days: int = 30) -> dict:
        """获取产品的价格和库存变化历史（来自 snapshots 表）。
        默认返回最近 30 天的数据，按时间正序排列，适合绘制趋势图。
        每条记录包含：price, stock_status, review_count, rating, scraped_at。"""
        items, total = models.get_snapshots(product_id=product_id, days=days, limit=1000)
        return {"product_id": product_id, "days": days, "data_points": total, "history": items}

    @mcp.tool
    def get_stats() -> dict:
        """获取数据库整体统计概览。
        包含：各站点产品数量、评论总数、最近采集时间、平均价格、平均评分等。
        适合快速了解当前数据规模和分布。"""
        return models.get_stats()

    # ── Advanced Query ───────────────────────────────

    @mcp.tool
    def execute_sql(sql: str) -> dict:
        """对采集数据库执行只读 SQL 查询，适合语义化工具无法覆盖的复杂分析场景。
        规则：仅允许 SELECT 语句，超时 5 秒，最多返回 500 行。
        数据库包含 4 张表：products, product_snapshots, reviews, tasks。
        使用前建议先读取 db://schema/overview 了解表结构和关系。
        返回 columns（列名列表）、rows（数据行）、row_count 和 truncated（是否截断）。"""
        try:
            return models.execute_readonly_sql(
                sql,
                timeout=config.SQL_QUERY_TIMEOUT,
                max_rows=config.SQL_QUERY_MAX_ROWS,
            )
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Query failed: {e}"}
```

**Step 2: Commit**

```bash
git add server/mcp/tools.py
git commit -m "feat: MCP Tools — task operations, data queries, and execute_sql"
```

---

### Task 8: FastAPI + FastMCP 组装 + Uvicorn 启动

**Files:**
- Create: `server/app.py`

**Step 1: 组装 FastAPI + FastMCP 应用**

`server/app.py`:

```python
"""Application entry point — FastAPI + FastMCP in one ASGI process."""

import logging

import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP

import config
import models
from server.task_manager import TaskManager
from server.api.tasks import router as tasks_router
from server.api.products import router as products_router
from server.mcp.tools import register_tools
from server.mcp.resources import register_resources

logger = logging.getLogger(__name__)

# ── Shared TaskManager singleton ────────────────────
task_manager = TaskManager(max_workers=config.MAX_WORKERS)

# ── MCP Server ──────────────────────────────────────
mcp = FastMCP(
    "Qbu-Crawler",
    instructions=(
        "多站点产品数据爬虫服务。可以启动爬虫任务采集产品信息和评论，"
        "查询已采集的产品、评论、价格历史等数据，"
        "支持 Bass Pro Shops 和 Meat Your Maker 两个站点。"
        "如需执行复杂查询，请先通过 Resources 了解表结构，再使用 execute_sql。"
    ),
)
register_tools(mcp)
register_resources(mcp)

# ── MCP ASGI sub-app ────────────────────────────────
mcp_app = mcp.http_app(path="/")

# ── FastAPI app ─────────────────────────────────────
app = FastAPI(
    title="Qbu-Crawler API",
    description="多站点产品数据爬虫 HTTP API",
    version="1.0.0",
    lifespan=mcp_app.lifespan,
)
app.include_router(tasks_router)
app.include_router(products_router)

# Mount MCP at /mcp
app.mount("/mcp", mcp_app)


@app.get("/health")
async def health():
    return {"status": "ok"}


def start_server(host: str | None = None, port: int | None = None):
    """Start the ASGI server."""
    models.init_db()
    h = host or config.SERVER_HOST
    p = port or config.SERVER_PORT

    if not config.API_KEY:
        logger.warning("API_KEY not set — HTTP API will reject all requests")

    logger.info(f"Starting server on {h}:{p}")
    logger.info(f"  HTTP API: http://{h}:{p}/api")
    logger.info(f"  MCP:      http://{h}:{p}/mcp")
    logger.info(f"  Docs:     http://{h}:{p}/docs")

    uvicorn.run(app, host=h, port=p)
```

**Step 2: Commit**

```bash
git add server/app.py
git commit -m "feat: assemble FastAPI + FastMCP app with shared TaskManager"
```

---

### Task 9: main.py — 添加 serve 子命令

**Files:**
- Modify: `main.py`

**Step 1: 在 main.py 的参数解析中添加 serve 命令**

在 `main.py` 的 `main()` 函数开头（参数解析之前），添加对 `serve` 子命令的检测：

```python
import sys

def main():
    # ── serve 子命令 ──────────────────────────────────
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        from server.app import start_server
        host = None
        port = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--host" and i + 1 < len(args):
                host = args[i + 1]; i += 2
            elif args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1]); i += 2
            else:
                i += 1
        start_server(host=host, port=port)
        return

    # ── 以下为现有 CLI 逻辑，不做任何修改 ──────────────
    # ... (existing code unchanged)
```

**Step 2: 验证 serve 命令**

Run: `uv run python main.py serve --port 8000`
Expected: 服务启动，终端打印 HTTP API / MCP / Docs URL

Run: `uv run python main.py https://www.basspro.com/some-product`
Expected: 现有 CLI 模式正常工作（不受影响）

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add 'serve' subcommand to main.py for HTTP/MCP server"
```

---

### Task 10: 更新 .env.example + CLAUDE.md + 配置文档

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.env`（添加示例配置注释）

**Step 1: 更新 CLAUDE.md**

在"常用命令"部分添加服务器相关命令：

```markdown
# 启动 HTTP API + MCP 服务
uv run python main.py serve
uv run python main.py serve --host 0.0.0.0 --port 9000
```

在"项目结构"中添加 `server/` 目录。

在"通用配置项"表中添加新配置。

**Step 2: Commit**

```bash
git add CLAUDE.md .env
git commit -m "docs: update CLAUDE.md with server commands, structure, and config"
```

---

### Task 11: 端到端验证

**Step 1: 启动服务**

Run: `uv run python main.py serve`

**Step 2: 测试 health endpoint**

Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

**Step 3: 测试认证**

Run: `curl http://localhost:8000/api/stats`
Expected: 401 Unauthorized

Run: `curl -H "Authorization: Bearer <your-api-key>" http://localhost:8000/api/stats`
Expected: 返回统计数据 JSON

**Step 4: 测试 OpenAPI 文档**

打开浏览器访问 `http://localhost:8000/docs`
Expected: Swagger UI 显示所有 endpoints

**Step 5: 测试 MCP（使用 FastMCP CLI 或 MCP Inspector）**

Run: `uv run fastmcp dev server/app.py:mcp`
或配置 Claude Desktop / Claude Code 连接 `http://localhost:8000/mcp`

Expected: 能看到所有 Tools 和 Resources，能调用 get_stats、list_products 等

**Step 6: 测试任务提交（可选，需要浏览器环境）**

通过 API 提交一个爬虫任务，观察状态变化。

**Step 7: Final commit**

如有修复，提交：
```bash
git commit -m "fix: address issues found during e2e verification"
```
