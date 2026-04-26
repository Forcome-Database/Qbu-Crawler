"""Tests for the governed analytical Excel workbook."""

from datetime import datetime

import openpyxl

from qbu_crawler.server.report import generate_excel


def _sheet_text(ws):
    values = []
    for row in ws.iter_rows(values_only=True):
        for value in row:
            if value not in (None, ""):
                values.append(str(value))
    return "\n".join(values)


def _analytics(report_semantics="incremental", **overrides):
    analytics = {
        "mode": "baseline" if report_semantics == "bootstrap" else "incremental",
        "report_semantics": report_semantics,
        "kpis": {
            "ingested_review_rows": 1,
            "own_review_rows": 1,
            "competitor_review_rows": 0,
            "health_index": 88,
            "high_risk_count": 0,
            "own_product_count": 1,
            "competitor_product_count": 0,
            "translated_count": 1,
            "untranslated_count": 0,
        },
        "change_digest": {
            "enabled": True,
            "view_state": "bootstrap" if report_semantics == "bootstrap" else "incremental",
            "suppressed_reason": "",
            "summary": {
                "ingested_review_count": 1,
                "ingested_own_review_count": 1,
                "ingested_competitor_review_count": 0,
                "ingested_own_negative_count": 0,
                "fresh_review_count": 1,
                "historical_backfill_count": 0,
                "fresh_own_negative_count": 0,
                "issue_new_count": 0,
                "issue_escalated_count": 0,
                "issue_improving_count": 0,
                "state_change_count": 0,
            },
            "issue_changes": {
                "new": [],
                "escalated": [],
                "improving": [],
                "de_escalated": [],
            },
            "product_changes": {
                "price_changes": [],
                "stock_changes": [],
                "rating_changes": [],
                "new_products": [],
                "removed_products": [],
            },
            "review_signals": {
                "fresh_negative_reviews": [],
                "fresh_competitor_positive_reviews": [],
            },
            "warnings": {
                "translation_incomplete": {"enabled": False, "message": ""},
                "estimated_dates": {"enabled": False, "message": ""},
                "backfill_dominant": {"enabled": False, "message": ""},
            },
            "empty_state": {"enabled": False, "title": "", "description": ""},
        },
        "self": {"risk_products": []},
        "_trend_series": [],
    }
    analytics.update(overrides)
    return analytics


class TestExcelWorkbook:
    def test_produces_5_sheets_with_analytics(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                     "price": 99.99, "stock_status": "in_stock", "rating": 4.0,
                     "review_count": 10, "scraped_at": "2026-04-10"}]
        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "user",
                    "headline": "Great", "body": "Nice product", "headline_cn": "很好",
                    "body_cn": "很好用", "rating": 5.0, "date_published_parsed": "2026-04-01",
                    "ownership": "own", "sentiment": "positive", "images": None,
                    "translate_status": "done", "analysis_labels": "[]", "analysis_features": "[]",
                    "analysis_insight_cn": "", "impact_category": None, "failure_mode": None}]
        analytics = _analytics(
            _trend_series=[{"product_name": "P1", "product_sku": "S1",
                            "series": [{"date": "2026-04-10", "price": 99.99,
                                        "rating": 4.0, "review_count": 10,
                                        "stock_status": "in_stock"}]}],
        )

        result = generate_excel(products, reviews, analytics=analytics, output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(result)

        assert set(wb.sheetnames) == {"评论明细", "产品概览", "今日变化", "问题标签", "趋势数据"}

    def test_review_sheet_no_embedded_images(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "u",
                    "headline": "H", "body": "B", "headline_cn": "H", "body_cn": "B",
                    "rating": 5.0, "date_published_parsed": "2026-04-01",
                    "ownership": "own", "sentiment": "positive",
                    "images": '["https://example.com/img.jpg"]',
                    "translate_status": "done"}]

        result = generate_excel([], reviews, analytics=_analytics(), output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(result)
        ws = wb["评论明细"]

        assert len(ws._images) == 0

    def test_legacy_format_without_analytics(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"url": "http://t", "name": "P", "sku": "S", "price": 10,
                     "stock_status": "in_stock", "rating": 4.0, "review_count": 5,
                     "scraped_at": "2026-04-10", "site": "test", "ownership": "own"}]

        result = generate_excel(products, [], output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(result)

        assert "产品" in wb.sheetnames

    def test_review_sheet_image_urls_as_text(self, tmp_path, monkeypatch):
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

        result = generate_excel([], reviews, analytics=_analytics(), output_path=str(tmp_path / "img_test.xlsx"))
        wb = openpyxl.load_workbook(result)
        ws = wb["评论明细"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        img_col = headers.index("照片") + 1
        cell_val = ws.cell(row=2, column=img_col).value or ""

        assert "https://a.com/1.jpg" in cell_val
        assert "https://b.com/2.jpg" in cell_val
        assert len(ws._images) == 0

    def test_product_overview_sheet_columns(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                     "price": 50.0, "stock_status": "in_stock", "rating": 4.5,
                     "review_count": 20, "scraped_at": "2026-04-10"}]
        analytics = _analytics(
            self={"risk_products": [
                {"product_name": "P1", "product_sku": "S1", "negative_review_rows": 2,
                 "negative_rate": 0.1, "risk_score": 5, "ingested_reviews": 20,
                 "top_features_display": "质量"}
            ]},
        )

        result = generate_excel(products, [], analytics=analytics, output_path=str(tmp_path / "prod_test.xlsx"))
        wb = openpyxl.load_workbook(result)
        ws = wb["产品概览"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]

        assert headers == [
            "产品名称", "SKU", "站点", "归属", "售价", "库存状态",
            "站点评分", "站点评论数", "采集评论数", "差评数", "差评率", "风险分",
        ]

    def test_label_sheet_pivot_rows(self, tmp_path, monkeypatch):
        from qbu_crawler import config
        import json

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

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

        result = generate_excel([], reviews, analytics=_analytics(), output_path=str(tmp_path / "label_test.xlsx"))
        wb = openpyxl.load_workbook(result)
        ws = wb["问题标签"]

        assert ws.max_row == 3
        assert ws.cell(row=2, column=3).value == "quality"
        assert ws.cell(row=3, column=3).value == "price"

    def test_trend_sheet_flattened(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        analytics = _analytics(
            _trend_series=[
                {"product_name": "P1", "product_sku": "S1", "series": [
                    {"date": "2026-04-08", "price": 10.0, "rating": 4.0, "review_count": 5, "stock_status": "in_stock"},
                    {"date": "2026-04-09", "price": 11.0, "rating": 4.1, "review_count": 6, "stock_status": "in_stock"},
                ]},
            ],
        )

        result = generate_excel([], [], analytics=analytics, output_path=str(tmp_path / "trend_test.xlsx"))
        wb = openpyxl.load_workbook(result)
        ws = wb["趋势数据"]

        text = _sheet_text(ws)
        assert "产品快照明细" in text
        assert "2026-04-08" in text
        assert "2026-04-09" in text
        assert "S1" in text

    def test_trend_sheet_exports_trend_digest_business_blocks(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        def block(label):
            return {
                "status": "ready",
                "status_message": "",
                "kpis": {"status": "ready", "items": [{"label": f"{label} KPI", "value": 1}]},
                "primary_chart": {
                    "status": "ready",
                    "title": f"{label} 主图",
                    "labels": ["2026-04-01"],
                    "series": [{"name": "指标", "data": [1]}],
                },
                "secondary_charts": [],
                "table": {"status": "ready", "columns": ["项目", "值"], "rows": [{"项目": label, "值": 1}]},
            }

        product_block = block("产品状态")
        product_block["secondary_charts"] = [
            {
                "status": "ready",
                "title": "重点 SKU 价格 - P1",
                "labels": ["2026-04-01"],
                "series": [{"name": "价格", "data": [10]}],
            }
        ]
        product_block["table"] = {
            "status": "ready",
            "columns": ["SKU", "当前库存", "库存变化次数"],
            "rows": [{"sku": "S1", "current_stock": "out_of_stock", "stock_change_count": 1}],
        }
        analytics = _analytics(
            trend_digest={
                "views": ["month"],
                "dimensions": ["sentiment", "issues", "products", "competition"],
                "dimension_notes": {
                    "sentiment": "基于评论发布时间 date_published 聚合。",
                    "issues": "基于评论发布时间 date_published 和问题标签聚合。",
                    "products": "基于产品快照 scraped_at 聚合，反映价格和库存。",
                    "competition": "基于评论发布时间 date_published 和可比样本聚合。",
                },
                "data": {
                    "month": {
                        "sentiment": block("评论声量与情绪"),
                        "issues": block("问题结构"),
                        "products": product_block,
                        "competition": block("竞品对标"),
                    }
                },
            },
            _trend_series=[],
        )

        result = generate_excel([], [], analytics=analytics, output_path=str(tmp_path / "trend_digest_blocks.xlsx"))
        wb = openpyxl.load_workbook(result)
        text = _sheet_text(wb["趋势数据"])

        assert "近30天 / 评论声量与情绪" in text
        assert "近30天 / 问题结构" in text
        assert "近30天 / 产品状态" in text
        assert "近30天 / 竞品对标" in text
        assert "重点 SKU 价格 - P1" in text
        assert "库存变化次数" in text
        assert "产品快照明细" in text
        assert "date_published" in text
        assert "scraped_at" in text

    def test_today_change_sheet_bootstrap_shows_monitoring_start(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        analytics = _analytics(
            report_semantics="bootstrap",
            change_digest={
                **_analytics("bootstrap")["change_digest"],
                "summary": {
                    "ingested_review_count": 6,
                    "ingested_own_review_count": 4,
                    "ingested_competitor_review_count": 2,
                    "ingested_own_negative_count": 1,
                    "fresh_review_count": 2,
                    "historical_backfill_count": 4,
                    "fresh_own_negative_count": 1,
                    "issue_new_count": 0,
                    "issue_escalated_count": 0,
                    "issue_improving_count": 0,
                    "state_change_count": 0,
                },
            },
        )

        result = generate_excel([], [], analytics=analytics, output_path=str(tmp_path / "bootstrap.xlsx"))
        wb = openpyxl.load_workbook(result)
        text = _sheet_text(wb["今日变化"])

        assert "监控起点" in text
        assert "今日新增" not in text

    def test_today_change_sheet_bootstrap_second_day_uses_building_wording(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        base_digest = _analytics("bootstrap")["change_digest"]
        analytics = _analytics(
            report_semantics="bootstrap",
            change_digest={
                **base_digest,
                "summary": {
                    **base_digest["summary"],
                    "baseline_day_index": 2,
                    "baseline_display_state": "building",
                    "window_meaning": "基线建立期第2天，本次入库用于补足基线，不按新增口径解释",
                },
            },
        )

        result = generate_excel([], [], analytics=analytics, output_path=str(tmp_path / "bootstrap_day2.xlsx"))
        wb = openpyxl.load_workbook(result)
        text = _sheet_text(wb["今日变化"])

        assert "基线建立期第2天" in text
        assert "首次建档" not in text
        assert "今日新增" not in text

    def test_product_overview_collected_reviews_uses_real_review_aggregate(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                     "price": 50.0, "stock_status": "in_stock", "rating": 4.5,
                     "review_count": 20, "scraped_at": "2026-04-10"}]
        reviews = [
            {"id": 1, "product_name": "P1", "product_sku": "S1", "author": "u1",
             "headline": "H1", "body": "B1", "headline_cn": "H1", "body_cn": "B1",
             "rating": 5.0, "date_published_parsed": "2026-04-01", "ownership": "own",
             "sentiment": "positive", "images": None, "translate_status": "done"},
            {"id": 2, "product_name": "P1", "product_sku": "S1", "author": "u2",
             "headline": "H2", "body": "B2", "headline_cn": "H2", "body_cn": "B2",
             "rating": 2.0, "date_published_parsed": "2026-04-02", "ownership": "own",
             "sentiment": "negative", "images": None, "translate_status": "done"},
        ]
        analytics = _analytics(
            self={"risk_products": [
                {"product_name": "P1", "product_sku": "S1", "negative_review_rows": 1,
                 "negative_rate": 0.5, "risk_score": 5, "ingested_reviews": 99,
                 "top_features_display": "质量"}
            ]},
        )

        result = generate_excel(products, reviews, analytics=analytics, output_path=str(tmp_path / "overview.xlsx"))
        wb = openpyxl.load_workbook(result)
        ws = wb["产品概览"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        count_col = headers.index("采集评论数") + 1

        assert ws.cell(row=2, column=count_col).value == 2

    def test_review_sheet_new_flag_uses_bootstrap_and_incremental_semantics(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                     "price": 50.0, "stock_status": "in_stock", "rating": 4.5,
                     "review_count": 20, "scraped_at": "2026-04-23"}]
        reviews = [
            {"id": 1, "product_name": "P1", "product_sku": "S1", "author": "u1",
             "headline": "Recent headline", "body": "B1", "headline_cn": "", "body_cn": "",
             "rating": 5.0, "date_published_parsed": "2026-04-20", "ownership": "own",
             "sentiment": "positive", "images": None, "translate_status": "done",
             "analysis_labels": "[]", "analysis_features": "[]", "analysis_insight_cn": "",
             "impact_category": None, "failure_mode": None},
            {"id": 2, "product_name": "P1", "product_sku": "S1", "author": "u2",
             "headline": "Motor failed", "body": "B2", "headline_cn": "", "body_cn": "",
             "rating": 1.0, "date_published_parsed": "2026-01-01", "ownership": "own",
             "sentiment": "negative", "images": None, "translate_status": "done",
             "analysis_labels": "[]", "analysis_features": "[]", "analysis_insight_cn": "",
             "impact_category": None, "failure_mode": "电机损坏"},
        ]

        bootstrap_result = generate_excel(
            products,
            reviews,
            report_date=datetime(2026, 4, 23),
            analytics=_analytics(report_semantics="bootstrap"),
            output_path=str(tmp_path / "bootstrap-flags.xlsx"),
        )
        bootstrap_wb = openpyxl.load_workbook(bootstrap_result)
        bootstrap_ws = bootstrap_wb["评论明细"]
        bootstrap_headers = [bootstrap_ws.cell(row=1, column=c).value for c in range(1, bootstrap_ws.max_column + 1)]
        scope_col = bootstrap_headers.index("窗口归属") + 1
        impact_col = bootstrap_headers.index("影响类别") + 1
        headline_cn_col = bootstrap_headers.index("标题(中文)") + 1

        assert "本次新增" not in bootstrap_headers
        assert bootstrap_ws.cell(row=2, column=scope_col).value == "历史累计·新近"
        assert bootstrap_ws.cell(row=3, column=scope_col).value == "历史累计·补采"
        assert bootstrap_ws.cell(row=3, column=impact_col).value == "电机损坏"
        assert bootstrap_ws.cell(row=3, column=headline_cn_col).value == "Motor failed"

        incremental_result = generate_excel(
            products,
            reviews,
            report_date=datetime(2026, 4, 23),
            analytics=_analytics(report_semantics="incremental", window_review_ids=[2]),
            output_path=str(tmp_path / "incremental-flags.xlsx"),
        )
        incremental_wb = openpyxl.load_workbook(incremental_result)
        incremental_ws = incremental_wb["评论明细"]
        incremental_headers = [incremental_ws.cell(row=1, column=c).value for c in range(1, incremental_ws.max_column + 1)]
        incremental_scope_col = incremental_headers.index("窗口归属") + 1

        assert "本次新增" not in incremental_headers
        assert incremental_ws.cell(row=2, column=incremental_scope_col).value == "历史累计"
        assert incremental_ws.cell(row=3, column=incremental_scope_col).value == "本次入库"

    def test_review_sheet_window_scope_distinguishes_bootstrap_window_ids(self, tmp_path, monkeypatch):
        from qbu_crawler import config

        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        reviews = [
            {"id": 1, "product_name": "P1", "product_sku": "S1", "author": "u1",
             "headline": "Recent historical", "body": "B1", "headline_cn": "", "body_cn": "",
             "rating": 5.0, "date_published_parsed": "2026-04-20", "ownership": "own",
             "sentiment": "positive", "images": None, "translate_status": "done",
             "analysis_labels": "[]", "analysis_features": "[]"},
            {"id": 2, "product_name": "P1", "product_sku": "S1", "author": "u2",
             "headline": "Recent window", "body": "B2", "headline_cn": "", "body_cn": "",
             "rating": 4.0, "date_published_parsed": "2026-04-21", "ownership": "own",
             "sentiment": "positive", "images": None, "translate_status": "done",
             "analysis_labels": "[]", "analysis_features": "[]"},
        ]
        analytics = _analytics(report_semantics="bootstrap", window_review_ids=[2])

        result = generate_excel(
            [],
            reviews,
            report_date=datetime(2026, 4, 23),
            analytics=analytics,
            output_path=str(tmp_path / "bootstrap-window-scope.xlsx"),
        )
        wb = openpyxl.load_workbook(result)
        ws = wb["评论明细"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        scope_col = headers.index("窗口归属") + 1

        assert "本次新增" not in headers
        assert ws.cell(row=2, column=scope_col).value == "历史累计·新近"
        assert ws.cell(row=3, column=scope_col).value == "本次入库·新近"
