#!/usr/bin/env python3
"""Preview V2 report artifacts — generates HTML, Excel, and optionally PDF.

Usage:
    uv run python scripts/preview_v2_report.py [--db PATH] [--pdf] [--open]

Options:
    --db PATH   Path to products.db (default: user's DB)
    --pdf       Also generate PDF (requires Playwright: uv run playwright install chromium)
    --open      Auto-open HTML preview in browser
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Override DB path BEFORE importing models
DEFAULT_DB = r"C:\Users\leo\Desktop\新建文件夹 (5)\products.db"
OUTPUT_DIR = ROOT / "data" / "preview_v2"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Preview V2 report")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to products.db")
    parser.add_argument("--pdf", action="store_true", help="Generate PDF (needs Playwright)")
    parser.add_argument("--open", action="store_true", dest="auto_open", help="Open in browser")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(1)

    # Work on a copy to avoid modifying the original
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work_db = str(OUTPUT_DIR / "preview.db")
    shutil.copy2(db_path, work_db)
    print(f"Working copy: {work_db}")

    # Patch config to use our paths
    os.environ["QBU_DATA_DIR"] = str(OUTPUT_DIR)
    os.environ.setdefault("REPORT_DIR", str(OUTPUT_DIR))

    from qbu_crawler import config, models

    # Monkey-patch DB path
    models.DB_PATH = work_db
    config.DB_PATH = work_db
    config.REPORT_DIR = str(OUTPUT_DIR)

    # Initialize new tables (adds review_analysis IF NOT EXISTS)
    models.init_db()
    print("DB initialized with new tables.")

    # ── Build snapshot from DB data ──
    conn = sqlite3.connect(work_db)
    conn.row_factory = sqlite3.Row

    products = [dict(r) for r in conn.execute(
        "SELECT url, name, sku, price, stock_status, rating, review_count, "
        "scraped_at, site, ownership FROM products ORDER BY scraped_at DESC"
    ).fetchall()]

    reviews = [dict(r) for r in conn.execute(
        "SELECT r.id, r.product_id, p.name AS product_name, p.sku AS product_sku, "
        "r.author, r.headline, r.body, r.rating, r.date_published, r.images, "
        "p.ownership, r.headline_cn, r.body_cn, r.translate_status "
        "FROM reviews r JOIN products p ON r.product_id = p.id "
        "ORDER BY r.scraped_at DESC"
    ).fetchall()]

    # Enrich reviews with review_analysis fields (if available)
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

    # Check if review_analysis data exists
    analysis_count = conn.execute(
        "SELECT COUNT(*) FROM review_analysis"
    ).fetchone()[0]
    conn.close()

    print(f"Products: {len(products)}, Reviews: {len(reviews)}, Analyses: {analysis_count}")

    if analysis_count == 0:
        print("[!] No review_analysis data -- using rule-based fallback for labels.")
        print("  (Run 'qbu-crawler backfill-analysis' + TranslationWorker to populate)")

    snapshot = {
        "run_id": 999,
        "logical_date": datetime.now().strftime("%Y-%m-%d"),
        "data_since": "2026-01-01T00:00:00",
        "data_until": datetime.now().isoformat(),
        "snapshot_at": datetime.now().isoformat(),
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": sum(1 for r in reviews if r.get("translate_status") == "done"),
        "untranslated_count": sum(1 for r in reviews if r.get("translate_status") != "done"),
        "snapshot_hash": "preview-v2",
    }

    # ── Run analytics pipeline ──
    print("\n── Building analytics...")
    from qbu_crawler.server import report_analytics, report_common
    from qbu_crawler.server.report_llm import generate_report_insights

    analytics = report_analytics.build_report_analytics(snapshot)

    # Generate insights (fallback if no LLM configured)
    insights = generate_report_insights(analytics)
    analytics["report_copy"] = insights

    # Normalize
    normalized = report_common.normalize_deep_report_analytics(analytics)
    print(f"  Health Index: {normalized['kpis'].get('health_index', 'N/A')}")
    print(f"  Negative Reviews: {normalized['kpis'].get('negative_review_rows', 0)}")
    print(f"  Negative Rate: {normalized['kpis'].get('negative_review_rate_display', 'N/A')}")
    print(f"  Risk Products: {len(normalized.get('self', {}).get('risk_products', []))}")
    print(f"  Issue Clusters: {len(normalized.get('self', {}).get('top_negative_clusters', []))}")

    # ── Generate HTML preview (PDF template) ──
    print("\n── Rendering PDF HTML preview...")
    from qbu_crawler.server import report_pdf

    html = report_pdf.render_report_html(snapshot, analytics)
    html_path = OUTPUT_DIR / "preview_report.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  [OK] PDF HTML preview: {html_path}")

    # ── Generate Email HTML preview ──
    print("\n── Rendering Email HTML preview...")
    from qbu_crawler.server import report

    try:
        email_html = report.render_daily_email_html(snapshot, normalized)
        email_path = OUTPUT_DIR / "preview_email.html"
        email_path.write_text(email_html, encoding="utf-8")
        print(f"  [OK] Email HTML preview: {email_path}")
    except Exception as e:
        print(f"  [!] Email render failed: {e}")
        # Try building subject + body as fallback
        try:
            subject, body = report.build_daily_deep_report_email(snapshot, analytics)
            email_path = OUTPUT_DIR / "preview_email.txt"
            email_path.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")
            print(f"  [OK] Email text preview: {email_path}")
        except Exception as e2:
            print(f"  [FAIL] Email fallback also failed: {e2}")

    # ── Generate Excel ──
    print("\n── Generating Excel workbook...")
    try:
        excel_path = report.generate_excel(
            products=products,
            reviews=reviews,
            analytics=normalized,
        )
        print(f"  [OK] Excel: {excel_path}")
    except Exception as e:
        print(f"  [!] Analytical Excel failed: {e}, trying legacy...")
        excel_path = report.generate_excel(products=products, reviews=reviews)
        print(f"  [OK] Legacy Excel: {excel_path}")

    # ── Generate PDF (optional) ──
    if args.pdf:
        print("\n── Generating PDF...")
        try:
            pdf_path = str(OUTPUT_DIR / "preview_report.pdf")
            report_pdf.generate_pdf_report(snapshot, analytics, pdf_path)
            print(f"  [OK] PDF: {pdf_path}")
        except Exception as e:
            print(f"  [FAIL] PDF generation failed: {e}")
            print("     Run: uv run playwright install chromium")
    else:
        print("\n── Skipping PDF (use --pdf to generate)")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("Preview artifacts generated in:")
    print(f"  {OUTPUT_DIR}")
    print()
    print("Files:")
    for f in sorted(OUTPUT_DIR.glob("preview_*")):
        size = f.stat().st_size
        print(f"  {f.name:30s} {size:>10,} bytes")
    print()
    print("Open preview_report.html in browser to see PDF layout.")
    print("Open preview_email.html in browser to see email layout.")
    print("Open the .xlsx file in Excel to see the 6-sheet workbook.")

    if args.auto_open:
        webbrowser.open(str(html_path))


if __name__ == "__main__":
    main()
