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
