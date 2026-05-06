"""Tests for MCP tool result shapes."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from qbu_crawler import models
from qbu_crawler.server import report
from qbu_crawler.server.mcp.tools import register_tools


def _call_tool(mcp: FastMCP, name: str, arguments: dict | None = None):
    return asyncio.run(mcp.call_tool(name, arguments or {}))


def test_get_stats_returns_structured_content(monkeypatch):
    monkeypatch.setattr(
        models,
        "get_stats",
        lambda: {
            "product_count": 41,
            "ingested_review_rows": 2570,
            "site_reported_review_total_current": 3120,
            "avg_price_current": 416.32,
            "avg_rating_current": 4.52,
            "total_products": 41,
            "total_reviews": 2570,
            "by_site": {
                "basspro": 13,
                "meatyourmaker": 13,
                "waltons": 15,
            },
            "by_ownership": {
                "own": 13,
                "competitor": 28,
            },
            "avg_price": 416.32,
            "avg_rating": 4.52,
            "last_scrape_at": "2026-03-31 18:31:00",
            "time_axes": {
                "product_state_time": {
                    "field": "products.scraped_at",
                    "latest": "2026-03-31 18:31:00",
                },
                "snapshot_time": {
                    "field": "product_snapshots.scraped_at",
                    "latest": "2026-03-31 17:55:00",
                },
                "review_ingest_time": {
                    "field": "reviews.scraped_at",
                    "latest": "2026-03-31 18:20:00",
                },
                "review_publish_time": {
                    "field": "reviews.date_published_parsed",
                    "latest": "2026-03-30",
                },
            },
        },
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(mcp, "get_stats")

    assert result.structured_content == {
        "product_count": 41,
        "ingested_review_rows": 2570,
        "site_reported_review_total_current": 3120,
        "avg_price_current": 416.32,
        "avg_rating_current": 4.52,
        "total_products": 41,
        "total_reviews": 2570,
        "by_site": {
            "basspro": 13,
            "meatyourmaker": 13,
            "waltons": 15,
        },
        "by_ownership": {
            "own": 13,
            "competitor": 28,
        },
        "avg_price": 416.32,
        "avg_rating": 4.52,
        "last_scrape_at": "2026-03-31 18:31:00",
        "time_axes": {
            "product_state_time": {
                "field": "products.scraped_at",
                "latest": "2026-03-31 18:31:00",
            },
            "snapshot_time": {
                "field": "product_snapshots.scraped_at",
                "latest": "2026-03-31 17:55:00",
            },
            "review_ingest_time": {
                "field": "reviews.scraped_at",
                "latest": "2026-03-31 18:20:00",
            },
            "review_publish_time": {
                "field": "reviews.date_published_parsed",
                "latest": "2026-03-30",
            },
        },
    }


def test_get_stats_keeps_catalog_and_review_metrics_distinct(monkeypatch):
    monkeypatch.setattr(
        models,
        "get_stats",
        lambda: {
            "product_count": 9,
            "ingested_review_rows": 636,
            "site_reported_review_total_current": 1284,
            "avg_price_current": 342.77,
            "avg_rating_current": 4.4,
            "total_products": 9,
            "total_reviews": 636,
            "by_site": {
                "basspro": 3,
                "meatyourmaker": 3,
                "waltons": 3,
            },
            "by_ownership": {
                "own": 3,
                "competitor": 6,
            },
            "avg_price": 342.77,
            "avg_rating": 4.4,
            "last_scrape_at": "2026-04-02 09:30:00",
            "time_axes": {
                "product_state_time": {
                    "field": "products.scraped_at",
                    "latest": "2026-04-02 09:30:00",
                },
                "review_ingest_time": {
                    "field": "reviews.scraped_at",
                    "latest": "2026-04-02 09:10:00",
                },
            },
        },
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(mcp, "get_stats")

    assert result.structured_content["product_count"] == 9
    assert result.structured_content["ingested_review_rows"] == 636
    assert result.structured_content["site_reported_review_total_current"] == 1284
    assert result.structured_content["ingested_review_rows"] != result.structured_content["site_reported_review_total_current"]


def test_list_products_returns_structured_content(monkeypatch):
    monkeypatch.setattr(
        models,
        "query_products",
        lambda **_kwargs: (
            [
                {
                    "id": 1,
                    "name": "16\" Meat Saw",
                    "site": "meatyourmaker",
                    "ownership": "competitor",
                    "price": 44.99,
                    "rating": 4.5,
                    "review_count": 71,
                }
            ],
            1,
        ),
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(mcp, "list_products", {"limit": 5})

    assert result.structured_content == {
        "items": [
            {
                "id": 1,
                "name": "16\" Meat Saw",
                "site": "meatyourmaker",
                "ownership": "competitor",
                "price": 44.99,
                "rating": 4.5,
                "review_count": 71,
            }
        ],
        "total": 1,
    }


def test_preview_scope_returns_counts_and_next_action_hint(monkeypatch):
    monkeypatch.setattr(
        models,
        "preview_scope_counts",
        lambda _scope: {
            "product_count": 20,
            "ingested_review_rows": 240,
            "site_reported_review_total_current": 800,
            "matched_review_product_count": 12,
            "image_review_rows": 18,
            "matched_product_count": 12,
            "matched_review_count": 240,
            "matched_image_review_count": 18,
        },
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "preview_scope",
        {
            "products": {"ownership": ["competitor"]},
            "window": {"since": "2026-03-01", "until": "2026-03-31"},
            "artifact_type": "report",
        },
    )

    assert result.structured_content["artifact_type"] == "report"
    assert result.structured_content["scope"]["products"]["ownership"] == ["competitor"]
    assert result.structured_content["scope"]["window"] == {
        "since": "2026-03-01",
        "until": "2026-03-31",
    }
    assert result.structured_content["counts"] == {
        "products": 12,
        "reviews": 240,
        "image_reviews": 18,
        "product_count": 20,
        "ingested_review_rows": 240,
        "site_reported_review_total_current": 800,
        "matched_review_product_count": 12,
        "image_review_rows": 18,
    }
    assert result.structured_content["next_action_hint"] == "requires_confirmation"


def test_preview_scope_preserves_catalog_product_count_when_reviews_narrow_scope(monkeypatch):
    monkeypatch.setattr(
        models,
        "preview_scope_counts",
        lambda _scope: {
            "product_count": 41,
            "ingested_review_rows": 27,
            "site_reported_review_total_current": 2570,
            "matched_review_product_count": 2,
            "image_review_rows": 5,
            "matched_product_count": 2,
            "matched_review_count": 27,
            "matched_image_review_count": 5,
        },
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "preview_scope",
        {
            "products": {"ownership": ["competitor"]},
            "reviews": {"sentiment": "negative"},
            "window": {"since": "2026-03-01", "until": "2026-03-31"},
            "artifact_type": "report",
        },
    )

    counts = result.structured_content["counts"]
    assert counts["products"] == 2
    assert counts["product_count"] == 41
    assert counts["matched_review_product_count"] == 2
    assert counts["site_reported_review_total_current"] == 2570


def test_preview_scope_rejects_non_object_inputs():
    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "preview_scope",
        {
            "products": "SKU-OWN",
            "artifact_type": "report",
        },
    )

    assert result.structured_content == {
        "error": "products must be an object when provided",
    }


def test_send_filtered_report_returns_structured_result(monkeypatch):
    monkeypatch.setattr(
        report,
        "send_filtered_report",
        lambda scope, delivery=None: {
            "scope": scope,
            "data": {
                "products_count": 1,
                "reviews_count": 3,
                "translated_count": 3,
                "untranslated_count": 0,
            },
            "artifact": {
                "success": True,
                "format": "excel",
                "excel_path": "./reports/filtered-report.xlsx",
            },
            "email": {
                "success": True,
                "error": None,
                "recipients": 1,
            },
        },
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "send_filtered_report",
        {
            "scope": {
                "products": {"skus": ["SKU-COMP"]},
                "reviews": {"sentiment": "negative"},
                "window": {"since": "2026-03-05", "until": "2026-03-05"},
            },
            "delivery": {
                "format": "email",
                "recipients": ["ops@example.com"],
            },
        },
    )

    assert result.structured_content["data"]["products_count"] == 1
    assert result.structured_content["artifact"]["success"] is True
    assert result.structured_content["email"]["success"] is True


def test_send_filtered_report_returns_unsupported_result(monkeypatch):
    monkeypatch.setattr(
        report,
        "send_filtered_report",
        lambda scope, delivery=None: {
            "error": "unsupported delivery format: pdf",
            "supported_formats": ["excel", "email"],
        },
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "send_filtered_report",
        {
            "scope": {"products": {"skus": ["SKU-COMP"]}},
            "delivery": {"format": "pdf"},
        },
    )

    assert result.structured_content == {
        "error": "unsupported delivery format: pdf",
        "supported_formats": ["excel", "email"],
    }


def test_export_review_images_returns_structured_links(monkeypatch):
    monkeypatch.setattr(
        models,
        "preview_scope_counts",
        lambda _scope: {
            "matched_product_count": 1,
            "matched_review_count": 2,
            "matched_image_review_count": 1,
        },
    )
    monkeypatch.setattr(
        models,
        "list_review_images_for_scope",
        lambda _scope, limit: [
            {
                "id": 9,
                "product_id": 3,
                "product_name": '16" Meat Saw',
                "product_sku": "SKU-COMP",
                "product_site": "meatyourmaker",
                "product_ownership": "competitor",
                "author": "Alice",
                "rating": 1,
                "date_published": "2026-03-05",
                "images": [
                    "https://img.example.com/1.jpg",
                    "https://img.example.com/2.jpg",
                ],
            }
        ][:limit],
    )

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "export_review_images",
        {
            "scope": {
                "products": {"skus": ["SKU-COMP"]},
                "reviews": {"sentiment": "negative", "has_images": True},
                "window": {"since": "2026-03-05", "until": "2026-03-05"},
            },
            "limit": 5,
        },
    )

    assert result.structured_content["data"] == {
        "products_count": 1,
        "reviews_count": 2,
        "image_reviews_count": 1,
        "image_links_count": 2,
    }
    assert result.structured_content["artifact"]["success"] is True
    assert result.structured_content["artifact"]["format"] == "links"
    assert result.structured_content["artifact"]["type"] == "review_images"
    assert result.structured_content["artifact"]["items"][0]["images"] == [
        "https://img.example.com/1.jpg",
        "https://img.example.com/2.jpg",
    ]


def test_export_review_images_returns_unsupported_result_when_empty(monkeypatch):
    monkeypatch.setattr(
        models,
        "preview_scope_counts",
        lambda _scope: {
            "matched_product_count": 1,
            "matched_review_count": 3,
            "matched_image_review_count": 0,
        },
    )
    monkeypatch.setattr(models, "list_review_images_for_scope", lambda _scope, limit: [])

    mcp = FastMCP("test-mcp")
    register_tools(mcp)

    result = _call_tool(
        mcp,
        "export_review_images",
        {
            "scope": {
                "products": {"skus": ["SKU-COMP"]},
                "reviews": {"sentiment": "negative", "has_images": True},
            },
            "limit": 5,
        },
    )

    assert result.structured_content == {
        "error": "no review images matched the requested scope",
        "scope": {
            "products": {
                "ids": [],
                "urls": [],
                "skus": ["SKU-COMP"],
                "names": [],
                "sites": [],
                "ownership": [],
                "price": {"min": None, "max": None},
                "rating": {"min": None, "max": None},
                "review_count": {"min": None, "max": None},
            },
            "reviews": {
                "sentiment": "negative",
                "rating": {"min": None, "max": 2},
                "keyword": "",
                "has_images": True,
            },
            "window": {"since": None, "until": None},
        },
        "counts": {
            "products": 1,
            "reviews": 3,
            "image_reviews": 0,
        },
        "supported_artifact_types": ["review_images"],
    }
