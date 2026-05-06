import json
import sqlite3

from qbu_crawler import config, models


def _conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _minimal_snapshot():
    return {
        "run_id": 14,
        "logical_date": "2026-05-06",
        "data_since": "2026-05-06T00:00:00+08:00",
        "data_until": "2026-05-07T00:00:00+08:00",
        "snapshot_hash": "hash",
        "products": [],
        "reviews": [{"id": 1, "ownership": "competitor", "rating": 1, "date_published": "a hour ago"}],
    }


def test_email_full_labels_cumulative_and_window_counts():
    from qbu_crawler.server.report import render_email_full

    html = render_email_full(
        snapshot=_minimal_snapshot(),
        analytics={
            "kpis": {
                "health_index": 94.9,
                "own_product_count": 28,
                "competitor_product_count": 13,
                "ingested_review_rows": 2594,
                "own_review_rows": 1624,
                "own_positive_review_rows": 1400,
                "own_negative_review_rate": 0.1,
            },
            "change_digest": {"summary": {"ingested_review_count": 1}},
            "window": {"reviews_count": 1},
            "self": {"product_status": [], "risk_products": [], "top_negative_clusters": []},
            "report_copy": {"executive_bullets": [], "improvement_priorities": []},
        },
    )

    assert "累计 自有 28 款 / 竞品 13 款 / 共 2594 条评论" in html
    assert "本期新增 1 条评论" in html
    assert "本期 自有 28 款 / 竞品 13 款 / 共 2594 条评论" not in html


def test_v3_overview_labels_window_ingested_as_current_window():
    from qbu_crawler.server.report_html import render_attachment_html

    html = render_attachment_html(
        snapshot=_minimal_snapshot(),
        analytics={
            "mode": "incremental",
            "report_semantics": "incremental",
            "kpis": {
                "health_index": 90,
                "own_review_rows": 10,
                "competitor_review_rows": 20,
                "ingested_review_rows": 30,
            },
            "change_digest": {
                "view_state": "active",
                "summary": {"ingested_review_count": 1, "fresh_review_count": 1},
                "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
                "product_changes": {},
                "review_signals": {"fresh_negative_reviews": [], "fresh_competitor_positive_reviews": []},
                "warnings": {},
                "empty_state": {"enabled": True},
                "immediate_attention": {
                    "own_new_negative_reviews": [],
                    "own_rating_drops": [],
                    "own_stock_alerts": [],
                },
                "trend_changes": {"new_issues": [], "escalated_issues": [], "improving_issues": []},
                "competitive_opportunities": {
                    "competitor_new_negative_reviews": [],
                    "competitor_new_positive_reviews": [],
                },
            },
            "self": {"risk_products": [], "top_negative_clusters": [], "product_status": []},
            "competitor": {"gap_analysis": [], "benchmark_examples": []},
            "report_copy": {"executive_bullets": [], "improvement_priorities": []},
            "trend_digest": {},
        },
    )

    assert "本期入库评论" in html
    assert "基线样本评论" not in html


def test_v3_panorama_uses_cumulative_reviews_when_available():
    from qbu_crawler.server.report_html import render_attachment_html

    snapshot = _minimal_snapshot()
    snapshot["products"] = [{"name": "Window Product", "sku": "WINDOW", "ownership": "competitor"}]
    snapshot["reviews"] = [{
        "id": 1,
        "ownership": "competitor",
        "product_name": "Window Product",
        "rating": 1,
        "headline": "Window only",
        "body": "Window body",
        "date_published": "a hour ago",
    }]
    snapshot["cumulative"] = {
        "products": [{"name": "Cumulative Product", "sku": "CUM", "ownership": "own"}],
        "reviews": [
            {
                "id": 1,
                "ownership": "competitor",
                "product_name": "Window Product",
                "rating": 1,
                "headline": "Window only",
                "body": "Window body",
                "date_published": "a hour ago",
            },
            {
                "id": 2,
                "ownership": "own",
                "product_name": "Cumulative Product",
                "rating": 5,
                "headline": "Historical cumulative",
                "body": "Historical body",
                "date_published_parsed": "2026-05-01",
            },
        ],
    }
    html = render_attachment_html(
        snapshot=snapshot,
        analytics={
            "mode": "incremental",
            "report_semantics": "incremental",
            "kpis": {"health_index": 90},
            "change_digest": {"summary": {"ingested_review_count": 1}},
            "self": {"risk_products": [], "top_negative_clusters": [], "product_status": []},
            "competitor": {"gap_analysis": [], "benchmark_examples": []},
            "report_copy": {"executive_bullets": [], "improvement_priorities": []},
            "trend_digest": {},
        },
    )

    assert 'data-tab="panorama"' in html
    assert "全景数据 <span class=\"tab-badge\">2</span>" in html
    assert "2 条评论" in html
    assert 'data-review-id="1"' in html
    assert 'data-review-id="2"' in html
    assert '<option value="Cumulative Product">Cumulative Product</option>' in html


def test_parse_date_published_supports_hour_and_minute_relative():
    assert models._parse_date_published("a hour ago", scraped_at="2026-05-06 00:19:00") == "2026-05-05"
    assert models._parse_date_published("12 hours ago", scraped_at="2026-05-06 12:19:00") == "2026-05-06"
    assert models._parse_date_published("5 minutes ago", scraped_at="2026-05-06 00:19:00") == "2026-05-06"


def test_scrape_quality_uses_extracted_reviews_not_saved_reviews():
    from qbu_crawler.server.scrape_quality import summarize_scrape_quality

    products = [
        {"sku": "SKU-1", "url": "https://example.com/1", "review_count": 100, "ratings_only_count": 20, "ingested_count": 0},
        {"sku": "SKU-2", "url": "https://example.com/2", "review_count": 10, "ratings_only_count": 0, "ingested_count": 0},
    ]
    tasks = [{
        "params": {"urls": ["https://example.com/1", "https://example.com/2"]},
        "result": {
            "saved_urls": ["https://example.com/1", "https://example.com/2"],
            "product_summaries": [
                {
                    "url": "https://example.com/1",
                    "sku": "SKU-1",
                    "site_review_count": 100,
                    "ratings_only_count": 20,
                    "extracted_review_count": 80,
                    "saved_review_count": 0,
                },
                {
                    "url": "https://example.com/2",
                    "sku": "SKU-2",
                    "site_review_count": 10,
                    "ratings_only_count": 0,
                    "extracted_review_count": 0,
                    "saved_review_count": 0,
                    "scrape_meta": {"review_extraction": {"stop_reason": "no_shadow_root"}},
                },
            ],
        },
    }]

    quality = summarize_scrape_quality(products, tasks=tasks, low_coverage_threshold=0.6)

    assert quality["scrape_completeness_ratio"] == 0.8889
    assert quality["zero_scrape_skus"] == ["SKU-2"]
    assert quality["low_coverage_skus"] == ["SKU-2"]


def test_save_product_preserves_existing_ratings_only_when_missing(tmp_path, monkeypatch):
    db_file = str(tmp_path / "ratings-only.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _conn(db_file))
    models.init_db()

    product = {
        "url": "https://example.com/p",
        "site": "meatyourmaker",
        "name": "Product",
        "sku": "SKU-1",
        "price": 10,
        "stock_status": "in_stock",
        "review_count": 93,
        "rating": 4.4,
        "ownership": "own",
        "ratings_only_count": 59,
    }
    models.save_product(product)
    second = dict(product)
    second.pop("ratings_only_count")
    models.save_product(second)

    conn = _conn(db_file)
    try:
        row = conn.execute("SELECT ratings_only_count FROM products WHERE url = ?", (product["url"],)).fetchone()
    finally:
        conn.close()

    assert row["ratings_only_count"] == 59


def test_quiet_report_uses_synced_analysis_labels_for_risk(tmp_path, monkeypatch):
    from qbu_crawler.server import report_analytics, report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "should_send_quiet_email", lambda *_a, **_k: (True, None, 0))
    monkeypatch.setattr(report_snapshot, "_render_quiet_or_change_html", lambda *a, **k: str(tmp_path / "quiet.html"))
    monkeypatch.setattr(report_snapshot, "_send_mode_email", lambda *a, **k: {"success": True, "recipients": []})
    monkeypatch.setattr(report_snapshot, "_build_trend_history_for_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(report_analytics.models, "replace_review_issue_labels", lambda *a, **k: None)

    captured = {}
    original = report_analytics.build_report_analytics

    def spy_build(snapshot, **kwargs):
        captured["synced_labels"] = kwargs.get("synced_labels")
        return original(snapshot, **kwargs)

    monkeypatch.setattr(report_analytics, "build_report_analytics", spy_build)

    snapshot = {
        "run_id": 14,
        "logical_date": "2026-05-06",
        "data_since": "2026-05-06T00:00:00+08:00",
        "data_until": "2026-05-07T00:00:00+08:00",
        "snapshot_hash": "hash",
        "cumulative": {
            "products": [{
                "url": "https://example.com/p",
                "site": "basspro",
                "name": "Product",
                "sku": "SKU-1",
                "ownership": "own",
                "review_count": 10,
                "ratings_only_count": 0,
            }],
            "reviews": [{
                "id": 1,
                "product_name": "Product",
                "product_sku": "SKU-1",
                "ownership": "own",
                "rating": 1,
                "headline": "breaks",
                "body": "breaks fast",
                "analysis_labels": json.dumps([{
                    "code": "quality_stability",
                    "polarity": "negative",
                    "severity": "high",
                    "confidence": 0.9,
                }]),
            }],
            "products_count": 1,
            "reviews_count": 1,
        },
    }

    report_snapshot._generate_quiet_report(snapshot, send_email=False, prev_analytics=None)

    assert captured["synced_labels"]
    assert captured["synced_labels"][1][0]["label_code"] == "quality_stability"


def test_quiet_report_records_generated_artifacts(tmp_path, monkeypatch):
    from qbu_crawler.server import report_analytics, report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "should_send_quiet_email", lambda *_a, **_k: (True, None, 0))
    monkeypatch.setattr(report_snapshot, "_build_trend_history_for_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(report_analytics.models, "replace_review_issue_labels", lambda *a, **k: None)

    html_path = tmp_path / "quiet.html"
    monkeypatch.setattr(report_snapshot, "_render_quiet_or_change_html", lambda *a, **k: str(html_path))

    recorded = []
    monkeypatch.setattr(report_snapshot, "_record_artifact_safe", lambda run_id, kind, path, template_version=None: recorded.append((run_id, kind, path)))

    snapshot = {
        "run_id": 14,
        "logical_date": "2026-05-06",
        "data_since": "2026-05-06T00:00:00+08:00",
        "data_until": "2026-05-07T00:00:00+08:00",
        "snapshot_hash": "hash",
        "cumulative": {"products": [], "reviews": [], "products_count": 0, "reviews_count": 0},
    }

    report_snapshot._generate_quiet_report(snapshot, send_email=False, prev_analytics=None)

    kinds = {item[1] for item in recorded}
    assert {"analytics", "html_attachment"} <= kinds
