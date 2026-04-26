import pytest
from qbu_crawler.server.report_analytics import (
    compute_risk_score, build_product_overview_rows,
)


def test_risk_negative_rate_uses_ingested():
    """F011 H6 — risk_score 分母改为 ingested_only（不再 max(site, ingested)）。"""
    product = {
        "sku": "TEST",
        "review_count": 253,
        "ingested_count": 109,
        "negative_review_count": 9,
    }
    risk = compute_risk_score(product)
    # ingested 分母：9/109 ≈ 0.0826
    assert abs(risk["neg_rate"] - 0.0826) < 0.001


def test_risk_low_coverage_warning_emitted():
    """coverage = ingested/site < 0.5 → low_coverage_warning True."""
    product = {
        "sku": "T",
        "review_count": 300,
        "ingested_count": 100,  # coverage = 0.333
        "negative_review_count": 5,
    }
    risk = compute_risk_score(product)
    assert risk["low_coverage_warning"] is True


def test_risk_no_warning_when_coverage_ok():
    product = {
        "sku": "T",
        "review_count": 100,
        "ingested_count": 90,  # 0.9 ≥ 0.5
        "negative_review_count": 5,
    }
    risk = compute_risk_score(product)
    assert risk["low_coverage_warning"] is False


def test_risk_zero_ingested_returns_none_marker():
    """Zero-scrape products must NOT be silently scored — return marker so caller can skip."""
    product = {
        "sku": "T",
        "review_count": 100,
        "ingested_count": 0,
        "negative_review_count": 0,
    }
    risk = compute_risk_score(product)
    assert risk["neg_rate"] is None
    assert risk["low_coverage_warning"] is True


def test_product_overview_excel_uses_unified_denominator():
    """F011 H10 — 产品概览同列同口径，差评率 = 差评 / 采集"""
    products_data = [
        {"name": "A", "review_count": 56, "ingested_count": 56, "negative_review_count": 25},
        {"name": "B", "review_count": 109, "ingested_count": 109, "negative_review_count": 9},
        {"name": "C", "review_count": 71, "ingested_count": 71, "negative_review_count": 0},
    ]
    rows = build_product_overview_rows(products_data)
    assert abs(rows[0]["negative_rate_ingested"] - 0.4464) < 0.001
    assert abs(rows[1]["negative_rate_ingested"] - 0.0826) < 0.001
    assert rows[2]["negative_rate_ingested"] == 0.0


def test_product_overview_dual_column_when_coverage_low():
    """When site != ingested, expose BOTH rates — never collapse to one."""
    products_data = [
        {"name": "A", "review_count": 200, "ingested_count": 50, "negative_review_count": 5},
    ]
    rows = build_product_overview_rows(products_data)
    assert abs(rows[0]["negative_rate_ingested"] - 0.10) < 0.001
    assert abs(rows[0]["negative_rate_site"] - 0.025) < 0.001
    assert abs(rows[0]["coverage"] - 0.25) < 0.001


def test_product_overview_handles_zero_site():
    products_data = [
        {"name": "A", "review_count": 0, "ingested_count": 0, "negative_review_count": 0},
    ]
    rows = build_product_overview_rows(products_data)
    assert rows[0]["coverage"] is None
    assert rows[0]["negative_rate_site"] is None
    assert rows[0]["negative_rate_ingested"] is None
