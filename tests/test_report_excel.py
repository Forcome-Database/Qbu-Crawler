"""Tests for Excel workbook generation (legacy 2-sheet and V3 5-sheet)."""

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
    monkeypatch.setattr(report, "_download_image_data", lambda url: None)


def test_generate_analytical_excel_has_five_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel(
        products=SAMPLE_PRODUCTS,
        reviews=SAMPLE_REVIEWS,
        analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert set(wb.sheetnames) == {"评论明细", "产品概览", "今日变化", "问题标签", "趋势数据"}


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
    """When analytics is passed, the wrapper produces the governed analytical format."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report.generate_excel(
        products=SAMPLE_PRODUCTS,
        reviews=SAMPLE_REVIEWS,
        analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert "评论明细" in wb.sheetnames
    assert "产品概览" in wb.sheetnames
    assert "今日变化" in wb.sheetnames
    assert len(wb.sheetnames) == 5


def test_review_detail_sheet_has_expected_columns(tmp_path, monkeypatch):
    """评论明细 sheet should have all required columns including 照片."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS, analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["评论明细"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert "情感" in headers
    assert "特征短语" in headers
    assert "洞察" in headers
    assert "照片" in headers
    # No embedded images — images appear as text URLs only
    assert len(ws._images) == 0


def test_review_detail_sheet_data_row(tmp_path, monkeypatch):
    """评论明细 first data row should contain the first review's sentiment."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS, analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["评论明细"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    sentiment_col = headers.index("情感") + 1
    product_name_col = headers.index("产品名称") + 1
    assert ws.cell(row=2, column=product_name_col).value == "Test Grinder"
    assert ws.cell(row=2, column=sentiment_col).value == "负面"


def test_product_overview_sheet_has_risk_data(tmp_path, monkeypatch):
    """产品概览 sheet should include ingested_reviews and risk_score from analytics."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    # Use a risk_products entry matching SAMPLE_PRODUCTS SKU-001
    analytics["self"]["risk_products"] = [
        {
            "product_name": "Test Grinder",
            "product_sku": "SKU-001",
            "negative_review_rows": 5,
            "negative_rate": 0.25,
            "risk_score": 9,
            "ingested_reviews": 20,
            "top_features_display": "质量稳定性",
        }
    ]
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, SAMPLE_REVIEWS, analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["产品概览"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert headers == [
        "产品名称", "SKU", "站点", "归属", "售价", "库存状态",
        "站点评分", "站点评论数", "采集评论数", "差评数", "差评率", "风险分",
    ]
    # First data row = Test Grinder (SKU-001)
    assert ws.cell(row=2, column=1).value == "Test Grinder"
    risk_score_col = headers.index("风险分") + 1
    assert ws.cell(row=2, column=risk_score_col).value == 9


def test_label_sheet_pivot_rows(tmp_path, monkeypatch):
    """问题标签 sheet should have one row per label per review."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    import json as _json
    analytics = _make_test_analytics()
    reviews_with_labels = [
        {
            "product_name": "Test Grinder",
            "product_sku": "SKU-001",
            "author": "Alice",
            "headline": "Blade broke",
            "body": "Broke after 2 uses.",
            "headline_cn": "刀片断了",
            "body_cn": "两次后断了。",
            "rating": 1.0,
            "date_published": "2026-03-28",
            "images": [],
            "ownership": "own",
            "sentiment": "negative",
            "analysis_labels": _json.dumps([
                {"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9},
                {"code": "material", "polarity": "negative", "severity": "medium", "confidence": 0.7},
            ]),
            "analysis_features": "[]",
            "analysis_insight_cn": "",
        }
    ]
    path = report._generate_analytical_excel(
        SAMPLE_PRODUCTS, reviews_with_labels, analytics=analytics,
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["问题标签"]
    # Header row + 2 label rows
    assert ws.max_row == 3
    assert ws.cell(row=2, column=3).value == "质量稳定性"
    assert ws.cell(row=3, column=3).value == "material"  # no mapping for "material" → passthrough


def test_trend_data_sheet_with_data(tmp_path, monkeypatch):
    """趋势数据 should flatten nested series; SKU column is present."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    analytics["_trend_series"] = [
        {
            "product_name": "Test Grinder",
            "product_sku": "SKU-1",
            "series": [
                {"date": "2026-04-01", "price": 100, "rating": 4.2, "review_count": 20, "stock_status": "in_stock"},
            ],
        },
    ]
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["趋势数据"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert "日期" in headers
    assert "SKU" in headers
    assert ws.cell(row=2, column=1).value == "2026-04-01"
    sku_col = headers.index("SKU") + 1
    assert ws.cell(row=2, column=sku_col).value == "SKU-1"


def test_trend_data_sheet_empty_still_has_header(tmp_path, monkeypatch):
    """趋势数据 sheet should always have a header row even when no series data."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    analytics = _make_test_analytics()
    # No _trend_series key → empty trend sheet
    path = report._generate_analytical_excel([], [], analytics=analytics)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb["趋势数据"]
    assert ws.cell(row=1, column=1).value == "日期"
    # Only the header row (no data rows, no "数据积累中" note in new format)
    assert ws.max_row == 1


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
    """Empty products/reviews with analytics still produce 5 sheets with headers."""
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
    assert len(wb.sheetnames) == 5
    assert set(wb.sheetnames) == {"评论明细", "产品概览", "今日变化", "问题标签", "趋势数据"}
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


def test_download_images_parallel_respects_timeout(monkeypatch):
    """Parallel image downloads should complete within global timeout."""
    import time
    from qbu_crawler.server.report import _download_images_parallel

    call_count = 0

    def slow_download(url, timeout=10):
        nonlocal call_count
        call_count += 1
        time.sleep(0.3)
        return None  # Simulate failed download

    monkeypatch.setattr("qbu_crawler.server.report._download_image_data", slow_download)
    urls = [f"https://img.example.com/{i}.jpg" for i in range(10)]
    start = time.time()
    results = _download_images_parallel(urls, global_timeout=3)
    elapsed = time.time() - start

    assert len(results) == 10
    # With 5 workers and 0.3s per download, 10 items should take ~0.6s (2 rounds)
    # Certainly less than serial 3.0s
    assert elapsed < 2.0, f"Took too long: {elapsed:.1f}s"


def test_download_images_parallel_empty_list():
    """Empty URL list should return empty results."""
    from qbu_crawler.server.report import _download_images_parallel

    results = _download_images_parallel([], global_timeout=5)
    assert results == {}


def test_generate_excel_calls_parallel_prefetch(monkeypatch, tmp_path):
    """Legacy generate_excel should call _download_images_parallel for pre-fetching."""
    from qbu_crawler.server import report

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    prefetch_calls = []
    original_parallel = report._download_images_parallel

    def mock_parallel(urls, **kwargs):
        prefetch_calls.append(urls)
        return {url: None for url in urls}

    monkeypatch.setattr(report, "_download_images_parallel", mock_parallel)
    monkeypatch.setattr(report, "_download_image_data", lambda url: None)

    reviews_with_images = [
        {
            "product_name": "P1",
            "product_sku": "SKU1",
            "author": "A1",
            "headline": "Great",
            "body": "Body",
            "headline_cn": "",
            "body_cn": "",
            "rating": 5,
            "date_published": "2026-01-01",
            "images": ["https://img.example.com/a.jpg", "https://img.example.com/b.jpg"],
        },
    ]
    report._legacy_generate_excel([], reviews_with_images)

    assert len(prefetch_calls) == 1
    assert set(prefetch_calls[0]) == {"https://img.example.com/a.jpg", "https://img.example.com/b.jpg"}


def test_excel_has_new_column_when_window_ids_present(tmp_path, monkeypatch):
    """'本次新增' column is present when window_review_ids is set; review id=2 is marked '新增'."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    import openpyxl

    # Two reviews: id=1 is old (cumulative only), id=2 is new (in window)
    reviews = [
        {
            "id": 1,
            "product_name": "Test Grinder",
            "product_sku": "SKU-001",
            "author": "Alice",
            "headline": "Old review",
            "body": "From before the window.",
            "headline_cn": "旧评论",
            "body_cn": "来自窗口之前。",
            "rating": 3.0,
            "date_published": "2026-03-01",
            "images": [],
            "ownership": "own",
            "sentiment": "neutral",
            "features": [],
            "insight_cn": "",
        },
        {
            "id": 2,
            "product_name": "Test Grinder",
            "product_sku": "SKU-001",
            "author": "Bob",
            "headline": "New review",
            "body": "Just posted this week.",
            "headline_cn": "新评论",
            "body_cn": "本周刚发布。",
            "rating": 2.0,
            "date_published": "2026-04-14",
            "images": [],
            "ownership": "own",
            "sentiment": "negative",
            "features": ["quality_stability"],
            "insight_cn": "新增差评",
        },
    ]

    analytics = _make_test_analytics()
    analytics["mode"] = "incremental"
    analytics["report_semantics"] = "incremental"
    analytics["window_review_ids"] = [2]

    path = report._generate_analytical_excel(
        products=SAMPLE_PRODUCTS,
        reviews=reviews,
        analytics=analytics,
    )

    wb = openpyxl.load_workbook(path)
    ws = wb["评论明细"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]

    # Column header must be present
    assert "本次新增" in headers, f"'本次新增' not found in headers: {headers}"

    new_col = headers.index("本次新增") + 1
    id_col = headers.index("ID") + 1

    # Collect (id, new_flag) for all data rows
    rows_data = {}
    for row in range(2, ws.max_row + 1):
        rid = ws.cell(row=row, column=id_col).value
        flag = ws.cell(row=row, column=new_col).value
        if rid is not None:
            rows_data[rid] = flag
    assert rows_data.get(2) == "新增", f"Review id=2 should be marked '新增', got {rows_data.get(2)!r}"
    assert rows_data.get(1) in ("", None), f"Review id=1 should be empty, got {rows_data.get(1)!r}"


def test_excel_classifies_bootstrap_rows_when_window_ids_absent(tmp_path, monkeypatch):
    """'本次新增' column stays present and uses bootstrap semantics when analytics has no window_review_ids."""
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    reviews = [
        {
            "id": 1, "product_name": "Test Product", "product_sku": "TP-1",
            "author": "Alice", "headline": "Good", "body": "Nice product",
            "rating": 4, "date_published": "2026-04-15", "images": "[]",
            "ownership": "own", "headline_cn": "", "body_cn": "",
            "translate_status": "done", "sentiment": "positive",
            "analysis_labels": "[]", "analysis_features": "[]",
            "analysis_insight_cn": "", "impact_category": "", "failure_mode": "",
        },
    ]
    products = [
        {"name": "Test Product", "sku": "TP-1", "price": 99.99,
         "stock_status": "in_stock", "rating": 4.0, "review_count": 3,
         "site": "basspro", "ownership": "own"},
    ]
    analytics = {
        "self": {"risk_products": [], "top_negative_clusters": []},
        "competitor": {}, "kpis": {}, "_trend_series": [],
        # NO window_review_ids key
    }

    output = str(tmp_path / "reports" / "test-no-new.xlsx")
    path = report.generate_excel(
        products,
        reviews,
        report_date=datetime(2026, 4, 20),
        analytics=analytics,
        output_path=output,
    )

    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb["评论明细"]
    headers = [cell.value for cell in ws[1]]
    assert "本次新增" in headers, f"Column should be present, got headers: {headers}"
    new_col = headers.index("本次新增") + 1
    assert ws.cell(row=2, column=new_col).value == "新近"
