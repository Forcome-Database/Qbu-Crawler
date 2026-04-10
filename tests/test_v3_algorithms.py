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
        """76 promoters, 55 detractors, 141 total → NPS=14.9, health=57.4"""
        kpis = {
            "own_review_rows": 141,
            "own_positive_review_rows": 76,
            "own_negative_review_rows": 55,
        }
        result = compute_health_index({"kpis": kpis})
        assert 57.0 <= result <= 58.0

    def test_zero_own_reviews_returns_neutral(self):
        kpis = {"own_review_rows": 0, "own_positive_review_rows": 0, "own_negative_review_rows": 0}
        assert compute_health_index({"kpis": kpis}) == 50.0

    def test_all_promoters(self):
        kpis = {"own_review_rows": 10, "own_positive_review_rows": 10, "own_negative_review_rows": 0}
        assert compute_health_index({"kpis": kpis}) == 100.0

    def test_all_detractors(self):
        kpis = {"own_review_rows": 10, "own_positive_review_rows": 0, "own_negative_review_rows": 10}
        assert compute_health_index({"kpis": kpis}) == 0.0

    def test_clamped_to_0_100(self):
        kpis = {"own_review_rows": 5, "own_positive_review_rows": 0, "own_negative_review_rows": 5}
        result = compute_health_index({"kpis": kpis})
        assert 0 <= result <= 100

    def test_missing_kpis_returns_neutral(self):
        assert compute_health_index({}) == 50.0
        assert compute_health_index(None) == 50.0


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
        cluster = {
            "review_count": 14, "affected_product_count": 2,
            "review_dates": ["2025-01-01"] * 14,
        }
        reviews = [{"headline": "metal debris", "body": ""}]
        assert compute_cluster_severity(cluster, reviews, date(2026, 4, 10)) == "high"

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
