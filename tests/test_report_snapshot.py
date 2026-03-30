"""Snapshot report tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def snapshot_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "snapshot.db")
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
            "https://example.com/product/1",
            "basspro",
            "Snapshot Product",
            "SKU-S1",
            39.99,
            "in_stock",
            1,
            4.0,
            "own",
            "2026-03-29 09:00:00",
        ),
    )
    product_id = conn.execute("SELECT id FROM products WHERE sku = 'SKU-S1'").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at,
                             headline_cn, body_cn, translate_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            "Alice",
            "Great",
            "Love it",
            "hash-1",
            5.0,
            "2026-03-28",
            json.dumps([]),
            "2026-03-29 09:05:00",
            "",
            "",
            "pending",
        ),
    )
    conn.commit()
    conn.close()

    run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "reporting",
            "logical_date": "2026-03-29",
            "trigger_key": "daily:2026-03-29:snapshot",
            "data_since": "2026-03-29T00:00:00+08:00",
            "data_until": "2026-03-30T00:00:00+08:00",
            "requested_by": "systemd",
            "service_version": "test",
        }
    )
    return {"db_file": db_file, "run": run, "tmp_path": tmp_path}


def test_freeze_report_snapshot_is_idempotent_for_same_run(snapshot_db):
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot

    first = freeze_report_snapshot(snapshot_db["run"]["id"], now="2026-03-29T12:00:00+08:00")
    second = freeze_report_snapshot(snapshot_db["run"]["id"], now="2026-03-29T12:05:00+08:00")

    assert first["snapshot_path"] == second["snapshot_path"]
    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert Path(first["snapshot_path"]).is_file()


def test_snapshot_artifact_content_is_stable_after_db_mutation(snapshot_db):
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot, load_report_snapshot

    frozen = freeze_report_snapshot(snapshot_db["run"]["id"], now="2026-03-29T12:00:00+08:00")
    before = load_report_snapshot(frozen["snapshot_path"])

    conn = _get_test_conn(snapshot_db["db_file"])
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/product/2",
            "basspro",
            "Late Product",
            "SKU-LATE",
            49.99,
            "in_stock",
            0,
            0,
            "competitor",
            "2026-03-29 10:00:00",
        ),
    )
    conn.execute(
        "UPDATE reviews SET headline_cn = '很好', body_cn = '非常喜欢', translate_status = 'done'"
    )
    conn.commit()
    conn.close()

    after = load_report_snapshot(frozen["snapshot_path"])

    assert after["snapshot_hash"] == before["snapshot_hash"]
    assert after["products_count"] == 1
    assert after["reviews_count"] == 1
    assert after["translated_count"] == 0


def test_fast_and_full_use_same_snapshot_hash(snapshot_db, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server.report_snapshot import (
        build_fast_report,
        freeze_report_snapshot,
        generate_full_report_from_snapshot,
        load_report_snapshot,
    )

    monkeypatch.setattr(report, "_download_and_resize", lambda url: None)

    frozen = freeze_report_snapshot(snapshot_db["run"]["id"], now="2026-03-29T12:00:00+08:00")
    snapshot = load_report_snapshot(frozen["snapshot_path"])

    fast = build_fast_report(snapshot)
    full = generate_full_report_from_snapshot(snapshot, send_email=False)

    assert fast["snapshot_hash"] == snapshot["snapshot_hash"]
    assert full["snapshot_hash"] == snapshot["snapshot_hash"]
    assert full["products_count"] == fast["products_count"] == 1
    assert full["reviews_count"] == fast["reviews_count"] == 1
