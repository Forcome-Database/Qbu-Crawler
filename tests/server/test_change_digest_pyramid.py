import pytest
from qbu_crawler.server.report_snapshot import build_change_digest


def _make_review(*, ownership, rating, scraped_at, product_name="Widget A", sku="SKU1", date_published="2026-04-26"):
    return {
        "id": hash((product_name, scraped_at, rating, ownership)) & 0xFFFF,
        "ownership": ownership,
        "rating": rating,
        "scraped_at": scraped_at,
        "date_published": date_published,
        "date_published_parsed": date_published,
        "product_name": product_name,
        "product_sku": sku,
        "headline": "h", "body": "b",
        "analysis_labels_parsed": [],
    }


def _empty_analytics(report_semantics="incremental"):
    return {
        "report_semantics": report_semantics,
        "kpis": {"untranslated_count": 0},
        "self": {"top_negative_clusters": []},
        "baseline_day_index": 1,
        "baseline_display_state": "initial",
    }


def test_change_digest_has_three_pyramid_layers():
    """F011 H22 — digest exposes immediate_attention / trend_changes / competitive_opportunities."""
    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-25T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "reviews": [],
        "products": [],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    assert "immediate_attention" in digest
    assert "trend_changes" in digest
    assert "competitive_opportunities" in digest


def test_immediate_attention_groups_own_new_negatives_by_product():
    """v1.1 / B4 — own new negatives filter by scraped_at >= data_since."""
    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-26T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "products": [],
        "reviews": [
            _make_review(ownership="own", rating=1, scraped_at="2026-04-26T10:00:00+08:00", product_name=".75 HP"),
            _make_review(ownership="own", rating=2, scraped_at="2026-04-26T11:00:00+08:00", product_name=".75 HP"),
            # before data_since: must be excluded
            _make_review(ownership="own", rating=1, scraped_at="2026-04-24T10:00:00+08:00", product_name=".75 HP"),
        ],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    own_neg = digest["immediate_attention"]["own_new_negative_reviews"]
    assert len(own_neg) == 1, own_neg
    assert own_neg[0]["product_name"] == ".75 HP"
    assert own_neg[0]["review_count"] == 2  # only 2 within window


def test_competitive_opportunities_lists_competitor_new_negatives():
    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-26T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "products": [],
        "reviews": [
            _make_review(ownership="competitor", rating=1,
                         scraped_at="2026-04-26T10:00:00+08:00",
                         product_name="Cabela X", sku="SKU2"),
            _make_review(ownership="competitor", rating=2,
                         scraped_at="2026-04-26T11:00:00+08:00",
                         product_name="Cabela X", sku="SKU2"),
            _make_review(ownership="competitor", rating=4,  # not negative, excluded from new_negative
                         scraped_at="2026-04-26T12:00:00+08:00",
                         product_name="Cabela X", sku="SKU2"),
        ],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    comp_neg = digest["competitive_opportunities"]["competitor_new_negative_reviews"]
    assert len(comp_neg) == 1
    assert comp_neg[0]["product_name"] == "Cabela X"
    assert comp_neg[0]["review_count"] == 2


def test_immediate_attention_excludes_pre_window_negatives():
    """B4 — scraped_at < data_since is rejected even if date_published is recent."""
    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-26T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "products": [],
        "reviews": [
            _make_review(ownership="own", rating=1,
                         scraped_at="2026-04-20T10:00:00+08:00",  # before window
                         date_published="2026-04-26",            # recent publish
                         product_name=".75 HP"),
        ],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    assert digest["immediate_attention"]["own_new_negative_reviews"] == []


def test_immediate_attention_falls_back_when_data_since_absent():
    """When data_since missing (legacy callers), use logical_date - 30d cutoff for `scraped_at`."""
    snapshot = {
        "logical_date": "2026-04-26",
        "products": [],
        "reviews": [
            _make_review(ownership="own", rating=1,
                         scraped_at="2026-04-20T10:00:00+08:00",  # within 30d
                         product_name="A"),
        ],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    own_neg = digest["immediate_attention"]["own_new_negative_reviews"]
    assert len(own_neg) == 1


def test_trend_changes_mirrors_issue_changes_for_now():
    """trend_changes layer wraps issue_changes (will be richer in later tasks).

    F011 §4.2.4 — keys MUST be `*_issues` to match daily_report_v3.html.j2 template.
    """
    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-26T00:00:00+08:00",
        "data_until": "2026-04-27T00:00:00+08:00",
        "products": [],
        "reviews": [],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    assert digest["trend_changes"]["new_issues"] == digest["issue_changes"]["new"]
    assert "escalated_issues" in digest["trend_changes"]
    assert "improving_issues" in digest["trend_changes"]


def test_existing_keys_preserved():
    """Backward compat: existing top-level keys survive the pyramid addition."""
    snapshot = {"logical_date": "2026-04-26", "products": [], "reviews": []}
    digest = build_change_digest(snapshot, _empty_analytics())
    for key in ("summary", "issue_changes", "product_changes", "review_signals",
                "warnings", "view_state", "empty_state", "suppressed_reason"):
        assert key in digest, f"{key} preserved"


def test_immediate_attention_handles_mixed_tz_suffixes():
    """Mixed +08:00 and UTC-Z suffixes must compare correctly across the threshold."""
    snapshot = {
        "logical_date": "2026-04-26",
        "data_since": "2026-04-26T00:00:00+08:00",  # Shanghai midnight = 2026-04-25T16:00:00 UTC
        "data_until": "2026-04-27T00:00:00+08:00",
        "products": [],
        "reviews": [
            # In-window review (Z-suffix UTC → 2026-04-26T08:00:00Z = 16:00 Shanghai → AFTER threshold)
            {
                "id": 1, "ownership": "own", "rating": 1,
                "scraped_at": "2026-04-26T08:00:00Z",
                "date_published": "2026-04-26", "date_published_parsed": "2026-04-26",
                "product_name": "X", "product_sku": "S1",
                "headline": "h", "body": "b",
                "analysis_labels_parsed": [],
            },
            # Out-of-window review (UTC-naive 2026-04-25T05:00:00 → before 16:00 Shanghai threshold)
            {
                "id": 2, "ownership": "own", "rating": 1,
                "scraped_at": "2026-04-25T05:00:00+00:00",
                "date_published": "2026-04-25", "date_published_parsed": "2026-04-25",
                "product_name": "X", "product_sku": "S1",
                "headline": "h", "body": "b",
                "analysis_labels_parsed": [],
            },
        ],
    }
    digest = build_change_digest(snapshot, _empty_analytics())
    own_neg = digest["immediate_attention"]["own_new_negative_reviews"]
    # Only the in-window review counts
    assert len(own_neg) == 1
    assert own_neg[0]["review_count"] == 1
