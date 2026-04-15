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
        "generate_report_insights",
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
        "generate_report_insights",
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

    assert result["analytics_path"].endswith(".json")
    assert result["pdf_path"] is None
    assert result["html_path"] == str(html_report_path)
    assert Path(result["analytics_path"]).is_file()


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

    monkeypatch.setattr(report_snapshot.report_llm, "generate_report_insights", fake_generate_report_insights)

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

    assert result["html_path"] == str(html_report_path)
    # The analytics passed to HTML renderer should have report_copy from generate_report_insights
    assert captured["html_analytics"]["report_copy"]["hero_headline"] == "聚焦可靠性"
    # The analytics JSON should be persisted with the insights
    saved = json.loads(Path(result["analytics_path"]).read_text(encoding="utf-8"))
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
        "generate_report_insights",
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
    assert result["html_path"] == str(html_report_path)
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
        "generate_report_insights",
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
    assert result["excel_path"] == str(excel_path)
    assert result["pdf_path"] is None
    assert result["html_path"] == str(html_report_path)
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
        "generate_report_insights",
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
    assert result["excel_path"] == str(excel_path)
    assert result["pdf_path"] is None
    assert result["html_path"] == str(html_report_path)


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
        "generate_report_insights",
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
    assert result["excel_path"] == str(excel_path)
    assert result["pdf_path"] is None
    assert result["html_path"] == str(html_report_path)


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
