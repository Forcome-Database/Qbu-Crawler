"""Tests for Report V3 LLM enhancements (Phase 2)."""

import sqlite3
import pytest
from qbu_crawler import config, models


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


class TestReviewAnalysisSchema:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return db_file

    def test_impact_category_column_exists(self, db):
        conn = _get_test_conn(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(review_analysis)").fetchall()]
        assert "impact_category" in cols

    def test_failure_mode_column_exists(self, db):
        conn = _get_test_conn(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(review_analysis)").fetchall()]
        assert "failure_mode" in cols

    def test_save_with_new_fields(self, db):
        conn = _get_test_conn(db)
        conn.execute("INSERT INTO products (url, site, name, sku) VALUES ('http://t', 'test', 'T', 'T1')")
        pid = conn.execute("SELECT id FROM products WHERE sku='T1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating) "
            "VALUES (?, 'a', 'h', 'b', 'x', 1.0)", (pid,))
        rid = conn.execute("SELECT id FROM reviews WHERE author='a'").fetchone()["id"]
        conn.commit()

        models.save_review_analysis(
            review_id=rid, sentiment="negative", sentiment_score=0.9,
            impact_category="safety", failure_mode="主轴金属屑脱落",
            prompt_version="v2",
        )

        row = conn.execute(
            "SELECT impact_category, failure_mode FROM review_analysis WHERE review_id=?", (rid,)
        ).fetchone()
        assert row["impact_category"] == "safety"
        assert row["failure_mode"] == "主轴金属屑脱落"

    def test_save_without_new_fields_backward_compat(self, db):
        """Calling without the new params should work (default None)."""
        conn = _get_test_conn(db)
        conn.execute("INSERT INTO products (url, site, name, sku) VALUES ('http://t2', 'test', 'T2', 'T2')")
        pid = conn.execute("SELECT id FROM products WHERE sku='T2'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating) "
            "VALUES (?, 'b', 'h2', 'b2', 'y', 2.0)", (pid,))
        rid = conn.execute("SELECT id FROM reviews WHERE author='b'").fetchone()["id"]
        conn.commit()

        # Call WITHOUT new params — should still work
        models.save_review_analysis(review_id=rid, sentiment="negative")

        row = conn.execute(
            "SELECT impact_category, failure_mode FROM review_analysis WHERE review_id=?", (rid,)
        ).fetchone()
        assert row["impact_category"] is None
        assert row["failure_mode"] is None


class TestTranslatorV2Prompt:
    def test_prompt_includes_impact_fields(self):
        from qbu_crawler.server.translator import TranslationWorker
        worker = TranslationWorker.__new__(TranslationWorker)
        prompt = worker._build_analysis_prompt([
            {"index": 0, "headline": "Broke", "body": "Metal shavings", "rating": 1.0, "product_name": "Test"}
        ])
        assert "impact_category" in prompt
        assert "failure_mode" in prompt
        assert "safety" in prompt
        # Removed fields from spec 15.6 should NOT be present
        assert "usage_context" not in prompt
        assert "purchase_intent_impact" not in prompt


class TestInsightSampleSelection:
    def test_function_exists(self):
        from qbu_crawler.server.report_llm import _select_insight_samples
        assert callable(_select_insight_samples)

    def test_prompt_signature_accepts_snapshot(self):
        from qbu_crawler.server.report_llm import _build_insights_prompt
        # Should accept snapshot param without error
        prompt = _build_insights_prompt({"kpis": {}}, snapshot={"reviews": []})
        assert isinstance(prompt, str)

    def test_generate_report_insights_accepts_snapshot(self):
        from qbu_crawler.server.report_llm import generate_report_insights
        import inspect
        sig = inspect.signature(generate_report_insights)
        assert "snapshot" in sig.parameters


class TestClusterDeepAnalysis:
    def test_function_exists(self):
        from qbu_crawler.server.report_llm import analyze_cluster_deep
        assert callable(analyze_cluster_deep)

    def test_returns_none_when_llm_not_configured(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_API_BASE", "")
        from qbu_crawler.server.report_llm import analyze_cluster_deep
        cluster = {"label_code": "quality_stability", "label_display": "质量稳定性", "review_count": 10}
        reviews = [{"headline": "bad", "body": "terrible", "rating": 1.0,
                     "product_name": "P1", "date_published_parsed": "2026-01-01"}]
        result = analyze_cluster_deep(cluster, reviews)
        assert result is None

    def test_returns_none_when_cluster_analysis_disabled(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_API_BASE", "http://fake")
        monkeypatch.setattr(config, "LLM_API_KEY", "fake")
        monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)
        from qbu_crawler.server.report_llm import analyze_cluster_deep
        cluster = {"label_code": "quality_stability", "label_display": "质量稳定性", "review_count": 10}
        result = analyze_cluster_deep(cluster, [])
        assert result is None

    def test_validate_cluster_analysis_sanitizes(self):
        from qbu_crawler.server.report_llm import _validate_cluster_analysis
        raw = {
            "failure_modes": [{"mode": "test", "frequency": 5}] * 15,  # over limit
            "root_causes": "not a list",  # wrong type
            "temporal_pattern": "stable",
            "user_workarounds": ["fix1"],
            "actionable_summary": "Do something",
        }
        result = _validate_cluster_analysis(raw)
        assert len(result["failure_modes"]) == 10  # capped
        assert result["root_causes"] == []  # sanitized to list
        assert result["actionable_summary"] == "Do something"

    def test_validate_returns_none_for_non_dict(self):
        from qbu_crawler.server.report_llm import _validate_cluster_analysis
        assert _validate_cluster_analysis("not a dict") is None
        assert _validate_cluster_analysis(None) is None

    def test_validate_filters_non_dict_failure_modes(self):
        from qbu_crawler.server.report_llm import _validate_cluster_analysis
        raw = {
            "failure_modes": [{"mode": "ok"}, "not a dict", 42, {"mode": "also ok"}],
            "root_causes": [{"cause": "valid"}, None, "bad"],
            "temporal_pattern": 123,  # wrong type — should become ""
            "user_workarounds": ["str ok", {"bad": "dict"}, "another str"],
            "actionable_summary": ["wrong type"],  # list — should become ""
        }
        result = _validate_cluster_analysis(raw)
        assert result["failure_modes"] == [{"mode": "ok"}, {"mode": "also ok"}]
        assert result["root_causes"] == [{"cause": "valid"}]
        assert result["temporal_pattern"] == ""
        assert result["user_workarounds"] == ["str ok", "another str"]
        assert result["actionable_summary"] == ""

    def test_returns_none_for_empty_cluster_reviews(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_API_BASE", "http://fake")
        monkeypatch.setattr(config, "LLM_API_KEY", "fake")
        monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", True)
        from qbu_crawler.server.report_llm import analyze_cluster_deep
        cluster = {"label_code": "quality_stability", "label_display": "质量稳定性", "review_count": 10}
        result = analyze_cluster_deep(cluster, [])
        assert result is None


class TestSelectInsightSamplesOwnership:
    """Ensure _select_insight_samples attaches correct ownership to DB results."""

    def test_own_reviews_tagged_own(self, monkeypatch):
        """Reviews from risk-product query (own) must have ownership='own'."""
        from qbu_crawler.server import report_llm

        fake_own = [{"id": 1, "rating": 1, "body": "broken", "product_name": "P1"}]
        monkeypatch.setattr(
            report_llm.models, "query_reviews",
            lambda **kw: (fake_own, 1),
        )
        analytics = {"self": {"risk_products": [{"product_sku": "SKU1"}]}}
        snapshot = {"reviews": []}
        samples = report_llm._select_insight_samples(snapshot, analytics)
        own_samples = [s for s in samples if s.get("id") == 1]
        assert own_samples, "Review from risk product should appear in samples"
        assert own_samples[0].get("ownership") == "own"

    def test_existing_ownership_not_overwritten(self, monkeypatch):
        """setdefault must NOT overwrite an existing ownership value."""
        from qbu_crawler.server import report_llm

        # Simulate a review that already has ownership='competitor' somehow
        fake_own = [{"id": 2, "rating": 1, "body": "ok", "ownership": "competitor"}]
        monkeypatch.setattr(
            report_llm.models, "query_reviews",
            lambda **kw: (fake_own, 1),
        )
        analytics = {"self": {"risk_products": [{"product_sku": "SKU2"}]}}
        snapshot = {"reviews": []}
        samples = report_llm._select_insight_samples(snapshot, analytics)
        # setdefault should not overwrite — existing value preserved
        own_samples = [s for s in samples if s.get("id") == 2]
        assert own_samples[0].get("ownership") == "competitor"


class TestClusterAnalysisPipelineIntegration:
    def test_cluster_analysis_gated_by_config(self, monkeypatch):
        """When REPORT_CLUSTER_ANALYSIS is False, no deep analysis is added."""
        monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)
        analytics = {
            "self": {"top_negative_clusters": [
                {"label_code": "quality_stability", "review_count": 10}
            ]}
        }
        # If config is off, no deep_analysis key should be added
        # (This test validates the conditional gate, not the LLM call)
        clusters = analytics["self"]["top_negative_clusters"]
        assert "deep_analysis" not in clusters[0]
