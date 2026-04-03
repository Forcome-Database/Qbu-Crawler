"""Tests for canonical metric and time semantics in the data layer."""

from __future__ import annotations

import json
import sqlite3

import pytest

from qbu_crawler import config, models
from qbu_crawler.server.scope import normalize_scope


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _insert_product(
    conn,
    *,
    url: str,
    site: str,
    name: str,
    sku: str,
    ownership: str,
    review_count: int,
    price: float,
    rating: float,
    scraped_at: str,
):
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, ownership, review_count, price, rating, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (url, site, name, sku, ownership, review_count, price, rating, scraped_at),
    )
    return conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()["id"]


def _insert_snapshot(conn, *, product_id: int, review_count: int, scraped_at: str):
    conn.execute(
        """
        INSERT INTO product_snapshots (product_id, review_count, scraped_at)
        VALUES (?, ?, ?)
        """,
        (product_id, review_count, scraped_at),
    )


def _insert_review(
    conn,
    *,
    product_id: int,
    author: str,
    headline: str,
    body: str,
    rating: int,
    date_published: str,
    scraped_at: str,
    images: list[str] | None = None,
):
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, images, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            author,
            headline,
            body,
            f"hash-{product_id}-{author}-{headline}",
            rating,
            date_published,
            json.dumps(images) if images is not None else None,
            scraped_at,
        ),
    )


@pytest.fixture()
def metric_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "metric-semantics.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()

    conn = _get_test_conn(db_file)
    own_product_id = _insert_product(
        conn,
        url="https://example.com/products/own",
        site="basspro",
        name="Own Product",
        sku="SKU-OWN",
        ownership="own",
        review_count=120,
        price=499.99,
        rating=4.6,
        scraped_at="2026-03-02 09:00:00",
    )
    competitor_product_id = _insert_product(
        conn,
        url="https://example.com/products/competitor",
        site="waltons",
        name="Competitor Product",
        sku="SKU-COMP",
        ownership="competitor",
        review_count=80,
        price=299.99,
        rating=4.2,
        scraped_at="2026-03-03 10:00:00",
    )

    _insert_snapshot(conn, product_id=own_product_id, review_count=100, scraped_at="2026-03-01 08:00:00")
    _insert_snapshot(conn, product_id=competitor_product_id, review_count=70, scraped_at="2026-03-01 08:30:00")

    _insert_review(
        conn,
        product_id=own_product_id,
        author="Alice",
        headline="Own review",
        body="solid",
        rating=2,
        date_published="2026-02-28",
        scraped_at="2026-03-02 12:00:00",
    )
    _insert_review(
        conn,
        product_id=competitor_product_id,
        author="Bob",
        headline="Competitor review",
        body="competitor body",
        rating=1,
        date_published="2026-03-01",
        scraped_at="2026-03-03 12:30:00",
        images=["https://img.example.com/1.jpg"],
    )
    _insert_review(
        conn,
        product_id=competitor_product_id,
        author="Cara",
        headline="Competitor review 2",
        body="competitor follow up",
        rating=2,
        date_published="2026-03-02",
        scraped_at="2026-03-03 13:00:00",
    )
    conn.commit()
    conn.close()
    return db_file


def test_get_stats_distinguishes_ingested_rows_from_site_reported_totals(metric_db):
    stats = models.get_stats()

    assert stats["product_count"] == 2
    assert stats["ingested_review_rows"] == 3
    assert stats["site_reported_review_total_current"] == 200

    # Backward-compatible aliases still point to the canonical values.
    assert stats["total_products"] == stats["product_count"]
    assert stats["total_reviews"] == stats["ingested_review_rows"]


def test_preview_scope_counts_distinguish_product_count_from_matched_review_product_count(metric_db):
    scope = normalize_scope(
        products={"sites": ["basspro", "waltons"]},
        reviews={"keyword": "competitor"},
        window={"since": "2026-03-01", "until": "2026-03-03"},
    )

    counts = models.preview_scope_counts(scope)

    assert counts["product_count"] == 2
    assert counts["matched_review_product_count"] == 1
    assert counts["ingested_review_rows"] == 2
    assert counts["image_review_rows"] == 1

    # Backward-compatible preview aliases stay available for existing callers.
    assert counts["matched_product_count"] == 1
    assert counts["matched_review_count"] == 2
    assert counts["matched_image_review_count"] == 1


def test_time_axis_helpers_expose_canonical_fields_and_latest_values(metric_db):
    time_axes = models.get_time_axis_semantics()

    assert time_axes["product_state_time"]["field"] == "products.scraped_at"
    assert time_axes["product_state_time"]["latest"] == "2026-03-03 10:00:00"
    assert time_axes["snapshot_time"]["field"] == "product_snapshots.scraped_at"
    assert time_axes["snapshot_time"]["latest"] == "2026-03-01 08:30:00"
    assert time_axes["review_ingest_time"]["field"] == "reviews.scraped_at"
    assert time_axes["review_ingest_time"]["latest"] == "2026-03-03 13:00:00"
    assert time_axes["review_publish_time"]["field"] == "reviews.date_published"
    assert time_axes["review_publish_time"]["latest"] == "2026-03-02"


def test_report_analytics_keeps_ingested_and_site_total_separate(metric_db):
    from qbu_crawler.server.report_analytics import build_report_analytics

    analytics = build_report_analytics(
        {
            "run_id": 999,
            "logical_date": "2026-03-03",
            "snapshot_hash": "hash-metrics",
            "products_count": 2,
            "reviews_count": 2,
            "translated_count": 2,
            "untranslated_count": 0,
            "products": [
                {
                    "name": "Own Product",
                    "sku": "SKU-OWN",
                    "site": "basspro",
                    "ownership": "own",
                    "review_count": 7,
                    "rating": 4.6,
                    "price": 499.99,
                },
                {
                    "name": "Competitor Product",
                    "sku": "SKU-COMP",
                    "site": "waltons",
                    "ownership": "competitor",
                    "review_count": 3,
                    "rating": 4.2,
                    "price": 299.99,
                },
            ],
            "reviews": [
                {
                    "product_name": "Own Product",
                    "product_sku": "SKU-OWN",
                    "author": "Alice",
                    "headline": "Broken",
                    "body": "The motor broke quickly.",
                    "rating": 2,
                    "date_published": "2026-03-02",
                    "images": [],
                    "ownership": "own",
                    "headline_cn": "",
                    "body_cn": "",
                    "translate_status": "done",
                },
                {
                    "product_name": "Competitor Product",
                    "product_sku": "SKU-COMP",
                    "author": "Bob",
                    "headline": "Easy",
                    "body": "Easy to use and worth the money.",
                    "rating": 5,
                    "date_published": "2026-03-02",
                    "images": [],
                    "ownership": "competitor",
                    "headline_cn": "",
                    "body_cn": "",
                    "translate_status": "done",
                },
            ],
        }
    )

    assert analytics["kpis"]["ingested_review_rows"] == 2
    assert analytics["kpis"]["site_reported_review_total_current"] == 10
