import base64
import logging
import mimetypes
from pathlib import Path

import matplotlib
import requests

matplotlib.use("Agg")

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from matplotlib import font_manager
from matplotlib import pyplot as plt

from qbu_crawler import config
from qbu_crawler.server import report
from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _PRIORITY_DISPLAY,
    _SEVERITY_DISPLAY,
    _derive_review_label_codes,
    _join_label_codes,
    _join_label_counts,
    _label_display,
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


def _resolve_chart_font_family(available=None):
    available = available or {font.name for font in font_manager.fontManager.ttflist}
    for family in _font_candidates():
        if family in available:
            return family
    logger.warning(
        "No CJK font found for chart rendering; Chinese text will display as boxes. "
        "Install a CJK font (e.g., 'apt install fonts-noto-cjk' or set REPORT_PDF_FONT_FAMILY)."
    )
    return "DejaVu Sans"


def _report_font_family_stack():
    values = [f'"{family}"' if " " in family else family for family in _font_candidates()]
    values.extend(['"DejaVu Sans"', "sans-serif"])
    return ", ".join(values)


def _chart_font():
    plt.rcParams["font.family"] = _resolve_chart_font_family()
    plt.rcParams["axes.unicode_minus"] = False


def _save_bar_chart(labels, values, output_path, title, color):
    _chart_font()
    figure, axis = plt.subplots(figsize=(7.0, 3.1))
    bars = axis.barh(labels, values, color=color, height=0.56)
    axis.bar_label(bars, fmt="%.0f", padding=4, fontsize=9, color="#4a4a4a")
    axis.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=10)
    axis.invert_yaxis()
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_visible(False)
    axis.grid(axis="x", linestyle="--", alpha=0.2)
    axis.tick_params(axis="y", labelsize=10, length=0)
    axis.tick_params(axis="x", labelsize=9, colors="#6b6b6b")
    figure.tight_layout()
    figure.savefig(output_path, format="svg", transparent=True)
    plt.close(figure)


def _truncate_label(label, max_visual_width=36):
    """按视觉宽度截断：CJK 字符计 2，ASCII 计 1。"""
    width = 0
    for i, ch in enumerate(label):
        width += 2 if ord(ch) > 127 else 1
        if width > max_visual_width:
            return label[:i] + "..."
    return label


def _chart_series(values, label_key, value_key):
    if not values:
        return ["暂无数据"], [0]
    labels = [_truncate_label(str(item.get(label_key) or "N/A")) for item in values[:6]]
    numbers = [item.get(value_key) or 0 for item in values[:6]]
    return labels, numbers


def _save_risk_matrix(products, output_path):
    """散点图：X=差评数, Y=风险分, 气泡大小=总评论数"""
    _chart_font()
    fig, ax = plt.subplots(figsize=(7.0, 4.5))
    x = [p.get("negative_review_rows", 0) for p in products]
    y = [p.get("risk_score", 0) for p in products]
    sizes = [max(p.get("total_reviews", 10), 10) * 2 for p in products]
    skus = [p.get("product_sku", "N/A") for p in products]
    ax.scatter(x, y, s=sizes, c="#8f4c38", alpha=0.7, edgecolors="#5a3020", linewidths=1)
    for i, sku in enumerate(skus):
        ax.annotate(sku, (x[i], y[i]), textcoords="offset points", xytext=(8, 4), fontsize=8, color="#4a4a4a")
    ax.set_xlabel("差评数", fontsize=10)
    ax.set_ylabel("风险分", fontsize=10)
    ax.set_title("自有产品风险矩阵", loc="left", fontsize=12, fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, linestyle="--", alpha=0.15)
    fig.tight_layout()
    fig.savefig(output_path, format="svg", transparent=True)
    plt.close(fig)


def build_chart_assets(analytics, output_dir):
    analytics = _normalized_analytics(analytics)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    chart_specs = {}

    labels, values = _chart_series(analytics["self"]["risk_products"], "product_name", "risk_score")
    chart_file = output_path / "self-risk-products.svg"
    _save_bar_chart(labels, values, chart_file, "高风险产品排序", "#8f4c38")
    chart_specs["self_risk_products"] = str(chart_file)

    severity_colors = {
        "high": "#6b3328",
        "medium": "#b7633f",
        "low": "#a89070",
    }
    negative_clusters = analytics["self"]["top_negative_clusters"]
    labels, values = _chart_series(negative_clusters, "label_display", "review_count")
    cluster_colors = [
        severity_colors.get((negative_clusters[i].get("severity") or "medium") if i < len(negative_clusters) else "medium", "#b7633f")
        for i in range(len(labels))
    ]
    chart_file = output_path / "self-negative-clusters.svg"
    _save_bar_chart(labels, values, chart_file, "问题簇排序", cluster_colors)
    chart_specs["self_negative_clusters"] = str(chart_file)

    labels, values = _chart_series(analytics["competitor"]["top_positive_themes"], "label_display", "review_count")
    chart_file = output_path / "competitor-positive-themes.svg"
    _save_bar_chart(labels, values, chart_file, "竞品正向主题", "#355f57")
    chart_specs["competitor_positive_themes"] = str(chart_file)

    risk_products = analytics["self"]["risk_products"]
    if len(risk_products) >= 6:
        chart_file = output_path / "self-risk-matrix.svg"
        _save_risk_matrix(risk_products, chart_file)
        chart_specs["self_risk_matrix"] = str(chart_file)

    return chart_specs


def _fallback_hero_headline(normalized):
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    top_cluster = (normalized["self"]["top_negative_clusters"] or [None])[0]
    if top_product and top_cluster:
        return (
            f"自有产品 {top_product.get('product_name')} 的"
            f"{top_cluster.get('label_display')}问题已形成当前最高风险，建议优先处理。"
        )
    if top_product:
        return f"自有产品 {top_product.get('product_name')} 已形成当前最高风险，建议优先排查。"
    if normalized["competitor"]["top_positive_themes"]:
        return (
            f"当前竞品最稳定的用户认可点集中在"
            f"{normalized['competitor']['top_positive_themes'][0].get('label_display')}。"
        )
    return "当前样本不足以形成明确主结论，建议继续积累样本后再判读。"


def _fallback_executive_bullets(normalized):
    bullets = []
    bullets.append(
        f"当前纳入分析产品 {normalized['kpis']['product_count']} 个，自有 {normalized['kpis']['own_product_count']} 个，竞品 {normalized['kpis']['competitor_product_count']} 个。"
    )
    if normalized["self"]["risk_products"]:
        names = "、".join(item.get("product_name") for item in normalized["self"]["risk_products"][:2])
        bullets.append(f"优先关注的自有产品为 {names}。")
    if normalized["competitor"]["top_positive_themes"]:
        themes = "、".join(item.get("label_display") for item in normalized["competitor"]["top_positive_themes"][:3])
        bullets.append(f"竞品高频正向主题集中在 {themes}。")
    return bullets[:3]


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


def _inline_chart_svgs(chart_paths):
    return {
        key: Markup(Path(path).read_text(encoding="utf-8"))
        for key, path in chart_paths.items()
    }


def render_report_html(snapshot, analytics, asset_dir):
    analytics = _normalized_analytics(analytics)
    for item in analytics["appendix"]["image_reviews"]:
        item["primary_image_data_uri"] = _inline_image_data_uri(item.get("primary_image"))
    chart_paths = build_chart_assets(analytics, asset_dir)
    template = _template_env().get_template("daily_report.html.j2")
    css_text = (_template_dir() / "daily_report.css").read_text(encoding="utf-8")
    return template.render(
        snapshot=snapshot,
        analytics=analytics,
        chart_svgs=_inline_chart_svgs(chart_paths),
        css_text=css_text,
        report_font_family=_report_font_family_stack(),
    )


def write_report_html_preview(snapshot, analytics, output_path):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    asset_dir = output_file.parent / f"{output_file.stem}-assets"
    html = render_report_html(snapshot, analytics, str(asset_dir))
    output_file.write_text(html, encoding="utf-8")
    return str(output_file)


def generate_pdf_report(snapshot, analytics, output_path):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    asset_dir = output_file.parent / f"{output_file.stem}-assets"
    html = render_report_html(snapshot, analytics, str(asset_dir))

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
                prefer_css_page_size=True,
            )
        finally:
            browser.close()

    return str(output_file)
