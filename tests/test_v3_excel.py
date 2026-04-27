"""Tests for the governed analytical Excel workbook.

F011 §4.3 — retired: 4 sheets reorganization
─────────────────────────────────────────────
Most of this file's tests asserted on the legacy 5-sheet layout
(评论明细 / 产品概览 / 今日变化 / 问题标签 / 趋势数据). The Excel attachment
was reorganized in F011 §4.3 to 4 sheets:
  核心数据 / 现在该做什么 / 评论原文 / 竞品启示

Replacement coverage lives in ``tests/server/test_excel_sheets.py`` —
that file pins sheet names, columns, and key invariants for the new layout.

This file retains a single legacy-path smoke test (no `analytics` arg →
2-sheet legacy format) since `_legacy_generate_excel` is still in use as
a backward-compat fallback.
"""

import openpyxl


class TestExcelLegacyPath:
    def test_legacy_format_without_analytics(self, tmp_path, monkeypatch):
        """Legacy path: ``generate_excel(products, reviews)`` with no analytics
        falls back to the 2-sheet workbook (产品 / 评论). Used for ad-hoc
        manual exports — kept for backward compatibility."""
        from qbu_crawler import config
        from qbu_crawler.server.report import generate_excel

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"url": "http://t", "name": "P", "sku": "S", "price": 10,
                     "stock_status": "in_stock", "rating": 4.0, "review_count": 5,
                     "scraped_at": "2026-04-10", "site": "test", "ownership": "own"}]

        result = generate_excel(products, [], output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(result)

        assert "产品" in wb.sheetnames
