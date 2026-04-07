"""Tests for server/report_common.py — shared constants and helpers."""

import pytest
from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _SEVERITY_DISPLAY,
    _PRIORITY_DISPLAY,
    _label_display,
    _summary_text,
    normalize_deep_report_analytics,
)


def test_label_display_known_code():
    assert _label_display("quality_stability") == "质量稳定性"


def test_label_display_unknown_code():
    assert _label_display("unknown_xyz") == "unknown_xyz"


def test_summary_text_cn_preferred():
    review = {"headline_cn": "标题", "body_cn": "内容", "headline": "Title", "body": "Content"}
    result = _summary_text(review)
    assert "标题" in result
    assert "内容" in result


def test_normalize_handles_none():
    result = normalize_deep_report_analytics(None)
    assert result["kpis"]["product_count"] == 0
    assert result["mode"] == "baseline"


def test_normalize_computes_rates():
    analytics = {"kpis": {"ingested_review_rows": 100, "negative_review_rows": 10, "translated_count": 90}}
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["negative_review_rate_display"] == "10.0%"
    assert result["kpis"]["translation_completion_rate_display"] == "90.0%"


def test_issue_cards_complete_fields():
    """issue_cards must carry all fields required by the P3 template."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "logical_date": "2026-04-07",
        "mode": "baseline",
        "snapshot_hash": "abc",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "review_count": 3,
                    "severity": "high",
                    "affected_product_count": 1,
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-04-01",
                    "image_review_count": 1,
                    "example_reviews": [
                        {"product_name": "P", "rating": 1, "headline": "bad",
                         "headline_cn": "差", "body": "broke", "body_cn": "坏了",
                         "images": ["https://example.com/img1.jpg"],
                         "author": "A", "date_published": "2026-01-01"}
                    ],
                }
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {
            "improvement_priorities": [
                {"rank": 1, "target": "P", "issue": "手柄松动", "action": "加强出厂耐久测试", "evidence_count": 3}
            ]
        },
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert card["first_seen"] == "2026-01-01"
    assert card["last_seen"] == "2026-04-01"
    assert card["duration_display"] is not None
    assert "月" in card["duration_display"] or "天" in card["duration_display"]
    assert len(card["example_reviews"]) == 1
    assert len(card["image_evidence"]) == 1
    assert card["image_evidence"][0]["url"] == "https://example.com/img1.jpg"
    assert card["image_evidence"][0]["evidence_id"] == "I1"
    assert card["image_evidence"][0]["data_uri"] is None  # data_uri is None pre-render (render_report_html converts it)
    assert card["recommendation"] == "加强出厂耐久测试"


# ---------------------------------------------------------------------------
# Tests for _cluster_summary_items and _risk_products (report_analytics)
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_analytics import _cluster_summary_items, _risk_products


def _make_labeled_review(ownership, polarity, label_code, severity="medium",
                         product_sku="SKU-1", product_name="Product A",
                         date_published="2026-03-01", headline="Title", body="Body",
                         headline_cn="标题", body_cn="正文", images=None):
    return {
        "review": {
            "ownership": ownership, "product_sku": product_sku,
            "product_name": product_name, "date_published": date_published,
            "headline": headline, "body": body,
            "headline_cn": headline_cn, "body_cn": body_cn,
        },
        "labels": [{"label_code": label_code, "label_polarity": polarity, "severity": severity, "confidence": 0.9}],
        "images": images or [],
    }


def test_cluster_has_affected_product_count():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="B"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["affected_product_count"] == 2


def test_cluster_has_timeline():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-02-14"),
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-03-29"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] == "2026-02-14"
    assert items[0]["last_seen"] == "2026-03-29"


def test_cluster_example_has_en_and_date():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             headline="Broke!", body="Support beam snapped",
                             date_published="2026-03-12"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    ex = items[0]["example_reviews"][0]
    assert ex["headline_en"] == "Broke!"
    assert ex["body_en"] == "Support beam snapped"
    assert ex["date_published"] == "2026-03-12"


def test_cluster_no_dates():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published=""),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] is None
    assert items[0]["last_seen"] is None


def test_risk_products_has_total_reviews():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    items = _risk_products(reviews, snapshot_products=[
        {"sku": "SKU-1", "review_count": 50},
    ])
    assert items[0]["total_reviews"] == 50


def test_risk_products_no_snapshot():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    items = _risk_products(reviews)
    assert items[0]["total_reviews"] == 0


# ---------------------------------------------------------------------------
# Tests for _competitor_gap_analysis and _compute_kpi_deltas
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_common import (
    _competitor_gap_analysis,
    _compute_kpi_deltas,
)


def test_competitor_gap_analysis_finds_intersection():
    normalized = {
        "self": {"top_negative_clusters": [
            {"label_code": "quality_stability", "review_count": 13},
            {"label_code": "material_finish", "review_count": 7},
        ]},
        "competitor": {"top_positive_themes": [
            {"label_code": "solid_build", "review_count": 69},
            {"label_code": "quality_stability", "review_count": 5},
        ]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    assert gaps[0]["label_code"] == "quality_stability"
    assert gaps[0]["competitor_positive_count"] == 5
    assert gaps[0]["own_negative_count"] == 13


def test_competitor_gap_analysis_empty():
    normalized = {
        "self": {"top_negative_clusters": [{"label_code": "material_finish", "review_count": 7}]},
        "competitor": {"top_positive_themes": [{"label_code": "solid_build", "review_count": 69}]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 0


def test_compute_kpi_deltas_normal():
    current = {"negative_review_rows": 78, "ingested_review_rows": 636, "product_count": 9}
    prev = {"kpis": {"negative_review_rows": 66, "ingested_review_rows": 500, "product_count": 9}}
    deltas = _compute_kpi_deltas(current, prev)
    assert deltas["negative_review_rows_delta"] == 12
    assert deltas["negative_review_rows_delta_display"] == "+12"
    assert deltas["product_count_delta"] == 0
    assert deltas["product_count_delta_display"] == "—"


def test_compute_kpi_deltas_no_prev():
    deltas = _compute_kpi_deltas({"negative_review_rows": 78}, None)
    assert deltas == {}


def test_compute_kpi_deltas_missing_field():
    deltas = _compute_kpi_deltas({"negative_review_rows": 10}, {"kpis": {}})
    assert deltas["negative_review_rows_delta"] == 10


# ---------------------------------------------------------------------------
# Tests for _generate_hero_headline, _compute_alert_level, _humanize_bullets
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_common import (
    _generate_hero_headline,
    _compute_alert_level,
    _humanize_bullets,
)


def test_hero_headline_with_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Cabela's Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 14}]}],
                 "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
        "kpis": {"negative_review_rows_delta": 12},
    }
    result = _generate_hero_headline(normalized)
    assert "环比" in result
    assert "Cabela's Stuffer" in result
    assert "质量稳定性" in result


def test_hero_headline_no_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability"}]}]},
        "competitor": {"top_positive_themes": []},
        "kpis": {},
    }
    result = _generate_hero_headline(normalized)
    assert "36%" in result  # 18/50


def test_hero_headline_no_risk():
    normalized = {"self": {"risk_products": []}, "competitor": {"top_positive_themes": []}, "kpis": {}}
    result = _generate_hero_headline(normalized)
    assert "样本不足" in result


def test_alert_level_red():
    normalized = {
        "self": {"top_negative_clusters": [{"severity": "high", "review_count": 10}]},
        "kpis": {"negative_review_rows_delta": 0},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "red"


def test_alert_level_yellow():
    normalized = {
        "self": {"top_negative_clusters": [{"severity": "medium", "review_count": 3}]},
        "kpis": {"negative_review_rows_delta": 5},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "yellow"


def test_alert_level_green():
    normalized = {"self": {"top_negative_clusters": []}, "kpis": {"negative_review_rows_delta": 0}}
    level, _ = _compute_alert_level(normalized)
    assert level == "green"


def test_humanize_bullets_with_rate_and_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability"}]}]},
        "competitor": {"top_positive_themes": [{"label_display": "做工扎实", "review_count": 69, "label_code": "solid_build"}],
                       "gap_analysis": []},
        "kpis": {"product_count": 9, "ingested_review_rows": 636, "untranslated_count": 0,
                 "negative_review_rows_delta": 5, "translation_completion_rate": 1.0},
    }
    bullets = _humanize_bullets(normalized)
    assert len(bullets) == 3
    assert "36%" in bullets[0]
    assert "新增 5 条" in bullets[0]


def test_humanize_bullets_low_translation():
    normalized = {
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "gap_analysis": []},
        "kpis": {"product_count": 5, "ingested_review_rows": 100,
                 "untranslated_count": 40, "translation_completion_rate": 0.6},
    }
    bullets = _humanize_bullets(normalized)
    assert any("翻译未完成" in b for b in bullets)


# ---------------------------------------------------------------------------
# Tests for compute_health_index and compute_competitive_gap_index
# ---------------------------------------------------------------------------

from qbu_crawler.server import report_common


def test_compute_health_index_perfect():
    analytics = {
        "kpis": {"own_avg_rating": 5.0, "negative_review_rate": 0, "own_product_count": 3},
        "self": {"risk_products": []},
    }
    assert report_common.compute_health_index(analytics) == 100.0


def test_compute_health_index_worst():
    from qbu_crawler import config
    analytics = {
        "kpis": {"own_avg_rating": 1.0, "negative_review_rate": 1.0, "own_product_count": 1},
        "self": {"risk_products": [{"risk_score": config.HIGH_RISK_THRESHOLD + 1}]},
    }
    assert report_common.compute_health_index(analytics) == 8.0  # 0.2*40 + 0*35 + 0*25 = 8


def test_compute_competitive_gap_index():
    gaps = [
        {"competitor_positive_count": 10, "own_negative_count": 5},
        {"competitor_positive_count": 8, "own_negative_count": 3},
    ]
    assert report_common.compute_competitive_gap_index(gaps) == 26


def test_compute_competitive_gap_index_empty():
    assert report_common.compute_competitive_gap_index([]) == 0


# ---------------------------------------------------------------------------
# Tests for normalize injecting health_index, kpi_cards, issue_cards
# ---------------------------------------------------------------------------


def test_normalize_injects_health_index():
    analytics = {
        "kpis": {
            "ingested_review_rows": 100,
            "negative_review_rows": 10,
            "translated_count": 90,
            "own_product_count": 2,
            "own_avg_rating": 4.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "health_index" in result["kpis"]
    assert isinstance(result["kpis"]["health_index"], float)
    assert result["kpis"]["health_index"] > 0


def test_normalize_injects_kpi_cards():
    analytics = {
        "kpis": {"ingested_review_rows": 50, "negative_review_rows": 5, "translated_count": 50},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "kpi_cards" in result
    assert len(result["kpi_cards"]) == 5
    labels = [c["label"] for c in result["kpi_cards"]]
    assert "健康指数" in labels
    assert "竞品差距指数" in labels


def test_normalize_injects_issue_cards():
    analytics = {
        "kpis": {"ingested_review_rows": 10, "translated_count": 10},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {"label_code": "quality_stability", "severity": "high", "review_count": 5, "example_reviews": []},
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "issue_cards" in result["self"]
    assert result["self"]["issue_cards"][0]["label_display"] == "质量稳定性"


def test_alert_level_red_on_low_health(monkeypatch):
    from qbu_crawler import config as _config
    monkeypatch.setattr(_config, "HEALTH_RED", 60)
    normalized = {
        "self": {"top_negative_clusters": []},
        "kpis": {"negative_review_rows_delta": 0, "health_index": 50},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "red"
    assert "健康指数" in text


def test_alert_level_yellow_on_moderate_health(monkeypatch):
    from qbu_crawler import config as _config
    monkeypatch.setattr(_config, "HEALTH_YELLOW", 80)
    monkeypatch.setattr(_config, "HEALTH_RED", 60)
    normalized = {
        "self": {"top_negative_clusters": []},
        "kpis": {"negative_review_rows_delta": 0, "health_index": 70},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "yellow"
    assert "健康指数" in text


# ---------------------------------------------------------------------------
# Tests for _risk_products rating_avg / negative_rate / top_features_display
# ---------------------------------------------------------------------------


def test_risk_products_has_rating_avg_and_negative_rate():
    """_risk_products via normalize returns rating_avg, negative_rate, top_features_display."""
    from qbu_crawler.server.report_analytics import _risk_products
    labeled_reviews = [
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 1},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                        "severity": "high", "confidence": 0.9}],
            "images": [],
        },
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 5},
            "labels": [],
            "images": [],
        },
    ]
    snapshot_products = [{"sku": "SKU1", "rating": 3.5, "review_count": 20}]
    result = _risk_products(labeled_reviews, snapshot_products=snapshot_products)
    assert len(result) == 1
    p = result[0]
    assert p["rating_avg"] == 3.5          # from snapshot_products
    assert p["negative_rate"] == pytest.approx(1 / 20)  # 1 negative / 20 site total
    assert "top_features_display" in p


def test_gap_analysis_has_gap_and_priority_display():
    """Gap analysis items must include 'gap' and 'priority_display'."""
    normalized = {
        "competitor": {
            "top_positive_themes": [
                {"label_code": "solid_build", "review_count": 10}
            ]
        },
        "self": {
            "top_negative_clusters": [
                {"label_code": "solid_build", "review_count": 6, "severity": "high"}
            ]
        },
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    g = gaps[0]
    assert "gap" in g
    assert "priority_display" in g
    assert g["gap"] == 10 - 6    # 4
    assert g["priority_display"] in ("高", "中", "低")
