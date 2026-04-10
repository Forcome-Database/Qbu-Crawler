"""Tests for Translation++ pipeline — combined translation + LLM analysis."""

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from qbu_crawler import config, models
from qbu_crawler.server.translator import TranslationWorker, _is_transient_error


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Create a temp SQLite DB with schema initialized."""
    db_file = str(tmp_path / "test_analysis.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)

    def _conn():
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(models, "get_conn", _conn)
    models.init_db()
    return _conn


_counter = 0


def _insert_product(conn_fn, name="Test Grinder", url=None, site="basspro"):
    global _counter
    _counter += 1
    url = url or f"https://example.com/p/{_counter}"
    conn = conn_fn()
    conn.execute(
        "INSERT INTO products (url, site, name, sku, price, ownership) VALUES (?, ?, ?, 'SKU1', 9.99, 'own')",
        (url, site, name),
    )
    conn.commit()
    pid = conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()["id"]
    conn.close()
    return pid


def _insert_review(conn_fn, product_id, headline="Good product", body="Works great",
                    rating=5.0, translate_status=None, retries=0):
    global _counter
    _counter += 1
    body_hash = f"hash_analysis_{_counter}"
    conn = conn_fn()
    conn.execute(
        """INSERT INTO reviews (product_id, author, headline, body, body_hash, rating,
                                translate_status, translate_retries)
           VALUES (?, 'Author', ?, ?, ?, ?, ?, ?)""",
        (product_id, headline, body, body_hash, rating, translate_status, retries),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rid


def _make_worker(monkeypatch):
    """Create a TranslationWorker without running __init__'s OpenAI setup."""
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_API_BASE", "")
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "TRANSLATE_MAX_RETRIES", 3)
    monkeypatch.setattr(config, "NEGATIVE_THRESHOLD", 2)
    worker = TranslationWorker(interval=1, batch_size=20)
    worker._client = MagicMock()
    return worker


# ---------------------------------------------------------------------------
# Full structured LLM response (translation + analysis)
# ---------------------------------------------------------------------------

def _full_llm_response(index=0):
    """Return a complete LLM response with both translation and analysis fields."""
    return [
        {
            "index": index,
            "headline_cn": "很棒的产品",
            "body_cn": "使用效果非常好",
            "sentiment": "positive",
            "sentiment_score": 0.9,
            "labels": [
                {"code": "HIGH_QUALITY", "polarity": "positive", "severity": "high", "confidence": 0.95},
                {"code": "EASY_USE", "polarity": "positive", "severity": "medium", "confidence": 0.8},
            ],
            "features": ["做工精良", "易于使用", "性价比高"],
            "insight_cn": "用户对产品质量和易用性非常满意",
            "insight_en": "User is very satisfied with product quality and ease of use",
        }
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnalyzeAndTranslateBatch:

    def test_saves_translation(self, test_db, monkeypatch):
        """Full structured LLM output should save translation to reviews table."""
        pid = _insert_product(test_db, name="Test Grinder")
        rid = _insert_review(test_db, pid, headline="Great", body="Works great", rating=5.0)

        worker = _make_worker(monkeypatch)

        def mock_call_llm(client, messages):
            return json.dumps(_full_llm_response(index=0))

        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)

        reviews = models.get_pending_translations(limit=20)
        result = worker._analyze_and_translate_batch(reviews)

        assert result is not None
        assert result[0] == 1  # translated_count
        assert result[1] == 0  # skipped_count

        conn = test_db()
        row = conn.execute(
            "SELECT headline_cn, body_cn, translate_status FROM reviews WHERE id = ?",
            (rid,),
        ).fetchone()
        conn.close()
        assert row["headline_cn"] == "很棒的产品"
        assert row["body_cn"] == "使用效果非常好"
        assert row["translate_status"] == "done"

    def test_saves_analysis(self, test_db, monkeypatch):
        """Full structured LLM output should save analysis to review_analysis table."""
        pid = _insert_product(test_db, name="Test Grinder")
        rid = _insert_review(test_db, pid, headline="Great", body="Works great", rating=5.0)

        worker = _make_worker(monkeypatch)

        def mock_call_llm(client, messages):
            return json.dumps(_full_llm_response(index=0))

        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)

        reviews = models.get_pending_translations(limit=20)
        worker._analyze_and_translate_batch(reviews)

        analysis = models.get_review_analysis(rid)
        assert analysis is not None
        assert analysis["sentiment"] == "positive"
        assert analysis["sentiment_score"] == 0.9
        assert analysis["llm_model"] == "test-model"
        assert analysis["prompt_version"] == "v2"

        labels = json.loads(analysis["labels"])
        assert len(labels) == 2
        assert labels[0]["code"] == "HIGH_QUALITY"

        features = json.loads(analysis["features"])
        assert "做工精良" in features

        assert analysis["insight_cn"] == "用户对产品质量和易用性非常满意"
        assert analysis["insight_en"] == "User is very satisfied with product quality and ease of use"

    def test_fallback_on_missing_analysis_fields(self, test_db, monkeypatch):
        """LLM response with ONLY translation fields (no analysis) should still save
        translation and not raise any exceptions."""
        pid = _insert_product(test_db, name="Test Grinder")
        rid = _insert_review(test_db, pid, headline="OK", body="It works", rating=3.0)

        worker = _make_worker(monkeypatch)

        # LLM returns only translation fields, no sentiment/labels/features
        def mock_call_llm(client, messages):
            return json.dumps([
                {"index": 0, "headline_cn": "还行", "body_cn": "能用"}
            ])

        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)

        reviews = models.get_pending_translations(limit=20)
        result = worker._analyze_and_translate_batch(reviews)

        # Translation should succeed
        assert result is not None
        assert result[0] == 1  # translated_count

        conn = test_db()
        row = conn.execute(
            "SELECT headline_cn, body_cn, translate_status FROM reviews WHERE id = ?",
            (rid,),
        ).fetchone()
        conn.close()
        assert row["headline_cn"] == "还行"
        assert row["body_cn"] == "能用"
        assert row["translate_status"] == "done"

        # Analysis should NOT exist (sentiment was missing/empty -> skipped)
        analysis = models.get_review_analysis(rid)
        assert analysis is None

    def test_transient_error_returns_none(self, test_db, monkeypatch):
        """A transient error from _call_llm should return None (signal for backoff)."""
        pid = _insert_product(test_db, name="Test Grinder")
        _insert_review(test_db, pid, headline="Good", body="Nice", rating=4.0)

        worker = _make_worker(monkeypatch)
        # Override _stop_event.wait to avoid actual sleep during test
        worker._stop_event = MagicMock()
        worker._stop_event.is_set.return_value = False
        worker._stop_event.wait = MagicMock()

        def mock_call_llm(client, messages):
            raise ValueError("LLM returned empty content in choices object")

        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)

        # Verify ValueError is classified as transient
        assert _is_transient_error(ValueError("test")) is True

        reviews = models.get_pending_translations(limit=20)
        result = worker._analyze_and_translate_batch(reviews)

        assert result is None

    def test_backward_compat_alias(self, test_db, monkeypatch):
        """_translate_batch should be an alias for _analyze_and_translate_batch."""
        worker = _make_worker(monkeypatch)
        assert worker._translate_batch == worker._analyze_and_translate_batch

    def test_analysis_failure_does_not_block_translation(self, test_db, monkeypatch):
        """If save_review_analysis raises, translation should still be saved."""
        pid = _insert_product(test_db, name="Test Grinder")
        rid = _insert_review(test_db, pid, headline="Nice", body="Very good", rating=5.0)

        worker = _make_worker(monkeypatch)

        def mock_call_llm(client, messages):
            return json.dumps(_full_llm_response(index=0))

        monkeypatch.setattr(worker, "_call_llm", mock_call_llm)

        # Make save_review_analysis always raise
        original_save = models.save_review_analysis

        def broken_save(*args, **kwargs):
            raise RuntimeError("DB write failed")

        monkeypatch.setattr(models, "save_review_analysis", broken_save)

        reviews = models.get_pending_translations(limit=20)
        result = worker._analyze_and_translate_batch(reviews)

        # Translation should still succeed
        assert result is not None
        assert result[0] == 1

        conn = test_db()
        row = conn.execute(
            "SELECT headline_cn, body_cn, translate_status FROM reviews WHERE id = ?",
            (rid,),
        ).fetchone()
        conn.close()
        assert row["headline_cn"] == "很棒的产品"
        assert row["body_cn"] == "使用效果非常好"
        assert row["translate_status"] == "done"

    def test_prompt_includes_taxonomy_and_threshold(self, monkeypatch):
        """The analysis prompt should contain the label taxonomy and NEGATIVE_THRESHOLD."""
        monkeypatch.setattr(config, "NEGATIVE_THRESHOLD", 2)
        worker = _make_worker(monkeypatch)
        items = [{"index": 0, "headline": "Test", "body": "Test body", "rating": 5, "product_name": "Widget"}]
        prompt = worker._build_analysis_prompt(items)

        assert "quality_stability" in prompt
        assert "solid_build" in prompt
        assert "good_packaging" in prompt
        assert "rating <= 2" in prompt
        assert "product_name" in prompt or "Widget" in prompt

    def test_prompt_version_attribute(self):
        """TranslationWorker should have _prompt_version class attribute."""
        assert TranslationWorker._prompt_version == "v2"
