"""V3 HTML report rendering — replaces Playwright PDF pipeline."""

import json
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from qbu_crawler import config
from qbu_crawler.server.report_common import (
    _compute_alert_level,
    has_estimated_dates,
    normalize_deep_report_analytics,
)
from qbu_crawler.server.report_charts import build_chartjs_configs

logger = logging.getLogger(__name__)


def render_v3_html(snapshot, analytics, output_path=None):
    """Render the V3 interactive HTML report.

    Returns the file path of the generated HTML file.
    """
    normalized = normalize_deep_report_analytics(analytics)

    # Compute alert level before passing to template
    computed_alert = _compute_alert_level(normalized)
    normalized["alert_level"] = computed_alert

    charts = build_chartjs_configs(normalized)

    # Add has_estimated_dates flag for template
    normalized["has_estimated_dates"] = has_estimated_dates(
        snapshot.get("reviews", []),
        snapshot.get("logical_date", ""),
    )

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("daily_report_v3.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    js_text = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    # Extract alert level from normalized (it's a tuple or already unpacked)
    alert = normalized.get("alert_level", ("green", ""))
    if isinstance(alert, (list, tuple)) and len(alert) >= 2:
        alert_level, alert_text = alert[0], alert[1]
    else:
        alert_level, alert_text = "green", ""

    html = template.render(
        logical_date=snapshot.get("logical_date", ""),
        mode=normalized.get("mode", "baseline"),
        snapshot=snapshot,
        analytics=normalized,
        charts=charts,
        alert_level=alert_level,
        alert_text=alert_text,
        report_copy=normalized.get("report_copy") or analytics.get("report_copy") or {},
        css_text=css_text,
        js_text=js_text,
        threshold=config.NEGATIVE_THRESHOLD,
        cumulative_kpis=normalized.get("cumulative_kpis") or normalized.get("kpis", {}),
        window=normalized.get("window", {}),
    )

    if output_path is None:
        run_id = snapshot.get("run_id", 0)
        output_path = os.path.join(config.REPORT_DIR, f"workflow-run-{run_id}-report-v3.html")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("V3 HTML report rendered: %s (%d bytes)", output_path, len(html))
    return output_path
