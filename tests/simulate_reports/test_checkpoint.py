from datetime import date
from scripts.simulate_reports.checkpoint import checkpoint_name, parse_checkpoint_name


def test_name_roundtrip():
    assert checkpoint_name(date(2026, 3, 20)) == "2026-03-20.db"
    assert parse_checkpoint_name("2026-03-20.db") == date(2026, 3, 20)
