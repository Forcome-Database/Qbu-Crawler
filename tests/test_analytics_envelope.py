"""AnalyticsEnvelope: persistence contract for report analytics."""
from qbu_crawler.server.report_common import (
    build_analytics_envelope,
    load_analytics_envelope,
)


def test_envelope_persists_normalized_derived_fields(tmp_path):
    raw = {
        "kpis": {
            "own_review_rows": 50,
            "own_positive_review_rows": 40,
            "own_negative_review_rows": 3,
            "competitor_review_rows": 20,
            "own_negative_review_rate": 0.06,
            "ingested_review_rows": 70,
            "site_reported_review_total_current": 100,
            "product_count": 5,
            "own_product_count": 3,
            "competitor_product_count": 2,
        },
        "self": {"risk_products": []},
        "competitor": {},
    }
    envelope = build_analytics_envelope(raw, mode="full", mode_context={})
    assert envelope["_schema_version"] == "v4"
    assert envelope["kpis_normalized"]["health_index"] is not None
    assert envelope["kpis_normalized"]["own_negative_review_rate_display"] == "6.0%"
    assert envelope["kpis_normalized"]["high_risk_count"] == 0
    assert envelope["kpis_raw"] == raw["kpis"]

    path = tmp_path / "analytics.json"
    path.write_text(
        __import__("json").dumps(envelope, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = load_analytics_envelope(str(path))
    assert loaded["kpis_normalized"]["health_index"] is not None


def test_envelope_legacy_fallback_from_raw_dict():
    """P1 fix: pass a legacy (no _schema_version) dict; loader must wrap it."""
    legacy = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 8,
            "own_negative_review_rows": 1,
            "competitor_review_rows": 0,
            "own_negative_review_rate": 0.1,
            "ingested_review_rows": 10,
            "product_count": 2, "own_product_count": 2, "competitor_product_count": 0,
        },
        "self": {"risk_products": []},
        "competitor": {},
    }
    wrapped = load_analytics_envelope(legacy)
    assert wrapped["_schema_version"] == "v4"
    assert wrapped["kpis_normalized"]["health_index"] is not None
