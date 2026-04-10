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
