import json
from pathlib import Path

from qbu_crawler.server.report_html import _render_v3_html_string
from qbu_crawler.server.run_log import build_quality_log_lines
from qbu_crawler.server.scrape_quality import summarize_scrape_quality


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "report_replay" / "test10_minimal"


def _load_fixture():
    raw_snapshot = json.loads((FIXTURE_DIR / "snapshot.json").read_text(encoding="utf-8"))
    analytics = json.loads((FIXTURE_DIR / "analytics.json").read_text(encoding="utf-8"))
    tasks = json.loads((FIXTURE_DIR / "tasks.json").read_text(encoding="utf-8"))
    products = raw_snapshot["products"]
    reviews = []
    for idx in range(raw_snapshot["reviews_count"]):
        product = products[idx % len(products)]
        reviews.append({
            "id": idx + 1,
            "product_name": product["name"],
            "product_sku": product["sku"],
            "ownership": product["ownership"],
            "rating": 5 if idx % 6 else 2,
            "body": f"review {idx + 1}",
            "date_published": "2026-04-01",
            "translate_status": "done",
        })
    snapshot = {
        **raw_snapshot,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "reviews": reviews,
    }
    return snapshot, analytics, tasks


def test_test10_replay_keeps_business_report_and_ops_log_separate():
    snapshot, analytics, tasks = _load_fixture()

    html = _render_v3_html_string(snapshot, analytics)
    quality = summarize_scrape_quality(snapshot["products"], tasks=tasks)
    run_log = "\n".join(build_quality_log_lines(snapshot, quality, tasks))

    assert "当前截面：7 款产品 / 565 条评论" in html
    assert "影响 5 款 · 证据 30 条" in html
    assert "影响 0 款" not in html
    assert "cabelas-heavy-duty-20-lb-meat-mixer" not in html
    assert "expected_urls=8" in run_log
    assert "saved_products=7" in run_log
    assert "failed_url_count=1" in run_log
    assert "cabelas-heavy-duty-20-lb-meat-mixer" in run_log
    assert "KeyError: 'searchId'" in run_log
