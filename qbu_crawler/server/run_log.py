from pathlib import Path

from qbu_crawler import config


def get_run_log_path(run_id, logical_date):
    date_part = str(logical_date or config.now_shanghai().date())[:10].replace("-", "")
    return Path(config.DATA_DIR) / f"log-run-{run_id}-{date_part}.log"


def append_run_log(*, run_id, logical_date, event, lines=None, now=None):
    path = get_run_log_path(run_id, logical_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = now or config.now_shanghai().isoformat()
    content = [f"[{ts}] {event}"]
    for line in lines or []:
        content.append(f"- {line}")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(content))
        f.write("\n\n")
    return path


def _pct(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _task_summary_by_sku(task_rows):
    by_sku = {}
    for row in task_rows or []:
        result = row.get("result") or {}
        for item in result.get("product_summaries") or []:
            sku = item.get("sku")
            if sku:
                by_sku[str(sku)] = item
    return by_sku


def build_quality_log_lines(snapshot, quality, task_rows=None):
    products = snapshot.get("products") or []
    task_by_sku = _task_summary_by_sku(task_rows)
    lines = [
        f"scrape_completeness_ratio={_pct(quality.get('scrape_completeness_ratio'))}",
        f"low_coverage_count={quality.get('low_coverage_count') or len(quality.get('low_coverage_skus') or [])}",
        f"outbox_deadletter_count={quality.get('outbox_deadletter_count') or 0}",
        f"estimated_date_ratio={_pct(quality.get('estimated_date_ratio'))}",
    ]
    low_skus = {str(sku) for sku in quality.get("low_coverage_skus") or []}
    for product in products:
        sku = str(product.get("sku") or "")
        if not sku or sku not in low_skus:
            continue
        site_total = int(product.get("review_count") or 0)
        ingested = int(product.get("ingested_count") or 0)
        coverage = (ingested / site_total) if site_total else 1.0
        task_summary = task_by_sku.get(sku) or {}
        extraction = (task_summary.get("scrape_meta") or {}).get("review_extraction") or {}
        stop_reason = extraction.get("stop_reason") or "unknown"
        pages_seen = extraction.get("pages_seen")
        lines.append(
            "low_coverage_product "
            f"sku={sku} site={product.get('site') or ''} "
            f"name={product.get('name') or product.get('product_name') or ''} "
            f"ingested={ingested} site_total={site_total} coverage={coverage * 100:.1f}% "
            f"extracted={task_summary.get('extracted_review_count', 'n/a')} "
            f"saved={task_summary.get('saved_review_count', 'n/a')} "
            f"stop_reason={stop_reason} pages_seen={pages_seen if pages_seen is not None else 'n/a'}"
        )
    return lines


def build_ops_log_summary(quality, log_path):
    parts = [
        f"完整率 {_pct(quality.get('scrape_completeness_ratio'))}",
        f"低覆盖 SKU {quality.get('low_coverage_count') or len(quality.get('low_coverage_skus') or [])}",
        f"通知 deadletter {quality.get('outbox_deadletter_count') or 0}",
        f"估算日期 {_pct(quality.get('estimated_date_ratio'))}",
    ]
    return "；".join(parts) + f"\n运行日志：{log_path}"
