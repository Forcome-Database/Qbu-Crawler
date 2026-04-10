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
