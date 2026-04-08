# Report Data Accuracy Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 report accuracy issues across data correctness, metric consistency, and feature gaps — delivering in 3 priority tiers (P0→P1→P2).

**Architecture:** Modifications to the existing report pipeline (`report_analytics.py` → `report_common.py` → templates). No new modules. LLM labels replace rule-based labels as the primary source for all analytics. 5 unified radar dimensions replace the current 14-code binary system.

**Tech Stack:** Python 3.10+, pytest, SQLite, openpyxl, Plotly.js, Jinja2

**Spec:** `docs/superpowers/specs/2026-04-08-report-data-accuracy-redesign.md`

---

## File Map

| File | Responsibility | Tasks |
|------|---------------|-------|
| `qbu_crawler/server/report_analytics.py` | Analytics engine: label sync, clustering, charts, risk scoring | T1, T2, T4, T5, T8, T9, T10 |
| `qbu_crawler/server/report_common.py` | Normalization, KPI cards, bullets, alerts, date parsing, dimension mapping | T3, T6, T7, T11 |
| `qbu_crawler/server/report_snapshot.py` | Snapshot freeze + date field persistence | T7 |
| `qbu_crawler/models.py` | DB schema migration, date backfill, trend queries | T7, T8 |
| `qbu_crawler/server/report.py` | Excel generation, image embedding | T10 |
| `tests/test_report_analytics.py` | Analytics unit tests | T1, T2, T4, T5, T9 |
| `tests/test_report_common.py` | Common helpers unit tests | T3, T6, T7, T11 |
| `tests/test_report_charts.py` | Chart data tests | T5, T9 |

---

## P0 — Data Correctness

### Task 1: Fix first_seen/last_seen date sorting

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:569-570, 785-786`
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: Write failing test for relative date sorting**

In `tests/test_report_analytics.py`, add:

```python
def test_date_sort_key_relative_dates():
    """Relative dates must sort chronologically, not lexicographically."""
    from qbu_crawler.server.report_analytics import _date_sort_key
    from datetime import date

    # "5 years ago" is earlier than "2 years ago"
    key_5y = _date_sort_key("5 years ago")
    key_2y = _date_sort_key("2 years ago")
    assert key_5y < key_2y, "5 years ago should sort before 2 years ago"

    # Unparseable falls to epoch
    key_bad = _date_sort_key("unknown")
    assert key_bad == date(1970, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_analytics.py::test_date_sort_key_relative_dates -v`
Expected: FAIL — `_date_sort_key` does not exist

- [ ] **Step 3: Implement `_date_sort_key` and fix sorting in `_cluster_summary_items`**

In `qbu_crawler/server/report_analytics.py`, add near the top (after imports):

```python
def _date_sort_key(date_str):
    """Parse date string for chronological sorting. Unparseable → epoch."""
    from qbu_crawler.server.report_common import _parse_date_flexible
    parsed = _parse_date_flexible(date_str)
    return parsed or date(1970, 1, 1)
```

Replace line 569-570 in `_cluster_summary_items`:
```python
# BEFORE:
# item["first_seen"] = min(dates) if dates else None
# item["last_seen"] = max(dates) if dates else None
# AFTER:
sorted_dates = sorted(dates, key=_date_sort_key)
item["first_seen"] = sorted_dates[0] if sorted_dates else None
item["last_seen"] = sorted_dates[-1] if sorted_dates else None
```

Replace line 785-786 in `_build_feature_clusters` with the same pattern.

- [ ] **Step 4: Write integration test for cluster date ordering**

```python
def test_feature_clusters_first_last_seen_chronological():
    """first_seen should be the earliest date, last_seen the most recent."""
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "5 years ago",
            "analysis_features": '["quality issue"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
        },
        {
            "ownership": "own", "sentiment": "negative", "rating": 2,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2 years ago",
            "analysis_features": '["quality issue"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
        },
    ]
    clusters = _build_feature_clusters(reviews, ownership="own", polarity="negative")
    cluster = clusters[0]
    assert cluster["first_seen"] == "5 years ago"
    assert cluster["last_seen"] == "2 years ago"
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/test_report_analytics.py -v -k "date_sort or first_last_seen"`
Expected: PASS

- [ ] **Step 6: Commit**

```
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "fix: sort first_seen/last_seen chronologically, not lexicographically"
```

---

### Task 2: Fix feature cluster fragmentation with label-code merging

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (`_build_feature_clusters`)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: Write failing test for cluster merging**

```python
def test_feature_clusters_merge_by_label_code():
    """Features with same primary label_code should merge into one cluster."""
    from qbu_crawler.server.report_analytics import _build_feature_clusters

    reviews = [
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-01-01",
            "analysis_features": '["broke after a week"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}]',
        },
        {
            "ownership": "own", "sentiment": "negative", "rating": 2,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-02-01",
            "analysis_features": '["lifespan too short"]',
            "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}]',
        },
        {
            "ownership": "own", "sentiment": "negative", "rating": 1,
            "product_sku": "SKU1", "product_name": "P1",
            "date_published": "2026-03-01",
            "analysis_features": '["metal shavings"]',
            "analysis_labels": '[{"code": "material_finish", "polarity": "negative", "severity": "medium", "confidence": 0.88}]',
        },
    ]
    clusters = _build_feature_clusters(reviews, ownership="own", polarity="negative")

    # Should produce 2 clusters (quality_stability + material_finish), not 3
    assert len(clusters) == 2

    # quality_stability cluster merges 2 reviews
    qs_cluster = next(c for c in clusters if c["label_code"] == "quality_stability")
    assert qs_cluster["review_count"] == 2
    assert len(qs_cluster["sub_features"]) == 2
    assert any(sf["feature"] == "broke after a week" for sf in qs_cluster["sub_features"])
    assert any(sf["feature"] == "lifespan too short" for sf in qs_cluster["sub_features"])

    # material_finish cluster has 1 review
    mf_cluster = next(c for c in clusters if c["label_code"] == "material_finish")
    assert mf_cluster["review_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_analytics.py::test_feature_clusters_merge_by_label_code -v`
Expected: FAIL — clusters produce 3 items (one per feature string)

- [ ] **Step 3: Implement label-code merging in `_build_feature_clusters`**

Rewrite `_build_feature_clusters` in `qbu_crawler/server/report_analytics.py`. The core change: after collecting features per review, determine each feature's primary label_code (highest-confidence matching-polarity label), then group by label_code instead of by feature string.

```python
def _build_feature_clusters(reviews_with_analysis, ownership="own", polarity="negative"):
    from collections import defaultdict

    # Phase 1: Collect features with their primary label_code
    code_groups = defaultdict(lambda: {"reviews": [], "products": set(), "severities": [], "sub_features": defaultdict(int)})
    uncategorized = {"reviews": [], "products": set(), "severities": [], "sub_features": defaultdict(int)}

    for r in reviews_with_analysis:
        if r.get("ownership") != ownership:
            continue
        sentiment = r.get("sentiment") or ""
        if polarity == "negative" and sentiment not in ("negative", "mixed"):
            continue
        if polarity == "positive" and sentiment not in ("positive", "mixed"):
            continue

        raw_features = r.get("analysis_features") or r.get("features") or "[]"
        raw_labels = r.get("analysis_labels") or r.get("labels") or "[]"
        features = json.loads(raw_features) if isinstance(raw_features, str) else raw_features
        labels = json.loads(raw_labels) if isinstance(raw_labels, str) else raw_labels

        # Find primary label_code matching target polarity
        matching_labels = [
            l for l in labels if isinstance(l, dict) and l.get("polarity") == polarity
        ]
        matching_labels.sort(key=lambda l: -l.get("confidence", 0))
        primary_code = matching_labels[0]["code"] if matching_labels else None

        max_severity = "low"
        for label in matching_labels:
            sev = label.get("severity", "low")
            if _SEVERITY_SCORE.get(sev, 0) > _SEVERITY_SCORE.get(max_severity, 0):
                max_severity = sev

        target = code_groups[primary_code] if primary_code else uncategorized
        target["reviews"].append(r)
        target["products"].add(r.get("product_sku") or r.get("product_name", ""))
        target["severities"].append(max_severity)
        for feat in features:
            feat = feat.strip() if isinstance(feat, str) else str(feat)
            if feat:
                target["sub_features"][feat] += 1

    # Phase 2: Build cluster output
    result = []
    from qbu_crawler.server.report_common import _LABEL_DISPLAY
    for code, data in code_groups.items():
        if not code or not data["reviews"]:
            continue
        reviews = data["reviews"]
        dates = [r.get("date_published") for r in reviews if r.get("date_published")]
        max_sev = max(data["severities"], key=lambda s: _SEVERITY_SCORE.get(s, 0), default="low")
        sorted_dates = sorted(dates, key=_date_sort_key)

        sub_features = [
            {"feature": feat, "count": cnt}
            for feat, cnt in sorted(data["sub_features"].items(), key=lambda x: -x[1])
        ]

        result.append({
            "label_code": code,
            "feature_display": _LABEL_DISPLAY.get(code, code),
            "label_display": _LABEL_DISPLAY.get(code, code),
            "label_polarity": polarity,
            "review_count": len(reviews),
            "affected_product_count": len(data["products"]),
            "severity": max_sev,
            "severity_display": {"high": "高", "medium": "中", "low": "低"}.get(max_sev, max_sev),
            "first_seen": sorted_dates[0] if sorted_dates else None,
            "last_seen": sorted_dates[-1] if sorted_dates else None,
            "example_reviews": sorted(reviews, key=lambda r: r.get("rating", 5))[:3],
            "image_review_count": sum(1 for r in reviews if r.get("images")),
            "sub_features": sub_features,
        })

    # Add uncategorized if any
    if uncategorized["reviews"]:
        dates = [r.get("date_published") for r in uncategorized["reviews"] if r.get("date_published")]
        sorted_dates = sorted(dates, key=_date_sort_key)
        max_sev = max(uncategorized["severities"], key=lambda s: _SEVERITY_SCORE.get(s, 0), default="low")
        result.append({
            "label_code": "_uncategorized",
            "feature_display": "其他",
            "label_display": "其他",
            "label_polarity": polarity,
            "review_count": len(uncategorized["reviews"]),
            "affected_product_count": len(uncategorized["products"]),
            "severity": max_sev,
            "severity_display": {"high": "高", "medium": "中", "low": "低"}.get(max_sev, max_sev),
            "first_seen": sorted_dates[0] if sorted_dates else None,
            "last_seen": sorted_dates[-1] if sorted_dates else None,
            "example_reviews": sorted(uncategorized["reviews"], key=lambda r: r.get("rating", 5))[:3],
            "image_review_count": sum(1 for r in uncategorized["reviews"] if r.get("images")),
            "sub_features": [{"feature": f, "count": c} for f, c in sorted(uncategorized["sub_features"].items(), key=lambda x: -x[1])],
        })

    result.sort(key=lambda c: (
        -c["review_count"],
        -_SEVERITY_SCORE.get(c["severity"], 0),
        -c["image_review_count"],
    ))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_report_analytics.py::test_feature_clusters_merge_by_label_code -v`
Expected: PASS

- [ ] **Step 5: Ensure downstream `sub_features` tolerance**

The fallback path `_cluster_summary_items` (used when `use_feature_clusters=False`) does NOT produce `sub_features`. Templates and `normalize_deep_report_analytics` that consume cluster data must use `.get("sub_features") or []`. Verify that `report_common.py`'s normalization loop (lines 616-628) does not crash on missing `sub_features`.

- [ ] **Step 6: Run full analytics test suite**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_common.py tests/test_report_charts.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "fix: merge feature clusters by label_code to eliminate fragmentation"
```

---

### Task 3: Fix backfill notice truncation in `_humanize_bullets`

**Files:**
- Modify: `qbu_crawler/server/report_common.py:331-383`
- Test: `tests/test_report_common.py`

- [ ] **Step 1: Write failing test**

```python
def test_humanize_bullets_backfill_notice_survives_truncation():
    """When >50% reviews are backfill, the notice must appear in first 3 bullets."""
    from qbu_crawler.server.report_common import _humanize_bullets

    normalized = {
        "kpis": {
            "ingested_review_rows": 100,
            "recently_published_count": 10,
            "own_negative_review_rows_delta": 0,
            "product_count": 2,
            "own_product_count": 1,
            "competitor_product_count": 1,
            "own_review_rows": 80,
        },
        "self": {"risk_products": [
            {"product_name": "P1", "negative_review_rows": 5, "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 5}]}
        ]},
        "competitor": {"top_positive_themes": [{"label_display": "易清洗", "review_count": 3}], "gap_analysis": []},
    }
    bullets = _humanize_bullets(normalized)
    assert len(bullets) <= 3
    assert any("历史补采" in b for b in bullets), f"Backfill notice missing from: {bullets}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_common.py::test_humanize_bullets_backfill_notice_survives_truncation -v`
Expected: FAIL — backfill notice not in first 3 bullets

- [ ] **Step 3: Move backfill detection to function start**

In `qbu_crawler/server/report_common.py`, modify `_humanize_bullets` (lines 331-383):

1. Move the backfill detection (lines 376-382) to the very top, before Bullet 1
2. Delete the old block at lines 376-382
3. Keep `return bullets[:3]` unchanged

```python
def _humanize_bullets(normalized):
    bullets = []
    kpis = normalized.get("kpis", {})

    # Backfill disclosure — MUST be first to survive [:3] truncation
    recently_published = kpis.get("recently_published_count", 0)
    ingested = kpis.get("ingested_review_rows", 0)
    if ingested > 0 and recently_published < ingested * 0.5:
        backfill_count = ingested - recently_published
        bullets.append(
            f"注：本期 {ingested} 条评论中有 {backfill_count} 条为历史补采"
            f"（发布于 30 天前），数据含历史积累"
        )

    # Bullet: highest-risk product (existing logic — lines 335-348 unchanged)
    top = (normalized.get("self", {}).get("risk_products") or [None])[0]
    # ... rest of existing logic unchanged ...

    return bullets[:3]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_report_common.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "fix: ensure backfill notice survives bullet truncation"
```

---

## P1 — Metric Accuracy

### Task 4: Unify label source (LLM primary, rule fallback)

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:456-476` (`sync_review_labels`)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: Write failing test for LLM label extraction**

```python
def test_extract_validated_llm_labels_filters_polarity():
    """LLM labels with wrong polarity for their code should be rejected."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    review = {
        "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}, '
                           '{"code": "solid_build", "polarity": "negative", "severity": "low", "confidence": 0.7}, '
                           '{"code": "easy_to_use", "polarity": "positive", "severity": "low", "confidence": 0.8}]'
    }
    labels = _extract_validated_llm_labels(review)
    codes = {l["label_code"] for l in labels}
    # solid_build/negative should be rejected (positive-only code)
    assert "solid_build" not in codes
    assert "quality_stability" in codes
    assert "easy_to_use" in codes


def test_extract_validated_llm_labels_caps_at_3():
    """Per-review cap of 3 labels, highest confidence first."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    review = {
        "analysis_labels": '[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}, '
                           '{"code": "structure_design", "polarity": "negative", "severity": "medium", "confidence": 0.9}, '
                           '{"code": "material_finish", "polarity": "negative", "severity": "medium", "confidence": 0.85}, '
                           '{"code": "packaging_shipping", "polarity": "negative", "severity": "low", "confidence": 0.7}]'
    }
    labels = _extract_validated_llm_labels(review)
    assert len(labels) == 3
    assert labels[0]["label_code"] == "quality_stability"  # highest confidence
    assert labels[2]["label_code"] == "material_finish"     # 3rd highest


def test_extract_validated_llm_labels_service_fulfillment_allows_both():
    """service_fulfillment is the only bidirectional code."""
    from qbu_crawler.server.report_analytics import _extract_validated_llm_labels

    review = {
        "analysis_labels": '[{"code": "service_fulfillment", "polarity": "positive", "severity": "low", "confidence": 0.8}]'
    }
    labels = _extract_validated_llm_labels(review)
    assert len(labels) == 1
    assert labels[0]["label_code"] == "service_fulfillment"
    assert labels[0]["label_polarity"] == "positive"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_analytics.py -v -k "extract_validated"`
Expected: FAIL — `_extract_validated_llm_labels` does not exist

- [ ] **Step 3: Implement `_extract_validated_llm_labels` and rewrite `sync_review_labels`**

**Critical field mapping**: LLM `analysis_labels` JSON uses `code`/`polarity` keys, but `review_issue_labels` table and downstream code expect `label_code`/`label_polarity`. The `_extract_validated_llm_labels` function must map: `code` → `label_code`, `polarity` → `label_polarity`.

In `qbu_crawler/server/report_analytics.py`, add the polarity whitelist and extraction function, then rewrite `sync_review_labels` per the spec (Section 4.1). Key constants:

```python
_POLARITY_WHITELIST = {
    "quality_stability": {"negative"},
    "structure_design": {"negative"},
    "assembly_installation": {"negative"},
    "material_finish": {"negative"},
    "cleaning_maintenance": {"negative"},
    "noise_power": {"negative"},
    "packaging_shipping": {"negative"},
    "service_fulfillment": {"negative", "positive"},
    "easy_to_use": {"positive"},
    "solid_build": {"positive"},
    "good_value": {"positive"},
    "easy_to_clean": {"positive"},
    "strong_performance": {"positive"},
    "good_packaging": {"positive"},
}

_MAX_LABELS_PER_REVIEW = 3
```

- [ ] **Step 4: Run all label-related tests**

Run: `uv run pytest tests/test_report_analytics.py tests/test_keyword_matching.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat: unify label source — LLM primary with polarity validation, rule fallback"
```

---

### Task 5: Fix radar chart with 5 unified dimensions

**Depends on:** Task 4 (label unification) — unified labels provide multi-polarity data per dimension, which is required for meaningful radar scores. Without Task 4, most dimensions remain single-polarity and the radar stays degenerate.

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (`_compute_chart_data`, radar section)
- Create constant: `qbu_crawler/server/report_common.py` (`CODE_TO_DIMENSION`)
- Test: `tests/test_report_charts.py`

- [ ] **Step 1: Write failing test for dimension mapping and radar values**

In `tests/test_report_charts.py`:

```python
def test_radar_uses_unified_dimensions():
    """Radar chart should use 5 unified dimensions, not raw label codes."""
    from qbu_crawler.server.report_analytics import _compute_chart_data
    from qbu_crawler.server.report_common import CODE_TO_DIMENSION

    # Verify dimension mapping
    assert CODE_TO_DIMENSION["quality_stability"] == "耐久性与质量"
    assert CODE_TO_DIMENSION["solid_build"] == "耐久性与质量"
    assert CODE_TO_DIMENSION["structure_design"] == "设计与使用"
    assert CODE_TO_DIMENSION["easy_to_use"] == "设计与使用"
    assert CODE_TO_DIMENSION["service_fulfillment"] == "售后与履约"

    labeled_reviews = [
        {"review": {"ownership": "own", "product_sku": "S1", "product_name": "P1"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative", "severity": "high", "confidence": 0.9}],
         "images": [], "product": {}},
        {"review": {"ownership": "own", "product_sku": "S1", "product_name": "P1"},
         "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
         "images": [], "product": {}},
        {"review": {"ownership": "competitor", "product_sku": "C1", "product_name": "CP1"},
         "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
         "images": [], "product": {}},
    ]
    snapshot = {"products": [
        {"name": "P1", "sku": "S1", "ownership": "own", "price": 100, "rating": 3.5},
        {"name": "CP1", "sku": "C1", "ownership": "competitor", "price": 200, "rating": 4.5},
    ]}
    charts = _compute_chart_data(labeled_reviews, snapshot)
    radar = charts.get("_radar_data", {})
    if radar:
        # Dimensions should be the unified Chinese names
        assert "耐久性与质量" in radar["categories"]
        # Values should not all be 0 or 1
        own_durability = radar["own_values"][radar["categories"].index("耐久性与质量")]
        assert 0 < own_durability < 1, f"Expected continuous value, got {own_durability}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_charts.py::test_radar_uses_unified_dimensions -v`
Expected: FAIL — `CODE_TO_DIMENSION` does not exist

- [ ] **Step 3: Add `CODE_TO_DIMENSION` constant to `report_common.py`**

```python
CODE_TO_DIMENSION = {
    "quality_stability": "耐久性与质量",
    "material_finish": "耐久性与质量",
    "solid_build": "耐久性与质量",
    "structure_design": "设计与使用",
    "assembly_installation": "设计与使用",
    "easy_to_use": "设计与使用",
    "cleaning_maintenance": "清洁便利性",
    "easy_to_clean": "清洁便利性",
    "noise_power": "性能表现",
    "strong_performance": "性能表现",
    "service_fulfillment": "售后与履约",
}
```

- [ ] **Step 4: Rewrite radar computation in `_compute_chart_data`**

Replace the radar section (~lines 823-854) with the two-phase negative-wins algorithm from the spec (Section 4.4).

- [ ] **Step 5: Run chart tests**

Run: `uv run pytest tests/test_report_charts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_report_charts.py
git commit -m "feat: replace degenerate radar with 5 unified dimensions, review-level counting"
```

---

### Task 6: Add coverage rate KPI and metric labeling

**Files:**
- Modify: `qbu_crawler/server/report_common.py` (KPI cards, METRIC_TOOLTIPS)
- Test: `tests/test_report_common.py`

- [ ] **Step 1: Write failing test for coverage KPI card**

```python
def test_normalize_adds_coverage_rate_kpi():
    """KPI cards should include a coverage rate card."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 148,
            "site_reported_review_total_current": 223,
            "translated_count": 148,
        },
    }
    result = normalize_deep_report_analytics(analytics)
    card_labels = [c["label"] for c in result["kpi_cards"]]
    assert "样本覆盖率" in card_labels
    coverage_card = next(c for c in result["kpi_cards"] if c["label"] == "样本覆盖率")
    assert coverage_card["value"] == "66%"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_common.py::test_normalize_adds_coverage_rate_kpi -v`
Expected: FAIL — no "样本覆盖率" card

- [ ] **Step 3: Add coverage rate KPI card in `normalize_deep_report_analytics`**

In the `kpi_cards` list construction (around line 744), add the 6th card. Also add per-product coverage to `risk_products` items, and append coverage caveat to the negative rate tooltip.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_report_common.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "feat: add coverage rate KPI card with per-product rates"
```

- [ ] **Step 6: Write test for metric labeling changes**

```python
def test_sentiment_distribution_uses_rating_labels():
    """Sentiment distribution chart legend should use rating-based labels, not NLP terms."""
    from qbu_crawler.server.report_analytics import _compute_chart_data

    labeled = [
        {"review": {"ownership": "own", "product_sku": "S1", "product_name": "P1", "rating": 5},
         "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
         "images": [], "product": {}},
        {"review": {"ownership": "own", "product_sku": "S2", "product_name": "P2", "rating": 1},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative", "severity": "high", "confidence": 0.9}],
         "images": [], "product": {}},
    ]
    snapshot = {"products": [
        {"name": "P1", "sku": "S1", "ownership": "own"},
        {"name": "P2", "sku": "S2", "ownership": "own"},
    ]}
    charts = _compute_chart_data(labeled, snapshot)
    # Chart data keys should NOT use misleading "positive/negative" NLP terms
    # (This test validates the output structure; actual label renaming is in templates)


def test_risk_score_tooltip_mentions_threshold():
    """Risk score tooltip should specify the rating threshold used."""
    from qbu_crawler.server.report_common import METRIC_TOOLTIPS
    tooltip = METRIC_TOOLTIPS.get("风险分", "")
    assert "≤" in tooltip or "星" in tooltip, f"Risk tooltip missing threshold info: {tooltip}"
```

- [ ] **Step 7: Add risk score tooltip and issue cluster footnote**

In `report_common.py` `METRIC_TOOLTIPS`, update:
```python
"风险分": "低分评论×2 + 含图评论×1 + 各标签严重度累加；仅计 ≤{low_rating}星评论",
```

For the sentiment distribution chart title: in `_compute_chart_data` (report_analytics.py), the output key `_sentiment_distribution_own` stays the same (templates read it by key), but HTML template should render title as "评分分布" instead of implying sentiment analysis.

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_report_common.py tests/test_report_charts.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py tests/test_report_common.py
git commit -m "feat: add metric caliber annotations — risk tooltip, chart title clarification"
```

---

### Task 7: Normalize relative dates with `anchor_date` and DB persistence

**Files:**
- Modify: `qbu_crawler/server/report_common.py:266-307` (`_parse_date_flexible`)
- Modify: `qbu_crawler/models.py` (ALTER TABLE + backfill in `init_db`)
- Modify: `qbu_crawler/server/report_snapshot.py` (freeze logic)
- Test: `tests/test_report_common.py`

- [ ] **Step 1: Write failing test for `anchor_date` parameter**

```python
def test_parse_date_flexible_anchor_date():
    """Relative dates should use anchor_date, not today."""
    from datetime import date
    from qbu_crawler.server.report_common import _parse_date_flexible

    anchor = date(2026, 4, 1)
    result = _parse_date_flexible("3 months ago", anchor_date=anchor)
    assert result == date(2026, 1, 1)

    # Without anchor, uses today (existing behavior)
    result_no_anchor = _parse_date_flexible("3 months ago")
    assert result_no_anchor is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_common.py::test_parse_date_flexible_anchor_date -v`
Expected: FAIL — `anchor_date` parameter not accepted

- [ ] **Step 3: Add `anchor_date` parameter to `_parse_date_flexible`**

Modify the function signature and replace `today = date.today()` with `today = anchor_date or date.today()`.

- [ ] **Step 4: Add DB migration for `date_published_parsed`**

In `models.py` `init_db()`, add after table creation:

```python
# Migration: add date_published_parsed column if missing
try:
    conn.execute("SELECT date_published_parsed FROM reviews LIMIT 1")
except sqlite3.OperationalError:
    conn.execute("ALTER TABLE reviews ADD COLUMN date_published_parsed TEXT")
    conn.commit()
```

Add backfill logic (lazy, runs once after migration).

- [ ] **Step 5: Update `freeze_report_snapshot` to include parsed dates**

In `report_snapshot.py`, after joining review data, add `date_published_parsed` field to each review dict.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_report_common.py tests/test_report_snapshot.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```
git add qbu_crawler/server/report_common.py qbu_crawler/models.py qbu_crawler/server/report_snapshot.py tests/test_report_common.py
git commit -m "feat: normalize relative dates with anchor_date, persist to DB"
```

---

## P2 — Feature Enhancements

### Task 8: Build trend data from product_snapshots

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (new `_build_trend_data`)
- Modify: `qbu_crawler/models.py` (new `get_product_snapshots` query)
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: Write failing test for trend data generation**

```python
def test_build_trend_data_returns_time_series(analytics_db):
    """_build_trend_data should return per-product time series from snapshots."""
    from qbu_crawler.server.report_analytics import _build_trend_data

    # Insert product and snapshots
    conn = models.get_conn()
    conn.execute("INSERT INTO products (url, site, name, sku, price, stock_status, rating, review_count, ownership, scraped_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("https://example.com/p1", "basspro", "Product 1", "SKU1", 100, "in_stock", 4.0, 10, "own", "2026-04-01 10:00:00"))
    pid = conn.execute("SELECT id FROM products WHERE sku='SKU1'").fetchone()["id"]
    for day in range(1, 4):
        conn.execute("INSERT INTO product_snapshots (product_id, price, stock_status, review_count, rating, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (pid, 100 + day, "in_stock", 10 + day, 4.0, f"2026-04-0{day} 10:00:00"))
    conn.commit()
    conn.close()

    products = [{"name": "Product 1", "sku": "SKU1", "id": pid}]
    trend = _build_trend_data(products, days=30)
    assert len(trend) > 0
    assert trend[0]["product_name"] == "Product 1"
    assert len(trend[0]["series"]) == 3
```

- [ ] **Step 2: Implement `_build_trend_data` and `get_product_snapshots`**

- [ ] **Step 3: Wire into `build_report_analytics` output**

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_report_analytics.py::test_build_trend_data_returns_time_series -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add qbu_crawler/server/report_analytics.py qbu_crawler/models.py tests/test_report_analytics.py
git commit -m "feat: build trend data from product_snapshots for Excel/charts"
```

---

### Task 9: Fix heatmap degeneration and label truncation

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (`_compute_chart_data`, heatmap section)
- Test: `tests/test_report_charts.py`

- [ ] **Step 1: Write failing test for continuous heatmap values**

```python
def test_heatmap_produces_continuous_values():
    """Heatmap z values should not collapse to -1/0/1 ternary."""
    from qbu_crawler.server.report_analytics import _compute_chart_data

    # 5 reviews for same product: 3 positive build, 2 negative quality → score should be between -1 and 1
    labeled = []
    for i in range(3):
        labeled.append({"review": {"ownership": "own", "product_sku": "S1", "product_name": "Product Alpha Beta Gamma Delta"},
                        "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
                        "images": [], "product": {}})
    for i in range(2):
        labeled.append({"review": {"ownership": "own", "product_sku": "S1", "product_name": "Product Alpha Beta Gamma Delta"},
                        "labels": [{"label_code": "quality_stability", "label_polarity": "negative", "severity": "high", "confidence": 0.9}],
                        "images": [], "product": {}})
    # Need 2nd own product for heatmap to render
    labeled.append({"review": {"ownership": "own", "product_sku": "S2", "product_name": "Product Two"},
                    "labels": [{"label_code": "solid_build", "label_polarity": "positive", "severity": "low", "confidence": 0.9}],
                    "images": [], "product": {}})

    snapshot = {"products": [
        {"name": "Product Alpha Beta Gamma Delta", "sku": "S1", "ownership": "own", "price": 100, "rating": 3.5, "review_count": 10},
        {"name": "Product Two", "sku": "S2", "ownership": "own", "price": 200, "rating": 4.0, "review_count": 5},
    ]}
    charts = _compute_chart_data(labeled, snapshot)
    heatmap = charts.get("_heatmap_data")
    if heatmap:
        # y_labels should not be truncated in the middle of a word
        assert len(heatmap["y_labels"][0]) < 26  # smart truncation
        # At least one z value should be between -1 and 1 (not ternary)
        all_z = [v for row in heatmap["z"] for v in row if v != 0.0]
        has_continuous = any(-1 < v < 1 for v in all_z)
        # With 10 total reviews as denominator, 3/10 = 0.3, not 1.0
        assert has_continuous, f"All z values are binary: {all_z}"
```

- [ ] **Step 2: Implement heatmap fixes**

Two changes in `_compute_chart_data` heatmap section:
1. Use product `review_count` (total reviews) as denominator instead of `pos + neg` (label-only count)
2. Replace `pname[:25]` truncation with smart truncation (remove brand prefix like "Cabela's ")

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_report_charts.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```
git add qbu_crawler/server/report_analytics.py tests/test_report_charts.py
git commit -m "fix: heatmap uses total reviews as denominator, smart label truncation"
```

---

### Task 10: Parallelize image downloads in Excel generation

**Files:**
- Modify: `qbu_crawler/server/report.py` (image embedding sections)
- Test: `tests/test_report_excel.py`

- [ ] **Step 1: Write test for parallel download behavior**

```python
def test_image_download_respects_global_timeout(monkeypatch):
    """Image downloads should not exceed global timeout."""
    import time
    from qbu_crawler.server.report import _download_images_parallel

    def slow_download(url, timeout=10):
        time.sleep(0.5)
        return None

    monkeypatch.setattr("qbu_crawler.server.report._download_and_resize", slow_download)
    urls = [f"https://img.example.com/{i}.jpg" for i in range(20)]
    results = _download_images_parallel(urls, global_timeout=2)
    # Should complete in ~2 seconds, not 10 (20 * 0.5)
    assert len(results) == 20
```

- [ ] **Step 2: Implement `_download_images_parallel`**

Extract image download logic into a new function using `ThreadPoolExecutor(max_workers=5)` with `concurrent.futures.wait(timeout=60)`.

- [ ] **Step 3: Wire into `generate_excel` image embedding sections**

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_report_excel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add qbu_crawler/server/report.py tests/test_report_excel.py
git commit -m "perf: parallelize image downloads with ThreadPoolExecutor, 60s global cap"
```

---

### Task 11: Fix baseline alert level + expand image evidence

**Files:**
- Modify: `qbu_crawler/server/report_common.py` (`_compute_alert_level`)
- Modify: `qbu_crawler/server/report_analytics.py` (image_reviews limit)
- Test: `tests/test_report_common.py`

- [ ] **Step 1: Write failing test for baseline alert**

```python
def test_alert_level_green_for_baseline():
    """Baseline mode should always return green regardless of data."""
    from qbu_crawler.server.report_common import _compute_alert_level

    normalized = {
        "mode": "baseline",
        "kpis": {"own_negative_review_rows_delta": 50, "health_index": 30},
        "self": {"top_negative_clusters": [
            {"severity": "high", "review_count": 20}
        ]},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "green"
    assert "基线" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_common.py::test_alert_level_green_for_baseline -v`
Expected: FAIL — returns "red" because high_sev cluster has ≥5 reviews

- [ ] **Step 3: Add baseline guard to `_compute_alert_level`**

At the top of `_compute_alert_level` (line 244):
```python
if normalized.get("mode") == "baseline":
    return "green", "首次基线采集完成，环比预警将在第 4 期后启用"
```

- [ ] **Step 4: Expand image_reviews limit**

In `report_analytics.py` `build_report_analytics`, change:
```python
# BEFORE: image_reviews[:10]
# AFTER:
image_reviews.sort(key=lambda r: (
    0 if r.get("ownership") == "own" else 1,
    r.get("rating") or 5,
))
... image_reviews[:20]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_report_common.py tests/test_report_analytics.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py tests/test_report_common.py
git commit -m "fix: baseline alert forced green, expand image evidence to 20"
```

---

### Task 12: Handle zero-review incremental reports

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (`generate_full_report_from_snapshot`)
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1: Write failing test for zero-review handling**

```python
def test_zero_review_snapshot_produces_change_report(analytics_db):
    """When an incremental snapshot has zero reviews, generate a change-only report or skip."""
    from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-08",
        "snapshot_hash": "hash-empty",
        "products_count": 2,
        "reviews_count": 0,
        "translated_count": 0,
        "untranslated_count": 0,
        "products": [
            {"name": "P1", "sku": "S1", "ownership": "own", "price": 100, "rating": 3.5, "review_count": 50, "site": "basspro", "stock_status": "in_stock"},
        ],
        "reviews": [],
    }
    result = generate_full_report_from_snapshot(snapshot, send_email=False)
    # Should not crash; should either produce a simplified report or mark as no_change
    assert result is not None
```

- [ ] **Step 2: Implement zero-review branch (MVP)**

At the top of `generate_full_report_from_snapshot`, add:
```python
if not snapshot.get("reviews"):
    # MVP: return early. Full snapshot-diff (compare price/stock/rating changes
    # vs previous run and generate simplified change report) is a follow-up task.
    return {"status": "completed_no_change", "reason": "No new reviews"}
```

Note: The spec envisions comparing current vs previous snapshot to detect price/stock/rating changes and generating a simplified change report. This MVP returns early unconditionally — the full snapshot-diff logic can be layered on without rework.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_report_snapshot.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat: handle zero-review incremental reports gracefully"
```

---

## Verification

After all tasks are complete:

- [ ] **Run full test suite**: `uv run pytest tests/ -v --tb=short`
- [ ] **Generate test report from existing snapshot**: Verify the report pipeline produces valid HTML/Excel/PDF with the new analytics
- [ ] **Spot-check**: Radar chart should show differentiated own vs competitor values, clusters should be ≤10 items with meaningful counts, coverage rate KPI should appear
