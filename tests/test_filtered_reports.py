"""Tests for filtered report generation paths."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qbu_crawler import config, models
from qbu_crawler.server.scope import normalize_scope


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def filtered_report_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "filtered-report.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    models.init_db()

    conn = _get_test_conn(db_file)
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/product/own",
            "basspro",
            "Own Grinder",
            "SKU-OWN",
            499.99,
            "in_stock",
            2,
            4.6,
            "own",
            "2026-03-01 08:00:00",
        ),
    )
    own_product_id = conn.execute("SELECT id FROM products WHERE sku = 'SKU-OWN'").fetchone()["id"]

    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/product/competitor",
            "meatyourmaker",
            "Competitor Mixer",
            "SKU-COMP",
            399.99,
            "in_stock",
            1,
            4.2,
            "competitor",
            "2026-03-01 08:30:00",
        ),
    )
    competitor_product_id = conn.execute("SELECT id FROM products WHERE sku = 'SKU-COMP'").fetchone()["id"]

    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at,
                             headline_cn, body_cn, translate_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            own_product_id,
            "Alice",
            "Good own review",
            "solid own product",
            "hash-own",
            5,
            "2026-03-01",
            json.dumps([]),
            "2026-03-05 09:00:00",
            "自有好评",
            "很好用",
            "done",
        ),
    )
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at,
                             headline_cn, body_cn, translate_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            competitor_product_id,
            "Bob",
            "Bad competitor review",
            "competitor issue",
            "hash-comp",
            2,
            "2026-03-05",
            json.dumps(["https://img.example.com/comp.jpg"]),
            "2026-03-05 10:00:00",
            "竞品差评",
            "表现一般",
            "done",
        ),
    )
    conn.commit()
    conn.close()

    return db_file


def test_query_scope_report_data_filters_products_and_reviews(filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)

    from qbu_crawler.server import report

    scope = normalize_scope(
        products={"ownership": ["competitor"]},
        reviews={"sentiment": "negative"},
        window={"since": "2026-03-05", "until": "2026-03-05"},
    )

    products, reviews = report.query_scope_report_data(scope)

    assert len(products) == 1
    assert products[0]["sku"] == "SKU-COMP"
    assert len(reviews) == 1
    assert reviews[0]["product_sku"] == "SKU-COMP"
    assert reviews[0]["headline"] == "Bad competitor review"


def test_send_filtered_report_reuses_legacy_email_contract(tmp_path, filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from qbu_crawler.server import report

    excel_path = tmp_path / "reports" / "filtered-report.xlsx"
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    excel_path.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(output_path or excel_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, attachment_path=None):
        captured["recipients"] = recipients
        captured["subject"] = subject
        captured["body_text"] = body_text
        captured["attachment_path"] = attachment_path
        return {"success": True, "error": None, "recipients": len(recipients)}

    monkeypatch.setattr(report, "_send_email_impl", fake_send_email)

    result = report.send_filtered_report(
        scope={
            "products": {"ownership": ["competitor"]},
            "reviews": {"sentiment": "negative"},
            "window": {"since": "2026-03-05", "until": "2026-03-05"},
        },
        delivery={
            "format": "email",
            "recipients": ["ops@example.com"],
        },
    )

    assert result["data"] == {
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
    }
    assert result["artifact"]["success"] is True
    assert result["artifact"]["excel_path"] == str(excel_path)
    assert result["email"] == {"success": True, "error": None, "recipients": 1}
    assert captured["subject"] == "【网评监控】Meat Your Maker 产品评论报告 2026-03-05"
    assert captured["body_text"] == (
        "各位好，\n\n"
        "附件是 2026-03-05 从 Meat Your Maker 抓取的最新产品网评报告，请查阅。\n\n"
        "【数据概览】\n"
        "  - 涉及产品：1 个（自有 0，竞品 1）\n"
        "  - 新增评论：1 条（已翻译 1 条）\n"
        "\n"
        "【差评预警】共 1 条差评（≤2星），请重点关注并更新改进措施。\n"
        "\n"
        "详细数据见附件 Excel（产品 + 评论两个 Sheet）。\n"
        "如有疑问请随时沟通，谢谢！\n"
    )
    assert captured["attachment_path"] == str(excel_path)


def test_send_filtered_report_can_generate_excel_without_email(tmp_path, filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from qbu_crawler.server import report

    excel_path = tmp_path / "reports" / "filtered-report.xlsx"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(output_path or excel_path),
    )

    result = report.send_filtered_report(
        scope={
            "products": {"skus": ["SKU-COMP"]},
            "reviews": {"sentiment": "negative"},
            "window": {"since": "2026-03-05", "until": "2026-03-05"},
        },
        delivery={"format": "excel"},
    )

    assert result["data"]["products_count"] == 1
    assert result["artifact"] == {
        "success": True,
        "format": "excel",
        "excel_path": str(excel_path),
    }
    assert result["email"] is None


def test_send_filtered_report_supports_url_scope_and_subject_override(tmp_path, filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from qbu_crawler.server import report

    excel_path = tmp_path / "reports" / "url-filtered-report.xlsx"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(output_path or excel_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, attachment_path=None):
        captured["recipients"] = recipients
        captured["subject"] = subject
        captured["body_text"] = body_text
        captured["attachment_path"] = attachment_path
        return {"success": True, "error": None, "recipients": len(recipients)}

    monkeypatch.setattr(report, "_send_email_impl", fake_send_email)

    result = report.send_filtered_report(
        scope={
            "products": {"urls": ["https://example.com/product/competitor"]},
            "reviews": {"sentiment": "negative"},
        },
        delivery={
            "format": "email",
            "recipients": ["ops@example.com"],
            "subject": "临时抓取结果：SKU-COMP",
        },
    )

    assert result["data"] == {
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
    }
    assert result["artifact"]["success"] is True
    assert result["email"] == {"success": True, "error": None, "recipients": 1}
    assert captured["recipients"] == ["ops@example.com"]
    assert captured["subject"] == "临时抓取结果：SKU-COMP"
    assert captured["attachment_path"] == str(excel_path)


def test_send_filtered_report_rejects_invalid_window(tmp_path, filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from qbu_crawler.server import report

    result = report.send_filtered_report(
        scope={
            "products": {"skus": ["SKU-COMP"]},
            "window": {"since": "not-a-date", "until": "2026-03-05"},
        },
        delivery={"format": "excel"},
    )

    assert result["artifact"]["success"] is False
    assert result["artifact"]["excel_path"] is None
    assert result["artifact"]["error"].startswith("Invalid scope window")
    assert result["email"] is None


def test_send_filtered_report_rejects_reversed_window(tmp_path, filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    from qbu_crawler.server import report

    result = report.send_filtered_report(
        scope={
            "products": {"skus": ["SKU-COMP"]},
            "window": {"since": "2026-03-06", "until": "2026-03-05"},
        },
        delivery={"format": "excel"},
    )

    assert result["artifact"]["success"] is False
    assert result["artifact"]["excel_path"] is None
    assert result["artifact"]["error"] == "Invalid scope window: since must be on or before until"
    assert result["email"] is None


def test_send_filtered_report_honors_empty_recipient_override(tmp_path, filtered_report_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", filtered_report_db)
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["fallback@example.com"])

    from qbu_crawler.server import report

    excel_path = tmp_path / "reports" / "filtered-report.xlsx"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(output_path or excel_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, attachment_path=None):
        captured["recipients"] = recipients
        return {"success": False, "error": "No recipients provided", "recipients": 0}

    monkeypatch.setattr(report, "_send_email_impl", fake_send_email)

    result = report.send_filtered_report(
        scope={
            "products": {"skus": ["SKU-COMP"]},
            "reviews": {"sentiment": "negative"},
            "window": {"since": "2026-03-05", "until": "2026-03-05"},
        },
        delivery={"format": "email", "recipients": []},
    )

    assert captured["recipients"] == []
    assert result["email"] == {"success": False, "error": "No recipients provided", "recipients": 0}
