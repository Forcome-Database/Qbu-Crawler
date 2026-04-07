"""Immutable report snapshot helpers for workflow-based reporting."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from qbu_crawler import config, models
from qbu_crawler.server import report, report_analytics, report_llm, report_pdf


class FullReportGenerationError(RuntimeError):
    def __init__(self, message, *, analytics_path=None, excel_path=None, pdf_path=None):
        super().__init__(message)
        self.analytics_path = analytics_path
        self.excel_path = excel_path
        self.pdf_path = pdf_path


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
    snapshot_hash = hashlib.sha1(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
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


def generate_full_report_from_snapshot(
    snapshot: dict,
    send_email: bool = True,
    output_path: str | None = None,
) -> dict:
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
    pdf_output_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{snapshot['run_id']}-full-report.pdf",
    )
    excel_path = None
    pdf_path = None

    try:
        synced_labels = report_analytics.sync_review_labels(snapshot)
        analytics = report_analytics.build_report_analytics(snapshot, synced_labels=synced_labels)

        # New: LLM-generated insights (single call, replaces old 3-function chain)
        insights = report_llm.generate_report_insights(analytics)
        analytics["report_copy"] = insights

        Path(analytics_path).write_text(
            json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

        excel_path = report.generate_excel(
            snapshot["products"],
            snapshot["reviews"],
            report_date=report_date,
            output_path=output_path,
            analytics=analytics,
        )
        pdf_path = report_pdf.generate_pdf_report(snapshot, analytics, pdf_output_path)
    except Exception as exc:
        if isinstance(exc, FullReportGenerationError):
            raise
        raise FullReportGenerationError(
            str(exc),
            analytics_path=analytics_path if os.path.isfile(analytics_path) else None,
            excel_path=excel_path if excel_path and os.path.isfile(excel_path) else None,
            pdf_path=pdf_path if pdf_path and os.path.isfile(pdf_path) else None,
        ) from exc

    email_result = None
    if send_email:
        subject, body = report.build_daily_deep_report_email(snapshot, analytics)
        body_html = report.render_daily_email_html(snapshot, analytics)
        try:
            email_result = report.send_email(
                recipients=config.EMAIL_RECIPIENTS,
                subject=subject,
                body_text=body,
                body_html=body_html,
                attachment_paths=[excel_path, pdf_path],
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
        "email": email_result,
    }
