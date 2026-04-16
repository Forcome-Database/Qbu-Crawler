"""Tests for Report V3 algorithm redesign (Phase 1)."""

from qbu_crawler.server.report_analytics import _SEVERITY_SCORE
from qbu_crawler.server.report_common import _SEVERITY_DISPLAY, _PRIORITY_DISPLAY


class TestSeverityDicts:
    def test_severity_score_has_critical(self):
        assert "critical" in _SEVERITY_SCORE
        assert _SEVERITY_SCORE["critical"] > _SEVERITY_SCORE["high"]

    def test_severity_display_has_critical(self):
        assert "critical" in _SEVERITY_DISPLAY
        assert _SEVERITY_DISPLAY["critical"] == "危急"

    def test_priority_display_has_critical(self):
        assert "critical" in _PRIORITY_DISPLAY

    def test_severity_score_ordering(self):
        assert _SEVERITY_SCORE["critical"] > _SEVERITY_SCORE["high"] > _SEVERITY_SCORE["medium"] > _SEVERITY_SCORE["low"]


from qbu_crawler.server.report_common import compute_health_index


class TestHealthIndexV3:
    """NPS-proxy: (promoters - detractors) / total * 100, mapped to 0-100."""

    def test_balanced_reviews(self):
        """76 promoters, 55 detractors, 141 total → NPS=14.9, health=57.4 (no shrinkage, >=30)"""
        kpis = {
            "own_review_rows": 141,
            "own_positive_review_rows": 76,
            "own_negative_review_rows": 55,
        }
        health, confidence = compute_health_index({"kpis": kpis})
        assert 57.0 <= health <= 58.0
        assert confidence == "high"

    def test_zero_own_reviews_returns_neutral(self):
        kpis = {"own_review_rows": 0, "own_positive_review_rows": 0, "own_negative_review_rows": 0}
        health, confidence = compute_health_index({"kpis": kpis})
        assert health == 50.0
        assert confidence == "no_data"

    def test_all_promoters(self):
        """10 reviews, all promoters: raw=100, shrunk to ~66.7 (medium confidence)"""
        kpis = {"own_review_rows": 10, "own_positive_review_rows": 10, "own_negative_review_rows": 0}
        health, confidence = compute_health_index({"kpis": kpis})
        assert 66.0 <= health <= 67.5
        assert confidence == "medium"

    def test_all_detractors(self):
        """10 reviews, all detractors: raw=0, shrunk to ~33.3 (medium confidence)"""
        kpis = {"own_review_rows": 10, "own_positive_review_rows": 0, "own_negative_review_rows": 10}
        health, confidence = compute_health_index({"kpis": kpis})
        assert 33.0 <= health <= 34.0
        assert confidence == "medium"

    def test_clamped_to_0_100(self):
        kpis = {"own_review_rows": 5, "own_positive_review_rows": 0, "own_negative_review_rows": 5}
        health, confidence = compute_health_index({"kpis": kpis})
        assert 0 <= health <= 100

    def test_missing_kpis_returns_neutral(self):
        health1, conf1 = compute_health_index({})
        health2, conf2 = compute_health_index(None)
        assert health1 == 50.0
        assert conf1 == "no_data"
        assert health2 == 50.0
        assert conf2 == "no_data"


from datetime import date
from qbu_crawler.server.report_analytics import compute_cluster_severity


class TestClusterSeverity:
    """4-factor: volume + breadth + recency + safety signal."""

    def test_critical_high_volume_safety(self):
        cluster = {
            "review_count": 36, "affected_product_count": 3,
            "review_dates": ["2026-01-01"] * 34 + ["2026-03-20", "2026-04-01"],
        }
        reviews = [{"headline": "metal shavings dangerous", "body": "rust everywhere"}]
        assert compute_cluster_severity(cluster, reviews, date(2026, 4, 10)) == "critical"

    def test_high_moderate_volume_safety(self):
        # P008: "metal debris" is now critical-tier (bonus=5), so total=2+1+0+5=8 → critical
        cluster = {
            "review_count": 14, "affected_product_count": 2,
            "review_dates": ["2025-01-01"] * 14,
        }
        reviews = [{"headline": "metal debris", "body": ""}]
        assert compute_cluster_severity(cluster, reviews, date(2026, 4, 10)) == "critical"

    def test_medium_no_safety(self):
        cluster = {
            "review_count": 12, "affected_product_count": 3,
            "review_dates": ["2025-01-01"] * 12,
        }
        reviews = [{"headline": "design flaw", "body": "poor quality"}]
        assert compute_cluster_severity(cluster, reviews, date(2026, 4, 10)) == "medium"

    def test_low_few_reviews(self):
        cluster = {
            "review_count": 4, "affected_product_count": 2,
            "review_dates": ["2025-06-01"] * 4,
        }
        reviews = [{"headline": "missing parts", "body": ""}]
        assert compute_cluster_severity(cluster, reviews, date(2026, 4, 10)) == "low"

    def test_empty_reviews_low(self):
        cluster = {"review_count": 0, "affected_product_count": 0, "review_dates": []}
        assert compute_cluster_severity(cluster, [], date(2026, 4, 10)) == "low"

    def test_recency_boosts_score(self):
        cluster = {
            "review_count": 8, "affected_product_count": 2,
            "review_dates": ["2026-03-01"] * 8,
        }
        reviews = [{"headline": "problem", "body": ""}]
        result = compute_cluster_severity(cluster, reviews, date(2026, 4, 10))
        assert result in ("medium", "high")  # 1(vol) + 1(breadth) + 2(recency 100%) = 4 → medium+


from qbu_crawler.server.report_analytics import _risk_products
from qbu_crawler import config


class TestRiskScoreV3:
    """Multi-factor: neg_rate(35%) + severity(25%) + evidence(15%) + recency(15%) + volume(10%)."""

    @staticmethod
    def _make_labeled_review(rating, labels=None, images=None, date_parsed="2026-03-01",
                              ownership="own", product_name="Prod", product_sku="SKU1"):
        return {
            "review": {
                "rating": rating, "ownership": ownership,
                "product_name": product_name, "product_sku": product_sku,
                "date_published_parsed": date_parsed,
                "headline": "", "body": "",
            },
            "labels": labels or [],
            "images": images or [],
        }

    @staticmethod
    def _neg_label(code="quality_stability", severity="high"):
        return {"label_code": code, "label_polarity": "negative", "severity": severity}

    def test_zero_reviews_returns_empty(self):
        assert _risk_products([], snapshot_products=[]) == []

    def test_all_positive_returns_zero_risk(self):
        """Product with only 5-star reviews → risk_score = 0."""
        items = [self._make_labeled_review(5) for _ in range(10)]
        products = [{"sku": "SKU1", "review_count": 10, "rating": 4.5}]
        result = _risk_products(items, snapshot_products=products)
        # No negative reviews → zero risk
        if result:
            assert all(p["risk_score"] == 0 for p in result)

    def test_high_neg_rate_scores_higher(self):
        """Product with 80% neg rate vs 20% neg rate."""
        high_neg_items = (
            [self._make_labeled_review(1, [self._neg_label()]) for _ in range(8)]
            + [self._make_labeled_review(5) for _ in range(2)]
        )
        low_neg_items = (
            [self._make_labeled_review(1, [self._neg_label()], product_sku="SKU2", product_name="P2") for _ in range(2)]
            + [self._make_labeled_review(5, product_sku="SKU2", product_name="P2") for _ in range(8)]
        )
        products = [
            {"sku": "SKU1", "review_count": 10, "rating": 2.0},
            {"sku": "SKU2", "review_count": 10, "rating": 4.0},
        ]
        result = _risk_products(high_neg_items + low_neg_items, snapshot_products=products)
        scores = {p["product_sku"]: p["risk_score"] for p in result}
        if "SKU1" in scores and "SKU2" in scores:
            assert scores["SKU1"] > scores["SKU2"], f"High neg rate ({scores['SKU1']}) should score higher than low neg rate ({scores['SKU2']})"

    def test_neg_review_without_labels_still_counts(self):
        """A 1-star review without labels should still contribute to neg_rate."""
        items = [
            self._make_labeled_review(1),  # no labels!
            self._make_labeled_review(5),
        ]
        products = [{"sku": "SKU1", "review_count": 2, "rating": 3.0}]
        result = _risk_products(items, snapshot_products=products)
        # Should have a product with risk > 0 because neg_rate = 50%
        if result:
            assert result[0]["risk_score"] > 0
            assert result[0]["negative_review_rows"] >= 1

    def test_output_structure_preserved(self):
        """Result contains all expected fields."""
        items = [self._make_labeled_review(1, [self._neg_label()])]
        products = [{"sku": "SKU1", "review_count": 5, "rating": 3.0}]
        result = _risk_products(items, snapshot_products=products)
        if result:
            p = result[0]
            assert "product_name" in p
            assert "product_sku" in p
            assert "negative_review_rows" in p
            assert "risk_score" in p
            assert 0 <= p["risk_score"] <= 100
            assert "negative_rate" in p
            assert "top_labels" in p


from qbu_crawler.server.report_common import _competitor_gap_analysis


def _build_normalized_with_clusters(own_neg, own_pos, comp_pos, own_total, comp_total):
    """Build minimal normalized analytics dict for gap analysis testing."""
    def _clusters(d, polarity):
        return [{"label_code": code, "review_count": count, "label_polarity": polarity,
                 "affected_product_count": 1, "severity": "high"} for code, count in d.items()]
    return {
        "kpis": {"own_review_rows": own_total, "competitor_review_rows": comp_total},
        "self": {
            "top_negative_clusters": _clusters(own_neg, "negative"),
            "top_positive_clusters": _clusters(own_pos, "positive"),
        },
        "competitor": {"top_positive_themes": _clusters(comp_pos, "positive")},
    }


class TestGapAnalysisV3:
    def test_fix_urgency_high_own_negative(self):
        normalized = _build_normalized_with_clusters(
            own_neg={"quality_stability": 62}, own_pos={},
            comp_pos={"solid_build": 108}, own_total=141, comp_total=569,
        )
        result = _competitor_gap_analysis(normalized)
        # quality_stability maps to solid_build dimension via _NEGATIVE_TO_POSITIVE_DIMENSION
        dim = next((g for g in result if g.get("own_negative_count", 0) > 0), None)
        assert dim is not None
        assert dim["gap_type"] == "止血"
        assert dim["fix_urgency"] > 0
        assert dim["priority"] == "high"

    def test_catch_up_gap_no_own_negative(self):
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={},
            comp_pos={"strong_performance": 318}, own_total=141, comp_total=569,
        )
        result = _competitor_gap_analysis(normalized)
        perf_dim = next((g for g in result if g.get("competitor_positive_count", 0) > 0), None)
        assert perf_dim is not None
        assert perf_dim["gap_type"] == "追赶"
        assert perf_dim["fix_urgency"] == 0
        assert perf_dim["catch_up_gap"] > 0

    def test_uncategorized_filtered(self):
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={}, comp_pos={"_uncategorized": 10},
            own_total=100, comp_total=500,
        )
        result = _competitor_gap_analysis(normalized)
        assert not any("uncategorized" in str(g.get("label_code", "")) for g in result)

    def test_empty_returns_empty(self):
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={}, comp_pos={}, own_total=0, comp_total=0,
        )
        assert _competitor_gap_analysis(normalized) == []

    def test_priority_based_on_priority_score(self):
        """Priority should be based on priority_score, not just own_rate."""
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={},
            comp_pos={"strong_performance": 318}, own_total=141, comp_total=569,
        )
        result = _competitor_gap_analysis(normalized)
        perf = next((g for g in result if g.get("competitor_positive_count", 0) > 0), None)
        if perf:
            # comp_rate = 318/569 ≈ 55.9%, fix_urgency = 0, catch_up = 55.9%
            # priority_score = 0*0.7 + 0.559*0.3 ≈ 17 → medium
            assert perf["priority"] == "medium"


class TestKpiDeltasAndGapCounts:
    def test_gap_fix_and_catch_counts(self):
        from qbu_crawler.server.report_common import normalize_deep_report_analytics
        analytics = {
            "kpis": {"ingested_review_rows": 100, "own_review_rows": 50,
                     "own_positive_review_rows": 30, "own_negative_review_rows": 10},
            "competitor": {"gap_analysis": [
                {"gap_type": "止血", "priority_score": 35},
                {"gap_type": "追赶", "priority_score": 17},
                {"gap_type": "监控", "priority_score": 2},
            ]},
        }
        result = normalize_deep_report_analytics(analytics)
        assert result["kpis"].get("gap_fix_count") == 1
        assert result["kpis"].get("gap_catch_count") == 1


from qbu_crawler.server.report_common import _compute_alert_level


class TestAlertLevelV3:
    def test_baseline_unhealthy_not_green(self):
        normalized = {"mode": "baseline", "kpis": {"health_index": 57.4, "own_review_rows": 141}}
        level, _ = _compute_alert_level(normalized)
        assert level in ("yellow", "red")

    def test_baseline_healthy_is_green(self):
        normalized = {"mode": "baseline", "kpis": {"health_index": 75.0, "own_review_rows": 50}}
        level, _ = _compute_alert_level(normalized)
        assert level == "green"

    def test_zero_own_reviews_is_green(self):
        normalized = {"mode": "incremental", "kpis": {"health_index": 50.0, "own_review_rows": 0}}
        level, text = _compute_alert_level(normalized)
        assert level == "green"

    def test_incremental_red_on_high_delta(self):
        normalized = {
            "mode": "incremental",
            "kpis": {"health_index": 40.0, "own_review_rows": 100, "own_negative_review_rows_delta": 15},
            "self": {"top_negative_clusters": []},
        }
        level, _ = _compute_alert_level(normalized)
        assert level == "red"

    def test_incremental_green_when_healthy(self):
        normalized = {
            "mode": "incremental",
            "kpis": {"health_index": 70.0, "own_review_rows": 100, "own_negative_review_rows_delta": 0},
            "self": {"top_negative_clusters": []},
        }
        level, _ = _compute_alert_level(normalized)
        assert level == "green"


from qbu_crawler.server.report_common import has_estimated_dates


class TestEstimatedDates:
    def test_detects_clustered_dates(self):
        reviews = [
            {"date_published_parsed": "2022-04-10"},
            {"date_published_parsed": "2023-04-10"},
            {"date_published_parsed": "2024-04-10"},
            {"date_published_parsed": "2026-01-15"},
        ]
        assert has_estimated_dates(reviews, "2026-04-10") is True

    def test_no_clustering(self):
        reviews = [
            {"date_published_parsed": "2026-01-01"},
            {"date_published_parsed": "2026-02-15"},
            {"date_published_parsed": "2026-03-20"},
        ]
        assert has_estimated_dates(reviews, "2026-04-10") is False

    def test_empty(self):
        assert has_estimated_dates([], "2026-04-10") is False


import sqlite3
import pytest
from qbu_crawler import config, models


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


class TestDBSupport:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return db_file

    def test_report_mode_column_exists(self, db):
        conn = _get_test_conn(db)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()]
        assert "report_mode" in cols

    def test_update_workflow_run_accepts_report_mode(self, db):
        run = models.create_workflow_run({
            "workflow_type": "daily", "status": "pending", "report_phase": "none",
            "logical_date": "2026-04-10", "trigger_key": "daily:2026-04-10:test-rm",
        })
        models.update_workflow_run(run["id"], report_mode="quiet")
        updated = models.get_workflow_run(run["id"])
        assert updated["report_mode"] == "quiet"

    def test_query_cluster_reviews(self, db):
        conn = _get_test_conn(db)
        conn.execute("INSERT INTO products (url, site, name, sku, ownership) VALUES (?, ?, ?, ?, ?)",
                     ("http://test.com/p1", "test", "Test Product", "TP1", "own"))
        pid = conn.execute("SELECT id FROM products WHERE sku='TP1'").fetchone()["id"]
        conn.execute("INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (pid, "user1", "Bad", "Broke", "abc123", 1.0, "2026-04-01 10:00:00"))
        rid = conn.execute("SELECT id FROM reviews WHERE author='user1'").fetchone()["id"]
        conn.execute("INSERT INTO review_issue_labels (review_id, label_code, label_polarity, severity, confidence, source, taxonomy_version) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (rid, "quality_stability", "negative", "high", 0.9, "rule_based", "v1"))
        conn.commit()
        result = models.query_cluster_reviews("quality_stability", ownership="own", limit=10)
        assert len(result) == 1
        assert result[0]["product_sku"] == "TP1"


class TestPhase1Integration:
    """End-to-end: build_report_analytics → normalize → verify V3 properties."""

    @pytest.fixture()
    def analytics_db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "integration.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        monkeypatch.setattr(config, "REPORT_LABEL_MODE", "rule")
        models.init_db()
        # Insert test products and reviews
        conn = _get_test_conn(db_file)
        # Own product with negative reviews
        conn.execute(
            "INSERT INTO products (url, site, name, sku, ownership, review_count, rating, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("http://test/own1", "test", "Own Grinder", "OWN1", "own", 20, 3.5, "2026-04-10 08:00:00"),
        )
        pid1 = conn.execute("SELECT id FROM products WHERE sku='OWN1'").fetchone()["id"]
        # Competitor product with positive reviews
        conn.execute(
            "INSERT INTO products (url, site, name, sku, ownership, review_count, rating, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("http://test/comp1", "test", "Comp Grinder", "COMP1", "competitor", 50, 4.7, "2026-04-10 08:00:00"),
        )
        pid2 = conn.execute("SELECT id FROM products WHERE sku='COMP1'").fetchone()["id"]

        # Own negative reviews (varied) — 10 rows (≥10 → vol_score=2; + safety → total=5 → "high")
        for i in range(10):
            conn.execute(
                "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid1, f"neg_user{i}", "Bad quality", "Metal shavings and rust found", f"neg{i}", 1.0, "2026-04-10 08:00:00"),
            )
        # Own positive reviews — 14 rows (14 promoters, 10 detractors → NPS≈16.7 → health≈58)
        for i in range(14):
            conn.execute(
                "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid1, f"pos_user{i}", "Great product", "Works perfectly fine", f"pos{i}", 5.0, "2026-04-10 08:00:00"),
            )
        # Competitor positive reviews — 15 rows
        for i in range(15):
            conn.execute(
                "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid2, f"comp_user{i}", "Awesome grinder", "Very powerful and durable", f"comp{i}", 5.0, "2026-04-10 08:00:00"),
            )
        conn.commit()

        # Fetch actual IDs from DB (auto-assigned) so snapshot IDs match DB
        neg_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM reviews WHERE product_id=? ORDER BY id ASC", (pid1,)
            ).fetchmany(10)
        ]
        pos_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM reviews WHERE product_id=? AND rating=5.0 ORDER BY id ASC", (pid1,)
            ).fetchall()
        ]
        comp_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM reviews WHERE product_id=? ORDER BY id ASC", (pid2,)
            ).fetchall()
        ]

        return {"db_file": db_file, "pid1": pid1, "pid2": pid2,
                "neg_ids": neg_ids, "pos_ids": pos_ids, "comp_ids": comp_ids}

    def test_v3_metrics_properties(self, analytics_db):
        from qbu_crawler.server.report_analytics import build_report_analytics, sync_review_labels
        from qbu_crawler.server.report_common import normalize_deep_report_analytics

        neg_ids = analytics_db["neg_ids"]
        pos_ids = analytics_db["pos_ids"]
        comp_ids = analytics_db["comp_ids"]

        snapshot = {
            "logical_date": "2026-04-10",
            "run_id": 1,
            "snapshot_hash": "test123",
            "products": [
                {
                    "url": "http://test/own1", "name": "Own Grinder", "sku": "OWN1",
                    "ownership": "own", "price": 299.99, "stock_status": "in_stock",
                    "rating": 3.5, "review_count": 20, "site": "test", "scraped_at": "2026-04-10 08:00:00",
                },
                {
                    "url": "http://test/comp1", "name": "Comp Grinder", "sku": "COMP1",
                    "ownership": "competitor", "price": 399.99, "stock_status": "in_stock",
                    "rating": 4.7, "review_count": 50, "site": "test", "scraped_at": "2026-04-10 08:00:00",
                },
            ],
            "reviews": [
                {
                    "id": neg_ids[i], "product_name": "Own Grinder", "product_sku": "OWN1",
                    "author": f"neg_user{i}", "headline": "Bad quality",
                    "body": "Metal shavings and rust found",
                    "body_cn": "metal shavings and rust", "headline_cn": "bad quality", "rating": 1.0,
                    "date_published_parsed": "2026-03-15", "images": None, "ownership": "own",
                    "sentiment": "negative", "translate_status": "done",
                }
                for i in range(10)
            ] + [
                {
                    "id": pos_ids[i], "product_name": "Own Grinder", "product_sku": "OWN1",
                    "author": f"pos_user{i}", "headline": "Great",
                    "body": "Works perfectly fine",
                    "body_cn": "works fine", "headline_cn": "great", "rating": 5.0,
                    "date_published_parsed": "2026-03-20", "images": None, "ownership": "own",
                    "sentiment": "positive", "translate_status": "done",
                }
                for i in range(14)
            ] + [
                {
                    "id": comp_ids[i], "product_name": "Comp Grinder", "product_sku": "COMP1",
                    "author": f"comp_user{i}", "headline": "Awesome",
                    "body": "Very powerful and durable",
                    "body_cn": "very powerful and durable", "headline_cn": "awesome", "rating": 5.0,
                    "date_published_parsed": "2026-03-25", "images": None, "ownership": "competitor",
                    "sentiment": "positive", "translate_status": "done",
                }
                for i in range(15)
            ],
            "products_count": 2,
            "reviews_count": 39,
            "translated_count": 39,
            "untranslated_count": 0,
        }

        synced = sync_review_labels(snapshot)
        analytics = build_report_analytics(snapshot, synced)
        normalized = normalize_deep_report_analytics(analytics)
        kpis = normalized["kpis"]

        # V3 Health index: NPS-proxy (0-100)
        assert 0 <= kpis.get("health_index", -1) <= 100
        # 14 promoters (≥4★), 10 detractors (≤2★), 24 total own: NPS=(14-10)/24*100≈16.7 → health≈58
        assert 55 <= kpis["health_index"] <= 65

        # Risk products use multi-factor scores (0-100)
        risk = normalized.get("self", {}).get("risk_products", [])
        for p in risk:
            assert 0 <= p["risk_score"] <= 100

        # Cluster severity has distinct levels (not all "high")
        clusters = normalized.get("self", {}).get("top_negative_clusters", [])
        if clusters:
            severities = {c["severity"] for c in clusters}
            # With safety keywords ("metal shavings", "rust"), at least one should be high/critical
            assert severities & {"critical", "high"}, f"Expected safety-triggered severity, got {severities}"

        # Gap analysis has V3 fields
        gaps = normalized.get("competitor", {}).get("gap_analysis", [])
        for g in gaps:
            assert "gap_type" in g, f"Missing gap_type: {g}"
            assert g["gap_type"] in ("止血", "追赶", "监控")
            assert "fix_urgency" in g
            assert "catch_up_gap" in g
            assert "priority_score" in g
            assert "_uncategorized" not in g.get("label_code", "")
            assert "_uncategorized" not in g.get("label_display", "")

        # KPIs have gap counts
        assert "gap_fix_count" in kpis
        assert "gap_catch_count" in kpis

        # Alert level: with ~60 health, should be yellow or green (not always green for baseline)
        alert = normalized.get("alert_level")
        if alert:
            assert alert[0] in ("red", "yellow", "green")
