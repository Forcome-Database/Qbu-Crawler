"""V3 HTML report rendering — replaces Playwright PDF pipeline."""

import json
import logging
import os
from datetime import date, timedelta
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


def _annotate_reviews(reviews, logical_date_str):
    """F011 §4.2.6 — annotate review dicts with derived flags for panorama filters.

    Adds (idempotent — re-running over already-annotated reviews is a no-op):
      - is_recent (bool): date_published within 30 days of logical_date
      - label_codes (list[str]): codes parsed from analysis_labels JSON string

    Mutates each review dict in-place; safe to call once per render.
    """
    try:
        ref_date = date.fromisoformat((logical_date_str or "")[:10]) if logical_date_str else date.today()
    except (ValueError, TypeError):
        ref_date = date.today()
    cutoff = ref_date - timedelta(days=30)

    for r in reviews or []:
        # is_recent
        try:
            d = date.fromisoformat((r.get("date_published") or "")[:10])
            r["is_recent"] = d >= cutoff
        except (ValueError, TypeError):
            r["is_recent"] = False

        # label_codes — parse JSON-string analysis_labels (Task 3.3 canonical field)
        raw = r.get("analysis_labels")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw or "[]")
            except (json.JSONDecodeError, TypeError):
                parsed = []
        elif isinstance(raw, list):
            parsed = raw
        else:
            parsed = []
        codes = []
        for lab in parsed or []:
            if not isinstance(lab, dict):
                continue
            code = lab.get("code") or lab.get("label_code")
            if code:
                codes.append(code)
        r["label_codes"] = codes


def _render_v3_html_string(snapshot, analytics):
    """Render the V3 interactive HTML report to a string.

    Shared core used by:
      - ``render_v3_html`` — writes to disk and returns the file path.
      - ``render_attachment_html`` — returns the HTML string directly
        (F011 §4.2.4 contract; preferred entry for tests).
    """
    normalized = normalize_deep_report_analytics(analytics)

    # F011 §4.2.6 — annotate reviews for panorama filter chrome (idempotent)
    _annotate_reviews(snapshot.get("reviews") or [], snapshot.get("logical_date"))

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

    return template.render(
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


def render_v3_html(snapshot, analytics, output_path=None):
    """Render the V3 interactive HTML report and write it to disk.

    Returns the file path of the generated HTML file.
    """
    html = _render_v3_html_string(snapshot, analytics)

    if output_path is None:
        run_id = snapshot.get("run_id", 0)
        output_path = os.path.join(config.REPORT_DIR, f"workflow-run-{run_id}-report-v3.html")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("V3 HTML report rendered: %s (%d bytes)", output_path, len(html))
    return output_path


def render_attachment_html(snapshot, analytics):
    """Render the V3 attachment HTML and return it as a string.

    Public alias used by F011 tests / spec (§4.2.4). Does NOT write to disk.
    """
    return _render_v3_html_string(snapshot, analytics)
