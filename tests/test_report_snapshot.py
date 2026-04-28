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
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import (
        build_fast_report,
        freeze_report_snapshot,
        generate_full_report_from_snapshot,
        load_report_snapshot,
    )

    monkeypatch.setattr(report, "_download_image_data", lambda url: None)
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(snapshot_db["tmp_path"] / "full.html"),
    )

    frozen = freeze_report_snapshot(snapshot_db["run"]["id"], now="2026-03-29T12:00:00+08:00")
    snapshot = load_report_snapshot(frozen["snapshot_path"])

    fast = build_fast_report(snapshot)
    full = generate_full_report_from_snapshot(snapshot, send_email=False)

    assert fast["snapshot_hash"] == snapshot["snapshot_hash"]
    assert full["snapshot_hash"] == snapshot["snapshot_hash"]
    assert full["products_count"] == fast["products_count"] == 1
    assert full["reviews_count"] == fast["reviews_count"] == 1


def test_generate_full_report_from_snapshot_uses_deep_report_email_template(tmp_path, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(
        config,
        "EMAIL_RECIPIENTS",
        ["leo.xia@forcome.com", "howard.yang@forcome.com", "chloe.tu@forcome.com"],
    )

    excel_path = tmp_path / "workflow-run-1-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {
            "mode": "baseline",
            "kpis": {
                "product_count": 40,
                "own_product_count": 13,
                "competitor_product_count": 27,
                "ingested_review_rows": 2345,
                "own_review_rows": 736,
                "competitor_review_rows": 1609,
                "image_review_rows": 112,
                "low_rating_review_rows": 236,
                "translated_count": 2345,
                "untranslated_count": 0,
            },
            "self": {
                "risk_products": [
                    {
                        "product_name": "Own Stuffer",
                        "product_sku": "OWN-1",
                        "negative_review_rows": 25,
                        "image_review_rows": 4,
                        "top_labels": [
                            {"label_code": "quality_stability", "count": 11},
                            {"label_code": "structure_design", "count": 7},
                        ],
                    }
                ],
                "top_negative_clusters": [
                    {
                        "label_code": "quality_stability",
                        "review_count": 18,
                        "image_review_count": 3,
                        "severity": "high",
                    }
                ],
                "recommendations": [
                    {
                        "label_code": "quality_stability",
                        "priority": "high",
                        "possible_cause_boundary": "可能与核心部件耐久性有关",
                        "improvement_direction": "优先复核高频失效部件寿命",
                        "evidence_count": 18,
                    }
                ],
            },
            "competitor": {
                "top_positive_themes": [
                    {
                        "label_code": "easy_to_use",
                        "review_count": 33,
                        "image_review_count": 2,
                    }
                ],
                "benchmark_examples": [
                    {
                        "product_name": "Competitor Grinder",
                        "product_sku": "COMP-1",
                        "label_codes": ["easy_to_use", "easy_to_clean"],
                        "headline_cn": "简单好用",
                        "body_cn": "安装方便，清洁也很轻松。",
                        "headline": "Simple and easy",
                        "body": "Easy to use and clean.",
                    }
                ],
                "negative_opportunities": [
                    {
                        "product_name": "Competitor Grinder",
                        "product_sku": "COMP-2",
                        "label_codes": ["packaging_shipping"],
                    }
                ],
            },
            "appendix": {},
        },
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None: {
            "hero_headline": "",
            "executive_summary": "",
            "executive_bullets": [],
            "improvement_priorities": [],
            "competitive_insight": "",
        },
    )
    html_report_path = tmp_path / "workflow-run-1-full-report.html"
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(html_report_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, body_html=None, attachment_path=None, attachment_paths=None):
        captured["recipients"] = recipients
        captured["subject"] = subject
        captured["body_text"] = body_text
        captured["attachment_path"] = attachment_path
        captured["attachment_paths"] = attachment_paths
        return {"success": True, "error": None, "recipients": len(recipients)}

    monkeypatch.setattr(report, "send_email", fake_send_email)

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-03-27",
        "data_since": "2026-03-27T00:00:00+08:00",
        "snapshot_hash": "hash-legacy",
        "products_count": 40,
        "reviews_count": 2345,
        "translated_count": 2345,
        "untranslated_count": 0,
        "products": (
            [{"site": "basspro", "ownership": "own"} for _ in range(13)]
            + [{"site": "meatyourmaker", "ownership": "competitor"} for _ in range(14)]
            + [{"site": "waltons", "ownership": "competitor"} for _ in range(13)]
        ),
        "reviews": [{"rating": 2, "translate_status": "done"} for _ in range(236)]
        + [{"rating": 5, "translate_status": "done"} for _ in range(2345 - 236)],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    assert result["email"] == {"success": True, "error": None, "recipients": 3}
    assert "产品评论日报" in captured["subject"]
    assert "2026-03-27" in captured["subject"]
    assert "Own Stuffer" in captured["subject"]
    assert "需要关注" in captured["body_text"]
    assert captured["attachment_path"] is None
    paths = captured["attachment_paths"]
    assert paths[0] == str(excel_path)
    assert paths[1] == str(html_report_path)
    assert len(paths) == 2


def test_generate_full_report_from_snapshot_returns_analytics_and_html_paths(tmp_path, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    excel_path = tmp_path / "workflow-run-1-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_report_path = tmp_path / "workflow-run-1-full-report.html"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None: {
            "hero_headline": "",
            "executive_summary": "",
            "executive_bullets": [],
            "improvement_priorities": [],
            "competitive_insight": "",
        },
    )
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(html_report_path),
    )

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-03-27",
        "data_since": "2026-03-27T00:00:00+08:00",
        "snapshot_hash": "hash-analytics",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=False, output_path=str(excel_path))

    # Stage B 修 7: artifact paths are now relative (to REPORT_DIR for analytics,
    # to their own parent dir for stub html in tmp_path). Resolve via REPORT_DIR
    # for analytics and via tmp_path for html since the stub returns tmp_path-rooted.
    assert result["analytics_path"].endswith(".json")
    assert result["pdf_path"] is None
    assert (Path(html_report_path).parent / result["html_path"]).resolve() == Path(html_report_path).resolve()
    assert (Path(config.REPORT_DIR) / result["analytics_path"]).is_file()


def test_generate_full_report_from_snapshot_passes_insights_to_html_and_email(tmp_path, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])
    excel_path = tmp_path / "workflow-run-9-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_report_path = tmp_path / "workflow-run-9-full-report.html"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {
            "mode": "baseline",
            "kpis": {},
            "self": {"top_negative_clusters": [{"label_code": "quality_stability", "example_reviews": [{"id": 1}]}]},
            "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
            "appendix": {"image_reviews": [{"id": 2}]},
        },
    )

    captured = {}

    def fake_generate_report_insights(analytics, snapshot=None):
        captured["analytics_for_insights"] = analytics
        return {
            "hero_headline": "聚焦可靠性",
            "executive_summary": "测试摘要",
            "executive_bullets": ["要点一"],
            "improvement_priorities": [],
            "competitive_insight": "",
        }

    monkeypatch.setattr(report_snapshot.report_llm, "generate_report_insights_with_validation", fake_generate_report_insights)

    def fake_render_v3_html(snapshot, analytics, output_path=None):
        captured["html_analytics"] = analytics
        return str(html_report_path)

    monkeypatch.setattr(report_snapshot.report_html, "render_v3_html", fake_render_v3_html)

    def fake_build_email(snapshot, analytics):
        captured["email_analytics"] = analytics
        return "subject", "body"

    monkeypatch.setattr(report, "build_daily_deep_report_email", fake_build_email)
    monkeypatch.setattr(
        report,
        "send_email",
        lambda recipients, subject, body_text, body_html=None, attachment_path=None, attachment_paths=None: {
            "success": True,
            "error": None,
            "recipients": len(recipients),
        },
    )

    snapshot = {
        "run_id": 9,
        "logical_date": "2026-03-29",
        "data_since": "2026-03-29T00:00:00+08:00",
        "snapshot_hash": "hash-merged",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"id": 1, "rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    # Stage B 修 7: artifact paths are now relative; resolve via parent for assertion.
    assert (Path(html_report_path).parent / result["html_path"]).resolve() == Path(html_report_path).resolve()
    # The analytics passed to HTML renderer should have report_copy from generate_report_insights
    assert captured["html_analytics"]["report_copy"]["hero_headline"] == "聚焦可靠性"
    # The analytics JSON should be persisted with the insights
    saved = json.loads((Path(config.REPORT_DIR) / result["analytics_path"]).read_text(encoding="utf-8"))
    assert saved["report_copy"]["hero_headline"] == "聚焦可靠性"


def test_generate_full_report_from_snapshot_sends_excel_and_html(monkeypatch, tmp_path):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])

    excel_path = tmp_path / "workflow-run-2-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_report_path = tmp_path / "workflow-run-2-full-report.html"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None: {"hero_headline": "", "executive_summary": "", "executive_bullets": [], "improvement_priorities": [], "competitive_insight": ""},
    )
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(html_report_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, body_html=None, attachment_path=None, attachment_paths=None):
        captured["attachment_path"] = attachment_path
        captured["attachment_paths"] = attachment_paths
        return {"success": True, "error": None, "recipients": len(recipients)}

    monkeypatch.setattr(report, "send_email", fake_send_email)

    snapshot = {
        "run_id": 2,
        "logical_date": "2026-03-28",
        "data_since": "2026-03-28T00:00:00+08:00",
        "snapshot_hash": "hash-email",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    assert result["pdf_path"] is None
    # Stage B 修 7: artifact paths are now relative; resolve via parent for assertion.
    assert (Path(html_report_path).parent / result["html_path"]).resolve() == Path(html_report_path).resolve()
    assert captured["attachment_path"] is None
    paths = captured["attachment_paths"]
    assert paths[0] == str(excel_path)
    assert paths[1] == str(html_report_path)
    assert len(paths) == 2


def test_generate_full_report_from_snapshot_returns_email_failure_with_partial_artifacts(
    monkeypatch,
    tmp_path,
):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])

    excel_path = tmp_path / "workflow-run-3-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_report_path = tmp_path / "workflow-run-3-full-report.html"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None: {"hero_headline": "", "executive_summary": "", "executive_bullets": [], "improvement_priorities": [], "competitive_insight": ""},
    )
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(html_report_path),
    )
    monkeypatch.setattr(
        report,
        "send_email",
        lambda recipients, subject, body_text, body_html=None, attachment_path=None, attachment_paths=None: {
            "success": False,
            "error": "smtp failed",
            "recipients": 0,
        },
    )

    snapshot = {
        "run_id": 3,
        "logical_date": "2026-03-29",
        "data_since": "2026-03-29T00:00:00+08:00",
        "snapshot_hash": "hash-email-fail",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    assert result["email"] == {"success": False, "error": "smtp failed", "recipients": 0}
    # Stage B 修 7: artifact paths are now relative; resolve via parent for assertion.
    assert (Path(excel_path).parent / result["excel_path"]).resolve() == Path(excel_path).resolve()
    assert result["pdf_path"] is None
    assert (Path(html_report_path).parent / result["html_path"]).resolve() == Path(html_report_path).resolve()
    assert result["analytics_path"].endswith(".json")


def test_generate_full_report_from_snapshot_captures_email_exception_with_partial_artifacts(
    monkeypatch,
    tmp_path,
):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])

    excel_path = tmp_path / "workflow-run-4-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_report_path = tmp_path / "workflow-run-4-full-report.html"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None: {"hero_headline": "", "executive_summary": "", "executive_bullets": [], "improvement_priorities": [], "competitive_insight": ""},
    )
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(html_report_path),
    )

    def _raise_send_email(recipients, subject, body_text, body_html=None, attachment_path=None, attachment_paths=None):
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr(report, "send_email", _raise_send_email)

    snapshot = {
        "run_id": 4,
        "logical_date": "2026-03-29",
        "data_since": "2026-03-29T00:00:00+08:00",
        "snapshot_hash": "hash-email-exception",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    assert result["email"] == {"success": False, "error": "smtp exploded", "recipients": 0}
    # Stage B 修 7: artifact paths are now relative; resolve via parent for assertion.
    assert (Path(excel_path).parent / result["excel_path"]).resolve() == Path(excel_path).resolve()
    assert result["pdf_path"] is None
    assert (Path(html_report_path).parent / result["html_path"]).resolve() == Path(html_report_path).resolve()


def test_freeze_snapshot_reviews_enriched_with_analysis_fields(snapshot_db):
    """After freezing, snapshot reviews contain analysis_features when review_analysis exists."""
    import json
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot
    from qbu_crawler import models

    run_id = snapshot_db["run"]["id"]

    # Get review id from DB (snapshot_db fixture inserts exactly one review)
    conn = _get_test_conn(snapshot_db["db_file"])
    review_id = conn.execute("SELECT id FROM reviews LIMIT 1").fetchone()["id"]
    conn.close()

    # Insert a review_analysis record
    models.save_review_analysis(
        review_id=review_id,
        sentiment="negative",
        sentiment_score=0.9,
        labels=[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}],
        features=["手柄松动"],
        insight_cn="产品质量问题",
        insight_en="quality issue",
        llm_model="gpt-4o-mini",
        prompt_version="v1",
        token_usage=100,
    )

    run = freeze_report_snapshot(run_id)
    from pathlib import Path
    snapshot = json.loads(Path(run["snapshot_path"]).read_text(encoding="utf-8"))

    enriched = [r for r in snapshot["reviews"] if r.get("id") == review_id]
    assert enriched, "review not found in snapshot"
    r = enriched[0]
    assert r.get("analysis_features") is not None, "analysis_features should be set after enrichment"
    assert "手柄松动" in (r.get("analysis_features") or "")


def test_generate_full_report_from_snapshot_allows_none_email_result(monkeypatch, tmp_path):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])

    excel_path = tmp_path / "workflow-run-5-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_report_path = tmp_path / "workflow-run-5-full-report.html"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None: {"hero_headline": "", "executive_summary": "", "executive_bullets": [], "improvement_priorities": [], "competitive_insight": ""},
    )
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(html_report_path),
    )
    monkeypatch.setattr(
        report,
        "send_email",
        lambda recipients, subject, body_text, body_html=None, attachment_path=None, attachment_paths=None: None,
    )

    snapshot = {
        "run_id": 5,
        "logical_date": "2026-03-29",
        "data_since": "2026-03-29T00:00:00+08:00",
        "snapshot_hash": "hash-email-none",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    assert result["email"] is None
    # Stage B 修 7: artifact paths are now relative; resolve via parent for assertion.
    assert (Path(excel_path).parent / result["excel_path"]).resolve() == Path(excel_path).resolve()
    assert result["pdf_path"] is None
    assert (Path(html_report_path).parent / result["html_path"]).resolve() == Path(html_report_path).resolve()


def test_change_and_quiet_report_return_none_email_when_send_email_false(
    snapshot_db, monkeypatch, tmp_path,
):
    """When send_email=False, change/quiet reports should return email=None,
    not {success: False} which would be misinterpreted as a send failure."""
    from qbu_crawler.server.report_snapshot import (
        _generate_change_report,
        _generate_quiet_report,
    )

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    snapshot = {
        "run_id": 99,
        "logical_date": "2026-04-14",
        "products_count": 41,
        "reviews_count": 0,
        "products": [],
        "reviews": [],
    }

    # _generate_change_report with send_email=False
    change_result = _generate_change_report(
        snapshot, send_email=False, prev_analytics=None,
        context={"changes": {"has_changes": True, "price_changes": []}},
    )
    assert change_result["email"] is None, (
        "change report with send_email=False should return email=None, not {success: False}"
    )

    # _generate_quiet_report with send_email=False
    quiet_result = _generate_quiet_report(snapshot, send_email=False, prev_analytics=None)
    assert quiet_result["email"] is None, (
        "quiet report with send_email=False should return email=None, not {success: False}"
    )


# ---------------------------------------------------------------------------
# Tests for get_email_recipients (Fix-7: unified recipient source)
# ---------------------------------------------------------------------------


def test_get_email_recipients_prefers_env_var(monkeypatch):
    """When config.EMAIL_RECIPIENTS is set, it should be returned directly."""
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr("qbu_crawler.config.EMAIL_RECIPIENTS", ["a@test.com", "b@test.com"])
    result = report_snapshot.get_email_recipients()
    assert result == ["a@test.com", "b@test.com"]


def test_get_email_recipients_falls_back_to_file(monkeypatch, tmp_path):
    """When config.EMAIL_RECIPIENTS is empty, read from file."""
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr("qbu_crawler.config.EMAIL_RECIPIENTS", [])
    recipients_file = tmp_path / "email_recipients.txt"
    recipients_file.write_text("c@test.com\n# comment\nd@test.com\n", encoding="utf-8")
    monkeypatch.setattr(
        report_snapshot, "_RECIPIENTS_FILE_PATH",
        str(recipients_file),
    )
    result = report_snapshot.get_email_recipients()
    assert result == ["c@test.com", "d@test.com"]


def test_get_email_recipients_returns_empty_when_no_source(monkeypatch, tmp_path):
    """When both sources are empty, return empty list."""
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr("qbu_crawler.config.EMAIL_RECIPIENTS", [])
    monkeypatch.setattr(
        report_snapshot, "_RECIPIENTS_FILE_PATH",
        str(tmp_path / "nonexistent.txt"),
    )
    result = report_snapshot.get_email_recipients()
    assert result == []


# ---------------------------------------------------------------------------
# Tests for dual-perspective snapshot (P007 Task 2)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dual_snapshot_db(tmp_path, monkeypatch):
    """DB with 1 product and 2 reviews across 2 days; workflow window = day 2 only."""
    db_file = str(tmp_path / "dual.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "REPORT_PERSPECTIVE", "dual")

    models.init_db()

    conn = _get_test_conn(db_file)
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status,
                              review_count, rating, ownership, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/product/dual-1",
            "basspro",
            "Dual Product",
            "SKU-DUAL-1",
            49.99,
            "in_stock",
            2,
            4.5,
            "own",
            "2026-04-15 10:00:00",
        ),
    )
    product_id = conn.execute("SELECT id FROM products WHERE sku = 'SKU-DUAL-1'").fetchone()["id"]

    # Day 1 review — outside the window (before data_since)
    conn.execute(
        """
        INSERT INTO reviews (product_id, author, headline, body, body_hash,
                             rating, date_published, images, scraped_at,
                             headline_cn, body_cn, translate_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            "Bob",
            "Old review",
            "Day 1 body",
            "hash-d1",
            4.0,
            "2026-04-14",
            json.dumps([]),
            "2026-04-14 09:00:00",
            "",
            "",
            "pending",
        ),
    )

    # Day 2 review — inside the window (on/after data_since)
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
            "New review",
            "Day 2 body",
            "hash-d2",
            5.0,
            "2026-04-15",
            json.dumps([]),
            "2026-04-15 10:00:00",
            "",
            "",
            "done",
        ),
    )
    conn.commit()
    conn.close()

    run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "reporting",
            "logical_date": "2026-04-15",
            "trigger_key": "daily:2026-04-15:dual",
            "data_since": "2026-04-15T00:00:00+08:00",
            "data_until": "2026-04-16T00:00:00+08:00",
            "requested_by": "systemd",
            "service_version": "test",
        }
    )
    return {"db_file": db_file, "run": run, "tmp_path": tmp_path}


def test_dual_snapshot_has_cumulative_field(dual_snapshot_db):
    """When REPORT_PERSPECTIVE='dual', snapshot includes cumulative with all products+reviews."""
    import hashlib
    from pathlib import Path
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot

    frozen = freeze_report_snapshot(dual_snapshot_db["run"]["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))

    assert "cumulative" in snapshot, "cumulative field should be present for dual perspective"
    cum = snapshot["cumulative"]
    assert cum["products_count"] == 1
    assert cum["reviews_count"] == 2


def test_dual_snapshot_window_only_has_new_reviews(dual_snapshot_db):
    """Window-only data in snapshot['reviews'] should contain only day-2 review."""
    from pathlib import Path
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot

    frozen = freeze_report_snapshot(dual_snapshot_db["run"]["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))

    assert snapshot["reviews_count"] == 1, "Window should only contain 1 review (day 2)"
    assert snapshot["reviews"][0]["headline"] == "New review"


def test_dual_snapshot_hash_excludes_cumulative(dual_snapshot_db):
    """snapshot_hash must be computed without the cumulative field."""
    import hashlib
    from pathlib import Path
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot

    frozen = freeze_report_snapshot(dual_snapshot_db["run"]["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))

    # Recompute hash without cumulative
    hash_payload = {k: v for k, v in snapshot.items() if k != "cumulative"}
    # Remove snapshot_hash itself for recomputation (it was added after hashing)
    hash_payload.pop("snapshot_hash", None)
    expected_hash = hashlib.sha1(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert snapshot["snapshot_hash"] == expected_hash, (
        "snapshot_hash should be computed without the cumulative field"
    )


def test_window_perspective_skips_cumulative(dual_snapshot_db, monkeypatch):
    """When REPORT_PERSPECTIVE='window', snapshot should NOT have cumulative field."""
    from pathlib import Path
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot

    monkeypatch.setattr(config, "REPORT_PERSPECTIVE", "window")

    frozen = freeze_report_snapshot(dual_snapshot_db["run"]["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))

    assert "cumulative" not in snapshot, "cumulative should be absent for window perspective"


# ---------------------------------------------------------------------------
# Tests for dual-perspective report generation routing (P007 Task 4)
# ---------------------------------------------------------------------------


def test_full_report_continues_with_cumulative_no_window_reviews(dual_snapshot_db, monkeypatch):
    """When window has no reviews but cumulative exists, should NOT early-return."""
    from qbu_crawler.server import report_snapshot

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Remove window reviews to simulate no-new-reviews day
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    # Mock out expensive operations
    monkeypatch.setattr(config, "LLM_API_BASE", "")  # disable LLM
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)

    result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False,
    )

    # Should NOT get "completed_no_change" because cumulative data exists
    assert result.get("status") != "completed_no_change"
    # Should have analytics path (dual analytics was computed)
    assert result.get("analytics_path") is not None


def test_full_report_early_returns_without_cumulative_or_reviews(snapshot_db, monkeypatch):
    """Without cumulative and without reviews, should still early-return."""
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_PERSPECTIVE", "window")
    run = snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-03-29T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Remove reviews
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False,
    )
    assert result.get("status") == "completed_no_change"


def test_full_report_analytics_has_dual_perspective(dual_snapshot_db, monkeypatch):
    """Full report analytics should contain perspective='dual' when cumulative exists."""
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    gen_result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False,
    )

    # Load saved analytics and verify dual perspective
    # Stage B 修 7: analytics_path is now relative to REPORT_DIR.
    analytics = json.loads(
        (Path(config.REPORT_DIR) / gen_result["analytics_path"]).read_text(encoding="utf-8")
    )
    assert analytics.get("perspective") == "dual"
    assert "cumulative_kpis" in analytics
    assert "window" in analytics


def test_full_report_passes_window_review_ids_and_cumulative_reviews_to_excel(tmp_path, monkeypatch):
    from qbu_crawler.server import report_snapshot

    snapshot = {
        "run_id": 42,
        "logical_date": "2026-04-24",
        "snapshot_hash": "hash-window-ids",
        "products_count": 1,
        "reviews_count": 2,
        "translated_count": 4,
        "untranslated_count": 0,
        "products": [{"sku": "S1", "name": "Window Product"}],
        "reviews": [{"id": 2, "product_sku": "S1"}, {"id": 4, "product_sku": "S1"}],
        "cumulative": {
            "products": [{"sku": "S1", "name": "Window Product"}],
            "reviews": [
                {"id": 1, "product_sku": "S1"},
                {"id": 2, "product_sku": "S1"},
                {"id": 3, "product_sku": "S1"},
                {"id": 4, "product_sku": "S1"},
            ],
        },
    }
    captured = {}
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_dual_report_analytics",
        lambda snapshot, synced_labels=None: {
            "mode": "baseline",
            "report_semantics": "bootstrap",
            "kpis": {},
            "self": {},
            "competitor": {},
            "appendix": {},
        },
    )
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda run_id: (None, None))
    monkeypatch.setattr(report_snapshot.report_llm, "generate_report_insights_with_validation", lambda analytics, snapshot=None: {})
    monkeypatch.setattr(
        report_snapshot.report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: captured.update(
            {"products": products, "reviews": reviews, "analytics": analytics}
        ) or str(tmp_path / "report.xlsx"),
    )
    monkeypatch.setattr(
        report_snapshot.report_html,
        "render_v3_html",
        lambda snapshot, analytics, output_path=None: str(tmp_path / "report.html"),
    )

    report_snapshot.generate_full_report_from_snapshot(snapshot, send_email=False)

    assert captured["analytics"]["window_review_ids"] == [2, 4]
    assert [review["id"] for review in captured["reviews"]] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Tests for change/quiet modes using cumulative analytics (P007 Task 8)
# ---------------------------------------------------------------------------


def test_change_mode_uses_cumulative_kpis(dual_snapshot_db, monkeypatch):
    """Change mode should compute cumulative analytics when snapshot['cumulative'] exists."""
    from qbu_crawler.server import report_snapshot

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Simulate a change-mode day: clear window reviews so it becomes no-new-reviews
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    # Build cum_snapshot so report_analytics.build_report_analytics is callable
    # monkeypatch it to return a lightweight stub
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None, skip_delta=False: {
            "mode": "baseline",
            "kpis": {"ingested_review_rows": 2, "own_review_rows": 1},
            "self": {},
            "competitor": {},
            "appendix": {},
        },
    )

    change_result = report_snapshot._generate_change_report(
        snapshot,
        send_email=False,
        prev_analytics=None,
        context={"changes": {"has_changes": True, "price_changes": [{"sku": "SKU-DUAL-1", "name": "Dual Product", "old": 49.99, "new": 44.99}]}},
    )

    assert change_result["mode"] == "change"
    assert change_result["status"] == "completed"
    # When cumulative data exists, analytics_path should be written
    assert change_result["analytics_path"] is not None
    assert change_result.get("cumulative_computed") is True
    # Stage B 修 7: analytics_path is now relative to REPORT_DIR.
    assert (Path(config.REPORT_DIR) / change_result["analytics_path"]).is_file()


def test_quiet_mode_uses_cumulative_kpis(dual_snapshot_db, monkeypatch):
    """Quiet mode should compute cumulative analytics when snapshot['cumulative'] exists."""
    from qbu_crawler.server import report_snapshot

    run = dual_snapshot_db["run"]
    result = report_snapshot.freeze_report_snapshot(run["id"], now="2026-04-15T12:00:00+08:00")
    snapshot = report_snapshot.load_report_snapshot(result["snapshot_path"])

    # Simulate a quiet-mode day: clear window reviews
    snapshot["reviews"] = []
    snapshot["reviews_count"] = 0

    # monkeypatch build_report_analytics to a lightweight stub
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None, skip_delta=False: {
            "mode": "baseline",
            "kpis": {"ingested_review_rows": 2, "own_review_rows": 1},
            "self": {},
            "competitor": {},
            "appendix": {},
        },
    )

    # monkeypatch should_send_quiet_email to always return True (avoid DB lookup on run_id)
    monkeypatch.setattr(
        report_snapshot,
        "should_send_quiet_email",
        lambda run_id: (True, None, 0),
    )

    quiet_result = report_snapshot._generate_quiet_report(
        snapshot,
        send_email=False,
        prev_analytics=None,
    )

    assert quiet_result["mode"] == "quiet"
    assert quiet_result["status"] == "completed_no_change"
    # When cumulative data exists, analytics_path should be written
    assert quiet_result["analytics_path"] is not None
    assert quiet_result.get("cumulative_computed") is True
    # Stage B 修 7: analytics_path is now relative to REPORT_DIR.
    assert (Path(config.REPORT_DIR) / quiet_result["analytics_path"]).is_file()


def test_build_change_digest_summarizes_incremental_fresh_and_backfill_mix():
    from qbu_crawler.server.report_snapshot import build_change_digest

    snapshot = {
        "logical_date": "2026-04-15",
        "untranslated_count": 1,
        "products": [
            {
                "sku": "SKU-1",
                "name": "Digest Product",
                "price": 89.99,
                "stock_status": "in_stock",
                "rating": 4.2,
            }
        ],
        "reviews": [
            {"id": 1, "product_name": "Digest Product", "product_sku": "SKU-1", "ownership": "own", "rating": 1, "date_published": "2026-04-14", "images": []},
            {"id": 2, "product_name": "Digest Product", "product_sku": "SKU-1", "ownership": "competitor", "rating": 5, "date_published": "2026-04-10", "images": ["https://img.example.com/1.jpg"]},
            {"id": 3, "product_name": "Digest Product", "product_sku": "SKU-1", "ownership": "own", "rating": 4, "date_published": "2026-02-01", "images": []},
            {"id": 4, "product_name": "Digest Product", "product_sku": "SKU-1", "ownership": "competitor", "rating": 4, "date_published": "2026-01-15", "images": []},
            {"id": 5, "product_name": "Digest Product", "product_sku": "SKU-1", "ownership": "own", "rating": 5, "date_published": "2025-12-20", "images": []},
            {"id": 6, "product_name": "Digest Product", "product_sku": "SKU-1", "ownership": "competitor", "rating": 3, "date_published": "2025-11-11", "images": []},
        ],
    }
    analytics = {
        "report_semantics": "incremental",
        "kpis": {"untranslated_count": 1},
        "self": {
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "label_display": "质量稳定性",
                    "review_count": 2,
                    "severity": "high",
                    "affected_product_count": 1,
                    "last_seen": "2026-04-15",
                }
            ]
        },
    }
    previous_snapshot = {
        "products": [
            {
                "sku": "SKU-1",
                "name": "Digest Product",
                "price": 99.99,
                "stock_status": "in_stock",
                "rating": 4.2,
            }
        ]
    }
    previous_analytics = {"self": {"top_negative_clusters": []}}

    digest = build_change_digest(snapshot, analytics, previous_snapshot, previous_analytics)

    assert digest["enabled"] is True
    assert digest["view_state"] == "active"
    assert digest["summary"]["ingested_review_count"] == 6
    assert digest["summary"]["fresh_review_count"] == 2
    assert digest["summary"]["historical_backfill_count"] == 4
    assert digest["summary"]["fresh_own_negative_count"] == 1
    assert digest["summary"]["issue_new_count"] == 1
    assert digest["summary"]["issue_escalated_count"] == 0
    assert digest["summary"]["issue_improving_count"] == 0
    assert digest["summary"]["state_change_count"] == 1
    assert digest["warnings"]["translation_incomplete"]["enabled"] is True


def test_build_change_digest_bootstrap_keeps_summary_and_warning_contract():
    from qbu_crawler.server.report_snapshot import build_change_digest

    digest = build_change_digest(
        {
            "logical_date": "2026-04-15",
            "products": [],
            "reviews": [
                {"ownership": "own", "rating": 2, "date_published": "2026-04-14"},
                {"ownership": "competitor", "rating": 5, "date_published": "2025-01-01"},
            ],
        },
        {
            "report_semantics": "bootstrap",
            "baseline_day_index": 2,
            "baseline_display_state": "building",
            "kpis": {"untranslated_count": 0},
            "self": {"top_negative_clusters": []},
        },
        None,
        None,
    )

    assert digest["enabled"] is True
    assert digest["view_state"] == "bootstrap"
    assert digest["summary"]["ingested_review_count"] == 2
    assert digest["summary"]["baseline_day_index"] == 2
    assert digest["summary"]["baseline_display_state"] == "building"
    assert digest["summary"]["window_meaning"] == "基线建立期第2天，当前样本用于建立基线，不按新增口径解释"
    assert set(digest["warnings"]) == {
        "translation_incomplete",
        "estimated_dates",
        "backfill_dominant",
    }


def test_build_change_digest_uses_empty_state_for_incremental_without_significant_changes():
    from qbu_crawler.server.report_snapshot import build_change_digest

    digest = build_change_digest(
        {
            "logical_date": "2026-04-15",
            "products": [
                {"sku": "SKU-1", "name": "Digest Product", "price": 99.99, "stock_status": "in_stock", "rating": 4.2}
            ],
            "reviews": [],
        },
        {
            "report_semantics": "incremental",
            "kpis": {"untranslated_count": 0},
            "self": {"top_negative_clusters": []},
        },
        {
            "products": [
                {"sku": "SKU-1", "name": "Digest Product", "price": 99.99, "stock_status": "in_stock", "rating": 4.2}
            ]
        },
        {"self": {"top_negative_clusters": []}},
    )

    assert digest["view_state"] == "empty"
    assert digest["empty_state"]["enabled"] is True
    assert digest["issue_changes"]["new"] == []
    assert digest["product_changes"]["price_changes"] == []


# ── F011 §4.1.3 — retired legacy template assertions ──
# The two tests below
# (test_render_full_email_html_prefers_top_level_kpis_and_change_digest /
#  test_render_full_email_html_includes_competitor_positive_review_signals)
# asserted that the email body rendered change_digest sections
# (price/stock/issue change blocks, fresh_competitor_positive_reviews list).
# F011 §4.1 strips those blocks from the email body in favor of 4 KPI lamps
# + Hero + Top 3 + product_status. The new render contract lives in
# tests/server/test_email_full_template.py. Both tests are now skipped to
# document the historical contract; they can be safely deleted in a follow-up.
import pytest as _f011_pytest


@_f011_pytest.mark.skip(reason="F011 §4.1.3 — change_digest blocks removed from email body")
def test_render_full_email_html_prefers_top_level_kpis_and_change_digest(monkeypatch):
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda run_id: ({}, None))
    monkeypatch.setattr(
        report_snapshot,
        "detect_snapshot_changes",
        lambda snapshot, previous_snapshot: {
            "has_changes": True,
            "price_changes": [{"name": "旧价格来源", "old": 100, "new": 90}],
            "stock_changes": [{"name": "旧库存来源", "old": "unknown", "new": "in_stock"}],
            "rating_changes": [],
            "new_products": [],
            "removed_products": [],
        },
    )
    monkeypatch.setattr(
        report_snapshot,
        "compute_cluster_changes",
        lambda current, previous, logical_date: {
            "new": [{"label_display": "旧问题来源", "review_count": 7}],
            "escalated": [],
            "improving": [],
            "de_escalated": [],
        },
    )

    html = report_snapshot.report.render_email_full(
        {
            "run_id": 8,
            "logical_date": "2026-04-23",
            "snapshot_at": "2026-04-23T09:00:00+08:00",
            "products_count": 1,
            "reviews_count": 0,
            "translated_count": 0,
            "untranslated_count": 0,
            "reviews": [],
        },
        {
            "report_semantics": "incremental",
            "kpis": {
                "health_index": 88,
                "own_review_rows": 12,
                "high_risk_count": 1,
                "own_product_count": 1,
                "competitor_product_count": 0,
                "translated_count": 0,
                "untranslated_count": 0,
            },
            "cumulative_kpis": {
                "health_index": 11,
                "own_review_rows": 999,
                "high_risk_count": 9,
                "own_product_count": 9,
                "competitor_product_count": 9,
            },
            "change_digest": {
                "enabled": True,
                "view_state": "active",
                "suppressed_reason": "",
                "summary": {
                    "ingested_review_count": 6,
                    "ingested_own_review_count": 4,
                    "ingested_competitor_review_count": 2,
                    "ingested_own_negative_count": 1,
                    "fresh_review_count": 2,
                    "historical_backfill_count": 4,
                    "fresh_own_negative_count": 1,
                    "issue_new_count": 1,
                    "issue_escalated_count": 0,
                    "issue_improving_count": 0,
                    "state_change_count": 2,
                },
                "issue_changes": {
                    "new": [{
                        "label_display": "新问题来源",
                        "change_type": "new",
                        "current_review_count": 3,
                        "delta_review_count": 3,
                        "affected_product_count": 1,
                        "severity": "high",
                        "days_quiet": 0,
                    }],
                    "escalated": [],
                    "improving": [],
                    "de_escalated": [],
                },
                "product_changes": {
                    "price_changes": [{"name": "新价格来源", "old": 100, "new": 90}],
                    "stock_changes": [{"name": "新库存来源", "old": "unknown", "new": "in_stock"}],
                    "rating_changes": [],
                    "new_products": [],
                    "removed_products": [],
                },
                "review_signals": {
                    "fresh_negative_reviews": [],
                    "fresh_competitor_positive_reviews": [],
                },
                "warnings": {
                    "translation_incomplete": {"enabled": False, "message": ""},
                    "estimated_dates": {"enabled": False, "message": ""},
                    "backfill_dominant": {"enabled": False, "message": ""},
                },
                "empty_state": {"enabled": False, "title": "", "description": ""},
            },
            "report_copy": {"hero_headline": "", "executive_bullets": []},
            "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
            "competitor": {
                "top_positive_themes": [],
                "benchmark_examples": [],
                "negative_opportunities": [],
            },
            "window": {"reviews_count": 999},
        },
    )

    assert "999" not in html
    assert "新问题来源" in html
    assert "旧问题来源" not in html
    assert "新价格来源" in html
    assert "旧价格来源" not in html


@_f011_pytest.mark.skip(reason="F011 §4.1.3 — competitor positive-review block removed from email body")
def test_render_full_email_html_includes_competitor_positive_review_signals(monkeypatch):
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda run_id: ({}, None))
    monkeypatch.setattr(
        report_snapshot,
        "detect_snapshot_changes",
        lambda snapshot, previous_snapshot: {
            "has_changes": False,
            "price_changes": [],
            "stock_changes": [],
            "rating_changes": [],
            "new_products": [],
            "removed_products": [],
        },
    )
    monkeypatch.setattr(
        report_snapshot,
        "compute_cluster_changes",
        lambda current, previous, logical_date: {
            "new": [],
            "escalated": [],
            "improving": [],
            "de_escalated": [],
        },
    )

    html = report_snapshot.report.render_email_full(
        {
            "run_id": 8,
            "logical_date": "2026-04-23",
            "snapshot_at": "2026-04-23T09:00:00+08:00",
            "products_count": 1,
            "reviews_count": 0,
            "translated_count": 0,
            "untranslated_count": 0,
            "reviews": [],
        },
        {
            "report_semantics": "incremental",
            "kpis": {
                "health_index": 88,
                "own_review_rows": 12,
                "high_risk_count": 1,
                "own_product_count": 1,
                "competitor_product_count": 1,
                "translated_count": 0,
                "untranslated_count": 0,
            },
            "change_digest": {
                "enabled": True,
                "view_state": "active",
                "summary": {
                    "ingested_review_count": 2,
                    "fresh_review_count": 2,
                    "historical_backfill_count": 0,
                    "fresh_own_negative_count": 0,
                    "issue_new_count": 0,
                    "issue_escalated_count": 0,
                    "issue_improving_count": 0,
                    "state_change_count": 0,
                },
                "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
                "product_changes": {
                    "price_changes": [],
                    "stock_changes": [],
                    "rating_changes": [],
                    "new_products": [],
                    "removed_products": [],
                },
                "review_signals": {
                    "fresh_negative_reviews": [],
                    "fresh_competitor_positive_reviews": [
                        {
                            "product_name": "Competitor Pro",
                            "headline_display": "Worth every penny",
                            "body_display": "Quiet, stable, and easy to clean.",
                        }
                    ],
                },
                "warnings": {
                    "translation_incomplete": {"enabled": False, "message": ""},
                    "estimated_dates": {"enabled": False, "message": ""},
                    "backfill_dominant": {"enabled": False, "message": ""},
                },
                "empty_state": {"enabled": False, "title": "", "description": ""},
            },
            "report_copy": {"hero_headline": "", "executive_bullets": []},
            "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
            "competitor": {
                "top_positive_themes": [],
                "benchmark_examples": [],
                "negative_opportunities": [],
            },
        },
    )

    assert "Competitor Pro" in html
    assert "Worth every penny" in html


def test_load_previous_report_context_resolves_stale_absolute_artifact_paths(snapshot_db):
    from qbu_crawler.server.report_snapshot import load_previous_report_context

    prev_run_id = snapshot_db["run"]["id"]
    Path(config.REPORT_DIR).mkdir(parents=True, exist_ok=True)
    analytics_file = Path(config.REPORT_DIR) / "workflow-run-1-analytics-2026-03-29.json"
    snapshot_file = Path(config.REPORT_DIR) / "workflow-run-1-snapshot-2026-03-29.json"
    analytics_file.write_text(json.dumps({"kpis": {"ingested_review_rows": 3}}), encoding="utf-8")
    snapshot_file.write_text(json.dumps({"snapshot_hash": "snapshot-1", "products": []}), encoding="utf-8")

    models.update_workflow_run(
        prev_run_id,
        status="completed",
        analytics_path=r"C:\Users\User\Desktop\QBU\reports\workflow-run-1-analytics-2026-03-29.json",
        snapshot_path=r"C:\Users\User\Desktop\QBU\reports\workflow-run-1-snapshot-2026-03-29.json",
    )
    current_run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "reporting",
            "logical_date": "2026-03-30",
            "trigger_key": "daily:2026-03-30:snapshot",
            "data_since": "2026-03-30T00:00:00+08:00",
            "data_until": "2026-03-31T00:00:00+08:00",
            "requested_by": "systemd",
            "service_version": "test",
        }
    )

    analytics, snapshot = load_previous_report_context(current_run["id"])

    assert analytics["kpis"]["ingested_review_rows"] == 3
    assert snapshot["snapshot_hash"] == "snapshot-1"


def test_generate_full_report_returns_relative_artifact_paths(snapshot_db, monkeypatch):
    """修 7: report_snapshot.generate_report_from_snapshot 返回 dict 中的
    analytics_path / excel_path / html_path 必须是相对 REPORT_DIR 的相对路径，
    便于跨机器迁移后 resolver 仍能恢复。下游 WorkflowWorker._finish_report 会
    将这些 value 原样落到 workflow_runs 表，所以这里只验证生产端契约。"""
    from qbu_crawler.server import report_snapshot

    # Stub all heavyweight collaborators — we only test the path-shaping behavior
    monkeypatch.setattr(report_snapshot.report, "query_report_data", lambda *a, **kw: ([], []))
    monkeypatch.setattr(report_snapshot.report, "query_cumulative_data", lambda *a, **kw: ([], []))
    monkeypatch.setattr(report_snapshot.report, "render_email_full", lambda *a, **kw: "<html></html>")
    monkeypatch.setattr(report_snapshot.report, "send_email", lambda **kw: {"success": True, "recipients": []})

    frozen = report_snapshot.freeze_report_snapshot(
        snapshot_db["run"]["id"], now="2026-04-25T12:00:00+08:00"
    )
    # `freeze_report_snapshot` returns the workflow_runs row dict; the actual
    # snapshot payload (run_id / products_count / reviews_count / ...) lives on
    # disk at snapshot_path. Load it back so generate_report_from_snapshot has
    # the keys it expects.
    snapshot = report_snapshot.load_report_snapshot(frozen["snapshot_path"])
    # Inject minimal cumulative + reviews so generate_report_from_snapshot picks "full" mode
    snapshot["reviews"] = [{"id": 1, "rating": 5, "ownership": "own"}]
    snapshot["cumulative"] = {
        "products": [], "reviews": [{"id": 1, "rating": 5, "ownership": "own"}],
        "products_count": 0, "reviews_count": 1, "translated_count": 0, "untranslated_count": 1,
    }

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)

    # The on-disk file MUST live under config.REPORT_DIR
    from qbu_crawler import config
    report_root = Path(config.REPORT_DIR).resolve()

    for key in ("analytics_path", "excel_path", "html_path"):
        stored = result.get(key)
        if stored is None:
            continue  # change/quiet modes legitimately omit some keys
        # Stored value must be relative (no drive letter, no leading slash)
        assert not Path(stored).is_absolute(), f"{key} must be relative, got {stored!r}"
        # Joining with REPORT_DIR must point to an existing file
        resolved = (report_root / stored).resolve()
        assert resolved.is_file(), f"{key}={stored!r} did not resolve to an existing file"


def test_artifact_resolver_recovers_when_original_path_moved(snapshot_db, monkeypatch, tmp_path):
    """修 7 补强：旧 run 的 analytics_path 已经是绝对路径（Stage A 之前生成），
    机器迁移后 REPORT_DIR 改了位置，resolver 应当通过 basename glob 找回 artifact。"""
    from qbu_crawler import config, models
    from qbu_crawler.server.report_snapshot import _resolve_artifact_path

    # 1. 模拟旧机器的 absolute path（写到 DB）
    legacy_abs = r"D:\OldServer\reports\workflow-run-42-analytics-2026-03-20.json"

    # 2. 当前机器的实际 REPORT_DIR
    Path(config.REPORT_DIR).mkdir(parents=True, exist_ok=True)
    actual_path = Path(config.REPORT_DIR) / "workflow-run-42-analytics-2026-03-20.json"
    actual_path.write_text('{"kpis": {}}', encoding="utf-8")

    # 3. resolver 必须找到当前 REPORT_DIR 下的同名文件
    resolved = _resolve_artifact_path(legacy_abs, run_id=42, kind="analytics")
    assert resolved is not None, "resolver should fall back to basename in REPORT_DIR"
    assert Path(resolved).is_file()
    assert Path(resolved).name == actual_path.name


# ──────────────────────────────────────────────────────────────────────
# F011 Critical A-1 — wiring test: pipeline routes through v3 orchestrator
# AND backfills improvement_priorities via build_fallback_priorities when
# the LLM output is empty (LLM disabled / fallback path / persistent
# validation failure).
# ──────────────────────────────────────────────────────────────────────

def test_full_report_uses_v3_llm_pipeline_and_fallback(tmp_path, monkeypatch):
    """A-1 e2e: confirm production pipeline calls
    `generate_report_insights_with_validation` AND that an empty
    `improvement_priorities` from that path is backfilled by
    `build_fallback_priorities` (so email_full Top 3 行动 always renders)."""
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    excel_path = tmp_path / "workflow-run-101-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_path = tmp_path / "workflow-run-101-full-report.html"
    html_path.write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None, analytics=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {
            "mode": "baseline",
            "kpis": {},
            "self": {
                "top_negative_clusters": [
                    {
                        "label_code": "noise",
                        "label_display": "噪音",
                        "review_count": 12,
                        "affected_products": ["P-A", "P-B"],
                    }
                ],
                "risk_products": [
                    {
                        "product_name": "P-A",
                        "top_labels": [
                            {"code": "structure_design", "display": "结构设计", "count": 5}
                        ],
                    }
                ],
            },
            "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
            "appendix": {},
        },
    )
    monkeypatch.setattr(report_snapshot.report_html, "render_v3_html",
                        lambda snapshot, analytics, output_path=None: str(html_path))

    captured = {"v3_called": 0, "legacy_called": 0}

    def fake_v3(analytics, snapshot=None, *, max_retries=3):
        captured["v3_called"] += 1
        # Simulate LLM disabled / persistent failure → empty insights stub
        return {
            "hero_headline": "",
            "executive_summary": "",
            "executive_bullets": [],
            "improvement_priorities": [],
            "competitive_insight": "",
        }

    def fake_legacy(analytics, snapshot=None):
        captured["legacy_called"] += 1
        return {"improvement_priorities": []}

    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        fake_v3,
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights",
        fake_legacy,
    )

    snapshot = {
        "run_id": 101,
        "logical_date": "2026-04-27",
        "data_since": "2026-04-27T00:00:00+08:00",
        "snapshot_hash": "h-a1",
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 1,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"id": 1, "rating": 1, "translate_status": "done"}],
    }

    result = generate_full_report_from_snapshot(snapshot, send_email=False, output_path=str(excel_path))

    # 1. v3 orchestrator must be called; legacy must NOT.
    assert captured["v3_called"] == 1, "pipeline must call v3 orchestrator"
    assert captured["legacy_called"] == 0, "legacy path must not be called"

    # 2. Persisted analytics must contain non-empty improvement_priorities
    #    via build_fallback_priorities.
    saved = json.loads((Path(config.REPORT_DIR) / result["analytics_path"]).read_text(encoding="utf-8"))
    priorities = saved["report_copy"]["improvement_priorities"]
    assert priorities, "improvement_priorities must be backfilled by build_fallback_priorities"
    # Rule: first row should come from risk_products[0].top_labels[0].
    codes = [p.get("label_code") for p in priorities]
    assert "structure_design" in codes


# ──────────────────────────────────────────────────────────────────────
# F011 Critical A-2 — wiring test: production pipeline renders email_full
# from the *normalized* analytics so the 4 KPI lights populate
# (health_index / own_negative_review_rate_display) instead of falling
# through to ⚪ "无数据".
# ──────────────────────────────────────────────────────────────────────

def test_email_full_in_production_pipeline_renders_health_index(tmp_path, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))

    excel_path = tmp_path / "workflow-run-202-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    html_path = tmp_path / "workflow-run-202-full-report.html"
    html_path.write_text("<html></html>", encoding="utf-8")

    captured = {}

    def spy_generate_excel(products, reviews, report_date=None, output_path=None, analytics=None):
        captured["excel_contract"] = (analytics or {}).get("report_user_contract")
        return str(excel_path)

    monkeypatch.setattr(report, "generate_excel", spy_generate_excel)
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})

    # Build raw analytics with kpi inputs that normalize_deep_report_analytics
    # will consume to produce health_index. Need own_review_rows ≥ 30 to avoid
    # the small-sample shrink-to-50 prior collapsing the value.
    raw_kpis = {
        "own_review_rows": 200,
        "own_positive_review_rows": 195,
        "own_negative_review_rows": 5,
        "own_neutral_review_rows": 0,
        "own_product_count": 3,
        "competitor_product_count": 2,
        "ingested_review_rows": 40,
    }
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot, synced_labels=None: {
            "mode": "baseline",
            "kpis": dict(raw_kpis),
            "self": {
                "top_negative_clusters": [],
                "risk_products": [],
                "product_status": [
                    {"product_name": "P-A", "status_lamp": "green",
                     "primary_concern": ""},
                ],
            },
            "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                           "negative_opportunities": []},
            "appendix": {},
        },
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "generate_report_insights_with_validation",
        lambda analytics, snapshot=None, max_retries=3: {
            "hero_headline": "稳健", "executive_summary": "",
            "executive_bullets": ["要点 A"], "improvement_priorities": [],
            "competitive_insight": "",
        },
    )
    monkeypatch.setattr(report_snapshot.report_html, "render_v3_html",
                        lambda snapshot, analytics, output_path=None: str(html_path))

    real_render_email_full = report.render_email_full

    def spy_render(snap, ana):
        captured["analytics_kpis"] = (ana or {}).get("kpis", {})
        return real_render_email_full(snap, ana)

    monkeypatch.setattr(report, "render_email_full", spy_render)
    # Also need report module symbol used by report_snapshot.
    monkeypatch.setattr(report_snapshot.report, "render_email_full", spy_render)

    monkeypatch.setattr(
        report,
        "send_email",
        lambda recipients, subject, body_text, body_html=None,
               attachment_path=None, attachment_paths=None: {
            "success": True, "error": None, "recipients": len(recipients),
        },
    )
    monkeypatch.setattr(report_snapshot, "get_email_recipients",
                        lambda: ["leo.xia@forcome.com"])

    snapshot = {
        "run_id": 202,
        "logical_date": "2026-04-27",
        "data_since": "2026-04-27T00:00:00+08:00",
        "snapshot_hash": "h-a2",
        "products_count": 3,
        "reviews_count": 200,
        "translated_count": 200,
        "untranslated_count": 0,
        "products": [{"site": "basspro", "ownership": "own"}],
        "reviews": [{"id": i, "rating": 5, "translate_status": "done"} for i in range(200)],
    }

    generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    kpis_received = captured["analytics_kpis"]
    # health_index must be populated by normalize_deep_report_analytics.
    assert "health_index" in kpis_received, (
        "render_email_full received un-normalized analytics; KPI lights would "
        f"render ⚪ '无数据'. kpis keys = {sorted(kpis_received.keys())}"
    )
    # own_negative_review_rate_display is also normalize-only.
    assert "own_negative_review_rate_display" in kpis_received
    assert isinstance(captured.get("excel_contract"), dict)


def test_merge_post_normalize_mutations_refreshes_report_user_contract():
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    from qbu_crawler.server.report_snapshot import _merge_post_normalize_mutations

    analytics = {
        "mode": "baseline",
        "kpis": {
            "ingested_review_rows": 2,
            "own_review_rows": 2,
            "own_product_count": 1,
        },
        "self": {
            "risk_products": [],
            "recommendations": [],
            "top_negative_clusters": [{
                "label_code": "quality_stability",
                "label_display": "质量稳定性",
                "feature_display": "质量稳定性",
                "review_count": 2,
                "severity": "high",
                "affected_product_count": 1,
                "example_reviews": [{"id": 301, "body_cn": "开关坏了"}],
            }],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "report_copy": {"hero_headline": "", "executive_bullets": [], "improvement_priorities": []},
    }
    normalized = normalize_deep_report_analytics(analytics)
    raw = dict(analytics)
    raw["report_copy"] = {
        "hero_headline": "关注开关质量",
        "executive_bullets": [],
        "improvement_priorities": [{
            "label_code": "quality_stability",
            "short_title": "复核开关耐久",
            "full_action": "加强出厂耐久测试，并对开关失效评论对应批次进行复测和客服回访。",
            "evidence_count": 2,
            "evidence_review_ids": [301],
            "affected_products": ["Product A"],
        }],
    }
    raw["self"] = {
        **raw["self"],
        "top_negative_clusters": [{
            **raw["self"]["top_negative_clusters"][0],
            "deep_analysis": {
                "failure_modes": [{"name": "开关失效"}],
                "root_causes": [{"name": "抽检不足"}],
                "user_workarounds": ["反复重启"],
            },
        }],
    }

    _merge_post_normalize_mutations(normalized, raw)

    contract = normalized["report_user_contract"]
    assert contract["action_priorities"][0]["full_action"].startswith("加强出厂耐久测试")
    assert contract["issue_diagnostics"][0]["ai_recommendation"].startswith("加强出厂耐久测试")
    assert contract["issue_diagnostics"][0]["failure_modes"] == [{"name": "开关失效"}]
