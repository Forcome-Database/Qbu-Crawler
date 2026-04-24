"""Tests for bootstrap and incremental email mode semantics."""

from qbu_crawler.server.report_snapshot import _render_full_email_html


def _render_full_email(*, report_semantics, change_digest):
    return _render_full_email_html(
        {
            "run_id": 0,
            "logical_date": "2026-04-16",
            "snapshot_at": "2026-04-16T15:00:00+08:00",
            "products_count": 1,
            "reviews_count": 0,
            "translated_count": 0,
            "untranslated_count": 0,
            "reviews": [],
            "products": [
                {"sku": "S1", "name": "P1", "price": 199.0, "stock_status": "in_stock", "rating": 4.2},
            ],
        },
        {
            "mode": "baseline" if report_semantics == "bootstrap" else "incremental",
            "report_semantics": report_semantics,
            "kpis": {
                "health_index": 80,
                "own_review_rows": 100,
                "high_risk_count": 0,
                "own_product_count": 1,
                "competitor_product_count": 0,
                "translated_count": 0,
                "untranslated_count": 0,
            },
            "change_digest": change_digest,
            "report_copy": {"hero_headline": "", "executive_bullets": []},
            "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
            "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        },
    )


def test_bootstrap_email_shows_monitoring_start_not_empty_state():
    html = _render_full_email(
        report_semantics="bootstrap",
        change_digest={
            "enabled": True,
            "view_state": "bootstrap",
            "summary": {
                "ingested_review_count": 6,
                "fresh_review_count": 2,
                "historical_backfill_count": 4,
                "fresh_own_negative_count": 1,
                "issue_new_count": 0,
                "issue_escalated_count": 0,
                "issue_improving_count": 0,
                "state_change_count": 0,
            },
            "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
            "product_changes": {"price_changes": [], "stock_changes": [], "rating_changes": [], "new_products": [], "removed_products": []},
            "review_signals": {"fresh_negative_reviews": [], "fresh_competitor_positive_reviews": []},
            "warnings": {
                "translation_incomplete": {"enabled": False, "message": ""},
                "estimated_dates": {"enabled": False, "message": ""},
                "backfill_dominant": {"enabled": False, "message": ""},
            },
            "empty_state": {"enabled": False, "title": "", "description": ""},
        },
    )

    assert "Monitoring Start" in html
    assert "No significant changes" not in html


def test_incremental_email_renders_explicit_empty_state():
    html = _render_full_email(
        report_semantics="incremental",
        change_digest={
            "enabled": True,
            "view_state": "empty",
            "summary": {
                "ingested_review_count": 1,
                "fresh_review_count": 0,
                "historical_backfill_count": 1,
                "fresh_own_negative_count": 0,
                "issue_new_count": 0,
                "issue_escalated_count": 0,
                "issue_improving_count": 0,
                "state_change_count": 0,
            },
            "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
            "product_changes": {"price_changes": [], "stock_changes": [], "rating_changes": [], "new_products": [], "removed_products": []},
            "review_signals": {"fresh_negative_reviews": [], "fresh_competitor_positive_reviews": []},
            "warnings": {
                "translation_incomplete": {"enabled": False, "message": ""},
                "estimated_dates": {"enabled": False, "message": ""},
                "backfill_dominant": {"enabled": False, "message": ""},
            },
            "empty_state": {
                "enabled": True,
                "title": "No significant changes",
                "description": "Window is stable.",
            },
        },
    )

    assert "No significant changes" in html
    assert "Monitoring Start" not in html


def test_active_email_renders_competitor_positive_review_signal():
    html = _render_full_email(
        report_semantics="incremental",
        change_digest={
            "enabled": True,
            "view_state": "active",
            "summary": {
                "ingested_review_count": 2,
                "fresh_review_count": 2,
                "historical_backfill_count": 0,
                "fresh_own_negative_count": 0,
                "issue_new_count": 0,
                "issue_escalated_count": 0,
                "issue_improving_count": 0,
                "state_change_count": 0,
            },
            "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
            "product_changes": {"price_changes": [], "stock_changes": [], "rating_changes": [], "new_products": [], "removed_products": []},
            "review_signals": {
                "fresh_negative_reviews": [],
                "fresh_competitor_positive_reviews": [
                    {
                        "product_name": "Competitor Pro",
                        "headline_display": "Worth every penny",
                        "body_display": "Quiet, stable, and easy to clean.",
                    }
                ],
            },
            "warnings": {
                "translation_incomplete": {"enabled": False, "message": ""},
                "estimated_dates": {"enabled": False, "message": ""},
                "backfill_dominant": {"enabled": False, "message": ""},
            },
            "empty_state": {"enabled": False, "title": "", "description": ""},
        },
    )

    assert "Competitor Pro" in html
    assert "Worth every penny" in html
