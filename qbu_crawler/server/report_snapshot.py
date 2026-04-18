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


def _inject_meta(snapshot: dict, tier: str = "daily",
                 expected_days: int | None = None, actual_days: int | None = None,
                 window_start_dt: datetime | None = None) -> dict:
    """Add version metadata to snapshot for traceability.

    is_partial resolution (D015 #5 / F3 — true cold-start detection):
      1. If `window_start_dt` is provided and the earliest review scraped_at
         is later than it (or the reviews table is empty), the deployment is
         younger than the tier window → is_partial = True.
      2. Otherwise, fall back to the classic `actual_days < expected_days`
         calendar check.

    `earliest_review_scraped_at` is always recorded in `_meta` so downstream
    templates can show "data since N" in cold-start notices.
    """
    from qbu_crawler import __version__
    meta = {
        "schema_version": "3",
        "generator_version": __version__,
        "taxonomy_version": snapshot.get("taxonomy_version", "v1"),
        "report_tier": tier,
    }

    is_partial = False
    if expected_days is not None and actual_days is not None and actual_days < expected_days:
        is_partial = True
        meta["expected_days"] = expected_days
        meta["actual_days"] = actual_days

    # Cold-start detection: compare earliest review against the window start.
    earliest_review = models.get_earliest_review_scraped_at()
    if window_start_dt is not None:
        if earliest_review is None:
            # No reviews at all — the window is trivially partial.
            is_partial = True
        else:
            try:
                earliest_dt = datetime.fromisoformat(
                    str(earliest_review).replace(" ", "T")
                )
            except ValueError:
                earliest_dt = None
            if earliest_dt is not None:
                if earliest_dt.tzinfo is None:
                    # reviews.scraped_at is stored as naive Shanghai-local time.
                    earliest_dt = earliest_dt.replace(tzinfo=config.SHANGHAI_TZ)
                if earliest_dt > window_start_dt:
                    is_partial = True

    meta["earliest_review_scraped_at"] = earliest_review
    if is_partial:
        meta["is_partial"] = True
        # Preserve expected/actual only when the calendar check set them above
        # (meta already has them). Cold-start without calendar gap leaves them
        # off — downstream code already treats their absence as "unknown".

    snapshot["_meta"] = meta
    return snapshot


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
    digest_mode is always None — weekly_digest was retired in P008 Phase 3.

    Rules:
    - First N quiet days (default 3): always send
    - Days N+1 onwards: skip (real weekly report from WeeklySchedulerWorker covers weekly cadence)
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
    # P008 Phase 3: weekly_digest retired — real weekly report replaces it
    return False, None, consecutive


def should_send_daily_email(new_review_count: int, changes: dict) -> bool:
    """P008 Phase 2: Smart send — only email when there's something to report.

    HTML is always archived regardless of this decision.
    """
    if new_review_count > 0:
        return True
    if changes.get("price_changes") or changes.get("stock_changes") or changes.get("rating_changes"):
        return True
    return False


def load_previous_report_context(run_id, report_tier=None):
    """Load most recent completed run's analytics and snapshot.

    Skips runs without analytics (quiet/change mode runs).
    When *report_tier* is provided, only matches runs with that tier.
    Returns (analytics_dict, snapshot_dict) or (None, None).
    """
    prev_run = models.get_previous_completed_run(run_id, report_tier=report_tier)
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
        # D4 symmetry fix: also propagate is_partial + reviews_count on the
        # idempotent cache-hit path; otherwise the first freeze writes these
        # columns but any subsequent re-freeze (triggered by _advance_run,
        # snapshot replay, etc.) would leave them at whatever the row had
        # before, which on a fresh run is the DEFAULT 0.
        _meta = snapshot.get("_meta") or {}
        _is_partial_val = 1 if _meta.get("is_partial") else 0
        _reviews_count_val = int(snapshot.get("reviews_count") or 0)
        try:
            models.update_workflow_run(
                run_id,
                snapshot_at=snapshot.get("snapshot_at"),
                snapshot_path=existing_path,
                snapshot_hash=snapshot.get("snapshot_hash"),
                report_phase=run.get("report_phase") or "none",
                is_partial=_is_partial_val,
                reviews_count=_reviews_count_val,
            )
        except Exception:
            # Fallback if is_partial/reviews_count columns not yet migrated
            _logger.debug(
                "failed to propagate is_partial/reviews_count on cache-hit for run %s",
                run_id, exc_info=True,
            )
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
                             "analysis_insight_cn", "analysis_insight_en",
                             "impact_category", "failure_mode"):
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

    # P008 Phase 3 / D015 #5 (F3): Pass report_tier from run to _meta; inject
    # is_partial for both calendar gap AND true cold-start (deployment younger
    # than the tier window, detected via earliest review scraped_at).
    # Cold-start cue: weekly uses fixed 7 days; monthly uses the actual calendar
    # length of the previous month (data_since's month), so Feb (28/29d) /
    # Apr (30d) / Jul (31d) each compute expected correctly.
    run_tier = run.get("report_tier", "daily")
    _expected: int | None = None
    _actual: int | None = None
    _window_start_dt: datetime | None = None
    if run.get("data_since"):
        try:
            _window_start_dt = datetime.fromisoformat(run["data_since"])
            if _window_start_dt.tzinfo is None:
                _window_start_dt = _window_start_dt.replace(tzinfo=config.SHANGHAI_TZ)
        except (TypeError, ValueError):
            _window_start_dt = None
    if run_tier in ("weekly", "monthly") and run.get("data_since") and run.get("data_until"):
        try:
            _since_d = datetime.fromisoformat(run["data_since"]).date()
            _until_d = datetime.fromisoformat(run["data_until"]).date()
            _actual = (_until_d - _since_d).days
            if run_tier == "weekly":
                _expected = 7
            else:  # monthly
                import calendar
                _expected = calendar.monthrange(_since_d.year, _since_d.month)[1]
        except (TypeError, ValueError) as e:
            _logger.warning(
                "freeze_report_snapshot: could not parse data window for run %s (%s); "
                "skipping is_partial check", run_id, e,
            )
            _expected = None
            _actual = None

    _inject_meta(
        snapshot,
        tier=run_tier,
        expected_days=_expected,
        actual_days=_actual,
        window_start_dt=_window_start_dt,
    )

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    snapshot_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{run_id}-snapshot-{run['logical_date']}.json",
    )
    Path(snapshot_path).write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    # D4: propagate is_partial + reviews_count from snapshot._meta to workflow_runs
    # so downstream templates and queries can read it without re-parsing snapshot JSON.
    _meta = snapshot.get("_meta") or {}
    _is_partial_val = 1 if _meta.get("is_partial") else 0
    try:
        return models.update_workflow_run(
            run_id,
            snapshot_at=snapshot_at,
            snapshot_path=snapshot_path,
            snapshot_hash=snapshot_hash,
            is_partial=_is_partial_val,
            reviews_count=int(snapshot.get("reviews_count") or 0),
        )
    except Exception:
        _logger.debug(
            "failed to persist is_partial/reviews_count for run %s",
            run_id,
            exc_info=True,
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


def _render_quiet_or_change_html(snapshot, prev_analytics, changes=None, cumulative_kpis=None):
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
    prev_run = models.get_previous_completed_run(run_id_for_lookup, report_tier="daily")
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
        cumulative_kpis=cumulative_kpis,
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
            from qbu_crawler.server.report_common import normalize_deep_report_analytics
            cum_analytics = normalize_deep_report_analytics(cum_analytics)
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

    # P008: Extract cumulative KPIs for template (always-available, never N/A)
    cumulative_kpis = (cum_analytics or {}).get("kpis") or (prev_analytics or {}).get("kpis") or {}

    # Render quiet day HTML with change info
    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics, changes=changes, cumulative_kpis=cumulative_kpis)
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
        "cumulative_kpis": cumulative_kpis or None,
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
            from qbu_crawler.server.report_common import normalize_deep_report_analytics
            cum_analytics = normalize_deep_report_analytics(cum_analytics)
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

    # P008: Extract cumulative KPIs for template (always-available, never N/A)
    cumulative_kpis = (cum_analytics or {}).get("kpis") or (prev_analytics or {}).get("kpis") or {}

    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics, cumulative_kpis=cumulative_kpis)
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
        "cumulative_kpis": cumulative_kpis or None,
        "email": email_result,
        "email_skipped": not should_send,
        "digest_mode": digest_mode,
    }


def _generate_daily_briefing(snapshot, send_email=True):
    """P008 Phase 2: Generate three-block daily briefing.

    Always archives HTML. Only sends email when should_send_daily_email() is True.
    """
    run_id = snapshot.get("run_id", 0)
    logical_date = snapshot.get("logical_date", "")

    # Load previous context for change detection
    prev_analytics, prev_snapshot = load_previous_report_context(run_id, report_tier="daily")
    changes = detect_snapshot_changes(snapshot, prev_snapshot) if prev_snapshot else {}

    # Compute cumulative analytics
    cum_analytics = None
    analytics_path = None
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": run_id,
                "logical_date": logical_date,
                "data_since": snapshot.get("data_since", ""),
                "data_until": snapshot.get("data_until", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                **snapshot["cumulative"],
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            from qbu_crawler.server.report_common import normalize_deep_report_analytics
            cum_analytics = normalize_deep_report_analytics(cum_analytics)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"daily-{logical_date}-analytics.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except Exception:
            _logger.exception("Daily briefing: cumulative analytics failed")

    cumulative_kpis = (cum_analytics or {}).get("kpis", {})

    # Compute attention signals
    from qbu_crawler.server.report_common import (
        compute_attention_signals, review_attention_label, detect_safety_level,
    )
    window_reviews = snapshot.get("reviews", [])

    # Enrich changes with ownership from products
    product_ownership = {
        p.get("sku"): p.get("ownership")
        for p in (snapshot.get("cumulative", {}).get("products", []) or snapshot.get("products", []))
    }
    for change_type in ("rating_changes", "stock_changes", "price_changes"):
        for ch in changes.get(change_type, []):
            ch.setdefault("ownership", product_ownership.get(ch.get("sku"), ""))

    cumulative_clusters = (cum_analytics or {}).get("self", {}).get("top_negative_clusters", [])
    attention_signals = compute_attention_signals(
        window_reviews, changes, cumulative_clusters, logical_date=logical_date,
    )

    # Enrich reviews with attention labels
    enriched_reviews = []
    for r in window_reviews:
        r_copy = dict(r)
        text = f"{r.get('headline', '')} {r.get('body', '')}"
        level = detect_safety_level(text)
        r_copy["attention"] = review_attention_label(r, safety_level=level)
        enriched_reviews.append(r_copy)

    # Render HTML (always archive)
    html_path = None
    try:
        html_output = os.path.join(config.REPORT_DIR, f"daily-{logical_date}.html")
        html_path = report_html.render_daily_briefing(
            snapshot=snapshot,
            cumulative_kpis=cumulative_kpis,
            window_reviews=enriched_reviews,
            attention_signals=attention_signals,
            changes=changes,
            output_path=html_output,
        )
    except Exception:
        _logger.exception("Daily briefing HTML generation failed")

    # Smart send email
    email_result = None
    do_send = should_send_daily_email(len(window_reviews), changes)
    if send_email and do_send:
        try:
            email_result = _send_daily_briefing_email(
                snapshot, cumulative_kpis, enriched_reviews,
                attention_signals, changes,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}
    elif not do_send:
        email_result = {"success": True, "error": "Smart send: no content", "recipients": []}

    try:
        models.update_workflow_run(
            run_id,
            report_mode="standard",
            analytics_path=analytics_path,
        )
    except Exception:
        pass

    return {
        "mode": "daily_briefing",
        "status": "completed" if window_reviews or changes.get("has_changes") else "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": len(snapshot.get("products", [])),
        "reviews_count": len(window_reviews),
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": analytics_path,
        "cumulative_kpis": cumulative_kpis or None,
        "email": email_result,
        "email_skipped": not do_send,
    }


def _send_daily_briefing_email(snapshot, cumulative_kpis, window_reviews,
                               attention_signals, changes):
    """Send daily briefing email using email_daily.html.j2."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("email_daily.html.j2")
    logical_date = snapshot.get("logical_date", "")

    body_html = template.render(
        logical_date=logical_date,
        cumulative_kpis=cumulative_kpis,
        window_reviews=window_reviews,
        attention_signals=attention_signals,
        changes=changes,
        threshold=config.NEGATIVE_THRESHOLD,
    )

    recipients = _get_email_recipients()
    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    subject = f"产品评论日报 {logical_date}"
    has_safety = any(s.get("type") == "safety_keyword" for s in attention_signals)
    if has_safety:
        subject = f"[安全] {subject}"

    report.send_email(recipients=recipients, subject=subject, body_html=body_html)

    # P2-F2: safety 信号独立分发至 SAFETY 通道，避免告警被日常收件人淹没
    safety_extra = []
    if has_safety and getattr(config, "EMAIL_RECIPIENTS_SAFETY", None):
        safety_extra = [
            r for r in config.EMAIL_RECIPIENTS_SAFETY
            if r and r not in recipients
        ]
        if safety_extra:
            try:
                report.send_email(
                    recipients=safety_extra,
                    subject=subject,
                    body_html=body_html,
                )
            except Exception:
                _logger.warning(
                    "Safety channel send failed, recipients=%s", safety_extra, exc_info=True
                )
                safety_extra = []  # don't claim delivery on failure

    return {"success": True, "error": None, "recipients": recipients + safety_extra}


def _generate_weekly_report(snapshot, send_email=True):
    """P008 Phase 3: Generate weekly report — V3 HTML + Excel + summary email.

    Reuses generate_full_report_from_snapshot for V3 HTML and Excel,
    uses separate email template (summary card + link).
    """
    run_id = snapshot.get("run_id", 0)
    logical_date = snapshot.get("logical_date", "")

    # Generate full report (V3 HTML + Excel) using existing pipeline
    try:
        full_result = generate_full_report_from_snapshot(
            snapshot, send_email=False,  # We send our own email
            report_tier="weekly",
        )
    except Exception as exc:
        _logger.exception("Weekly report: full generation failed for run %d", run_id)
        raise

    # Guard: empty week (no data at all)
    if full_result.get("status") == "completed_no_change" and not full_result.get("html_path"):
        _logger.info("Weekly report: no data for run %d, skipping", run_id)
        return {
            "mode": "weekly_report",
            "status": "completed_no_change",
            "run_id": run_id,
            "snapshot_hash": snapshot.get("snapshot_hash", ""),
            "products_count": 0, "reviews_count": 0,
            "html_path": None, "excel_path": None, "analytics_path": None,
            "email": None,
        }

    # Compute label quality stats
    review_ids = [r.get("id") for r in
                  (snapshot.get("cumulative", {}).get("reviews") or snapshot.get("reviews", []))
                  if r.get("id")]
    label_quality = models.get_label_anomaly_stats(review_ids)

    # Enrich analytics with label_quality + dispersion + RCW sort
    analytics_path = full_result.get("analytics_path")
    if analytics_path and os.path.isfile(analytics_path):
        try:
            analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
            analytics["label_quality"] = label_quality

            # Enrich issue_cards with dispersion + lifecycle status
            from qbu_crawler.server.report_common import compute_dispersion, credibility_weight
            all_reviews = snapshot.get("cumulative", {}).get("reviews") or snapshot.get("reviews", [])
            own_skus = sum(1 for p in (snapshot.get("cumulative", {}).get("products") or [])
                          if p.get("ownership") == "own")
            for card in analytics.get("self", {}).get("issue_cards", []):
                label_code = card.get("label_code", "")
                if label_code:
                    dtype, skus = compute_dispersion(label_code, all_reviews, total_skus=own_skus or 1)
                    card["dispersion_type"] = dtype
                    card["dispersion_display"] = {"systemic": "系统性", "isolated": "个体", "uncertain": "待观察"}.get(dtype, dtype)

                # Simplified lifecycle status
                last_seen = card.get("last_seen")
                if last_seen:
                    from datetime import date as _date
                    try:
                        ls = _date.fromisoformat(last_seen[:10])
                        ld = _date.fromisoformat(logical_date[:10])
                        card["lifecycle_status"] = "active" if (ld - ls).days < 14 else "dormant"
                    except (ValueError, TypeError):
                        card["lifecycle_status"] = None
                else:
                    card["lifecycle_status"] = None

                # Sort example_reviews by RCW
                examples = card.get("example_reviews") or []
                if examples:
                    from datetime import date as _date
                    today = _date.fromisoformat(logical_date[:10]) if logical_date else _date.today()
                    examples.sort(key=lambda r: credibility_weight(r, today=today), reverse=True)
                    card["example_reviews"] = examples

            Path(analytics_path).write_text(
                json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except Exception:
            _logger.debug("Weekly report: failed to enrich analytics", exc_info=True)

    # Send weekly email (summary + link, not full body)
    email_result = None
    if send_email:
        try:
            email_result = _send_weekly_email(snapshot, full_result, logical_date)
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    try:
        models.update_workflow_run(
            run_id,
            report_mode="standard",
            analytics_path=analytics_path,
        )
    except Exception:
        pass

    return {
        "mode": "weekly_report",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": full_result.get("products_count", 0),
        "reviews_count": full_result.get("reviews_count", 0),
        "html_path": full_result.get("html_path"),
        "excel_path": full_result.get("excel_path"),
        "analytics_path": analytics_path,
        "email": email_result,
    }


def _send_weekly_email(snapshot, full_result, logical_date):
    """Send weekly report email: summary card + attachments."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )

    # Build report URL
    report_url = ""
    if config.REPORT_HTML_PUBLIC_URL and full_result.get("html_path"):
        html_name = Path(full_result["html_path"]).name
        report_url = f"{config.REPORT_HTML_PUBLIC_URL}/{html_name}"

    # Load analytics for KPI summary
    analytics = {}
    analytics_path = full_result.get("analytics_path")
    if analytics_path and os.path.isfile(analytics_path):
        try:
            analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
        except Exception:
            pass

    kpis = analytics.get("kpis", {})
    template = env.get_template("email_weekly.html.j2")
    body_html = template.render(
        logical_date=logical_date,
        kpis=kpis,
        report_url=report_url,
        reviews_count=full_result.get("reviews_count", 0),
        threshold=config.NEGATIVE_THRESHOLD,
    )

    recipients = _get_email_recipients()
    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    subject = f"产品评论周报 {logical_date}"
    attachments = []
    if full_result.get("html_path") and os.path.isfile(full_result["html_path"]):
        attachments.append(full_result["html_path"])
    if full_result.get("excel_path") and os.path.isfile(full_result["excel_path"]):
        attachments.append(full_result["excel_path"])

    report.send_email(
        recipients=recipients,
        subject=subject,
        body_text=f"QBU 周报 {logical_date}",
        body_html=body_html,
        attachment_paths=attachments if attachments else None,
    )
    return {"success": True, "error": None, "recipients": recipients}


def _generate_monthly_report(snapshot, send_email=True):
    """P008 Phase 4: Generate monthly report — V3-style HTML + 6-sheet Excel + executive email.

    Reuses generate_full_report_from_snapshot for V3 pipeline, then enriches with:
    - category benchmark (analytics_category)
    - SKU scorecard (analytics_scorecard)
    - issue lifecycle (analytics_lifecycle, full state machine)
    - executive summary (analytics_executive, LLM with fallback)
    Renders monthly_report.html.j2 and sends email_monthly.html.j2.
    """
    from datetime import date as _date

    from qbu_crawler.server import (
        analytics_category, analytics_executive, analytics_lifecycle, analytics_scorecard,
    )
    from qbu_crawler.server.report_common import load_category_map

    run_id = snapshot.get("run_id", 0)
    logical_date = snapshot.get("logical_date", "")

    # Generate full V3 report (reuse for charts, KPIs, Excel data)
    try:
        full_result = generate_full_report_from_snapshot(
            snapshot, send_email=False, report_tier="monthly",
        )
    except Exception:
        _logger.exception("Monthly report: full generation failed for run %d", run_id)
        raise

    # Note: no "completed_no_change" early-return here (unlike weekly). Monthly
    # must always produce a report because executive summary, category benchmark,
    # and scorecard are derived from cumulative data, which is never empty after
    # the first daily run.

    analytics_path = full_result.get("analytics_path")
    from qbu_crawler.server.report_common import load_analytics_envelope
    analytics = {}
    if analytics_path and os.path.isfile(analytics_path):
        envelope = load_analytics_envelope(analytics_path)
        # Flatten envelope for legacy consumers: prefer normalized
        analytics = {
            "kpis": envelope.get("kpis_normalized") or envelope.get("kpis_raw") or {},
            "self": envelope.get("self", {}),
            "competitor": envelope.get("competitor", {}),
            "report_copy": envelope.get("report_copy", {}),
            "kpi_cards": envelope.get("kpi_cards", []),
            "issue_cards": envelope.get("issue_cards", []),
        }
        # Preserve non-kpi top-level keys
        for k, v in envelope.items():
            if k not in analytics and k not in ("kpis_raw", "kpis_normalized", "_schema_version"):
                analytics[k] = v
        # P10 fix — surface mode_context so downstream consumers can read
        # is_partial / mode without walking nested keys
        _ctx = envelope.get("mode_context") or {}
        analytics["is_partial"] = _ctx.get("is_partial", False)
        analytics["mode"] = envelope.get("mode", "full")

    cumulative = snapshot.get("cumulative") or {}
    cum_products = cumulative.get("products") or []
    cum_reviews = cumulative.get("reviews") or []

    # ── Module 1: category benchmark ──
    category_map = load_category_map()
    category_benchmark = analytics_category.derive_category_benchmark(cum_products, category_map)

    # ── Module 2: SKU scorecard ──
    risk_products = (analytics.get("self") or {}).get("risk_products") or []
    safety_incidents = _load_safety_incidents_for_window(
        snapshot.get("data_since"), snapshot.get("data_until"),
    )
    previous_scorecards = _load_previous_scorecards(run_id)
    scorecard = analytics_scorecard.derive_product_scorecard(
        cum_products, risk_products, safety_incidents, previous_scorecards,
    )

    # ── Module 3: full lifecycle state machine (cold-start guarded) ──
    try:
        window_end = _date.fromisoformat(logical_date[:10])
    except (ValueError, TypeError):
        window_end = _date.today()

    history_days = _compute_history_span_days(cum_reviews, window_end)
    lifecycle_insufficient = history_days < 30
    if lifecycle_insufficient:
        lifecycle_results = {}
        lifecycle_cards = []
        _logger.info(
            "Monthly report: lifecycle suppressed, only %d days of history (<30)",
            history_days,
        )
    else:
        lifecycle_results = analytics_lifecycle.derive_all_lifecycles(
            cum_reviews, window_end=window_end,
        )
        lifecycle_cards = _build_lifecycle_cards(lifecycle_results, cum_reviews)

    # ── Module 4: LLM executive summary ──
    kpis = analytics.get("kpis") or {}
    prev_analytics, _ = load_previous_report_context(run_id, report_tier="monthly")
    prev_kpis = (prev_analytics or {}).get("kpis") or {}
    kpi_delta = {
        "health_index": _safe_delta(kpis.get("health_index"), prev_kpis.get("health_index")),
        "high_risk_count": _safe_delta(kpis.get("high_risk_count"), prev_kpis.get("high_risk_count")),
    }
    top_issues = ((analytics.get("self") or {}).get("top_negative_clusters") or [])[:3]
    executive_inputs = {
        "kpis": kpis,
        "kpi_delta": kpi_delta,
        "top_issues": top_issues,
        "category_benchmark": category_benchmark,
        "safety_incidents_count": len(safety_incidents),
        "safety_incidents": safety_incidents[:10],
    }
    executive = analytics_executive.generate_executive_summary(executive_inputs)

    # ── Weekly summaries (4-week recap) + Chart.js trend config ──
    weekly_summaries, weekly_trend_config = _build_weekly_recap(
        snapshot.get("data_since"), snapshot.get("data_until"),
    )

    # Persist enriched analytics
    if analytics_path:
        analytics["category_benchmark"] = category_benchmark
        analytics["scorecard"] = scorecard
        analytics["lifecycle"] = {
            f"{code}::{ownership}": data
            for (code, ownership), data in lifecycle_results.items()
        }
        analytics["executive"] = executive
        analytics["kpi_delta_monthly"] = kpi_delta
        Path(analytics_path).write_text(
            json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )

    # Render monthly HTML
    html_path = _render_monthly_html(
        snapshot, analytics, executive, kpi_delta, category_benchmark,
        scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
        weekly_summaries, weekly_trend_config, safety_incidents, full_result,
    )

    # Generate 6-sheet monthly Excel (evaluates category benchmark + scorecard into sheets 5+6)
    from qbu_crawler.server import report as report_mod
    monthly_excel_path = report_mod._generate_monthly_excel(
        products=cum_products,
        reviews=cum_reviews,
        analytics=analytics,
        category_benchmark=category_benchmark,
        scorecard=scorecard,
    )

    # Send email
    email_result = None
    if send_email:
        try:
            email_result = _send_monthly_email(
                snapshot, executive, kpi_delta, safety_incidents,
                html_path, monthly_excel_path,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    try:
        models.update_workflow_run(
            run_id, report_mode="standard", analytics_path=analytics_path,
        )
    except Exception:
        pass

    return {
        "mode": "monthly_report",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": full_result.get("products_count", 0),
        "reviews_count": full_result.get("reviews_count", 0),
        "html_path": html_path,
        "excel_path": monthly_excel_path,
        "analytics_path": analytics_path,
        "email": email_result,
    }


def _safe_delta(current, previous):
    try:
        if current is None or previous is None:
            return None
        return round(float(current) - float(previous), 2)
    except (TypeError, ValueError):
        return None


def _compute_history_span_days(reviews, window_end):
    """Days from earliest review scraped_at / date_published_parsed to window_end."""
    from datetime import date as _date, datetime as _dt
    earliest = None
    for r in reviews or []:
        for key in ("scraped_at", "date_published_parsed", "date_published"):
            val = r.get(key)
            if not val:
                continue
            if isinstance(val, (_date, _dt)):
                d = val.date() if isinstance(val, _dt) else val
            else:
                try:
                    d = _date.fromisoformat(str(val)[:10])
                except (ValueError, TypeError):
                    continue
            if earliest is None or d < earliest:
                earliest = d
            break
    if earliest is None:
        return 0
    return max(0, (window_end - earliest).days)


def _load_safety_incidents_for_window(data_since, data_until):
    if not data_since or not data_until:
        return []
    conn = None
    try:
        conn = models.get_conn()
        rows = conn.execute(
            "SELECT * FROM safety_incidents WHERE detected_at >= ? AND detected_at < ?"
            " ORDER BY detected_at DESC",
            (data_since, data_until),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        _logger.debug("safety_incidents query failed", exc_info=True)
        return []
    finally:
        if conn is not None:
            conn.close()


def _load_previous_scorecards(current_run_id):
    """Load scorecards from the previous monthly run (for trend computation)."""
    prev_run = models.get_previous_completed_run(current_run_id, report_tier="monthly")
    if not prev_run or not prev_run.get("analytics_path"):
        return {}
    try:
        prev_analytics = json.loads(Path(prev_run["analytics_path"]).read_text(encoding="utf-8"))
        prev_cards = (prev_analytics.get("scorecard") or {}).get("scorecards") or []
        return {
            c["sku"]: {"risk_score": c.get("risk_score"), "light": c.get("light")}
            for c in prev_cards if c.get("sku")
        }
    except Exception:
        return {}


def _build_lifecycle_cards(lifecycle_results, all_reviews):
    """Convert lifecycle state-machine output into renderable issue cards (own only).

    Each card also attaches a ``competitor_reference`` block — negative reviews
    from competitors for the same label_code — so the monthly report can show
    cross-ownership context.
    """
    from datetime import date as _date
    from qbu_crawler.server.report_common import credibility_weight, _label_display

    cards = []
    today = _date.today()

    def _reviews_matching(label_code, ownership):
        out = []
        for r in all_reviews:
            if r.get("ownership") != ownership:
                continue
            raw = r.get("analysis_labels") or "[]"
            try:
                labels = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                labels = []
            if any(lb.get("code") == label_code and lb.get("polarity") == "negative" for lb in labels):
                out.append(r)
        out.sort(key=lambda r: credibility_weight(r, today=today), reverse=True)
        return out

    for (label_code, ownership), data in lifecycle_results.items():
        if ownership != "own":
            continue

        own_examples = _reviews_matching(label_code, "own")
        comp_examples = _reviews_matching(label_code, "competitor")

        cards.append({
            "label_code": label_code,
            "label_display": _label_display(label_code),
            "state": data["state"],
            "history": data["history"],
            "review_count": data["review_count"],
            "first_seen": data["first_seen"],
            "last_seen": data["last_seen"],
            "example_reviews": own_examples[:3],
            "competitor_reference": {
                "review_count": len(comp_examples),
                "top_examples": comp_examples[:3],
            },
        })

    state_priority = {"recurrent": 0, "active": 1, "receding": 2, "dormant": 3}
    cards.sort(key=lambda c: (state_priority.get(c["state"], 9), -c["review_count"]))
    return cards


def _build_weekly_recap(data_since, data_until):
    """Return (summaries, Chart.js line-config) for completed weekly runs in the window.

    Uses partial-overlap SQL filter so weeks straddling month boundaries are included.
    """
    if not data_since or not data_until:
        return [], None
    conn = None
    try:
        conn = models.get_conn()
        rows = conn.execute(
            "SELECT logical_date, analytics_path FROM workflow_runs"
            " WHERE report_tier = 'weekly' AND status = 'completed'"
            "   AND data_since < ? AND data_until > ?"
            " ORDER BY logical_date ASC",
            (data_until, data_since),
        ).fetchall()
    except Exception:
        return [], None
    finally:
        if conn is not None:
            conn.close()

    summaries = []
    labels = []
    health_series = []
    neg_series = []
    for idx, row in enumerate(rows, start=1):
        week_label = f"第{idx}周"
        labels.append(week_label)
        try:
            wkly = json.loads(Path(row["analytics_path"]).read_text(encoding="utf-8"))
            kpis = wkly.get("kpis") or {}
            health = kpis.get("health_index")
            neg_rate_display = kpis.get("own_negative_review_rate_display") or "—"
            health_series.append(float(health) if health is not None else None)
            neg = kpis.get("own_negative_review_rate")
            neg_series.append(round(float(neg) * 100, 2) if neg is not None else None)
            summaries.append(
                f"{week_label}（{row['logical_date']}）：健康 {health if health is not None else '—'} · "
                f"差评率 {neg_rate_display} · 高风险 {kpis.get('high_risk_count', 0)}"
            )
        except Exception:
            summaries.append(f"{week_label}（{row['logical_date']}）：数据缺失")
            health_series.append(None)
            neg_series.append(None)

    if not labels or all(v is None for v in health_series):
        return summaries, None

    trend_config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "健康指数",
                    "data": health_series,
                    "borderColor": "#93543f",
                    "backgroundColor": "rgba(147,84,63,0.12)",
                    "tension": 0.3,
                    "fill": True,
                    "spanGaps": True,
                    "yAxisID": "y",
                },
                {
                    "label": "差评率 (%)",
                    "data": neg_series,
                    "borderColor": "#b7633f",
                    "backgroundColor": "transparent",
                    "tension": 0.3,
                    "spanGaps": True,
                    "yAxisID": "y1",
                },
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "scales": {
                "y":  {"type": "linear", "position": "left",  "title": {"display": True, "text": "健康指数"}},
                "y1": {"type": "linear", "position": "right", "grid": {"drawOnChartArea": False},
                        "title": {"display": True, "text": "差评率 (%)"}},
            },
            "plugins": {"legend": {"position": "bottom"}},
        },
    }
    return summaries, trend_config


def _render_monthly_html(snapshot, analytics, executive, kpi_delta, category_benchmark,
                         scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
                         weekly_summaries, weekly_trend_config, safety_incidents,
                         full_result):
    """Render monthly_report.html.j2 to disk, return path."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("monthly_report.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"

    from datetime import date as _date, timedelta as _td
    logical_date = snapshot.get("logical_date", "")
    # Month label like "2026年04月" — month-1st logical_date refers to previous month
    try:
        ld = _date.fromisoformat(logical_date[:10])
        prev_month = ld.replace(day=1) - _td(days=1)  # last day of previous month
        month_label = prev_month.strftime("%Y年%m月")
    except (ValueError, TypeError):
        month_label = logical_date[:7]

    charts = dict(analytics.get("charts") or {})
    if weekly_trend_config is not None:
        charts["weekly_trend"] = weekly_trend_config

    html = template.render(
        logical_date=logical_date,
        month_label=month_label,
        executive=executive,
        kpis=analytics.get("kpis") or {},
        kpi_delta=kpi_delta,
        category_benchmark=category_benchmark,
        scorecard=scorecard,
        lifecycle_cards=lifecycle_cards,
        lifecycle_insufficient=lifecycle_insufficient,
        history_days=history_days,
        weekly_summaries=weekly_summaries,
        snapshot=snapshot,
        analytics=analytics,
        charts=charts,
        alert_level=analytics.get("alert_level") or "green",
        alert_text=analytics.get("alert_text") or "",
        safety_incidents=safety_incidents,
        css_text=css_path.read_text(encoding="utf-8") if css_path.exists() else "",
        js_text=js_path.read_text(encoding="utf-8") if js_path.exists() else "",
        threshold=config.NEGATIVE_THRESHOLD,
    )

    out_path = Path(config.REPORT_DIR) / f"monthly-{month_label.replace('年', '-').replace('月', '')}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


def _send_monthly_email(snapshot, executive, kpi_delta, safety_incidents, html_path, excel_path):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_monthly.html.j2")

    logical_date = snapshot.get("logical_date", "")
    try:
        from datetime import date as _date, timedelta as _td
        ld = _date.fromisoformat(logical_date[:10])
        prev_month = ld - _td(days=1)
        month_label = prev_month.strftime("%Y年%m月")
    except (ValueError, TypeError):
        month_label = logical_date[:7]

    report_url = ""
    if config.REPORT_HTML_PUBLIC_URL and html_path:
        report_url = f"{config.REPORT_HTML_PUBLIC_URL}/{Path(html_path).name}"

    body_html = template.render(
        month_label=month_label,
        executive=executive,
        kpis=snapshot.get("cumulative_kpis") or {},
        kpi_delta=kpi_delta,
        safety_incidents=safety_incidents,
        report_url=report_url,
    )

    recipients = config.EMAIL_RECIPIENTS_EXEC or _get_email_recipients()
    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    subject = f"产品评论月报 {month_label}"
    attachments = []
    if html_path and os.path.isfile(html_path):
        attachments.append(html_path)
    if excel_path and os.path.isfile(excel_path):
        attachments.append(excel_path)

    report.send_email(
        recipients=recipients,
        subject=subject,
        body_text=f"QBU 月报 {month_label}",
        body_html=body_html,
        attachment_paths=attachments if attachments else None,
    )
    return {"success": True, "error": None, "recipients": recipients}


def generate_report_from_snapshot(snapshot, send_email=True, output_path=None):
    """Generate report for any mode (full/change/quiet).

    Replaces generate_full_report_from_snapshot with 3-mode routing.

    Returns dict with:
        mode: "full" | "change" | "quiet" | "daily_briefing"
        status: "completed" | "completed_no_change"
        run_id, products_count, reviews_count
        html_path, excel_path, analytics_path (None for non-full modes)
        email: {success, error, recipients}
    """
    run_id = snapshot.get("run_id", 0)

    # P008 Phase 2: Check report_tier — new daily runs use three-block pipeline
    run_tier = None
    if run_id:
        conn = None
        try:
            conn = models.get_conn()
            row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
            run_tier = row["report_tier"] if row else None
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()

    if run_tier == "daily":
        return _generate_daily_briefing(snapshot, send_email)
    elif run_tier == "weekly":
        return _generate_weekly_report(snapshot, send_email)
    elif run_tier == "monthly":
        return _generate_monthly_report(snapshot, send_email)

    # Load previous context (legacy path: run_tier is None → treat as daily)
    prev_analytics, prev_snapshot = load_previous_report_context(run_id, report_tier="daily")

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
            # Delegate to existing function (which handles its own email).
            # Legacy path: run_tier is None → treat as daily (matches branch above).
            result = generate_full_report_from_snapshot(
                snapshot, send_email=send_email, output_path=output_path,
                report_tier="daily",
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


def _render_full_email_html(snapshot, analytics, *, report_tier: str | None = None):
    """Render email_full.html.j2 for the full-mode email body.

    Args:
        snapshot: report snapshot dict
        analytics: analytics dict
        report_tier: explicit tier ("daily" / "weekly" / "monthly") for
            baseline lookup. Falls back to ``snapshot["_meta"]["report_tier"]``
            for backward compatibility (D015 #3 follow-up). If both absent,
            logs WARNING and defaults to ``"daily"``.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics, _compute_alert_level

    # D015 #3 follow-up: resolve report_tier with priority:
    # explicit param > snapshot._meta.report_tier > WARNING + "daily"
    if report_tier is None:
        report_tier = (snapshot.get("_meta") or {}).get("report_tier")
    if report_tier is None:
        _logger.warning(
            "_render_full_email_html: report_tier missing "
            "(explicit param + snapshot._meta both absent); "
            "run_id=%s logical_date=%s; defaulting to 'daily'",
            snapshot.get("run_id"),
            snapshot.get("logical_date"),
        )
        report_tier = "daily"

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
        prev_analytics_ctx, prev_snapshot = load_previous_report_context(run_id, report_tier=report_tier)
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

    # Merge snapshot changes (price/stock/rating) with cluster changes (escalated/new/improving)
    merged_changes = {**cluster_changes}
    merged_changes["price_changes"] = changes.get("price_changes", [])
    merged_changes["stock_changes"] = changes.get("stock_changes", [])
    merged_changes["rating_changes"] = changes.get("rating_changes", [])
    merged_changes["has_changes"] = changes.get("has_changes", False)

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
        changes=merged_changes,
        new_review_summary=new_review_summary,
        report_url=report_url,
    )


def generate_full_report_from_snapshot(
    snapshot: dict,
    send_email: bool = True,
    output_path: str | None = None,
    *,
    report_tier: str | None = None,
) -> dict:
    """Generate full-mode report (analytics + Excel + V3 HTML + email).

    Args:
        snapshot: report snapshot dict
        send_email: whether to send the summary email
        output_path: optional explicit Excel output path
        report_tier: explicit tier ("daily" / "weekly" / "monthly") for
            baseline lookup. Falls back to ``snapshot["_meta"]["report_tier"]``
            for backward compatibility (D015 #3 follow-up). If both absent,
            logs WARNING and defaults to ``"daily"``.
    """
    # D015 #3 follow-up: resolve report_tier with priority:
    # explicit param > snapshot._meta.report_tier > WARNING + "daily"
    if report_tier is None:
        report_tier = (snapshot.get("_meta") or {}).get("report_tier")
    if report_tier is None:
        _logger.warning(
            "generate_full_report_from_snapshot: report_tier missing "
            "(explicit param + snapshot._meta both absent); "
            "run_id=%s logical_date=%s; defaulting to 'daily'",
            snapshot.get("run_id"),
            snapshot.get("logical_date"),
        )
        report_tier = "daily"

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

        from qbu_crawler.server.report_common import build_analytics_envelope
        envelope = build_analytics_envelope(
            analytics,
            mode=(snapshot.get("_meta") or {}).get("report_mode", "full"),
            mode_context={
                "report_tier": report_tier,
                "is_partial": (snapshot.get("_meta") or {}).get("is_partial", False),
            },
        )
        Path(analytics_path).write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2),
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
        # P008: compute snapshot changes for Tab 2
        try:
            _prev_a, _prev_s = load_previous_report_context(
                snapshot.get("run_id", 0), report_tier=report_tier,
            )
            _changes = detect_snapshot_changes(snapshot, _prev_s) if _prev_s else None
        except Exception:
            _changes = None
        html_path = report_html.render_v3_html(snapshot, analytics, output_path=html_output_path, changes=_changes)
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
            body_html = _render_full_email_html(
                snapshot, analytics, report_tier=report_tier,
            )
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
