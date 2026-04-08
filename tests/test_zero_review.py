"""Test zero-review incremental report handling."""
import sys
import types
from unittest.mock import MagicMock

# Stub json_repair before importing report_snapshot (which imports report_llm → json_repair)
if "json_repair" not in sys.modules:
    json_repair_mock = types.ModuleType("json_repair")
    json_repair_mock.repair_json = MagicMock(side_effect=lambda x, **kw: x)
    sys.modules["json_repair"] = json_repair_mock


def test_zero_review_snapshot_returns_no_change():
    """When snapshot has zero reviews, should return completed_no_change without crashing."""
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-08",
        "snapshot_hash": "hash-empty",
        "products_count": 1,
        "reviews_count": 0,
        "translated_count": 0,
        "untranslated_count": 0,
        "products": [
            {
                "name": "P1",
                "sku": "S1",
                "ownership": "own",
                "price": 100,
                "rating": 3.5,
                "review_count": 50,
                "site": "basspro",
                "stock_status": "in_stock",
            },
        ],
        "reviews": [],
    }
    result = generate_full_report_from_snapshot(snapshot, send_email=False)
    assert result is not None
    assert result.get("status") == "completed_no_change"
    assert "reviews" in result.get("reason", "").lower()
