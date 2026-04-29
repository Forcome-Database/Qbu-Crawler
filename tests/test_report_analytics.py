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


def test_baseline_second_run_exposes_building_display_state(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    _create_daily_run("2026-03-28", status="completed", analytics_path="a.json")
    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["mode"] == "baseline"
    assert analytics["report_semantics"] == "bootstrap"
    assert analytics["baseline_sample_days"] == 1
    assert analytics["baseline_day_index"] == 2
    assert analytics["baseline_display_state"] == "building"


def test_build_report_analytics_uses_incremental_mode_with_prior_runs(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    _create_daily_run("2026-03-20", analytics_path="a.json")
    _create_daily_run("2026-03-21", analytics_path="b.json")
    _create_daily_run("2026-03-25", analytics_path="c.json")
    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["mode"] == "incremental"
    assert analytics["baseline_sample_days"] == 3


def test_build_report_analytics_exposes_report_semantics_fields(analytics_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    _create_daily_run("2026-03-20", analytics_path="a.json")
    _create_daily_run("2026-03-21", analytics_path="b.json")
    _create_daily_run("2026-03-25", analytics_path="c.json")
    run = _create_daily_run("2026-03-29", status="reporting")

    analytics = build_report_analytics(_build_snapshot(run["id"], "2026-03-29"))

    assert analytics["report_semantics"] == "incremental"
    assert analytics["is_bootstrap"] is False
    assert analytics["change_digest"] == {}
    # F011 §4.2.5 — analytics["trend_digest"] now uses the public build_trend_digest
    # shape: {primary_chart: {...}, drill_downs: [...]}. The legacy 12-panel
    # views/dimensions/data[view][dim] shape was retired in this task.
    trend = analytics["trend_digest"]
    assert "primary_chart" in trend
    assert "drill_downs" in trend
    primary = trend["primary_chart"]
    assert primary.get("kind") == "health_trend"
    assert primary.get("default_window") in {"7d", "30d", "12m"}
    assert primary.get("confidence") in {"high", "medium", "low", "no_data"}


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
    assert analytics["kpis"]["own_avg_rating"] == 1.5


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
    """sample_avg_rating should be the mean of all review ratings, not the site rating."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    snapshot = _build_snapshot(1, "2026-04-01")
    # Set specific ratings on own reviews to verify computation
    own_reviews = [r for r in snapshot["reviews"] if r.get("ownership") == "own"]
    for i, r in enumerate(own_reviews):
        r["rating"] = 2 + i  # e.g., 2, 3, 4...

    analytics = build_report_analytics(snapshot)
    sample_avg = analytics["kpis"].get("sample_avg_rating")
    assert sample_avg is not None, "sample_avg_rating should be computed"
    expected = round(sum(r["rating"] for r in snapshot["reviews"]) / len(snapshot["reviews"]), 2)
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


def test_feature_cluster_has_affected_products():
    """Clusters must include affected_products list with product names."""
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [{
        "product_name": "Cabela's Heavy-Duty", "product_sku": "SKU1", "ownership": "own",
        "rating": 1, "headline": "bad", "body": "broke",
        "sentiment": "negative",
        "analysis_features": '["handle broke"]',
        "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
    }]
    clusters = _build_feature_clusters(reviews, ownership="own", polarity="negative")
    assert len(clusters) >= 1
    cluster = clusters[0]
    assert "affected_products" in cluster
    assert "Cabela's Heavy-Duty" in cluster["affected_products"]


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


def test_example_reviews_diverse_selection():
    """example_reviews should include diverse ratings, not just lowest."""
    from qbu_crawler.server.report_analytics import _select_diverse_examples
    reviews_data = [
        {"rating": 1, "headline": "terrible", "body": "worst", "images": [], "date_published_parsed": "2026-01-01", "product_name": "P"},
        {"rating": 1, "headline": "awful", "body": "bad too", "images": [], "date_published_parsed": "2026-01-02", "product_name": "P"},
        {"rating": 1, "headline": "poor", "body": "bad three", "images": ["img.jpg"], "date_published_parsed": "2026-01-03", "product_name": "P"},
        {"rating": 2, "headline": "mediocre", "body": "could be better", "images": [], "date_published_parsed": "2026-01-04", "product_name": "P"},
        {"rating": 3, "headline": "ok", "body": "mixed feelings", "images": [], "date_published_parsed": "2026-02-01", "product_name": "P"},
    ]
    selected = _select_diverse_examples(reviews_data, max_count=3)
    ratings = [r["rating"] for r in selected]
    assert max(ratings) >= 2, f"All examples are 1-star: {ratings}"
    has_image = any(r.get("images") for r in selected)
    assert has_image, "Should include at least one review with images"


# ---------------------------------------------------------------------------
# Tests for detect_report_mode baseline exit condition (Fix-5)
# ---------------------------------------------------------------------------


def test_detect_report_mode_counts_quiet_runs(analytics_db):
    """Quiet runs (no analytics_path) should count toward the 3-run baseline threshold."""
    from qbu_crawler.server.report_analytics import detect_report_mode

    _create_daily_run("2026-04-01", status="completed", analytics_path="/tmp/a1.json")
    _create_daily_run("2026-04-02", status="completed", analytics_path=None)
    _create_daily_run("2026-04-03", status="completed", analytics_path="/tmp/a3.json")

    current = _create_daily_run("2026-04-04", status="reporting")

    result = detect_report_mode(current["id"], "2026-04-04")
    assert result["mode"] == "incremental", (
        f"Expected incremental with 3 completed runs (1 quiet), got {result['mode']} "
        f"with baseline_sample_days={result['baseline_sample_days']}"
    )


def test_detect_report_mode_baseline_with_fewer_than_3(analytics_db):
    """Fewer than 3 completed runs should remain baseline."""
    from qbu_crawler.server.report_analytics import detect_report_mode

    _create_daily_run("2026-04-01", status="completed", analytics_path=None)
    _create_daily_run("2026-04-02", status="completed", analytics_path=None)

    current = _create_daily_run("2026-04-04", status="reporting")

    result = detect_report_mode(current["id"], "2026-04-04")
    assert result["mode"] == "baseline"
    assert result["baseline_sample_days"] == 2


# ---------------------------------------------------------------------------
# Tests for KPI delta activation (Fix-4)
# ---------------------------------------------------------------------------

import json
from pathlib import Path


def test_build_report_analytics_includes_kpi_deltas(analytics_db, tmp_path, monkeypatch):
    """In incremental mode, analytics should include KPI deltas from previous run."""
    from qbu_crawler.server import report_analytics

    # Create 3 completed prior runs to exit baseline mode
    for i, date in enumerate(["2026-04-01", "2026-04-02", "2026-04-03"]):
        analytics_path = str(tmp_path / f"analytics-{date}.json")
        prev_analytics = {
            "kpis": {
                "negative_review_rows": 10 + i,
                "own_negative_review_rows": 5 + i,
                "ingested_review_rows": 100 + i * 10,
                "product_count": 5,
                "health_index": 70.0 + i,
                "recently_published_count": 3,
            }
        }
        Path(analytics_path).write_text(json.dumps(prev_analytics, ensure_ascii=False), encoding="utf-8")
        _create_daily_run(date, status="completed", analytics_path=analytics_path)

    current_run = _create_daily_run("2026-04-04", status="reporting")
    snapshot = _build_snapshot(current_run["id"], "2026-04-04")
    analytics = report_analytics.build_report_analytics(snapshot)

    assert analytics.get("mode") == "incremental" or analytics.get("mode_info", {}).get("mode") == "incremental"
    kpis = analytics["kpis"]
    assert "negative_review_rows_delta" in kpis, f"Missing delta keys. KPI keys: {list(kpis.keys())}"
    assert "negative_review_rows_delta_display" in kpis


def test_build_report_analytics_baseline_has_no_deltas(analytics_db, monkeypatch):
    """In baseline mode, KPI deltas should not be present."""
    from qbu_crawler.server import report_analytics

    current_run = _create_daily_run("2026-04-04", status="reporting")
    snapshot = _build_snapshot(current_run["id"], "2026-04-04")
    analytics = report_analytics.build_report_analytics(snapshot)

    kpis = analytics["kpis"]
    assert "negative_review_rows_delta" not in kpis


# ---------------------------------------------------------------------------
# Tests for build_dual_report_analytics (P007 Task 3)
# ---------------------------------------------------------------------------


def _build_dual_snapshot(run_id: int, logical_date: str):
    """Extend _build_snapshot with a 'cumulative' field containing window reviews + 3 older reviews."""
    window = _build_snapshot(run_id, logical_date)
    # Additional older reviews for cumulative perspective
    older_reviews = [
        {
            "product_name": "Own Grinder",
            "product_sku": "OWN-1",
            "author": "Frank",
            "headline": "Works well overall",
            "body": "Good performance for the price.",
            "rating": 4,
            "date_published": "2026-03-01",
            "images": [],
            "ownership": "own",
            "headline_cn": "",
            "body_cn": "",
            "translate_status": "done",
        },
        {
            "product_name": "Own Grinder",
            "product_sku": "OWN-1",
            "author": "Grace",
            "headline": "Great grinder",
            "body": "Solid build, easy to use.",
            "rating": 5,
            "date_published": "2026-02-15",
            "images": [],
            "ownership": "own",
            "headline_cn": "",
            "body_cn": "",
            "translate_status": "done",
        },
        {
            "product_name": "Competitor Grinder",
            "product_sku": "COMP-1",
            "author": "Hank",
            "headline": "Decent product",
            "body": "Does the job.",
            "rating": 3,
            "date_published": "2026-02-01",
            "images": [],
            "ownership": "competitor",
            "headline_cn": "",
            "body_cn": "",
            "translate_status": "done",
        },
    ]
    cumulative_reviews = window["reviews"] + older_reviews
    dual = {
        **window,
        "cumulative": {
            "products": window["products"],
            "reviews": cumulative_reviews,
            "products_count": window["products_count"],
            "reviews_count": len(cumulative_reviews),
            "translated_count": len(cumulative_reviews),
            "untranslated_count": 0,
        },
    }
    return dual


def test_build_dual_report_analytics_perspective(analytics_db):
    """Result should have perspective == 'dual' when cumulative field is present."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    result = build_dual_report_analytics(snapshot)

    assert result["perspective"] == "dual"


def test_build_dual_report_analytics_has_cumulative_kpis(analytics_db):
    """cumulative_kpis should be present with correct review count from cumulative data."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    result = build_dual_report_analytics(snapshot)

    assert "cumulative_kpis" in result
    kpis = result["cumulative_kpis"]
    # cumulative has 5 (window) + 3 (older) = 8 reviews total
    cumulative_review_count = len(snapshot["cumulative"]["reviews"])
    assert kpis["ingested_review_rows"] == cumulative_review_count


def test_build_dual_report_analytics_has_window(analytics_db):
    """window key should be present with reviews_count, own_reviews_count, etc."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    result = build_dual_report_analytics(snapshot)

    assert "window" in result
    window = result["window"]
    assert "reviews_count" in window
    assert "own_reviews_count" in window
    assert "competitor_reviews_count" in window
    assert "new_negative_count" in window
    assert "new_reviews" in window
    # window reviews_count matches the top-level snapshot reviews (not cumulative)
    assert window["reviews_count"] == len(snapshot["reviews"])
    # own_reviews_count + competitor_reviews_count == reviews_count
    assert window["own_reviews_count"] + window["competitor_reviews_count"] == window["reviews_count"]


def test_build_dual_degrades_without_cumulative(analytics_db):
    """When snapshot has no 'cumulative' field, result should NOT have 'dual' perspective."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_snapshot(run["id"], "2026-03-29")  # old format, no cumulative
    result = build_dual_report_analytics(snapshot)

    assert result.get("perspective") != "dual"
    assert "cumulative_kpis" not in result
    assert "window" not in result


def test_build_dual_risk_products_from_cumulative(analytics_db):
    """risk products should be present (derived from cumulative data)."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    result = build_dual_report_analytics(snapshot)

    # self.risk_products should exist (populated from cumulative reviews)
    assert "self" in result
    assert "risk_products" in result["self"]
    # The list may be empty or non-empty, but the key must be present
    assert isinstance(result["self"]["risk_products"], list)


def test_build_dual_window_analytics_has_no_delta_keys(analytics_db):
    """Window analytics (skip_delta=True) should NOT contain _delta keys."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")
    _insert_review_record()

    result = build_dual_report_analytics(snapshot)

    window_analytics = result.get("window", {}).get("analytics")
    if window_analytics:
        delta_keys = [k for k in window_analytics.get("kpis", {}) if k.endswith("_delta")]
        assert delta_keys == [], f"Window analytics should have no delta keys, found: {delta_keys}"


# F011 §4.2.5 — retired: legacy 12-panel data shape replaced by primary_chart+drill_downs
# Original test asserted result["trend_digest"]["data"]["month"][dim]["status"] across
# the 4 dimensions × 3 views. The new shape exposes a single primary_chart for "口碑
# 健康度趋势" plus 3 drill_downs (top_issues / product_ratings / competitor_radar).
# Mixed-state coverage of ready/accumulating per-block is no longer meaningful;
# confidence-tier coverage lives in tests/server/test_trend_digest_thresholds.py.
def test_build_dual_trend_digest_uses_primary_chart_shape(analytics_db):
    """Smoke: build_dual_report_analytics still emits the new trend_digest shape."""
    from qbu_crawler.server.report_analytics import build_dual_report_analytics

    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_dual_snapshot(run["id"], "2026-03-29")

    result = build_dual_report_analytics(snapshot)

    trend = result["trend_digest"]
    assert "primary_chart" in trend
    assert "drill_downs" in trend
    assert trend["primary_chart"].get("kind") == "health_trend"


def test_sentiment_trend_bucket_health_is_bayesian_shrunk():
    """趋势 health_scores 必须用 _bayesian_bucket_health，
    不能再是 100 - own_negative_rate 的简化公式。

    场景：某 bucket 只有 1 条 5 星评论 → 旧公式给 100，新公式必须 < 70。
    """
    from qbu_crawler.server.report_analytics import _build_sentiment_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        # 只在 '2026-04' bucket 有 1 条 5 星自有评论，其它 bucket 空
        {
            "review": {
                "ownership": "own",
                "rating": 5,
                "date_published_parsed": "2026-04-10",
            },
            "published": date(2026, 4, 10),
        },
    ]
    result = _build_sentiment_trend("month", logical_day, labeled_reviews)
    # 找到 primary_chart 里名为 '健康分' 的 series
    series = next(
        s for s in result["primary_chart"]["series"]
        if "健康" in s["name"]
    )
    # 非空 bucket 的值必须 < 70（贝叶斯收缩后）；空 bucket 必须 None
    non_null = [v for v in series["data"] if v is not None]
    assert non_null, "expected at least one non-null bucket"
    assert all(v < 70 for v in non_null), \
        f"small-sample bucket should shrink toward 50, got {non_null}"
    # 空 bucket 应该是 None 而不是 0
    assert series["data"].count(None) >= 1


def test_competition_trend_mixed_state_keeps_ready_table_when_chart_accumulating():
    """spec §8.5 要求：竞品趋势允许按子组件混合状态输出，
    不能整维度一刀切成同一状态。

    场景：自有有评论但竞品无评论 → primary_chart 无法 ready，
    但表格仍应列出自有侧数据（status=ready）。
    """
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    labeled_reviews = [
        {
            "review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-10"},
            "published": date(2026, 4, 10),
        },
        {
            "review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-03-15"},
            "published": date(2026, 3, 15),
        },
    ]
    result = _build_competition_trend("month", date(2026, 4, 24), labeled_reviews)
    # 顶层 status 允许是 accumulating
    assert result["status"] in {"accumulating", "ready"}
    # 但表格组件必须 ready（因为自有侧有数据）
    assert result["table"]["status"] == "ready"
    assert len(result["table"]["rows"]) >= 1
    # primary_chart 可以 accumulating（缺竞品不能对比）
    assert result["primary_chart"]["status"] in {"accumulating", "ready"}


def test_build_trend_digest_emits_year_view_note():
    """修 9: trend_digest 必须在 year 视角下提供语义 banner，
    告诉用户 year 维度基于评论发布时间聚合，不代表监控运行年限。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest

    snapshot = {
        "logical_date": "2026-04-25",
        "products": [],
        "reviews": [],
    }
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    assert "view_notes" in digest, "trend_digest 必须暴露 view_notes 用于年视图 banner"
    assert "year" in digest["view_notes"]
    note = digest["view_notes"]["year"]
    assert "评论发布时间" in note or "发布时间" in note
    assert "监控" in note  # 必须强调"非监控运行年限"
    # week / month 可以为 None 或 ""（不需要 banner）
    assert digest["view_notes"].get("week") in (None, "")
    assert digest["view_notes"].get("month") in (None, "")


def test_trend_digest_blocks_all_have_phase2_schema():
    """Phase 2 T9: 每块 (view × dim) 必须同时具备 Phase 1 5 键 + Phase 2 2 键，
    无论 status 是 ready / accumulating / degraded。
    schema 永远齐全，缺数据时 series 为空、comparison 三段为 null。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest

    snapshot = {
        "logical_date": "2026-04-25",
        "products": [],
        "reviews": [],
    }
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    expected_keys = {
        "status", "status_message", "kpis", "primary_chart",
        "secondary_charts", "comparison", "table",
    }
    for view in digest["views"]:
        for dim in digest["dimensions"]:
            block = digest["data"][view][dim]
            missing = expected_keys - set(block.keys())
            assert not missing, f"{view}/{dim} missing keys: {missing}"
            assert isinstance(block["secondary_charts"], list), \
                f"{view}/{dim} secondary_charts must be list, got {type(block['secondary_charts'])}"
            assert isinstance(block["comparison"], dict), \
                f"{view}/{dim} comparison must be dict, got {type(block['comparison'])}"
            # comparison 三段固定 key
            assert set(block["comparison"].keys()) == {
                "period_over_period", "year_over_year", "start_vs_end",
            }, f"{view}/{dim} comparison keys mismatch: {block['comparison'].keys()}"
            pop = block["comparison"]["period_over_period"]
            assert set(pop.keys()) >= {"label", "current", "previous", "change_pct"}, \
                f"{view}/{dim} period_over_period inner shape mismatch: {pop.keys()}"
            yoy = block["comparison"]["year_over_year"]
            assert set(yoy.keys()) >= {"label", "current", "previous", "change_pct"}, \
                f"{view}/{dim} year_over_year inner shape mismatch: {yoy.keys()}"
            sve = block["comparison"]["start_vs_end"]
            assert set(sve.keys()) >= {"label", "start", "end", "change_pct"}, \
                f"{view}/{dim} start_vs_end inner shape mismatch: {sve.keys()}"


def test_trend_digest_blocks_always_have_four_kpi_items():
    """Phase 2 T9 + audit §4.1: 任何 view × dim 组合的 kpis.items 必须恰好 4 条 KPI 项；
    且 accumulating 状态下 label 必须给 dimension-specific 名字（非纯 "—"），
    保留指标骨架便于前端展示"差评率：—"而不是"—：—"。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest

    snapshot = {"logical_date": "2026-04-25", "products": [], "reviews": []}
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    for view in digest["views"]:
        for dim in digest["dimensions"]:
            block = digest["data"][view][dim]
            items = (block.get("kpis") or {}).get("items") or []
            assert len(items) == 4, \
                f"{view}/{dim} kpis.items must have 4 entries, got {len(items)}"
            # label 必须非空且至少有 1 个不是占位 "—"（accumulating 也要给业务标签）
            labels = [it.get("label") for it in items]
            assert all(label for label in labels), \
                f"{view}/{dim} kpis.items[*].label must be non-empty, got {labels}"
            assert all(label and label != "—" for label in labels), \
                f"{view}/{dim} accumulating 状态每个 KPI 都必须给 dimension-specific 标签，" \
                f"不能含 \"—\"，当前: {labels}"


def test_trend_digest_exposes_dimension_notes_and_contract():
    from qbu_crawler.server.report_analytics import _build_trend_digest

    snapshot = {"logical_date": "2026-04-25", "products": [], "reviews": []}
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    assert set(digest["dimension_notes"]) == {"sentiment", "issues", "products", "competition"}
    assert "date_published" in digest["dimension_notes"]["sentiment"]
    assert "date_published" in digest["dimension_notes"]["issues"]
    assert "date_published" in digest["dimension_notes"]["competition"]
    assert "scraped_at" in digest["dimension_notes"]["products"]
    assert "价格" in digest["dimension_notes"]["products"]
    assert "库存" in digest["dimension_notes"]["products"]
    assert "可比样本不足" in digest["dimension_notes"]["competition"]


def test_sentiment_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: sentiment dim 在 ready 时必须输出 2 张辅图：
    1) 自有差评率趋势 (line)
    2) 健康分趋势 (line)
    每张图都带独立 status，labels 与主图同 buckets，series 至少 1 条。"""
    from qbu_crawler.server.report_analytics import _build_sentiment_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-10"}},
        {"review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-04-11"}},
        {"review": {"ownership": "own", "rating": 2, "date_published_parsed": "2026-04-12"}},
    ]
    result = _build_sentiment_trend("month", logical_day, labeled_reviews)

    assert result["status"] == "ready"
    secondary = result["secondary_charts"]
    assert isinstance(secondary, list) and len(secondary) >= 2, \
        f"expected >=2 secondary charts, got {len(secondary)}"

    titles = {chart["title"] for chart in secondary}
    assert "自有差评率趋势" in titles, f"missing exact title; got {titles}"
    assert "健康分趋势" in titles, f"missing exact title; got {titles}"

    for chart in secondary:
        assert set(chart.keys()) >= {"status", "chart_type", "title", "labels", "series"}
        assert chart["status"] in {"ready", "accumulating", "degraded"}
        if chart["status"] == "ready":
            assert chart["labels"], "ready chart must have non-empty labels"
            assert chart["series"], "ready chart must have non-empty series"


def test_sentiment_trend_emits_comparison_with_start_vs_end():
    """Phase 2 T9: sentiment dim ready 时 comparison.start_vs_end 必须有
    start / end / change_pct 三个非 null 值（差评率，单位 %）；
    period_over_period / year_over_year 在数据不足时填 null 但 key 必须存在。"""
    from qbu_crawler.server.report_analytics import _build_sentiment_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    # 构造首尾两个 bucket 都有数据的场景
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-03-26"}},  # 月初
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-22"}},  # 月末
        {"review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-23"}},
    ]
    result = _build_sentiment_trend("month", logical_day, labeled_reviews)
    comp = result["comparison"]

    # shape 永远齐全
    assert set(comp.keys()) == {"period_over_period", "year_over_year", "start_vs_end"}

    # start_vs_end 在有首尾数据时必须可计算
    sve = comp["start_vs_end"]
    assert sve["start"] is not None, "start_vs_end.start should be computable"
    assert sve["end"] is not None, "start_vs_end.end should be computable"
    # 月初 1/2 = 50% 差评率，月末 0/2 = 0% → end < start
    assert sve["end"] < sve["start"], f"end={sve['end']} should be < start={sve['start']}"

    # change_pct 语义锁：相对百分比变化 (end-start)/start*100；50% → 0% 为 -100.0
    assert sve["change_pct"] is not None
    assert sve["change_pct"] < 0, "差评率下降 → change_pct 应为负"
    assert sve["change_pct"] == -100.0, \
        f"差评率从 50% (1/2) 降到 0% (0/2)，相对变化应为 -100.0，得到 {sve['change_pct']}"


def test_issue_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: issues dim ready 时必须输出 2 张辅图：
    1) Top3 问题分时段堆叠 (stacked_bar)
    2) Top3 问题影响 SKU 数 (bar, x=问题, y=affected_product_count)
    标题精确锁，避免未来重命名导致测试失效."""
    from qbu_crawler.server.report_analytics import _build_issue_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        {
            "review": {"ownership": "own", "rating": 1, "product_sku": "A1",
                       "date_published_parsed": "2026-04-10"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "rating": 1, "product_sku": "B2",
                       "date_published_parsed": "2026-04-12"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "rating": 2, "product_sku": "C3",
                       "date_published_parsed": "2026-04-15"},
            "labels": [{"label_code": "shipping_delay", "label_polarity": "negative"}],
        },
    ]
    result = _build_issue_trend("month", logical_day, labeled_reviews)

    assert result["status"] == "ready"
    secondary = result["secondary_charts"]
    assert isinstance(secondary, list) and len(secondary) >= 2

    titles = {chart["title"] for chart in secondary}
    assert "Top3 问题分时段堆叠" in titles, f"missing exact title; got {titles}"
    assert "Top3 问题影响 SKU 数" in titles, f"missing exact title; got {titles}"

    chart_types = {chart["chart_type"] for chart in secondary}
    # 至少有 stacked_bar 或 bar
    assert chart_types & {"stacked_bar", "bar"}, \
        f"expected at least one stacked_bar/bar chart, got {chart_types}"

    for chart in secondary:
        assert set(chart.keys()) >= {"status", "chart_type", "title", "labels", "series"}
        assert chart["status"] in {"ready", "accumulating", "degraded"}


def test_issue_trend_emits_comparison_with_top_issue_heat():
    """Phase 2 T9: issues dim comparison.start_vs_end 度量为「头号问题在窗口首尾的评论数」。
    change_pct 语义：相对百分比变化（与 sentiment dim 同口径）。"""
    from qbu_crawler.server.report_analytics import _build_issue_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    # quality_stability 是头号问题：3 条
    # 月初 (3-26) 1 条，中间 (4-10) 1 条，月末 (4-23) 1 条
    labeled_reviews = [
        {
            "review": {"ownership": "own", "product_sku": "A1",
                       "date_published_parsed": "2026-03-26"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "product_sku": "B2",
                       "date_published_parsed": "2026-04-10"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
        {
            "review": {"ownership": "own", "product_sku": "C3",
                       "date_published_parsed": "2026-04-23"},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}],
        },
    ]
    result = _build_issue_trend("month", logical_day, labeled_reviews)
    comp = result["comparison"]
    assert set(comp.keys()) == {"period_over_period", "year_over_year", "start_vs_end"}

    sve = comp["start_vs_end"]
    assert sve["start"] == 1, f"start: 月初有 1 条 quality_stability，got {sve['start']}"
    assert sve["end"] == 1, f"end: 月末有 1 条 quality_stability，got {sve['end']}"
    # start=1, end=1 → change_pct = 0.0
    assert sve["change_pct"] == 0.0, \
        f"start=1, end=1, 相对变化应 0.0，got {sve['change_pct']}"

    # PoP / YoY 仍留 None
    assert comp["period_over_period"]["current"] is None
    assert comp["year_over_year"]["current"] is None


def test_product_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: products dim ready 时辅图 2 张：
    1) 重点 SKU 评论总数趋势 (line)
    2) 重点 SKU 价格趋势 (line)
    依赖 product_snapshots 已有 >=2 个时间点。"""
    from qbu_crawler.server.report_analytics import _build_product_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    snapshot_products = [
        {"sku": "A1", "name": "Prod A", "ownership": "own", "rating": 4.2,
         "review_count": 200, "scraped_at": "2026-04-24T08:00:00+08:00"},
    ]
    # 模拟 trend_series 提供 >=2 个时间点
    trend_series = [
        {
            "product_sku": "A1",
            "series": [
                {"date": "2026-04-01", "rating": 4.0, "review_count": 180, "price": 99.0},
                {"date": "2026-04-15", "rating": 4.2, "review_count": 200, "price": 95.0},
            ],
        },
    ]
    result = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    assert result["status"] == "ready"

    secondary = result["secondary_charts"]
    assert len(secondary) >= 2

    titles = {c["title"] for c in secondary}
    # 标题精确含 product_name
    assert any("评论总数" in t and "Prod A" in t for t in titles), \
        f"missing 评论总数 chart with product name: {titles}"
    assert any("价格" in t and "Prod A" in t for t in titles), \
        f"missing 价格 chart with product name: {titles}"

    for chart in secondary:
        assert set(chart.keys()) >= {"status", "chart_type", "title", "labels", "series"}


def test_product_trend_table_includes_price_and_stock_state_changes():
    from qbu_crawler.server.report_analytics import _build_product_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    snapshot_products = [
        {"sku": "SKU-A", "name": "Product A", "ownership": "own", "rating": 4.2,
         "review_count": 20, "price": 12.0, "stock_status": "out_of_stock",
         "scraped_at": "2026-04-24 10:00:00"},
        {"sku": "SKU-B", "name": "Product B", "ownership": "own", "rating": 4.5,
         "review_count": 10, "price": 20.0, "stock_status": "in_stock",
         "scraped_at": "2026-04-24 10:00:00"},
    ]
    trend_series = [
        {
            "product_sku": "SKU-B",
            "series": [
                {"date": "2026-04-10", "price": 20.0, "rating": 4.5, "review_count": 10, "stock_status": "in_stock"},
                {"date": "2026-04-20", "price": 20.0, "rating": 4.5, "review_count": 10, "stock_status": "in_stock"},
            ],
        },
        {
            "product_sku": "SKU-A",
            "series": [
                {"date": "2026-04-10", "price": 10.0, "rating": 4.0, "review_count": 18, "stock_status": "in_stock"},
                {"date": "2026-04-15", "price": 11.0, "rating": 4.1, "review_count": 19, "stock_status": "in_stock"},
                {"date": "2026-04-20", "price": 12.0, "rating": 4.2, "review_count": 20, "stock_status": "out_of_stock"},
            ],
        },
    ]

    result = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    columns = result["table"]["columns"]
    rows = result["table"]["rows"]
    product_a = next(row for row in rows if row["sku"] == "SKU-A")
    secondary_titles = [chart.get("title", "") for chart in result["secondary_charts"]]

    for column in ("当前价格", "当前库存", "价格变化次数", "库存变化次数", "最近库存变化"):
        assert column in columns
    assert product_a["current_price"] == 12.0
    assert product_a["current_stock"] == "out_of_stock"
    assert product_a["price_change_count"] == 2
    assert product_a["stock_change_count"] == 1
    assert "in_stock -> out_of_stock" in product_a["latest_stock_change"]
    assert result["primary_chart"]["title"] == "产品状态 - Product A"
    assert any("价格" in title and "Product A" in title for title in secondary_titles)
    assert not any("库存" in title for title in secondary_titles)


def test_product_trend_emits_comparison_with_focus_sku_rating():
    """Phase 2 T9: products dim comparison.start_vs_end 度量为「重点 SKU 评分」。
    使用 trend_series 首尾点；change_pct 语义：相对百分比变化。"""
    from qbu_crawler.server.report_analytics import _build_product_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    snapshot_products = [
        {"sku": "A1", "name": "Prod A", "ownership": "own", "rating": 4.2,
         "review_count": 200, "scraped_at": "2026-04-24T08:00:00+08:00"},
    ]
    trend_series = [
        {
            "product_sku": "A1",
            "series": [
                {"date": "2026-04-01", "rating": 3.8, "review_count": 100, "price": 99.0},
                {"date": "2026-04-23", "rating": 4.2, "review_count": 200, "price": 95.0},
            ],
        },
    ]
    result = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    sve = result["comparison"]["start_vs_end"]
    assert sve["start"] == 3.8
    assert sve["end"] == 4.2
    # change_pct: (4.2 - 3.8) / 3.8 * 100 = 10.526..., round to 10.5
    assert sve["change_pct"] == 10.5, \
        f"start=3.8, end=4.2, 相对变化应 ≈ 10.5，得到 {sve['change_pct']}"

    # PoP/YoY 仍 None
    assert result["comparison"]["period_over_period"]["current"] is None
    assert result["comparison"]["year_over_year"]["current"] is None


def test_competition_trend_emits_two_secondary_charts_when_ready():
    """Phase 2 T9: competition dim ready 时辅图 2 张：
    1) 评分差趋势 (line, 单 series = competitor_avg - own_avg)
    2) 差/好评率对比 (line, series = own_negative_rate, competitor_positive_rate)
    标题精确锁。"""
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = []
    for d in ["2026-04-10", "2026-04-12", "2026-04-15"]:
        labeled_reviews.append({"review": {"ownership": "own", "rating": 3,
                                            "date_published_parsed": d}})
        labeled_reviews.append({"review": {"ownership": "competitor", "rating": 4,
                                            "date_published_parsed": d}})
    result = _build_competition_trend("month", logical_day, labeled_reviews)
    assert result["status"] == "ready"

    secondary = result["secondary_charts"]
    assert len(secondary) >= 2

    titles = {c["title"] for c in secondary}
    assert "评分差趋势 (竞品 − 自有)" in titles, f"missing exact title: {titles}"
    assert "差/好评率对比" in titles, f"missing exact title: {titles}"

    for chart in secondary:
        assert set(chart.keys()) >= {"status", "chart_type", "title", "labels", "series"}


def test_competition_trend_emits_comparison_with_rating_gap():
    """Phase 2 T9: competition dim comparison.start_vs_end 度量为「评分差 (competitor - own)」。
    change_pct 语义：相对百分比变化（与 sentiment / issues / products dim 同口径）。"""
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    # 3 月 27（月初）：own=4, comp=4.5 → gap=0.5
    # 4 月 22（月末）：own=3, comp=4 → gap=1.0
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 4, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "competitor", "rating": 4.5, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "own", "rating": 3, "date_published_parsed": "2026-04-22"}},
        {"review": {"ownership": "competitor", "rating": 4, "date_published_parsed": "2026-04-22"}},
    ]
    result = _build_competition_trend("month", logical_day, labeled_reviews)
    sve = result["comparison"]["start_vs_end"]
    assert sve["start"] == 0.5, f"start gap=0.5 (4.5-4.0), got {sve['start']}"
    assert sve["end"] == 1.0, f"end gap=1.0 (4.0-3.0), got {sve['end']}"
    # change_pct: (1.0 - 0.5) / 0.5 * 100 = 100.0
    assert sve["change_pct"] == 100.0, \
        f"start=0.5 end=1.0, 相对变化应 100.0，得到 {sve['change_pct']}"

    # PoP/YoY 仍 None
    assert result["comparison"]["period_over_period"]["current"] is None
    assert result["comparison"]["year_over_year"]["current"] is None


def test_competition_trend_negative_gap_change_pct_keeps_sign():
    """Phase 2 T9 (Q1 regression lock): competition dim 的 change_pct 用 abs(start) 作分母，
    避免负 gap 时符号被静默翻转。
    场景: own 一直比竞品评分高（gap 始终为负）→ end 比 start 更负 = own 优势进一步扩大。
    用 abs(start)：(-1.0 − (-0.5)) / 0.5 * 100 = -100.0（gap 负向扩大 100%）。
    用 start：(-1.0 − (-0.5)) / -0.5 * 100 = +100.0（错误！会被理解为"差距收窄"）。"""
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    # 月初: own=4.5, comp=4.0 → gap = -0.5 (own 领先)
    # 月末: own=5.0, comp=4.0 → gap = -1.0 (own 领先扩大)
    labeled_reviews = [
        {"review": {"ownership": "own", "rating": 4.5, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "competitor", "rating": 4.0, "date_published_parsed": "2026-03-27"}},
        {"review": {"ownership": "own", "rating": 5.0, "date_published_parsed": "2026-04-22"}},
        {"review": {"ownership": "competitor", "rating": 4.0, "date_published_parsed": "2026-04-22"}},
    ]
    result = _build_competition_trend("month", logical_day, labeled_reviews)
    sve = result["comparison"]["start_vs_end"]
    assert sve["start"] == -0.5, f"start gap=-0.5, got {sve['start']}"
    assert sve["end"] == -1.0, f"end gap=-1.0, got {sve['end']}"
    # 关键：abs(start)=0.5 作分母，change_pct=-100.0 表示 gap 向 own 优势方向扩大 100%
    assert sve["change_pct"] == -100.0, \
        f"abs(start) 分母时 change_pct=-100.0；若误用 start 会变成 +100.0；得到 {sve['change_pct']}"


def test_trend_dimensions_use_correct_time_field():
    """Phase 2 T9 + 原始 plan T9 step 2:
    sentiment / issues / competition 必须基于 review.date_published_parsed (评论发布时间);
    products 必须基于 product_snapshot.scraped_at (抓取时间).

    关键防御：构造一条评论 date_published_parsed 在月窗口内、date_published 落到窗口外，
    若实现误用 date_published 而非 date_published_parsed，桶为空 → sentiment 变 accumulating。"""
    from qbu_crawler.server.report_analytics import (
        _build_sentiment_trend, _build_issue_trend,
        _build_product_trend,
    )
    from datetime import date

    logical_day = date(2026, 4, 24)

    # case 1: parsed 在窗口内 (2026-04-10)，原始 date_published 字段在窗口外 (2026-01-01)
    # 这能区分实现是用 date_published_parsed 还是 fallback 到 date_published
    review_published_parsed = {
        "ownership": "own",
        "rating": 1,
        "date_published_parsed": "2026-04-10",  # 月窗口内
        "date_published": "2026-01-01",          # 月窗口外（陷阱字段）
    }
    labeled_reviews = [
        {"review": review_published_parsed,
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}]},
    ]

    sentiment = _build_sentiment_trend("month", logical_day, labeled_reviews)
    assert sentiment["status"] == "ready", \
        "sentiment 必须优先用 date_published_parsed 落桶 → 落入 4 月 → ready；" \
        "若误读 date_published 会落到 1 月窗口外 → accumulating"

    issues = _build_issue_trend("month", logical_day, labeled_reviews)
    assert issues["status"] == "ready", \
        "issues 必须优先用 date_published_parsed 落桶（同 sentiment 口径）"

    # case 2: products 应基于 scraped_at（snapshot 字段），评论时间字段不影响
    snapshot_products = [
        {"sku": "A1", "name": "Prod A", "ownership": "own", "rating": 4.0,
         "review_count": 100, "scraped_at": "2026-04-24T08:00:00+08:00"},
    ]
    trend_series = [
        {
            "product_sku": "A1",
            # series 用的 date 字段对应 product_snapshots.scraped_at
            "series": [
                {"date": "2026-04-01", "rating": 3.8, "review_count": 90, "price": 99.0},
                {"date": "2026-04-23", "rating": 4.0, "review_count": 100, "price": 95.0},
            ],
        },
    ]
    products = _build_product_trend("month", logical_day, trend_series, snapshot_products)
    assert products["status"] == "ready", \
        "products 必须按 scraped_at（即 series[*].date）落桶"

    # case 3: 反向 trap — parsed=out-of-window + raw=in-window
    # 若实现误读 date_published 或做 fallback，会让评论被错误地纳入窗口 → ready
    # 正确实现应只读 date_published_parsed → 桶为空 → accumulating
    review_parsed_outside = {
        "ownership": "own",
        "rating": 1,
        "date_published_parsed": "2026-01-01",  # 月窗口外
        "date_published": "2026-04-10",          # 月窗口内（陷阱）
    }
    sentiment_neg = _build_sentiment_trend(
        "month", logical_day,
        [{"review": review_parsed_outside,
          "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}]}]
    )
    assert sentiment_neg["status"] == "accumulating", \
        "若实现 fallback 到 date_published，会让 review 错误落入 4 月窗口 → 测试失败"

    issues_neg = _build_issue_trend(
        "month", logical_day,
        [{"review": review_parsed_outside,
          "labels": [{"label_code": "quality_stability", "label_polarity": "negative"}]}]
    )
    assert issues_neg["status"] == "accumulating", \
        "issues 同口径：parsed 在窗口外则桶为空，不应 fallback"
