"""Tests for server/report.py"""

import json
import os
import smtplib
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qbu_crawler import models, config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def patch_db(tmp_path, monkeypatch):
    """Create a temp SQLite DB, init schema, insert one product + one review."""
    db_file = str(tmp_path / "test_products.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))

    models.init_db()

    conn = _get_test_conn(db_file)
    # Insert a product (scraped_at = now)
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            "https://example.com/product/1",
            "basspro",
            "Test Product",
            "SKU-001",
            49.99,
            "in_stock",
            5,
            4.5,
            "own",
        ),
    )
    conn.commit()

    product_id = conn.execute("SELECT id FROM products WHERE sku = 'SKU-001'").fetchone()["id"]

    images_json = json.dumps(["https://img.example.com/1.jpg"])
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            product_id,
            "John Doe",
            "Great product",
            "Really loved it, would buy again.",
            "abc123",
            5.0,
            "2026-03-01",
            images_json,
        ),
    )
    conn.commit()
    conn.close()

    yield db_file


def _get_test_conn(db_file: str):
    """Return a sqlite3 connection with Row factory pointing at db_file."""
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# query_report_data
# ---------------------------------------------------------------------------

def test_query_report_data(patch_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", patch_db)

    from qbu_crawler.server.report import query_report_data

    # Query from 1 hour ago — should capture the test data
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    products, reviews = query_report_data(since)

    assert len(products) == 1
    assert products[0]["name"] == "Test Product"
    assert products[0]["sku"] == "SKU-001"
    assert products[0]["site"] == "basspro"
    assert products[0]["ownership"] == "own"

    assert len(reviews) == 1
    assert reviews[0]["author"] == "John Doe"
    assert reviews[0]["headline"] == "Great product"
    assert reviews[0]["product_name"] == "Test Product"
    # images should be parsed from JSON
    assert isinstance(reviews[0]["images"], list)
    assert reviews[0]["images"][0] == "https://img.example.com/1.jpg"


def test_query_report_data_future_cutoff(patch_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", patch_db)

    from qbu_crawler.server.report import query_report_data

    # Query from 1 hour in the future — should return nothing
    since = datetime.now(timezone.utc) + timedelta(hours=1)
    products, reviews = query_report_data(since)

    assert products == []
    assert reviews == []


# ---------------------------------------------------------------------------
# generate_excel
# ---------------------------------------------------------------------------

def test_generate_excel(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    from qbu_crawler.server.report import generate_excel
    from openpyxl import load_workbook

    products = [
        {
            "url": "https://example.com/p/1",
            "name": "Test Product",
            "sku": "SKU-001",
            "price": 49.99,
            "stock_status": "in_stock",
            "rating": 4.5,
            "review_count": 10,
            "scraped_at": "2026-03-10 00:00:00",
            "site": "basspro",
            "ownership": "own",
        }
    ]
    reviews = [
        {
            "product_name": "Test Product",
            "author": "John Doe",
            "headline": "Great",
            "body": "Loved it",
            "headline_cn": "很棒",
            "body_cn": "喜欢",
            "rating": 5.0,
            "date_published": "2026-03-01",
            "images": ["https://img.example.com/1.jpg"],
        }
    ]

    report_date = datetime(2026, 3, 10, tzinfo=timezone.utc)
    filepath = generate_excel(products, reviews, report_date=report_date)

    assert os.path.isfile(filepath)
    assert filepath.endswith("scrape-report-2026-03-10.xlsx")

    wb = load_workbook(filepath)
    assert "产品" in wb.sheetnames
    assert "评论" in wb.sheetnames

    ws_p = wb["产品"]
    # Header row
    headers = [ws_p.cell(row=1, column=c).value for c in range(1, 11)]
    assert "产品地址" in headers
    assert "产品名称" in headers
    assert "SKU" in headers

    # Data row
    assert ws_p.cell(row=2, column=1).value == "https://example.com/p/1"
    assert ws_p.cell(row=2, column=2).value == "Test Product"

    ws_r = wb["评论"]
    r_headers = [ws_r.cell(row=1, column=c).value for c in range(1, 10)]
    assert "产品名称" in r_headers
    assert "标题（中文）" in r_headers
    # images list serialised to JSON string
    images_cell = ws_r.cell(row=2, column=9).value
    assert "img.example.com" in images_cell


def test_generate_excel_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    from qbu_crawler.server.report import generate_excel
    from openpyxl import load_workbook

    report_date = datetime(2026, 3, 10, tzinfo=timezone.utc)
    filepath = generate_excel([], [], report_date=report_date)

    assert os.path.isfile(filepath)
    wb = load_workbook(filepath)
    assert "产品" in wb.sheetnames
    assert "评论" in wb.sheetnames

    ws_p = wb["产品"]
    # Only header row, no data
    assert ws_p.max_row == 1
    assert ws_p.cell(row=1, column=1).value == "产品地址"

    ws_r = wb["评论"]
    assert ws_r.max_row == 1
    assert ws_r.cell(row=1, column=1).value == "产品名称"


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------

def test_send_email_success(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(config, "SMTP_FROM", "sender@example.com")
    monkeypatch.setattr(config, "SMTP_USE_SSL", False)

    mock_smtp_instance = MagicMock()

    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        from qbu_crawler.server.report import send_email

        result = send_email(
            recipients=["recipient@example.com"],
            subject="Test Subject",
            body_text="Hello World",
        )

    assert result["success"] is True
    assert result["error"] is None
    assert result["recipients"] == 1
    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("user@example.com", "secret")
    mock_smtp_instance.sendmail.assert_called_once()
    mock_smtp_instance.quit.assert_called_once()


def test_send_email_ssl(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 465)
    monkeypatch.setattr(config, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(config, "SMTP_FROM", "sender@example.com")
    monkeypatch.setattr(config, "SMTP_USE_SSL", True)

    mock_smtp_instance = MagicMock()

    with patch("smtplib.SMTP_SSL", return_value=mock_smtp_instance):
        from qbu_crawler.server.report import send_email

        result = send_email(
            recipients=["recipient@example.com"],
            subject="Test",
            body_text="Body",
        )

    assert result["success"] is True
    # No STARTTLS for SSL connections
    mock_smtp_instance.starttls.assert_not_called()


def test_send_email_no_config(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")

    from qbu_crawler.server.report import send_email

    result = send_email(
        recipients=["recipient@example.com"],
        subject="Test",
        body_text="Hello",
    )

    assert result["success"] is False
    assert "SMTP_HOST" in result["error"]
    assert result["recipients"] == 0


def test_send_email_no_recipients(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")

    from qbu_crawler.server.report import send_email

    result = send_email(recipients=[], subject="Test", body_text="Hello")

    assert result["success"] is False
    assert result["recipients"] == 0


def test_send_email_smtp_error(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    monkeypatch.setattr(config, "SMTP_FROM", "")
    monkeypatch.setattr(config, "SMTP_USE_SSL", False)

    with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("Connection refused")):
        from qbu_crawler.server.report import send_email

        result = send_email(
            recipients=["r@example.com"],
            subject="Test",
            body_text="Hello",
        )

    assert result["success"] is False
    assert "Connection refused" in result["error"]
    assert result["recipients"] == 0


# ---------------------------------------------------------------------------
# load_email_recipients
# ---------------------------------------------------------------------------

def test_load_email_recipients(tmp_path):
    from qbu_crawler.server.report import load_email_recipients

    recipients_file = tmp_path / "recipients.txt"
    recipients_file.write_text(
        "# Comment line\n"
        "alice@example.com\n"
        "bob@example.com\n"
        "\n"
        "# Another comment\n"
        "carol@example.com\n",
        encoding="utf-8",
    )

    result = load_email_recipients(str(recipients_file))
    assert result == ["alice@example.com", "bob@example.com", "carol@example.com"]


def test_load_email_recipients_missing_file():
    from qbu_crawler.server.report import load_email_recipients

    result = load_email_recipients("/nonexistent/path/recipients.txt")
    assert result == []


# ---------------------------------------------------------------------------
# generate_report (full pipeline)
# ---------------------------------------------------------------------------

def test_generate_report_full(patch_db, tmp_path, monkeypatch):
    """Full pipeline — translation comes from DB, not inline."""
    monkeypatch.setattr(config, "DB_PATH", patch_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from qbu_crawler.server.report import generate_report

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = generate_report(since, send_email=False)

    assert result["products_count"] == 1
    assert result["reviews_count"] == 1
    assert result["translated_count"] == 0
    assert result["untranslated_count"] == 1
    assert os.path.isfile(result["excel_path"])
    assert result["email"] is None


def test_generate_report_with_pretranslated_reviews(patch_db, tmp_path, monkeypatch):
    """Pipeline reads pre-translated data from DB."""
    monkeypatch.setattr(config, "DB_PATH", patch_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    import sqlite3
    conn = sqlite3.connect(patch_db)
    conn.execute(
        "UPDATE reviews SET headline_cn = '好产品', body_cn = '非常喜欢', translate_status = 'done'"
    )
    conn.commit()
    conn.close()

    from qbu_crawler.server.report import generate_report

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = generate_report(since, send_email=False)

    assert result["reviews_count"] == 1
    assert result["translated_count"] == 1
    assert result["untranslated_count"] == 0


def test_generate_report_with_email(patch_db, tmp_path, monkeypatch):
    """Email fails gracefully when SMTP not configured."""
    monkeypatch.setattr(config, "DB_PATH", patch_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "SMTP_HOST", "")  # no SMTP
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["test@example.com"])

    from qbu_crawler.server.report import generate_report

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = generate_report(since, send_email=True)

    # Should not raise
    assert result["products_count"] == 1
    assert result["email"] is not None
    assert result["email"]["success"] is False
    assert "SMTP_HOST" in result["email"]["error"]


def test_generate_report_email_no_recipients(patch_db, tmp_path, monkeypatch):
    """Email is skipped gracefully when no recipients configured."""
    monkeypatch.setattr(config, "DB_PATH", patch_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    monkeypatch.setattr(config, "SMTP_FROM", "")
    monkeypatch.setattr(config, "SMTP_USE_SSL", False)
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", [])

    from qbu_crawler.server.report import generate_report

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = generate_report(since, send_email=True)

    # No recipients → send_email returns error, but generate_report doesn't raise
    assert result["email"] is not None
    assert result["email"]["success"] is False
