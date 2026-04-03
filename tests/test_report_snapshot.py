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

    monkeypatch.setattr(report, "_download_and_resize", lambda url: None)
    monkeypatch.setattr(
        report_snapshot.report_pdf,
        "generate_pdf_report",
        lambda snapshot, analytics, output_path: str(snapshot_db["tmp_path"] / "full.pdf"),
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
        lambda products, reviews, report_date=None, output_path=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot: {
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
        "run_llm_report_analysis",
        lambda snapshot, analytics: {"candidate_pools": {}, "llm_findings": {}, "report_copy": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "validate_findings",
        lambda snapshot, analytics, llm_result: {
            "self_negative_clusters": analytics["self"]["top_negative_clusters"],
            "competitor_positive_themes": analytics["competitor"]["top_positive_themes"],
            "own_image_evidence": [],
            "competitor_negative_opportunities": analytics["competitor"]["negative_opportunities"],
            "competitor_benchmark_examples": analytics["competitor"]["benchmark_examples"],
            "recommendations": analytics["self"]["recommendations"],
        },
    )
    monkeypatch.setattr(
        report_snapshot.report_llm,
        "merge_final_analytics",
        lambda analytics, llm_result, validated_result: {
            **analytics,
            "self": {
                **analytics["self"],
                "top_negative_clusters": validated_result["self_negative_clusters"],
                "recommendations": validated_result["recommendations"],
            },
            "competitor": {
                **analytics["competitor"],
                "top_positive_themes": validated_result["competitor_positive_themes"],
                "benchmark_examples": validated_result["competitor_benchmark_examples"],
                "negative_opportunities": validated_result["competitor_negative_opportunities"],
            },
            "appendix": {"image_reviews": validated_result["own_image_evidence"]},
            "validated_findings": validated_result,
            "report_copy": llm_result["report_copy"],
        },
    )
    pdf_path = tmp_path / "workflow-run-1-full-report.pdf"
    monkeypatch.setattr(
        report_snapshot.report_pdf,
        "generate_pdf_report",
        lambda snapshot, analytics, output_path: str(pdf_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, attachment_path=None, attachment_paths=None):
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
    assert captured["subject"] == "【产品评论基线建档】2026-03-27 自有产品风险与竞品卖点全量分析"
    assert "本次为首日全量基线版" in captured["body_text"]
    assert "Own Stuffer（SKU: OWN-1）" in captured["body_text"]
    assert "质量稳定性(11)、结构设计(7)" in captured["body_text"]
    assert "易上手：33 条" in captured["body_text"]
    assert "Competitor Grinder（SKU: COMP-2）：包装运输" in captured["body_text"]
    assert captured["attachment_path"] is None
    assert captured["attachment_paths"] == [str(excel_path), str(pdf_path)]


def test_generate_full_report_from_snapshot_returns_analytics_and_pdf_paths(tmp_path, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    excel_path = tmp_path / "workflow-run-1-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    pdf_path = tmp_path / "workflow-run-1-full-report.pdf"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_pdf,
        "generate_pdf_report",
        lambda snapshot, analytics, output_path: str(pdf_path),
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
    assert result["pdf_path"] == str(pdf_path)
    assert Path(result["analytics_path"]).is_file()


def test_generate_full_report_from_snapshot_uses_merged_analytics_from_report_llm(tmp_path, monkeypatch):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])
    excel_path = tmp_path / "workflow-run-9-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    pdf_path = tmp_path / "workflow-run-9-full-report.pdf"
    pdf_path.write_text("pdf", encoding="utf-8")
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot: {
            "mode": "baseline",
            "kpis": {},
            "self": {"top_negative_clusters": [{"label_code": "quality_stability", "example_reviews": [{"id": 1}]}]},
            "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
            "appendix": {"image_reviews": [{"id": 2}]},
        },
    )

    captured = {}

    def fake_run_llm_report_analysis(snapshot, analytics):
        captured["analytics_before_merge"] = analytics
        return {
            "candidate_pools": {},
            "llm_findings": {},
            "report_copy": {"hero_headline": "聚焦可靠性"},
        }

    def fake_merge_final_analytics(analytics, llm_result, validated_result):
        merged = dict(analytics)
        merged["self"] = {"top_negative_clusters": [{"label_code": "quality_stability", "example_reviews": [{"id": 99}]}]}
        merged["competitor"] = {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []}
        merged["appendix"] = {"image_reviews": [{"id": 77}]}
        merged["validated_findings"] = validated_result
        merged["report_copy"] = llm_result["report_copy"]
        return merged

    def fake_validate_findings(snapshot, analytics, llm_result):
        return {"own_image_evidence": [{"id": 77}]}

    monkeypatch.setattr(report_snapshot.report_llm, "run_llm_report_analysis", fake_run_llm_report_analysis)
    monkeypatch.setattr(report_snapshot.report_llm, "validate_findings", fake_validate_findings)
    monkeypatch.setattr(report_snapshot.report_llm, "merge_final_analytics", fake_merge_final_analytics)

    def fake_generate_pdf_report(snapshot, analytics, output_path):
        captured["pdf_analytics"] = analytics
        return str(pdf_path)

    monkeypatch.setattr(report_snapshot.report_pdf, "generate_pdf_report", fake_generate_pdf_report)

    def fake_build_email(snapshot, analytics):
        captured["email_analytics"] = analytics
        return "subject", "body"

    monkeypatch.setattr(report, "build_daily_deep_report_email", fake_build_email)
    monkeypatch.setattr(
        report,
        "send_email",
        lambda recipients, subject, body_text, attachment_path=None, attachment_paths=None: {
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

    assert result["pdf_path"] == str(pdf_path)
    assert captured["pdf_analytics"]["self"]["top_negative_clusters"][0]["example_reviews"][0]["id"] == 99
    assert captured["email_analytics"]["appendix"]["image_reviews"][0]["id"] == 77
    assert json.loads(Path(result["analytics_path"]).read_text(encoding="utf-8"))["report_copy"]["hero_headline"] == "聚焦可靠性"


def test_generate_full_report_from_snapshot_sends_excel_and_pdf(monkeypatch, tmp_path):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])

    excel_path = tmp_path / "workflow-run-2-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    pdf_path = tmp_path / "workflow-run-2-full-report.pdf"
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_pdf,
        "generate_pdf_report",
        lambda snapshot, analytics, output_path: str(pdf_path),
    )

    captured = {}

    def fake_send_email(recipients, subject, body_text, attachment_path=None, attachment_paths=None):
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

    assert result["pdf_path"] == str(pdf_path)
    assert captured["attachment_path"] is None
    assert captured["attachment_paths"] == [str(excel_path), str(pdf_path)]


def test_generate_full_report_from_snapshot_raises_on_email_failure_with_partial_artifacts(
    monkeypatch,
    tmp_path,
):
    from qbu_crawler.server import report
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_snapshot import (
        FullReportGenerationError,
        generate_full_report_from_snapshot,
    )

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(config, "EMAIL_RECIPIENTS", ["leo.xia@forcome.com"])

    excel_path = tmp_path / "workflow-run-3-full-report.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    pdf_path = tmp_path / "workflow-run-3-full-report.pdf"
    pdf_path.write_text("pdf", encoding="utf-8")
    monkeypatch.setattr(
        report,
        "generate_excel",
        lambda products, reviews, report_date=None, output_path=None: str(excel_path),
    )
    monkeypatch.setattr(report_snapshot.report_analytics, "sync_review_labels", lambda snapshot: {})
    monkeypatch.setattr(
        report_snapshot.report_analytics,
        "build_report_analytics",
        lambda snapshot: {"mode": "baseline", "kpis": {}, "self": {}, "competitor": {}, "appendix": {}},
    )
    monkeypatch.setattr(
        report_snapshot.report_pdf,
        "generate_pdf_report",
        lambda snapshot, analytics, output_path: str(pdf_path),
    )
    monkeypatch.setattr(
        report,
        "send_email",
        lambda recipients, subject, body_text, attachment_path=None, attachment_paths=None: {
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

    with pytest.raises(FullReportGenerationError, match="smtp failed") as exc_info:
        generate_full_report_from_snapshot(snapshot, send_email=True, output_path=str(excel_path))

    exc = exc_info.value
    assert exc.excel_path == str(excel_path)
    assert exc.pdf_path == str(pdf_path)
    assert exc.analytics_path.endswith(".json")
