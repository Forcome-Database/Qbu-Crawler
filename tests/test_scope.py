"""Tests for server-owned scope normalization and preview hints."""

import json
import sqlite3

import pytest

from qbu_crawler import config, models
from qbu_crawler.server.scope import normalize_scope, needs_preview, preview_hint


def test_normalize_scope_maps_simple_filters():
    scope = normalize_scope(
        products={"skus": ["SKU-1"], "ownership": ["own"]},
        reviews={"sentiment": "negative"},
        window={"since": "2026-03-01", "until": "2026-03-31"},
    )

    assert scope.products.skus == ["SKU-1"]
    assert scope.products.ownership == ["own"]
    assert scope.reviews.max_rating == 2
    assert scope.window.since == "2026-03-01"
    assert scope.window.until == "2026-03-31"


def test_normalize_scope_maps_product_urls():
    scope = normalize_scope(
        products={"urls": ["https://example.com/products/test"]},
    )

    assert scope.products.urls == ["https://example.com/products/test"]


def test_single_product_scope_does_not_need_preview():
    scope = normalize_scope(products={"skus": ["SKU-1"]})

    assert needs_preview(scope) is False
    assert preview_hint(scope) == "safe_to_continue"


def test_single_product_url_scope_does_not_need_preview():
    scope = normalize_scope(products={"urls": ["https://example.com/products/test"]})

    assert needs_preview(scope) is False
    assert preview_hint(scope) == "safe_to_continue"


def test_redundant_single_product_identifiers_do_not_need_preview():
    scope = normalize_scope(
        products={"ids": ["123"], "skus": ["SKU-1"], "names": ["Test Product"]},
    )

    assert needs_preview(scope) is False
    assert preview_hint(scope) == "safe_to_continue"


def test_multi_site_scope_needs_preview():
    scope = normalize_scope(products={"sites": ["basspro", "meatyourmaker"]})

    assert needs_preview(scope) is True
    assert preview_hint(scope) == "requires_confirmation"


def test_multi_ownership_scope_needs_preview():
    scope = normalize_scope(products={"ownership": ["own", "competitor"]})

    assert needs_preview(scope) is True
    assert preview_hint(scope) == "requires_confirmation"


def test_long_window_scope_needs_preview():
    scope = normalize_scope(
        products={"skus": ["SKU-1"]},
        window={"since": "2026-03-01", "until": "2026-03-09"},
    )

    assert needs_preview(scope) is True
    assert preview_hint(scope) == "requires_confirmation"


def test_invalid_window_scope_needs_preview():
    scope = normalize_scope(
        products={"skus": ["SKU-1"]},
        window={"since": "not-a-date", "until": "2026-03-31"},
    )

    assert needs_preview(scope) is True
    assert preview_hint(scope) == "requires_confirmation"


def test_reversed_window_scope_needs_preview():
    scope = normalize_scope(
        products={"skus": ["SKU-1"]},
        window={"since": "2026-03-10", "until": "2026-03-01"},
    )

    assert needs_preview(scope) is True
    assert preview_hint(scope) == "requires_confirmation"


def test_unsupported_artifact_returns_unsupported():
    scope = normalize_scope(products={"skus": ["SKU-1"]})

    assert preview_hint(scope, artifact_type="csv") == "unsupported"


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _insert_product(conn, *, url: str, site: str, name: str, sku: str, ownership: str, scraped_at: str):
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (url, site, name, sku, ownership, scraped_at),
    )
    return conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()["id"]


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
def scope_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "scope.db")
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
        scraped_at="2026-03-01 08:00:00",
    )
    competitor_product_id = _insert_product(
        conn,
        url="https://example.com/products/competitor",
        site="basspro",
        name="Competitor Product",
        sku="SKU-COMP",
        ownership="competitor",
        scraped_at="2026-03-01 08:30:00",
    )

    _insert_review(
        conn,
        product_id=own_product_id,
        author="Alice",
        headline="Great one",
        body="great product",
        rating=2,
        date_published="2026-03-01",
        scraped_at="2026-03-01 09:00:00",
        images=["https://img.example.com/1.jpg"],
    )
    _insert_review(
        conn,
        product_id=own_product_id,
        author="Bob",
        headline="Great two",
        body="great follow up",
        rating=1,
        date_published="2026-03-01",
        scraped_at="2026-03-01 10:00:00",
    )
    _insert_review(
        conn,
        product_id=own_product_id,
        author="Cara",
        headline="Great three",
        body="great again",
        rating=2,
        date_published="2026-03-01",
        scraped_at="2026-03-01 11:00:00",
        images=["https://img.example.com/3.jpg"],
    )
    _insert_review(
        conn,
        product_id=competitor_product_id,
        author="Dan",
        headline="Great competitor",
        body="great competitor product",
        rating=1,
        date_published="2026-03-01",
        scraped_at="2026-03-01 12:00:00",
        images=["https://img.example.com/competitor.jpg"],
    )
    _insert_review(
        conn,
        product_id=own_product_id,
        author="Eve",
        headline="Later own review",
        body="later negative review",
        rating=1,
        date_published="2026-03-05",
        scraped_at="2026-03-05 09:00:00",
    )
    conn.commit()
    conn.close()
    return db_file


def test_preview_scope_counts_and_image_rows_follow_scope_filters(scope_db):
    scope = normalize_scope(
        products={"sites": ["basspro"], "ownership": ["own"]},
        reviews={"sentiment": "negative", "keyword": "great"},
        window={"since": "2026-03-01", "until": "2026-03-01"},
    )

    counts = models.preview_scope_counts(scope)
    assert counts == {
        "product_count": 1,
        "ingested_review_rows": 3,
        "site_reported_review_total_current": 0,
        "matched_review_product_count": 1,
        "image_review_rows": 2,
        "matched_product_count": 1,
        "matched_review_count": 3,
        "matched_image_review_count": 2,
    }

    rows = models.list_review_images_for_scope(scope, limit=1)
    assert len(rows) == 1
    assert rows[0]["author"] == "Cara"
    assert rows[0]["product_name"] == "Own Product"
    assert rows[0]["product_site"] == "basspro"
    assert rows[0]["product_ownership"] == "own"
    assert rows[0]["images"] == ["https://img.example.com/3.jpg"]


def test_list_review_images_for_scope_respects_limit_and_empty_limit(scope_db):
    scope = normalize_scope(
        products={"sites": ["basspro"], "ownership": ["own"]},
        reviews={"sentiment": "negative", "keyword": "great"},
        window={"since": "2026-03-01", "until": "2026-03-01"},
    )

    assert models.list_review_images_for_scope(scope, limit=0) == []

    rows = models.list_review_images_for_scope(scope, limit=5)
    assert [row["author"] for row in rows] == ["Cara", "Alice"]
    assert all(isinstance(row["images"], list) for row in rows)


def test_preview_scope_counts_use_review_window_without_excluding_older_products(scope_db):
    scope = normalize_scope(
        products={"skus": ["SKU-OWN"]},
        reviews={"sentiment": "negative"},
        window={"since": "2026-03-05", "until": "2026-03-05"},
    )

    counts = models.preview_scope_counts(scope)
    assert counts == {
        "product_count": 1,
        "ingested_review_rows": 1,
        "site_reported_review_total_current": 0,
        "matched_review_product_count": 1,
        "image_review_rows": 0,
        "matched_product_count": 1,
        "matched_review_count": 1,
        "matched_image_review_count": 0,
    }


def test_preview_scope_counts_only_include_products_with_matching_reviews(scope_db):
    scope = normalize_scope(
        products={"sites": ["basspro"]},
        reviews={"sentiment": "negative", "keyword": "competitor"},
        window={"since": "2026-03-01", "until": "2026-03-01"},
    )

    counts = models.preview_scope_counts(scope)
    assert counts == {
        "product_count": 2,
        "ingested_review_rows": 1,
        "site_reported_review_total_current": 0,
        "matched_review_product_count": 1,
        "image_review_rows": 1,
        "matched_product_count": 1,
        "matched_review_count": 1,
        "matched_image_review_count": 1,
    }
