from __future__ import annotations

from pathlib import Path

import pytest
import requests


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
            "hero_headline": "Own Grinder 的可靠性问题需要优先处理。",
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
            "negative_review_rows": 2,
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

    assert "report-page-hero" in html
    assert "hero-headline" in html
    assert "focus-grid" in html
    assert "issue-grid" in html
    assert "benchmark-layout" in html
    assert "report-section" in html
    assert 'class="report-page' in html


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

    assert "quality_stability" not in html
    assert "easy_to_use" not in html
    assert "Own Grinder 的可靠性问题需要优先处理。" in html
    assert "自有产品差评集中在可靠性问题。" in html


def test_render_report_html_uses_business_kpis(tmp_path):
    from qbu_crawler.server.report_pdf import render_report_html

    html = render_report_html(_snapshot(), _analytics(), str(tmp_path))

    assert "新增评论" in html
    assert "差评率" in html
    assert "图片评论" not in html
    assert "40.0%" in html


def test_render_report_html_renders_evidence_refs(tmp_path, monkeypatch):
    """Evidence appendix was removed; verify evidence ref IDs still appear in risk/cluster sections."""
    from qbu_crawler.server.report_pdf import render_report_html

    class FakeResponse:
        content = b"\x89PNG\r\n\x1a\nfake-image"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "get", lambda url, timeout=10: FakeResponse())

    html = render_report_html(_snapshot(), _analytics(), str(tmp_path))

    # Evidence ref IDs are still computed and shown in risk products / cluster sections
    assert "E1" in html
    # Evidence appendix section is removed from the template body (class may still exist in CSS)
    assert 'class="evidence-directory"' not in html


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
    assert calls["pdf"]["prefer_css_page_size"] is False
    assert calls["pdf"]["display_header_footer"] is True
    assert calls["pdf"]["margin"] == {"top": "18mm", "bottom": "16mm", "left": "10mm", "right": "10mm"}
    assert "header_template" in calls["pdf"]
    assert "footer_template" in calls["pdf"]
    assert "Daily Product Intelligence" in calls["pdf"]["header_template"]
    assert "2026-04-02" in calls["pdf"]["header_template"]
    assert "Run #1" in calls["pdf"]["footer_template"]
    assert "pageNumber" in calls["pdf"]["footer_template"]
    assert "totalPages" in calls["pdf"]["footer_template"]
    assert "timeout" not in calls["pdf"]


def test_generate_pdf_closes_browser_when_pdf_raises(monkeypatch, tmp_path):
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
            raise RuntimeError("pdf failed")

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

    with pytest.raises(RuntimeError, match="pdf failed"):
        report_pdf.generate_pdf_report(_snapshot(), _analytics(), str(tmp_path / "report.pdf"))

    assert calls["browser_closed"] is True
