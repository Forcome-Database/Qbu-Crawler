"""F011 §4.2.3.1 v1.3 — issue cards Top 3 默认展开 + 删除 temporal_pattern.

Covers AC-35:
  1. issue_cards sorted by (evidence_count DESC, severity_rank DESC,
     affected_product_count DESC).
  2. First 3 cards have ``default_expanded=True``; rest have False.
  3. HTML renders all cards inline; Top 3 expanded, 4-N carry ``card-collapsed``
     class so only the header is visible (click header to expand).
  4. ``temporal_pattern`` no longer appears in rendered HTML.
  5. LLM prompt + parser for ``analyze_cluster_deep`` no longer requests/emits
     ``temporal_pattern``.
"""
from __future__ import annotations

import re

from qbu_crawler.server.report_common import normalize_deep_report_analytics
from qbu_crawler.server.report_html import render_attachment_html


# ──────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────
def _base_snapshot(*, reviews=None, products=None,
                   logical_date="2026-04-27", run_id=0):
    return {
        "logical_date": logical_date,
        "run_id": run_id,
        "snapshot_at": f"{logical_date}T12:00:00+08:00",
        "data_since": f"{logical_date}T00:00:00+08:00",
        "data_until": f"{logical_date}T23:59:59+08:00",
        "products": products or [],
        "reviews": reviews or [],
    }


def _base_kpis():
    return {
        "health_index": 80,
        "ingested_review_rows": 0,
        "own_review_rows": 0,
        "competitor_review_rows": 0,
        "own_product_count": 0,
        "competitor_product_count": 0,
        "own_negative_review_rows": 0,
        "negative_review_rows": 0,
        "low_rating_review_rows": 0,
    }


def _make_cluster(*, label_code, review_count, severity, affected_product_count,
                   first_seen="2024-03-15", last_seen="2024-08-22"):
    return {
        "label_code": label_code,
        "label_display": label_code,
        "feature_display": label_code,
        "review_count": review_count,
        "severity": severity,
        "severity_display": {"high": "高", "medium": "中", "low": "低"}.get(severity, ""),
        "affected_product_count": affected_product_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "review_dates": [first_seen, last_seen],
        "example_reviews": [],
        "image_review_count": 0,
        "translated_rate": 1.0,
    }


def _analytics_with_clusters(clusters):
    return {
        "report_semantics": "incremental",
        "mode": "incremental",
        "kpis": _base_kpis(),
        "self": {
            "risk_products": [],
            "product_status": [],
            "top_negative_clusters": clusters,
            "top_positive_clusters": [],
            "recommendations": [],
        },
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [],
        },
        "appendix": {"image_reviews": [], "coverage": {}},
        "change_digest": {},
        "report_copy": {
            "improvement_priorities": [],
            "executive_bullets": [],
        },
    }


def _eight_card_analytics():
    """Build an analytics payload with 8 mixed clusters to exercise sort + fold."""
    clusters = [
        _make_cluster(label_code="c_low_2",  review_count=2,  severity="low",    affected_product_count=1),
        _make_cluster(label_code="c_high_30", review_count=30, severity="high",   affected_product_count=4),
        _make_cluster(label_code="c_med_10",  review_count=10, severity="medium", affected_product_count=2),
        _make_cluster(label_code="c_high_15", review_count=15, severity="high",   affected_product_count=5),
        _make_cluster(label_code="c_med_15",  review_count=15, severity="medium", affected_product_count=2),
        _make_cluster(label_code="c_low_15",  review_count=15, severity="low",    affected_product_count=1),
        _make_cluster(label_code="c_high_8",  review_count=8,  severity="high",   affected_product_count=3),
        _make_cluster(label_code="c_med_5",   review_count=5,  severity="medium", affected_product_count=1),
    ]
    return normalize_deep_report_analytics(_analytics_with_clusters(clusters))


# ──────────────────────────────────────────────────────────
# AC-35 (1) — sort order
# ──────────────────────────────────────────────────────────
def test_issue_cards_sorted_by_evidence_severity():
    """Primary: evidence_count DESC. Secondary: severity_rank DESC. Tertiary: affected_product_count DESC."""
    analytics = _eight_card_analytics()
    cards = analytics["issue_cards"]
    assert len(cards) == 8

    # Validate the expected order:
    # 1. c_high_30  (rc=30, h, 4)
    # 2. c_high_15  (rc=15, h, 5)   — rc tied with c_med_15/c_low_15, severity=high wins
    # 3. c_med_15   (rc=15, m, 2)   — rc=15, severity=medium beats low
    # 4. c_low_15   (rc=15, l, 1)
    # 5. c_med_10   (rc=10, m, 2)
    # 6. c_high_8   (rc=8,  h, 3)
    # 7. c_med_5    (rc=5,  m, 1)
    # 8. c_low_2    (rc=2,  l, 1)
    expected_order = [
        "c_high_30", "c_high_15", "c_med_15", "c_low_15",
        "c_med_10", "c_high_8", "c_med_5", "c_low_2",
    ]
    actual_order = [c.get("label_display") for c in cards]
    assert actual_order == expected_order


# ──────────────────────────────────────────────────────────
# AC-35 (2) — default_expanded marker
# ──────────────────────────────────────────────────────────
def test_issue_cards_top_3_marked_default_expanded():
    """First 3 cards should have default_expanded=True; rest False."""
    analytics = _eight_card_analytics()
    cards = analytics["issue_cards"]
    assert len(cards) == 8
    for i, c in enumerate(cards):
        assert c.get("default_expanded") is (i < 3), (
            f"card {i} ({c.get('label_display')}) has default_expanded={c.get('default_expanded')}, expected {i < 3}"
        )


def test_issue_cards_evidence_count_field_present():
    """spec consistency — each card carries evidence_count mirroring review_count."""
    analytics = _eight_card_analytics()
    for c in analytics["issue_cards"]:
        assert "evidence_count" in c
        assert c["evidence_count"] == c["review_count"]


# ──────────────────────────────────────────────────────────
# AC-35 (3) — HTML rendering: Top 3 expanded, 4-N inline with card-collapsed
# ──────────────────────────────────────────────────────────
def test_html_top_3_expanded_rest_folded():
    """All 8 issue-card divs render inline; only 4-N carry ``card-collapsed`` class."""
    analytics = _eight_card_analytics()
    html = render_attachment_html(_base_snapshot(), analytics)

    # Old <details class="issue-cards-folded"> wrapper must NOT exist
    assert 'class="issue-cards-folded"' not in html, (
        "Folded <details> wrapper should be removed in v1.3 — cards now render inline"
    )

    # All 8 cards visible at section level
    total_card_count = len(re.findall(r'class="issue-card severity-', html))
    assert total_card_count == 8, f"Expected 8 issue cards inline, got {total_card_count}"

    # 5 cards collapsed (4-N), 3 cards expanded (Top 3)
    collapsed_count = len(re.findall(r'class="issue-card severity-\w+ card-collapsed', html))
    assert collapsed_count == 5, f"Expected 5 collapsed cards, got {collapsed_count}"
    expanded_count = total_card_count - collapsed_count
    assert expanded_count == 3, f"Expected 3 expanded cards, got {expanded_count}"


def test_html_no_folded_details_summary():
    """v1.3 — old '展开剩余 N 张诊断卡' summary text must be gone."""
    analytics = _eight_card_analytics()
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "展开剩余" not in html
    assert 'class="issue-cards-folded"' not in html


def test_html_no_data_default_collapsed_attribute():
    """Old soft-collapse marker must be gone (replaced by <details> wrapper)."""
    analytics = _eight_card_analytics()
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "data-default-collapsed" not in html


# ──────────────────────────────────────────────────────────
# AC-35 (4) — temporal_pattern removed from rendered HTML
# ──────────────────────────────────────────────────────────
def test_temporal_pattern_removed_from_html():
    analytics = _eight_card_analytics()
    html = render_attachment_html(_base_snapshot(), analytics)
    assert "temporal_pattern" not in html


# ──────────────────────────────────────────────────────────
# AC-35 (5) — LLM prompt + parser drop temporal_pattern
# ──────────────────────────────────────────────────────────
def test_llm_prompt_no_longer_requests_temporal_pattern(monkeypatch):
    """analyze_cluster_deep prompt no longer mentions temporal_pattern.

    Patch OpenAI client to capture the prompt without making a network call.
    """
    from qbu_crawler import config
    from qbu_crawler.server import report_llm

    monkeypatch.setattr(config, "LLM_API_BASE", "http://fake")
    monkeypatch.setattr(config, "LLM_API_KEY", "fake")
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", True)

    captured = {}

    class _FakeChoice:
        def __init__(self):
            self.message = type("M", (), {"content": '{"failure_modes":[],"root_causes":[],"actionable_summary":"x"}'})()

    class _FakeResponse:
        def __init__(self):
            self.choices = [_FakeChoice()]

    class _FakeChat:
        class completions:
            @staticmethod
            def create(model, messages, temperature):
                captured["prompt"] = messages[0]["content"]
                return _FakeResponse()

    class _FakeClient:
        def __init__(self, *a, **kw):
            self.chat = _FakeChat()

    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeClient)

    cluster = {"label_code": "quality_stability", "label_display": "质量稳定性", "review_count": 10}
    reviews = [{"rating": 1, "product_name": "P1", "date_published_parsed": "2026-01-01",
                 "body": "broken"}]
    report_llm.analyze_cluster_deep(cluster, reviews)

    assert "prompt" in captured, "Prompt was never captured"
    assert "temporal_pattern" not in captured["prompt"], (
        "Prompt should no longer request temporal_pattern"
    )


def test_validate_cluster_analysis_drops_temporal_pattern():
    """_validate_cluster_analysis no longer emits temporal_pattern field."""
    from qbu_crawler.server.report_llm import _validate_cluster_analysis

    raw = {
        "failure_modes": [{"mode": "x"}],
        "root_causes": [],
        "user_workarounds": [],
        "actionable_summary": "summary",
        # Even if upstream LLM returns this, parser must not propagate it.
        "temporal_pattern": "stable trend",
    }
    result = _validate_cluster_analysis(raw)
    assert result is not None
    assert "temporal_pattern" not in result
