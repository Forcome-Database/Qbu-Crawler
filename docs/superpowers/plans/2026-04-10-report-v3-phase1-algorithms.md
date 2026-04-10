# Report V3 Phase 1 — Algorithm Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all 5 core report metrics (health index, risk score, gap analysis, severity, alert level) with V3 algorithms, and add supporting DB/config changes.

**Architecture:** Pure backend changes — no template or LLM modifications. Each algorithm is independently testable. Existing tests must still pass after each task (except for tests that assert old metric values, which are updated in-place).

**Tech Stack:** Python 3.10+, pytest, SQLite

**Spec Reference:** `docs/superpowers/specs/2026-04-10-report-v3-redesign.md` — Sections 6.1–6.5, 14.1–14.7

**Baseline:** 401 tests passing (1 pre-existing failure in `test_report_charts.py::test_sentiment_chart_uses_rating_title`, excluded from scope).

**Test command:** `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/config.py` | Modify | Threshold recalibration |
| `qbu_crawler/models.py` | Modify | `report_mode` column, `query_cluster_reviews()` |
| `qbu_crawler/server/report_analytics.py` | Modify | `_SEVERITY_SCORE` update, `_risk_products` → V3, `compute_cluster_severity()` new, `_uncategorized` filter, own positive clusters |
| `qbu_crawler/server/report_common.py` | Modify | `compute_health_index` → V3, `_competitor_gap_analysis` → V3, `_compute_alert_level` → V3, `_SEVERITY_DISPLAY`/`_PRIORITY_DISPLAY` update, `_compute_kpi_deltas` expansion, KPI cards rebuild, `normalize_deep_report_analytics` updates |
| `tests/test_report_common.py` | Modify | Update tests for V3 health index, gap analysis, alert level, KPI cards |
| `tests/test_report_analytics.py` | Modify | Update tests for V3 risk score, cluster severity |
| `tests/test_v3_algorithms.py` | Create | New comprehensive test file for V3 metric algorithms |

---

### Task 1: Add "critical" severity level to lookup dicts

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:263`
- Modify: `qbu_crawler/server/report_common.py:31-32`
- Test: `tests/test_v3_algorithms.py` (create)

- [ ] **Step 1: Create test file with severity dict tests**

```python
# tests/test_v3_algorithms.py
"""Tests for Report V3 algorithm redesign (Phase 1)."""

from qbu_crawler.server.report_analytics import _SEVERITY_SCORE
from qbu_crawler.server.report_common import _SEVERITY_DISPLAY, _PRIORITY_DISPLAY


class TestSeverityDicts:
    def test_severity_score_has_critical(self):
        assert "critical" in _SEVERITY_SCORE
        assert _SEVERITY_SCORE["critical"] > _SEVERITY_SCORE["high"]

    def test_severity_display_has_critical(self):
        assert "critical" in _SEVERITY_DISPLAY
        assert _SEVERITY_DISPLAY["critical"] == "危急"

    def test_priority_display_has_critical(self):
        assert "critical" in _PRIORITY_DISPLAY

    def test_severity_score_ordering(self):
        assert _SEVERITY_SCORE["critical"] > _SEVERITY_SCORE["high"] > _SEVERITY_SCORE["medium"] > _SEVERITY_SCORE["low"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_v3_algorithms.py::TestSeverityDicts -v`
Expected: FAIL — `"critical" not in _SEVERITY_SCORE`

- [ ] **Step 3: Update severity dicts**

In `qbu_crawler/server/report_analytics.py:263`, change:
```python
_SEVERITY_SCORE = {"high": 3, "medium": 2, "low": 1}
```
to:
```python
_SEVERITY_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1}
```

In `qbu_crawler/server/report_common.py:31`, change:
```python
_PRIORITY_DISPLAY = {"high": "高", "medium": "中", "low": "低"}
_SEVERITY_DISPLAY = {"high": "高", "medium": "中", "low": "低"}
```
to:
```python
_PRIORITY_DISPLAY = {"critical": "危急", "high": "高", "medium": "中", "low": "低"}
_SEVERITY_DISPLAY = {"critical": "危急", "high": "高", "medium": "中", "low": "低"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_v3_algorithms.py::TestSeverityDicts -v`
Expected: 4 passed

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: 401+ passed

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_v3_algorithms.py
git commit -m "feat(report): add 'critical' severity level to lookup dicts"
```

---

### Task 2: Replace health index with NPS-proxy formula

**Files:**
- Modify: `qbu_crawler/server/report_common.py:433-463` (`compute_health_index`)
- Modify: `qbu_crawler/config.py:160-161` (threshold recalibration)
- Test: `tests/test_v3_algorithms.py` (append)
- Modify: `tests/test_report_common.py` (update any existing health index assertions)

**Spec ref:** Section 6.1.2, 11.1

- [ ] **Step 1: Write NPS-proxy tests**

Append to `tests/test_v3_algorithms.py`:

```python
from qbu_crawler.server.report_common import compute_health_index


class TestHealthIndexV3:
    """NPS-proxy: (promoters - detractors) / total * 100, mapped to 0-100."""

    def test_balanced_reviews(self):
        """76 promoters, 55 detractors, 141 total → NPS=14.9, health=57.4"""
        kpis = {
            "own_review_rows": 141,
            "own_positive_review_rows": 76,
            "own_negative_review_rows": 55,
        }
        result = compute_health_index({"kpis": kpis})
        assert 57.0 <= result <= 58.0

    def test_zero_own_reviews_returns_neutral(self):
        kpis = {"own_review_rows": 0, "own_positive_review_rows": 0, "own_negative_review_rows": 0}
        assert compute_health_index({"kpis": kpis}) == 50.0

    def test_all_promoters(self):
        kpis = {"own_review_rows": 10, "own_positive_review_rows": 10, "own_negative_review_rows": 0}
        assert compute_health_index({"kpis": kpis}) == 100.0

    def test_all_detractors(self):
        kpis = {"own_review_rows": 10, "own_positive_review_rows": 0, "own_negative_review_rows": 10}
        assert compute_health_index({"kpis": kpis}) == 0.0

    def test_clamped_to_0_100(self):
        kpis = {"own_review_rows": 5, "own_positive_review_rows": 0, "own_negative_review_rows": 5}
        result = compute_health_index({"kpis": kpis})
        assert 0 <= result <= 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_v3_algorithms.py::TestHealthIndexV3 -v`
Expected: FAIL — old formula produces different values

- [ ] **Step 3: Replace compute_health_index implementation**

In `qbu_crawler/server/report_common.py`, replace the `compute_health_index` function (lines 433-463) with:

```python
def compute_health_index(analytics: dict) -> float:
    """NPS-proxy health index.

    Maps Net Promoter Score (-100..+100) to a 0..100 scale:
        promoters (rating >= 4) minus detractors (rating <= NEGATIVE_THRESHOLD),
        divided by total own reviews, times 100, then linearly mapped.

    Industry benchmarks for consumer products:
        > 75 excellent, 60-75 good, 50-60 needs attention, < 50 critical.
    """
    kpis = analytics.get("kpis", {}) if isinstance(analytics, dict) else {}
    own_reviews = kpis.get("own_review_rows", 0)
    if own_reviews == 0:
        return 50.0  # No data → neutral sentinel

    promoters = kpis.get("own_positive_review_rows", 0)
    detractors = kpis.get("own_negative_review_rows", 0)

    nps = ((promoters - detractors) / own_reviews) * 100
    health = (nps + 100) / 2

    return round(max(0.0, min(100.0, health)), 1)
```

- [ ] **Step 4: Update config thresholds**

In `qbu_crawler/config.py`, change:
```python
HEALTH_RED = int(os.getenv("REPORT_HEALTH_RED", "60"))
HEALTH_YELLOW = int(os.getenv("REPORT_HEALTH_YELLOW", "80"))
```
to:
```python
HEALTH_RED = int(os.getenv("REPORT_HEALTH_RED", "45"))
HEALTH_YELLOW = int(os.getenv("REPORT_HEALTH_YELLOW", "60"))
```

- [ ] **Step 5: Fix any existing tests that assert old health index values**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py 2>&1 | head -20`

For each failure in `tests/test_report_common.py` or `tests/test_report_analytics.py` that checks a specific health index value, update the expected value to match the NPS-proxy formula. The test data fixtures produce known inputs — recalculate expected health for each.

Also update `tests/test_config_thresholds.py` if it asserts `HEALTH_RED == 60` or `HEALTH_YELLOW == 80`.

- [ ] **Step 6: Run full suite**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/config.py tests/test_v3_algorithms.py tests/test_report_common.py tests/test_config_thresholds.py
git commit -m "feat(report): replace health index with NPS-proxy formula

NPS = (promoters - detractors) / total * 100, mapped to 0-100.
Thresholds: HEALTH_RED 60→45, HEALTH_YELLOW 80→60."
```

---

### Task 3: Replace risk score with multi-factor algorithm

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:650-739` (`_risk_products`)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 6.2.2, 14.7

- [ ] **Step 1: Write multi-factor risk score tests**

Append to `tests/test_v3_algorithms.py`:

```python
from qbu_crawler.server.report_analytics import _risk_products


class TestRiskScoreV3:
    """Multi-factor: neg_rate(35%) + severity(25%) + evidence(15%) + recency(15%) + volume(10%)."""

    @staticmethod
    def _make_review(rating, labels=None, images=None, date_parsed="2026-03-01",
                     ownership="own", product_name="Prod", product_sku="SKU1"):
        return {
            "review": {
                "rating": rating,
                "ownership": ownership,
                "product_name": product_name,
                "product_sku": product_sku,
                "date_published_parsed": date_parsed,
                "images": images,
                "headline": "", "body": "",
            },
            "labels": labels or [],
            "images": images or [],
        }

    @staticmethod
    def _make_label(code="quality_stability", polarity="negative", severity="high"):
        return {"label_code": code, "label_polarity": polarity, "severity": severity}

    def test_zero_reviews_returns_empty(self):
        result = _risk_products([], snapshot_products=[])
        assert result == []

    def test_all_positive_reviews_returns_zero_risk(self):
        items = [self._make_review(5, [self._make_label(polarity="positive")]) for _ in range(10)]
        products = [{"sku": "SKU1", "review_count": 10, "rating": 4.5}]
        result = _risk_products(items, snapshot_products=products)
        # No negative reviews → no products in risk list (only own negatives counted)
        assert len(result) == 0 or all(p["risk_score"] == 0 for p in result)

    def test_high_neg_rate_higher_score(self):
        """Product with 80% neg rate should score higher than 20% neg rate."""
        # 8 of 10 negative
        high_neg = (
            [self._make_review(1, [self._make_label()]) for _ in range(8)]
            + [self._make_review(5) for _ in range(2)]
        )
        # 2 of 10 negative
        low_neg = (
            [self._make_review(1, [self._make_label()], product_sku="SKU2", product_name="Prod2") for _ in range(2)]
            + [self._make_review(5, product_sku="SKU2", product_name="Prod2") for _ in range(8)]
        )
        products = [
            {"sku": "SKU1", "review_count": 10, "rating": 2.0},
            {"sku": "SKU2", "review_count": 10, "rating": 4.0},
        ]
        result = _risk_products(high_neg + low_neg, snapshot_products=products)
        scores = {p["product_sku"]: p["risk_score"] for p in result}
        assert scores.get("SKU1", 0) > scores.get("SKU2", 0)
```

- [ ] **Step 2: Run to verify tests fail with current implementation**

Run: `uv run pytest tests/test_v3_algorithms.py::TestRiskScoreV3 -v`
Expected: Some tests may pass, some may fail depending on current algorithm behavior

- [ ] **Step 3: Rewrite `_risk_products` with V3 multi-factor algorithm**

In `qbu_crawler/server/report_analytics.py`, replace `_risk_products` (lines 650-739) with the V3 algorithm from spec Section 6.2.2. Key changes:

1. Remove the `rating > config.LOW_RATING_THRESHOLD` gate — count ALL own reviews for the product, use `config.NEGATIVE_THRESHOLD` for negative classification
2. Remove the `if not negative_labels: continue` skip — 1-star reviews without labels still contribute
3. Replace raw score accumulation with 5-factor formula (neg_rate, severity_avg, evidence_rate, recency, volume_sig)
4. Add `logical_date` parameter (obtain from `snapshot.get("logical_date")` in the caller)
5. Early return `risk_score = 0.0` when `neg_count == 0`

The function signature changes to:
```python
def _risk_products(labeled_reviews, snapshot_products=None, logical_date=None):
```

Update the caller `build_report_analytics()` (line ~1230) to pass `logical_date`:
```python
risk_products = _risk_products(labeled_reviews, snapshot.get("products"), logical_date=snapshot.get("logical_date"))
```

- [ ] **Step 4: Run V3 risk tests**

Run: `uv run pytest tests/test_v3_algorithms.py::TestRiskScoreV3 -v`
Expected: All pass

- [ ] **Step 5: Fix existing tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`

Fix any tests in `test_report_analytics.py` that assert specific risk_score values — recalculate with the new formula.

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_v3_algorithms.py tests/test_report_analytics.py
git commit -m "feat(report): replace risk score with multi-factor algorithm

5 factors: neg_rate(35%), severity(25%), evidence(15%), recency(15%), volume(10%).
Removes LOW_RATING_THRESHOLD gate and label-required filter."
```

---

### Task 4: Add cluster-level computed severity

**Files:**
- Create function in: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_analytics.py` (call site in `_build_feature_clusters` or `build_report_analytics`)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 6.4.2

- [ ] **Step 1: Write cluster severity tests**

Append to `tests/test_v3_algorithms.py`:

```python
from datetime import date, timedelta
from qbu_crawler.server.report_analytics import compute_cluster_severity


class TestClusterSeverity:
    """4-factor: volume + breadth + recency + safety signal."""

    def test_critical_high_volume_safety(self):
        """36 reviews, 3 products, safety keywords → critical."""
        cluster = {
            "review_count": 36,
            "affected_product_count": 3,
            "review_dates": ["2026-01-01"] * 34 + ["2026-03-20", "2026-04-01"],
        }
        reviews = [{"headline": "metal shavings dangerous", "body": "rust everywhere"}]
        result = compute_cluster_severity(cluster, reviews, date(2026, 4, 10))
        assert result == "critical"

    def test_high_moderate_volume_safety(self):
        """14 reviews, 2 products, safety → high."""
        cluster = {
            "review_count": 14,
            "affected_product_count": 2,
            "review_dates": ["2025-01-01"] * 14,
        }
        reviews = [{"headline": "metal debris", "body": ""}]
        result = compute_cluster_severity(cluster, reviews, date(2026, 4, 10))
        assert result == "high"

    def test_medium_moderate_volume_no_safety(self):
        """12 reviews, 3 products, no safety → medium."""
        cluster = {
            "review_count": 12,
            "affected_product_count": 3,
            "review_dates": ["2025-01-01"] * 12,
        }
        reviews = [{"headline": "design flaw", "body": "poor quality"}]
        result = compute_cluster_severity(cluster, reviews, date(2026, 4, 10))
        assert result == "medium"

    def test_low_few_reviews(self):
        """4 reviews, 2 products, no safety → low."""
        cluster = {
            "review_count": 4,
            "affected_product_count": 2,
            "review_dates": ["2025-06-01"] * 4,
        }
        reviews = [{"headline": "missing parts", "body": ""}]
        result = compute_cluster_severity(cluster, reviews, date(2026, 4, 10))
        assert result == "low"

    def test_recency_boosts_score(self):
        """Same cluster but with many recent reviews → higher severity."""
        base = {
            "review_count": 8,
            "affected_product_count": 2,
            "review_dates": ["2026-03-01"] * 8,  # all within 90 days
        }
        reviews = [{"headline": "problem", "body": ""}]
        result = compute_cluster_severity(base, reviews, date(2026, 4, 10))
        # 8 reviews (score 1) + 2 products (score 1) + recency 100% (score 2) = 4 → medium
        assert result in ("medium", "high")

    def test_empty_reviews_returns_low(self):
        cluster = {"review_count": 0, "affected_product_count": 0, "review_dates": []}
        result = compute_cluster_severity(cluster, [], date(2026, 4, 10))
        assert result == "low"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_v3_algorithms.py::TestClusterSeverity -v`
Expected: FAIL — `compute_cluster_severity` not defined

- [ ] **Step 3: Implement compute_cluster_severity**

Add to `qbu_crawler/server/report_analytics.py` (after `_SEVERITY_SCORE` dict, before `classify_review_labels`):

```python
_SAFETY_KEYWORDS = frozenset({
    "metal shaving", "metal debris", "metal flake", "metal particle",
    "broke", "broken", "snapped", "shattered", "exploded",
    "dangerous", "hazard", "injury", "hurt", "unsafe",
    "rust", "rusted", "corrosion",
    "金属屑", "金属碎", "断裂", "爆裂", "危险", "安全隐患", "锈",
})


def compute_cluster_severity(cluster, reviews_in_cluster, logical_date):
    """Compute severity at cluster level from volume, breadth, recency, safety.

    Returns one of: "critical", "high", "medium", "low".
    """
    from datetime import datetime, timedelta

    review_count = cluster.get("review_count", 0)
    affected_products = cluster.get("affected_product_count", 0)

    # Recency: count reviews from last 90 days
    recent_cutoff = logical_date - timedelta(days=90)
    recent_count = 0
    for d in cluster.get("review_dates", []):
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() >= recent_cutoff:
                recent_count += 1
        except (ValueError, TypeError):
            pass
    recency_rate = recent_count / max(review_count, 1)

    # Safety signal
    has_safety = False
    for r in reviews_in_cluster:
        text = f"{r.get('headline', '')} {r.get('body', '')}".lower()
        if any(kw in text for kw in _SAFETY_KEYWORDS):
            has_safety = True
            break

    score = 0
    if review_count >= 20:
        score += 3
    elif review_count >= 10:
        score += 2
    elif review_count >= 5:
        score += 1

    if affected_products >= 3:
        score += 2
    elif affected_products >= 2:
        score += 1

    if recency_rate >= 0.30:
        score += 2
    elif recency_rate >= 0.10:
        score += 1

    if has_safety:
        score += 3

    if score >= 7:
        return "critical"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"
```

- [ ] **Step 4: Integrate into cluster building**

In `build_report_analytics()`, after `_build_feature_clusters` or `_cluster_summary_items` returns clusters, add a severity override loop:

```python
# After building own_negative_clusters:
from datetime import datetime
logical_date_obj = datetime.strptime(snapshot.get("logical_date", "2026-01-01"), "%Y-%m-%d").date()
for cluster in own_negative_clusters:
    # Collect reviews in this cluster for safety scan
    cluster_reviews = [
        item["review"] for item in labeled_reviews
        if any(l["label_code"] == cluster["label_code"] and l["label_polarity"] == "negative"
               for l in item["labels"])
        and item["review"].get("ownership") == "own"
    ]
    cluster["severity"] = compute_cluster_severity(cluster, cluster_reviews, logical_date_obj)
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass (existing tests may need severity assertion updates if they hardcode "high")

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_v3_algorithms.py
git commit -m "feat(report): add cluster-level computed severity

4-factor scoring: volume + breadth + recency + safety signal.
Produces 4 distinct levels (critical/high/medium/low) vs all-high."
```

---

### Task 5: Replace gap analysis with dual-dimension algorithm

**Files:**
- Modify: `qbu_crawler/server/report_common.py:159-222` (`_competitor_gap_analysis`)
- Modify: `qbu_crawler/server/report_analytics.py` (generate own positive clusters)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 6.3.2, 14.2

- [ ] **Step 1: Write dual-dimension gap analysis tests**

Append to `tests/test_v3_algorithms.py`:

```python
from qbu_crawler.server.report_common import _competitor_gap_analysis


class TestGapAnalysisV3:
    """Dual-dimension: fix_urgency (own_neg_rate) + catch_up_gap (comp_pos - own_pos)."""

    def test_fix_urgency_high_own_negative(self):
        """Dimension with high own negative rate → 止血 type."""
        # Build a normalized analytics dict with gap_analysis inputs
        normalized = _build_normalized_with_clusters(
            own_neg={"solid_build": 62}, own_pos={}, comp_pos={"solid_build": 108},
            own_total=141, comp_total=569,
        )
        result = _competitor_gap_analysis(normalized)
        dim = next((g for g in result if "质量" in g.get("label_display", "")), None)
        if dim:
            assert dim["gap_type"] == "止血"
            assert dim["fix_urgency"] > 0
            assert dim["priority"] == "high"

    def test_catch_up_gap_no_own_negative(self):
        """Dimension with 0% own negative but high competitor positive → 追赶 type."""
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={}, comp_pos={"strong_performance": 318},
            own_total=141, comp_total=569,
        )
        result = _competitor_gap_analysis(normalized)
        perf_dim = next((g for g in result if "性能" in g.get("label_display", "")), None)
        if perf_dim:
            assert perf_dim["gap_type"] == "追赶"
            assert perf_dim["fix_urgency"] == 0

    def test_uncategorized_filtered_out(self):
        """_uncategorized dimension must not appear in results."""
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={}, comp_pos={"_uncategorized": 10},
            own_total=100, comp_total=500,
        )
        result = _competitor_gap_analysis(normalized)
        codes = [g.get("label_code", g.get("label_display", "")) for g in result]
        assert not any("uncategorized" in c for c in codes)

    def test_empty_data_returns_empty(self):
        normalized = _build_normalized_with_clusters(
            own_neg={}, own_pos={}, comp_pos={}, own_total=0, comp_total=0,
        )
        result = _competitor_gap_analysis(normalized)
        assert result == []
```

Define `_build_normalized_with_clusters` as a module-level helper in `tests/test_v3_algorithms.py`:

```python
def _build_normalized_with_clusters(own_neg, own_pos, comp_pos, own_total, comp_total):
    """Build a minimal normalized analytics dict for gap analysis testing.
    
    Args:
        own_neg: dict {label_code: review_count} for own negative clusters
        own_pos: dict {label_code: review_count} for own positive clusters
        comp_pos: dict {label_code: review_count} for competitor positive clusters
        own_total: total own review count
        comp_total: total competitor review count
    """
    def _clusters_from_dict(d, polarity):
        return [
            {"label_code": code, "review_count": count, "label_polarity": polarity,
             "affected_product_count": 1, "severity": "high"}
            for code, count in d.items()
        ]
    return {
        "kpis": {"own_review_rows": own_total, "competitor_review_rows": comp_total},
        "self": {
            "top_negative_clusters": _clusters_from_dict(own_neg, "negative"),
            "top_positive_clusters": _clusters_from_dict(own_pos, "positive"),
        },
        "competitor": {
            "top_positive_themes": _clusters_from_dict(comp_pos, "positive"),
        },
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_v3_algorithms.py::TestGapAnalysisV3 -v`
Expected: FAIL — old function doesn't return `gap_type`, `fix_urgency` fields

- [ ] **Step 3: Rewrite `_competitor_gap_analysis`**

Replace the function in `report_common.py:159-222` with the V3 algorithm from spec Section 6.3.2:

Key changes:
1. Add `fix_urgency = own_neg_rate` and `catch_up_gap = max(comp_pos_rate - own_pos_rate, 0)`
2. Add `priority_score = fix_urgency * 0.7 + catch_up_gap * 0.3`
3. Add `gap_type` classification ("止血"/"追赶"/"监控")
4. Filter out dimensions where `label_code.startswith("_")`
5. Base `priority` on `priority_score`, not `own_rate`
6. Retain all existing output fields for backward compatibility (old `gap_rate` can be kept as an alias)

- [ ] **Step 4: Generate own positive clusters in `build_report_analytics`**

In `qbu_crawler/server/report_analytics.py`, within `build_report_analytics()`, add after the existing own-negative cluster generation:

```python
own_positive_clusters = _build_feature_clusters(
    labeled_reviews_with_analysis, ownership="own", polarity="positive",
) if labeled_reviews_with_analysis else _cluster_summary_items(
    labeled_reviews, ownership="own", polarity="positive",
)
```

Pass `own_positive_clusters` into the analytics dict so `_competitor_gap_analysis` can access it:

```python
analytics["self"]["top_positive_clusters"] = own_positive_clusters
```

In `_competitor_gap_analysis`, read from `normalized["self"].get("top_positive_clusters", [])` to count own positive mentions per dimension.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py tests/test_v3_algorithms.py
git commit -m "feat(report): dual-dimension gap analysis (fix urgency + catch-up gap)

Replaces single gap_rate with fix_urgency and catch_up_gap.
Classifies dimensions as 止血/追赶/监控.
Filters _uncategorized from output.
Generates own positive clusters for catch_up_gap computation."
```

---

### Task 6: Fix alert level for baseline mode + own_reviews=0 guard

**Files:**
- Modify: `qbu_crawler/server/report_common.py:278-298` (`_compute_alert_level`)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 5.1.3, 14.3

- [ ] **Step 1: Write alert level tests**

Append to `tests/test_v3_algorithms.py`:

```python
from qbu_crawler.server.report_common import _compute_alert_level


class TestAlertLevelV3:
    def test_baseline_high_neg_rate_not_green(self):
        """Baseline with 39% neg rate (health ~57) → should NOT be green."""
        normalized = {
            "mode": "baseline",
            "kpis": {"health_index": 57.4, "own_review_rows": 141},
        }
        level, text = _compute_alert_level(normalized)
        assert level in ("yellow", "red"), f"Expected non-green for unhealthy baseline, got {level}"

    def test_baseline_healthy_is_green(self):
        normalized = {
            "mode": "baseline",
            "kpis": {"health_index": 75.0, "own_review_rows": 50},
        }
        level, _ = _compute_alert_level(normalized)
        assert level == "green"

    def test_zero_own_reviews_is_green(self):
        """No own data → no alert, regardless of health sentinel."""
        normalized = {
            "mode": "incremental",
            "kpis": {"health_index": 50.0, "own_review_rows": 0},
        }
        level, text = _compute_alert_level(normalized)
        assert level == "green"
        assert "不足" in text or "暂不" in text

    def test_incremental_with_escalation_is_red(self):
        normalized = {
            "mode": "incremental",
            "kpis": {
                "health_index": 40.0,
                "own_review_rows": 100,
                "own_negative_review_rows_delta": 15,
            },
            "self": {"top_negative_clusters": []},
        }
        level, _ = _compute_alert_level(normalized)
        assert level == "red"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_v3_algorithms.py::TestAlertLevelV3 -v`
Expected: FAIL — baseline always returns green currently

- [ ] **Step 3: Rewrite `_compute_alert_level`**

Replace in `report_common.py:278-298`:

```python
def _compute_alert_level(normalized):
    """Compute alert level based on health index, deltas, and mode."""
    mode = normalized.get("mode", "baseline")
    kpis = normalized.get("kpis", {})
    health = kpis.get("health_index", 100)
    own_reviews = kpis.get("own_review_rows", 0)

    # Guard: no own data → no alert
    if own_reviews == 0:
        return ("green", "自有评论数据不足，暂不预警")

    if mode == "baseline":
        if health < config.HEALTH_RED:
            return ("red", f"首次基线：健康指数 {health}/100，低于警戒线")
        if health < config.HEALTH_YELLOW:
            return ("yellow", f"首次基线：健康指数 {health}/100，需关注")
        return ("green", "首次基线采集完成，整体状态良好")

    # Incremental mode
    neg_delta = kpis.get("own_negative_review_rows_delta", 0)
    clusters = normalized.get("self", {}).get("top_negative_clusters", [])
    has_escalation = any(
        c.get("severity") in ("critical", "high") and c.get("is_new_or_escalated")
        for c in clusters
    )

    if health < config.HEALTH_RED or neg_delta >= 10 or has_escalation:
        return ("red", _build_alert_text(normalized, "red"))
    if health < config.HEALTH_YELLOW or neg_delta > 0:
        return ("yellow", _build_alert_text(normalized, "yellow"))
    return ("green", "整体健康度良好，无需紧急处理")


def _build_alert_text(normalized, level):
    """Build human-readable alert text from analytics data."""
    kpis = normalized.get("kpis", {})
    health = kpis.get("health_index", 0)
    neg_delta = kpis.get("own_negative_review_rows_delta", 0)
    if level == "red":
        parts = []
        if health < config.HEALTH_RED:
            parts.append(f"健康指数 {health} 低于警戒线 {config.HEALTH_RED}")
        if neg_delta >= 10:
            parts.append(f"差评新增 {neg_delta} 条")
        return "；".join(parts) if parts else "高风险信号"
    # yellow
    parts = []
    if neg_delta > 0:
        parts.append(f"差评新增 {neg_delta} 条")
    if health < config.HEALTH_YELLOW:
        parts.append(f"健康指数 {health} 偏低")
    return "；".join(parts) if parts else "需关注"
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_v3_algorithms.py
git commit -m "feat(report): fix alert level — baseline respects health, zero-data guard

Baseline mode now shows yellow/red when health index is low.
Zero own reviews → green with '暂不预警' text."
```

---

### Task 7: Expand KPI delta fields + add gap summary counts

**Files:**
- Modify: `qbu_crawler/server/report_common.py` (`_compute_kpi_deltas`, KPI card array in `normalize_deep_report_analytics`)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 5.1.2, 14.5, 14.6

- [ ] **Step 1: Write delta and gap count tests**

Append to `tests/test_v3_algorithms.py`:

```python
class TestKpiDeltasAndGapCounts:
    def test_health_index_delta_computed(self):
        """Delta computation includes health_index."""
        from qbu_crawler.server.report_common import normalize_deep_report_analytics
        current = {
            "kpis": {
                "ingested_review_rows": 100,
                "own_review_rows": 50,
                "own_positive_review_rows": 30,
                "own_negative_review_rows": 10,
            }
        }
        previous = {
            "kpis": {
                "ingested_review_rows": 90,
                "own_review_rows": 45,
                "own_positive_review_rows": 28,
                "own_negative_review_rows": 8,
                "health_index": 72.0,
            }
        }
        result = normalize_deep_report_analytics(current, previous_analytics=previous)
        # health_index_delta should exist
        assert "health_index_delta" in result["kpis"] or "health_index_delta_display" in result["kpis"]

    def test_gap_fix_and_catch_counts_present(self):
        """KPIs include gap_fix_count and gap_catch_count after normalization."""
        from qbu_crawler.server.report_common import normalize_deep_report_analytics
        analytics = {
            "kpis": {"ingested_review_rows": 100},
            "competitor": {
                "gap_analysis": [
                    {"gap_type": "止血", "priority_score": 35},
                    {"gap_type": "追赶", "priority_score": 17},
                    {"gap_type": "监控", "priority_score": 2},
                ],
            },
        }
        result = normalize_deep_report_analytics(analytics)
        assert result["kpis"].get("gap_fix_count") == 1
        assert result["kpis"].get("gap_catch_count") == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_v3_algorithms.py::TestKpiDeltasAndGapCounts -v`
Expected: FAIL

- [ ] **Step 3: Expand `_compute_kpi_deltas`**

In `report_common.py`, find `_compute_kpi_deltas` and add `"health_index"` and `"recently_published_count"` to the delta field list.

- [ ] **Step 4: Add gap counts to normalization**

In `normalize_deep_report_analytics`, after gap_analysis is computed, add:

```python
gap_analysis = normalized.get("competitor", {}).get("gap_analysis", [])
kpis["gap_fix_count"] = sum(1 for g in gap_analysis if g.get("gap_type") == "止血")
kpis["gap_catch_count"] = sum(1 for g in gap_analysis if g.get("gap_type") == "追赶")
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_v3_algorithms.py
git commit -m "feat(report): expand KPI deltas + add gap summary counts

Add health_index, recently_published_count to delta computation.
Add gap_fix_count, gap_catch_count to KPIs after gap analysis."
```

---

### Task 8: Add DB support — report_mode column + query_cluster_reviews + update_workflow_run allowed set

**Files:**
- Modify: `qbu_crawler/models.py` (migrations, `query_cluster_reviews`, `update_workflow_run` allowed set)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 10.1 (models.py), 15.1

**Critical note (P1-02):** `update_workflow_run` at line 652 uses an `allowed` whitelist. The `report_mode` field MUST be added to this set, otherwise `update_workflow_run(run_id, report_mode="quiet")` will be silently ignored.

- [ ] **Step 1: Write DB tests**

Append to `tests/test_v3_algorithms.py`:

```python
import sqlite3
import pytest
from qbu_crawler import config, models


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


class TestDBSupport:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return db_file

    def test_report_mode_column_exists(self, db):
        conn = _get_test_conn(db)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()]
        assert "report_mode" in cols

    def test_update_workflow_run_accepts_report_mode(self, db):
        """P1-02 fix: report_mode must be in the allowed set of update_workflow_run."""
        run = models.create_workflow_run({
            "workflow_type": "daily", "status": "pending", "report_phase": "none",
            "logical_date": "2026-04-10", "trigger_key": "daily:2026-04-10:test",
        })
        models.update_workflow_run(run["id"], report_mode="quiet")
        updated = models.get_workflow_run(run["id"])
        assert updated["report_mode"] == "quiet"

    def test_query_cluster_reviews_returns_reviews(self, db):
        conn = _get_test_conn(db)
        # Insert product, review, label
        conn.execute(
            "INSERT INTO products (url, site, name, sku, ownership) VALUES (?, ?, ?, ?, ?)",
            ("http://test.com/p1", "test", "Test Product", "TP1", "own"),
        )
        pid = conn.execute("SELECT id FROM products WHERE sku='TP1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, "user1", "Bad quality", "Broke after 2 uses", "abc123", 1.0, "2026-04-01 10:00:00"),
        )
        rid = conn.execute("SELECT id FROM reviews WHERE author='user1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO review_issue_labels (review_id, label_code, label_polarity, severity, confidence, source, taxonomy_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rid, "quality_stability", "negative", "high", 0.9, "rule_based", "v1"),
        )
        conn.commit()

        result = models.query_cluster_reviews("quality_stability", ownership="own", limit=10)
        assert len(result) == 1
        assert result[0]["product_sku"] == "TP1"
        assert result[0]["rating"] == 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_v3_algorithms.py::TestDBSupport -v`
Expected: FAIL — `report_mode` column missing, `query_cluster_reviews` not defined

- [ ] **Step 3: Add migration for report_mode column**

In `qbu_crawler/models.py`, add to the `migrations` list (around line 244):

```python
"ALTER TABLE workflow_runs ADD COLUMN report_mode TEXT",
```

- [ ] **Step 4: Add `report_mode` to `update_workflow_run` allowed set**

In `qbu_crawler/models.py:653`, add `"report_mode"` to the `allowed` set:

```python
    allowed = {
        "status",
        "report_phase",
        "report_mode",  # NEW — V3 report mode (full/change/quiet)
        "data_since",
        # ... rest unchanged ...
    }
```

- [ ] **Step 5: Implement `query_cluster_reviews`**

Add to `qbu_crawler/models.py` (after `get_previous_completed_run`):

```python
def query_cluster_reviews(label_code: str, ownership: str | None = None, limit: int = 50) -> list[dict]:
    """Fetch reviews tagged with a given label_code from the full corpus.

    Joins reviews + products + review_issue_labels + optional review_analysis.
    Returns newest first by scraped_at.
    """
    conn = get_conn()
    try:
        query = """
            SELECT r.id, r.headline, r.body, r.rating, r.author,
                   r.date_published_parsed, r.images, r.scraped_at,
                   r.headline_cn, r.body_cn,
                   p.name AS product_name, p.sku AS product_sku,
                   p.ownership, p.site
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            JOIN review_issue_labels ril ON ril.review_id = r.id
            WHERE ril.label_code = ?
        """
        params: list = [label_code]
        if ownership:
            query += " AND p.ownership = ?"
            params.append(ownership)
        query += " ORDER BY r.scraped_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/models.py tests/test_v3_algorithms.py
git commit -m "feat(report): add report_mode column + query_cluster_reviews()

DB migration adds report_mode to workflow_runs.
report_mode added to update_workflow_run allowed set.
query_cluster_reviews fetches full-corpus reviews by label_code."
```

---

### Task 8.5: Add `has_estimated_dates` utility (GLOBAL-01)

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 6.5

- [ ] **Step 1: Write test**

```python
from qbu_crawler.server.report_common import has_estimated_dates


class TestEstimatedDates:
    def test_detects_clustered_dates(self):
        """When >30% of reviews parse to the same MM-DD as logical_date, return True."""
        reviews = [
            {"date_published_parsed": "2022-04-10"},  # same MM-DD
            {"date_published_parsed": "2023-04-10"},  # same MM-DD
            {"date_published_parsed": "2024-04-10"},  # same MM-DD
            {"date_published_parsed": "2026-01-15"},  # different
        ]
        assert has_estimated_dates(reviews, "2026-04-10") is True

    def test_no_clustering(self):
        reviews = [
            {"date_published_parsed": "2026-01-01"},
            {"date_published_parsed": "2026-02-15"},
            {"date_published_parsed": "2026-03-20"},
        ]
        assert has_estimated_dates(reviews, "2026-04-10") is False

    def test_empty_reviews(self):
        assert has_estimated_dates([], "2026-04-10") is False
```

- [ ] **Step 2: Implement**

Add to `report_common.py`:

```python
def has_estimated_dates(reviews, logical_date_str):
    """Check if >30% of review dates cluster on the same MM-DD as logical_date.
    
    This indicates relative dates ("3 years ago") parsed to the same day-of-year,
    making timeline analysis unreliable.
    """
    if not reviews:
        return False
    logical_mmdd = logical_date_str[5:]  # "MM-DD" from "YYYY-MM-DD"
    count_matching = sum(
        1 for r in reviews
        if (r.get("date_published_parsed") or "").endswith(logical_mmdd)
    )
    return count_matching / len(reviews) > 0.30
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_v3_algorithms.py::TestEstimatedDates -v
git add qbu_crawler/server/report_common.py tests/test_v3_algorithms.py
git commit -m "feat(report): add has_estimated_dates utility for relative date detection"
```

---

### Task 9: Update config — HIGH_RISK_THRESHOLD + REPORT_OFFLINE_MODE + REPORT_HTML_PUBLIC_URL

**Files:**
- Modify: `qbu_crawler/config.py:162`
- Modify: `tests/test_config_thresholds.py` (if exists)

**Spec ref:** Section 6.2.3, 11.1

- [ ] **Step 1: Change threshold**

In `qbu_crawler/config.py:162`, change:
```python
HIGH_RISK_THRESHOLD = int(os.getenv("REPORT_HIGH_RISK_THRESHOLD", "8"))
```
to:
```python
HIGH_RISK_THRESHOLD = int(os.getenv("REPORT_HIGH_RISK_THRESHOLD", "35"))
```

Also add new config variables (spec 11.1, GLOBAL-02, P3a-03):

```python
REPORT_OFFLINE_MODE = os.getenv("REPORT_OFFLINE_MODE", "false").lower() == "true"
REPORT_HTML_PUBLIC_URL = os.getenv("REPORT_HTML_PUBLIC_URL", "")
```

- [ ] **Step 2: Fix any tests asserting old value**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`

If `test_config_thresholds.py` asserts `HIGH_RISK_THRESHOLD == 8`, update to `35`.

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/config.py tests/test_config_thresholds.py
git commit -m "feat(report): recalibrate HIGH_RISK_THRESHOLD 8→35 for V3 risk score range"
```

---

### Task 9.5: Add `has_estimated_dates` detection (GLOBAL-01 fix)

**Files:**
- Modify: `qbu_crawler/server/report_common.py` (add function)
- Test: `tests/test_v3_algorithms.py` (append)

**Spec ref:** Section 6.5

- [ ] **Step 1: Write test**

```python
from qbu_crawler.server.report_common import has_estimated_dates


class TestEstimatedDates:
    def test_detects_relative_date_clustering(self):
        """When >30% of reviews parse to same MM-DD as logical_date → True."""
        reviews = [
            {"date_published_parsed": "2022-04-10"},  # matches MM-DD
            {"date_published_parsed": "2023-04-10"},  # matches
            {"date_published_parsed": "2024-04-10"},  # matches
            {"date_published_parsed": "2025-04-10"},  # matches
            {"date_published_parsed": "2025-01-15"},  # doesn't match
        ]
        assert has_estimated_dates(reviews, "2026-04-10") is True

    def test_returns_false_for_natural_dates(self):
        reviews = [
            {"date_published_parsed": "2025-01-15"},
            {"date_published_parsed": "2025-03-22"},
            {"date_published_parsed": "2025-06-01"},
            {"date_published_parsed": "2025-09-14"},
        ]
        assert has_estimated_dates(reviews, "2026-04-10") is False

    def test_empty_reviews(self):
        assert has_estimated_dates([], "2026-04-10") is False
```

- [ ] **Step 2: Implement**

Add to `report_common.py`:

```python
def has_estimated_dates(reviews, logical_date_str):
    """Detect if >30% of review dates cluster on the same MM-DD as logical_date.
    
    This indicates relative dates ("3 years ago") were parsed anchored to logical_date.
    Returns True if the dates are likely estimated, False otherwise.
    """
    if not reviews:
        return False
    logical_mmdd = logical_date_str[-5:]  # "MM-DD" from "YYYY-MM-DD"
    matching = sum(
        1 for r in reviews
        if (r.get("date_published_parsed") or "").endswith(logical_mmdd)
    )
    return matching / len(reviews) > 0.30
```

This function is used by:
1. Templates: show footnote "部分日期为估算值" on timeline charts
2. `compute_cluster_changes` (spec 14.9): suppress "improving" detection when dates are estimated

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_v3_algorithms.py::TestEstimatedDates -v
git add qbu_crawler/server/report_common.py tests/test_v3_algorithms.py
git commit -m "feat(report): add has_estimated_dates detection for relative date warning

Detects >30% review date clustering on logical_date MM-DD pattern.
Used by templates for footnote and by cluster change detection for accuracy guard."
```

---

### Task 10: Phase 1 integration test — end-to-end validation

**Files:**
- Test: `tests/test_v3_algorithms.py` (append integration test)

- [ ] **Step 1: Write integration test**

```python
class TestPhase1Integration:
    """End-to-end: build_report_analytics produces V3 metrics from realistic data."""

    @pytest.fixture()
    def analytics_db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "integration.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        monkeypatch.setattr(config, "REPORT_LABEL_MODE", "rule")
        models.init_db()
        return db_file

    def test_full_pipeline_produces_v3_metrics(self, analytics_db):
        """Build analytics from realistic snapshot → verify V3 metric properties."""
        from qbu_crawler.server.report_analytics import build_report_analytics, sync_review_labels
        from qbu_crawler.server.report_common import normalize_deep_report_analytics

        # Insert test data: 2 own products with negative reviews
        conn = _get_test_conn(analytics_db)
        # ... insert products, reviews, snapshots ...
        conn.commit()

        snapshot = {  # minimal snapshot
            "logical_date": "2026-04-10",
            "run_id": 1,
            "products": [...],
            "reviews": [...],
        }

        synced = sync_review_labels(snapshot)
        analytics = build_report_analytics(snapshot, synced)
        normalized = normalize_deep_report_analytics(analytics)

        # V3 property checks
        kpis = normalized["kpis"]

        # Health index is NPS-based (0-100)
        assert 0 <= kpis.get("health_index", -1) <= 100

        # Risk products have rate-based scores
        risk = normalized.get("self", {}).get("risk_products", [])
        if risk:
            assert all(0 <= p["risk_score"] <= 100 for p in risk)

        # Severity has multiple levels
        clusters = normalized.get("self", {}).get("top_negative_clusters", [])
        severities = {c["severity"] for c in clusters}
        # With varied data, should have more than 1 severity level
        # (exact check depends on test data)

        # Gap analysis has gap_type field
        gaps = normalized.get("competitor", {}).get("gap_analysis", [])
        for g in gaps:
            assert "gap_type" in g
            assert g["gap_type"] in ("止血", "追赶", "监控")
            assert "_uncategorized" not in g.get("label_display", "")

        # Alert level: not always green for baseline with low health
        alert_level, alert_text = normalized.get("alert_level", ("green", ""))
        # (depends on health — just verify it's computed)
        assert alert_level in ("red", "yellow", "green")
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_v3_algorithms.py::TestPhase1Integration -v`
Expected: All pass

- [ ] **Step 3: Run full suite one final time**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All 401+ tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_v3_algorithms.py
git commit -m "test(report): add Phase 1 integration test for V3 metric pipeline"
```

---

## Phase 1 Completion Checklist

After all 10 tasks, verify:

- [ ] `_SEVERITY_SCORE` has `"critical"` key
- [ ] `_SEVERITY_DISPLAY` and `_PRIORITY_DISPLAY` have `"critical"` entries
- [ ] `compute_health_index` uses NPS-proxy formula
- [ ] `config.HEALTH_RED` = 45, `config.HEALTH_YELLOW` = 60, `config.HIGH_RISK_THRESHOLD` = 35
- [ ] `_risk_products` uses 5-factor multi-factor formula
- [ ] `compute_cluster_severity` exists and is called in `build_report_analytics`
- [ ] `_competitor_gap_analysis` returns `gap_type`, `fix_urgency`, `catch_up_gap` fields
- [ ] `_uncategorized` dimensions are filtered from gap output
- [ ] `_compute_alert_level` respects baseline health and zero-own-reviews
- [ ] `_compute_kpi_deltas` includes `health_index` and `recently_published_count`
- [ ] KPIs include `gap_fix_count` and `gap_catch_count`
- [ ] `workflow_runs` has `report_mode` column
- [ ] `query_cluster_reviews()` function exists in `models.py`
- [ ] All existing tests pass (401+)
- [ ] No `_uncategorized` in normalized analytics output
