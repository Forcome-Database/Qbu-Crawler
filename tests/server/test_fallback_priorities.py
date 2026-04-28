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


def test_fallback_priorities_are_user_readable_without_engineering_copy():
    risk_products = [{
        "product_name": ".5 HP Dual Grind Grinder (#8)",
        "top_labels": [{"code": "service_fulfillment", "count": 4}],
    }]

    out = build_fallback_priorities(risk_products, [])

    item = out[0]
    assert item["label_display"] == "售后与履约"
    assert item["short_title"] == "售后与履约"
    assert "service_fulfillment" not in item["short_title"]
    assert "规则降级" not in item["full_action"]
    assert "LLM" not in item["full_action"]
    assert "附件 HTML" not in item["full_action"]


def test_fallback_priorities_are_distinct_by_label():
    issue_clusters = [
        {
            "label_code": "structure_design",
            "label_display": "结构设计",
            "review_count": 3,
            "affected_products": ["Product A"],
            "example_reviews": [{"id": 1, "body_cn": "出料口尺寸不合适"}],
        },
        {
            "label_code": "service_fulfillment",
            "label_display": "售后与履约",
            "review_count": 2,
            "affected_products": ["Product B"],
            "example_reviews": [{"id": 2, "body_cn": "发货迟迟没有回应"}],
        },
        {
            "label_code": "material_finish",
            "label_display": "材料与做工",
            "review_count": 4,
            "affected_products": ["Product C"],
            "example_reviews": [{"id": 3, "body_cn": "表面有明显毛刺"}],
        },
    ]

    out = build_fallback_priorities([], issue_clusters)

    actions = [item["full_action"] for item in out]
    assert len(set(actions)) == len(actions)


def test_fallback_priorities_bind_evidence_and_top_complaint():
    issue_clusters = [{
        "label_code": "quality_stability",
        "label_display": "质量稳定性",
        "review_count": 2,
        "affected_products": ["Product A"],
        "example_reviews": [
            {"id": 101, "headline_cn": "开关失效", "body_cn": "用了两次开关就坏了"},
            {"review_id": 102, "body_cn": "电机发热后停机"},
        ],
    }]

    out = build_fallback_priorities([], issue_clusters)

    item = out[0]
    assert item["source"] == "rule_fallback"
    assert item["evidence_review_ids"] == [101, 102]
    assert item["top_complaint"] == "开关失效：用了两次开关就坏了"
    assert item["affected_products"] == ["Product A"]


def test_fallback_priority_without_review_evidence_is_marked_insufficient():
    issue_clusters = [{
        "label_code": "assembly_installation",
        "label_display": "安装装配",
        "review_count": 2,
        "affected_products": ["Product A"],
    }]

    out = build_fallback_priorities([], issue_clusters)

    item = out[0]
    assert item["source"] == "evidence_insufficient"
    assert item["evidence_review_ids"] == []
    assert "证据不足" in item["full_action"]
