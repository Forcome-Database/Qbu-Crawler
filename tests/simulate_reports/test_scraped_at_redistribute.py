from datetime import date, datetime
from scripts.simulate_reports.data_builder import redistribute_scraped_at


def test_redistribute_keeps_count():
    reviews = [
        {"id": i, "date_published_parsed": f"2025-01-{(i%28)+1:02d}T10:00:00"}
        for i in range(20)
    ]
    out = redistribute_scraped_at(reviews, timeline_start=date(2026, 3, 20))
    assert len(out) == 20


def test_redistribute_respects_not_before_publish_date():
    reviews = [
        {"id": 1, "date_published_parsed": "2026-04-10T00:00:00"},  # 发布晚于 timeline start
    ]
    out = redistribute_scraped_at(reviews, timeline_start=date(2026, 3, 20))
    scraped = datetime.fromisoformat(out[0]["scraped_at"])
    pub = datetime.fromisoformat(out[0]["date_published_parsed"])
    assert scraped >= pub, "scraped_at must not precede publish date"


def test_redistribute_15pct_on_day1():
    """Earliest 15% should be stamped at timeline_start (cold-start)."""
    reviews = [
        {"id": i, "date_published_parsed": f"2024-0{(i%9)+1}-15T10:00:00"}
        for i in range(100)
    ]
    out = redistribute_scraped_at(reviews, timeline_start=date(2026, 3, 20))
    day1 = sum(
        1 for r in out
        if r["scraped_at"].startswith("2026-03-20")
    )
    assert 12 <= day1 <= 18, f"expected ~15, got {day1}"
