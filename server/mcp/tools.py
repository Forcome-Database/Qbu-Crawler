"""MCP Tools — task management, data queries, and advanced SQL execution."""

from enum import Enum

from fastmcp import FastMCP

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
