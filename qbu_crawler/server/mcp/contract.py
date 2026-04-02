"""Authoritative MCP tool contract for OpenClaw integration."""

from __future__ import annotations

import json
from pathlib import Path

METRIC_CATALOG = {
    "product_count": {
        "label": "Product count",
        "meaning": "Number of products in the current scoped catalog view.",
        "source": "products",
    },
    "ingested_review_rows": {
        "label": "Ingested review rows",
        "meaning": "Number of ingested rows in reviews for the current scope.",
        "source": "reviews",
    },
    "site_reported_review_total_current": {
        "label": "Site-reported review total",
        "meaning": "Sum of current products.review_count across the scoped products.",
        "source": "products.review_count",
    },
    "matched_review_product_count": {
        "label": "Matched-review product count",
        "meaning": "Distinct product count among the matched review rows.",
        "source": "reviews x products",
    },
    "image_review_rows": {
        "label": "Image review rows",
        "meaning": "Matched review rows that contain images.",
        "source": "reviews.images",
    },
    "avg_price_current": {
        "label": "Average current price",
        "meaning": "Average current product price for the scoped products.",
        "source": "products.price",
    },
    "avg_rating_current": {
        "label": "Average current rating",
        "meaning": "Average current product rating for the scoped products.",
        "source": "products.rating",
    },
}

TIME_AXIS_CATALOG = {
    "product_state_time": {
        "label": "Product state time",
        "meaning": "Time when the current product state was last refreshed.",
        "field": "products.scraped_at",
    },
    "snapshot_time": {
        "label": "Snapshot time",
        "meaning": "Time when a historical product snapshot was captured.",
        "field": "product_snapshots.scraped_at",
    },
    "review_ingest_time": {
        "label": "Review ingest time",
        "meaning": "Time when a review row was ingested by the crawler.",
        "field": "reviews.scraped_at",
    },
    "review_publish_time": {
        "label": "Review publish time",
        "meaning": "Time published on the source site.",
        "field": "reviews.date_published",
    },
    "task_lifecycle_time": {
        "label": "Task lifecycle time",
        "meaning": "Task, workflow, or notification lifecycle timestamps.",
        "field": "tasks/workflow_runs/notification_outbox timestamps",
    },
}


def _tool(
    *,
    name: str,
    tier: str,
    description: str,
    input_schema: dict,
    output_schema: dict,
    metrics: list[str] | None = None,
    time_axes: list[str] | None = None,
    supports: list[str] | None = None,
    does_not_support: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "tier": tier,
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "metrics": metrics or [],
        "time_axes": time_axes or [],
        "supports": supports or [],
        "does_not_support": does_not_support or [],
    }


TOOL_CONTRACTS = {
    "get_stats": _tool(
        name="get_stats",
        tier="inspect_exact",
        description="Get a high-level current-state database overview.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {
                "product_count": {"type": "integer"},
                "ingested_review_rows": {"type": "integer"},
                "site_reported_review_total_current": {"type": "integer"},
                "avg_price_current": {"type": ["number", "null"]},
                "avg_rating_current": {"type": ["number", "null"]},
                "total_products": {"type": "integer"},
                "total_reviews": {"type": "integer"},
                "by_site": {"type": "object"},
                "by_ownership": {"type": "object"},
                "avg_price": {"type": ["number", "null"]},
                "avg_rating": {"type": ["number", "null"]},
                "last_scrape_at": {"type": ["string", "null"]},
                "time_axes": {"type": "object"},
            },
            "required": ["product_count", "ingested_review_rows", "total_products", "total_reviews"],
            "additionalProperties": True,
        },
        metrics=["product_count", "ingested_review_rows", "avg_price_current", "avg_rating_current"],
        time_axes=["product_state_time"],
        supports=["exact current-state catalog overview"],
        does_not_support=["historical trend analysis", "site-reported review totals unless explicitly named"],
    ),
    "list_products": _tool(
        name="list_products",
        tier="inspect_list",
        description="Search and filter current product records.",
        input_schema={
            "type": "object",
            "properties": {
                "site": {"type": "string"},
                "search": {"type": "string"},
                "min_price": {"type": "number"},
                "max_price": {"type": "number"},
                "stock_status": {"type": "string"},
                "ownership": {"type": "string"},
                "sort_by": {"type": "string"},
                "order": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "total": {"type": "integer"},
            },
            "required": ["items", "total"],
            "additionalProperties": False,
        },
        metrics=["product_count", "site_reported_review_total_current"],
        time_axes=["product_state_time"],
        supports=["sample product browsing", "current-state product filtering"],
    ),
    "get_product_detail": _tool(
        name="get_product_detail",
        tier="inspect_detail",
        description="Get one product plus recent reviews and snapshots.",
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "url": {"type": "string"},
                "sku": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "review_count": {"type": ["integer", "null"]},
                "recent_reviews": {"type": "array"},
                "recent_snapshots": {"type": "array"},
            },
            "additionalProperties": True,
        },
        metrics=["site_reported_review_total_current"],
        time_axes=["product_state_time", "snapshot_time", "review_ingest_time"],
        supports=["single-product inspection"],
    ),
    "query_reviews": _tool(
        name="query_reviews",
        tier="inspect_reviews",
        description="Query reviews with structured filters.",
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "sku": {"type": "string"},
                "site": {"type": "string"},
                "ownership": {"type": "string"},
                "min_rating": {"type": "number"},
                "max_rating": {"type": "number"},
                "author": {"type": "string"},
                "keyword": {"type": "string"},
                "has_images": {"type": "string"},
                "sort_by": {"type": "string"},
                "order": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "total": {"type": "integer"},
            },
            "required": ["items", "total"],
            "additionalProperties": False,
        },
        metrics=["ingested_review_rows", "image_review_rows"],
        time_axes=["review_ingest_time", "review_publish_time"],
        supports=["review sample inspection", "negative-review inspection"],
    ),
    "preview_scope": _tool(
        name="preview_scope",
        tier="produce_preview",
        description="Preview a normalized scope before producing an artifact.",
        input_schema={
            "type": "object",
            "properties": {
                "products": {"type": "object"},
                "reviews": {"type": "object"},
                "window": {"type": "object"},
                "artifact_type": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "artifact_type": {"type": "string"},
                "scope": {"type": "object"},
                "counts": {"type": "object"},
                "next_action_hint": {"type": "string"},
            },
            "required": ["artifact_type", "scope", "counts", "next_action_hint"],
            "additionalProperties": False,
        },
        metrics=["product_count", "matched_review_product_count", "ingested_review_rows", "image_review_rows"],
        time_axes=["review_ingest_time", "review_publish_time", "product_state_time"],
        supports=["scope preview before filtered report or review-image export"],
    ),
    "send_filtered_report": _tool(
        name="send_filtered_report",
        tier="produce_action",
        description="Generate a filtered report for a normalized scope and optionally deliver it by email.",
        input_schema={
            "type": "object",
            "properties": {
                "scope": {"type": "object"},
                "delivery": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "scope": {"type": "object"},
                "data": {"type": "object"},
                "artifact": {"type": "object"},
                "email": {"type": "object"},
                "error": {"type": "string"},
            },
            "additionalProperties": True,
        },
        metrics=["product_count", "ingested_review_rows", "matched_review_product_count"],
        time_axes=["review_ingest_time", "review_publish_time", "product_state_time"],
        supports=["filtered report artifact generation", "email delivery for supported formats"],
        does_not_support=["arbitrary zip or pdf packaging", "product hero-image export"],
    ),
    "export_review_images": _tool(
        name="export_review_images",
        tier="produce_action",
        description="Export review-image links or manifest data for a normalized scope.",
        input_schema={
            "type": "object",
            "properties": {
                "scope": {"type": "object"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "scope": {"type": "object"},
                "data": {"type": "object"},
                "artifact": {"type": "object"},
                "error": {"type": "string"},
            },
            "additionalProperties": True,
        },
        metrics=["product_count", "ingested_review_rows", "image_review_rows"],
        time_axes=["review_ingest_time", "review_publish_time", "product_state_time"],
        supports=["review-image export only"],
        does_not_support=["product hero-image export", "zip packaging"],
    ),
    "get_workflow_status": _tool(
        name="get_workflow_status",
        tier="inspect_status",
        description="Get one workflow run plus child task records.",
        input_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "trigger_key": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "run": {"type": "object"},
                "tasks": {"type": "array"},
            },
            "additionalProperties": True,
        },
        time_axes=["task_lifecycle_time"],
        supports=["workflow status inspection"],
    ),
    "list_pending_notifications": _tool(
        name="list_pending_notifications",
        tier="inspect_status",
        description="List notification outbox rows, optionally filtered by status.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "total": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        time_axes=["task_lifecycle_time"],
        supports=["notification delivery inspection"],
    ),
}


def build_tool_contract_payload() -> dict:
    return {
        "version": 1,
        "metrics": METRIC_CATALOG,
        "time_axes": TIME_AXIS_CATALOG,
        "tools": TOOL_CONTRACTS,
    }


def export_tool_contract_artifact(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_tool_contract_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
