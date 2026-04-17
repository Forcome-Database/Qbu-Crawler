"""P008 Phase 4: Per-SKU health scorecard for the monthly report.

Each own SKU receives a traffic-light status:
  - green:  risk_score < 15 AND negative_rate < 3% AND no safety incidents
  - yellow: risk_score 15-35 OR negative_rate 3-8%
  - red:    risk_score > 35 OR negative_rate > 8% OR has critical/high safety incident

Trend is derived by comparing this month's risk_score with the previous monthly
report's value (improving / steady / worsening / new).
"""

from __future__ import annotations


_HIGH_SAFETY_LEVELS = ("critical", "high")


def _classify_light(
    risk_score: float,
    negative_rate: float,
    has_high_safety_incident: bool,
) -> str:
    if has_high_safety_incident:
        return "red"
    if risk_score > 35 or negative_rate > 0.08:
        return "red"
    if risk_score >= 15 or negative_rate >= 0.03:
        return "yellow"
    return "green"


def _classify_trend(
    current_score: float,
    previous_score: float | None,
) -> str:
    if previous_score is None:
        return "new"
    delta = current_score - previous_score
    if delta < -3:
        return "improving"
    if delta > 3:
        return "worsening"
    return "steady"


def derive_product_scorecard(
    products: list[dict],
    risk_products: list[dict],
    safety_incidents: list[dict] | None = None,
    previous_scorecards: dict[str, dict] | None = None,
) -> dict:
    """Build per-own-SKU scorecard for the monthly report.

    Args:
        products: cumulative products list (from snapshot.cumulative.products).
        risk_products: output of report_analytics._risk_products().
        safety_incidents: rows from safety_incidents table for the month window.
        previous_scorecards: ``{sku: {"risk_score": float, "light": str}}`` from previous monthly.

    Returns ``{"scorecards": [...], "summary": {...}}``.
    """
    safety_incidents = safety_incidents or []
    previous_scorecards = previous_scorecards or {}

    high_safety_skus = {
        s.get("product_sku")
        for s in safety_incidents
        if s.get("safety_level") in _HIGH_SAFETY_LEVELS
    }
    risk_by_sku = {r.get("sku"): r for r in risk_products}

    scorecards = []
    for p in products:
        if p.get("ownership") != "own":
            continue
        sku = p.get("sku")
        risk = risk_by_sku.get(sku, {})
        risk_score = float(risk.get("risk_score") or 0)
        negative_rate = float(risk.get("negative_rate") or 0)
        has_safety = sku in high_safety_skus
        light = _classify_light(risk_score, negative_rate, has_safety)

        prev = previous_scorecards.get(sku) or {}
        trend = _classify_trend(risk_score, prev.get("risk_score"))

        scorecards.append({
            "sku": sku,
            "name": p.get("name"),
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "risk_score": round(risk_score, 1),
            "negative_rate": round(negative_rate, 4),
            "negative_count": risk.get("negative_count", 0),
            "light": light,
            "safety_flag": has_safety,
            "trend": trend,
            "previous_risk_score": prev.get("risk_score"),
            "previous_light": prev.get("light"),
        })

    summary = {
        "green": sum(1 for s in scorecards if s["light"] == "green"),
        "yellow": sum(1 for s in scorecards if s["light"] == "yellow"),
        "red": sum(1 for s in scorecards if s["light"] == "red"),
        "total": len(scorecards),
        "with_safety_flag": sum(1 for s in scorecards if s["safety_flag"]),
    }

    return {"scorecards": scorecards, "summary": summary}
