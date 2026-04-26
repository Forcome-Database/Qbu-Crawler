"""F011 H11 — METRIC_TOOLTIPS 风险分 sync with 5-factor algorithm."""

from qbu_crawler.server.report_common import METRIC_TOOLTIPS, _resolve_tooltip


def test_risk_score_tooltip_template_mentions_5_factor():
    """F011 H11 — raw template must declare 5-factor weighting."""
    template = METRIC_TOOLTIPS["风险分"]
    assert "5 因子" in template or "5因子" in template
    assert "差评率" in template and "35%" in template
    assert "{low_rating}" in template  # placeholder preserved
    assert "{high_risk}" in template
    # legacy formula must be gone
    assert "×2" not in template
    assert "×1" not in template


def test_risk_score_tooltip_resolves_with_low_rating_and_high_risk():
    """Resolved text replaces placeholders with runtime values."""
    resolved = _resolve_tooltip("风险分")
    # `low_rating` substitution: text should contain a star number, not literal {low_rating}
    assert "{low_rating}" not in resolved
    assert "{high_risk}" not in resolved
    assert "≤" in resolved and "星" in resolved
    assert "高风险" in resolved
