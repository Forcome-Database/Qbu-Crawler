from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from matplotlib import font_manager
from matplotlib import pyplot as plt

from qbu_crawler import config
from qbu_crawler.server import report_analytics

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None


_LABEL_DISPLAY = {
    "quality_stability": "质量稳定性",
    "structure_design": "结构设计",
    "assembly_installation": "安装装配",
    "material_finish": "材料与做工",
    "cleaning_maintenance": "清洁维护",
    "noise_power": "噪音与动力",
    "packaging_shipping": "包装运输",
    "service_fulfillment": "售后与履约",
    "easy_to_use": "易上手",
    "solid_build": "做工扎实",
    "good_value": "性价比高",
    "easy_to_clean": "易清洗",
    "strong_performance": "性能强",
    "good_packaging": "包装到位",
}

_SEVERITY_DISPLAY = {"high": "高", "medium": "中", "low": "低"}
_PRIORITY_DISPLAY = {"high": "高", "medium": "中", "low": "低"}

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
    axis.barh(labels, values, color=color, height=0.56)
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


def _chart_series(values, label_key, value_key):
    if not values:
        return ["暂无数据"], [0]
    labels = [str(item.get(label_key) or "N/A") for item in values[:6]]
    numbers = [item.get(value_key) or 0 for item in values[:6]]
    return labels, numbers


def build_chart_assets(analytics, output_dir):
    analytics = _normalized_analytics(analytics)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    chart_specs = {}

    labels, values = _chart_series(analytics["self"]["risk_products"], "product_name", "risk_score")
    chart_file = output_path / "self-risk-products.svg"
    _save_bar_chart(labels, values, chart_file, "高风险产品排序", "#8f4c38")
    chart_specs["self_risk_products"] = str(chart_file)

    labels, values = _chart_series(analytics["self"]["top_negative_clusters"], "label_display", "review_count")
    chart_file = output_path / "self-negative-clusters.svg"
    _save_bar_chart(labels, values, chart_file, "问题簇排序", "#b7633f")
    chart_specs["self_negative_clusters"] = str(chart_file)

    labels, values = _chart_series(analytics["competitor"]["top_positive_themes"], "label_display", "review_count")
    chart_file = output_path / "competitor-positive-themes.svg"
    _save_bar_chart(labels, values, chart_file, "竞品正向主题", "#355f57")
    chart_specs["competitor_positive_themes"] = str(chart_file)

    return chart_specs


def _label_display(label_code):
    return _LABEL_DISPLAY.get(label_code or "", label_code or "")


def _join_label_counts(items):
    values = []
    for item in items or []:
        label_code = item.get("label_code")
        if not label_code:
            continue
        values.append(f"{_label_display(label_code)}({item.get('count') or 0})")
    return "、".join(values) or "暂无"


def _join_label_codes(label_codes):
    values = [_label_display(label_code) for label_code in label_codes or [] if label_code]
    return "、".join(values) or "暂无"


def _summary_text(item):
    title = (item.get("headline_cn") or item.get("headline") or "").strip()
    body = (item.get("body_cn") or item.get("body") or "").strip()
    if title and body:
        return f"{title}：{body}"
    return title or body or "暂无摘要"


def _derive_review_label_codes(review):
    label_codes = [item for item in (review.get("label_codes") or []) if item]
    if label_codes:
        return label_codes
    labels = report_analytics.classify_review_labels(review)
    ownership = review.get("ownership") or ""
    preferred = "negative" if ownership == "own" else "positive"
    preferred_codes = [item["label_code"] for item in labels if item.get("label_polarity") == preferred]
    if preferred_codes:
        return preferred_codes[:3]
    return [item["label_code"] for item in labels[:3]]


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
    analytics = analytics or {}
    normalized = {
        "mode": analytics.get("mode", "baseline"),
        "mode_display": "首日全量基线版" if analytics.get("mode", "baseline") == "baseline" else "增量监控版",
        "baseline_sample_days": analytics.get("baseline_sample_days", 0),
        "metric_semantics": {
            "ingested_review_rows": "reviews 实际入库行数",
            "site_reported_review_total_current": "products.review_count 当前站点展示总评论数",
            **(analytics.get("metric_semantics") or {}),
        },
        "report_copy": {
            "hero_headline": "",
            "executive_bullets": [],
            **(analytics.get("report_copy") or {}),
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
        **{
            key: value
            for key, value in analytics.items()
            if key not in {"metric_semantics", "report_copy", "kpis", "self", "competitor", "appendix"}
        },
    }

    negative_clusters = []
    for item in normalized["self"]["top_negative_clusters"]:
        cluster = dict(item)
        cluster["label_display"] = _label_display(cluster.get("label_code"))
        cluster["severity_display"] = _SEVERITY_DISPLAY.get(cluster.get("severity"), cluster.get("severity") or "")
        examples = []
        for example in cluster.get("example_reviews") or []:
            record = dict(example)
            record["summary_text"] = _summary_text(record)
            record["primary_image"] = (record.get("images") or [None])[0]
            examples.append(record)
        cluster["example_reviews"] = examples
        negative_clusters.append(cluster)
    normalized["self"]["top_negative_clusters"] = negative_clusters

    recommendations = []
    for item in normalized["self"]["recommendations"]:
        recommendation = dict(item)
        recommendation["label_display"] = _label_display(recommendation.get("label_code"))
        recommendation["priority_display"] = _PRIORITY_DISPLAY.get(
            recommendation.get("priority"),
            recommendation.get("priority") or "",
        )
        recommendations.append(recommendation)
    normalized["self"]["recommendations"] = recommendations

    positive_themes = []
    for item in normalized["competitor"]["top_positive_themes"]:
        theme = dict(item)
        theme["label_display"] = _label_display(theme.get("label_code"))
        positive_themes.append(theme)
    normalized["competitor"]["top_positive_themes"] = positive_themes

    benchmark_examples = []
    for item in normalized["competitor"]["benchmark_examples"]:
        example = dict(item)
        example["label_display_list"] = _join_label_codes(example.get("label_codes") or [])
        example["summary_text"] = _summary_text(example)
        benchmark_examples.append(example)
    normalized["competitor"]["benchmark_examples"] = benchmark_examples

    opportunities = []
    for item in normalized["competitor"]["negative_opportunities"]:
        opportunity = dict(item)
        opportunity["label_display_list"] = _join_label_codes(opportunity.get("label_codes") or [])
        opportunity["summary_text"] = _summary_text(opportunity)
        opportunities.append(opportunity)
    normalized["competitor"]["negative_opportunities"] = opportunities

    image_reviews = []
    evidence_refs_by_sku = {}
    evidence_refs_by_label = {}
    for index, item in enumerate(normalized["appendix"]["image_reviews"][:4], start=1):
        review = dict(item)
        images = review.get("images") or []
        label_codes = _derive_review_label_codes(review)
        review["label_codes"] = label_codes
        review["label_display_list"] = _join_label_codes(label_codes)
        review["primary_image"] = images[0] if images else None
        review["headline_display"] = review.get("headline_cn") or review.get("headline") or "图片证据"
        review["body_display"] = review.get("body_cn") or review.get("body") or ""
        review["evidence_id"] = f"E{index}"
        review["supports_text"] = (
            f"支撑结论：{review['label_display_list']}" if label_codes else "支撑结论：自有产品差评判断"
        )
        product_key = review.get("product_sku") or review.get("product_name") or ""
        if product_key:
            evidence_refs_by_sku.setdefault(product_key, []).append(review["evidence_id"])
        for label_code in label_codes:
            evidence_refs_by_label.setdefault(label_code, []).append(review["evidence_id"])
        image_reviews.append(review)
    normalized["appendix"]["image_reviews"] = image_reviews

    risk_products = []
    for item in normalized["self"]["risk_products"]:
        product = dict(item)
        product["top_labels_display"] = _join_label_counts(product.get("top_labels") or [])
        evidence_refs = evidence_refs_by_sku.get(product.get("product_sku") or product.get("product_name") or "", [])
        product["evidence_refs"] = evidence_refs
        product["evidence_refs_display"] = "、".join(evidence_refs) or "暂无图片证据"
        product["focus_summary"] = ""
        for cluster in normalized["self"]["top_negative_clusters"]:
            for example in cluster.get("example_reviews") or []:
                if example.get("product_sku") == product.get("product_sku"):
                    product["focus_summary"] = example.get("summary_text") or ""
                    break
            if product["focus_summary"]:
                break
        risk_products.append(product)
    normalized["self"]["risk_products"] = risk_products

    for item in normalized["self"]["top_negative_clusters"]:
        evidence_refs = evidence_refs_by_label.get(item.get("label_code"), [])
        item["evidence_refs"] = evidence_refs
        item["evidence_refs_display"] = "、".join(evidence_refs) or "暂无图片证据"

    for item in normalized["self"]["recommendations"]:
        evidence_refs = evidence_refs_by_label.get(item.get("label_code"), [])
        item["evidence_refs"] = evidence_refs
        item["evidence_refs_display"] = "、".join(evidence_refs) or "暂无图片证据"

    normalized["competitor"]["benchmark_takeaways"] = [
        f"用户持续认可{item.get('label_display')}体验。"
        for item in normalized["competitor"]["top_positive_themes"][:3]
    ]

    if not normalized["report_copy"]["hero_headline"]:
        normalized["report_copy"]["hero_headline"] = _fallback_hero_headline(normalized)
    if not normalized["report_copy"]["executive_bullets"]:
        normalized["report_copy"]["executive_bullets"] = _fallback_executive_bullets(normalized)

    return normalized


def _inline_chart_svgs(chart_paths):
    return {
        key: Markup(Path(path).read_text(encoding="utf-8"))
        for key, path in chart_paths.items()
    }


def render_report_html(snapshot, analytics, asset_dir):
    analytics = _normalized_analytics(analytics)
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
        browser.close()

    return str(output_file)
