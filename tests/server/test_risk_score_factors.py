from qbu_crawler.server.report_analytics import (
    compute_risk_score, is_near_high_risk,
    RISK_WEIGHTS, HIGH_RISK_THRESHOLD,
)


def test_risk_score_factors_breakdown():
    """F011 H11 — risk_score must output 5-factor breakdown."""
    product = {
        "sku": "TEST",
        "ingested_count": 109,
        "review_count": 109,
        "negative_review_count": 9,
        "high_severity_count": 7,
        "image_evidence_count": 3,
        "recent_negative_count": 2,
        "total_volume": 109,
    }
    result = compute_risk_score(product)

    assert "risk_factors" in result
    factors = result["risk_factors"]
    for key in ("neg_rate", "severity", "evidence", "recency", "volume"):
        assert key in factors, f"missing factor {key}"
        assert "raw" in factors[key]
        assert "weight" in factors[key]
        assert "weighted" in factors[key]
    total_weight = sum(f["weight"] for f in factors.values())
    assert abs(total_weight - 1.0) < 0.001


def test_near_high_risk_flag():
    """F011 H18 — near-high-risk band: [0.85*threshold, threshold)"""
    score_near = 32.6
    assert is_near_high_risk(score_near, threshold=35) is True
    score_low = 25.0
    assert is_near_high_risk(score_low, threshold=35) is False
    score_high = 40.0
    assert is_near_high_risk(score_high, threshold=35) is False


def test_risk_score_value_matches_weighted_sum():
    """risk_score = sum(raw * weight) * 100, rounded to 1 dp."""
    product = {
        "ingested_count": 100,
        "review_count": 100,
        "negative_review_count": 10,
        "high_severity_count": 5,
        "image_evidence_count": 2,
        "recent_negative_count": 4,
        "total_volume": 50,
    }
    result = compute_risk_score(product)
    expected_raw = (
        (10/100) * 0.35
        + (5/10) * 0.25
        + (2/10) * 0.15
        + (4/10) * 0.15
        + min(50/100, 1.0) * 0.10
    )
    assert abs(result["risk_score"] - round(expected_raw * 100, 1)) < 0.05


def test_compute_risk_score_zero_ingested_returns_none_breakdown():
    product = {"ingested_count": 0, "review_count": 100, "negative_review_count": 0}
    result = compute_risk_score(product)
    assert result["risk_score"] is None
    assert result["risk_factors"] is None
    assert result["near_high_risk"] is False
    # Task 2.1 backward compat — these keys must still be present
    assert result["neg_rate"] is None
    assert result["coverage"] is None
    assert result["low_coverage_warning"] is True


def test_compute_risk_score_minimal_input_defaults_missing_fields_to_zero():
    """Callers that supply only Task 2.1 fields (ingested + neg) must not crash."""
    product = {
        "ingested_count": 50,
        "review_count": 50,
        "negative_review_count": 5,
    }
    result = compute_risk_score(product)
    # severity / evidence / recency default to 0 → only neg_rate and volume contribute
    assert result["risk_score"] is not None
    assert result["risk_factors"]["severity"]["raw"] == 0.0
    assert result["risk_factors"]["evidence"]["raw"] == 0.0
    assert result["risk_factors"]["recency"]["raw"] == 0.0
    # Task 2.1 backward compat
    assert abs(result["neg_rate"] - 0.10) < 0.001


def test_volume_factor_clipped_at_one():
    product = {
        "ingested_count": 100, "review_count": 100,
        "negative_review_count": 10,
        "total_volume": 500,  # 500/100 = 5 → clip to 1.0
    }
    result = compute_risk_score(product)
    assert result["risk_factors"]["volume"]["raw"] == 1.0


def test_high_risk_threshold_default():
    """HIGH_RISK_THRESHOLD constant exposed for callers."""
    assert HIGH_RISK_THRESHOLD == 35.0
    assert RISK_WEIGHTS == {
        "neg_rate": 0.35, "severity": 0.25,
        "evidence": 0.15, "recency": 0.15, "volume": 0.10,
    }
