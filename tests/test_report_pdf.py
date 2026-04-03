from __future__ import annotations

from pathlib import Path


def _snapshot():
    return {
        "run_id": 1,
        "logical_date": "2026-04-02",
        "snapshot_hash": "hash-1",
    }


def _analytics():
    return {
        "mode": "baseline",
        "taxonomy_version": "v1",
        "label_mode": "rule",
        "generated_at": "2026-04-02T10:00:00+08:00",
        "report_copy": {
            "hero_headline": "Own Grinder 的可靠性问题需要优先处理",
            "executive_bullets": [
                "自有产品差评集中在可靠性问题。",
                "竞品高频卖点集中在易用与做工。",
                "图片证据可以直接支撑质量判断。",
            ],
        },
        "kpis": {
            "product_count": 2,
            "ingested_review_rows": 5,
            "site_reported_review_total_current": 10,
            "translated_count": 5,
            "untranslated_count": 0,
            "own_product_count": 1,
            "competitor_product_count": 1,
            "own_review_rows": 2,
            "competitor_review_rows": 3,
            "image_review_rows": 1,
            "low_rating_review_rows": 2,
        },
        "self": {
            "risk_products": [
                {
                    "product_name": "Own Grinder",
                    "product_sku": "OWN-1",
                    "negative_review_rows": 2,
                    "image_review_rows": 1,
                    "risk_score": 8,
                    "top_labels": [{"label_code": "quality_stability", "count": 1}],
                }
            ],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "label_polarity": "negative",
                    "review_count": 1,
                    "image_review_count": 1,
                    "severity": "high",
                    "example_reviews": [
                        {
                            "product_name": "Own Grinder",
                            "product_sku": "OWN-1",
                            "author": "Alice",
                            "rating": 1,
                            "headline": "Motor failed",
                            "body": "The motor broke after two uses.",
                            "headline_cn": "电机故障",
                            "body_cn": "只用了两次电机就坏了。",
                            "images": ["https://img.example.com/1.jpg"],
                        }
                    ],
                }
            ],
            "recommendations": [
                {
                    "label_code": "quality_stability",
                    "priority": "high",
                    "possible_cause_boundary": "可能与核心部件耐久性有关",
                    "improvement_direction": "优先复核核心部件寿命",
                    "evidence_count": 1,
                }
            ],
        },
        "competitor": {
            "top_positive_themes": [
                {
                    "label_code": "easy_to_use",
                    "label_polarity": "positive",
                    "review_count": 2,
                    "image_review_count": 0,
                    "severity": "low",
                    "example_reviews": [],
                }
            ],
            "benchmark_examples": [
                {
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "author": "Bob",
                    "rating": 5,
                    "headline": "Simple and easy",
                    "body": "Easy to use every day.",
                    "headline_cn": "简单好用",
                    "body_cn": "每天使用都很顺手。",
                    "label_codes": ["easy_to_use"],
                }
            ],
            "negative_opportunities": [
                {
                    "product_name": "Competitor Grinder",
                    "product_sku": "COMP-1",
                    "rating": 2,
                    "headline": "Damaged box",
                    "body": "The packaging was damaged on arrival.",
                    "label_codes": ["packaging_shipping"],
                }
            ],
        },
        "appendix": {
            "image_reviews": [
                {
                    "product_name": "Own Grinder",
                    "product_sku": "OWN-1",
                    "ownership": "own",
                    "rating": 1,
                    "headline": "Motor failed",
                    "body": "The motor broke after two uses.",
                    "label_codes": ["quality_stability"],
                    "images": ["https://img.example.com/1.jpg"],
                }
            ],
            "coverage": {
                "own_products": 1,
                "competitor_products": 1,
                "own_reviews": 2,
                "competitor_reviews": 3,
            },
        },
    }


def test_render_report_html_contains_required_sections(tmp_path):
    from qbu_crawler.server.report_pdf import render_report_html

    html = render_report_html(_snapshot(), _analytics(), str(tmp_path))

    assert "每日深度分析报告" in html
    assert "主结论" in html
    assert "自有产品风险总览" in html
    assert "重点产品深挖" in html
    assert "问题簇与改良建议" in html
    assert "竞品好评 Benchmark" in html
    assert "证据附录" in html
    assert "执行摘要" not in html
    assert "class=\"report-page" in html


def test_build_chart_assets_outputs_svg_files(tmp_path):
    from qbu_crawler.server.report_pdf import build_chart_assets

    chart_paths = build_chart_assets(_analytics(), str(tmp_path))

    assert set(chart_paths) == {
        "self_risk_products",
        "self_negative_clusters",
        "competitor_positive_themes",
    }
    assert all(Path(path).suffix == ".svg" for path in chart_paths.values())


def test_resolve_chart_font_family_prefers_installed_cjk_font():
    from qbu_crawler.server.report_pdf import _resolve_chart_font_family

    family = _resolve_chart_font_family({"Microsoft YaHei", "DejaVu Sans"})

    assert family == "Microsoft YaHei"


def test_render_report_html_inlines_styles_and_svg_assets(tmp_path):
    from qbu_crawler.server.report_pdf import render_report_html

    html = render_report_html(_snapshot(), _analytics(), str(tmp_path))

    assert "<style>" in html
    assert "report-shell" in html
    assert "<svg" in html
    assert 'rel="stylesheet"' not in html
    assert "file:///" not in html


def test_render_report_html_uses_readable_labels_and_mode_copy(tmp_path):
    from qbu_crawler.server.report_pdf import render_report_html

    html = render_report_html(_snapshot(), _analytics(), str(tmp_path))

    assert "首日全量基线版" in html
    assert "质量稳定性" in html
    assert "易上手" in html
    assert "quality_stability" not in html


def test_render_report_html_renders_evidence_image_cards(tmp_path):
    from qbu_crawler.server.report_pdf import render_report_html

    html = render_report_html(_snapshot(), _analytics(), str(tmp_path))

    assert "https://img.example.com/1.jpg" in html
    assert "evidence-media" in html
    assert "E1" in html
    assert "支撑结论" in html
    assert "质量稳定性" in html


def test_write_report_html_preview_creates_file(tmp_path):
    from qbu_crawler.server.report_pdf import write_report_html_preview

    output_path = tmp_path / "preview.html"
    result = write_report_html_preview(_snapshot(), _analytics(), str(output_path))

    assert Path(result).is_file()


def test_generate_pdf_uses_playwright_print_contract(monkeypatch, tmp_path):
    from qbu_crawler.server import report_pdf

    calls = {}

    class FakePage:
        def set_default_timeout(self, timeout):
            calls["default_timeout"] = timeout

        def set_content(self, html, wait_until=None):
            calls["html"] = html
            calls["wait_until"] = wait_until

        def emulate_media(self, media=None):
            calls["media"] = media

        def pdf(self, **kwargs):
            calls["pdf"] = kwargs
            Path(kwargs["path"]).write_text("pdf", encoding="utf-8")

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            calls["browser_closed"] = True

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        def launch(self, headless=True):
            calls["headless"] = headless
            return FakeBrowser()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            calls["manager_closed"] = True

    monkeypatch.setattr(report_pdf, "sync_playwright", lambda: FakeManager())

    output_path = tmp_path / "report.pdf"
    result = report_pdf.generate_pdf_report(_snapshot(), _analytics(), str(output_path))

    assert result == str(output_path)
    assert calls["headless"] is True
    assert calls["default_timeout"] == 60000
    assert calls["wait_until"] == "load"
    assert calls["media"] == "print"
    assert calls["pdf"]["format"] == "A4"
    assert calls["pdf"]["print_background"] is True
    assert calls["pdf"]["prefer_css_page_size"] is True
    assert "timeout" not in calls["pdf"]
