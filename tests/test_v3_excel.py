"""Tests for the new 4-sheet data-oriented Excel (Report V3 Phase 4)."""

import openpyxl
import pytest
from qbu_crawler.server.report import generate_excel


class TestExcel4Sheet:
    def test_produces_4_sheets_with_analytics(self, tmp_path, monkeypatch):
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                     "price": 99.99, "stock_status": "in_stock", "rating": 4.0,
                     "review_count": 10, "scraped_at": "2026-04-10"}]
        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "user",
                     "headline": "Great", "body": "Nice product", "headline_cn": "好",
                     "body_cn": "好产品", "rating": 5.0, "date_published_parsed": "2026-04-01",
                     "ownership": "own", "sentiment": "positive", "images": None,
                     "translate_status": "done", "analysis_labels": "[]", "analysis_features": "[]",
                     "analysis_insight_cn": "", "impact_category": None, "failure_mode": None}]
        analytics = {
            "kpis": {"ingested_review_rows": 1},
            "self": {"risk_products": [
                {"product_name": "P1", "product_sku": "S1", "negative_review_rows": 0,
                 "negative_rate": 0, "risk_score": 0, "ingested_reviews": 1,
                 "top_features_display": ""}
            ]},
            "_trend_series": [{"product_name": "P1", "product_sku": "S1",
                              "series": [{"date": "2026-04-10", "price": 99.99,
                                          "rating": 4.0, "review_count": 10,
                                          "stock_status": "in_stock"}]}],
        }
        path = str(tmp_path / "test.xlsx")
        result = generate_excel(products, reviews, analytics=analytics, output_path=path)
        wb = openpyxl.load_workbook(result)
        assert set(wb.sheetnames) == {"评论明细", "产品概览", "问题标签", "趋势数据"}

    def test_review_sheet_no_embedded_images(self, tmp_path, monkeypatch):
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "u",
                     "headline": "H", "body": "B", "headline_cn": "H", "body_cn": "B",
                     "rating": 5.0, "date_published_parsed": "2026-04-01",
                     "ownership": "own", "sentiment": "positive",
                     "images": '["https://example.com/img.jpg"]',
                     "translate_status": "done"}]
        # Pass analytics so we get the 4-sheet format
        analytics = {"kpis": {}, "self": {}, "_trend_series": []}
        path = str(tmp_path / "test.xlsx")
        result = generate_excel([], reviews, analytics=analytics, output_path=path)
        wb = openpyxl.load_workbook(result)
        ws = wb["评论明细"]
        assert len(ws._images) == 0  # No embedded images

    def test_legacy_format_without_analytics(self, tmp_path, monkeypatch):
        """Without analytics, should still produce the legacy 2-sheet format."""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"url": "http://t", "name": "P", "sku": "S", "price": 10,
                     "stock_status": "in_stock", "rating": 4.0, "review_count": 5,
                     "scraped_at": "2026-04-10", "site": "test", "ownership": "own"}]
        path = str(tmp_path / "test.xlsx")
        result = generate_excel(products, [], output_path=path)
        wb = openpyxl.load_workbook(result)
        assert "产品" in wb.sheetnames  # Legacy format

    def test_review_sheet_image_urls_as_text(self, tmp_path, monkeypatch):
        """Images should appear as newline-separated text URLs, not embedded images."""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        reviews = [{"id": 2, "product_name": "P2", "product_sku": "S2", "author": "u",
                     "headline": "Title", "body": "Body", "headline_cn": "标题", "body_cn": "正文",
                     "rating": 3.0, "date_published_parsed": "2026-04-01",
                     "ownership": "own", "sentiment": "neutral",
                     "images": '["https://a.com/1.jpg", "https://b.com/2.jpg"]',
                     "translate_status": "done",
                     "analysis_labels": "[]", "analysis_features": "[]",
                     "analysis_insight_cn": "", "impact_category": None, "failure_mode": None}]
        analytics = {"kpis": {}, "self": {}, "_trend_series": []}
        path = str(tmp_path / "img_test.xlsx")
        result = generate_excel([], reviews, analytics=analytics, output_path=path)
        wb = openpyxl.load_workbook(result)
        ws = wb["评论明细"]
        # Find the image URL column (last column = 照片)
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        img_col = headers.index("照片") + 1
        cell_val = ws.cell(row=2, column=img_col).value or ""
        assert "https://a.com/1.jpg" in cell_val
        assert "https://b.com/2.jpg" in cell_val
        assert len(ws._images) == 0

    def test_product_overview_sheet_columns(self, tmp_path, monkeypatch):
        """产品概览 sheet should have the expected 12 columns."""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                     "price": 50.0, "stock_status": "in_stock", "rating": 4.5,
                     "review_count": 20, "scraped_at": "2026-04-10"}]
        analytics = {
            "kpis": {},
            "self": {"risk_products": [
                {"product_name": "P1", "product_sku": "S1", "negative_review_rows": 2,
                 "negative_rate": 0.1, "risk_score": 5, "ingested_reviews": 20,
                 "top_features_display": "质量"}
            ]},
            "_trend_series": [],
        }
        path = str(tmp_path / "prod_test.xlsx")
        result = generate_excel(products, [], analytics=analytics, output_path=path)
        wb = openpyxl.load_workbook(result)
        ws = wb["产品概览"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        expected = ["产品名称", "SKU", "站点", "归属", "售价", "库存状态",
                    "站点评分", "站点评论数", "采集评论数", "差评数", "差评率", "风险分"]
        assert headers == expected

    def test_label_sheet_pivot_rows(self, tmp_path, monkeypatch):
        """问题标签 sheet should have one row per label assignment."""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        import json
        labels = [
            {"code": "quality", "polarity": "negative", "severity": "high", "confidence": 0.9},
            {"code": "price", "polarity": "positive", "severity": "low", "confidence": 0.7},
        ]
        reviews = [{"id": 10, "product_name": "P1", "product_sku": "S1",
                     "author": "u", "headline": "H", "body": "B",
                     "headline_cn": "H", "body_cn": "B", "rating": 2.0,
                     "date_published_parsed": "2026-04-01", "ownership": "own",
                     "sentiment": "negative", "images": None, "translate_status": "done",
                     "analysis_labels": json.dumps(labels),
                     "analysis_features": "[]", "analysis_insight_cn": "",
                     "impact_category": None, "failure_mode": None}]
        analytics = {"kpis": {}, "self": {}, "_trend_series": []}
        path = str(tmp_path / "label_test.xlsx")
        result = generate_excel([], reviews, analytics=analytics, output_path=path)
        wb = openpyxl.load_workbook(result)
        ws = wb["问题标签"]
        # Header row + 2 label rows
        assert ws.max_row == 3
        assert ws.cell(row=2, column=3).value == "quality"
        assert ws.cell(row=3, column=3).value == "price"

    def test_trend_sheet_flattened(self, tmp_path, monkeypatch):
        """趋势数据 sheet should flatten nested series to one row per date×SKU."""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        analytics = {
            "kpis": {},
            "self": {},
            "_trend_series": [
                {"product_name": "P1", "product_sku": "S1", "series": [
                    {"date": "2026-04-08", "price": 10.0, "rating": 4.0, "review_count": 5, "stock_status": "in_stock"},
                    {"date": "2026-04-09", "price": 11.0, "rating": 4.1, "review_count": 6, "stock_status": "in_stock"},
                ]},
            ],
        }
        path = str(tmp_path / "trend_test.xlsx")
        result = generate_excel([], [], analytics=analytics, output_path=path)
        wb = openpyxl.load_workbook(result)
        ws = wb["趋势数据"]
        # Header + 2 data rows
        assert ws.max_row == 3
        assert ws.cell(row=2, column=1).value == "2026-04-08"
        assert ws.cell(row=3, column=1).value == "2026-04-09"
        assert ws.cell(row=2, column=2).value == "S1"
