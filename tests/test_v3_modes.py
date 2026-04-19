"""Tests for Report V3 three-mode routing (Phase 3b)."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


class TestLoadPreviousContext:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return tmp_path

    def test_returns_none_when_no_previous(self, db):
        from qbu_crawler.server.report_snapshot import load_previous_report_context
        analytics, snapshot = load_previous_report_context(run_id=1)
        assert analytics is None
        assert snapshot is None

    def test_loads_from_previous_full_run(self, db):
        from qbu_crawler.server.report_snapshot import load_previous_report_context
        analytics_path = str(db / "analytics.json")
        Path(analytics_path).write_text('{"kpis": {"test": 1}}')
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-08", "trigger_key": "daily:2026-04-08",
            "analytics_path": analytics_path,
        })
        analytics, snapshot = load_previous_report_context(run_id=999)
        assert analytics is not None
        assert analytics["kpis"]["test"] == 1

    def test_skips_quiet_run_without_analytics(self, db):
        from qbu_crawler.server.report_snapshot import load_previous_report_context
        # Run 1: full with analytics
        analytics_path = str(db / "analytics.json")
        Path(analytics_path).write_text('{"kpis": {"from": "full"}}')
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-07", "trigger_key": "daily:2026-04-07",
            "analytics_path": analytics_path,
        })
        # Run 2: quiet without analytics
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-08", "trigger_key": "daily:2026-04-08",
            "analytics_path": None,
        })
        analytics, _ = load_previous_report_context(run_id=999)
        assert analytics["kpis"]["from"] == "full"

    def test_handles_missing_file(self, db):
        from qbu_crawler.server.report_snapshot import load_previous_report_context
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-08", "trigger_key": "daily:2026-04-08",
            "analytics_path": "/nonexistent/path.json",
        })
        analytics, snapshot = load_previous_report_context(run_id=999)
        assert analytics is None
        assert snapshot is None


from qbu_crawler.server.report_snapshot import detect_snapshot_changes


class TestDetectSnapshotChanges:
    def test_no_changes(self):
        current = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is False
        assert len(result["price_changes"]) == 0

    def test_price_change(self):
        current = {"products": [{"sku": "A", "name": "P", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["price_changes"]) == 1
        assert result["price_changes"][0]["old"] == 169.99
        assert result["price_changes"][0]["new"] == 149.99

    def test_float_precision_no_phantom(self):
        current = {"products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "name": "P", "price": 169.99000000000001, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is False

    def test_stock_change(self):
        current = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "out_of_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["stock_changes"]) == 1

    def test_new_product(self):
        current = {"products": [
            {"sku": "A", "name": "PA", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50},
            {"sku": "B", "name": "PB", "price": 20.0, "stock_status": "in_stock", "rating": 4.0, "review_count": 10},
        ]}
        previous = {"products": [{"sku": "A", "name": "PA", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["new_products"]) == 1

    def test_removed_product(self):
        current = {"products": []}
        previous = {"products": [{"sku": "A", "name": "PA", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["removed_products"]) == 1

    def test_none_previous(self):
        current = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, None)
        assert result["has_changes"] is False

    def test_rating_change(self):
        current = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.6, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.7, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["rating_changes"]) == 1


class TestDetectSnapshotChangesMissingValueGuard:
    """Bug A regression — 采集缺失不应被当作业务变动。"""

    def test_rating_none_to_real_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": None,
                                   "price": 10.0, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 10.0, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["rating_changes"] == []
        assert result["has_changes"] is False

    def test_rating_real_to_none_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.0, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": None,
                                  "price": 10.0, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["rating_changes"] == []
        assert result["has_changes"] is False

    def test_stock_unknown_to_in_stock_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.0, "stock_status": "unknown",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 10.0, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["stock_changes"] == []
        assert result["has_changes"] is False

    def test_stock_in_stock_to_out_of_stock_is_a_real_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.0, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 10.0, "stock_status": "out_of_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert len(result["stock_changes"]) == 1
        assert result["stock_changes"][0]["old"] == "in_stock"
        assert result["stock_changes"][0]["new"] == "out_of_stock"
        assert result["has_changes"] is True

    def test_price_none_to_real_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": None, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 19.99, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["price_changes"] == []
        assert result["has_changes"] is False

    def test_price_real_to_real_crosses_threshold(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.00, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 12.50, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert len(result["price_changes"]) == 1
        assert result["price_changes"][0]["old"] == 10.00
        assert result["price_changes"][0]["new"] == 12.50


class TestFullReportAnalyticsPersistsNormalizedKpis:
    """Bug B regression — full report JSON 必须含 normalize 后的 KPI。"""

    def test_full_analytics_json_contains_health_index(self, tmp_path, monkeypatch):
        """Full report 落盘的 analytics JSON 应包含 normalize 产物，
        否则下一日 change/quiet 的 KPI 区块会全部回退成 '—'。"""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        import json
        from pathlib import Path
        from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot
        snapshot = _build_minimal_full_snapshot(run_id=999, with_cumulative=True)

        # 屏蔽邮件与 LLM（测试只关心 JSON 落盘内容）
        monkeypatch.setattr(
            "qbu_crawler.server.report_snapshot.report.send_email",
            lambda **kw: {"success": True, "recipients": []})
        monkeypatch.setattr(
            "qbu_crawler.server.report_llm.generate_report_insights",
            lambda *a, **kw: {"hero_headline": "", "executive_bullets": []})

        result = generate_full_report_from_snapshot(snapshot, send_email=False)

        analytics_path = result.get("analytics_path")
        assert analytics_path and Path(analytics_path).exists()
        data = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
        kpis = data.get("kpis") or {}
        # 这些字段都是 normalize_deep_report_analytics 的产物
        assert "health_index" in kpis, \
            f"kpis 应含 health_index，当前 keys={sorted(kpis.keys())}"
        assert "high_risk_count" in kpis
        assert "own_negative_review_rate_display" in kpis
        # 同时应有 normalize 产物的顶层字段（用作可回归对照）
        assert "mode_display" in data
        assert "kpi_cards" in data

    def test_deep_analysis_reattached_by_label_code_not_position(self):
        """Regression — if normalize ever reorders clusters, deep_analysis must still
        land on the cluster with the matching label_code, not a positional neighbor."""
        from qbu_crawler.server.report_snapshot import _merge_post_normalize_mutations

        raw = {
            "self": {"top_negative_clusters": [
                {"label_code": "A", "deep_analysis": {"marker": "analysis-A"}},
                {"label_code": "B", "deep_analysis": {"marker": "analysis-B"}},
            ]},
            "report_copy": {"hero_headline": "x"},
        }
        # Normalize "reordered" the clusters (B before A) — position-based zip
        # would have misaligned; label-code match must still be correct.
        normalized = {
            "self": {"top_negative_clusters": [
                {"label_code": "B"},
                {"label_code": "A"},
            ]},
        }
        _merge_post_normalize_mutations(normalized, raw)

        by_label = {c["label_code"]: c for c in normalized["self"]["top_negative_clusters"]}
        assert by_label["A"]["deep_analysis"] == {"marker": "analysis-A"}
        assert by_label["B"]["deep_analysis"] == {"marker": "analysis-B"}
        assert normalized["report_copy"] == {"hero_headline": "x"}


def _build_minimal_full_snapshot(run_id: int, with_cumulative: bool):
    """最小可用 snapshot factory — 能跑通 build_report_analytics。"""
    products = [
        {"sku": f"OWN{i}", "name": f"Own {i}", "site": "waltons",
         "url": f"https://x/{i}", "price": 10.0, "stock_status": "in_stock",
         "rating": 4.6, "review_count": 20, "ownership": "own"}
        for i in range(5)
    ] + [
        {"sku": f"CMP{i}", "name": f"Comp {i}", "site": "basspro",
         "url": f"https://y/{i}", "price": 12.0, "stock_status": "in_stock",
         "rating": 4.0, "review_count": 30, "ownership": "competitor"}
        for i in range(3)
    ]
    reviews = [
        {"id": idx, "product_id": None, "product_sku": p["sku"],
         "product_name": p["name"], "site": p["site"], "ownership": p["ownership"],
         "rating": 5, "headline": "ok", "body": "great",
         "body_cn": "不错", "headline_cn": "还行",
         "author": f"u{idx}", "date_published": "2026-04-16",
         "scraped_at": "2026-04-16T12:00:00+08:00", "images": []}
        for idx, p in enumerate(products)
    ]
    snap = {
        "run_id": run_id, "logical_date": "2026-04-16",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "snapshot_at": "2026-04-16T15:00:00+08:00",
        "snapshot_hash": "test-hash",
        "products": products, "products_count": len(products),
        "reviews": reviews, "reviews_count": len(reviews),
        "translated_count": len(reviews), "untranslated_count": 0,
    }
    if with_cumulative:
        snap["cumulative"] = {
            "products": products, "products_count": len(products),
            "reviews": reviews, "reviews_count": len(reviews),
            "translated_count": len(reviews), "untranslated_count": 0,
        }
    return snap


from qbu_crawler.server.report_snapshot import determine_report_mode, compute_cluster_changes


class TestDetermineReportMode:
    def test_full_when_reviews_present(self):
        snapshot = {"reviews": [{"id": 1}], "products": []}
        mode, ctx = determine_report_mode(snapshot, None, None)
        assert mode == "full"

    def test_change_when_price_changed(self):
        snapshot = {"reviews": [], "products": [{"sku": "A", "name": "P", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        prev = {"products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        mode, ctx = determine_report_mode(snapshot, prev, None)
        assert mode == "change"
        assert ctx["changes"]["has_changes"] is True

    def test_quiet_when_nothing_changed(self):
        snapshot = {"reviews": [], "products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        prev = {"products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        mode, ctx = determine_report_mode(snapshot, prev, {"kpis": {}})
        assert mode == "quiet"

    def test_full_even_when_also_price_changed(self):
        snapshot = {"reviews": [{"id": 1}], "products": [{"sku": "A", "name": "P", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        prev = {"products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        mode, _ = determine_report_mode(snapshot, prev, None)
        assert mode == "full"  # Reviews take precedence

    def test_quiet_no_previous_snapshot(self):
        snapshot = {"reviews": [], "products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        mode, _ = determine_report_mode(snapshot, None, None)
        assert mode == "quiet"


class TestComputeClusterChanges:
    def test_new_cluster(self):
        current = [{"label_code": "quality_stability", "label_display": "质量稳定性",
                     "review_count": 5, "affected_product_count": 1, "severity": "high",
                     "review_dates": [], "last_seen": "2026-04-01"}]
        changes = compute_cluster_changes(current, [], date(2026, 4, 10))
        assert len(changes["new"]) == 1
        assert changes["new"][0]["label_display"] == "质量稳定性"

    def test_escalated(self):
        current = [{"label_code": "qc", "label_display": "QC", "review_count": 10,
                     "severity": "high", "last_seen": "2026-04-09", "review_dates": []}]
        previous = [{"label_code": "qc", "review_count": 7, "severity": "medium"}]
        changes = compute_cluster_changes(current, previous, date(2026, 4, 10))
        assert len(changes["escalated"]) == 1
        assert changes["escalated"][0]["delta"] == 3
        assert changes["escalated"][0]["severity_changed"] is True

    def test_improving(self):
        current = [{"label_code": "qc", "label_display": "QC", "review_count": 5,
                     "severity": "low", "last_seen": "2026-03-01", "review_dates": []}]
        previous = [{"label_code": "qc", "review_count": 5, "severity": "low"}]
        changes = compute_cluster_changes(current, previous, date(2026, 4, 10))
        assert len(changes["improving"]) == 1
        assert changes["improving"][0]["days_quiet"] >= 7

    def test_none_previous(self):
        current = [{"label_code": "qc", "label_display": "QC", "review_count": 5,
                     "severity": "high", "last_seen": "2026-04-01", "review_dates": []}]
        changes = compute_cluster_changes(current, None, date(2026, 4, 10))
        assert len(changes["new"]) == 1

    def test_empty_current(self):
        changes = compute_cluster_changes([], [{"label_code": "qc", "review_count": 5}], date(2026, 4, 10))
        assert changes == {"new": [], "escalated": [], "improving": [], "de_escalated": []}

    def test_string_logical_date(self):
        """Accept string dates as well as date objects."""
        current = [{"label_code": "qc", "label_display": "QC", "review_count": 5,
                     "severity": "low", "last_seen": "2026-03-01", "review_dates": []}]
        previous = [{"label_code": "qc", "review_count": 5, "severity": "low"}]
        changes = compute_cluster_changes(current, previous, "2026-04-10")
        assert len(changes["improving"]) == 1


from qbu_crawler.server.report_snapshot import _change_report_subject_prefix


class TestChangeReportSubjectPrefix:
    def test_single_price(self):
        assert _change_report_subject_prefix({"price_changes": [1]}) == "[价格变动]"

    def test_single_stock(self):
        assert _change_report_subject_prefix({"stock_changes": [1]}) == "[库存变动]"

    def test_multiple_types(self):
        assert _change_report_subject_prefix({"price_changes": [1], "stock_changes": [1]}) == "[数据变化]"

    def test_empty(self):
        assert _change_report_subject_prefix({}) == "[数据变化]"

    def test_new_products(self):
        assert _change_report_subject_prefix({"new_products": [1]}) == "[产品变动]"


class TestGenerateReportFromSnapshot:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
        models.init_db()
        return tmp_path

    def test_quiet_mode_returns_no_change(self, db):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        snapshot = {
            "run_id": 1, "logical_date": "2026-04-10",
            "snapshot_at": "2026-04-10T08:00:00",
            "products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
            "reviews": [], "products_count": 1, "reviews_count": 0,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["mode"] == "quiet"
        assert result["status"] == "completed_no_change"
        assert result["excel_path"] is None

    def test_change_mode_detected(self, db):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        # Create a previous run with different price
        analytics_path = str(db / "prev_analytics.json")
        snapshot_path = str(db / "prev_snapshot.json")
        Path(analytics_path).write_text('{"kpis": {"health_index": 60}}')
        Path(snapshot_path).write_text(json.dumps({
            "products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
        }))
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-09", "trigger_key": "daily:2026-04-09",
            "analytics_path": analytics_path, "snapshot_path": snapshot_path,
        })

        snapshot = {
            "run_id": 2, "logical_date": "2026-04-10",
            "snapshot_at": "2026-04-10T08:00:00",
            "products": [{"sku": "A", "name": "P", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
            "reviews": [], "products_count": 1, "reviews_count": 0,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["mode"] == "change"
        assert result["status"] == "completed"

    def test_full_mode_with_reviews(self, db, monkeypatch):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        # Mock the full report generation to avoid needing real data
        monkeypatch.setattr(
            "qbu_crawler.server.report_snapshot.generate_full_report_from_snapshot",
            lambda snapshot, send_email=True, output_path=None: {
                "status": "completed",
                "run_id": snapshot["run_id"],
                "products_count": 1, "reviews_count": 1,
            },
        )
        snapshot = {
            "run_id": 3, "logical_date": "2026-04-10",
            "products": [], "reviews": [{"id": 1}],
            "products_count": 1, "reviews_count": 1,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["mode"] == "full"

    def test_quiet_mode_generates_html(self, db):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        snapshot = {
            "run_id": 1, "logical_date": "2026-04-10",
            "snapshot_at": "2026-04-10T08:00:00",
            "products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
            "reviews": [], "products_count": 1, "reviews_count": 0,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["html_path"] is not None
        assert Path(result["html_path"]).exists()
        html_content = Path(result["html_path"]).read_text(encoding="utf-8")
        assert "2026-04-10" in html_content

    def test_change_mode_generates_html(self, db):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        analytics_path = str(db / "prev_analytics.json")
        snapshot_path = str(db / "prev_snapshot.json")
        Path(analytics_path).write_text('{"kpis": {"health_index": 60}}')
        Path(snapshot_path).write_text(json.dumps({
            "products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
        }))
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-09", "trigger_key": "daily:2026-04-09",
            "analytics_path": analytics_path, "snapshot_path": snapshot_path,
        })

        snapshot = {
            "run_id": 2, "logical_date": "2026-04-10",
            "snapshot_at": "2026-04-10T08:00:00",
            "products": [{"sku": "A", "name": "P", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
            "reviews": [], "products_count": 1, "reviews_count": 0,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["html_path"] is not None
        assert "change" in result["html_path"]

    def test_failure_raises(self, db, monkeypatch):
        """When full mode raises, generate_report_from_snapshot re-raises."""
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot

        def _boom(snapshot, send_email=True, output_path=None):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "qbu_crawler.server.report_snapshot.generate_full_report_from_snapshot",
            _boom,
        )
        snapshot = {
            "run_id": 99, "logical_date": "2026-04-10",
            "products": [], "reviews": [{"id": 1}],
            "products_count": 1, "reviews_count": 1,
        }
        with pytest.raises(RuntimeError, match="boom"):
            generate_report_from_snapshot(snapshot, send_email=False)


class TestSnapshotHashInReturnDicts:
    """Verify that change and quiet return dicts include snapshot_hash (Fix-1A)."""

    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
        models.init_db()
        return tmp_path

    def test_quiet_mode_includes_snapshot_hash(self, db):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        snapshot = {
            "run_id": 1, "logical_date": "2026-04-10",
            "snapshot_at": "2026-04-10T08:00:00",
            "snapshot_hash": "abc123hash",
            "products": [{"sku": "A", "name": "P", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
            "reviews": [], "products_count": 1, "reviews_count": 0,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["mode"] == "quiet"
        assert result["snapshot_hash"] == "abc123hash"

    def test_change_mode_includes_snapshot_hash(self, db):
        from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
        # Create a previous run with different price
        analytics_path = str(db / "prev_analytics.json")
        snapshot_path = str(db / "prev_snapshot.json")
        Path(analytics_path).write_text('{"kpis": {"health_index": 60}}')
        Path(snapshot_path).write_text(json.dumps({
            "products": [{"sku": "A", "name": "P", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
        }))
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-09", "trigger_key": "daily:2026-04-09",
            "analytics_path": analytics_path, "snapshot_path": snapshot_path,
        })

        snapshot = {
            "run_id": 2, "logical_date": "2026-04-10",
            "snapshot_at": "2026-04-10T08:00:00",
            "snapshot_hash": "def456hash",
            "products": [{"sku": "A", "name": "P", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}],
            "reviews": [], "products_count": 1, "reviews_count": 0,
        }
        result = generate_report_from_snapshot(snapshot, send_email=False)
        assert result["mode"] == "change"
        assert result["snapshot_hash"] == "def456hash"


class TestShouldSendQuietEmail:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return db_file

    def _create_runs(self, modes):
        """Create sequential runs with given modes, setting report_mode via update."""
        for i, mode in enumerate(modes, 1):
            run = models.create_workflow_run({
                "workflow_type": "daily", "status": "completed",
                "report_phase": "full_done",
                "logical_date": f"2026-04-{i:02d}",
                "trigger_key": f"daily:2026-04-{i:02d}",
            })
            models.update_workflow_run(run["id"], report_mode=mode)

    def test_first_quiet_day_sends(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        self._create_runs(["full"])  # Previous was full
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is True
        assert mode is None
        assert consecutive == 0

    def test_third_quiet_day_sends(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        self._create_runs(["full", "quiet", "quiet"])  # 2 consecutive quiet before this one
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is True
        assert consecutive == 2

    def test_fourth_quiet_day_skips(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        self._create_runs(["full", "quiet", "quiet", "quiet"])  # 3 consecutive quiet
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is False
        assert consecutive == 3

    def test_seventh_quiet_day_sends_weekly(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        self._create_runs(["full"] + ["quiet"] * 6)  # 6 consecutive quiet
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is True
        assert mode == "weekly_digest"
        assert consecutive == 6

    def test_no_previous_runs_sends(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is True
        assert consecutive == 0

    def test_fifth_quiet_day_skips(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        self._create_runs(["full"] + ["quiet"] * 4)  # 4 consecutive quiet
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is False
        assert mode is None
        assert consecutive == 4

    def test_fourteenth_quiet_day_sends_weekly(self, db):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        # 13 consecutive quiet → 14th is also quiet, (13+1)%7 == 0
        self._create_runs(["full"] + ["quiet"] * 13)
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is True
        assert mode == "weekly_digest"
        assert consecutive == 13

    def test_custom_threshold_via_env(self, db, monkeypatch):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        monkeypatch.setenv("REPORT_QUIET_EMAIL_DAYS", "1")
        # With threshold=1: day 2 (1 consecutive quiet) should skip
        self._create_runs(["full", "quiet"])
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is False
        assert consecutive == 1

    def test_null_report_mode_breaks_streak(self, db):
        """Runs with NULL report_mode (pre-V3) should break the consecutive quiet count."""
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        # Create a run with NULL report_mode (default) then quiet runs
        run = models.create_workflow_run({
            "workflow_type": "daily", "status": "completed",
            "report_phase": "full_done",
            "logical_date": "2026-04-01",
            "trigger_key": "daily:2026-04-01",
        })
        # Don't set report_mode → it stays NULL
        # Then add 5 quiet runs
        for i in range(2, 7):
            r = models.create_workflow_run({
                "workflow_type": "daily", "status": "completed",
                "report_phase": "full_done",
                "logical_date": f"2026-04-{i:02d}",
                "trigger_key": f"daily:2026-04-{i:02d}",
            })
            models.update_workflow_run(r["id"], report_mode="quiet")
        # 5 consecutive quiet runs precede run_id=999
        # NULL run appears before those 5, but the streak stops at NULL
        send, mode, consecutive = should_send_quiet_email(run_id=999)
        assert send is False  # 5 consecutive quiet > threshold=3, not at day 7
        assert consecutive == 5


class TestChangeEmailKpiBindsToCurrentAnalytics:
    """Bug C regression — change 邮件 KPI 必须反映当日，而不是前一日。"""

    def test_change_email_uses_current_own_review_rows(self, monkeypatch, tmp_path):
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
        # 前一日 own=100，当日 cumulative own=250
        prev = {"kpis": {"own_review_rows": 100, "health_index": 80,
                         "own_negative_review_rate_display": "2.0%",
                         "high_risk_count": 0}}
        cur = {"kpis": {"own_review_rows": 250, "health_index": 92,
                        "own_negative_review_rate_display": "1.2%",
                        "high_risk_count": 1}}
        snapshot = {"logical_date": "2026-04-16",
                    "snapshot_at": "2026-04-16T15:00:00+08:00"}
        changes = {"rating_changes": [], "price_changes": [],
                   "stock_changes": []}

        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from pathlib import Path as _P
        tpl_dir = _P("qbu_crawler/server/report_templates")
        env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html", "j2"]))
        template = env.get_template("email_change.html.j2")
        html = template.render(
            logical_date="2026-04-16",
            snapshot=snapshot, analytics=cur, previous_analytics=prev,
            changes=changes, threshold=2)

        # 当日 own=250 应出现；昨天 own=100 不应出现
        assert ">250<" in html, "评论总量应展示当日 250"
        assert ">100<" not in html, "不应再展示昨天的 100"
        # health_index 同理
        assert ">92<" in html
        assert ">80<" not in html
