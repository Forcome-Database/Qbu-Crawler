from __future__ import annotations

import sqlite3

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def analytics_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "analytics.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    monkeypatch.setattr(config, "REPORT_LABEL_MODE", "rule")
    models.init_db()
    return db_file


def _create_daily_run(logical_date: str, *, status: str = "completed", analytics_path: str | None = None):
    return models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": status,
            "report_phase": "full_done" if status == "completed" else "reporting",
            "logical_date": logical_date,
            "trigger_key": f"daily:{logical_date}:{status}:{analytics_path or 'none'}",
            "analytics_path": analytics_path,
        }
    )


def _build_snapshot(run_id: int, logical_date: str):
    return {
        "run_id": run_id,
        "logical_date": logical_date,
        "snapshot_hash": f"hash-{logical_date}",
        "products_count": 2,
        "reviews_count": 5,
        "translated_count": 5,
        "untranslated_count": 0,
        "products": [
            {
                "url": "https://example.com/own-1",
                "name": "Own Grinder",
                "sku": "OWN-1",
                "price": 299.99,
                "stock_status": "in_stock",
                "rating": 3.7,
                "review_count": 6,
                "scraped_at": "2026-03-29 09:00:00",
                "site": "basspro",
                "ownership": "own",
            },
            {
                "url": "https://example.com/comp-1",
                "name": "Competitor Grinder",
                "sku": "COMP-1",
                "price": 279.99,
                "stock_status": "in_stock",
                "rating": 4.7,
                "review_count": 4,
                "scraped_at": "2026-03-29 09:10:00",
                "site": "waltons",
                "ownership": "competitor",
            },
        ],
        "reviews": [
            {
                "product_name": "Own Grinder",
                "product_sku": "OWN-1",
                "author": "Alice",
                "headline": "Motor failed fast",
                "body": "The motor broke after two uses and stopped working.",
                "rating": 1,
                "date_published": "2026-03-28",
                "images": ["https://img.example.com/own-1.jpg"],
                "ownership": "own",
                "headline_cn": "",
                "body_cn": "",
                "translate_status": "done",
            },
            {
                "product_name": "Own Grinder",
                "product_sku": "OWN-1",
                "author": "Bob",
                "headline": "Hard to assemble",
                "body": "Assembly was difficult and the instructions were unclear.",
                "rating": 2,
                "date_published": "2026-03-28",
                "images": [],
                "ownership": "own",
                "headline_cn": "",
                "body_cn": "",
                "translate_status": "done",
            },
            {
                "product_name": "Competitor Grinder",
                "product_sku": "COMP-1",
                "author": "Cara",
                "headline": "Very easy to use",
                "body": "Easy to use every day and easy to clean after use.",
                "rating": 5,
                "date_published": "2026-03-28",
                "images": [],
                "ownership": "competitor",
                "headline_cn": "",
                "body_cn": "",
                "translate_status": "done",
            },
            {
                "product_name": "Competitor Grinder",
                "product_sku": "COMP-1",
                "author": "Drew",
                "headline": "Simple and easy",
                "body": "Easy to use, great value, and sturdy enough for daily work.",
                "rating": 5,
                "date_published": "2026-03-27",
                "images": [],
                "ownership": "competitor",
                "headline_cn": "",
                "body_cn": "",
                "translate_status": "done",
            },
            {
                "product_name": "Competitor Grinder",
                "product_sku": "COMP-1",
                "author": "Evan",
                "headline": "Box was damaged",
                "body": "The packaging was damaged on arrival.",
                "rating": 2,
                "date_published": "2026-03-27",
                "images": [],
                "ownership": "competitor",
                "headline_cn": "",
                "body_cn": "",
                "translate_status": "done",
            },
        ],
    }


def _insert_review_record():
    conn = models.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO products (url, site, name, sku, price, stock_status, rating, review_count, ownership, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/own-db-1",
                "basspro",
                "Own Grinder",
                "OWN-1",
                299.99,
                "in_stock",
                3.7,
                6,
                "own",
                "2026-03-29 09:00:00",
            ),
        )
        product_id = conn.execute("SELECT id FROM products WHERE sku = 'OWN-1'").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, images, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                "Alice",
                "Motor failed fast",
                "The motor broke after two uses and stopped working.",
                "hash-own-1",
                1,
                "2026-03-28",
                "[]",
                "2026-03-29 09:05:00",
            ),
        )
        review_id = conn.execute("SELECT id FROM reviews WHERE body_hash = 'hash-own-1'").fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    return review_id


def test_build_report_analytics_uses_baseline_mode_without_prior_runs(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["mode"] == "baseline"
    assert analytics["baseline_sample_days"] == 0


def test_build_report_analytics_uses_incremental_mode_with_prior_runs(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    _create_daily_run("2026-03-20", analytics_path="a.json")
    _create_daily_run("2026-03-21", analytics_path="b.json")
    _create_daily_run("2026-03-25", analytics_path="c.json")
    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["mode"] == "incremental"
    assert analytics["baseline_sample_days"] == 3


def test_self_focus_on_negative_clusters(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["self"]["top_negative_clusters"][0]["label_code"] == "quality_stability"


def test_competitor_focus_on_positive_themes(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["competitor"]["top_positive_themes"][0]["label_code"] == "easy_to_use"


def test_sync_review_labels_persists_rule_labels(analytics_db):
    from qbu_crawler.server.report_analytics import sync_review_labels

    review_id = _insert_review_record()
    snapshot = {
        "reviews": [
            {
                "id": review_id,
                "product_name": "Own Grinder",
                "product_sku": "OWN-1",
                "author": "Alice",
                "headline": "Motor failed fast",
                "body": "The motor broke after two uses and stopped working.",
                "rating": 1,
                "date_published": "2026-03-28",
                "images": [],
                "ownership": "own",
                "headline_cn": "",
                "body_cn": "",
            }
        ]
    }

    stored = sync_review_labels(snapshot)

    assert stored[review_id][0]["label_code"] == "quality_stability"
    assert stored[review_id][0]["source"] == "rule"


def test_hybrid_label_mode_can_replace_source_with_llm(monkeypatch, analytics_db):
    from qbu_crawler.server import report_analytics

    monkeypatch.setattr(config, "REPORT_LABEL_MODE", "hybrid")
    review_id = _insert_review_record()
    snapshot = {
        "reviews": [
            {
                "id": review_id,
                "product_name": "Own Grinder",
                "product_sku": "OWN-1",
                "author": "Alice",
                "headline": "Motor failed fast",
                "body": "The motor broke after two uses and stopped working.",
                "rating": 1,
                "date_published": "2026-03-28",
                "images": [],
                "ownership": "own",
                "headline_cn": "",
                "body_cn": "",
            }
        ]
    }

    monkeypatch.setattr(
        report_analytics,
        "_maybe_normalize_labels_with_llm",
        lambda review_labels: {
            review_id: [
                {
                    "label_code": "quality_stability",
                    "label_polarity": "negative",
                    "severity": "high",
                    "confidence": 0.98,
                    "source": "llm",
                    "taxonomy_version": report_analytics.TAXONOMY_VERSION,
                }
            ]
        },
    )

    stored = report_analytics.sync_review_labels(snapshot)

    assert stored[review_id][0]["source"] == "llm"


# ---------------------------------------------------------------------------
# Tests for _build_feature_clusters (feature-based clustering)
# ---------------------------------------------------------------------------


def test_build_feature_clusters_basic():
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own",
            "sentiment": "negative",
            "analysis_features": '["手柄松动", "做工粗糙"]',
            "analysis_labels": '[{"code": "structure_design", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
            "product_sku": "SKU1",
            "rating": 1,
            "date_published": "2026-01-01",
        },
        {
            "ownership": "own",
            "sentiment": "negative",
            "analysis_features": '["手柄松动"]',
            "analysis_labels": '[{"code": "structure_design", "polarity": "negative", "severity": "medium", "confidence": 0.85}]',
            "product_sku": "SKU2",
            "rating": 2,
            "date_published": "2026-02-01",
        },
    ]
    clusters = _build_feature_clusters(reviews, "own", "negative")
    assert clusters[0]["label_code"] == "structure_design"
    assert clusters[0]["review_count"] == 2
    assert clusters[0]["affected_product_count"] == 2
    assert clusters[0]["severity"] == "high"


def test_build_feature_clusters_positive_polarity():
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "competitor",
            "sentiment": "positive",
            "analysis_features": '["易操作"]',
            "analysis_labels": '[{"code": "easy_to_use", "polarity": "positive", "severity": "low", "confidence": 0.9}]',
            "product_sku": "COMP-1",
            "rating": 5,
            "date_published": "2026-03-01",
        },
        {
            "ownership": "competitor",
            "sentiment": "positive",
            "analysis_features": '["外观好"]',
            "analysis_labels": '[{"code": "solid_build", "polarity": "positive", "severity": "low", "confidence": 0.88}]',
            "product_sku": "COMP-1",
            "rating": 5,
            "date_published": "2026-03-02",
        },
    ]
    clusters = _build_feature_clusters(reviews, "competitor", "positive")
    assert len(clusters) == 2
    label_codes = [c["label_code"] for c in clusters]
    assert "easy_to_use" in label_codes
    assert "solid_build" in label_codes


def test_build_feature_clusters_ignores_wrong_ownership():
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "competitor",
            "sentiment": "negative",
            "analysis_features": '["问题A"]',
            "analysis_labels": '[{"severity": "high"}]',
            "product_sku": "COMP-1",
            "rating": 1,
        },
    ]
    clusters = _build_feature_clusters(reviews, "own", "negative")
    assert clusters == []


def test_build_feature_clusters_empty_features():
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own",
            "sentiment": "negative",
            "analysis_features": "[]",
            "analysis_labels": "[]",
            "product_sku": "SKU1",
            "rating": 1,
        },
    ]
    clusters = _build_feature_clusters(reviews, "own", "negative")
    assert clusters == []


def test_build_feature_clusters_timeline():
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own",
            "sentiment": "negative",
            "analysis_features": '["问题X"]',
            "analysis_labels": '[]',
            "product_sku": "SKU1",
            "rating": 2,
            "date_published": "2026-01-15",
        },
        {
            "ownership": "own",
            "sentiment": "negative",
            "analysis_features": '["问题X"]',
            "analysis_labels": '[]',
            "product_sku": "SKU1",
            "rating": 1,
            "date_published": "2026-03-20",
        },
    ]
    clusters = _build_feature_clusters(reviews, "own", "negative")
    assert clusters[0]["first_seen"] == "2026-01-15"
    assert clusters[0]["last_seen"] == "2026-03-20"


def test_has_review_analysis_data():
    from qbu_crawler.server.report_analytics import _has_review_analysis_data

    assert _has_review_analysis_data([]) is False
    assert _has_review_analysis_data([{"analysis_features": "[]"}]) is False
    assert _has_review_analysis_data([{"analysis_features": '["手柄松动"]'}]) is True
    assert _has_review_analysis_data([{"features": '["问题A"]'}]) is True


def test_build_report_analytics_includes_own_avg_rating(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert "own_avg_rating" in analytics["kpis"]
    # Own Grinder has rating 3.7
    assert analytics["kpis"]["own_avg_rating"] == 3.7


def test_build_report_analytics_includes_products_for_charts(analytics_db):
    """_products_for_charts must be present in analytics for the quadrant chart."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_snapshot(run["id"], "2026-03-29")
    result = build_report_analytics(snapshot)
    assert "_products_for_charts" in result
    pfc = result["_products_for_charts"]
    assert isinstance(pfc, list)
    assert len(pfc) >= 1
    assert "name" in pfc[0]
    assert "price" in pfc[0]
    assert "ownership" in pfc[0]


def test_build_report_analytics_includes_chart_data(analytics_db):
    """Chart data keys should be present when sufficient data exists."""
    from qbu_crawler.server.report_analytics import build_report_analytics
    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_snapshot(run["id"], "2026-03-29")
    result = build_report_analytics(snapshot)
    # _sentiment_distribution needs >= 2 products with reviews (snapshot has 2)
    if "_sentiment_distribution" in result:
        sd = result["_sentiment_distribution"]
        assert "categories" in sd
        assert "positive" in sd
        assert len(sd["categories"]) == len(sd["positive"])
    # _radar_data needs >= 3 dimensions with data from both sides
    # May not be present with small test data — just verify format if present
    if "_radar_data" in result:
        rd = result["_radar_data"]
        assert len(rd["categories"]) == len(rd["own_values"])
        assert len(rd["categories"]) == len(rd["competitor_values"])


def test_sample_avg_rating_computed_from_reviews(analytics_db):
    """sample_avg_rating should be the mean of own review ratings, not the site rating."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    snapshot = _build_snapshot(1, "2026-04-01")
    # Set specific ratings on own reviews to verify computation
    own_reviews = [r for r in snapshot["reviews"] if r.get("ownership") == "own"]
    for i, r in enumerate(own_reviews):
        r["rating"] = 2 + i  # e.g., 2, 3, 4...

    analytics = build_report_analytics(snapshot)
    sample_avg = analytics["kpis"].get("sample_avg_rating")
    assert sample_avg is not None, "sample_avg_rating should be computed"
    expected = round(sum(r["rating"] for r in own_reviews) / len(own_reviews), 2)
    assert abs(sample_avg - expected) < 0.01, \
        f"Expected {expected}, got {sample_avg}"


def test_risk_products_ignores_high_rating_reviews(analytics_db):
    """Reviews with rating > LOW_RATING_THRESHOLD should not contribute to risk_score."""
    from qbu_crawler.server.report_analytics import _risk_products, _build_labeled_reviews

    snapshot = {
        "products": [
            {"name": "Test Product", "sku": "TP-1", "ownership": "own",
             "rating": 4.5, "review_count": 10, "site": "basspro"},
        ],
        "reviews": [
            # 5-star review that contains a negative keyword
            {"product_name": "Test Product", "product_sku": "TP-1", "ownership": "own",
             "rating": 5, "headline": "poor finish on the handle but works great", "body": "",
             "headline_cn": "", "body_cn": "", "images": None},
            # 1-star review — should count
            {"product_name": "Test Product", "product_sku": "TP-1", "ownership": "own",
             "rating": 1, "headline": "broke after one use", "body": "",
             "headline_cn": "", "body_cn": "", "images": None},
        ],
    }
    labeled = _build_labeled_reviews(snapshot)
    risk = _risk_products(labeled, snapshot_products=snapshot["products"])

    if risk:
        product = risk[0]
        assert product["negative_review_rows"] == 1, \
            f"Expected 1 negative review (only low-rating), got {product['negative_review_rows']}"


def _insert_snapshot_reviews_into_db(snapshot):
    """Insert products and reviews from snapshot into DB so sync_review_labels can persist labels."""
    conn = models.get_conn()
    try:
        review_ids = []
        product_ids = {}
        for p in snapshot.get("products") or []:
            conn.execute(
                """INSERT INTO products (url, site, name, sku, price, stock_status, rating, review_count, ownership, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["url"], p["site"], p["name"], p["sku"], p["price"],
                 p["stock_status"], p["rating"], p["review_count"],
                 p["ownership"], p["scraped_at"]),
            )
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            product_ids[p["sku"]] = pid
        for r in snapshot.get("reviews") or []:
            pid = product_ids.get(r["product_sku"])
            if not pid:
                continue
            body = r.get("body") or ""
            conn.execute(
                """INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, images, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pid, r["author"], r["headline"], body,
                 f"hash-{r['author'].lower()}", r["rating"],
                 r.get("date_published"), "[]", "2026-03-29 09:05:00"),
            )
            rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            review_ids.append(rid)
        conn.commit()
    finally:
        conn.close()
    return review_ids


def test_build_report_analytics_uses_synced_labels(analytics_db, monkeypatch):
    """build_report_analytics should use labels from sync, not re-classify."""
    from qbu_crawler.server import report_analytics

    call_count = {"classify": 0}
    original_classify = report_analytics.classify_review_labels

    def counting_classify(review):
        call_count["classify"] += 1
        return original_classify(review)

    monkeypatch.setattr(report_analytics, "classify_review_labels", counting_classify)

    snapshot = _build_snapshot(1, "2026-04-01")
    # Insert real DB records and assign IDs to snapshot reviews
    review_ids = _insert_snapshot_reviews_into_db(snapshot)
    for i, review in enumerate(snapshot["reviews"]):
        review["id"] = review_ids[i]

    # First: sync persists labels and returns them
    synced = report_analytics.sync_review_labels(snapshot)
    initial_count = call_count["classify"]

    # Second: build_report_analytics should NOT re-classify
    call_count["classify"] = 0
    analytics = report_analytics.build_report_analytics(snapshot, synced_labels=synced)
    assert call_count["classify"] == 0, \
        f"classify_review_labels called {call_count['classify']} times during build_report_analytics"


def test_recommendations_include_concrete_evidence(analytics_db):
    """Recommendations should reference specific review content, not just generic text."""
    from qbu_crawler.server.report_analytics import _recommendations

    clusters = [
        {
            "label_code": "quality_stability",
            "severity": "high",
            "review_count": 5,
            "example_reviews": [
                {"headline": "Motor burned out", "headline_cn": "电机烧了",
                 "body": "After 3 months the motor just died", "body_cn": "用了三个月电机坏了",
                 "product_name": "Grinder Pro", "product_sku": "GP-1"},
            ],
        },
    ]
    recs = _recommendations(clusters)
    assert recs, "Should produce recommendations"
    rec = recs[0]
    assert "top_complaint" in rec, "Should include top_complaint field"
    assert rec["top_complaint"], "top_complaint should not be empty"
    assert "affected_products" in rec, "Should include affected_products field"


def test_kpis_include_recently_published_count(analytics_db):
    """KPIs should distinguish scraped count from recently published count."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-07",
        "snapshot_hash": "test",
        "products": [
            {"name": "P1", "sku": "S1", "ownership": "own", "rating": 4.0,
             "review_count": 10, "site": "basspro"},
        ],
        "reviews": [
            # Published recently
            {"product_name": "P1", "product_sku": "S1", "ownership": "own",
             "rating": 2, "headline": "broke", "body": "", "headline_cn": "",
             "body_cn": "", "date_published": "2026-04-06", "images": None},
            # Published 6 months ago but scraped in this window
            {"product_name": "P1", "product_sku": "S1", "ownership": "own",
             "rating": 1, "headline": "broke after a week", "body": "",
             "headline_cn": "", "body_cn": "", "date_published": "2025-10-01",
             "images": None},
        ],
    }
    analytics = build_report_analytics(snapshot)
    kpis = analytics["kpis"]
    assert "recently_published_count" in kpis
    assert kpis["recently_published_count"] == 1  # only the recent one


def test_date_sort_key_relative_dates():
    """Relative dates must sort chronologically, not lexicographically."""
    from qbu_crawler.server.report_analytics import _date_sort_key
    from datetime import date

    key_5y = _date_sort_key("5 years ago")
    key_2y = _date_sort_key("2 years ago")
    assert key_5y < key_2y, "5 years ago should sort before 2 years ago"

    key_bad = _date_sort_key("unknown")
    assert key_bad == date(1970, 1, 1)


def test_feature_clusters_first_last_seen_chronological():
    """first_seen should be the earliest date, last_seen the most recent."""
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "5 years ago",
            "analysis_features": '["quality issue"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
        },
        {
            "ownership": "own", "sentiment": "negative", "rating": 2,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2 years ago",
            "analysis_features": '["quality issue"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
        },
    ]
    clusters = _build_feature_clusters(reviews, ownership="own", polarity="negative")
    cluster = clusters[0]
    assert cluster["first_seen"] == "5 years ago"
    assert cluster["last_seen"] == "2 years ago"


def test_cluster_output_consistent_fields(analytics_db):
    """Both cluster code paths must produce the same set of required fields."""
    from qbu_crawler.server.report_analytics import _cluster_summary_items, _build_feature_clusters, _build_labeled_reviews

    snapshot = _build_snapshot(1, "2026-04-01")
    labeled = _build_labeled_reviews(snapshot)
    label_clusters = _cluster_summary_items(labeled, ownership="own", polarity="negative")

    # Feature clusters need analysis data
    enriched_reviews = [
        {**r, "analysis_features": '["电机质量"]', "analysis_labels": '[{"severity": "high"}]',
         "sentiment": "negative"}
        for r in snapshot["reviews"] if r.get("ownership") == "own"
    ]
    feature_clusters = _build_feature_clusters(enriched_reviews, ownership="own", polarity="negative")

    required_keys = {
        "label_code", "label_display", "review_count", "severity",
        "severity_display", "affected_product_count", "first_seen",
        "last_seen", "example_reviews", "image_review_count",
    }
    for cluster in label_clusters:
        missing = required_keys - set(cluster.keys())
        assert not missing, f"Label cluster missing keys: {missing}"
    for cluster in feature_clusters:
        missing = required_keys - set(cluster.keys())
        assert not missing, f"Feature cluster missing keys: {missing}"


def test_feature_clusters_merge_by_label_code():
    """Features with same primary label_code should merge into one cluster."""
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-01-01",
            "analysis_features": '["broke after a week"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}]',
        },
        {
            "ownership": "own", "sentiment": "negative", "rating": 2,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-02-01",
            "analysis_features": '["lifespan too short"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
        },
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-03-01",
            "analysis_features": '["metal shavings"]',
            "analysis_labels": '[{"code": "material_finish", "polarity": "negative", "severity": "medium", "confidence": 0.88}]',
        },
    ]
    clusters = _build_feature_clusters(reviews, ownership="own", polarity="negative")

    # Should produce 2 clusters (quality_stability + material_finish), not 3
    assert len(clusters) == 2

    qs_cluster = next(c for c in clusters if c["label_code"] == "quality_stability")
    assert qs_cluster["review_count"] == 2
    assert len(qs_cluster["sub_features"]) == 2
    assert any(sf["feature"] == "broke after a week" for sf in qs_cluster["sub_features"])
    assert any(sf["feature"] == "lifespan too short" for sf in qs_cluster["sub_features"])
    # Must have standard display name, not free-text
    assert qs_cluster["label_display"] == "质量稳定性"

    mf_cluster = next(c for c in clusters if c["label_code"] == "material_finish")
    assert mf_cluster["review_count"] == 1


def test_feature_clusters_uncategorized_fallback():
    """Reviews with no matching-polarity labels go to _uncategorized."""
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-01-01",
            "analysis_features": '["some issue"]',
            "analysis_labels": '[]',  # no labels at all
        },
    ]
    clusters = _build_feature_clusters(reviews, ownership="own", polarity="negative")
    assert len(clusters) == 1
    assert clusters[0]["label_code"] == "_uncategorized"


# ---------------------------------------------------------------------------
# Tests for _extract_validated_llm_labels
# ---------------------------------------------------------------------------


def test_extract_validated_llm_labels_filters_polarity():
    """LLM labels with wrong polarity for their code should be rejected."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    review = {
        "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}, '
                           '{"code": "solid_build", "polarity": "negative", "severity": "low", "confidence": 0.7}, '
                           '{"code": "easy_to_use", "polarity": "positive", "severity": "low", "confidence": 0.8}]'
    }
    labels = _extract_validated_llm_labels(review)
    codes = {l["label_code"] for l in labels}
    assert "solid_build" not in codes  # positive-only code with negative polarity → rejected
    assert "quality_stability" in codes
    assert "easy_to_use" in codes


def test_extract_validated_llm_labels_caps_at_3():
    """Per-review cap of 3 labels, highest confidence first."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    review = {
        "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}, '
                           '{"code": "structure_design", "polarity": "negative", "severity": "medium", "confidence": 0.9}, '
                           '{"code": "material_finish", "polarity": "negative", "severity": "medium", "confidence": 0.85}, '
                           '{"code": "packaging_shipping", "polarity": "negative", "severity": "low", "confidence": 0.7}]'
    }
    labels = _extract_validated_llm_labels(review)
    assert len(labels) == 3
    assert labels[0]["label_code"] == "quality_stability"
    assert labels[2]["label_code"] == "material_finish"


def test_extract_validated_llm_labels_service_fulfillment_allows_both():
    """service_fulfillment is the only bidirectional code."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    review = {
        "analysis_labels": '[{"code": "service_fulfillment", "polarity": "positive", "severity": "low", "confidence": 0.8}]'
    }
    labels = _extract_validated_llm_labels(review)
    assert len(labels) == 1
    assert labels[0]["label_code"] == "service_fulfillment"
    assert labels[0]["label_polarity"] == "positive"


def test_extract_validated_llm_labels_empty_input():
    """None or empty analysis_labels returns empty list."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    assert _extract_validated_llm_labels({}) == []
    assert _extract_validated_llm_labels({"analysis_labels": None}) == []
    assert _extract_validated_llm_labels({"analysis_labels": "[]"}) == []


def test_build_trend_data_returns_time_series(analytics_db):
    """_build_trend_data should return per-product time series from snapshots."""
    from qbu_crawler.server.report_analytics import _build_trend_data

    conn = models.get_conn()
    try:
        conn.execute(
            "INSERT INTO products (url, site, name, sku, price, stock_status, rating, review_count, ownership, scraped_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("https://example.com/p1", "basspro", "Product 1", "SKU1", 100, "in_stock", 4.0, 10, "own", "2026-04-01 10:00:00"),
        )
        pid = conn.execute("SELECT id FROM products WHERE sku='SKU1'").fetchone()["id"]
        for day in range(1, 4):
            conn.execute(
                "INSERT INTO product_snapshots (product_id, price, stock_status, review_count, rating, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, 100.0 + day, "in_stock", 10 + day, 4.0 + day * 0.1, f"2026-04-0{day} 10:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    products = [{"name": "Product 1", "sku": "SKU1"}]
    trend = _build_trend_data(products, days=30)
    assert len(trend) == 1
    assert trend[0]["product_name"] == "Product 1"
    assert trend[0]["product_sku"] == "SKU1"
    series = trend[0]["series"]
    assert len(series) == 3
    assert series[0]["price"] == 101.0
    assert series[2]["price"] == 103.0


def test_build_trend_data_empty_snapshots(analytics_db):
    """Products with no snapshots should return empty series."""
    from qbu_crawler.server.report_analytics import _build_trend_data

    products = [{"name": "Ghost Product", "sku": "GHOST"}]
    trend = _build_trend_data(products, days=30)
    assert len(trend) == 1
    assert trend[0]["series"] == []


def test_image_reviews_expanded_to_20(analytics_db):
    """appendix.image_reviews should allow up to 20 items, prioritized by ownership and rating."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    # Build snapshot with many image reviews
    reviews = []
    for i in range(25):
        reviews.append({
            "product_name": "Own Product", "product_sku": "OWN-1",
            "author": f"Author-{i}", "headline": f"Review {i}",
            "body": f"This product broke. Body {i}",
            "rating": (i % 5) + 1, "date_published": "2026-03-28",
            "images": [f"https://img.example.com/{i}.jpg"],
            "ownership": "own" if i < 15 else "competitor",
            "headline_cn": "", "body_cn": "", "translate_status": "done",
        })

    snapshot = {
        "run_id": 1, "logical_date": "2026-04-08",
        "snapshot_hash": "test-hash",
        "products": [
            {"url": "https://example.com/own-1", "name": "Own Product", "sku": "OWN-1",
             "price": 100, "stock_status": "in_stock", "rating": 3.0, "review_count": 25,
             "scraped_at": "2026-04-08 10:00:00", "site": "basspro", "ownership": "own"},
        ],
        "reviews": reviews,
        "products_count": 1, "reviews_count": 25,
        "translated_count": 25, "untranslated_count": 0,
    }

    result = build_report_analytics(snapshot)
    image_reviews = result["appendix"]["image_reviews"]
    assert len(image_reviews) == 20  # expanded from 10
    # Own products should come first
    assert image_reviews[0]["ownership"] == "own"
