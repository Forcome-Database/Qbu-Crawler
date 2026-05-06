"""Tests for the authoritative MCP tool contract."""

from __future__ import annotations

import json
from pathlib import Path

from qbu_crawler.server.mcp.contract import (
    TIME_AXIS_CATALOG,
    TOOL_CONTRACTS,
    export_tool_contract_artifact,
)
from qbu_crawler.server.mcp.resources import SCHEMAS

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT / "qbu_crawler" / "server" / "openclaw" / "workspace"
ACCEPTANCE_DIR = ROOT / "docs" / "superpowers" / "acceptance"


def test_high_value_tools_exist_in_contract():
    expected_tools = {
        "get_stats",
        "list_products",
        "get_product_detail",
        "query_reviews",
        "preview_scope",
        "send_filtered_report",
        "export_review_images",
        "get_workflow_status",
        "list_pending_notifications",
    }

    assert expected_tools.issubset(TOOL_CONTRACTS.keys())


def test_get_stats_contract_uses_canonical_metrics_and_time_axis():
    contract = TOOL_CONTRACTS["get_stats"]

    assert contract["tier"] == "inspect_exact"
    assert contract["metrics"] == [
        "product_count",
        "ingested_review_rows",
        "avg_price_current",
        "avg_rating_current",
    ]
    assert contract["time_axes"] == ["product_state_time"]


def test_preview_scope_contract_declares_scope_preview_semantics():
    contract = TOOL_CONTRACTS["preview_scope"]

    assert contract["tier"] == "produce_preview"
    assert "matched_review_product_count" in contract["metrics"]
    assert "image_review_rows" in contract["metrics"]
    assert set(contract["time_axes"]) == {"review_ingest_time", "review_publish_time", "product_state_time"}


def test_time_axis_catalog_contains_canonical_axes():
    assert TIME_AXIS_CATALOG["product_state_time"]["field"] == "products.scraped_at"
    assert TIME_AXIS_CATALOG["review_ingest_time"]["field"] == "reviews.scraped_at"
    assert TIME_AXIS_CATALOG["review_publish_time"]["field"] == "reviews.date_published_parsed"


def test_mcp_resources_cover_current_workflow_and_analysis_schema():
    expected = {
        "overview",
        "products",
        "product_snapshots",
        "reviews",
        "tasks",
        "workflow_runs",
        "workflow_run_tasks",
        "notification_outbox",
        "report_artifacts",
        "review_analysis",
        "review_issue_labels",
    }
    assert expected.issubset(SCHEMAS.keys())
    assert "ratings_only_count" in SCHEMAS["products"]
    assert "date_published_parsed" in SCHEMAS["reviews"]
    assert "report_generation_status" in SCHEMAS["workflow_runs"]
    assert "workflow_notification_status" in SCHEMAS["workflow_runs"]


def test_export_tool_contract_artifact_matches_checked_in_json(tmp_path: Path):
    out = tmp_path / "tool_contract.json"
    export_tool_contract_artifact(out)

    generated = json.loads(out.read_text(encoding="utf-8"))
    checked_in = json.loads(
        (ROOT / "qbu_crawler" / "server" / "openclaw" / "plugin" / "generated" / "tool_contract.json").read_text(
            encoding="utf-8"
        )
    )

    assert generated == checked_in


def test_produce_contract_support_boundaries_are_explicit():
    export_contract = TOOL_CONTRACTS["export_review_images"]
    report_contract = TOOL_CONTRACTS["send_filtered_report"]

    assert export_contract["supports"] == ["review-image export only"]
    assert "product hero-image export" in export_contract["does_not_support"]
    assert "zip packaging" in export_contract["does_not_support"]

    assert "filtered report artifact generation" in report_contract["supports"]
    assert "email delivery for supported formats" in report_contract["supports"]
    assert "product hero-image export" in report_contract["does_not_support"]


def test_semantic_harness_includes_prompt_and_composite_cases():
    semantic_harness = (ACCEPTANCE_DIR / "2026-04-02-openclaw-semantic-regression.md").read_text(encoding="utf-8")

    assert "## Case 9: Prompt-organization ownership drift" in semantic_harness
    assert "## Case 10: Composite-ask decomposition failure" in semantic_harness
    assert "repo-local paths inside runtime workspace prompts" in semantic_harness
    assert "routing the whole ask as only `produce`" in semantic_harness


def test_runtime_workspace_docs_stay_repo_local_free_and_role_separated():
    agents = (WORKSPACE_DIR / "AGENTS.md").read_text(encoding="utf-8")
    tools = (WORKSPACE_DIR / "TOOLS.md").read_text(encoding="utf-8")
    skill = (WORKSPACE_DIR / "skills" / "qbu-product-data" / "SKILL.md").read_text(encoding="utf-8")

    for text in (agents, tools, skill):
        assert "docs/superpowers/" not in text
        assert ".worktrees/" not in text
        assert "Qbu-Crawler" not in text

    assert "## Decision Vector" in agents
    assert "## Routing-Aware Output Guidance" in tools
    assert "## 进入条件（Decision Vector）" in skill
    assert "按当前归属回看" in skill
    assert "report_generation_status" in tools
    assert "email_delivery_status" in tools
    assert "workflow_notification_status" in tools
    assert "date_published_parsed" in skill
    assert "ratings_only_count" in skill


def test_runtime_workspace_docs_lock_single_product_email_scope():
    agents = (WORKSPACE_DIR / "AGENTS.md").read_text(encoding="utf-8")
    tools = (WORKSPACE_DIR / "TOOLS.md").read_text(encoding="utf-8")

    assert "Once `get_product_detail` confirms a single product" in agents
    assert "reuse the same explicit `url` or `sku`" in agents
    assert "Do not broaden that scope back to `name`, `site`, or `ownership`" in agents

    assert "Single-product artifact flow" in tools
    assert "must stay locked to the same explicit `url` or `sku`" in tools
    assert "If preview comes back with more than 1 product" in tools


def test_all_live_tools_exist_in_contract():
    """Every tool registered in the MCP server must have a contract entry."""
    expected_tools = {
        # inspect
        "get_stats", "list_products", "get_product_detail", "query_reviews",
        "get_price_history", "get_task_status", "list_tasks",
        "get_workflow_status", "list_workflow_runs", "list_pending_notifications",
        "get_translate_status", "execute_sql",
        # produce
        "start_scrape", "start_collect", "cancel_task",
        "preview_scope", "send_filtered_report", "export_review_images",
        "generate_report", "trigger_translate",
    }
    assert expected_tools == set(TOOL_CONTRACTS.keys())


def test_produce_tools_have_does_not_support():
    """All produce-tier tools must declare what they cannot do."""
    produce_tiers = {"produce_action", "produce_preview"}
    for name, contract in TOOL_CONTRACTS.items():
        if contract["tier"] in produce_tiers:
            assert contract["does_not_support"], (
                f"{name} is produce-tier but has empty does_not_support"
            )
