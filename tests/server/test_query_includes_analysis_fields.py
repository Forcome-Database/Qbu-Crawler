import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from qbu_crawler import models, config
from qbu_crawler.server import report


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Build a tiny DB and redirect models.get_conn / DB_PATH."""
    db_path = tmp_path / "qbu_test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    monkeypatch.setattr(models, "DB_PATH", str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            site TEXT, name TEXT, sku TEXT, price REAL,
            stock_status TEXT, review_count INTEGER, rating REAL,
            scraped_at TEXT, ownership TEXT
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            author TEXT, headline TEXT, body TEXT, body_hash TEXT,
            rating REAL, date_published TEXT, date_published_parsed TEXT,
            images TEXT, scraped_at TEXT,
            headline_cn TEXT, body_cn TEXT, translate_status TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        CREATE TABLE review_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL REFERENCES reviews(id),
            sentiment TEXT, sentiment_score REAL,
            labels TEXT, features TEXT,
            insight_cn TEXT, insight_en TEXT,
            llm_model TEXT, prompt_version TEXT, token_usage INTEGER,
            analyzed_at TEXT NOT NULL,
            impact_category TEXT, failure_mode TEXT
        );
        """
    )
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat(sep=" ", timespec="seconds")
    conn.execute(
        "INSERT INTO products (url,site,name,sku,price,stock_status,review_count,rating,scraped_at,ownership) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("https://example.com/p1", "demo", "Widget", "W1", 9.99, "in_stock", 10, 4.2, now, "own"),
    )
    conn.execute(
        "INSERT INTO reviews (product_id,author,headline,body,body_hash,rating,date_published,"
        "date_published_parsed,scraped_at,translate_status) VALUES (1,?,?,?,?,?,?,?,?,?)",
        ("Alice", "Headline", "Body text", "h1", 4.0, "2026-04-26", "2026-04-26", now, "skipped"),
    )
    conn.execute(
        "INSERT INTO review_analysis (review_id,sentiment,sentiment_score,labels,features,"
        "insight_cn,insight_en,prompt_version,analyzed_at,impact_category,failure_mode) "
        "VALUES (1,?,?,?,?,?,?,?,?,?,?)",
        ("negative", -0.5, "[]", "[]", "中文洞察", "english insight",
         "v1", now, "performance", "gear_failure"),
    )
    conn.commit()
    conn.close()
    yield db_path


def _has_field(rows, key):
    return rows and key in rows[0]


def test_cumulative_returns_failure_mode_and_impact(temp_db):
    products, reviews = report.query_cumulative_data()
    assert reviews, "fixture should produce at least one review"
    assert _has_field(reviews, "failure_mode")
    assert _has_field(reviews, "impact_category")
    assert reviews[0]["failure_mode"] == "gear_failure"
    assert reviews[0]["impact_category"] == "performance"


def test_report_window_returns_failure_mode_and_impact(temp_db):
    since = (datetime.utcnow() - timedelta(days=2)).isoformat(sep=" ", timespec="seconds")
    until = (datetime.utcnow() + timedelta(days=1)).isoformat(sep=" ", timespec="seconds")
    products, reviews = report.query_report_data(since, until)
    assert reviews, "fixture should produce at least one review in window"
    assert _has_field(reviews, "failure_mode")
    assert _has_field(reviews, "impact_category")
    assert reviews[0]["failure_mode"] == "gear_failure"
    assert reviews[0]["impact_category"] == "performance"


def test_review_without_analysis_returns_none_for_new_columns(temp_db, tmp_path):
    """LEFT JOIN must not drop reviews lacking analysis; the new columns return None."""
    # Add a second review with no analysis row
    conn = sqlite3.connect(str(temp_db))
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn.execute(
        "INSERT INTO reviews (product_id,author,headline,body,body_hash,rating,scraped_at,translate_status) "
        "VALUES (1,?,?,?,?,?,?,?)",
        ("Bob", "No analysis", "Body 2", "h2", 3.0, now, "skipped"),
    )
    conn.commit()
    conn.close()

    products, reviews = report.query_cumulative_data()
    no_analysis = [r for r in reviews if r["author"] == "Bob"]
    assert len(no_analysis) == 1
    assert no_analysis[0]["failure_mode"] is None
    assert no_analysis[0]["impact_category"] is None
