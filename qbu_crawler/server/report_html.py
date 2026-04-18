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


def render_v3_html(snapshot, analytics, output_path=None, changes=None):
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
        changes=changes,
    )

    if output_path is None:
        run_id = snapshot.get("run_id", 0)
        output_path = os.path.join(config.REPORT_DIR, f"workflow-run-{run_id}-report-v3.html")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("V3 HTML report rendered: %s (%d bytes)", output_path, len(html))
    return output_path


def render_daily_briefing(snapshot, cumulative_kpis, window_reviews,
                          attention_signals, changes, output_path,
                          quiet_days=0):
    """Render the P008 Phase 2 daily briefing three-block HTML."""
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("daily_briefing.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    html = template.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        cumulative_kpis=cumulative_kpis,
        window_reviews=window_reviews,
        attention_signals=attention_signals,
        changes=changes,
        quiet_days=quiet_days,
        css_text=css_text,
        threshold=config.NEGATIVE_THRESHOLD,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("Daily briefing HTML rendered: %s (%d bytes)", output_path, len(html))
    return output_path


def render_daily_v4(
    snapshot, analytics, cumulative_kpis, window_reviews,
    attention_signals, changes, output_path, *, mode, mode_context,
):
    """V4 daily renderer — mode-aware, shared partials."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      autoescape=select_autoescape(["html", "j2"]))
    css_path = template_dir / "daily_report_v3.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    normalized = normalize_deep_report_analytics(analytics or {})
    logical_date = snapshot.get("logical_date", "")
    action_signals = [s for s in (attention_signals or []) if s.get("urgency") == "action"]

    # Hero inputs derived from mode
    kicker_map = {
        "partial": f"BASELINE BUILDING · Day {mode_context.get('day_index', 1)}/7",
        "full":    f"DAILY INTELLIGENCE · {logical_date}",
        "change":  "CHANGE ONLY · 产品数据变动",
        "quiet":   f"QUIET · 连续 {mode_context.get('quiet_days', 0)} 天无新评论",
    }
    headline_map = {
        "partial": "样本积累中，本日数据置信度：样本不足",
        "full":    (normalized.get("report_copy") or {}).get("hero_headline") or "",
        "change":  f"今日 {len((changes or {}).get('price_changes') or []) + len((changes or {}).get('stock_changes') or [])} 个产品发生变动",
        "quiet":   "累积指标稳定，详情见核心指标卡",
    }
    tabs = [{"id": "overview", "label": "总览"}]
    if mode in ("full", "partial"):
        tabs += [
            {"id": "changes", "label": "今日变化",
             "badge": len(window_reviews or []) if window_reviews else None},
            {"id": "issues", "label": "问题诊断",
             "badge": len(normalized.get("issue_cards") or []) or None},
            {"id": "panorama", "label": "全景"},
        ]

    # Expose kpis_normalized on analytics wrapper so {{ analytics.kpis_normalized }} works
    analytics_view = dict(normalized)
    analytics_view["kpis_normalized"] = normalized.get("kpis", {})

    return _write_template(
        env, "daily.html.j2", output_path,
        page_title=f"QBU 网评监控 · 日报 {logical_date}",
        css_text=css_text,
        brand="QBU 网评监控",
        kpi_items=[
            {"label": "健康", "value": normalized["kpis"].get("health_index", "—")},
            {"label": "差评", "value": normalized["kpis"].get("own_negative_review_rate_display", "—")},
            {"label": "高风险", "value": normalized["kpis"].get("high_risk_count", 0)},
        ],
        mode=mode,
        kicker=kicker_map.get(mode, ""),
        meta=f"Run #{snapshot.get('run_id','?')} · {logical_date}",
        cards=normalized.get("kpi_cards", []),
        tabs=tabs,
        active="overview",
        title="QBU网评监控智能分析报告",
        headline=headline_map.get(mode, ""),
        health_index=normalized["kpis"].get("health_index"),
        confidence=normalized["kpis"].get("health_confidence", "no_data"),
        bullets=(normalized.get("report_copy") or {}).get("executive_bullets_human") or [],
        actions=None,
        analytics=analytics_view,
        snapshot=snapshot,
        window_reviews=window_reviews or [],
        changes=changes or {},
        action_signals=action_signals,
        mode_context=mode_context,
        threshold=config.NEGATIVE_THRESHOLD,
        generated_at=(snapshot.get("snapshot_at") or "")[:19],
        version="v4",
    )


def _write_template(env, name, output_path, **ctx):
    html = env.get_template(name).render(**ctx)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("V4 render: %s (%d bytes)", output_path, len(html))
    return output_path


def render_weekly_v4(snapshot, analytics, output_path=None, changes=None):
    """V4 weekly renderer using shared partials."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      autoescape=select_autoescape(["html", "j2"]))
    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    js_text = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    normalized = normalize_deep_report_analytics(analytics or {})
    logical_date = snapshot.get("logical_date", "")
    iso_week = (snapshot.get("_meta") or {}).get("iso_week") or logical_date

    tabs = [
        {"id": "overview", "label": "总览"},
        {"id": "changes", "label": "本周变化",
         "badge": len((snapshot.get("reviews") or [])) or None},
        {"id": "issues", "label": "问题诊断",
         "badge": len(normalized.get("issue_cards") or []) or None},
        {"id": "products", "label": "产品排行"},
        {"id": "panorama", "label": "全景"},
    ]

    if output_path is None:
        output_path = os.path.join(
            config.REPORT_DIR,
            f"workflow-run-{snapshot.get('run_id','x')}-full-report.html",
        )

    return _write_template(
        env, "weekly.html.j2", output_path,
        page_title=f"QBU 网评监控 · 周报 {iso_week}",
        css_text=css_text, js_text=js_text,
        brand="QBU 网评监控",
        kpi_items=[
            {"label": "健康", "value": normalized["kpis"].get("health_index", "—")},
            {"label": "差评", "value": normalized["kpis"].get("own_negative_review_rate_display", "—")},
            {"label": "高风险", "value": normalized["kpis"].get("high_risk_count", 0)},
        ],
        show_print=True,
        mode="weekly",
        kicker=f"WEEKLY REPORT · {iso_week}",
        meta=f"Run #{snapshot.get('run_id','?')} · {logical_date}",
        title="QBU 网评监控 周报",
        headline=(normalized.get("report_copy") or {}).get("hero_headline") or "",
        health_index=normalized["kpis"].get("health_index"),
        confidence=normalized["kpis"].get("health_confidence", "no_data"),
        bullets=(normalized.get("report_copy") or {}).get("executive_bullets_human") or [],
        actions=None,
        cards=normalized.get("kpi_cards", []),
        tabs=tabs, active="overview",
        analytics=normalized, snapshot=snapshot,
        window_reviews=snapshot.get("reviews", []),
        changes=changes or {},
        issue_cards=normalized.get("issue_cards", []),
        threshold=config.NEGATIVE_THRESHOLD,
        generated_at=(snapshot.get("snapshot_at") or "")[:19],
        version="v4",
    )


def render_monthly_v4(
    snapshot, analytics, executive, kpi_delta, category_benchmark,
    scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
    weekly_summaries, weekly_trend_config, safety_incidents, output_path,
):
    """V4 monthly renderer using shared partials."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      autoescape=select_autoescape(["html", "j2"]))
    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    js_text = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    normalized = normalize_deep_report_analytics(analytics or {})

    logical_date = snapshot.get("logical_date", "")
    from datetime import date as _date, timedelta as _td
    try:
        ld = _date.fromisoformat(logical_date[:10])
        prev_month = ld.replace(day=1) - _td(days=1)
        month_label = prev_month.strftime("%Y年%m月")
    except (ValueError, TypeError):
        month_label = logical_date[:7]

    charts = {}
    if weekly_trend_config:
        charts["weekly_trend"] = weekly_trend_config

    tabs = [
        {"id": "overview", "label": "高管视图"},
        {"id": "changes", "label": "本月变化",
         "badge": len(snapshot.get("reviews") or []) or None},
        {"id": "issues", "label": "问题生命周期"},
        {"id": "categories", "label": "品类对标"},
        {"id": "scorecard", "label": "产品计分卡"},
        {"id": "competitor", "label": "竞品对标"},
        {"id": "panorama", "label": "全景数据"},
    ]

    actions = ((executive or {}).get("actions") or [])[:3]

    return _write_template(
        env, "monthly.html.j2", output_path,
        page_title=f"QBU 网评监控 · 月报 {month_label}",
        css_text=css_text, js_text=js_text,
        brand="QBU 网评监控",
        kpi_items=[
            {"label": "健康", "value": normalized["kpis"].get("health_index", "—")},
            {"label": "差评", "value": normalized["kpis"].get("own_negative_review_rate_display", "—")},
            {"label": "高风险", "value": normalized["kpis"].get("high_risk_count", 0)},
        ],
        mode="monthly",
        kicker=f"MONTHLY EXECUTIVE BRIEF · {month_label}",
        meta=f"Run #{snapshot.get('run_id','?')}",
        title="QBU 网评监控 月度报告",
        headline=(executive or {}).get("stance_text") or "",
        health_index=normalized["kpis"].get("health_index"),
        confidence=normalized["kpis"].get("health_confidence", "no_data"),
        bullets=(executive or {}).get("bullets") or [],
        actions=actions,
        cards=normalized.get("kpi_cards", []),
        tabs=tabs, active="overview",
        analytics=normalized, snapshot=snapshot,
        window_reviews=snapshot.get("reviews", []),
        lifecycle_cards=lifecycle_cards,
        lifecycle_insufficient=lifecycle_insufficient,
        history_days=history_days,
        category_benchmark=category_benchmark,
        scorecard=scorecard,
        weekly_summaries=weekly_summaries,
        safety_incidents=safety_incidents,
        charts=charts,
        kpis=normalized["kpis"],
        kpi_delta=kpi_delta,
        threshold=config.NEGATIVE_THRESHOLD,
        generated_at=(snapshot.get("snapshot_at") or "")[:19],
        version="v4",
    )
