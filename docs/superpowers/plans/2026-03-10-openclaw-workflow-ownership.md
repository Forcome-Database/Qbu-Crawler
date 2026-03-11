# OpenClaw 定时工作流 + 产品归属字段 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Qbu-Crawler 增加产品归属字段（own/competitor）、OpenClaw 定时爬虫工作流（三阶段：Cron 提交 → Heartbeat 监控 → Cron 汇报）、URL/SKU 验证与 CSV 管理、以及任务完成后的 Excel 报告 + 邮件发送。

**Architecture:** 服务端增加 ownership 字段贯穿 models → task_manager → MCP tools → HTTP API → resources 全链路。OpenClaw 侧新增 3 个 Skill（daily-scrape-submit、daily-scrape-report、csv-management）+ HEARTBEAT.md + 更新 SOUL.md/TOOLS.md/SKILL.md。

**Tech Stack:** Python 3.10+, SQLite, FastAPI, FastMCP, OpenClaw (Cron + Heartbeat + himalaya + xlsx + brave)

**Spec:** `docs/superpowers/specs/2026-03-10-openclaw-workflow-ownership-design.md`

---

## Chunk 1: 服务端 ownership 字段

### Task 1: models.py — ownership 列迁移 + save_product 更新

**Files:**
- Modify: `models.py:17-28` (CREATE TABLE products)
- Modify: `models.py:69-79` (migrations)
- Modify: `models.py:118-139` (save_product)

- [ ] **Step 1: 在 products CREATE TABLE 中添加 ownership 列**

在 `models.py:28` 的 `scraped_at` 行后添加 ownership 列：

```python
# models.py CREATE TABLE products 块，在 scraped_at 行后添加：
            ownership TEXT NOT NULL DEFAULT 'competitor'
```

> 注意：CREATE TABLE 中加 DEFAULT 是为了兼容已有数据。应用层不依赖默认值。

- [ ] **Step 2: 在 migrations 列表中添加 ALTER TABLE**

在 `models.py:74`（最后一条 migration）后追加：

```python
        "ALTER TABLE products ADD COLUMN ownership TEXT NOT NULL DEFAULT 'competitor'",
```

- [ ] **Step 3: 更新 save_product INSERT 和 UPSERT**

将 `models.py:120-132` 的 SQL 替换为：

```python
    cursor = conn.execute("""
        INSERT INTO products (url, site, name, sku, price, stock_status, review_count, rating, ownership, scraped_at)
        VALUES (:url, :site, :name, :sku, :price, :stock_status, :review_count, :rating, :ownership, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
            site = excluded.site,
            name = excluded.name,
            sku = excluded.sku,
            price = excluded.price,
            stock_status = excluded.stock_status,
            review_count = excluded.review_count,
            rating = excluded.rating,
            ownership = excluded.ownership,
            scraped_at = CURRENT_TIMESTAMP
    """, data)
```

- [ ] **Step 4: 验证数据库迁移**

```bash
uv run python -c "from models import init_db; init_db(); print('Migration OK')"
```

Expected: `Migration OK`，无报错。

- [ ] **Step 5: Commit**

```bash
git add models.py
git commit -m "feat: add ownership column to products table with migration"
```

---

### Task 2: models.py — query_products / query_reviews / get_stats 增加 ownership 过滤

**Files:**
- Modify: `models.py:265-304` (query_products)
- Modify: `models.py:334-397` (query_reviews)
- Modify: `models.py:423-447` (get_stats)

- [ ] **Step 1: query_products 增加 ownership 参数**

在 `models.py:270` 的 `stock_status` 参数后添加：

```python
    ownership: str | None = None,
```

在 `models.py:288`（`if stock_status:` 块后）添加：

```python
        if ownership:
            conditions.append("ownership = ?"); params.append(ownership)
```

- [ ] **Step 2: query_reviews 增加 ownership 参数**

在 `models.py:346` 的 `offset` 参数前添加：

```python
    ownership: str | None = None,
```

在 `models.py:369`（`has_images` 条件块后）添加：

```python
        if ownership:
            conditions.append("p.ownership = ?"); params.append(ownership)
```

- [ ] **Step 3: get_stats 增加 by_ownership 分组**

在 `models.py:436`（`avg_rating` 查询后、`return` 语句前）添加：

```python
        by_ownership = {}
        for row in conn.execute(
            "SELECT ownership, COUNT(*) as cnt FROM products GROUP BY ownership"
        ).fetchall():
            by_ownership[row["ownership"]] = row["cnt"]
```

在 return dict 中添加 `"by_ownership": by_ownership`：

```python
        return {
            "total_products": total_products,
            "total_reviews": total_reviews,
            "by_site": by_site,
            "by_ownership": by_ownership,
            "last_scrape_at": last_scrape,
            "avg_price": round(avg_price, 2) if avg_price else None,
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
        }
```

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "feat: add ownership filter to query_products, query_reviews, get_stats"
```

---

### Task 3: task_manager.py — ownership 注入

**Files:**
- Modify: `server/task_manager.py:63-70` (submit_scrape)
- Modify: `server/task_manager.py:72-79` (submit_collect)
- Modify: `server/task_manager.py:129-133` (_run_scrape 中 save_product 调用)
- Modify: `server/task_manager.py:207-212` (_run_collect 中 save_product 调用)

- [ ] **Step 1: submit_scrape 接受 ownership 参数**

修改 `server/task_manager.py:63`：

```python
    def submit_scrape(self, urls: list[str], ownership: str = "competitor") -> Task:
        task = Task(type="scrape", params={"urls": urls, "ownership": ownership})
```

- [ ] **Step 2: submit_collect 接受 ownership 参数**

修改 `server/task_manager.py:72`：

```python
    def submit_collect(self, category_url: str, max_pages: int = 0, ownership: str = "competitor") -> Task:
        task = Task(type="collect", params={"category_url": category_url, "max_pages": max_pages, "ownership": ownership})
```

- [ ] **Step 3: _run_scrape 注入 ownership**

在 `server/task_manager.py:130`（`product = data.get("product", {})` 之后）添加：

```python
                    product["ownership"] = task.params["ownership"]
```

- [ ] **Step 4: _run_collect 注入 ownership**

在 `server/task_manager.py:208`（`product = data.get("product", {})` 之后）添加：

```python
                    product["ownership"] = task.params["ownership"]
```

- [ ] **Step 5: Commit**

```bash
git add server/task_manager.py
git commit -m "feat: inject ownership from task params into save_product"
```

---

### Task 4: MCP tools.py — ownership 参数

**Files:**
- Modify: `server/mcp/tools.py:26-37` (start_scrape)
- Modify: `server/mcp/tools.py:39-52` (start_collect)
- Modify: `server/mcp/tools.py:91-120` (list_products)
- Modify: `server/mcp/tools.py:148-190` (query_reviews)
- Modify: `server/mcp/tools.py:200-205` (get_stats)

- [ ] **Step 1: start_scrape 增加 ownership 必填参数**

修改 `server/mcp/tools.py:26`：

```python
    @mcp.tool
    def start_scrape(urls: list[str], ownership: str) -> str:
        """提交一个或多个产品页 URL 开始爬取，返回任务 ID 用于后续查询进度。
        支持 Bass Pro Shops (www.basspro.com) 和 Meat Your Maker (www.meatyourmaker.com) 站点。
        URL 会自动识别所属站点。可同时提交不同站点的 URL。
        ownership 必填：own（自有产品）或 competitor（竞品）。"""
        tm = _get_tm()
        task = tm.submit_scrape(urls, ownership=ownership)
```

- [ ] **Step 2: start_collect 增加 ownership 必填参数**

修改 `server/mcp/tools.py:40`：

```python
    @mcp.tool
    def start_collect(category_url: str, max_pages: int = 0, ownership: str = "") -> str:
        """从分类/列表页自动采集所有产品 URL 并逐一爬取详情。
        先翻页收集产品链接，再逐个抓取产品数据和评论。
        max_pages 限制最多翻几页，0 表示采集所有页。
        ownership 必填：own（自有产品）或 competitor（竞品）。
        返回任务 ID，可用 get_task_status 查询采集进度。"""
        if not ownership:
            return _json.dumps({"error": "ownership is required (own or competitor)"})
        tm = _get_tm()
        task = tm.submit_collect(category_url, max_pages, ownership=ownership)
```

- [ ] **Step 3: list_products 增加 ownership 可选参数**

在 `server/mcp/tools.py:101`（`offset` 参数后）添加 `ownership: str = ""`，并更新 docstring 和调用：

```python
    @mcp.tool
    def list_products(
        site: str = "",
        search: str = "",
        min_price: float = -1,
        max_price: float = -1,
        stock_status: str = "",
        sort_by: str = "scraped_at",
        order: str = "desc",
        limit: int = 20,
        offset: int = 0,
        ownership: str = "",
    ) -> str:
        """搜索和筛选已采集的产品数据。
        - site: 按站点筛选，可选 basspro 或 meatyourmaker，留空不筛选
        - search: 按产品名称关键词模糊搜索
        - min_price/max_price: 价格区间过滤（美元），-1 表示不限制
        - stock_status: 库存状态，可选 in_stock/out_of_stock/unknown，留空不筛选
        - ownership: 产品归属，可选 own（自有）或 competitor（竞品），留空不筛选
        - sort_by: 排序字段，可选 price/rating/review_count/scraped_at/name
        - order: 排序方向，asc 升序或 desc 降序
        返回产品列表和总数，支持分页。"""
        items, total = models.query_products(
            site=site if site else None,
            search=search if search else None,
            min_price=min_price if min_price >= 0 else None,
            max_price=max_price if max_price >= 0 else None,
            stock_status=stock_status if stock_status else None,
            ownership=ownership if ownership else None,
            sort_by=sort_by, order=order,
            limit=limit, offset=offset,
        )
        return _json.dumps({"items": items, "total": total}, default=str)
```

- [ ] **Step 4: query_reviews 增加 ownership 可选参数**

在 `server/mcp/tools.py:161`（`offset` 参数后）添加 `ownership: str = ""`，更新 docstring，并在调用 `models.query_reviews` 时传递：

```python
        items, total = models.query_reviews(
            product_id=product_id if product_id >= 0 else None,
            sku=sku if sku else None,
            site=site if site else None,
            min_rating=min_rating if min_rating >= 0 else None,
            max_rating=max_rating if max_rating >= 0 else None,
            author=author if author else None,
            keyword=keyword if keyword else None,
            has_images=_has_images,
            ownership=ownership if ownership else None,
            sort_by=sort_by, order=order,
            limit=limit, offset=offset,
        )
```

- [ ] **Step 5: get_stats 无需改动**

`get_stats` MCP tool 直接调用 `models.get_stats()`，Task 2 已在 models 层添加 `by_ownership`，自动透传。

- [ ] **Step 6: Commit**

```bash
git add server/mcp/tools.py
git commit -m "feat: add ownership param to MCP tools (start_scrape, list_products, query_reviews)"
```

---

### Task 5: HTTP API — ownership 参数

**Files:**
- Modify: `server/api/tasks.py:9-14` (Request models)
- Modify: `server/api/tasks.py:22-28` (create_scrape_task)
- Modify: `server/api/tasks.py:31-35` (create_collect_task)
- Modify: `server/api/products.py:9-26` (list_products)

- [ ] **Step 1: 更新 Request models**

```python
class ScrapeRequest(BaseModel):
    urls: list[str]
    ownership: str  # "own" or "competitor"

class CollectRequest(BaseModel):
    category_url: str
    max_pages: int = 0
    ownership: str  # "own" or "competitor"
```

- [ ] **Step 2: 传递 ownership 到 TaskManager**

修改 `server/api/tasks.py:27`：

```python
    task = tm.submit_scrape(req.urls, ownership=req.ownership)
```

修改 `server/api/tasks.py:34`：

```python
    task = tm.submit_collect(req.category_url, req.max_pages, ownership=req.ownership)
```

- [ ] **Step 3: list_products API 增加 ownership 参数**

在 `server/api/products.py:16`（`stock_status` 参数后）添加：

```python
    ownership: str | None = None,
```

并传递到 `models.query_products` 调用中：

```python
    items, total = models.query_products(
        site=site, search=search, min_price=min_price, max_price=max_price,
        stock_status=stock_status, ownership=ownership,
        sort_by=sort_by, order=order,
        limit=limit, offset=offset,
    )
```

- [ ] **Step 4: Commit**

```bash
git add server/api/tasks.py server/api/products.py
git commit -m "feat: add ownership param to HTTP API endpoints"
```

---

### Task 6: MCP resources.py — 元数据更新

**Files:**
- Modify: `server/mcp/resources.py:5-26` (SCHEMA_OVERVIEW)
- Modify: `server/mcp/resources.py:28-52` (SCHEMA_PRODUCTS)

- [ ] **Step 1: 更新 SCHEMA_OVERVIEW**

在 `数据特性` 部分添加：

```
- products.ownership 区分自有产品(own)和竞品(competitor)
```

- [ ] **Step 2: 更新 SCHEMA_PRODUCTS**

在表格中 `scraped_at` 行后添加：

```
| ownership | TEXT | NOT NULL | 产品归属：own（自有）, competitor（竞品） |
```

更新示例 SQL，添加：

```sql
SELECT ownership, COUNT(*), AVG(price), AVG(rating) FROM products GROUP BY ownership;
```

- [ ] **Step 3: Commit**

```bash
git add server/mcp/resources.py
git commit -m "feat: update MCP schema resources with ownership field"
```

---

## Chunk 2: OpenClaw 配置文件更新

### Task 7: SOUL.md — 增加角色职责

**Files:**
- Modify: `server/openclaw/workspace/SOUL.md`

- [ ] **Step 1: 在身份部分增加角色**

在 `## 身份` 段落后扩展：

```markdown
## 身份

你是一个专业的产品数据分析助手，帮助用户管理多站点电商产品爬虫、查询产品信息、分析评论趋势和追踪价格变化。

你同时承担以下角色：
- **定时任务管理者**：负责 CSV 管理、爬虫任务提交、进度监控和结果汇报
- **数据验证者**：验证 URL/SKU 合法性、确认产品归属（自有/竞品）

## 边界

- 不暴露技术细节（JSON、SQL、API、工具名称）
- 不修改或删除数据，只做查询和分析
- 不确定时主动询问，不猜测用户意图
- 大量数据先给摘要，用户要求时再展开详情
- **非支持站点**的 URL/SKU 不能写入定时任务 CSV，不能通过 MCP 爬虫任务流处理
- 非支持站点内容可用浏览器/搜索技能临时获取并返回给用户，但不持久化到数据库
- 产品归属（ownership）必须明确为 own 或 competitor，未指定时必须向用户澄清
```

- [ ] **Step 2: Commit**

```bash
git add server/openclaw/workspace/SOUL.md
git commit -m "feat: update SOUL.md with task manager and data validator roles"
```

---

### Task 8: TOOLS.md — ownership + URL 验证 + CSV 规范

**Files:**
- Modify: `server/openclaw/workspace/TOOLS.md`

- [ ] **Step 1: 更新任务管理工具说明**

将 `### 任务管理` 部分的 `start_scrape` 和 `start_collect` 更新为：

```markdown
### 任务管理

- `start_scrape` — 抓取产品页，参数：`urls`（URL列表）、`ownership`（必填，own 或 competitor）
- `start_collect` — 从分类页采集，参数：`category_url`、`max_pages`（0=全部）、`ownership`（必填，own 或 competitor）
- `get_task_status` — 查询任务进度，参数：`task_id`
- `list_tasks` — 列出任务记录，参数：`status`（可选）、`limit`
- `cancel_task` — 取消任务，参数：`task_id`
```

- [ ] **Step 2: 更新数据查询工具说明**

将 `### 数据查询` 部分更新，增加 ownership 参数：

```markdown
### 数据查询

- `list_products` — 搜索/筛选产品，参数：`site`、`search`、`min_price`、`max_price`、`ownership`（可选，own/competitor）、`sort_by`
- `get_product_detail` — 产品详情+评论+快照，参数：`product_id` 或 `url` 或 `sku`
- `query_reviews` — 查询评论，参数：`product_id`、`min_rating`、`keyword`、`has_images`、`ownership`（可选）
- `get_price_history` — 价格趋势，参数：`product_id`、`days`（默认30）
- `get_stats` — 数据统计总览（含按归属分组），无参数
- `execute_sql` — 只读SQL（仅SELECT），参数：`sql`，最多500行，5秒超时
```

- [ ] **Step 3: 在 `## 参数说明` 前添加 URL 验证和 CSV 管理章节**

```markdown
## URL 验证规则

支持站点域名：
- `www.basspro.com` → basspro（Bass Pro Shops）
- `www.meatyourmaker.com` → meatyourmaker（Meat Your Maker）

验证流程：
1. 提取 URL 域名部分
2. 匹配上述列表 → 通过，可写入 CSV 或提交任务
3. 不匹配 → 告知用户"该站点不在支持范围内，无法加入定时任务"
4. 非支持站点可用浏览器/搜索技能临时获取内容，但不走 MCP 任务流

## CSV 管理规范

两个 CSV 文件位于 `~/.openclaw/workspace/data/`：

- `sku-list-source.csv` — 分类页 URL（用于 `start_collect`）
- `sku-product-details.csv` — 产品详情页 URL（用于 `start_scrape`）

格式：两列 `url,ownership`，一行一条，有表头，ownership 值为 `own` 或 `competitor`。

写入规则：
1. URL 必须通过域名验证
2. ownership 必须明确指定，未指定时向用户追问
3. 用户无法回答 ownership 时，不写入 CSV
4. 累积式管理，无需清理（服务端 UPSERT 去重）

## 定时任务汇报格式

### 任务启动通知

```
🚀 每日爬虫任务已启动

- **提交时间**：YYYY-MM-DD HH:MM
- **分类采集**：N 个任务
- **产品抓取**：N 个任务（N 个产品）
- **任务 ID**：xxx, yyy

将自动监控任务进度，完成后汇报。
```

### 任务完成通知

```
✅ 每日爬虫任务已完成

- **完成时间**：YYYY-MM-DD HH:MM
- **产品抓取**：成功 N，失败 N
- **新增评论**：N 条
- **自有产品**：N 个 | **竞品**：N 个
- **邮件发送**：✅ 已发送至 N 位收件人
- **报告文件**：scrape-report-YYYY-MM-DD.xlsx
```
```

- [ ] **Step 4: 更新数据总览格式模板**

在数据总览格式中增加归属分布：

```markdown
### 产品归属

- 🏠 **自有产品**：N 个
- 🎯 **竞品**：N 个
```

- [ ] **Step 5: Commit**

```bash
git add server/openclaw/workspace/TOOLS.md
git commit -m "feat: update TOOLS.md with ownership params, URL validation, CSV management"
```

---

### Task 9: SKILL.md (qbu-product-data) — ownership 维度 SQL 模板

**Files:**
- Modify: `server/openclaw/workspace/skills/qbu-product-data/SKILL.md`

- [ ] **Step 1: 在竞品分析部分后添加 ownership 分析模板**

在 `## 竞品分析` 部分添加：

```markdown
### 自有 vs 竞品对比

```sql
SELECT ownership, COUNT(*) AS products, ROUND(AVG(price), 2) AS avg_price, ROUND(AVG(rating), 2) AS avg_rating, SUM(review_count) AS total_reviews, SUM(CASE WHEN stock_status = 'in_stock' THEN 1 ELSE 0 END) AS in_stock FROM products GROUP BY ownership
```

### 按归属+站点交叉分析

```sql
SELECT ownership, site, COUNT(*) AS products, ROUND(AVG(price), 2) AS avg_price, ROUND(AVG(rating), 2) AS avg_rating FROM products GROUP BY ownership, site ORDER BY ownership, site
```

### 自有产品差评预警

```sql
SELECT r.rating, r.author, r.headline, SUBSTR(r.body, 1, 100) AS preview, p.name, p.site FROM reviews r JOIN products p ON r.product_id = p.id WHERE p.ownership = 'own' AND r.rating <= 2 ORDER BY r.scraped_at DESC LIMIT 15
```
```

- [ ] **Step 2: 在多步骤工作流中添加按时间查询模板**

```markdown
### 按时间范围查新增数据

```sql
-- 新增产品（指定时间后）
SELECT url, name, sku, price, stock_status, rating, review_count, scraped_at, site, ownership FROM products WHERE scraped_at >= datetime('{start_time}') ORDER BY site, ownership

-- 新增评论（指定时间后）
SELECT p.name, r.author, r.headline, r.body, r.rating, r.date_published, r.images, p.ownership FROM reviews r JOIN products p ON r.product_id = p.id WHERE r.scraped_at >= datetime('{start_time}') ORDER BY p.name
```
```

- [ ] **Step 3: Commit**

```bash
git add server/openclaw/workspace/skills/qbu-product-data/SKILL.md
git commit -m "feat: add ownership analysis SQL templates to SKILL.md"
```

---

## Chunk 3: OpenClaw 新建文件（Skills + HEARTBEAT + 数据文件）

### Task 10: HEARTBEAT.md — 心跳检查清单

**Files:**
- Create: `server/openclaw/workspace/HEARTBEAT.md`

- [ ] **Step 1: 创建 HEARTBEAT.md**

```markdown
# 心跳检查清单

1. 读取 `~/.openclaw/workspace/state/active-tasks.json`
2. 如果文件不存在、为空或内容为 `{}` → 回复 HEARTBEAT_OK
3. 如果有活跃任务：
   - 逐个调用 `get_task_status` 检查每个 task_id
   - 如果某个 task_id 返回 "not found" → 视为失败
   - 如果所有任务仍在运行（pending/running）→ 回复 HEARTBEAT_OK
   - 如果所有任务都有终态（completed/failed/cancelled/not found）→ 执行以下命令触发汇报：

```
openclaw cron add --name "scrape-report" --at +0m --session isolated --message "执行爬虫任务汇报，使用 daily-scrape-report 技能" --announce --to "<dingtalk-channel-id>" --delete-after-run
```

触发后回复 HEARTBEAT_OK
```

- [ ] **Step 2: Commit**

```bash
git add server/openclaw/workspace/HEARTBEAT.md
git commit -m "feat: add HEARTBEAT.md for task monitoring"
```

---

### Task 11: Skill — daily-scrape-submit

**Files:**
- Create: `server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md`

- [ ] **Step 1: 创建技能文件**

```markdown
# 每日爬虫任务提交

定时 Cron Job 触发此技能，读取 CSV 文件并提交爬虫任务。

## 执行步骤

### 1. 读取分类页 CSV

读取 `~/.openclaw/workspace/data/sku-list-source.csv`。

格式：`url,ownership`（有表头）。如果文件不存在或为空（只有表头），跳过此步。

对每一行调用 `start_collect(category_url=url, ownership=ownership)`，记录返回的 task_id。

### 2. 读取产品页 CSV

读取 `~/.openclaw/workspace/data/sku-product-details.csv`。

格式：`url,ownership`（有表头）。如果文件不存在或为空，跳过此步。

按 ownership 分组，对每组调用 `start_scrape(urls=[该组所有URL], ownership=ownership)`，记录 task_id。

### 3. 保存任务状态

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

`submitted_at` 使用 UTC 时间，格式 `YYYY-MM-DDTHH:MM:SS`（无时区后缀）。

### 4. 汇报

输出任务启动通知（参考 TOOLS.md 中的"任务启动通知"格式）。

### 异常处理

- 两个 CSV 都为空 → 输出"无待采集 URL，跳过今日任务"
- CSV 中有无效行（缺少 ownership 或 URL 为空）→ 跳过该行，日志记录
```

- [ ] **Step 2: Commit**

```bash
git add server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md
git commit -m "feat: add daily-scrape-submit skill for cron job"
```

---

### Task 12: Skill — daily-scrape-report

**Files:**
- Create: `server/openclaw/workspace/skills/daily-scrape-report/SKILL.md`

- [ ] **Step 1: 创建技能文件**

```markdown
# 每日爬虫任务汇报

由 Heartbeat 检测到任务完成后触发，生成报告、发送邮件并汇报结果。

## 执行步骤

### 1. 汇总任务结果

读取 `~/.openclaw/workspace/state/active-tasks.json`，获取 task_id 列表和 submitted_at。

对每个 task_id 调用 `get_task_status`，记录：
- 成功的产品数（result.products_saved）
- 成功的评论数（result.reviews_saved）
- 失败数（progress.failed）

### 2. 查询新增数据

使用 `execute_sql` 查询本次新增的产品和评论：

产品查询：
```sql
SELECT url, name, sku, price, stock_status, rating, review_count, scraped_at, site, ownership FROM products WHERE scraped_at >= datetime('{submitted_at}') ORDER BY site, ownership
```

评论查询：
```sql
SELECT p.name, r.author, r.headline, r.body, r.rating, r.date_published, r.images, p.ownership FROM reviews r JOIN products p ON r.product_id = p.id WHERE r.scraped_at >= datetime('{submitted_at}') ORDER BY p.name
```

将 `{submitted_at}` 替换为 active-tasks.json 中的值（UTC 格式）。

### 3. 翻译评论

将评论的 headline 和 body 翻译为中文。

翻译规则：
- 每批 30-50 条，使用低端模型
- 指令："将以下英文评论标题和内容翻译为中文，保持原意，简洁自然"
- 翻译结果暂存，不回写数据库
- 翻译失败的条目中文列留空

### 4. 生成 Excel

使用 xlsx 技能创建 `~/.openclaw/workspace/reports/scrape-report-YYYY-MM-DD.xlsx`。

Sheet1 — 产品：
| 列 | 数据 |
|---|---|
| 产品地址 | url |
| 产品名称 | name |
| SKU | sku |
| 售价$ | price |
| 库存状态 | stock_status |
| 综合评分 | rating |
| 评分数量 | review_count |
| 抓取时间 | scraped_at |
| 站点 | site |
| 归属 | ownership |

Sheet2 — 评论：
| 列 | 数据 |
|---|---|
| 产品名称 | p.name |
| 评论人 | author |
| 标题（原文） | headline |
| 内容（原文） | body |
| 标题（中文） | 翻译结果 |
| 内容（中文） | 翻译结果 |
| 打分 | rating |
| 评论时间 | date_published |
| 照片 | images URL |

### 5. 发送邮件

从 `~/.openclaw/workspace/config/email-recipients.txt` 读取收件人列表（一行一个邮箱）。

使用 himalaya 技能发送邮件：
- 主题：`[Qbu-Crawler] 每日爬虫报告 YYYY-MM-DD`
- 正文：简要统计（新增 N 个产品，N 条评论，自有 N 个，竞品 N 个）
- 附件：Excel 文件（使用绝对路径 `~/.openclaw/workspace/reports/scrape-report-YYYY-MM-DD.xlsx`）

记录邮件发送结果（成功/失败+原因）。

### 6. DingTalk 汇报

输出任务完成通知（参考 TOOLS.md 中的"任务完成通知"格式），包含邮件发送状态。

### 7. 清理状态

将 `~/.openclaw/workspace/state/active-tasks.json` 内容清空为 `{}`。

### 异常处理

- 无新增数据 → Excel 保留表头但数据行为空，仍发送邮件
- 邮件发送失败 → DingTalk 汇报中标注 "❌ 邮件发送失败：{原因}"
- 翻译部分失败 → Excel 中对应中文列留空，不阻断流程
- 所有任务都失败 → 仍执行汇报流程，Excel 为空，DingTalk 列出失败详情
```

- [ ] **Step 2: Commit**

```bash
git add server/openclaw/workspace/skills/daily-scrape-report/SKILL.md
git commit -m "feat: add daily-scrape-report skill with translation, excel, email"
```

---

### Task 13: Skill — csv-management

**Files:**
- Create: `server/openclaw/workspace/skills/csv-management/SKILL.md`

- [ ] **Step 1: 创建技能文件**

```markdown
# URL/SKU 验证与 CSV 管理

当用户提供产品 URL、分类页 URL 或 SKU 时，验证后写入定时任务 CSV。

## 支持站点

- `www.basspro.com` → basspro
- `www.meatyourmaker.com` → meatyourmaker

## 处理流程

### 1. 判断输入类型

- 以 `http://` 或 `https://` 开头 → URL
- 其他 → 视为 SKU

### 2. URL 验证（仅域名匹配）

提取 URL 的域名部分，与支持站点列表匹配。

- 匹配 → 继续下一步
- 不匹配 → 告知用户："该站点（{域名}）不在定时任务支持范围内。我可以用搜索技能帮你获取相关信息，但无法加入定时任务。"

### 3. SKU → URL 转换

如果输入是 SKU：

1. 用 brave 搜索 `site:basspro.com {SKU}` 和 `site:meatyourmaker.com {SKU}`
2. 从搜索结果中找到产品详情页 URL
3. 找不到 → 尝试 firecrawl
4. 仍然找不到 → 告知用户"无法找到该 SKU 对应的产品页"，不写入 CSV

### 4. 确认 ownership

检查用户是否已指定产品归属（自有/竞品）。

- 已指定 → 继续
- 未指定 → 追问："这是自有产品还是竞品？请告知以便正确分类。"
- 用户无法回答 → 告知"无法确定归属，暂不加入定时任务"，不写入 CSV

### 5. 判断目标 CSV

- 产品详情页 URL（含具体产品路径） → 写入 `~/.openclaw/workspace/data/sku-product-details.csv`
- 分类页/列表页 URL → 写入 `~/.openclaw/workspace/data/sku-list-source.csv`

判断方式：由 agent 根据 URL 结构判断。分类页通常包含 `/c/`、`/l/`、`/shop/en/` 等路径但无具体产品名。

### 6. 写入 CSV

追加一行到对应 CSV 文件：`{url},{ownership}`

如果文件不存在，先创建并写入表头 `url,ownership`。

写入后告知用户："已将 {url} 加入定时任务（归属：{ownership}）"。

## 非支持站点处理

用户要求获取非支持站点的产品信息时：
- 可以用 brave 搜索或浏览器技能获取信息并返回给用户
- 不调用 start_scrape / start_collect
- 不写入 CSV
- 不写入数据库
```

- [ ] **Step 2: Commit**

```bash
git add server/openclaw/workspace/skills/csv-management/SKILL.md
git commit -m "feat: add csv-management skill for URL/SKU validation"
```

---

### Task 14: 数据和配置文件模板

**Files:**
- Create: `server/openclaw/workspace/data/sku-list-source.csv`
- Create: `server/openclaw/workspace/data/sku-product-details.csv`
- Create: `server/openclaw/workspace/config/email-recipients.txt`
- Create: `server/openclaw/workspace/state/active-tasks.json`

- [ ] **Step 1: 创建 CSV 空模板**

`server/openclaw/workspace/data/sku-list-source.csv`：
```csv
url,ownership
```

`server/openclaw/workspace/data/sku-product-details.csv`：
```csv
url,ownership
```

- [ ] **Step 2: 创建配置和状态文件**

`server/openclaw/workspace/config/email-recipients.txt`：
```
# 每日爬虫报告邮件收件人（一行一个）
# alice@company.com
# bob@company.com
```

`server/openclaw/workspace/state/active-tasks.json`：
```json
{}
```

- [ ] **Step 3: 创建 reports 目录**

```bash
mkdir -p server/openclaw/workspace/reports
```

- [ ] **Step 4: Commit**

```bash
git add server/openclaw/workspace/data/ server/openclaw/workspace/config/ server/openclaw/workspace/state/ server/openclaw/workspace/reports/
git commit -m "feat: add workspace data templates (CSV, config, state)"
```

---

## Chunk 4: 文档同步

### Task 15: 更新 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新项目结构图**

在 `server/` 目录下的 `mcp/` 后更新 openclaw 结构：

```
│   └── openclaw/
│       ├── README.md
│       ├── plugin/                 # MCP 插件
│       └── workspace/
│           ├── SOUL.md
│           ├── TOOLS.md
│           ├── HEARTBEAT.md        # 心跳检查清单
│           ├── state/              # 运行时状态
│           ├── config/             # 邮件收件人等配置
│           ├── reports/            # Excel 报告输出
│           ├── data/               # CSV（分类页+产品页 URL）
│           └── skills/
│               ├── qbu-product-data/
│               ├── daily-scrape-submit/
│               ├── daily-scrape-report/
│               └── csv-management/
```

- [ ] **Step 2: 更新数据存储策略**

在 `### 数据存储策略` 部分增加：

```markdown
- **products.ownership**：产品归属字段，值为 `own`（自有）或 `competitor`（竞品），通过任务参数传入，爬虫不感知
```

- [ ] **Step 3: 新增 OpenClaw 工作流章节**

在 `### HTTP API + MCP 服务架构` 后添加：

```markdown
### OpenClaw 定时工作流

三阶段架构：
1. **Cron Job（每日定时，isolated）**：读取 CSV → 提交 start_scrape/start_collect → 存 task_id 到 state/active-tasks.json → DingTalk 通知
2. **Heartbeat（每 5 分钟，main session，lightContext）**：检查 active-tasks.json → 轮询 get_task_status → 全部完成则触发阶段 3
3. **Cron Job（一次性，isolated）**：查新增数据 → 翻译评论 → xlsx 生成 Excel → himalaya 发邮件 → DingTalk 汇报 → 清除状态

CSV 文件存放在 OpenClaw workspace `~/.openclaw/workspace/data/`，与项目 `data/`（products.db）物理分离。
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with ownership field and OpenClaw workflow"
```

---

### Task 16: 更新 openclaw README.md

**Files:**
- Modify: `server/openclaw/README.md`

- [ ] **Step 1: 新增定时工作流章节**

在安装步骤后添加：

```markdown
## 定时工作流配置

### Cron Job（每日任务提交）

```bash
openclaw cron add --name "daily-scrape-submit" \
  --cron "0 8 * * *" --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行每日爬虫任务提交，使用 daily-scrape-submit 技能" \
  --announce --to "<dingtalk-channel-id>"
```

### Heartbeat（任务监控）

在 `openclaw.json` 中配置：

```json5
{
  agents: {
    defaults: {
      heartbeat: {
        every: "5m",
        lightContext: true,
        target: "none",
        activeHours: {
          start: "07:00",
          end: "23:00",
          timezone: "Asia/Shanghai"
        }
      }
    }
  }
}
```

### 新增 Skills

- `daily-scrape-submit` — 每日定时任务提交（Cron Job 使用）
- `daily-scrape-report` — 任务完成汇报（含翻译 + Excel + 邮件）
- `csv-management` — URL/SKU 验证与 CSV 管理
```

- [ ] **Step 2: 更新 workspace 文件列表**

在安装步骤中补充新文件的复制命令：

```bash
# 新增文件
cp server/openclaw/workspace/HEARTBEAT.md ~/.openclaw/workspace/
mkdir -p ~/.openclaw/workspace/skills/daily-scrape-submit
cp server/openclaw/workspace/skills/daily-scrape-submit/SKILL.md ~/.openclaw/workspace/skills/daily-scrape-submit/
mkdir -p ~/.openclaw/workspace/skills/daily-scrape-report
cp server/openclaw/workspace/skills/daily-scrape-report/SKILL.md ~/.openclaw/workspace/skills/daily-scrape-report/
mkdir -p ~/.openclaw/workspace/skills/csv-management
cp server/openclaw/workspace/skills/csv-management/SKILL.md ~/.openclaw/workspace/skills/csv-management/
mkdir -p ~/.openclaw/workspace/{data,config,state,reports}
cp server/openclaw/workspace/data/*.csv ~/.openclaw/workspace/data/
cp server/openclaw/workspace/config/email-recipients.txt ~/.openclaw/workspace/config/
cp server/openclaw/workspace/state/active-tasks.json ~/.openclaw/workspace/state/
```

- [ ] **Step 3: Commit**

```bash
git add server/openclaw/README.md
git commit -m "docs: update openclaw README with cron/heartbeat config and new skills"
```
