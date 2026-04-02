"""MCP tools for task management, reporting, and data queries."""

import json as _json
import logging
from dataclasses import asdict

from fastmcp import FastMCP

from qbu_crawler import config, models
from qbu_crawler.server.scope import normalize_scope, preview_hint

logger = logging.getLogger(__name__)


def _get_tm():
    from qbu_crawler.server.app import task_manager

    return task_manager


def _structured(payload):
    """Convert payloads into plain JSON-compatible Python objects."""

    return _json.loads(_json.dumps(payload, default=str, ensure_ascii=False))


def _as_object_or_error(name: str, value: object | None) -> tuple[dict | None, dict | None]:
    if value is None:
        return None, None
    if isinstance(value, dict):
        return value, None
    return None, {"error": f"{name} must be an object when provided"}


def register_tools(mcp: FastMCP):
    """Register all tools on the MCP server."""

    @mcp.tool
    def start_scrape(
        urls: list[str],
        ownership: str,
        review_limit: int = 0,
        reply_to: str = "",
    ) -> dict:
        """Submit one or more product URLs for scraping.

        Supports Bass Pro Shops, Meat Your Maker, and Walton's product pages.
        `ownership` must be `own` or `competitor`.
        Pass `reply_to` for ad-hoc chat tasks so completion updates can flow
        through the outbox/bridge delivery path.
        `review_limit` only applies to repeat scrapes; the first successful
        scrape of a product URL still runs full.
        """

        if ownership not in ("own", "competitor"):
            return {"error": "ownership must be 'own' or 'competitor'"}
        tm = _get_tm()
        task = tm.submit_scrape(
            urls,
            ownership=ownership,
            review_limit=review_limit,
            reply_to=reply_to,
        )
        return {
            "message": f"Task submitted successfully for {len(urls)} product URLs. Use get_task_status to query progress.",
            "task_id": task.id,
            "status": task.status.value,
            "total": len(urls),
        }

    @mcp.tool
    def start_collect(
        category_url: str,
        ownership: str,
        max_pages: int = 0,
        review_limit: int = 0,
        reply_to: str = "",
    ) -> dict:
        """Collect product URLs from a category page, then scrape each product.

        `max_pages=0` means collect all pages.
        `ownership` must be `own` or `competitor`.
        Pass `reply_to` for ad-hoc chat tasks so completion updates can flow
        through the outbox/bridge delivery path.
        `review_limit` only applies when a discovered product URL already has a
        successful scrape record; newly discovered products still run full.
        """

        if ownership not in ("own", "competitor"):
            return {"error": "ownership must be 'own' or 'competitor'"}
        tm = _get_tm()
        task = tm.submit_collect(
            category_url,
            max_pages,
            review_limit=review_limit,
            ownership=ownership,
            reply_to=reply_to,
        )
        pages_info = f"up to {max_pages} pages" if max_pages > 0 else "all pages"
        return {
            "message": f"Collect task submitted successfully; products will be discovered from the category page ({pages_info}) and then scraped. Use get_task_status to query progress.",
            "task_id": task.id,
            "status": task.status.value,
        }

    @mcp.tool
    def get_task_status(task_id: str) -> dict:
        """Query a crawler task's real-time status and progress."""

        tm = _get_tm()
        task = tm.get_task(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}
        return _structured(task)

    @mcp.tool
    def list_tasks(status: str = "", limit: int = 20) -> dict:
        """List crawler task records, optionally filtered by status."""

        tm = _get_tm()
        tasks, total = tm.list_tasks(status=status if status else None, limit=limit)
        return _structured({"tasks": tasks, "total": total})

    @mcp.tool
    def cancel_task(task_id: str) -> dict:
        """Cancel a running or pending crawler task."""

        tm = _get_tm()
        ok = tm.cancel_task(task_id)
        if not ok:
            return {"error": "Task not found or not cancellable (already completed/failed)"}
        return {"task_id": task_id, "status": "cancelled"}

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
    ) -> dict:
        """Search and filter collected product records."""

        items, total = models.query_products(
            site=site if site else None,
            search=search if search else None,
            min_price=min_price if min_price >= 0 else None,
            max_price=max_price if max_price >= 0 else None,
            stock_status=stock_status if stock_status else None,
            ownership=ownership if ownership else None,
            sort_by=sort_by,
            order=order,
            limit=limit,
            offset=offset,
        )
        return _structured({"items": items, "total": total})

    @mcp.tool
    def get_product_detail(
        product_id: int = -1,
        url: str = "",
        sku: str = "",
    ) -> dict:
        """Fetch full detail for one product, plus recent reviews and snapshots."""

        product = None
        if product_id >= 0:
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
        return _structured({**product, "recent_reviews": reviews, "recent_snapshots": snapshots})

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
    ) -> dict:
        """Query reviews with multi-dimensional filters."""

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
            sort_by=sort_by,
            order=order,
            limit=limit,
            offset=offset,
        )
        return _structured({"items": items, "total": total})

    @mcp.tool
    def get_price_history(product_id: int, days: int = 30) -> dict:
        """Get price, stock, rating, and review-count history from snapshots."""

        items, total = models.get_snapshots(product_id=product_id, days=days, limit=1000)
        return _structured(
            {
                "product_id": product_id,
                "days": days,
                "data_points": total,
                "history": items,
            }
        )

    @mcp.tool
    def preview_scope(
        products: object | None = None,
        reviews: object | None = None,
        window: object | None = None,
        artifact_type: str = "report",
    ) -> dict:
        """Preview a scope without generating files or sending email."""

        products_value, error = _as_object_or_error("products", products)
        if error:
            return error
        reviews_value, error = _as_object_or_error("reviews", reviews)
        if error:
            return error
        window_value, error = _as_object_or_error("window", window)
        if error:
            return error

        scope = normalize_scope(products=products_value, reviews=reviews_value, window=window_value)
        normalized_artifact_type = (artifact_type or "report").strip().lower()
        counts = models.preview_scope_counts(scope)
        return _structured(
            {
                "artifact_type": normalized_artifact_type,
                "scope": asdict(scope),
                "counts": {
                    "products": counts["matched_product_count"],
                    "reviews": counts["matched_review_count"],
                    "image_reviews": counts["matched_image_review_count"],
                    "product_count": counts["product_count"],
                    "ingested_review_rows": counts["ingested_review_rows"],
                    "site_reported_review_total_current": counts["site_reported_review_total_current"],
                    "matched_review_product_count": counts["matched_review_product_count"],
                    "image_review_rows": counts["image_review_rows"],
                },
                "next_action_hint": preview_hint(scope, artifact_type=normalized_artifact_type),
            }
        )

    @mcp.tool
    def get_stats() -> dict:
        """Get a high-level database overview."""

        return _structured(models.get_stats())

    @mcp.tool
    def execute_sql(sql: str) -> dict:
        """Execute a read-only SQL query against the collected database."""

        try:
            result = models.execute_readonly_sql(
                sql,
                timeout=config.SQL_QUERY_TIMEOUT,
                max_rows=config.SQL_QUERY_MAX_ROWS,
            )
            return _structured(result)
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Query failed: {exc}"}

    @mcp.tool
    def generate_report(since: str, send_email: str = "true") -> dict:
        """Generate a legacy report for data added after `since`."""

        from datetime import datetime

        from qbu_crawler.server.report import generate_report as _generate_report

        try:
            since_dt = datetime.fromisoformat(since)
            result = _generate_report(
                since=since_dt,
                send_email=(send_email.lower() == "true"),
            )
            return _structured(result)
        except ValueError as exc:
            return {"error": f"Invalid 'since' format: {exc}. Use YYYY-MM-DDTHH:MM:SS"}
        except Exception as exc:
            return {"error": f"Report generation failed: {exc}"}

    @mcp.tool
    def send_filtered_report(
        scope: object | None = None,
        delivery: object | None = None,
    ) -> dict:
        """Generate a filtered report for a normalized scope.

        Product scope supports ids, urls, skus, names, sites, ownership,
        price/rating/review_count ranges. Delivery supports format,
        recipients, output_path, and an optional email subject override.
        """

        from qbu_crawler.server import report as report_module

        scope_value, error = _as_object_or_error("scope", scope)
        if error:
            return error
        delivery_value, error = _as_object_or_error("delivery", delivery)
        if error:
            return error

        return _structured(
            report_module.send_filtered_report(
                scope=scope_value or {},
                delivery=delivery_value,
            )
        )

    @mcp.tool
    def export_review_images(
        scope: object | None = None,
        limit: int = 20,
    ) -> dict:
        """Export review-image links for a normalized scope."""

        scope_value, error = _as_object_or_error("scope", scope)
        if error:
            return error

        normalized_scope = normalize_scope(**(scope_value or {}))
        normalized_scope.reviews.has_images = True

        counts = models.preview_scope_counts(normalized_scope)
        if counts["matched_image_review_count"] <= 0:
            return _structured(
                {
                    "error": "no review images matched the requested scope",
                    "scope": asdict(normalized_scope),
                    "counts": {
                        "products": counts["matched_product_count"],
                        "reviews": counts["matched_review_count"],
                        "image_reviews": counts["matched_image_review_count"],
                    },
                    "supported_artifact_types": ["review_images"],
                }
            )

        rows = models.list_review_images_for_scope(normalized_scope, limit=max(limit, 0))
        if not rows:
            return _structured(
                {
                    "error": "no review images matched the requested scope",
                    "scope": asdict(normalized_scope),
                    "counts": {
                        "products": counts["matched_product_count"],
                        "reviews": counts["matched_review_count"],
                        "image_reviews": counts["matched_image_review_count"],
                    },
                    "supported_artifact_types": ["review_images"],
                }
            )

        items = []
        image_links_count = 0
        for row in rows:
            images = row.get("images") or []
            image_links_count += len(images)
            items.append(
                {
                    "review_id": row.get("id"),
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "product_sku": row.get("product_sku"),
                    "product_site": row.get("product_site"),
                    "product_ownership": row.get("product_ownership"),
                    "product_url": row.get("product_url"),
                    "author": row.get("author"),
                    "headline": row.get("headline"),
                    "rating": row.get("rating"),
                    "date_published": row.get("date_published"),
                    "images": images,
                }
            )

        return _structured(
            {
                "scope": asdict(normalized_scope),
                "data": {
                    "products_count": counts["matched_product_count"],
                    "reviews_count": counts["matched_review_count"],
                    "image_reviews_count": counts["matched_image_review_count"],
                    "image_links_count": image_links_count,
                },
                "artifact": {
                    "success": True,
                    "format": "links",
                    "type": "review_images",
                    "limit": limit,
                    "truncated": counts["matched_image_review_count"] > len(items),
                    "items": items,
                },
            }
        )

    @mcp.tool
    def trigger_translate(reset_skipped: str = "false") -> dict:
        """Wake the translation worker immediately."""

        from qbu_crawler.server.app import translator

        if reset_skipped.lower() == "true":
            count = models.reset_skipped_translations()
            logger.info("trigger_translate: reset %d skipped reviews", count)
        translator.trigger()
        stats = models.get_translate_stats()
        return {
            "message": "Translation worker triggered",
            "pending": stats["pending"],
            "failed": stats["failed"],
        }

    @mcp.tool
    def get_translate_status(since: str = "") -> dict:
        """Query translation backlog and completion counts."""

        stats = models.get_translate_stats(since=since if since else None)
        return _structured(stats)

    @mcp.tool
    def get_workflow_status(run_id: str = "", trigger_key: str = "") -> dict:
        """Get one workflow run plus its child task records."""

        run = None
        if run_id:
            run = models.get_workflow_run(run_id)
        elif trigger_key:
            run = models.get_workflow_run_by_trigger_key(trigger_key)
        else:
            return {"error": "Provide run_id or trigger_key"}

        if not run:
            return {"error": "Workflow run not found"}

        tasks = models.list_workflow_run_tasks(run["id"])
        return _structured({"run": run, "tasks": tasks})

    @mcp.tool
    def list_workflow_runs(status: str = "", limit: int = 20) -> dict:
        """List workflow runs, optionally filtered by status."""

        statuses = [status] if status else None
        runs = models.list_workflow_runs(statuses=statuses, limit=limit)
        return _structured({"items": runs, "total": len(runs)})

    @mcp.tool
    def list_pending_notifications(status: str = "", limit: int = 20) -> dict:
        """List outbox notification records, optionally filtered by status."""

        statuses = [status] if status else None
        items = models.list_notifications(statuses=statuses, limit=limit)
        return _structured({"items": items, "total": len(items)})
