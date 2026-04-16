"""Immutable report snapshot helpers for workflow-based reporting."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from qbu_crawler import config, models
from qbu_crawler.server import report, report_analytics, report_html, report_llm

_logger = logging.getLogger(__name__)

_RECIPIENTS_FILE_PATH = os.path.join(
    os.path.dirname(__file__), "openclaw", "workspace", "config", "email_recipients.txt"
)


def _get_email_recipients() -> list[str]:
    """Unified email recipient loader.

    Priority: config.EMAIL_RECIPIENTS (env var) > openclaw file > empty list.
    """
    if config.EMAIL_RECIPIENTS:
        return list(config.EMAIL_RECIPIENTS)

    if os.path.exists(_RECIPIENTS_FILE_PATH):
        return report.load_email_recipients(_RECIPIENTS_FILE_PATH)
    return []


def should_send_quiet_email(run_id):
    """Determine whether to send a quiet-day email or skip.

    Returns (should_send: bool, digest_mode: str | None, consecutive: int).
    digest_mode is "weekly_digest" on day 7, 14, 21...

    Rules (spec 15.5):
    - First N quiet days (default 3): always send
    - Days N+1 to 6: skip
    - Day 7 (and 14, 21...): send as weekly digest
    - Days 8+: repeat 7-day cycle
    """
    threshold = int(os.getenv("REPORT_QUIET_EMAIL_DAYS", "3"))

    conn = models.get_conn()
    try:
        rows = conn.execute(
            """
            SELECT report_mode FROM workflow_runs
            WHERE workflow_type = 'daily' AND status = 'completed' AND id < ?
            ORDER BY id DESC LIMIT 30
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    consecutive = 0
    for row in rows:
        if row["report_mode"] == "quiet":
            consecutive += 1
        else:
            break

    if consecutive < threshold:
        return True, None, consecutive
    if (consecutive + 1) % 7 == 0:  # +1 because current run is also quiet
        return True, "weekly_digest", consecutive
    return False, None, consecutive


def load_previous_report_context(run_id):
    """Load most recent completed run's analytics and snapshot.

    Skips runs without analytics (quiet/change mode runs).
    Returns (analytics_dict, snapshot_dict) or (None, None).
    """
    prev_run = models.get_previous_completed_run(run_id)
    if not prev_run or not prev_run.get("analytics_path"):
        return None, None

    try:
        analytics = json.loads(Path(prev_run["analytics_path"]).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _logger.warning("Failed to load previous analytics: %s", e)
        return None, None

    snapshot = None
    if prev_run.get("snapshot_path"):
        try:
            snapshot = json.loads(Path(prev_run["snapshot_path"]).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            _logger.warning("Failed to load previous snapshot: %s", e)

    return analytics, snapshot


def _price_changed(a, b):
    """Compare prices with float tolerance."""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(float(a) - float(b)) >= 0.01


def detect_snapshot_changes(current_snapshot, previous_snapshot):
    """Compare two snapshots for price/stock/rating changes.

    Returns dict with: has_changes, price_changes, stock_changes,
    rating_changes, review_count_changes, new_products, removed_products.
    """
    changes = {
        "has_changes": False,
        "price_changes": [], "stock_changes": [], "rating_changes": [],
        "review_count_changes": [], "new_products": [], "removed_products": [],
    }

    if previous_snapshot is None:
        return changes

    prev_by_sku = {p["sku"]: p for p in previous_snapshot.get("products", [])}

    for product in current_snapshot.get("products", []):
        sku = product.get("sku", "")
        prev = prev_by_sku.get(sku)
        if not prev:
            changes["new_products"].append(product)
            changes["has_changes"] = True
            continue

        name = product.get("name", sku)

        if _price_changed(product.get("price"), prev.get("price")):
            changes["price_changes"].append({"sku": sku, "name": name, "old": prev.get("price"), "new": product.get("price")})
            changes["has_changes"] = True

        if product.get("stock_status") != prev.get("stock_status"):
            changes["stock_changes"].append({"sku": sku, "name": name, "old": prev.get("stock_status"), "new": product.get("stock_status")})
            changes["has_changes"] = True

        if product.get("rating") != prev.get("rating"):
            changes["rating_changes"].append({"sku": sku, "name": name, "old": prev.get("rating"), "new": product.get("rating")})
            changes["has_changes"] = True

        if product.get("review_count") != prev.get("review_count"):
            changes["review_count_changes"].append({"sku": sku, "name": name, "old": prev.get("review_count"), "new": product.get("review_count")})

    current_skus = {p.get("sku") for p in current_snapshot.get("products", [])}
    for sku, prev_product in prev_by_sku.items():
        if sku not in current_skus:
            changes["removed_products"].append(prev_product)
            changes["has_changes"] = True

    return changes


def determine_report_mode(snapshot, previous_snapshot, previous_analytics):
    """Central routing for report mode selection.

    Returns:
        mode: "full" | "change" | "quiet"
        context: dict with mode-specific metadata
    """
    has_reviews = bool(snapshot.get("reviews"))

    if has_reviews:
        changes = detect_snapshot_changes(snapshot, previous_snapshot)
        return "full", {"changes": changes}

    changes = detect_snapshot_changes(snapshot, previous_snapshot)
    if changes.get("has_changes"):
        return "change", {"changes": changes}

    return "quiet", {"previous_analytics": previous_analytics}


def compute_cluster_changes(current_clusters, previous_clusters, logical_date):
    """Diff two cluster lists to detect new, escalated, improving, and de-escalated clusters.

    Args:
        current_clusters: list of cluster dicts from current analytics
        previous_clusters: list of cluster dicts from previous analytics (may be None)
        logical_date: date object for "improving" detection

    Returns dict with keys: new, escalated, improving, de_escalated
    """
    from datetime import datetime, timedelta  # noqa: F401 (timedelta imported for completeness)

    prev_by_code = {c["label_code"]: c for c in (previous_clusters or [])}
    sev_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    changes = {"new": [], "escalated": [], "improving": [], "de_escalated": []}

    for cluster in current_clusters:
        code = cluster.get("label_code", "")
        prev = prev_by_code.get(code)

        if prev is None:
            changes["new"].append({
                "label_display": cluster.get("label_display", code),
                "review_count": cluster.get("review_count", 0),
                "affected_products": cluster.get("affected_products", []),
            })
            continue

        delta = cluster.get("review_count", 0) - prev.get("review_count", 0)
        cur_sev = sev_order.get(cluster.get("severity"), 0)
        prev_sev = sev_order.get(prev.get("severity"), 0)

        if delta > 0:
            changes["escalated"].append({
                "label_display": cluster.get("label_display", code),
                "delta": delta,
                "old_count": prev.get("review_count", 0),
                "new_count": cluster.get("review_count", 0),
                "severity": cluster.get("severity", "low"),
                "severity_changed": cur_sev > prev_sev,
            })
        elif cur_sev < prev_sev:
            changes["de_escalated"].append({
                "label_display": cluster.get("label_display", code),
                "old_severity": prev.get("severity"),
                "new_severity": cluster.get("severity"),
            })

    # Improving: clusters unchanged for 7+ days
    # TODO(14.9): When has_estimated_dates is true, this last_seen comparison
    # may be unreliable due to relative date parsing. A future enhancement
    # should pass the flag and fall back to scraped_at-based last_seen.
    if isinstance(logical_date, str):
        try:
            from datetime import datetime
            logical_date = datetime.strptime(logical_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            logical_date = None

    if logical_date:
        for cluster in current_clusters:
            code = cluster.get("label_code", "")
            prev = prev_by_code.get(code)
            if prev is None:
                continue
            last_seen = cluster.get("last_seen")
            if not last_seen:
                continue
            try:
                from datetime import datetime
                last_seen_date = datetime.strptime(last_seen, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            days_quiet = (logical_date - last_seen_date).days
            if days_quiet >= 7 and cluster.get("review_count", 0) == prev.get("review_count", 0):
                changes["improving"].append({
                    "label_display": cluster.get("label_display", code),
                    "days_quiet": days_quiet,
                })

    return changes


class FullReportGenerationError(RuntimeError):
    def __init__(self, message, *, analytics_path=None, excel_path=None, pdf_path=None):
        super().__init__(message)
        self.analytics_path = analytics_path
        self.excel_path = excel_path
        self.pdf_path = pdf_path  # Legacy — always None in V3


def freeze_report_snapshot(run_id: int, now: str | None = None) -> dict:
    """Freeze a workflow run into a single JSON snapshot artifact."""
    run = models.get_workflow_run(run_id)
    if run is None:
        raise ValueError(f"Workflow run {run_id} not found")

    existing_path = run.get("snapshot_path") or ""
    if existing_path and os.path.isfile(existing_path):
        snapshot = load_report_snapshot(existing_path)
        models.update_workflow_run(
            run_id,
            snapshot_at=snapshot.get("snapshot_at"),
            snapshot_path=existing_path,
            snapshot_hash=snapshot.get("snapshot_hash"),
            report_phase=run.get("report_phase") or "none",
        )
        return models.get_workflow_run(run_id) or run

    products, reviews = report.query_report_data(run["data_since"], until=run["data_until"])
    for item in reviews:
        item.setdefault("headline_cn", "")
        item.setdefault("body_cn", "")

    # ── Enrich reviews with review_analysis fields (LLM analysis data) ──
    _review_ids = [r["id"] for r in reviews if r.get("id")]
    if _review_ids:
        _enriched_map = {
            ea["id"]: ea
            for ea in models.get_reviews_with_analysis(review_ids=_review_ids)
        }
        for r in reviews:
            ea = _enriched_map.get(r.get("id"))
            if ea:
                for _key in ("sentiment", "analysis_features", "analysis_labels",
                             "analysis_insight_cn", "analysis_insight_en"):
                    _val = ea.get(_key)
                    if _val is not None:
                        r.setdefault(_key, _val)

    translated_count = sum(1 for item in reviews if item.get("translate_status") == "done")
    snapshot_at = now or config.now_shanghai().isoformat()
    snapshot = {
        "run_id": run["id"],
        "logical_date": run["logical_date"],
        "data_since": run["data_since"],
        "data_until": run["data_until"],
        "snapshot_at": snapshot_at,
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "untranslated_count": len(reviews) - translated_count,
    }

    # ── Dual-perspective: embed cumulative (all-time) data ──
    if config.REPORT_PERSPECTIVE == "dual":
        cum_products, cum_reviews = report.query_cumulative_data()
        cum_translated = sum(1 for r in cum_reviews if r.get("translate_status") == "done")
        snapshot["cumulative"] = {
            "products": cum_products,
            "reviews": cum_reviews,
            "products_count": len(cum_products),
            "reviews_count": len(cum_reviews),
            "translated_count": cum_translated,
            "untranslated_count": len(cum_reviews) - cum_translated,
        }

    # ── Hash excludes cumulative (Correction C) ──
    hash_payload = {k: v for k, v in snapshot.items() if k != "cumulative"}
    snapshot_hash = hashlib.sha1(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    snapshot["snapshot_hash"] = snapshot_hash

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    snapshot_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{run_id}-snapshot-{run['logical_date']}.json",
    )
    Path(snapshot_path).write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    return models.update_workflow_run(
        run_id,
        snapshot_at=snapshot_at,
        snapshot_path=snapshot_path,
        snapshot_hash=snapshot_hash,
    )


def load_report_snapshot(path: str) -> dict:
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    if "snapshot_hash" not in snapshot:
        raise ValueError(f"Snapshot at {path} is missing snapshot_hash")
    return snapshot


def build_fast_report(snapshot: dict) -> dict:
    return {
        "run_id": snapshot["run_id"],
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "products_count": snapshot["products_count"],
        "reviews_count": snapshot["reviews_count"],
        "translated_count": snapshot["translated_count"],
        "untranslated_count": snapshot["untranslated_count"],
    }


def _change_report_subject_prefix(changes):
    """Build dynamic subject prefix based on change types."""
    types = []
    if changes.get("price_changes"):
        types.append("价格")
    if changes.get("stock_changes"):
        types.append("库存")
    if changes.get("rating_changes"):
        types.append("评分")
    if changes.get("removed_products") or changes.get("new_products"):
        types.append("产品")
    if len(types) == 1:
        return f"[{types[0]}变动]"
    return "[数据变化]"


def _render_quiet_or_change_html(snapshot, prev_analytics, changes=None):
    """Render the quiet day or change report HTML using the quiet day template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("quiet_day_report.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    translate_stats = models.get_translate_stats()

    # Resolve last full report link from the previous completed run
    last_full_report_path = None
    run_id_for_lookup = snapshot.get("run_id", 0)
    prev_run = models.get_previous_completed_run(run_id_for_lookup)
    if prev_run:
        # Construct expected path from run_id (v3 HTML naming convention)
        expected = os.path.join(
            config.REPORT_DIR,
            f"workflow-run-{prev_run['id']}-full-report.html",
        )
        if Path(expected).exists():
            last_full_report_path = expected
            # If REPORT_HTML_PUBLIC_URL is configured, convert to a URL for the link
            if config.REPORT_HTML_PUBLIC_URL:
                last_full_report_path = (
                    f"{config.REPORT_HTML_PUBLIC_URL}/{Path(expected).name}"
                )

    html = template.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        previous_analytics=prev_analytics,
        translate_stats=translate_stats,
        last_full_report_path=last_full_report_path,
        css_text=css_text,
        threshold=config.NEGATIVE_THRESHOLD,
        changes=changes,
    )

    run_id = snapshot.get("run_id", 0)
    mode_tag = "change" if changes else "quiet"
    output_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{run_id}-{mode_tag}-report.html",
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    _logger.info("%s report HTML generated: %s", mode_tag, output_path)
    return output_path


def _send_mode_email(mode, snapshot, prev_analytics, changes=None,
                     report_url=None, analytics=None, risk_products=None,
                     consecutive_quiet=0):
    """Send email for any report mode using the appropriate template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )

    logical_date = snapshot.get("logical_date", "")
    kpis = (  # noqa: F841 — kept for future template use
        (prev_analytics or {}).get("kpis", {}) if mode != "full"
        else (analytics or {}).get("kpis", {})
    )

    # Build subject
    if mode == "full":
        subject = f"产品评论日报 {logical_date}"
    elif mode == "change":
        prefix = _change_report_subject_prefix(changes or {})
        subject = f"{prefix} 产品监控简报 {logical_date}"
    else:
        subject = f"[无变化] 产品监控简报 {logical_date}"

    # Render email template
    template_name = f"email_{mode}.html.j2"
    try:
        template = env.get_template(template_name)
    except Exception:
        _logger.warning("Email template %s not found, skipping", template_name)
        return {"success": False, "error": f"Template {template_name} not found", "recipients": []}

    try:
        body_html = template.render(
            logical_date=logical_date,
            snapshot=snapshot,
            analytics=analytics or prev_analytics or {},
            previous_analytics=prev_analytics,
            changes=changes,
            report_url=report_url,
            risk_products=risk_products or [],
            threshold=config.NEGATIVE_THRESHOLD,
            alert_level=(analytics or {}).get("alert_level", ("green", ""))[0] if analytics else "green",
            alert_text=(analytics or {}).get("alert_level", ("green", ""))[1] if analytics else "",
            report_copy=(analytics or {}).get("report_copy", {}),
            translate_stats=models.get_translate_stats() if mode == "quiet" else None,
            consecutive_quiet_days=consecutive_quiet,
        )
    except Exception as e:
        _logger.exception("Email template rendering failed for mode %s", mode)
        return {"success": False, "error": f"Template render error: {e}", "recipients": []}

    # Load recipients and send
    recipients = _get_email_recipients()

    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    try:
        result = report.send_email(
            recipients=recipients,
            subject=subject,
            body_text=subject,  # Plain text fallback
            body_html=body_html,
        )
        return result
    except Exception as e:
        _logger.warning("Email send failed: %s", e)
        return {"success": False, "error": str(e), "recipients": recipients}


def _generate_change_report(snapshot, send_email, prev_analytics, context):
    """Generate a change report (no new reviews, but price/stock/rating changed)."""
    run_id = snapshot.get("run_id", 0)
    changes = context.get("changes", {})

    # ── Cumulative analytics: compute from snapshot["cumulative"] when available ──
    cum_analytics = None
    analytics_path = None
    cumulative_computed = False
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": run_id,
                "logical_date": snapshot.get("logical_date", ""),
                "data_since": snapshot.get("data_since", ""),
                "data_until": snapshot.get("data_until", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                **snapshot["cumulative"],
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{run_id}-analytics-{snapshot.get('logical_date', 'unknown')}.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            cumulative_computed = True
            _logger.info("Change report: cumulative analytics computed and saved to %s", analytics_path)
        except Exception:
            _logger.exception("Change report: cumulative analytics computation failed")
            cum_analytics = None
            analytics_path = None

    # Use cumulative analytics when available, fall back to prev_analytics
    effective_analytics = cum_analytics or prev_analytics

    # Render quiet day HTML with change info
    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics, changes=changes)
    except Exception:
        _logger.exception("Change report HTML generation failed")

    # Send email
    email_result = None
    if send_email:
        try:
            email_result = _send_mode_email("change", snapshot, effective_analytics, changes=changes)
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    return {
        "mode": "change",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": analytics_path,
        "cumulative_computed": cumulative_computed,
        "email": email_result,
    }


def _generate_quiet_report(snapshot, send_email, prev_analytics):
    """Generate a quiet day report (no new reviews, no changes)."""
    run_id = snapshot.get("run_id", 0)

    # Check if we should send this quiet-day email (also returns consecutive count)
    should_send, digest_mode, consecutive = should_send_quiet_email(run_id)

    # ── Cumulative analytics: compute from snapshot["cumulative"] when available ──
    cum_analytics = None
    analytics_path = None
    cumulative_computed = False
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": run_id,
                "logical_date": snapshot.get("logical_date", ""),
                "data_since": snapshot.get("data_since", ""),
                "data_until": snapshot.get("data_until", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                **snapshot["cumulative"],
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{run_id}-analytics-{snapshot.get('logical_date', 'unknown')}.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            cumulative_computed = True
            _logger.info("Quiet report: cumulative analytics computed and saved to %s", analytics_path)
        except Exception:
            _logger.exception("Quiet report: cumulative analytics computation failed")
            cum_analytics = None
            analytics_path = None

    # Use cumulative analytics when available, fall back to prev_analytics
    effective_analytics = cum_analytics or prev_analytics

    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics)
    except Exception:
        _logger.exception("Quiet report HTML generation failed")

    email_result = None
    if send_email and should_send:
        try:
            email_result = _send_mode_email(
                "quiet", snapshot, effective_analytics,
                consecutive_quiet=consecutive,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}
    elif not should_send:
        email_result = {"success": True, "error": "Skipped (quiet day frequency)", "recipients": []}
        _logger.info("Quiet-day email skipped (consecutive quiet: reached skip window)")

    return {
        "mode": "quiet",
        "status": "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": analytics_path,
        "cumulative_computed": cumulative_computed,
        "email": email_result,
        "email_skipped": not should_send,
        "digest_mode": digest_mode,
    }


def generate_report_from_snapshot(snapshot, send_email=True, output_path=None):
    """Generate report for any mode (full/change/quiet).

    Replaces generate_full_report_from_snapshot with 3-mode routing.

    Returns dict with:
        mode: "full" | "change" | "quiet"
        status: "completed" | "completed_no_change"
        run_id, products_count, reviews_count
        html_path, excel_path, analytics_path (None for non-full modes)
        email: {success, error, recipients}
    """
    run_id = snapshot.get("run_id", 0)

    # Load previous context
    prev_analytics, prev_snapshot = load_previous_report_context(run_id)

    # Determine mode
    mode, context = determine_report_mode(snapshot, prev_snapshot, prev_analytics)

    # Write report_mode to workflow_runs
    try:
        models.update_workflow_run(run_id, report_mode=mode)
    except Exception:
        _logger.debug("Could not update report_mode for run %d", run_id, exc_info=True)

    _logger.info("Report mode: %s for run %d", mode, run_id)

    try:
        if mode == "full":
            # Entry point for 3-mode routing. workflows.py calls this function
            # instead of generate_full_report_from_snapshot directly.
            # Delegate to existing function (which handles its own email)
            result = generate_full_report_from_snapshot(
                snapshot, send_email=send_email, output_path=output_path,
            )
            result["mode"] = "full"
            # Full-mode email now uses email_full.html.j2 via _render_full_email_html()
            result.setdefault("status", "completed")
            return result
        elif mode == "change":
            return _generate_change_report(snapshot, send_email, prev_analytics, context)
        else:
            return _generate_quiet_report(snapshot, send_email, prev_analytics)
    except Exception as e:
        _logger.exception("Report generation failed for run %d", run_id)
        # Send failure notification
        try:
            recipients = _get_email_recipients()
            if recipients:
                report.send_email(
                    recipients=recipients,
                    subject=f"[报告失败] 产品监控 {snapshot.get('logical_date', '')}",
                    body_text=f"报告生成失败: {str(e)[:200]}\n请检查服务日志。",
                )
        except Exception:
            _logger.exception("Failed to send failure notification")
        raise


def _render_full_email_html(snapshot, analytics):
    """Render email_full.html.j2 for the full-mode email body."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics, _compute_alert_level

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    normalized = normalize_deep_report_analytics(analytics)
    alert = _compute_alert_level(normalized)
    alert_level = alert[0] if isinstance(alert, (list, tuple)) else "green"
    alert_text = alert[1] if isinstance(alert, (list, tuple)) else ""

    # Dual-perspective template variables (Correction E)
    cumulative_kpis = normalized.get("cumulative_kpis") or normalized.get("kpis", {})
    window = normalized.get("window", {})
    health_confidence = cumulative_kpis.get("health_confidence", "high")

    # F4 fix: load previous context ONCE, reuse for detect_snapshot_changes,
    # cluster_changes, and prev_analytics
    prev_analytics_ctx = None
    prev_snapshot = None
    run_id = snapshot.get("run_id", 0)
    if run_id:
        prev_analytics_ctx, prev_snapshot = load_previous_report_context(run_id)
    changes = detect_snapshot_changes(snapshot, prev_snapshot)

    # New review summary for email template
    window_reviews = window.get("new_reviews") or snapshot.get("reviews", [])
    own_new = [r for r in window_reviews if r.get("ownership") == "own"]
    comp_new = [r for r in window_reviews if r.get("ownership") == "competitor"]
    new_review_summary = {
        "own_count": len(own_new),
        "comp_count": len(comp_new),
        "own_negative": sum(
            1 for r in own_new if (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD
        ),
    }

    # Compute cluster changes for "today's changes" section
    prev_clusters = None
    if prev_analytics_ctx:
        prev_clusters = (prev_analytics_ctx.get("self") or {}).get("top_negative_clusters")
    cluster_changes = compute_cluster_changes(
        (normalized.get("self") or {}).get("top_negative_clusters", []),
        prev_clusters,
        snapshot.get("logical_date", ""),
    )

    # Build report URL
    report_url = ""
    report_html_public_url = getattr(config, "REPORT_HTML_PUBLIC_URL", "")
    if report_html_public_url:
        html_name = f"workflow-run-{run_id}-full-report.html"
        report_url = f"{report_html_public_url}/{html_name}"

    tpl = env.get_template("email_full.html.j2")
    return tpl.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        analytics=normalized,
        alert_level=alert_level,
        alert_text=alert_text,
        report_copy=normalized.get("report_copy") or analytics.get("report_copy") or {},
        risk_products=(normalized.get("self") or {}).get("risk_products", [])[:3],
        threshold=config.NEGATIVE_THRESHOLD,
        # New dual-perspective variables
        cumulative_kpis=cumulative_kpis,
        window=window,
        health_confidence=health_confidence,
        changes=cluster_changes,
        new_review_summary=new_review_summary,
        report_url=report_url,
    )


def generate_full_report_from_snapshot(
    snapshot: dict,
    send_email: bool = True,
    output_path: str | None = None,
) -> dict:
    if not snapshot.get("reviews") and not snapshot.get("cumulative"):
        return {"status": "completed_no_change", "reason": "No new reviews"}

    report_date = datetime.fromisoformat(
        snapshot.get("data_since") or f"{snapshot['logical_date']}T00:00:00+08:00"
    )
    if output_path is None:
        output_path = os.path.join(
            config.REPORT_DIR,
            f"workflow-run-{snapshot['run_id']}-full-report.xlsx",
        )

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    analytics_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{snapshot['run_id']}-analytics-{snapshot['logical_date']}.json",
    )
    html_output_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{snapshot['run_id']}-full-report.html",
    )
    excel_path = None
    pdf_path = None
    html_path = None

    try:
        # Correction F: sync labels on cumulative reviews (superset), call once
        if snapshot.get("cumulative"):
            _label_snapshot = {
                "reviews": snapshot["cumulative"]["reviews"],
            }
        else:
            _label_snapshot = snapshot
        synced_labels = report_analytics.sync_review_labels(_label_snapshot)

        # Use dual analytics when cumulative data exists
        if snapshot.get("cumulative"):
            analytics = report_analytics.build_dual_report_analytics(
                snapshot, synced_labels=synced_labels,
            )
        else:
            analytics = report_analytics.build_report_analytics(
                snapshot, synced_labels=synced_labels,
            )

        # Pre-normalize so LLM gets gap_analysis, enriched clusters, and top_symptoms
        from qbu_crawler.server.report_common import normalize_deep_report_analytics
        pre_normalized = normalize_deep_report_analytics(analytics)

        # LLM insights with full context (gap_analysis, top_symptoms, etc.)
        insights = report_llm.generate_report_insights(pre_normalized, snapshot=snapshot)
        analytics["report_copy"] = insights

        # Cluster deep analysis (top N clusters with ≥5 reviews)
        if config.REPORT_CLUSTER_ANALYSIS:
            from qbu_crawler.server.report_llm import analyze_cluster_deep
            top_clusters = analytics.get("self", {}).get("top_negative_clusters", [])
            for cluster in top_clusters[:config.REPORT_MAX_CLUSTER_ANALYSIS]:
                if cluster.get("review_count", 0) >= 5:
                    cluster_reviews = models.query_cluster_reviews(
                        label_code=cluster["label_code"],
                        ownership="own",
                        limit=30,
                    )
                    deep = analyze_cluster_deep(cluster, cluster_reviews)
                    if deep:
                        cluster["deep_analysis"] = deep

        # Attach window_review_ids so Excel can mark newly-added reviews (Correction H)
        if snapshot.get("cumulative"):
            analytics["window_review_ids"] = [
                r.get("id") for r in snapshot.get("reviews", []) if r.get("id")
            ]

        Path(analytics_path).write_text(
            json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

        # Excel uses cumulative reviews when available, with window ID marking
        if snapshot.get("cumulative"):
            _excel_products = snapshot["cumulative"]["products"]
            _excel_reviews = snapshot["cumulative"]["reviews"]
        else:
            _excel_products = snapshot["products"]
            _excel_reviews = snapshot["reviews"]
        excel_path = report.generate_excel(
            _excel_products,
            _excel_reviews,
            report_date=report_date,
            output_path=output_path,
            analytics=analytics,
        )

        # V3 HTML report (replaces V2 PDF + HTML pipeline)
        html_path = report_html.render_v3_html(snapshot, analytics, output_path=html_output_path)
    except Exception as exc:
        if isinstance(exc, FullReportGenerationError):
            raise
        raise FullReportGenerationError(
            str(exc),
            analytics_path=analytics_path if os.path.isfile(analytics_path) else None,
            excel_path=excel_path if excel_path and os.path.isfile(excel_path) else None,
            pdf_path=None,
        ) from exc

    email_result = None
    if send_email:
        subject, body = report.build_daily_deep_report_email(snapshot, analytics)
        # Render email_full.html.j2 (replaces legacy daily_report_email.html.j2)
        try:
            body_html = _render_full_email_html(snapshot, analytics)
        except Exception:
            _logger.warning("email_full.html.j2 render failed, falling back to legacy", exc_info=True)
            body_html = report.render_daily_email_html(snapshot, analytics)
        try:
            email_result = report.send_email(
                recipients=_get_email_recipients(),
                subject=subject,
                body_text=body,
                body_html=body_html,
                attachment_paths=[excel_path, html_path],
            )
        except Exception as exc:
            email_result = {"success": False, "error": str(exc), "recipients": 0}

    return {
        "run_id": snapshot["run_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "products_count": snapshot["products_count"],
        "reviews_count": snapshot["reviews_count"],
        "translated_count": snapshot["translated_count"],
        "untranslated_count": snapshot["untranslated_count"],
        "excel_path": excel_path,
        "analytics_path": analytics_path,
        "pdf_path": pdf_path,
        "html_path": html_path,
        "email": email_result,
    }
