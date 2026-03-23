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
- waltons (Walton's)

## 数据特性
- products 表使用 UPSERT，始终是最新状态
- product_snapshots 每次采集 INSERT，记录变化趋势
- reviews 增量写入，用 (product_id, author, headline, body_hash) 去重
- reviews.translate_status 管理翻译队列（后台线程自动翻译评论为中文）
- products.ownership 区分自有产品(own)和竞品(competitor)
- tasks 记录任务历史，params/progress/result 为 JSON 字段
"""

SCHEMA_PRODUCTS = """
## products 表 — 产品当前快照

每个产品的最新状态，URL 唯一键，每次采集 UPSERT 更新。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 产品 ID |
| url | TEXT | UNIQUE, NOT NULL | 产品页 URL |
| site | TEXT | NOT NULL | 站点标识：basspro, meatyourmaker, waltons |
| name | TEXT | | 产品名称 |
| sku | TEXT | | SKU 编号 |
| price | REAL | | 当前价格 (USD) |
| stock_status | TEXT | | 库存状态：in_stock, out_of_stock, unknown |
| review_count | INTEGER | | 评论总数 |
| rating | REAL | | 平均评分 (0-5) |
| scraped_at | TIMESTAMP | | 最后采集时间 |
| ownership | TEXT | NOT NULL, DEFAULT 'competitor' | 产品归属：own(自有) 或 competitor(竞品) |

### 常用查询示例
```sql
SELECT * FROM products WHERE site = 'basspro' AND rating >= 4.5 ORDER BY rating DESC;
SELECT * FROM products WHERE name LIKE '%fishing%' ORDER BY price ASC;
SELECT site, stock_status, COUNT(*) FROM products GROUP BY site, stock_status;
SELECT ownership, COUNT(*), AVG(price) FROM products GROUP BY ownership;
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
SELECT scraped_at, price FROM product_snapshots WHERE product_id = 1 ORDER BY scraped_at;
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
| headline_cn | TEXT | | 评论标题中文翻译 |
| body_cn | TEXT | | 评论正文中文翻译 |
| translate_status | TEXT | | 翻译状态：NULL=待翻译, done=完成, failed=重试中, skipped=跳过 |
| translate_retries | INTEGER | DEFAULT 0 | 翻译失败重试次数 |

### 常用查询示例
```sql
SELECT * FROM reviews WHERE product_id = 1 AND rating <= 2 ORDER BY date_published DESC;
SELECT r.*, p.name FROM reviews r JOIN products p ON r.product_id = p.id
WHERE r.images IS NOT NULL AND r.images != '[]';
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
SELECT id, type, status, progress, result, created_at FROM tasks ORDER BY created_at DESC LIMIT 10;
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
