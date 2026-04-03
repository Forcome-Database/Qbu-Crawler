from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from jinja2 import Environment, FileSystemLoader, select_autoescape
from matplotlib import font_manager
from matplotlib import pyplot as plt

from qbu_crawler import config

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None


def _template_dir():
    return Path(__file__).with_name("report_templates")


def _template_env():
    return Environment(
        loader=FileSystemLoader(str(_template_dir())),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _chart_font():
    available = {font.name for font in font_manager.fontManager.ttflist}
    if config.REPORT_PDF_FONT_FAMILY in available:
        plt.rcParams["font.family"] = config.REPORT_PDF_FONT_FAMILY
    else:
        plt.rcParams["font.family"] = "DejaVu Sans"


def _save_bar_chart(labels, values, output_path, title, color):
    _chart_font()
    figure, axis = plt.subplots(figsize=(7.2, 3.4))
    axis.barh(labels, values, color=color)
    axis.set_title(title)
    axis.invert_yaxis()
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(axis="x", linestyle="--", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_path, format="svg", transparent=True)
    plt.close(figure)


def _chart_series(values, label_key, value_key):
    if not values:
        return ["No data"], [0]
    labels = [str(item.get(label_key) or "N/A") for item in values[:8]]
    numbers = [item.get(value_key) or 0 for item in values[:8]]
    return labels, numbers


def build_chart_assets(analytics, output_dir):
    analytics = _normalized_analytics(analytics)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    chart_specs = {}

    labels, values = _chart_series(analytics.get("self", {}).get("risk_products", []), "product_sku", "risk_score")
    chart_file = output_path / "self-risk-products.svg"
    _save_bar_chart(labels, values, chart_file, "Self Risk Products", "#8c3d3d")
    chart_specs["self_risk_products"] = str(chart_file)

    labels, values = _chart_series(
        analytics.get("self", {}).get("top_negative_clusters", []),
        "label_code",
        "review_count",
    )
    chart_file = output_path / "self-negative-clusters.svg"
    _save_bar_chart(labels, values, chart_file, "Self Negative Clusters", "#c45d3c")
    chart_specs["self_negative_clusters"] = str(chart_file)

    labels, values = _chart_series(
        analytics.get("competitor", {}).get("top_positive_themes", []),
        "label_code",
        "review_count",
    )
    chart_file = output_path / "competitor-positive-themes.svg"
    _save_bar_chart(labels, values, chart_file, "Competitor Positive Themes", "#2f7d60")
    chart_specs["competitor_positive_themes"] = str(chart_file)

    coverage = analytics.get("appendix", {}).get("coverage", {})
    labels = ["own_products", "competitor_products", "own_reviews", "competitor_reviews"]
    values = [coverage.get(label, 0) for label in labels]
    chart_file = output_path / "coverage-summary.svg"
    _save_bar_chart(labels, values, chart_file, "Coverage Summary", "#3d5a80")
    chart_specs["coverage_summary"] = str(chart_file)

    return chart_specs


def render_report_html(snapshot, analytics, asset_dir):
    analytics = _normalized_analytics(analytics)
    chart_paths = build_chart_assets(analytics, asset_dir)
    template = _template_env().get_template("daily_report.html.j2")
    return template.render(
        snapshot=snapshot,
        analytics=analytics,
        chart_paths={key: Path(path).as_uri() for key, path in chart_paths.items()},
        css_href=(_template_dir() / "daily_report.css").as_uri(),
        report_font_family=config.REPORT_PDF_FONT_FAMILY,
    )


def _normalized_analytics(analytics):
    return {
        "mode": analytics.get("mode", "baseline"),
        "baseline_sample_days": analytics.get("baseline_sample_days", 0),
        "metric_semantics": {
            "ingested_review_rows": "reviews 实际入库行数",
            "site_reported_review_total_current": "products.review_count 当前站点展示总评论数",
            **(analytics.get("metric_semantics") or {}),
        },
        "kpis": {
            "product_count": 0,
            "ingested_review_rows": 0,
            "site_reported_review_total_current": 0,
            "translated_count": 0,
            "untranslated_count": 0,
            "own_product_count": 0,
            "competitor_product_count": 0,
            "own_review_rows": 0,
            "competitor_review_rows": 0,
            "image_review_rows": 0,
            "low_rating_review_rows": 0,
            **(analytics.get("kpis") or {}),
        },
        "self": {
            "risk_products": [],
            "top_negative_clusters": [],
            "recommendations": [],
            **(analytics.get("self") or {}),
        },
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            **(analytics.get("competitor") or {}),
        },
        "appendix": {
            "image_reviews": [],
            "coverage": {
                "own_products": 0,
                "competitor_products": 0,
                "own_reviews": 0,
                "competitor_reviews": 0,
                **((analytics.get("appendix") or {}).get("coverage") or {}),
            },
            **{
                key: value
                for key, value in (analytics.get("appendix") or {}).items()
                if key != "coverage"
            },
        },
        **{key: value for key, value in analytics.items() if key not in {"metric_semantics", "kpis", "self", "competitor", "appendix"}},
    }


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
        page = browser.new_page()
        page.set_default_timeout(config.REPORT_PDF_TIMEOUT_SECONDS * 1000)
        page.set_content(html, wait_until="load")
        page.emulate_media(media="print")
        page.pdf(
            path=str(output_file),
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
        )
        browser.close()

    return str(output_file)
