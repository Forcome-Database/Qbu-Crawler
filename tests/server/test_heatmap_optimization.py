"""F011 §4.2.6.2 v1.2 — 特征情感热力图优化（Top 8 维度聚合 + hover top 评论 + 点击下钻）.

Validates:
  - x_labels aggregated to ≤ HEATMAP_MAX_LABELS (= 8); overflow merged into "其他"
  - cells with sample_size ≥ HEATMAP_MIN_SAMPLE (= 3) carry top_review_id + excerpt
  - cells with sample_size < HEATMAP_MIN_SAMPLE rendered gray (score=None)
  - color_class derivation: green > 0.7 / yellow [0.4, 0.7] / red < 0.4 / gray < 3 samples
  - rendered HTML contains clickable .heatmap-cell with data-product / data-label

Tests call ``_compute_chart_data`` directly for unit-level shape assertions and
``render_attachment_html`` for the rendered-template integration check.
"""
from __future__ import annotations

import json
import re

import pytest

from qbu_crawler.server.report_analytics import _compute_chart_data
from qbu_crawler.server.report_html import render_attachment_html


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────
_OWN_PRODUCTS = [
    {"sku": f"OWN-{i}", "name": f"Own Product {i}", "ownership": "own", "rating": 4.0,
     "review_count": 50, "price": 199.99}
    for i in range(1, 4)
]


def _labeled(*, product_sku, product_name, label_codes, polarity, rating, review_id=None,
             body=None, body_cn=None):
    """Construct one labeled_reviews entry with given codes/polarity/rating."""
    return {
        "review": {
            "id": review_id,
            "ownership": "own",
            "product_sku": product_sku,
            "product_name": product_name,
            "rating": rating,
            "body": body or "Default review body text.",
            "body_cn": body_cn or "",
            "body_translated": "",
        },
        "labels": [
            {"label_code": code, "label_polarity": polarity, "severity": "low",
             "confidence": 0.9}
            for code in label_codes
        ],
        "images": [],
        "product": {},
    }


def _snapshot(products=None, reviews=None, logical_date="2026-04-27"):
    return {
        "run_id": 0,
        "logical_date": logical_date,
        "snapshot_hash": "test-hash",
        "products_count": len(products or []),
        "reviews_count": len(reviews or []),
        "translated_count": len(reviews or []),
        "untranslated_count": 0,
        "snapshot_at": f"{logical_date}T12:00:00+08:00",
        "data_since": f"{logical_date}T00:00:00+08:00",
        "data_until": f"{logical_date}T23:59:59+08:00",
        "products": products or [],
        "reviews": reviews or [],
    }


def _base_analytics(heatmap_data, label_options=None):
    """Minimum analytics dict with _heatmap_data injected for the rendering test."""
    return {
        "report_semantics": "incremental",
        "mode": "incremental",
        "kpis": {"health_index": 80, "ingested_review_rows": 0,
                 "own_review_rows": 0, "competitor_review_rows": 0,
                 "own_product_count": 0, "competitor_product_count": 0,
                 "own_negative_review_rows": 0, "negative_review_rows": 0,
                 "low_rating_review_rows": 0},
        "self": {"risk_products": [], "product_status": [],
                 "top_negative_clusters": [], "top_positive_clusters": [],
                 "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                       "negative_opportunities": [], "gap_analysis": []},
        "appendix": {"image_reviews": [], "coverage": {}},
        "change_digest": {},
        "label_options": label_options or [],
        "_heatmap_data": heatmap_data,
    }


# ──────────────────────────────────────────────────────────
# §4.2.6.2 — Step 1: Top-N label aggregation
# ──────────────────────────────────────────────────────────
def test_heatmap_x_labels_aggregated_to_top_8():
    """x_labels must be capped at HEATMAP_MAX_LABELS (= 8). Overflow merged into '其他'."""
    # 14 distinct labels; with min-sample=3 we need ≥3 reviews per (product, label) for non-gray.
    # Generate 3 reviews per label per product to ensure all cells have data.
    all_codes = [
        "quality_stability", "structure_design", "assembly_installation",
        "material_finish", "cleaning_maintenance", "noise_power",
        "packaging_shipping", "service_fulfillment", "easy_to_use",
        "solid_build", "good_value", "easy_to_clean",
        "strong_performance", "good_packaging",
    ]
    labeled = []
    review_id = 1
    for product in _OWN_PRODUCTS[:2]:  # two products needed to avoid skip
        for code in all_codes:
            for _ in range(3):
                labeled.append(_labeled(
                    product_sku=product["sku"],
                    product_name=product["name"],
                    label_codes=[code],
                    polarity="positive",
                    rating=5,
                    review_id=review_id,
                ))
                review_id += 1

    charts = _compute_chart_data(labeled, _snapshot(products=_OWN_PRODUCTS[:2]))
    heatmap = charts.get("_heatmap_data")
    assert heatmap is not None
    assert len(heatmap["x_labels"]) <= 8
    # Since we have 14 codes > 7, '其他' bucket should appear
    assert "其他" in heatmap["x_labels"]
    # aggregated_labels should list the codes folded into '其他'
    assert isinstance(heatmap.get("aggregated_labels"), list)
    assert len(heatmap["aggregated_labels"]) == 14 - (8 - 1)  # 14 - 7 = 7 codes in '其他'


def test_heatmap_no_other_bucket_when_few_labels():
    """When labels ≤ HEATMAP_MAX_LABELS-1, '其他' bucket is omitted."""
    codes = ["quality_stability", "structure_design", "easy_to_use"]
    labeled = []
    review_id = 1
    for product in _OWN_PRODUCTS[:2]:
        for code in codes:
            for _ in range(3):
                labeled.append(_labeled(
                    product_sku=product["sku"], product_name=product["name"],
                    label_codes=[code], polarity="positive", rating=5,
                    review_id=review_id,
                ))
                review_id += 1

    charts = _compute_chart_data(labeled, _snapshot(products=_OWN_PRODUCTS[:2]))
    heatmap = charts.get("_heatmap_data")
    assert heatmap is not None
    assert "其他" not in heatmap["x_labels"]
    assert heatmap.get("aggregated_labels", []) == []


# ──────────────────────────────────────────────────────────
# §4.2.6.2 — Step 2: Per-cell metadata (top review)
# ──────────────────────────────────────────────────────────
def test_heatmap_cell_has_top_review_excerpt():
    """Each non-gray cell carries top_review_id + excerpt (≤ 80 chars)."""
    long_body = "这是一条非常详细的中文评论，描述了产品的方方面面，" * 5  # >> 80 chars
    labeled = []
    review_id = 1
    for product in _OWN_PRODUCTS[:2]:
        for _ in range(4):  # ≥ HEATMAP_MIN_SAMPLE
            labeled.append(_labeled(
                product_sku=product["sku"], product_name=product["name"],
                label_codes=["quality_stability"], polarity="positive", rating=5,
                review_id=review_id, body_cn=long_body,
            ))
            review_id += 1
        for _ in range(4):
            labeled.append(_labeled(
                product_sku=product["sku"], product_name=product["name"],
                label_codes=["structure_design"], polarity="positive", rating=5,
                review_id=review_id, body_cn=long_body,
            ))
            review_id += 1

    charts = _compute_chart_data(labeled, _snapshot(products=_OWN_PRODUCTS[:2]))
    heatmap = charts.get("_heatmap_data")
    assert heatmap is not None

    found_with_excerpt = False
    for row in heatmap["z"]:
        for cell in row:
            assert isinstance(cell, dict), "z cells must be dicts (v1.2 shape)"
            if cell.get("sample_size", 0) >= 3:
                assert "top_review_id" in cell
                assert cell["top_review_id"] is not None
                assert "top_review_excerpt" in cell
                assert len(cell["top_review_excerpt"]) <= 80
                found_with_excerpt = True
    assert found_with_excerpt, "expected at least one non-gray cell with excerpt"


# ──────────────────────────────────────────────────────────
# §4.2.6.2 — Step 3: Low sample → gray
# ──────────────────────────────────────────────────────────
def test_heatmap_low_sample_marked_gray():
    """sample_size < 3 → score=None and color_class='gray'."""
    # Two products, two labels — only 1-2 reviews per cell.
    labeled = [
        _labeled(product_sku="OWN-1", product_name="Own Product 1",
                 label_codes=["quality_stability"], polarity="positive",
                 rating=5, review_id=1),
        _labeled(product_sku="OWN-1", product_name="Own Product 1",
                 label_codes=["structure_design"], polarity="negative",
                 rating=1, review_id=2),
        _labeled(product_sku="OWN-2", product_name="Own Product 2",
                 label_codes=["quality_stability"], polarity="positive",
                 rating=4, review_id=3),
    ]

    charts = _compute_chart_data(labeled, _snapshot(products=_OWN_PRODUCTS[:2]))
    heatmap = charts.get("_heatmap_data")
    assert heatmap is not None

    found_gray = False
    for row in heatmap["z"]:
        for cell in row:
            assert isinstance(cell, dict)
            if cell.get("sample_size", 0) < 3:
                assert cell.get("score") is None
                assert cell.get("color_class") == "gray"
                found_gray = True
    assert found_gray


# ──────────────────────────────────────────────────────────
# §4.2.6.2 — Step 4: Color thresholds
# ──────────────────────────────────────────────────────────
def test_heatmap_color_thresholds_green_yellow_red():
    """score > 0.7 → green; [0.4, 0.7] → yellow; < 0.4 → red."""
    labeled = []
    review_id = 1
    # Product 1 / quality_stability: 4 positive (rating 5), 1 negative (rating 1) → 4/5 = 0.8 → green
    for _ in range(4):
        labeled.append(_labeled(product_sku="OWN-1", product_name="Own Product 1",
                                label_codes=["quality_stability"], polarity="positive",
                                rating=5, review_id=review_id))
        review_id += 1
    labeled.append(_labeled(product_sku="OWN-1", product_name="Own Product 1",
                            label_codes=["quality_stability"], polarity="negative",
                            rating=1, review_id=review_id))
    review_id += 1

    # Product 1 / structure_design: 2 positive (rating 5), 3 neutral (rating 3) → positives=2/5 = 0.4 → yellow
    for _ in range(2):
        labeled.append(_labeled(product_sku="OWN-1", product_name="Own Product 1",
                                label_codes=["structure_design"], polarity="positive",
                                rating=5, review_id=review_id))
        review_id += 1
    for _ in range(3):
        labeled.append(_labeled(product_sku="OWN-1", product_name="Own Product 1",
                                label_codes=["structure_design"], polarity="positive",
                                rating=3, review_id=review_id))
        review_id += 1

    # Product 2 / quality_stability: 0 positive, 5 negative (rating 1) → 0.0 → red
    for _ in range(5):
        labeled.append(_labeled(product_sku="OWN-2", product_name="Own Product 2",
                                label_codes=["quality_stability"], polarity="negative",
                                rating=1, review_id=review_id))
        review_id += 1

    # Product 2 / structure_design: filler so the cell exists (≥3 of any kind)
    for _ in range(3):
        labeled.append(_labeled(product_sku="OWN-2", product_name="Own Product 2",
                                label_codes=["structure_design"], polarity="positive",
                                rating=5, review_id=review_id))
        review_id += 1

    charts = _compute_chart_data(labeled, _snapshot(products=_OWN_PRODUCTS[:2]))
    heatmap = charts.get("_heatmap_data")
    assert heatmap is not None

    by_label = dict(zip(heatmap["x_labels"], range(len(heatmap["x_labels"]))))
    by_product = dict(zip(heatmap["y_labels"], range(len(heatmap["y_labels"]))))

    # Find labels by display name
    from qbu_crawler.server.report_common import _LABEL_DISPLAY
    qs_label = _LABEL_DISPLAY["quality_stability"]
    sd_label = _LABEL_DISPLAY["structure_design"]

    # Resolve y row by partial match (smart truncation may shorten)
    def _row(name_part: str) -> int:
        for i, y in enumerate(heatmap["y_labels"]):
            if name_part in y:
                return i
        raise AssertionError(f"product row containing '{name_part}' not found in {heatmap['y_labels']}")

    p1 = _row("Product 1")
    p2 = _row("Product 2")

    cell_p1_qs = heatmap["z"][p1][by_label[qs_label]]
    cell_p1_sd = heatmap["z"][p1][by_label[sd_label]]
    cell_p2_qs = heatmap["z"][p2][by_label[qs_label]]

    assert cell_p1_qs["color_class"] == "green", cell_p1_qs
    assert cell_p1_sd["color_class"] == "yellow", cell_p1_sd
    assert cell_p2_qs["color_class"] == "red", cell_p2_qs


# ──────────────────────────────────────────────────────────
# §4.2.6.2 — Step 5: Rendered HTML has clickable cells
# ──────────────────────────────────────────────────────────
def test_heatmap_html_has_clickable_cells():
    """Rendered template emits <td class="heatmap-cell ..." data-product=".." data-label="..">."""
    # Build a minimal heatmap_data dict directly to bypass labeled-review plumbing.
    heatmap_data = {
        "x_labels": ["质量稳定性", "结构设计"],
        "x_label_codes": ["quality_stability", "structure_design"],
        "y_labels": ["Product 1", "Product 2"],
        "z": [
            [
                {"score": 0.8, "sample_size": 5, "color_class": "green",
                 "top_review_id": 100, "top_review_excerpt": "performance ok"},
                {"score": 0.5, "sample_size": 4, "color_class": "yellow",
                 "top_review_id": 101, "top_review_excerpt": "structure mediocre"},
            ],
            [
                {"score": None, "sample_size": 1, "color_class": "gray",
                 "top_review_id": None, "top_review_excerpt": "样本不足"},
                {"score": 0.2, "sample_size": 5, "color_class": "red",
                 "top_review_id": 102, "top_review_excerpt": "design flawed"},
            ],
        ],
        "aggregated_labels": [],
    }
    snapshot = _snapshot(products=_OWN_PRODUCTS[:2])
    analytics = _base_analytics(heatmap_data)

    html = render_attachment_html(snapshot, analytics)

    # Cells with data-product + data-label
    cells = re.findall(
        r'<td[^>]*class="[^"]*heatmap-cell[^"]*"[^>]*data-product="([^"]+)"[^>]*data-label="([^"]+)"',
        html,
    )
    assert len(cells) >= 4, f"expected ≥4 heatmap cells, found {len(cells)}"

    # Legend present
    assert "heatmap-legend" in html
    assert "混合=正负并存" in html
    # color classes present
    assert "heatmap-cell green" in html
    assert "heatmap-cell yellow" in html
    assert "heatmap-cell red" in html
    assert "heatmap-cell gray" in html


def test_heatmap_html_emits_label_codes_for_drilldown():
    """data-label-code attribute enables JS drill-down to apply panorama label filter."""
    heatmap_data = {
        "x_labels": ["质量稳定性", "其他"],
        "x_label_codes": ["quality_stability", ""],
        "y_labels": ["Product 1"],
        "z": [
            [
                {"score": 0.8, "sample_size": 5, "color_class": "green",
                 "top_review_id": 100, "top_review_excerpt": "ok"},
                {"score": None, "sample_size": 0, "color_class": "gray",
                 "top_review_id": None, "top_review_excerpt": "无样本"},
            ],
        ],
        "aggregated_labels": ["service_fulfillment"],
    }
    snapshot = _snapshot(products=_OWN_PRODUCTS[:1])
    analytics = _base_analytics(heatmap_data)

    html = render_attachment_html(snapshot, analytics)
    assert 'data-label-code="quality_stability"' in html
    # '其他' bucket emits empty data-label-code
    assert 'data-label-code=""' in html


def test_panorama_rows_do_not_use_star_rating_data_attribute():
    snapshot = _snapshot(
        products=_OWN_PRODUCTS[:1],
        reviews=[
            {
                "id": 1,
                "ownership": "own",
                "product_name": "Own Product 1",
                "product_sku": "OWN-1",
                "rating": 5,
                "headline": "Great",
                "body": "Works well",
                "analysis_labels": '[{"code":"quality_stability"}]',
            }
        ],
    )
    analytics = _base_analytics({"x_labels": [], "x_label_codes": [], "y_labels": [], "z": []})

    html = render_attachment_html(snapshot, analytics)

    row_start = html.index('id="review-1"')
    row_end = html.index(">", row_start)
    row_tag = html[row_start:row_end]
    assert "data-rating=" not in row_tag
    assert 'data-rating-value="5"' in row_tag
    assert '<span class="star-rating" data-rating="5">' in html


def test_heatmap_drilldown_has_product_filter_contract():
    heatmap_data = {
        "x_labels": ["质量稳定性"],
        "x_label_codes": ["quality_stability"],
        "y_labels": ["Product 1"],
        "z": [[{"score": 0.8, "sample_size": 5, "color_class": "green",
                 "top_review_id": 100, "top_review_excerpt": "ok"}]],
        "aggregated_labels": [],
    }
    snapshot = _snapshot(products=_OWN_PRODUCTS[:1])
    analytics = _base_analytics(
        heatmap_data,
        label_options=[{"code": "quality_stability", "display": "质量稳定性"}],
    )

    html = render_attachment_html(snapshot, analytics)

    # name="product" is what the JS filter looks up; it now also carries an id.
    assert 'name="product"' in html
    assert "product: prodEl ? prodEl.value : ''" in html
    assert "if (f.product && d.product !== f.product) return false;" in html
    assert "productSelect.value = product" in html


def test_heatmap_cell_uses_full_product_name_for_drilldown_and_short_label_for_display():
    heatmap_data = {
        "x_labels": ["结构设计"],
        "x_label_codes": ["structure_design"],
        "y_labels": ["Walton's Quick Patty"],
        "y_items": [{
            "product_name": "Walton's Quick Patty Maker",
            "display_label": "Walton's Quick Patty",
        }],
        "z": [[{"score": 0.8, "sample_size": 5, "color_class": "green",
                 "top_review_id": 100, "top_review_excerpt": "ok"}]],
        "aggregated_labels": [],
    }
    snapshot = _snapshot(products=[{
        "sku": "WQP",
        "name": "Walton's Quick Patty Maker",
        "ownership": "own",
    }])
    analytics = _base_analytics(heatmap_data)

    html = render_attachment_html(snapshot, analytics)

    assert "Walton&#39;s Quick Patty</th>" in html or "Walton's Quick Patty</th>" in html
    assert (
        'data-product="Walton&#39;s Quick Patty Maker"' in html
        or 'data-product="Walton\'s Quick Patty Maker"' in html
    )


# ──────────────────────────────────────────────────────────
# §4.2.6.2 — Step 6: Sentiment-vs-rating classification (I-2 regression)
# ──────────────────────────────────────────────────────────
def test_heatmap_classifies_positive_using_sentiment_when_present():
    """Explicit `sentiment` from translator overrides rating-based fallback.

    Reviews with `rating=2` would normally count as non-positive via the rating
    fallback. With `sentiment="positive"` from the LLM translator, they MUST
    flip to positive — proving the sentiment branch fires.
    """
    from qbu_crawler.server.report_analytics import _classify_review_positive

    # 4 of 5 reviews: low rating but explicit positive sentiment → positives wins
    cell_reviews = [
        {"rating": 2, "sentiment": "positive"},
        {"rating": 2, "sentiment": "positive"},
        {"rating": 2, "sentiment": "positive"},
        {"rating": 2, "sentiment": "mixed"},
        {"rating": 5, "sentiment": "negative"},  # high rating but LLM said negative
    ]

    classifications = [_classify_review_positive(r) for r in cell_reviews]
    # 4 positives (3 "positive" + 1 "mixed"), the rating=5 with negative sentiment
    # MUST NOT be counted (LLM verdict overrides star rating).
    assert classifications == [True, True, True, True, False]


def test_heatmap_classifies_positive_using_rating_when_sentiment_absent():
    """When `sentiment` is missing/empty, fall back to rating >= 4 = positive."""
    from qbu_crawler.server.report_analytics import _classify_review_positive

    cell_reviews = [
        {"rating": 5},                       # no sentiment key → rating >= 4 → positive
        {"rating": 4, "sentiment": ""},      # empty sentiment → rating >= 4 → positive
        {"rating": 3, "sentiment": None},    # None sentiment → rating < 4 → not positive
        {"rating": 1},                       # no sentiment, low rating → not positive
        {"sentiment": ""},                   # neither → not positive
    ]

    classifications = [_classify_review_positive(r) for r in cell_reviews]
    assert classifications == [True, True, False, False, False]


def test_heatmap_cell_scores_mixed_as_half_weight_and_explains_counts():
    from qbu_crawler.server.report_analytics import _build_heatmap_cell

    cell = _build_heatmap_cell([
        {"id": 1, "rating": 5, "sentiment": "positive", "body_cn": "稳定好用"},
        {"id": 2, "rating": 5, "sentiment": "mixed", "body_cn": "有小问题但还可以"},
        {"id": 3, "rating": 1, "sentiment": "negative", "body_cn": "完全不能用"},
    ])

    assert cell["positive_count"] == 1
    assert cell["mixed_count"] == 1
    assert cell["negative_count"] == 1
    assert cell["neutral_count"] == 0
    assert cell["score"] == pytest.approx(0.5)
    assert cell["color_class"] == "yellow"
    assert "正向 1" in cell["tooltip"]
    assert "混合 1" in cell["tooltip"]
    assert "混合=正负并存" in cell["tooltip"]
    assert "负向 1" in cell["tooltip"]
    assert cell["top_review_id"] == 2
