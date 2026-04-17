import json
from scripts.simulate_reports.data_builder import expand_labels_rows


def test_expand_labels_basic():
    review_analysis_rows = [
        {"review_id": 1, "labels": json.dumps([
            {"code": "quality_stability", "polarity": "negative",
             "severity": "medium", "confidence": 0.85}
        ])},
        {"review_id": 2, "labels": json.dumps([
            {"code": "shipping", "polarity": "negative", "severity": "low", "confidence": 0.6},
            {"code": "price", "polarity": "positive", "severity": "low", "confidence": 0.5},
        ])},
    ]
    rows = expand_labels_rows(review_analysis_rows)
    assert len(rows) == 3
    assert rows[0]["review_id"] == 1
    assert rows[0]["label_code"] == "quality_stability"
    assert rows[0]["label_polarity"] == "negative"


def test_expand_labels_skip_invalid():
    review_analysis_rows = [
        {"review_id": 1, "labels": "{not json}"},
        {"review_id": 2, "labels": None},
        {"review_id": 3, "labels": "[]"},
    ]
    assert expand_labels_rows(review_analysis_rows) == []
