import pytest
from qbu_crawler.models import _parse_date_published

class TestUnifiedAnchor:
    """两条路径必须用同一 anchor (scraped_at)。"""

    def test_relative_time_uses_scraped_at_anchor(self):
        scraped_at = "2026-04-26 12:00:00"
        result = _parse_date_published("a year ago", scraped_at=scraped_at)
        assert result.startswith("2025-04")  # 一年前 = scraped_at - 365 天

    def test_absolute_date_unchanged(self):
        result = _parse_date_published("01/15/2024", scraped_at="2026-04-26 12:00:00")
        assert result == "2024-01-15"

    def test_returns_with_metadata(self):
        result, meta = _parse_date_published(
            "2 years ago",
            scraped_at="2026-04-26 12:00:00",
            return_meta=True,
        )
        assert result.startswith("2024-04")
        assert meta["method"] == "relative_scraped_at"
        assert meta["anchor"] == "2026-04-26 12:00:00"
        assert 0 < meta["confidence"] < 1.0  # 相对时间置信度低

    def test_iso_date_returns_absolute_method(self):
        result, meta = _parse_date_published(
            "2026-01-15", scraped_at="2026-04-26 12:00:00", return_meta=True,
        )
        assert result == "2026-01-15"
        assert meta["method"] == "absolute"
        assert meta["confidence"] == 1.0

    def test_unknown_returns_meta_unknown(self):
        result, meta = _parse_date_published("nonsense", return_meta=True)
        assert result is None
        assert meta["method"] == "unknown"
        assert meta["confidence"] == 0.0

    def test_no_scraped_at_falls_back_to_now(self):
        result, meta = _parse_date_published("a day ago", return_meta=True)
        assert result is not None
        assert meta["method"] == "relative_now"
        assert meta["confidence"] == 0.95

    def test_empty_input_returns_none_with_meta(self):
        result, meta = _parse_date_published("", return_meta=True)
        assert result is None
        assert meta["method"] == "unknown"
