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
