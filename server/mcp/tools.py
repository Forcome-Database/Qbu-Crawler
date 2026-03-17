"""MCP Tools — task management, data queries, and advanced SQL execution.

All parameter types use simple primitives (str, int, float, bool) for maximum
compatibility with OpenAI-based function calling schema validation.
"""

import json as _json
import logging

from fastmcp import FastMCP

import models
import config

logger = logging.getLogger(__name__)


def _get_tm():
    from server.app import task_manager
    return task_manager


def register_tools(mcp: FastMCP):
    """Register all tools on the MCP server."""

    # ── Task Operations ──────────────────────────────

    @mcp.tool
    def start_scrape(urls: list[str], ownership: str, reply_to: str = "") -> str:
        """提交一个或多个产品页 URL 开始爬取，返回任务 ID 用于后续查询进度。
        支持 Bass Pro Shops (www.basspro.com)、Meat Your Maker (www.meatyourmaker.com) 和 Walton's (waltons.com) 站点。
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
        max_pages 限制最多翻几页，0 表示采集所有页。
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

    @mcp.tool
    def get_task_status(task_id: str) -> str:
        """查询爬虫任务的实时状态。
        返回信息包括：状态（pending/running/completed/failed/cancelled）、
        进度（已完成数/总数、当前正在处理的 URL）、
        结果（成功时的统计）、错误信息（失败时）、耗时等。"""
        tm = _get_tm()
        task = tm.get_task(task_id)
        if not task:
            return _json.dumps({"error": f"Task {task_id} not found"})
        return _json.dumps(task, default=str)

    @mcp.tool
    def list_tasks(status: str = "", limit: int = 20) -> str:
        """列出爬虫任务记录，默认按创建时间倒序返回最近 20 条。
        status 可选值：pending（等待中）、running（执行中）、
        completed（已完成）、failed（失败）、cancelled（已取消）。
        留空则返回全部状态。"""
        tm = _get_tm()
        tasks, total = tm.list_tasks(
            status=status if status else None, limit=limit,
        )
        return _json.dumps({"tasks": tasks, "total": total}, default=str)

    @mcp.tool
    def cancel_task(task_id: str) -> str:
        """取消正在运行或等待中的爬虫任务。
        当前正在处理的 URL 会完成（不会中途打断），但后续 URL 不再执行。
        已完成或已失败的任务无法取消。"""
        tm = _get_tm()
        ok = tm.cancel_task(task_id)
        if not ok:
            return _json.dumps({"error": "Task not found or not cancellable (already completed/failed)"})
        return _json.dumps({"task_id": task_id, "status": "cancelled"})

    # ── Data Queries ─────────────────────────────────

    @mcp.tool
    def list_products(
        site: str = "",
        search: str = "",
        min_price: float = -1,
        max_price: float = -1,
        stock_status: str = "",
        ownership: str = "",
        sort_by: str = "scraped_at",
        order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """搜索和筛选已采集的产品数据。
        - site: 按站点筛选，可选 basspro、meatyourmaker 或 waltons，留空不筛选
        - search: 按产品名称关键词模糊搜索
        - min_price/max_price: 价格区间过滤（美元），-1 表示不限制
        - stock_status: 库存状态，可选 in_stock/out_of_stock/unknown，留空不筛选
        - ownership: 产品归属筛选，可选 own（自有）或 competitor（竞品），留空不筛选
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

    @mcp.tool
    def get_product_detail(
        product_id: int = -1,
        url: str = "",
        sku: str = "",
    ) -> str:
        """获取单个产品的完整信息，包含最新价格、库存状态、评分，
        以及最近 5 条评论摘要和最近 10 条价格快照。
        支持三种查找方式（任选其一）：product_id（产品ID）, url（产品页URL）, 或 sku。"""
        product = None
        if product_id >= 0:
            product = models.get_product_by_id(product_id)
        elif url:
            product = models.get_product_by_url(url)
        elif sku:
            product = models.get_product_by_sku(sku)
        else:
            return _json.dumps({"error": "Provide at least one of: product_id, url, or sku"})

        if not product:
            return _json.dumps({"error": "Product not found"})

        reviews, _ = models.query_reviews(product_id=product["id"], limit=5)
        snapshots, _ = models.get_snapshots(product_id=product["id"], days=30, limit=10)
        return _json.dumps({**product, "recent_reviews": reviews, "recent_snapshots": snapshots}, default=str)

    @mcp.tool
    def query_reviews(
        product_id: int = -1,
        sku: str = "",
        site: str = "",
        ownership: str = "",
        min_rating: float = -1,
        max_rating: float = -1,
        author: str = "",
        keyword: str = "",
        has_images: str = "",
        sort_by: str = "scraped_at",
        order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """查询产品评论，支持多维度筛选。
        - product_id: 指定产品的评论，-1 表示不限
        - sku: 按产品 SKU 精确匹配，留空不限
        - site: 按站点筛选（basspro、meatyourmaker 或 waltons），留空不限
        - ownership: 按产品归属筛选，可选 own（自有）或 competitor（竞品），留空不限
        - min_rating/max_rating: 评分区间（0-5），-1 表示不限
        - author: 作者名模糊匹配
        - keyword: 在标题和正文中搜索关键词
        - has_images: 是否有图片，可选 true/false，留空不限
        返回评论列表（含产品名称和站点）和总数。"""
        _has_images = None
        if has_images == "true":
            _has_images = True
        elif has_images == "false":
            _has_images = False

        items, total = models.query_reviews(
            product_id=product_id if product_id >= 0 else None,
            sku=sku if sku else None,
            site=site if site else None,
            ownership=ownership if ownership else None,
            min_rating=min_rating if min_rating >= 0 else None,
            max_rating=max_rating if max_rating >= 0 else None,
            author=author if author else None,
            keyword=keyword if keyword else None,
            has_images=_has_images,
            sort_by=sort_by, order=order,
            limit=limit, offset=offset,
        )
        return _json.dumps({"items": items, "total": total}, default=str)

    @mcp.tool
    def get_price_history(product_id: int, days: int = 30) -> str:
        """获取产品的价格和库存变化历史（来自 snapshots 表）。
        默认返回最近 30 天的数据，按时间正序排列，适合绘制趋势图。
        每条记录包含：price, stock_status, review_count, rating, scraped_at。"""
        items, total = models.get_snapshots(product_id=product_id, days=days, limit=1000)
        return _json.dumps({"product_id": product_id, "days": days, "data_points": total, "history": items}, default=str)

    @mcp.tool
    def get_stats() -> str:
        """获取数据库整体统计概览。
        包含：各站点产品数量、评论总数、最近采集时间、平均价格、平均评分等。
        适合快速了解当前数据规模和分布。"""
        return _json.dumps(models.get_stats(), default=str)

    # ── Advanced Query ───────────────────────────────

    @mcp.tool
    def execute_sql(sql: str) -> str:
        """对采集数据库执行只读 SQL 查询，适合语义化工具无法覆盖的复杂分析场景。
        规则：仅允许 SELECT 语句，超时 5 秒，最多返回 500 行。
        数据库包含 4 张表：products, product_snapshots, reviews, tasks。
        使用前建议先读取 db://schema/overview 了解表结构和关系。
        返回 columns（列名列表）、rows（数据行）、row_count 和 truncated（是否截断）。"""
        try:
            result = models.execute_readonly_sql(
                sql,
                timeout=config.SQL_QUERY_TIMEOUT,
                max_rows=config.SQL_QUERY_MAX_ROWS,
            )
            return _json.dumps(result, default=str)
        except ValueError as e:
            return _json.dumps({"error": str(e)})
        except Exception as e:
            return _json.dumps({"error": f"Query failed: {e}"})

    # ── Report Generation ─────────────────────────────

    @mcp.tool
    def generate_report(since: str, send_email: str = "true") -> str:
        """生成爬虫数据报告：查询新增数据（含已翻译的中文）→ 生成 Excel → 发送邮件。
        翻译由后台线程自动执行，无需等待。如需确认翻译完成度，先调用 get_translate_status。
        - since: 上海时间戳（YYYY-MM-DDTHH:MM:SS），查询该时间之后的新增数据
        - send_email: 是否发送邮件，"true" 或 "false"
        返回报告摘要：新增产品数、评论数、翻译数、Excel 路径、邮件发送结果。"""
        from datetime import datetime
        from server.report import generate_report as _generate_report
        try:
            since_dt = datetime.fromisoformat(since)
            result = _generate_report(
                since=since_dt,
                send_email=(send_email.lower() == "true"),
            )
            return _json.dumps(result, default=str, ensure_ascii=False)
        except ValueError as e:
            return _json.dumps({"error": f"Invalid 'since' format: {e}. Use YYYY-MM-DDTHH:MM:SS"})
        except Exception as e:
            return _json.dumps({"error": f"Report generation failed: {e}"})

    @mcp.tool
    def trigger_translate(reset_skipped: str = "false") -> str:
        """手动触发翻译，立即唤醒后台翻译线程处理未翻译的评论。
        reset_skipped: "true" 时先将所有 skipped 评论重置为待翻译（用于补翻历史数据），
        "false"（默认）只触发现有待翻译队列。
        返回当前待翻译数量。"""
        from server.app import translator
        if reset_skipped.lower() == "true":
            count = models.reset_skipped_translations()
            logger.info("trigger_translate: reset %d skipped reviews", count)
        translator.trigger()
        stats = models.get_translate_stats()
        return _json.dumps({
            "message": "翻译线程已唤醒",
            "pending": stats["pending"],
            "failed": stats["failed"],
        })

    @mcp.tool
    def get_translate_status(since: str = "") -> str:
        """查询翻译进度：总评论数、已翻译、待翻译、失败数、跳过数。
        since: 可选，上海时间戳（YYYY-MM-DDTHH:MM:SS），只统计该时间之后的评论。
        留空则返回全量统计。"""
        stats = models.get_translate_stats(since=since if since else None)
        return _json.dumps(stats)

    # ── Task Completion Tracking ─────────────────────────

    @mcp.tool
    def check_pending_completions() -> str:
        """检查已完成但尚未通知的任务。返回所有终态（completed/failed/cancelled）且设置了
        reply_to 但未标记 notified_at 的任务。心跳调用此工具可一次性获取所有待通知任务。"""
        tasks = models.get_pending_completions()
        return _json.dumps({"tasks": tasks, "count": len(tasks)}, default=str)

    @mcp.tool
    def mark_notified(task_ids: list[str]) -> str:
        """将任务标记为已通知。在心跳成功投递完成通知后调用。
        标记后这些任务不会再出现在 check_pending_completions 结果中。"""
        count = models.mark_task_notified(task_ids)
        return _json.dumps({"marked": count})
