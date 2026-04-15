"""V3 Report manual validation script.

Usage:
    uv run python scripts/test_v3_report.py full
    uv run python scripts/test_v3_report.py quiet
    uv run python scripts/test_v3_report.py change
    uv run python scripts/test_v3_report.py metrics
"""

import json
import os
import sys
from pathlib import Path

# Point to the desktop DB that matches the snapshot files
_DESKTOP_REPORT = "C:/Users/leo/Desktop/report"
if Path(_DESKTOP_REPORT, "data", "products.db").exists():
    os.environ["QBU_DATA_DIR"] = str(Path(_DESKTOP_REPORT, "data"))
    os.environ["REPORT_DIR"] = str(Path(_DESKTOP_REPORT, "reports"))

from qbu_crawler import config  # noqa: E402 — must import after env override

print(f"DB: {config.DB_PATH}")
print(f"Reports: {config.REPORT_DIR}")


def run_full():
    """Generate a Full Report from the Day 1 snapshot (710 reviews)."""
    from qbu_crawler.server.report_snapshot import generate_report_from_snapshot

    snapshot_path = "C:/Users/leo/Desktop/report/reports/workflow-run-1-snapshot-2026-04-08.json"
    if not Path(snapshot_path).exists():
        print(f"Snapshot not found: {snapshot_path}")
        return

    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    print(f"Loaded snapshot: {snapshot.get('products_count')} products, {snapshot.get('reviews_count')} reviews")
    print("Generating Full Report (this may take a minute)...")

    result = generate_report_from_snapshot(snapshot, send_email=False)

    print(f"\nMode: {result.get('mode')}")
    print(f"Status: {result.get('status')}")
    print(f"HTML: {result.get('html_path') or result.get('v3_html_path')}")
    print(f"Excel: {result.get('excel_path')}")
    print(f"Analytics: {result.get('analytics_path')}")

    html_path = result.get("html_path") or result.get("v3_html_path")
    if html_path and Path(html_path).exists():
        size_kb = Path(html_path).stat().st_size / 1024
        print(f"\nHTML report: {size_kb:.0f} KB")
        print(f"Open in browser: file:///{Path(html_path).as_posix()}")


def run_quiet():
    """Generate a Quiet Day Report from the Day 2 snapshot (0 reviews, no changes)."""
    from qbu_crawler.server.report_snapshot import generate_report_from_snapshot

    snapshot_path = "C:/Users/leo/Desktop/report/reports/workflow-run-2-snapshot-2026-04-09.json"
    if not Path(snapshot_path).exists():
        print(f"Snapshot not found: {snapshot_path}")
        return

    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    print(f"Loaded snapshot: {snapshot.get('reviews_count', 0)} reviews")
    print("Generating Quiet Day Report...")

    result = generate_report_from_snapshot(snapshot, send_email=False)

    print(f"\nMode: {result.get('mode')} (expected: quiet)")
    print(f"Status: {result.get('status')}")
    print(f"HTML: {result.get('html_path')}")
    print(f"Excel: {result.get('excel_path')} (expected: None)")


def run_change():
    """Simulate a Change Report by modifying a product price."""
    from qbu_crawler.server.report_snapshot import generate_report_from_snapshot

    snapshot_path = "C:/Users/leo/Desktop/report/reports/workflow-run-2-snapshot-2026-04-09.json"
    if not Path(snapshot_path).exists():
        print(f"Snapshot not found: {snapshot_path}")
        return

    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    # Simulate a $50 price drop on the first product
    if snapshot.get("products"):
        old_price = snapshot["products"][0].get("price", 0)
        snapshot["products"][0]["price"] = old_price - 50
        print(f"Simulated price change: {snapshot['products'][0]['name']}")
        print(f"  ${old_price} -> ${old_price - 50}")

    snapshot["run_id"] = 99  # Avoid conflict with real runs
    print("Generating Change Report...")

    result = generate_report_from_snapshot(snapshot, send_email=False)

    print(f"\nMode: {result.get('mode')} (expected: change)")
    print(f"Status: {result.get('status')}")
    print(f"HTML: {result.get('html_path')}")


def run_metrics():
    """Verify V3 algorithm outputs with known data."""
    from datetime import date

    from qbu_crawler.server.report_analytics import compute_cluster_severity
    from qbu_crawler.server.report_common import compute_health_index

    # Health Index (NPS-proxy)
    kpis = {"own_review_rows": 141, "own_positive_review_rows": 76, "own_negative_review_rows": 55}
    health = compute_health_index({"kpis": kpis})
    print(f"Health Index: {health} (expected ~57.4)")

    # Cluster Severity
    cluster = {
        "review_count": 36,
        "affected_product_count": 3,
        "review_dates": ["2026-03-20", "2026-04-01"] + ["2025-01-01"] * 34,
    }
    reviews = [{"headline": "metal shavings", "body": "dangerous rust"}]
    severity = compute_cluster_severity(cluster, reviews, date(2026, 4, 10))
    print(f"Cluster Severity: {severity} (expected: critical)")

    # Zero reviews
    health_zero = compute_health_index({"kpis": {"own_review_rows": 0}})
    print(f"Health (zero reviews): {health_zero} (expected: 50.0)")

    print("\nAll metric checks passed!" if health == 57.4 and severity == "critical" and health_zero == 50.0 else "\nSome checks FAILED!")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "metrics"
    tests = {"full": run_full, "quiet": run_quiet, "change": run_change, "metrics": run_metrics}

    if mode == "all":
        for name, fn in tests.items():
            print(f"\n{'='*60}")
            print(f"  {name.upper()}")
            print(f"{'='*60}\n")
            fn()
    elif mode in tests:
        tests[mode]()
    else:
        print(f"Usage: uv run python scripts/test_v3_report.py [{' | '.join(tests)} | all]")
