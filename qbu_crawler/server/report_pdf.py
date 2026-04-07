import base64
import logging
import mimetypes
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.offline import get_plotlyjs

from qbu_crawler import config
from qbu_crawler.server import report
from qbu_crawler.server.report_charts import build_chart_html_fragments
from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _PRIORITY_DISPLAY,
    _SEVERITY_DISPLAY,
    _competitor_gap_analysis,
    _compute_alert_level,
    _compute_kpi_deltas,
    _derive_review_label_codes,
    _generate_hero_headline,
    _humanize_bullets,
    _join_label_codes,
    _join_label_counts,
    _label_display,
    _load_previous_analytics,
    _summary_text,
)

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None


_FONT_FAMILY_CANDIDATES = (
    config.REPORT_PDF_FONT_FAMILY,
    "Microsoft YaHei",
    "Microsoft JhengHei",
    "DengXian",
    "SimHei",
    "SimSun",
    "PingFang SC",
    "Hiragino Sans GB",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",
)


def _template_dir():
    return Path(__file__).with_name("report_templates")


def _template_env():
    return Environment(
        loader=FileSystemLoader(str(_template_dir())),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _font_candidates():
    seen = set()
    for family in _FONT_FAMILY_CANDIDATES:
        if not family or family in seen:
            continue
        seen.add(family)
        yield family


def _report_font_family_stack():
    values = [f'"{family}"' if " " in family else family for family in _font_candidates()]
    values.extend(['"DejaVu Sans"', "sans-serif"])
    return ", ".join(values)


def _normalized_analytics(analytics):
    return report.normalize_deep_report_analytics(analytics)


def _inline_image_data_uri(url, max_size=(300, 240), quality=75):
    if not url:
        return None
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        logger.warning("Skipping non-HTTP image URL: %s", str(url)[:100])
        return None
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except Exception:
        logger.warning("Image download failed, omitting from PDF: %s", url[:100])
        return None
    if len(response.content) > 2 * 1024 * 1024:
        logger.warning("Image too large (%d bytes), omitting: %s", len(response.content), url[:100])
        return None

    # Pillow 缩放压缩
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(response.content))
        img.thumbnail(max_size, Image.LANCZOS)
        buf = _io.BytesIO()
        # 转 RGB（处理 RGBA/P 模式）
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality)
        payload = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"
    except Exception:
        # Pillow 处理失败，退回原始编码
        payload = base64.b64encode(response.content).decode("ascii")
        content_type = response.headers.get("Content-Type") or mimetypes.guess_type(url)[0] or "application/octet-stream"
        return f"data:{content_type};base64,{payload}"


def render_report_html(snapshot, analytics, asset_dir=None):
    normalized = _normalized_analytics(analytics)

    # Delta 链路
    prev_analytics = _load_previous_analytics(snapshot.get("run_id"))
    kpi_deltas = _compute_kpi_deltas(normalized["kpis"], prev_analytics)
    normalized["kpis"].update(kpi_deltas)

    # Hero headline (from report_copy if LLM populated it, else fallback)
    if not normalized.get("report_copy", {}).get("hero_headline"):
        normalized.setdefault("report_copy", {})["hero_headline"] = _generate_hero_headline(normalized)

    # Alert level
    alert_level, alert_text = _compute_alert_level(normalized)
    normalized["alert_level"] = alert_level
    normalized["alert_text"] = alert_text

    # Humanized bullets
    normalized.setdefault("report_copy", {})["executive_bullets_human"] = _humanize_bullets(normalized)

    # Gap analysis
    normalized.setdefault("competitor", {})["gap_analysis"] = _competitor_gap_analysis(normalized)

    # 图片 data URI
    for item in normalized.get("appendix", {}).get("image_reviews", []):
        item["primary_image_data_uri"] = _inline_image_data_uri(item.get("primary_image"))

    # issue_cards image_evidence: convert URLs to data URIs for offline PDF rendering
    for card in normalized.get("self", {}).get("issue_cards", []):
        for img_item in card.get("image_evidence") or []:
            img_item["data_uri"] = _inline_image_data_uri(img_item.get("url"))

    # Plotly 图表 HTML 片段
    charts = build_chart_html_fragments(normalized)
    plotly_js = get_plotlyjs()

    # CSS
    css_text = (_template_dir() / "daily_report.css").read_text(encoding="utf-8")
    font_family = _report_font_family_stack()

    # 模板渲染
    template = _template_env().get_template("daily_report.html.j2")
    return template.render(
        snapshot=snapshot,
        analytics=normalized,
        charts=charts,
        plotly_js=plotly_js,
        css_text=css_text,
        threshold=config.NEGATIVE_THRESHOLD,
        report_font_family=font_family,
    )


def write_report_html_preview(snapshot, analytics, output_path):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    html = render_report_html(snapshot, analytics)
    output_file.write_text(html, encoding="utf-8")
    return str(output_file)


def _build_header_template(snapshot):
    date = snapshot.get("logical_date", "")
    return (
        '<div style="width:100%;font-size:8px;color:#766d62;overflow:hidden;">'
        f'<span style="float:left;">Daily Product Intelligence · 内部资料</span>'
        f'<span style="float:right;">{date}</span>'
        '</div>'
    )


def _build_footer_template(snapshot):
    run_id = snapshot.get("run_id", "")
    return (
        '<div style="width:100%;font-size:8px;color:#766d62;overflow:hidden;">'
        f'<span style="float:left;">Run #{run_id}</span>'
        '<span style="float:right;"><span class="pageNumber"></span> / <span class="totalPages"></span></span>'
        '</div>'
    )


def generate_pdf_report(snapshot, analytics, output_path):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    html = render_report_html(snapshot, analytics)

    runtime_sync_playwright = sync_playwright
    if runtime_sync_playwright is None:
        from playwright.sync_api import sync_playwright as runtime_sync_playwright

    with runtime_sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(config.REPORT_PDF_TIMEOUT_SECONDS * 1000)
            page.set_content(html, wait_until="load")
            if hasattr(page, "wait_for_function"):
                page.wait_for_function(
                    "() => document.fonts ? document.fonts.status === 'loaded' : true"
                )
                page.wait_for_function(
                    "() => Array.from(document.images).every((img) => img.complete)"
                )
            page.emulate_media(media="print")
            page.pdf(
                path=str(output_file),
                format="A4",
                print_background=True,
                prefer_css_page_size=False,
                display_header_footer=True,
                margin={"top": "18mm", "bottom": "16mm", "left": "10mm", "right": "10mm"},
                header_template=_build_header_template(snapshot),
                footer_template=_build_footer_template(snapshot),
            )
        finally:
            browser.close()

    return str(output_file)
