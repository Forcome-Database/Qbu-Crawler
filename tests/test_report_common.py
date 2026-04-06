"""Tests for server/report_common.py — shared constants and helpers."""

from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _SEVERITY_DISPLAY,
    _PRIORITY_DISPLAY,
    _label_display,
    _summary_text,
    normalize_deep_report_analytics,
)


def test_label_display_known_code():
    assert _label_display("quality_stability") == "质量稳定性"


def test_label_display_unknown_code():
    assert _label_display("unknown_xyz") == "unknown_xyz"


def test_summary_text_cn_preferred():
    review = {"headline_cn": "标题", "body_cn": "内容", "headline": "Title", "body": "Content"}
    result = _summary_text(review)
    assert "标题" in result
    assert "内容" in result


def test_normalize_handles_none():
    result = normalize_deep_report_analytics(None)
    assert result["kpis"]["product_count"] == 0
    assert result["mode"] == "baseline"


def test_normalize_computes_rates():
    analytics = {"kpis": {"ingested_review_rows": 100, "negative_review_rows": 10, "translated_count": 90}}
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["negative_review_rate_display"] == "10.0%"
    assert result["kpis"]["translation_completion_rate_display"] == "90.0%"
