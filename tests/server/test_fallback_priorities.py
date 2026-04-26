import pytest
from qbu_crawler.server.report_analytics import build_fallback_priorities


def test_uses_top_risk_product_label_first():
    risk_products = [{
        "product_name": ".75 HP",
        "top_labels": [{"code": "structure_design", "display": "结构设计", "count": 7}],
    }]
    out = build_fallback_priorities(risk_products, [])
    assert len(out) == 1
    item = out[0]
    assert item["label_code"] == "structure_design"
    assert item["short_title"]
    assert len(item["short_title"]) <= 20
    assert item["full_action"]
    assert len(item["full_action"]) >= 80
    assert item["evidence_count"] == 7
    assert item["evidence_review_ids"] == []
    assert item["affected_products"] == [".75 HP"]
    assert item["affected_products_count"] == 1


def test_dedupes_by_label_code_across_risk_products():
    risk_products = [
        {"product_name": "A", "top_labels": [{"code": "structure_design", "count": 5}]},
        {"product_name": "B", "top_labels": [{"code": "structure_design", "count": 3}]},
    ]
    out = build_fallback_priorities(risk_products, [])
    assert len(out) == 1
    assert out[0]["label_code"] == "structure_design"


def test_falls_back_to_issue_clusters_when_priorities_underfull():
    risk_products = [
        {"product_name": "A", "top_labels": [{"code": "structure_design", "count": 5}]},
    ]
    issue_clusters = [
        {"label_code": "noise", "label_display": "噪音", "review_count": 22,
         "affected_products": ["A", "B", "C", "D"]},
        {"label_code": "structure_design"},  # duplicate, must be skipped
        {"label_code": "motor_anomaly", "label_display": "电机", "review_count": 4},
    ]
    out = build_fallback_priorities(risk_products, issue_clusters, max_items=3)
    codes = [r["label_code"] for r in out]
    assert codes == ["structure_design", "noise", "motor_anomaly"]
    noise = next(r for r in out if r["label_code"] == "noise")
    assert noise["affected_products"] == ["A", "B", "C"]  # capped at 3
    assert noise["affected_products_count"] == 4


def test_returns_empty_when_no_input():
    assert build_fallback_priorities([], []) == []


def test_max_items_caps_output():
    risk_products = [
        {"product_name": f"P{i}", "top_labels": [{"code": f"c{i}", "count": 1}]}
        for i in range(5)
    ]
    out = build_fallback_priorities(risk_products, [], max_items=2)
    assert len(out) == 2


def test_short_title_truncated_when_too_long():
    risk_products = [{
        "product_name": "非常长的产品名称用于测试截断处理逻辑实际上会被裁剪",
        "top_labels": [{"code": "x", "display": "结构调节缺位"}],
    }]
    out = build_fallback_priorities(risk_products, [])
    assert len(out[0]["short_title"]) <= 20
