import sqlite3

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def trend_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "historical-trends.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


def _insert_product(conn, *, url, site, sku, ownership, name=None):
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            site,
            name or sku,
            sku,
            99.99,
            "in_stock",
            10,
            4.2,
            ownership,
            "2026-04-29 09:00:00",
        ),
    )
    return conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()["id"]


def _insert_review(conn, *, product_id, headline, rating, published, scraped_at):
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, date_published_parsed,
                             images, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            "Tester",
            headline,
            headline,
            headline,
            rating,
            published,
            published,
            "[]",
            scraped_at,
        ),
    )


def _insert_snapshot(conn, *, product_id, rating, review_count, scraped_at):
    conn.execute(
        """
        INSERT INTO product_snapshots (product_id, price, stock_status,
                                      review_count, rating, ratings_only_count,
                                      scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (product_id, 99.99, "in_stock", review_count, rating, 0, scraped_at),
    )


def test_query_trend_history_reviews_excludes_future_rows(trend_db):
    from qbu_crawler.server import report

    conn = _get_test_conn(trend_db)
    own_id = _insert_product(
        conn,
        url="https://example.com/own",
        site="basspro",
        sku="SKU-OWN",
        ownership="own",
    )
    _insert_snapshot(conn, product_id=own_id, rating=4.0, review_count=8, scraped_at="2026-04-29 09:00:00")
    _insert_review(conn, product_id=own_id, headline="current", rating=5, published="2026-04-29", scraped_at="2026-04-29 10:00:00")
    _insert_review(conn, product_id=own_id, headline="previous", rating=4, published="2026-03-29", scraped_at="2026-04-01 10:00:00")
    _insert_review(conn, product_id=own_id, headline="future publish", rating=2, published="2026-05-01", scraped_at="2026-04-29 10:00:00")
    _insert_review(conn, product_id=own_id, headline="future ingest", rating=1, published="2026-04-01", scraped_at="2026-05-01 10:00:00")
    conn.commit()
    conn.close()

    products, reviews = report.query_trend_history(
        until="2026-04-30T00:00:00+08:00",
        lookback_days=730,
    )

    assert [product["sku"] for product in products] == ["SKU-OWN"]
    assert {review["headline"] for review in reviews} == {"current", "previous"}
    assert all(str(review["date_published_parsed"]) < "2026-04-30" for review in reviews)
    assert all(str(review["scraped_at"]) < "2026-04-30 00:00:00" for review in reviews)


def test_get_product_snapshots_until_excludes_future_rows_and_same_sku_other_site(trend_db):
    conn = _get_test_conn(trend_db)
    own_id = _insert_product(
        conn,
        url="https://example.com/product-1",
        site="basspro",
        sku="SKU-1",
        ownership="own",
    )
    other_id = _insert_product(
        conn,
        url="https://other.example.com/product-1",
        site="meatyourmaker",
        sku="SKU-1",
        ownership="competitor",
    )
    _insert_snapshot(conn, product_id=own_id, rating=4.1, review_count=10, scraped_at="2026-04-15 09:00:00")
    _insert_snapshot(conn, product_id=own_id, rating=4.0, review_count=12, scraped_at="2026-04-29 09:00:00")
    _insert_snapshot(conn, product_id=own_id, rating=3.9, review_count=14, scraped_at="2026-05-01 09:00:00")
    _insert_snapshot(conn, product_id=other_id, rating=1.0, review_count=99, scraped_at="2026-04-20 09:00:00")
    conn.commit()
    conn.close()

    rows = models.get_product_snapshots_until(
        product_url="https://example.com/product-1",
        until="2026-04-30T00:00:00+08:00",
        days=30,
    )

    assert [row["scraped_at"][:10] for row in rows] == ["2026-04-15", "2026-04-29"]
    assert [row["rating"] for row in rows] == [4.1, 4.0]


def test_build_historical_product_trend_series_uses_report_until(monkeypatch):
    from qbu_crawler.server import report_analytics

    called = {}

    def fake_get_product_snapshots_until(product_url=None, until=None, days=30, sku=None, site=None):
        called[(product_url, sku, site, until, days)] = True
        return [{"scraped_at": "2026-04-29 09:00:00", "rating": 4.1, "review_count": 10}]

    monkeypatch.setattr(models, "get_product_snapshots_until", fake_get_product_snapshots_until)

    series = report_analytics.build_historical_product_trend_series(
        [{"url": "https://example.com/product-1", "sku": "SKU-1", "site": "basspro", "name": "Product 1"}],
        until="2026-04-30T00:00:00+08:00",
        days=30,
    )

    assert called[("https://example.com/product-1", "SKU-1", "basspro", "2026-04-30T00:00:00+08:00", 30)]
    assert series[0]["series"][0]["date"] == "2026-04-29 09:00:00"
