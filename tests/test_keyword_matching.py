"""Regression tests for keyword-based review label classification."""

import pytest
from qbu_crawler.server.report_analytics import classify_review_labels, _match_rule


class TestMatchRule:
    def test_exact_word_match(self):
        rule = {"keywords": ("broke",)}
        assert _match_rule("the handle broke off", rule)

    def test_no_substring_match(self):
        rule = {"keywords": ("broke",)}
        assert not _match_rule("i am a broker and love this", rule)

    def test_finish_false_positive(self):
        rule = {"keywords": ("finish",)}
        assert not _match_rule("i just finished assembling it works great", rule)

    def test_rust_false_positive(self):
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
        rule = {"keywords": ("hard to clean",)}
        assert not _match_rule("it's not hard to clean at all", rule)

    def test_negation_with_never(self):
        rule = {"keywords": ("broke",)}
        assert not _match_rule("never broke even after years of use", rule)

    def test_case_insensitive(self):
        rule = {"keywords": ("broke",)}
        assert _match_rule("the handle broke", rule)

    def test_chinese_keyword(self):
        rule = {"keywords": ("生锈",)}
        assert _match_rule("这个刀片很快就生锈了", rule)
        assert not _match_rule("不会生锈的材料", rule)


class TestClassifyReviewLabels:
    def _review(self, text, ownership="own", rating=1):
        return {"headline": text, "body": "", "headline_cn": "", "body_cn": "",
                "ownership": ownership, "rating": rating}

    def test_genuine_quality_issue(self):
        labels = classify_review_labels(self._review("The motor broke after two uses"))
        codes = [l["label_code"] for l in labels]
        assert "quality_stability" in codes

    def test_no_false_positive_on_finished(self):
        labels = classify_review_labels(self._review("Just finished setting up, works perfectly!", rating=5))
        codes = [l["label_code"] for l in labels]
        assert "material_finish" not in codes

    def test_negated_difficulty(self):
        labels = classify_review_labels(self._review(
            "It's not hard to assemble at all, very straightforward", rating=5))
        codes = [l["label_code"] for l in labels]
        assert "assembly_installation" not in codes

    def test_powerful_bare_word_no_longer_matches(self):
        labels = classify_review_labels(self._review(
            "Has a powerful chemical smell out of the box", ownership="competitor", rating=2))
        codes = [l["label_code"] for l in labels]
        assert "strong_performance" not in codes
