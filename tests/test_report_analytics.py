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
            "analysis_labels": '[{"severity": "high"}]',
            "product_sku": "SKU1",
            "rating": 1,
            "date_published": "2026-01-01",
        },
        {
            "ownership": "own",
            "sentiment": "negative",
            "analysis_features": '["手柄松动"]',
            "analysis_labels": '[{"severity": "medium"}]',
            "product_sku": "SKU2",
            "rating": 2,
            "date_published": "2026-02-01",
        },
    ]
    clusters = _build_feature_clusters(reviews, "own", "negative")
    assert clusters[0]["feature_display"] == "手柄松动"
    assert clusters[0]["review_count"] == 2
    assert clusters[0]["affected_product_count"] == 2
    assert clusters[0]["severity"] == "high"


def test_build_feature_clusters_positive_polarity():
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "competitor",
            "sentiment": "positive",
            "analysis_features": '["易操作", "外观好"]',
            "analysis_labels": '[{"severity": "low"}]',
            "product_sku": "COMP-1",
            "rating": 5,
            "date_published": "2026-03-01",
        },
    ]
    clusters = _build_feature_clusters(reviews, "competitor", "positive")
    assert len(clusters) == 2
    feature_names = [c["feature_display"] for c in clusters]
    assert "易操作" in feature_names
    assert "外观好" in feature_names


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
