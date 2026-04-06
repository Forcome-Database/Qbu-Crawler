"""Tests for 6-sheet analytical Excel workbook generation."""

import os
from datetime import datetime, timezone

import pytest

from qbu_crawler import config
from qbu_crawler.server import report


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_PRODUCTS = [
    {
        "url": "https://example.com/p/1",
        "name": "Test Grinder",
        "sku": "SKU-001",
        "price": 49.99,
        "stock_status": "in_stock",
        "rating": 4.2,
        "review_count": 20,
        "scraped_at": "2026-04-01 08:00:00",
        "site": "basspro",
        "ownership": "own",
    },
    {
        "url": "https://example.com/p/2",
        "name": "Rival Grinder",
        "sku": "SKU-002",
        "price": 59.99,
        "stock_status": "in_stock",
        "rating": 4.5,
        "review_count": 30,
        "scraped_at": "2026-04-01 08:00:00",
        "site": "basspro",
        "ownership": "competitor",
    },
]

SAMPLE_REVIEWS = [
    {
        "product_name": "Test Grinder",
        "product_sku": "SKU-001",
        "author": "Alice",
        "headline": "Blade broke",
        "body": "The blade broke after 2 uses.",
        "headline_cn": "刀片断了",
        "body_cn": "使用两次后刀片就断了。",
        "rating": 1.0,
        "date_published": "2026-03-28",
        "images": [],
        "ownership": "own",
        "sentiment": "negative",
        "features": ["quality_stability"],
        "insight_cn": "刀片质量问题",
    },
    {
        "product_name": "Rival Grinder",
        "product_sku": "SKU-002",
        "author": "Bob",
        "headline": "Works great",
        "body": "Solid build and easy to use.",
        "headline_cn": "很好用",
        "body_cn": "做工扎实，操作简单。",
        "rating": 5.0,
        "date_published": "2026-03-29",
        "images": ["https://img.example.com/1.jpg"],
        "ownership": "competitor",
        "sentiment": "positive",
        "features": ["solid_build", "easy_to_use"],
        "insight_cn": "",
    },
]


def _make_test_analytics():
    """Return a minimal valid analytics dict for testing."""
    return {
        "mode": "baseline",
        "mode_display": "首日全量基线版",
        "kpis": {
            "product_count": 2,
            "ingested_review_rows": 2,
            "negative_review_rows": 1,
            "negative_review_rate_display": "50.0%",
            "health_index": 72.5,
            "health_index_delta_display": "—",
            "high_risk_count": 1,
            "competitive_gap_index": 3,
            "competitive_gap_index_delta_display": "—",
            "negative_review_rows_delta_display": "—",
            "own_product_count": 1,
            "competitor_product_count": 1,
            "translated_count": 2,
            "untranslated_count": 0,
        },
        "self": {
            "risk_products": [
                {
                    "product_name": "Test Grinder",
                    "product_sku": "SKU-001",
                    "site": "basspro",
                    "ownership": "own",
                    "price": 49.99,
                    "rating": 4.2,
                    "total_reviews": 20,
                    "negative_review_rows": 5,
                    "risk_score": 9,
                    "top_labels_display": "质量稳定性(3)、材料与做工(2)",
                    "focus_summary": "刀片断了：使用两次后刀片就断了。",
                },
            ],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "label_display": "质量稳定性",
                    "severity": "high",
                    "severity_display": "高",
                    "review_count": 5,
                    "affected_product_count": 1,
                    "first_seen": "2026-03-25",
                    "last_seen": "2026-03-28",
                    "example_reviews": [
                        {
                            "summary_text": "刀片断了：使用两次后刀片就断了。",
                        }
                    ],
                },
            ],
            "issue_cards": [
                {
                    "feature_display": "质量稳定性",
                    "label_display": "质量稳定性",
                    "review_count": 5,
                    "severity": "high",
                    "severity_display": "高",
                    "affected_product_count": 1,
                },
            ],
            "recommendations": [],
        },
        "competitor": {
            "gap_analysis": [
                {
                    "label_code": "quality_stability",
                    "label_display": "质量稳定性",
                    "competitor_positive_count": 8,
                    "own_negative_count": 5,
                },
            ],
            "top_positive_themes": [
                {
                    "label_code": "solid_build",
                    "label_display": "做工扎实",
                    "review_count": 12,
                },
            ],
            "benchmark_examples": [],
            "negative_opportunities": [],
        },
        "report_copy": {
            "hero_headline": "本期最高风险：Test Grinder 质量稳定性问题集中。",
            "executive_summary": "自有产品 Test Grinder 差评率偏高，主要集中在质量稳定性问题。",
            "executive_bullets": [
                "自有产品 Test Grinder 累计 5 条差评（差评率 25%），问题集中在质量稳定性",
            ],
        },
        "appendix": {
            "image_reviews": [],
            "coverage": {
                "own_products": 1,
                "competitor_products": 1,
                "own_reviews": 1,
                "competitor_reviews": 1,
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_image_download(monkeypatch):
    """Prevent actual HTTP calls for image downloads in all tests."""
    monkeypatch.setattr(report, "_download_and_resize", lambda url: None)


def test_generate_analytical_excel_has_six_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel(
        products=SAMPLE_PRODUCTS,
        reviews=SAMPLE_REVIEWS,
        analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == [
        "Executive Summary",
        "Product Scorecard",
        "Issue Analysis",
        "Competitive Benchmark",
        "Review Details",
        "Trend Data",
    ]


def test_generate_excel_without_analytics_uses_legacy(tmp_path, monkeypatch):
    """Backward compat: no analytics -> 2-sheet legacy format."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    path = report.generate_excel(
        products=SAMPLE_PRODUCTS,
        reviews=SAMPLE_REVIEWS,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert "产品" in wb.sheetnames
    assert "评论" in wb.sheetnames


def test_generate_excel_with_analytics_uses_analytical(tmp_path, monkeypatch):
    """When analytics is passed, the wrapper produces the 6-sheet format."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report.generate_excel(
        products=SAMPLE_PRODUCTS,
        reviews=SAMPLE_REVIEWS,
        analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert "Executive Summary" in wb.sheetnames
    assert "Review Details" in wb.sheetnames
    assert len(wb.sheetnames) == 6


def test_executive_summary_has_kpis(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Executive Summary"]
    # Check that KPI header row exists
    found_kpi_header = False
    for row in ws.iter_rows(values_only=True):
        if row and "指标" in str(row[0] or ""):
            found_kpi_header = True
            break
    assert found_kpi_header


def test_executive_summary_has_report_date(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    report_date = datetime(2026, 4, 5, tzinfo=timezone.utc)
    path = report._generate_analytical_excel(
        [], [], analytics=analytics, report_date=report_date,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Executive Summary"]
    assert ws.cell(row=1, column=1).value == "报告日期"
    assert ws.cell(row=1, column=2).value == "2026-04-05"


def test_executive_summary_has_llm_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Executive Summary"]
    # Find the LLM summary section
    found_summary = False
    for row in ws.iter_rows(values_only=True):
        if row and str(row[0] or "").startswith("自有产品"):
            found_summary = True
            break
    assert found_summary


def test_product_scorecard_sorted_by_risk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    # Add a second risk product with lower score
    analytics["self"]["risk_products"].append({
        "product_name": "Another Product",
        "product_sku": "SKU-003",
        "site": "basspro",
        "ownership": "own",
        "price": 39.99,
        "rating": 3.8,
        "total_reviews": 10,
        "negative_review_rows": 2,
        "risk_score": 4,
        "top_labels_display": "包装运输(2)",
        "focus_summary": "",
    })
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS, analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Product Scorecard"]
    # First data row should be the highest risk_score
    assert ws.cell(row=2, column=1).value == "Test Grinder"
    assert ws.cell(row=3, column=1).value == "Another Product"


def test_issue_analysis_sorted_by_review_count(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    analytics["self"]["issue_cards"].append({
        "feature_display": "包装运输",
        "label_display": "包装运输",
        "review_count": 10,
        "severity": "medium",
        "severity_display": "中",
        "affected_product_count": 2,
    })
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Issue Analysis"]
    # Higher review_count should come first
    assert ws.cell(row=2, column=1).value == "包装运输"
    assert ws.cell(row=3, column=1).value == "质量稳定性"


def test_competitive_benchmark_with_gap_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Competitive Benchmark"]
    # Header check — gap_analysis is present
    assert ws.cell(row=1, column=1).value == "对标维度"
    assert ws.cell(row=1, column=4).value == "差距"
    assert ws.cell(row=2, column=1).value == "质量稳定性"


def test_competitive_benchmark_fallback_to_themes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    analytics["competitor"]["gap_analysis"] = []  # No gap data
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Competitive Benchmark"]
    # Should fall back to positive themes
    assert ws.cell(row=1, column=1).value == "竞品优势维度"
    assert ws.cell(row=1, column=2).value == "好评数"
    assert ws.cell(row=2, column=1).value == "做工扎实"


def test_review_details_has_enhanced_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS, analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Review Details"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, 13)]
    assert "情感" in headers
    assert "具体特征" in headers
    assert "洞察" in headers
    assert "图片" in headers

    # Data row check
    assert ws.cell(row=2, column=1).value == "Test Grinder"
    assert ws.cell(row=2, column=5).value == "negative"
    assert "quality_stability" in (ws.cell(row=2, column=9).value or "")


def test_trend_data_shows_note_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Trend Data"]
    assert ws.cell(row=1, column=1).value == "日期"
    assert "数据积累中" in (ws.cell(row=2, column=1).value or "")


def test_trend_data_with_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    analytics["_trend_data"] = [
        {
            "date": "2026-04-01",
            "product_name": "Test Grinder",
            "rating": 4.2,
            "negative_rate": "25%",
            "negative_count": 5,
            "review_count": 20,
        },
    ]
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["Trend Data"]
    assert ws.cell(row=2, column=1).value == "2026-04-01"
    assert ws.cell(row=2, column=2).value == "Test Grinder"


def test_analytical_excel_none_analytics_falls_back_to_legacy(tmp_path, monkeypatch):
    """_generate_analytical_excel with None analytics -> legacy format."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS, analytics=None,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert "产品" in wb.sheetnames
    assert "评论" in wb.sheetnames


def test_analytical_excel_empty_data_still_has_headers(tmp_path, monkeypatch):
    """Empty products/reviews with analytics still produce headers-only sheets."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = {
        "mode_display": "首日全量基线版",
        "kpis": {},
        "self": {},
        "competitor": {},
        "report_copy": {},
    }
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert len(wb.sheetnames) == 6
    # Each sheet should at least have a header row
    for name in wb.sheetnames:
        ws = wb[name]
        assert ws.max_row >= 1


def test_generate_excel_output_path_with_analytics(tmp_path, monkeypatch):
    """Output path copy logic works with the analytical format."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "default"))
    custom_out = str(tmp_path / "custom" / "report.xlsx")
    analytics = _make_test_analytics()

    path = report.generate_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS,
        analytics=analytics,
        output_path=custom_out,
    )
    assert path == custom_out
    assert os.path.isfile(custom_out)
