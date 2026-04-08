# Report Analytics Accuracy Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 data accuracy, caliber consistency, and business effectiveness issues identified in the daily report analytics pipeline, ensuring all KPI metrics are truthful, internally consistent, and actionable.

**Architecture:** Bottom-up approach — fix the foundation (keyword matching) first, then metrics caliber, then composite indices, then LLM/display layer. Each task is independently testable and committable. Existing tests in `tests/` provide regression safety.

**Tech Stack:** Python 3.10+, pytest, SQLite, OpenAI SDK (LLM), openpyxl, Jinja2

---

## File Map

| File | Role | Tasks |
|------|------|-------|
| `qbu_crawler/server/report_analytics.py` | Core analytics engine: label classification, clustering, risk scoring, KPI computation | 1, 2, 3, 5, 9 |
| `qbu_crawler/server/report_common.py` | Normalization, health index, alert level, gap index, display helpers | 2, 4, 5 |
| `qbu_crawler/server/report_llm.py` | LLM insights generation and validation | 6 |
| `qbu_crawler/server/report_snapshot.py` | Snapshot freeze and full report orchestration | 7 |
| `qbu_crawler/config.py` | Threshold constants | 4 |
| `tests/test_report_analytics.py` | Analytics engine tests | 1, 2, 3, 5, 9 |
| `tests/test_report_common.py` | Normalization and index tests | 2, 4, 5 |
| `tests/test_report_llm.py` | LLM insights tests | 6 |
| `tests/test_keyword_matching.py` | **New** — dedicated keyword matcher tests | 1 |

---

## Task 1: Fix Keyword Matching — Word Boundary + Negation Detection

**Problem:** `_match_rule` uses `keyword in text` substring matching, causing false positives: "finish" matches "finished assembling", "rust" matches "trust", "hard to clean" matches "not hard to clean".

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:308-309` (`_match_rule`)
- Modify: `qbu_crawler/server/report_analytics.py:29-227` (keyword tuples — add multi-word phrase handling)
- Create: `tests/test_keyword_matching.py`
- Modify: `tests/test_report_analytics.py` (existing tests may need adjustment)

### Steps

- [ ] **Step 1: Create dedicated keyword matching test file with false-positive regression tests**

```python
# tests/test_keyword_matching.py
"""Regression tests for keyword-based review label classification."""

import pytest
from qbu_crawler.server.report_analytics import classify_review_labels, _match_rule


class TestMatchRule:
    """Test the low-level _match_rule function."""

    def test_exact_word_match(self):
        rule = {"keywords": ("broke",)}
        assert _match_rule("the handle broke off", rule)

    def test_no_substring_match(self):
        """'broke' should NOT match inside 'broker' or 'unbroken'."""
        rule = {"keywords": ("broke",)}
        assert not _match_rule("i am a broker and love this", rule)

    def test_finish_false_positive(self):
        """'finish' for material defect must NOT fire on 'finished assembling'."""
        rule = {"keywords": ("finish",)}
        assert not _match_rule("i just finished assembling it works great", rule)

    def test_rust_false_positive(self):
        """'rust' must NOT match 'trust' or 'rustic'."""
        rule = {"keywords": ("rust",)}
        assert not _match_rule("i trust this brand completely", rule)
        assert not _match_rule("nice rustic look", rule)

    def test_rust_true_positive(self):
        rule = {"keywords": ("rust",)}
        assert _match_rule("the blade started to rust after one week", rule)

    def test_multi_word_phrase(self):
        rule = {"keywords": ("hard to clean",)}
        assert _match_rule("this is hard to clean", rule)

    def test_negation_blocks_match(self):
        """'not hard to clean' should NOT match 'hard to clean'."""
        rule = {"keywords": ("hard to clean",)}
        assert not _match_rule("it's not hard to clean at all", rule)

    def test_negation_with_never(self):
        rule = {"keywords": ("broke",)}
        assert not _match_rule("never broke even after years of use", rule)

    def test_case_insensitive(self):
        rule = {"keywords": ("broke",)}
        # _review_text lowercases, but _match_rule receives lowered text
        assert _match_rule("the handle broke", rule)

    def test_chinese_keyword(self):
        rule = {"keywords": ("生锈",)}
        assert _match_rule("这个刀片很快就生锈了", rule)
        assert not _match_rule("不会生锈的材料", rule)  # negation in Chinese


class TestClassifyReviewLabels:
    """Integration tests for full classification pipeline."""

    def _review(self, text, ownership="own", rating=1):
        return {
            "headline": text,
            "body": "",
            "headline_cn": "",
            "body_cn": "",
            "ownership": ownership,
            "rating": rating,
        }

    def test_genuine_quality_issue(self):
        labels = classify_review_labels(self._review("The motor broke after two uses"))
        codes = [l["label_code"] for l in labels]
        assert "quality_stability" in codes

    def test_no_false_positive_on_finished(self):
        labels = classify_review_labels(self._review(
            "Just finished setting up, works perfectly!", rating=5
        ))
        codes = [l["label_code"] for l in labels]
        assert "material_finish" not in codes

    def test_negated_difficulty(self):
        labels = classify_review_labels(self._review(
            "It's not hard to assemble at all, very straightforward", rating=5
        ))
        codes = [l["label_code"] for l in labels]
        assert "assembly_installation" not in codes

    def test_powerful_bare_word_no_longer_matches(self):
        """Bare 'powerful' was removed — only qualified phrases like 'powerful motor' match."""
        labels = classify_review_labels(self._review(
            "Has a powerful chemical smell out of the box", ownership="competitor", rating=2
        ))
        codes = [l["label_code"] for l in labels]
        assert "strong_performance" not in codes
```

- [ ] **Step 2: Run tests to confirm they fail against current implementation**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_keyword_matching.py -v`
Expected: Multiple FAIL — substring matches and negation cases will fail.

- [ ] **Step 3: Implement word-boundary matching with negation detection in `_match_rule`**

Replace `report_analytics.py:267-309`:

```python
import re

# Negation window: if any of these words appear within N words before the keyword, suppress the match.
_NEGATION_WORDS = {"not", "no", "never", "don't", "doesn't", "didn't", "isn't", "wasn't",
                   "won't", "can't", "couldn't", "shouldn't", "wouldn't", "hardly",
                   "没有", "不", "不会", "没", "未", "无"}
_NEGATION_WINDOW = 4  # words

# Pre-compiled regex cache: keyword -> compiled pattern
_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _build_keyword_pattern(keyword: str) -> re.Pattern:
    """Build a regex that matches the keyword at word boundaries.

    For CJK keywords (Chinese/Japanese/Korean), use plain substring matching
    since CJK text has no word boundaries.
    """
    # Check if keyword is primarily CJK
    cjk_chars = sum(1 for c in keyword if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(keyword) / 2:
        # CJK: use escaped literal (no word boundary needed)
        return re.compile(re.escape(keyword))
    # Latin: use word boundary
    return re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)


def _get_keyword_pattern(keyword: str) -> re.Pattern:
    if keyword not in _KEYWORD_PATTERN_CACHE:
        _KEYWORD_PATTERN_CACHE[keyword] = _build_keyword_pattern(keyword)
    return _KEYWORD_PATTERN_CACHE[keyword]


def _is_negated(text: str, match_start: int, keyword: str) -> bool:
    """Check if a keyword match is preceded by a negation word within _NEGATION_WINDOW words."""
    # For CJK: check if common negation characters appear directly before
    cjk_chars = sum(1 for c in keyword if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(keyword) / 2:
        # Look at the 4 characters before the match
        prefix = text[max(0, match_start - 4):match_start]
        return any(neg in prefix for neg in ("不", "没", "未", "无", "没有", "不会"))

    # For Latin: look at preceding words
    before_text = text[:match_start]
    words = before_text.split()
    preceding = words[-_NEGATION_WINDOW:] if words else []
    return any(w.lower().rstrip(".,;:!?") in _NEGATION_WORDS for w in preceding)


def _match_rule(text: str, rule: dict) -> bool:
    """Match keywords using word boundaries with negation detection."""
    for keyword in rule["keywords"]:
        pattern = _get_keyword_pattern(keyword)
        for m in pattern.finditer(text):
            if not _is_negated(text, m.start(), keyword):
                return True
    return False
```

- [ ] **Step 4: Fix ambiguous keywords in rule definitions**

In `_NEGATIVE_RULES`, replace the overly-broad `"finish"` keyword:

```python
"material_finish": {
    "severity": "medium",
    "confidence": 0.88,
    "keywords": (
        "cheap plastic",
        "rust",
        "rusted",
        "rusting",
        "poor finish",
        "bad finish",
        "finish peeling",
        "finish chipping",
        "scratched",
        "scratch",
        "材料差",
        "做工差",
        "生锈",
        "毛刺",
    ),
},
```

In `_POSITIVE_RULES`, qualify `"powerful"`:

```python
"strong_performance": {
    "severity": "medium",
    "confidence": 0.9,
    "keywords": (
        "works great",
        "great performance",
        "powerful motor",
        "powerful enough",
        "very powerful",
        "performs well",
        "动力强",
        "性能好",
    ),
},
```

- [ ] **Step 5: Run all keyword tests + existing tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_keyword_matching.py tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_keyword_matching.py qbu_crawler/server/report_analytics.py
git commit -m "$(cat <<'EOF'
fix: keyword matching uses word boundaries + negation detection

Replaces substring `in` matching with regex \b word boundaries for Latin
keywords and direct lookup for CJK keywords. Adds negation window
detection (not/never/don't etc.) to suppress false positives like
"not hard to clean" → assembly_installation.

Fixes ambiguous keywords: "finish" → "poor finish"/"finish peeling" etc.,
"powerful" → "powerful motor"/"powerful enough" etc.
EOF
)"
```

---

## Task 2: Fix negative_review_rows Mixed-Ownership Caliber

**Problem:** `negative_review_rows` in KPIs counts ALL reviews (own + competitor). `_compute_alert_level` and `_generate_hero_headline` use `negative_review_rows_delta`, so competitor negative growth can falsely trigger own-product alerts.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:938-963` (KPI computation in `build_report_analytics`)
- Modify: `qbu_crawler/server/report_common.py:147-161` (`_compute_kpi_deltas`)
- Modify: `qbu_crawler/server/report_common.py:195-214` (`_compute_alert_level`)
- Modify: `qbu_crawler/server/report_common.py:167-192` (`_generate_hero_headline`)
- Modify: `tests/test_report_analytics.py`
- Modify: `tests/test_report_common.py`

### Steps

- [ ] **Step 1: Write test that proves competitor negatives inflate alert level**

Add to `tests/test_report_common.py`:

```python
def test_alert_level_ignores_competitor_negative_delta():
    """Competitor negative review growth must NOT trigger own-product yellow/red alert."""
    from qbu_crawler.server.report_common import _compute_alert_level, normalize_deep_report_analytics

    analytics = {
        "kpis": {
            "ingested_review_rows": 50,
            "negative_review_rows": 20,       # includes competitor
            "own_negative_review_rows": 2,     # own is low
            "own_review_rows": 20,
            "competitor_review_rows": 30,
            "own_negative_review_rate": 0.1,
            "translated_count": 50,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    normalized = normalize_deep_report_analytics(analytics)
    # Simulate previous run had 10 total negatives (mostly competitor)
    normalized["kpis"]["negative_review_rows_delta"] = 10   # this is ALL reviews
    normalized["kpis"]["own_negative_review_rows_delta"] = 1  # own only changed by 1

    level, _ = _compute_alert_level(normalized)
    # Should NOT be red/yellow just because competitor negatives grew
    assert level == "green", f"Expected green but got {level} — competitor delta is inflating alert"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py::test_alert_level_ignores_competitor_negative_delta -v`
Expected: FAIL

- [ ] **Step 3: Add `own_negative_review_rows_delta` to KPI deltas**

In `report_common.py:153`, expand `_compute_kpi_deltas` to include own-specific delta:

```python
def _compute_kpi_deltas(current_kpis, prev_analytics):
    """Compute difference between current KPIs and those from a previous report."""
    if not prev_analytics:
        return {}
    prev_kpis = prev_analytics.get("kpis", {})
    deltas = {}
    for key in ("negative_review_rows", "own_negative_review_rows",
                "ingested_review_rows", "product_count"):
        curr = current_kpis.get(key, 0) or 0
        prev = prev_kpis.get(key, 0) or 0
        diff = curr - prev
        deltas[f"{key}_delta"] = diff
        deltas[f"{key}_delta_display"] = (
            f"+{diff}" if diff > 0 else str(diff)
        ) if diff != 0 else "—"
    return deltas
```

- [ ] **Step 4: Switch `_compute_alert_level` to use own-only delta**

Replace `report_common.py:195-214`:

```python
def _compute_alert_level(normalized):
    """Return ``(level, text)`` where *level* is ``"red"``/``"yellow"``/``"green"``."""
    top_neg = normalized.get("self", {}).get("top_negative_clusters") or []
    high_sev = [c for c in top_neg if c.get("severity") == "high" and (c.get("review_count") or 0) >= 5]
    # Use own-only delta, not mixed
    delta = normalized.get("kpis", {}).get("own_negative_review_rows_delta", 0) or 0
    health = normalized.get("kpis", {}).get("health_index")

    if high_sev or delta >= 10:
        return "red", "存在高严重度问题簇，建议今日跟进"
    if health is not None and health < config.HEALTH_RED:
        return "red", f"健康指数 {health} 低于警戒线 {config.HEALTH_RED}，建议今日跟进"

    if delta > 0:
        return "yellow", "自有产品差评数较上期有所上升，请持续关注"
    if health is not None and health < config.HEALTH_YELLOW:
        return "yellow", f"健康指数 {health} 偏低，请持续关注"

    return "green", "无新增高风险信号"
```

- [ ] **Step 5: Switch `_generate_hero_headline` to use own-only delta**

In `report_common.py:181`, change:

```python
neg_delta = normalized.get("kpis", {}).get("own_negative_review_rows_delta")
```

- [ ] **Step 5b: Switch `_humanize_bullets` to use own-only delta**

In `report_common.py:_humanize_bullets` (around line 285), change:

```python
neg_delta = normalized.get("kpis", {}).get("own_negative_review_rows_delta", 0) or 0
```

This ensures the executive summary bullet "较上期新增 N 条" also uses the own-only delta, not the mixed-ownership value.

- [ ] **Step 6: Run all related tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py tests/test_report_common.py
git commit -m "$(cat <<'EOF'
fix: alert level and hero headline use own-only negative delta

_compute_alert_level and _generate_hero_headline now reference
own_negative_review_rows_delta instead of the mixed-ownership
negative_review_rows_delta. Prevents competitor negative review
growth from falsely triggering own-product alerts.
EOF
)"
```

---

## Task 3: Add Rating Gate to risk_score Calculation

**Problem:** Any review with a negative keyword label contributes to `risk_score` regardless of its star rating. A 5-star review mentioning "finish" adds 1 + severity_score to the product's risk.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:520-583` (`_risk_products`)
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test for the rating gate**

Add to `tests/test_report_analytics.py`:

```python
def test_risk_products_ignores_high_rating_reviews(analytics_db):
    """Reviews with rating > LOW_RATING_THRESHOLD should not contribute to risk_score."""
    from qbu_crawler.server.report_analytics import _risk_products, _build_labeled_reviews

    snapshot = {
        "products": [
            {"name": "Test Product", "sku": "TP-1", "ownership": "own",
             "rating": 4.5, "review_count": 10, "site": "basspro"},
        ],
        "reviews": [
            # 5-star review that happens to contain "finish" (after Task 1 fix, this may not match,
            # but we test the gate directly)
            {"product_name": "Test Product", "product_sku": "TP-1", "ownership": "own",
             "rating": 5, "headline": "poor finish on the handle", "body": "",
             "headline_cn": "", "body_cn": "", "images": None},
            # 1-star review — should count
            {"product_name": "Test Product", "product_sku": "TP-1", "ownership": "own",
             "rating": 1, "headline": "broke after one use", "body": "",
             "headline_cn": "", "body_cn": "", "images": None},
        ],
    }
    labeled = _build_labeled_reviews(snapshot)
    risk = _risk_products(labeled, snapshot_products=snapshot["products"])

    if risk:
        # The 5-star review should NOT contribute to risk_score
        # Only the 1-star review should count
        product = risk[0]
        assert product["negative_review_rows"] == 1, \
            f"Expected 1 negative review (only low-rating), got {product['negative_review_rows']}"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py::test_risk_products_ignores_high_rating_reviews -v`
Expected: FAIL — currently counts both reviews.

- [ ] **Step 3: Add rating gate to `_risk_products`**

In `report_analytics.py`, modify `_risk_products` (around line 530):

```python
def _risk_products(labeled_reviews, snapshot_products=None):
    sku_to_review_count = {}
    sku_to_rating = {}
    for p in (snapshot_products or []):
        sku = p.get("sku") or ""
        sku_to_review_count[sku] = p.get("review_count") or 0
        sku_to_rating[sku] = p.get("rating")

    grouped = {}
    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != "own":
            continue
        # ── Rating gate: only reviews at or below threshold contribute to risk ──
        rating = float(review.get("rating") or 0)
        if rating > config.LOW_RATING_THRESHOLD:
            continue
        negative_labels = [label for label in item["labels"] if label["label_polarity"] == "negative"]
        if not negative_labels:
            continue
        # ... rest unchanged ...
```

- [ ] **Step 4: Run all analytics tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
fix: risk_score only counts reviews at or below LOW_RATING_THRESHOLD

Reviews with rating > 3 (configurable via LOW_RATING_THRESHOLD) no longer
contribute to product risk scores, even if keyword matching finds negative
labels. This prevents false risk inflation from high-rating reviews that
happen to contain matched keywords.
EOF
)"
```

---

## Task 4: Normalize competitive_gap_index for Sample Size

**Problem:** `compute_competitive_gap_index` sums absolute counts without normalizing for sample size. More competitor reviews → higher index regardless of actual gap severity.

**Files:**
- Modify: `qbu_crawler/server/report_common.py:346-351` (`compute_competitive_gap_index`)
- Modify: `qbu_crawler/server/report_common.py:636-685` (KPI card thresholds for new scale)
- Modify: `tests/test_report_common.py`

### Steps

- [ ] **Step 1: Write test for normalized gap index**

Add to `tests/test_report_common.py`:

```python
def test_competitive_gap_index_normalized():
    """Gap index should be rate-based, not inflated by sample size."""
    from qbu_crawler.server.report_common import compute_competitive_gap_index

    small_sample = [
        {"competitor_positive_count": 5, "own_negative_count": 3,
         "competitor_total": 10, "own_total": 10},
    ]
    large_sample = [
        {"competitor_positive_count": 50, "own_negative_count": 30,
         "competitor_total": 100, "own_total": 100},
    ]
    # Same proportions → same index
    idx_small = compute_competitive_gap_index(small_sample)
    idx_large = compute_competitive_gap_index(large_sample)
    assert abs(idx_small - idx_large) < 5, \
        f"Same proportions should yield similar index: {idx_small} vs {idx_large}"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py::test_competitive_gap_index_normalized -v`
Expected: FAIL — current sum yields 8 vs 80.

- [ ] **Step 3: Implement rate-based gap index**

Replace `report_common.py:346-351`:

```python
def compute_competitive_gap_index(gap_analysis: list[dict]) -> int:
    """Rate-based competitive gap index (0-100 scale).

    For each dimension: gap_rate = (comp_pos_rate + own_neg_rate) / 2
    where each rate = count / total (capped at 1.0).
    Final index = average across dimensions × 100.
    """
    if not gap_analysis:
        return 0
    dimension_scores = []
    for g in gap_analysis:
        comp_pos = g.get("competitor_positive_count", 0)
        own_neg = g.get("own_negative_count", 0)
        comp_total = g.get("competitor_total", 0) or max(comp_pos, 1)
        own_total = g.get("own_total", 0) or max(own_neg, 1)
        comp_rate = min(comp_pos / max(comp_total, 1), 1.0)
        own_rate = min(own_neg / max(own_total, 1), 1.0)
        dimension_scores.append((comp_rate + own_rate) / 2)
    avg = sum(dimension_scores) / len(dimension_scores) if dimension_scores else 0
    return round(avg * 100)
```

- [ ] **Step 4: Pass total review counts into `_competitor_gap_analysis` and populate in gap dicts**

The gap analysis needs total review counts (not just positive/negative counts) for rate-based normalization. These come from KPIs already computed in `normalize_deep_report_analytics`.

In `report_common.py`, update `_competitor_gap_analysis` signature and gap dict:

```python
def _competitor_gap_analysis(normalized):
    """Find dimensions where competitors are praised but our products are criticised."""
    # Total review counts for rate normalization
    kpis = normalized.get("kpis", {})
    competitor_total = kpis.get("competitor_review_rows", 0) or 1
    own_total = kpis.get("own_review_rows", 0) or 1

    comp_positive = {
        t["label_code"]: t
        for t in normalized.get("competitor", {}).get("top_positive_themes", [])
    }
    own_negative_clusters = normalized.get("self", {}).get("top_negative_clusters", [])

    # Group own negatives by their positive-taxonomy dimension
    dimension_own_negative: dict[str, int] = {}
    dimension_neg_codes: dict[str, list[str]] = {}
    for c in own_negative_clusters:
        neg_code = c.get("label_code", "")
        pos_dim = _NEGATIVE_TO_POSITIVE_DIMENSION.get(neg_code)
        if not pos_dim:
            continue
        dimension_own_negative[pos_dim] = dimension_own_negative.get(pos_dim, 0) + (c.get("review_count") or 0)
        dimension_neg_codes.setdefault(pos_dim, []).append(neg_code)

    # Find dimensions where competitor has positive AND own has negative
    gap_dims = set(comp_positive) & set(dimension_own_negative)
    gaps = []
    for dim in gap_dims:
        comp_cnt = comp_positive[dim].get("review_count", 0)
        own_cnt = dimension_own_negative[dim]
        gap_val = comp_cnt - own_cnt
        if own_cnt >= 5:
            priority, priority_display = "high", "高"
        elif own_cnt >= 2:
            priority, priority_display = "medium", "中"
        else:
            priority, priority_display = "low", "低"
        gaps.append({
            "label_code": dim,
            "label_display": _DIMENSION_DISPLAY.get(dim, _LABEL_DISPLAY.get(dim, dim)),
            "competitor_positive_count": comp_cnt,
            "own_negative_count": own_cnt,
            "competitor_total": competitor_total,
            "own_total": own_total,
            "gap": gap_val,
            "priority": priority,
            "priority_display": priority_display,
        })
    return sorted(gaps, key=lambda g: g["own_negative_count"], reverse=True)
```

Note: `competitor_total` and `own_total` are the **total review counts for their respective ownership**, sourced from `kpis.competitor_review_rows` and `kpis.own_review_rows`. This gives the correct denominator for rate calculation in `compute_competitive_gap_index`.

- [ ] **Step 5: Adjust KPI card thresholds for new 0-100 scale**

In `report_common.py` KPI card for "竞品差距指数", update the value_class thresholds:

```python
elif label == "竞品差距指数" and isinstance(val, (int, float)):
    card["value_class"] = "severity-high" if val > 60 else ("severity-medium" if val > 30 else "")
```

- [ ] **Step 6: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "$(cat <<'EOF'
fix: competitive_gap_index uses rate-based scoring (0-100 scale)

Replaces raw count summation with rate-based computation that normalizes
for sample size. Each dimension contributes (comp_positive_rate +
own_negative_rate) / 2, averaged across dimensions and scaled to 0-100.
Same proportions now yield same index regardless of review volume.
EOF
)"
```

---

## Task 5: Rebalance Health Index Weights + Use Sample Rating

**Problem:** 40% of health_index comes from site-reported average rating (a lagging indicator that barely moves). `neg_score` and `risk_score` (leading indicators) are underweighted.

**Files:**
- Modify: `qbu_crawler/server/report_common.py:323-343` (`compute_health_index`)
- Modify: `qbu_crawler/server/report_analytics.py:900-902` (`own_avg_rating` computation)
- Modify: `tests/test_report_common.py`
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test for rebalanced health index**

Add to `tests/test_report_common.py`:

```python
def test_health_index_sensitive_to_negative_spike():
    """Health index should drop significantly when negative rate spikes."""
    from qbu_crawler.server.report_common import compute_health_index

    baseline = {
        "kpis": {"own_avg_rating": 4.5, "own_negative_review_rate": 0.05,
                 "own_product_count": 5, "sample_avg_rating": 4.5},
        "self": {"risk_products": []},
    }
    spiked = {
        "kpis": {"own_avg_rating": 4.5, "own_negative_review_rate": 0.30,
                 "own_product_count": 5, "sample_avg_rating": 3.0},
        "self": {"risk_products": []},
    }
    idx_baseline = compute_health_index(baseline)
    idx_spiked = compute_health_index(spiked)
    # With rebalanced weights, a 25pp neg rate spike should cause >15 point drop
    assert idx_baseline - idx_spiked > 15, \
        f"Index drop too small: {idx_baseline} → {idx_spiked} (diff {idx_baseline - idx_spiked})"
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py::test_health_index_sensitive_to_negative_spike -v`

- [ ] **Step 3: Add `sample_avg_rating` to KPIs in `build_report_analytics`**

In `report_analytics.py`, after `own_avg_rating` computation (line 900-902), add:

```python
# own_avg_rating: site-reported (lagging)
own_ratings = [p.get("rating") for p in own_products if p.get("rating")]
own_avg_rating = round(sum(own_ratings) / len(own_ratings), 2) if own_ratings else 0

# sample_avg_rating: average from actual reviews in this window (leading)
own_review_ratings = [
    float(r["review"].get("rating") or 0) for r in own_reviews
    if r["review"].get("rating")
]
sample_avg_rating = round(sum(own_review_ratings) / len(own_review_ratings), 2) if own_review_ratings else own_avg_rating
```

Add `"sample_avg_rating": sample_avg_rating` to the kpis dict in the return value.

- [ ] **Step 4: Rebalance health index weights**

Replace `report_common.py:323-343`:

```python
def compute_health_index(analytics: dict) -> float:
    """Compute 0-100 health index. Higher = healthier.

    Weights: 20% site rating (lagging) + 25% sample rating (leading)
             + 35% negative rate + 20% risk score.
    """
    kpis = analytics.get("kpis", {})
    own_count = kpis.get("own_product_count", 0) or 1

    # Site-reported rating (lagging indicator)
    site_rating = kpis.get("own_avg_rating", 0) or 0
    site_rating_score = min(site_rating / 5.0, 1.0)

    # Sample rating from current window reviews (leading indicator)
    sample_rating = kpis.get("sample_avg_rating") or site_rating or 0
    sample_rating_score = min(sample_rating / 5.0, 1.0)

    # Negative review rate (leading indicator)
    neg_rate = kpis.get("own_negative_review_rate") or kpis.get("negative_review_rate", 0) or 0
    neg_score = 1.0 - min(neg_rate, 1.0)

    high_risk_count = sum(
        1 for p in analytics.get("self", {}).get("risk_products", [])
        if p.get("risk_score", 0) >= config.HIGH_RISK_THRESHOLD
    )
    risk_ratio = high_risk_count / max(own_count, 1)
    risk_score = 1.0 - min(risk_ratio, 1.0)

    index = (
        site_rating_score * 0.20
        + sample_rating_score * 0.25
        + neg_score * 0.35
        + risk_score * 0.20
    ) * 100
    return round(max(0, min(100, index)), 1)
```

- [ ] **Step 4b: Add test for sample_avg_rating computation in build_report_analytics**

Add to `tests/test_report_analytics.py`:

```python
def test_sample_avg_rating_computed_from_reviews(analytics_db):
    """sample_avg_rating should be the mean of own review ratings, not the site rating."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    snapshot = _build_snapshot(1, "2026-04-01")
    # Ensure own reviews have specific ratings
    own_reviews = [r for r in snapshot["reviews"] if r.get("ownership") == "own"]
    for i, r in enumerate(own_reviews):
        r["rating"] = 2 + i  # e.g., ratings 2, 3, 4...

    analytics = build_report_analytics(snapshot)
    sample_avg = analytics["kpis"].get("sample_avg_rating")
    assert sample_avg is not None, "sample_avg_rating should be computed"
    # Should be the mean of actual review ratings, not the product's site rating
    expected = sum(r["rating"] for r in own_reviews) / len(own_reviews)
    assert abs(sample_avg - expected) < 0.01, \
        f"Expected {expected}, got {sample_avg}"
```

- [ ] **Step 5: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_report_common.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
fix: health index rebalanced — 20% site rating, 25% sample rating, 35% neg rate, 20% risk

Adds sample_avg_rating (from current window reviews) as a leading
indicator alongside the lagging site-reported rating. Negative rate
now has the highest weight (35%) for faster response to quality spikes.
EOF
)"
```

---

## Task 6: Validate LLM Insights Against Actual Analytics Data

**Problem:** `generate_report_insights` trusts LLM output without verifying numerical claims. LLM may hallucinate `evidence_count` or exaggerate quantities in `hero_headline`.

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:359-405` (`generate_report_insights`)
- Modify: `tests/test_report_llm.py`

### Steps

- [ ] **Step 1: Write test for LLM output validation**

Add to `tests/test_report_llm.py`:

```python
def test_validate_llm_evidence_counts():
    """LLM-reported evidence_count must be capped at actual cluster counts."""
    from qbu_crawler.server.report_llm import _validate_insights

    analytics = {
        "self": {
            "top_negative_clusters": [
                {"label_code": "quality_stability", "review_count": 5},
                {"label_code": "noise_power", "review_count": 3},
            ],
        },
    }
    llm_output = {
        "hero_headline": "质量问题严重",
        "executive_summary": "摘要",
        "executive_bullets": ["要点1"],
        "improvement_priorities": [
            {"rank": 1, "target": "Product A", "issue": "质量",
             "action": "修复", "evidence_count": 999},  # hallucinated
        ],
        "competitive_insight": "洞察",
    }
    validated = _validate_insights(llm_output, analytics)
    for p in validated["improvement_priorities"]:
        assert p["evidence_count"] <= 8, \
            f"evidence_count {p['evidence_count']} exceeds total cluster count"


def test_hero_headline_truncation():
    """hero_headline must be capped at 80 chars."""
    from qbu_crawler.server.report_llm import _validate_insights

    llm_output = {
        "hero_headline": "A" * 200,
        "executive_summary": "",
        "executive_bullets": [],
        "improvement_priorities": [],
        "competitive_insight": "",
    }
    validated = _validate_insights(llm_output, {})
    assert len(validated["hero_headline"]) <= 80
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_llm.py::test_validate_llm_evidence_counts tests/test_report_llm.py::test_hero_headline_truncation -v`
Expected: FAIL — `_validate_insights` doesn't exist yet.

- [ ] **Step 3: Implement `_validate_insights` and integrate into pipeline**

Add to `report_llm.py`, before `generate_report_insights`:

```python
_MAX_HEADLINE_LEN = 80


def _validate_insights(llm_output: dict, analytics: dict) -> dict:
    """Cross-validate LLM output against actual analytics data."""
    result = dict(llm_output)

    # Cap headline length
    headline = result.get("hero_headline", "")
    if len(headline) > _MAX_HEADLINE_LEN:
        result["hero_headline"] = headline[:_MAX_HEADLINE_LEN - 1] + "…"

    # Cap executive_bullets to 3
    bullets = result.get("executive_bullets") or []
    result["executive_bullets"] = bullets[:3]

    # Validate improvement_priorities evidence counts
    cluster_counts = {}
    for c in (analytics.get("self") or {}).get("top_negative_clusters") or []:
        code = c.get("label_code") or c.get("feature_display") or ""
        cluster_counts[code] = cluster_counts.get(code, 0) + (c.get("review_count") or 0)
    total_negative = sum(cluster_counts.values())

    for p in result.get("improvement_priorities") or []:
        claimed = p.get("evidence_count", 0) or 0
        # Cap at total negative reviews (LLM can't claim more evidence than exists)
        p["evidence_count"] = min(claimed, total_negative)

    return result
```

Then in `generate_report_insights`, after parsing the LLM response (line 401), add:

```python
        result = _validate_insights(result, analytics)
```

- [ ] **Step 4: Run all LLM tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_llm.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "$(cat <<'EOF'
fix: validate LLM insights against actual analytics data

Adds _validate_insights() that cross-checks LLM output:
- Caps hero_headline at 80 chars
- Caps executive_bullets at 3
- Caps improvement_priorities.evidence_count at total negative reviews
Prevents LLM hallucinations from producing inconsistent report numbers.
EOF
)"
```

---

## Task 7: Share Label Classification Results Instead of Re-Computing

**Problem:** `classify_review_labels` runs 3 times on the same data: `sync_review_labels` (persisted), `_build_labeled_reviews` (in-memory), and `report_llm._review_labels`. Wasteful and risks divergence if hybrid mode is enabled.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:434-449` (`_build_labeled_reviews`)
- Modify: `qbu_crawler/server/report_analytics.py:863-984` (`build_report_analytics`)
- Modify: `qbu_crawler/server/report_snapshot.py:145-147` (call order)
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test confirming label reuse**

Add to `tests/test_report_analytics.py`:

```python
def test_build_report_analytics_uses_synced_labels(analytics_db, monkeypatch):
    """build_report_analytics should use labels from sync, not re-classify."""
    from qbu_crawler.server import report_analytics

    call_count = {"classify": 0}
    original_classify = report_analytics.classify_review_labels

    def counting_classify(review):
        call_count["classify"] += 1
        return original_classify(review)

    monkeypatch.setattr(report_analytics, "classify_review_labels", counting_classify)

    snapshot = _build_snapshot(1, "2026-04-01")
    # Ensure reviews have IDs (sync_review_labels uses _review_id)
    for i, review in enumerate(snapshot["reviews"], start=1):
        review["id"] = i

    # First: sync persists labels and returns them
    synced = report_analytics.sync_review_labels(snapshot)
    initial_count = call_count["classify"]

    # Second: build_report_analytics should NOT re-classify
    call_count["classify"] = 0
    analytics = report_analytics.build_report_analytics(snapshot, synced_labels=synced)
    assert call_count["classify"] == 0, \
        f"classify_review_labels called {call_count['classify']} times during build_report_analytics"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py::test_build_report_analytics_uses_synced_labels -v`
Expected: FAIL — `synced_labels` parameter doesn't exist.

- [ ] **Step 3: Add `synced_labels` parameter to `build_report_analytics`**

Modify `report_analytics.py`:

```python
def _build_labeled_reviews(snapshot, synced_labels=None):
    products = _group_products(snapshot.get("products") or [])
    labeled_reviews = []
    for review in snapshot.get("reviews") or []:
        product_key = _product_key(review.get("product_name"), review.get("product_sku"))
        product = products.get(product_key, {})
        review_id = _review_id(review)
        # Use synced labels if available, otherwise classify
        if synced_labels and review_id in synced_labels:
            labels = synced_labels[review_id]
        else:
            labels = classify_review_labels(review)
        labeled_reviews.append(
            {
                "review": review,
                "labels": labels,
                "product": product,
                "images": _review_images(review),
            }
        )
    return labeled_reviews


def build_report_analytics(snapshot, synced_labels=None):
    mode_info = detect_report_mode(snapshot.get("run_id", 0), snapshot["logical_date"])
    labeled_reviews = _build_labeled_reviews(snapshot, synced_labels=synced_labels)
    # ... rest unchanged
```

- [ ] **Step 4: Update `generate_full_report_from_snapshot` to pass labels through**

In `report_snapshot.py:146-147`:

```python
synced_labels = report_analytics.sync_review_labels(snapshot)
analytics = report_analytics.build_report_analytics(snapshot, synced_labels=synced_labels)
```

- [ ] **Step 5: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py tests/test_report_snapshot.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_snapshot.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
refactor: build_report_analytics reuses synced labels instead of re-classifying

sync_review_labels returns persisted label dict, which is passed through
to _build_labeled_reviews via new synced_labels parameter. Eliminates
redundant classification calls and ensures hybrid-mode label consistency.
EOF
)"
```

---

## Task 8: Make Recommendations Data-Driven with Example Citations

**Problem:** `_RECOMMENDATION_MAP` is a static dict of generic advice. "优先复核高频失效部件寿命" is the same text every report, regardless of what reviews actually say.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:231-264` (`_RECOMMENDATION_MAP`)
- Modify: `qbu_crawler/server/report_analytics.py:586-601` (`_recommendations`)
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test for enriched recommendations**

Add to `tests/test_report_analytics.py`:

```python
def test_recommendations_include_concrete_evidence(analytics_db):
    """Recommendations should reference specific review content, not just generic text."""
    from qbu_crawler.server.report_analytics import _recommendations

    clusters = [
        {
            "label_code": "quality_stability",
            "severity": "high",
            "review_count": 5,
            "example_reviews": [
                {"headline": "Motor burned out", "headline_cn": "电机烧了",
                 "body": "After 3 months the motor just died", "body_cn": "用了三个月电机坏了",
                 "product_name": "Grinder Pro", "product_sku": "GP-1"},
            ],
        },
    ]
    recs = _recommendations(clusters)
    assert recs, "Should produce recommendations"
    rec = recs[0]
    assert "top_complaint" in rec, "Should include top_complaint field"
    assert rec["top_complaint"], "top_complaint should not be empty"
    assert "affected_products" in rec, "Should include affected_products field"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py::test_recommendations_include_concrete_evidence -v`
Expected: FAIL

- [ ] **Step 3: Enrich `_recommendations` with review-level details**

Replace `report_analytics.py:586-601`:

```python
def _recommendations(top_negative_clusters):
    items = []
    for cluster in top_negative_clusters[:5]:
        content = _RECOMMENDATION_MAP.get(cluster["label_code"])
        if not content:
            continue

        # Extract concrete evidence from example reviews
        examples = cluster.get("example_reviews") or []
        top_complaint = ""
        affected_products = []
        seen_products = set()
        for ex in examples:
            if not top_complaint:
                # Use Chinese translation if available, else English
                top_complaint = (
                    (ex.get("headline_cn") or ex.get("headline") or "")
                    + "：" +
                    (ex.get("body_cn") or ex.get("body") or "")
                ).strip().rstrip("：")[:120]
            pname = ex.get("product_name") or ""
            if pname and pname not in seen_products:
                seen_products.add(pname)
                affected_products.append(pname)

        items.append(
            {
                "label_code": cluster["label_code"],
                "priority": "high" if cluster["severity"] == "high" else "medium",
                "possible_cause_boundary": content["possible_cause_boundary"],
                "improvement_direction": content["improvement_direction"],
                "evidence_count": cluster["review_count"],
                "top_complaint": top_complaint,
                "affected_products": affected_products[:3],
            }
        )
    return items
```

- [ ] **Step 4: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
feat: recommendations include top_complaint and affected_products from reviews

_recommendations now extracts concrete evidence from cluster example_reviews:
top_complaint (first review summary, max 120 chars) and affected_products
(up to 3 product names). Makes recommendations actionable with specific
context instead of only generic template text.
EOF
)"
```

---

## Task 9: Add scraped_at vs date_published Semantic Annotation

**Problem:** Reports use `scraped_at` as the time window but readers interpret it as "new reviews". A review published 6 months ago but scraped today appears as "newly added".

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:934-937` (metric_semantics)
- Modify: `qbu_crawler/server/report_analytics.py:938-963` (add date_published breakdown)
- Modify: `qbu_crawler/server/report_common.py:273-317` (`_humanize_bullets`)
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test for time window annotation**

Add to `tests/test_report_analytics.py`:

```python
def test_kpis_include_recently_published_count(analytics_db):
    """KPIs should distinguish scraped count from recently published count."""
    from qbu_crawler.server.report_analytics import build_report_analytics

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-07",
        "snapshot_hash": "test",
        "products": [
            {"name": "P1", "sku": "S1", "ownership": "own", "rating": 4.0,
             "review_count": 10, "site": "basspro"},
        ],
        "reviews": [
            # Published recently
            {"product_name": "P1", "product_sku": "S1", "ownership": "own",
             "rating": 2, "headline": "broke", "body": "", "headline_cn": "",
             "body_cn": "", "date_published": "2026-04-06", "images": None},
            # Published 6 months ago but scraped in this window
            {"product_name": "P1", "product_sku": "S1", "ownership": "own",
             "rating": 1, "headline": "broke after a week", "body": "",
             "headline_cn": "", "body_cn": "", "date_published": "2025-10-01",
             "images": None},
        ],
    }
    analytics = build_report_analytics(snapshot)
    kpis = analytics["kpis"]
    assert "recently_published_count" in kpis
    assert kpis["recently_published_count"] == 1  # only the recent one
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py::test_kpis_include_recently_published_count -v`
Expected: FAIL

- [ ] **Step 3: Add `recently_published_count` to KPIs**

In `report_analytics.py`, add inside `build_report_analytics` before the return dict:

```python
from qbu_crawler.server.report_common import _parse_date_flexible
from datetime import date, timedelta

logical = date.fromisoformat(snapshot["logical_date"])
recent_cutoff = (logical - timedelta(days=30)).isoformat()
recently_published_count = 0
for review in snapshot_reviews:
    pub_date = _parse_date_flexible(review.get("date_published"))
    if pub_date and pub_date >= date.fromisoformat(recent_cutoff):
        recently_published_count += 1
```

Add to the kpis dict:

```python
"recently_published_count": recently_published_count,
```

Update metric_semantics:

```python
"metric_semantics": {
    "ingested_review_rows": "reviews 实际入库行数（按 scraped_at 窗口，含历史补采）",
    "recently_published_count": "其中 date_published 在近 30 天内的评论数",
    "site_reported_review_total_current": "products.review_count 当前站点展示总评论数",
},
```

- [ ] **Step 4: Add disclosure bullet when gap is significant**

In `report_common.py:_humanize_bullets`, before the return, add:

```python
# Bullet: disclosure when many reviews are historically published
kpis = normalized.get("kpis", {})
recently_published = kpis.get("recently_published_count", 0)
ingested = kpis.get("ingested_review_rows", 0)
if ingested > 0 and recently_published < ingested * 0.5:
    backfill_count = ingested - recently_published
    bullets.append(
        f"注：本期 {ingested} 条评论中有 {backfill_count} 条为历史补采（发布于 30 天前），数据含历史积累"
    )
```

- [ ] **Step 5: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
feat: KPIs distinguish recently-published vs backfill-scraped reviews

Adds recently_published_count to KPIs (reviews with date_published within
30 days of logical_date). Updates metric_semantics to clarify scraped_at
window semantics. Adds disclosure bullet when >50% of reviews are
historically published backfills.
EOF
)"
```

---

## Task 10: Unify Feature Cluster and Label Cluster Output Interface

**Problem:** `_build_feature_clusters` and `_cluster_summary_items` produce structurally different cluster objects. Templates may get inconsistent data depending on which path is taken.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:653-716` (`_build_feature_clusters`)
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test for unified cluster interface**

Add to `tests/test_report_analytics.py`:

```python
def test_cluster_output_consistent_fields(analytics_db):
    """Both cluster code paths must produce the same set of fields."""
    from qbu_crawler.server.report_analytics import _cluster_summary_items, _build_feature_clusters, _build_labeled_reviews

    snapshot = _build_snapshot(1, "2026-04-01")
    labeled = _build_labeled_reviews(snapshot)
    label_clusters = _cluster_summary_items(labeled, ownership="own", polarity="negative")

    # Feature clusters need analysis data
    enriched_reviews = [
        {**r, "analysis_features": '["电机质量"]', "analysis_labels": '[{"severity": "high"}]',
         "sentiment": "negative"}
        for r in snapshot["reviews"] if r.get("ownership") == "own"
    ]
    feature_clusters = _build_feature_clusters(enriched_reviews, ownership="own", polarity="negative")

    required_keys = {
        "label_code", "label_display", "review_count", "severity",
        "severity_display", "affected_product_count", "first_seen",
        "last_seen", "example_reviews", "image_review_count",
    }
    for cluster in label_clusters:
        missing = required_keys - set(cluster.keys())
        assert not missing, f"Label cluster missing keys: {missing}"
    for cluster in feature_clusters:
        missing = required_keys - set(cluster.keys())
        assert not missing, f"Feature cluster missing keys: {missing}"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py::test_cluster_output_consistent_fields -v`
Expected: FAIL — `_build_feature_clusters` is missing `label_code` and `severity_display` in some clusters.

- [ ] **Step 3: Add missing fields to `_build_feature_clusters` output**

In `report_analytics.py:698-708`, ensure every cluster dict has:

```python
result.append({
    "label_code": feat,  # use feature text as label_code for template compat
    "feature_display": feat,
    "label_display": feat,
    "label_polarity": polarity,
    "review_count": len(reviews),
    "affected_product_count": len(data["products"]),
    "severity": max_sev,
    "severity_display": {"high": "高", "medium": "中", "low": "低"}.get(max_sev, max_sev),
    "first_seen": min(dates) if dates else None,
    "last_seen": max(dates) if dates else None,
    "example_reviews": sorted(reviews, key=lambda r: r.get("rating", 5))[:3],
    "image_review_count": sum(1 for r in reviews if r.get("images")),
})
```

Also add `label_polarity` to `_cluster_summary_items` output if not already present (it is — line 466 — just confirm `label_code` is always set).

- [ ] **Step 4: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
fix: unify feature cluster and label cluster output interface

_build_feature_clusters now includes label_code and label_polarity
fields for template compatibility with _cluster_summary_items.
Both paths produce the same required field set.
EOF
)"
```

---

## Task 11: Improve Report Mode Semantics

**Problem:** `detect_report_mode` returns "baseline" or "incremental" but both modes run the same analysis logic. The mode label has no behavioral impact.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:349-378` (`detect_report_mode`)
- Modify: `qbu_crawler/server/report_analytics.py:863` (`build_report_analytics` — mode usage)
- Modify: `qbu_crawler/server/report_common.py:431` (mode_display)
- Modify: `tests/test_report_analytics.py`

### Steps

- [ ] **Step 1: Write test for mode-specific behavior**

Add to `tests/test_report_analytics.py`:

```python
def test_baseline_mode_disables_delta_display(analytics_db):
    """In baseline mode, KPI deltas should show '—' since there's no comparison basis."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "mode": "baseline",
        "kpis": {
            "ingested_review_rows": 50,
            "negative_review_rows": 5,
            "own_negative_review_rows": 3,
            "translated_count": 50,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    normalized = normalize_deep_report_analytics(analytics)
    # In baseline mode, delta fields should indicate "no comparison available"
    assert normalized.get("baseline_note"), "Baseline mode should include explanatory note"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_analytics.py::test_baseline_mode_disables_delta_display -v`

- [ ] **Step 3: Add baseline_note and suppress misleading deltas**

In `report_common.py:normalize_deep_report_analytics`, add **AFTER the KPI defaults+spread block** (after the `normalized["kpis"]` dict is fully built, around line 510 — after `translation_completion_rate_display` is set):

```python
# ── Baseline mode: suppress delta displays (must run AFTER KPI spread) ──
if normalized["mode"] == "baseline":
    normalized["baseline_note"] = (
        f"首次全量基线报告（历史样本 {normalized.get('baseline_sample_days', 0)} 天），"
        f"环比数据将在第 4 期报告后开始展示"
    )
    # Clear delta displays to avoid misleading comparisons
    for key in list(normalized["kpis"].keys()):
        if key.endswith("_delta_display"):
            normalized["kpis"][key] = "—"
        if key.endswith("_delta"):
            normalized["kpis"][key] = 0
else:
    normalized["baseline_note"] = ""
```

**Important:** This block MUST be placed after the KPI spread (`**(analytics.get("kpis") or {})`) completes, otherwise the spread would overwrite the suppressed values.

- [ ] **Step 4: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py tests/test_report_analytics.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_analytics.py
git commit -m "$(cat <<'EOF'
feat: baseline mode suppresses delta displays and adds explanatory note

When mode is "baseline" (< 3 historical samples), all KPI delta_display
fields show "—" and baseline_note explains that trend data starts from
the 4th report. Prevents misleading "环比增加" claims on first reports.
EOF
)"
```

---

## Task 12: Strengthen Image Evidence Linking with Label Relevance

**Problem:** Image reviews are linked to risk products and clusters by SKU and label_code only, without semantic relevance scoring. A food photo may be linked to "质量稳定性" and "材料做工" simultaneously.

**Files:**
- Modify: `qbu_crawler/server/report_common.py:561-606` (evidence linking loop)
- Modify: `tests/test_report_common.py`

### Steps

- [ ] **Step 1: Write test for prioritized evidence linking**

Add to `tests/test_report_common.py`:

```python
def test_evidence_refs_prioritize_primary_label():
    """Image evidence should be linked to its primary (highest confidence) label only."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [
                {"product_name": "P1", "product_sku": "S1",
                 "negative_review_rows": 3, "risk_score": 10,
                 "top_labels": [{"label_code": "quality_stability", "count": 3}]},
            ],
            "top_negative_clusters": [
                {"label_code": "quality_stability", "review_count": 3,
                 "severity": "high", "affected_product_count": 1,
                 "example_reviews": [], "image_review_count": 1},
                {"label_code": "material_finish", "review_count": 1,
                 "severity": "medium", "affected_product_count": 1,
                 "example_reviews": [], "image_review_count": 0},
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {
            "image_reviews": [
                {"product_name": "P1", "product_sku": "S1", "ownership": "own",
                 "rating": 1, "headline": "Motor burned out", "body": "broke",
                 "images": ["http://example.com/img1.jpg"],
                 "label_codes": ["quality_stability", "material_finish"]},
            ],
        },
    }
    normalized = normalize_deep_report_analytics(analytics)
    # quality_stability should have the evidence ref (primary label)
    qs_cluster = [c for c in normalized["self"]["top_negative_clusters"]
                  if c.get("label_code") == "quality_stability"][0]
    mf_cluster = [c for c in normalized["self"]["top_negative_clusters"]
                  if c.get("label_code") == "material_finish"][0]

    assert qs_cluster["evidence_refs"], "Primary label cluster should have evidence"
    # material_finish should NOT have the same evidence if it's a secondary label
    # (This is a "nice to have" — at minimum, primary should be linked)
```

- [ ] **Step 2: Implement primary-label-first evidence linking**

In `report_common.py`, modify the image_reviews processing loop (around line 563) to track which label is primary:

```python
for index, item in enumerate(normalized["appendix"]["image_reviews"][:10], start=1):
    review = dict(item)
    images = review.get("images") or []
    label_codes = _derive_review_label_codes(review)
    review["label_codes"] = label_codes
    review["primary_label"] = label_codes[0] if label_codes else None
    # ... rest unchanged, but use primary_label for evidence_refs_by_label:

    # Only link to the primary (first/highest-confidence) label
    primary = label_codes[0] if label_codes else None
    if primary:
        evidence_refs_by_label.setdefault(primary, []).append(review["evidence_id"])
```

- [ ] **Step 3: Run tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "$(cat <<'EOF'
fix: image evidence linked to primary label only, not all matched labels

Evidence references in clusters now link to the review's primary
(highest-confidence) label instead of all matched labels. Prevents
one image from being spread across unrelated issue clusters.
EOF
)"
```

---

## Task 13: Fix Relative Date Parsing Precision

**Problem:** `_parse_date_flexible` uses month=30 days, year=365 days, causing ~2 day drift per month. For `duration_display`, this can change a "2 month" duration to "3 months".

**Files:**
- Modify: `qbu_crawler/server/report_common.py:217-249` (`_parse_date_flexible`)
- Modify: `tests/test_report_common.py`

### Steps

- [ ] **Step 1: Write precision test**

Add to `tests/test_report_common.py`:

```python
def test_parse_date_flexible_month_precision():
    """'3 months ago' from 2026-04-07 should be ~2026-01-07, not 2025-12-28."""
    from qbu_crawler.server.report_common import _parse_date_flexible
    from datetime import date

    # _parse_date_flexible imports `date` locally, so we patch at the datetime module level
    import datetime as dt_module
    original_date = dt_module.date

    class FakeDate(original_date):
        @classmethod
        def today(cls):
            return original_date(2026, 4, 7)

    dt_module.date = FakeDate
    try:
        result = _parse_date_flexible("3 months ago")
    finally:
        dt_module.date = original_date

    # Should be January 2026, not December 2025
    assert result is not None
    assert result.month == 1 and result.year == 2026
```

- [ ] **Step 2: Run test**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py::test_parse_date_flexible_month_precision -v`

- [ ] **Step 3: Use `dateutil.relativedelta` or calendar-aware subtraction**

Replace the month/year handling in `_parse_date_flexible`:

```python
def _parse_date_flexible(value: str | None):
    """Parse a date string in various formats."""
    if not value:
        return None
    from datetime import date, timedelta
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, IndexError):
        pass
    try:
        from datetime import datetime
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        pass
    import re
    today = date.today()
    m = re.match(r"(?:(\d+)|a|an)\s+(day|week|month|year)s?\s+ago", s, re.IGNORECASE)
    if m:
        amount = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2).lower()
        if unit == "day":
            return today - timedelta(days=amount)
        elif unit == "week":
            return today - timedelta(weeks=amount)
        elif unit == "month":
            # Calendar-aware: subtract months, clamp day
            month = today.month - amount
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            import calendar
            max_day = calendar.monthrange(year, month)[1]
            day = min(today.day, max_day)
            return date(year, month, day)
        elif unit == "year":
            try:
                return today.replace(year=today.year - amount)
            except ValueError:
                # Feb 29 → Feb 28
                return today.replace(year=today.year - amount, day=28)
    return None
```

- [ ] **Step 4: Run all tests**

Run: `cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "$(cat <<'EOF'
fix: relative date parsing uses calendar-aware month/year subtraction

Replaces timedelta(days=amount*30) with proper calendar subtraction
that handles varying month lengths. "3 months ago" from April 7 now
correctly yields January 7, not December 28.
EOF
)"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd /e/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/ -v --tb=short
```
Expected: ALL PASS

- [ ] **Update CLAUDE.md if needed**

Check if any new config, new KPI field, or changed behavior needs documenting in CLAUDE.md's "通用架构决策" or "DrissionPage 通用开发注意事项" sections.

---

## Dependency Graph

```
Task 1 (keyword matching)  ← Foundation — all downstream metrics depend on this
    ↓
Task 3 (risk_score gate)   ← Uses labels from Task 1
    ↓
Task 5 (health index)      ← Uses risk_score from Task 3
    ↓
Task 2 (own-only delta)    ← Affects alert_level which uses health_index
    ↓
Task 4 (gap index)         ← Independent of 2/3/5 but same normalization layer
    ↓
Task 6 (LLM validation)    ← Uses analytics output from above tasks
Task 7 (label reuse)       ← Refactor, can run after Task 1
Task 8 (recommendations)   ← Uses cluster data from Task 1/3
Task 9 (time annotation)   ← Independent, any time
Task 10 (cluster interface) ← Independent, any time
Task 11 (report mode)      ← Independent, any time
Task 12 (evidence linking)  ← Independent, any time
Task 13 (date parsing)     ← Independent, any time
```

Tasks 9-13 are independent and can be parallelized as subagent work.
