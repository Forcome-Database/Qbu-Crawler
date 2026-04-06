# Report Intelligence Redesign V2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the report system from keyword-based label matching (44.5% coverage) to LLM-powered semantic analysis (95%+ coverage), with Plotly charts, 6-sheet Excel, and audience-specific outputs.

**Architecture:** Two-phase approach: Phase 1 enhances the translation pipeline to piggyback LLM analysis on each translation call, storing structured results in a new `review_analysis` table. Phase 2 rebuilds the report output layer using Plotly charts, redesigned PDF/email templates, and analytical Excel workbooks — all consuming the enriched data from Phase 1.

**Tech Stack:** Python 3.10+ · Plotly ≥5.20 · Jinja2 · Playwright · openpyxl · OpenAI SDK · SQLite

**Spec:** `docs/superpowers/specs/2026-04-06-report-intelligence-redesign-v2-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `qbu_crawler/server/report_charts.py` | All Plotly chart builders + theme definition |
| `tests/test_review_analysis.py` | review_analysis table CRUD tests |
| `tests/test_translator_analysis.py` | Translation++ prompt + parsing tests |
| `tests/test_report_charts.py` | Chart generation tests |

### Modified Files

| File | Key Changes |
|------|-------------|
| `qbu_crawler/config.py` | Add 5 configurable thresholds |
| `qbu_crawler/models.py` | Add review_analysis table DDL + CRUD |
| `qbu_crawler/server/translator.py` | Replace `_translate_batch()` with `_analyze_and_translate_batch()` |
| `qbu_crawler/cli.py` | Add `backfill-analysis` subcommand |
| `qbu_crawler/server/report_analytics.py` | Use review_analysis data, feature-based aggregation |
| `qbu_crawler/server/report_common.py` | Health index, competitive gap index, new normalization |
| `qbu_crawler/server/report_llm.py` | Replace candidate-pool workflow with `generate_report_insights()` |
| `qbu_crawler/server/report_pdf.py` | Wire Plotly charts, remove Matplotlib imports |
| `qbu_crawler/server/report.py` | 6-sheet Excel, updated email rendering |
| `qbu_crawler/server/report_snapshot.py` | Wire new analytics + chart pipeline |
| `qbu_crawler/server/report_templates/daily_report.html.j2` | Complete redesign (5 sections) |
| `qbu_crawler/server/report_templates/daily_report.css` | Dashboard-density design system |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | Executive decision dashboard |
| `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2` | Updated plain text |
| `pyproject.toml` | Add plotly, remove matplotlib |

---

## Phase 1: Data Layer Enhancement

### Task 1: Configurable Thresholds

**Files:**
- Modify: `qbu_crawler/config.py:153-189`
- Test: `tests/test_config_thresholds.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_thresholds.py
import os
import importlib

def test_default_negative_threshold():
    from qbu_crawler import config
    assert config.NEGATIVE_THRESHOLD == 2

def test_default_low_rating_threshold():
    from qbu_crawler import config
    assert config.LOW_RATING_THRESHOLD == 3

def test_default_health_red():
    from qbu_crawler import config
    assert config.HEALTH_RED == 60

def test_default_health_yellow():
    from qbu_crawler import config
    assert config.HEALTH_YELLOW == 80

def test_default_high_risk_threshold():
    from qbu_crawler import config
    assert config.HIGH_RISK_THRESHOLD == 8

def test_negative_threshold_from_env(monkeypatch):
    monkeypatch.setenv("REPORT_NEGATIVE_THRESHOLD", "4")
    import qbu_crawler.config as cfg
    importlib.reload(cfg)
    assert cfg.NEGATIVE_THRESHOLD == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_thresholds.py -v`
Expected: FAIL — `AttributeError: module 'qbu_crawler.config' has no attribute 'NEGATIVE_THRESHOLD'`

- [ ] **Step 3: Add thresholds to config.py**

Add after the existing `REPORT_PDF_FONT_FAMILY` line (~line 156 in `config.py`):

```python
# ── Report Thresholds ─────────────────────────────
NEGATIVE_THRESHOLD = int(os.getenv("REPORT_NEGATIVE_THRESHOLD", "2"))
LOW_RATING_THRESHOLD = int(os.getenv("REPORT_LOW_RATING_THRESHOLD", "3"))
HEALTH_RED = int(os.getenv("REPORT_HEALTH_RED", "60"))
HEALTH_YELLOW = int(os.getenv("REPORT_HEALTH_YELLOW", "80"))
HIGH_RISK_THRESHOLD = int(os.getenv("REPORT_HIGH_RISK_THRESHOLD", "8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_thresholds.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/config.py tests/test_config_thresholds.py
git commit -m "feat: add configurable report thresholds (negative, health index, risk)"
```

---

### Task 2: review_analysis Table

**Files:**
- Modify: `qbu_crawler/models.py`
- Test: `tests/test_review_analysis.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_analysis.py
import sqlite3
import json
import pytest
from qbu_crawler import models

@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()
    # Insert a product + review for FK references
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO products (id, url, site, name, sku) VALUES (1, 'http://x', 'test', 'Test Product', 'SKU1')")
    conn.execute("INSERT INTO reviews (id, product_id, headline, body, body_hash, rating) VALUES (1, 1, 'Great', 'Love it', 'abc123', 5.0)")
    conn.commit()
    conn.close()
    return db_path

def test_save_review_analysis(db):
    models.save_review_analysis(
        review_id=1,
        sentiment="positive",
        sentiment_score=0.92,
        labels=[{"code": "solid_build", "polarity": "positive", "severity": "low", "confidence": 0.9}],
        features=["做工扎实", "材质厚实"],
        insight_cn="用户对做工和材质非常满意",
        insight_en="User is very satisfied with build quality and material",
        llm_model="gpt-4o-mini",
        prompt_version="v1",
        token_usage=350,
    )
    result = models.get_review_analysis(review_id=1)
    assert result is not None
    assert result["sentiment"] == "positive"
    assert result["sentiment_score"] == 0.92
    assert json.loads(result["labels"])[0]["code"] == "solid_build"
    assert "做工扎实" in json.loads(result["features"])

def test_save_review_analysis_upsert(db):
    """Same review_id + prompt_version should upsert."""
    models.save_review_analysis(review_id=1, sentiment="positive", sentiment_score=0.9,
        labels=[], features=[], prompt_version="v1", llm_model="m", token_usage=100)
    models.save_review_analysis(review_id=1, sentiment="negative", sentiment_score=0.2,
        labels=[], features=["手柄松动"], prompt_version="v1", llm_model="m", token_usage=120)
    result = models.get_review_analysis(review_id=1)
    assert result["sentiment"] == "negative"  # Updated

def test_get_review_analysis_latest_version(db):
    """Should return the latest prompt_version analysis."""
    models.save_review_analysis(review_id=1, sentiment="positive", sentiment_score=0.9,
        labels=[], features=[], prompt_version="v1", llm_model="m", token_usage=100)
    models.save_review_analysis(review_id=1, sentiment="negative", sentiment_score=0.3,
        labels=[], features=[], prompt_version="v2", llm_model="m", token_usage=100)
    result = models.get_review_analysis(review_id=1)
    assert result["sentiment"] == "negative"  # v2 is latest

def test_get_reviews_with_analysis(db):
    """Bulk query: reviews joined with analysis data."""
    models.save_review_analysis(review_id=1, sentiment="positive", sentiment_score=0.9,
        labels=[{"code": "solid_build", "polarity": "positive", "severity": "low", "confidence": 0.9}],
        features=["做工好"], prompt_version="v1", llm_model="m", token_usage=100)
    results = models.get_reviews_with_analysis(review_ids=[1])
    assert len(results) == 1
    assert results[0]["sentiment"] == "positive"
    assert results[0]["headline"] == "Great"  # From reviews table

def test_get_pending_translations_includes_product_name(db):
    """get_pending_translations must return product_name for analysis prompt."""
    results = models.get_pending_translations(limit=10)
    assert len(results) >= 1
    assert "product_name" in results[0]
    assert results[0]["product_name"] == "Test Product"
    assert "rating" in results[0]
    assert "product_sku" in results[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_analysis.py -v`
Expected: FAIL — `AttributeError: module 'qbu_crawler.models' has no attribute 'save_review_analysis'`

- [ ] **Step 3: Add review_analysis table DDL to init_db()**

In `models.py`, find the `init_db()` function. The main DDL block uses `conn.executescript("""...""")`. Add the `review_analysis` table DDL **inside** that `executescript()` string, after the `review_issue_labels` CREATE TABLE (~line 123). Then add indexes as separate `conn.execute()` calls after the `executescript()` block (matching the pattern at lines 227-246):

```python
        # Inside the executescript() string, after review_issue_labels:
        """
            CREATE TABLE IF NOT EXISTS review_analysis (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id       INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
                sentiment       TEXT NOT NULL,
                sentiment_score REAL,
                labels          TEXT NOT NULL DEFAULT '[]',
                features        TEXT NOT NULL DEFAULT '[]',
                insight_cn      TEXT,
                insight_en      TEXT,
                llm_model       TEXT,
                prompt_version  TEXT NOT NULL,
                token_usage     INTEGER,
                analyzed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(review_id, prompt_version)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ra_review ON review_analysis(review_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ra_sentiment ON review_analysis(sentiment)")
```

- [ ] **Step 4: Add CRUD functions to models.py**

Add at the end of `models.py` (before any `if __name__` block):

```python
# ── review_analysis CRUD ──────────────────────────

def save_review_analysis(
    review_id: int,
    sentiment: str,
    sentiment_score: float | None = None,
    labels: list | None = None,
    features: list | None = None,
    insight_cn: str | None = None,
    insight_en: str | None = None,
    llm_model: str | None = None,
    prompt_version: str = "v1",
    token_usage: int | None = None,
) -> None:
    """Save or update a review analysis result."""
    import json as _json
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO review_analysis
               (review_id, sentiment, sentiment_score, labels, features,
                insight_cn, insight_en, llm_model, prompt_version, token_usage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(review_id, prompt_version) DO UPDATE SET
                   sentiment = excluded.sentiment,
                   sentiment_score = excluded.sentiment_score,
                   labels = excluded.labels,
                   features = excluded.features,
                   insight_cn = excluded.insight_cn,
                   insight_en = excluded.insight_en,
                   llm_model = excluded.llm_model,
                   token_usage = excluded.token_usage,
                   analyzed_at = CURRENT_TIMESTAMP
            """,
            (review_id, sentiment, sentiment_score,
             _json.dumps(labels or [], ensure_ascii=False),
             _json.dumps(features or [], ensure_ascii=False),
             insight_cn, insight_en, llm_model, prompt_version, token_usage),
        )
        conn.commit()
    finally:
        conn.close()


def get_review_analysis(review_id: int) -> dict | None:
    """Get the latest analysis for a review (newest prompt_version)."""
    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT * FROM review_analysis
               WHERE review_id = ?
               ORDER BY analyzed_at DESC LIMIT 1""",
            (review_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_reviews_with_analysis(review_ids: list[int] | None = None,
                               since: str | None = None) -> list[dict]:
    """Get reviews joined with their latest analysis data."""
    conn = get_conn()
    try:
        sql = """
            SELECT r.id, r.product_id, r.headline, r.body, r.rating,
                   r.date_published, r.images, r.headline_cn, r.body_cn,
                   p.name AS product_name, p.sku AS product_sku,
                   p.site, p.ownership, p.price,
                   ra.sentiment, ra.sentiment_score, ra.labels AS analysis_labels,
                   ra.features, ra.insight_cn AS analysis_insight_cn,
                   ra.insight_en AS analysis_insight_en
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            LEFT JOIN review_analysis ra ON ra.review_id = r.id
                AND ra.analyzed_at = (
                    SELECT MAX(ra2.analyzed_at) FROM review_analysis ra2
                    WHERE ra2.review_id = r.id
                )
        """
        params = []
        clauses = []
        if review_ids:
            placeholders = ",".join("?" for _ in review_ids)
            clauses.append(f"r.id IN ({placeholders})")
            params.extend(review_ids)
        if since:
            clauses.append("r.scraped_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.scraped_at DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
```

- [ ] **Step 5: Modify get_pending_translations() to JOIN product_name**

In `models.py`, find `get_pending_translations()` (~line 1329). Change the SQL to:

```python
def get_pending_translations(limit: int = 20) -> list[dict]:
    """Fetch reviews needing translation, newest first. Includes product_name for analysis."""
    conn = get_conn()
    try:
        from qbu_crawler import config as _cfg
        max_retries = _cfg.TRANSLATE_MAX_RETRIES
        rows = conn.execute(
            """SELECT r.id, r.headline, r.body, r.rating,
                      p.name AS product_name, p.sku AS product_sku
               FROM reviews r
               JOIN products p ON r.product_id = p.id
               WHERE r.translate_status IS NULL
                  OR (r.translate_status = 'failed' AND r.translate_retries < ?)
               ORDER BY r.scraped_at DESC
               LIMIT ?""",
            (max_retries, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
```

- [ ] **Step 6: Run tests to verify**

Run: `uv run pytest tests/test_review_analysis.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/models.py tests/test_review_analysis.py
git commit -m "feat: add review_analysis table and CRUD functions"
```

---

### Task 3: Translation++ Pipeline

**Files:**
- Modify: `qbu_crawler/server/translator.py:178-255`
- Test: `tests/test_translator_analysis.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_translator_analysis.py
import json
import pytest
from unittest.mock import patch, MagicMock
from qbu_crawler.server.translator import TranslationWorker

SAMPLE_LLM_RESPONSE = json.dumps([
    {
        "index": 0,
        "headline_cn": "很棒的绞肉机",
        "body_cn": "用了三个月了，非常满意。做工扎实，电机强劲。",
        "sentiment": "positive",
        "sentiment_score": 0.92,
        "labels": [
            {"code": "solid_build", "polarity": "positive", "severity": "low", "confidence": 0.93},
            {"code": "strong_performance", "polarity": "positive", "severity": "low", "confidence": 0.88}
        ],
        "features": ["做工扎实", "电机强劲"],
        "insight_cn": "用户对绞肉机的做工和电机性能非常满意",
        "insight_en": "User is very satisfied with build quality and motor performance"
    }
], ensure_ascii=False)

SAMPLE_REVIEWS = [
    {
        "id": 1,
        "headline": "Great grinder",
        "body": "Used it for 3 months, very happy. Solid build, powerful motor.",
        "rating": 5.0,
        "product_name": "1 HP Grinder (#22)",
        "product_sku": "MYM-1HP-22",
    }
]


def test_analyze_and_translate_batch_saves_translation(tmp_path, monkeypatch):
    """Translation fields must be saved to reviews table."""
    from qbu_crawler import models
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()

    # Insert product + review
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO products (id, url, site, name, sku) VALUES (1, 'http://x', 'test', '1 HP Grinder (#22)', 'MYM-1HP-22')")
    conn.execute("INSERT INTO reviews (id, product_id, headline, body, body_hash, rating) VALUES (1, 1, 'Great grinder', 'Used it for 3 months', 'h1', 5.0)")
    conn.commit()
    conn.close()

    worker = TranslationWorker.__new__(TranslationWorker)
    worker._client = MagicMock()
    worker._prompt_version = "v1"

    with patch.object(worker, "_call_llm", return_value=SAMPLE_LLM_RESPONSE):
        translated, skipped = worker._analyze_and_translate_batch(SAMPLE_REVIEWS)

    assert translated == 1
    assert skipped == 0

    # Verify translation saved
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT headline_cn, body_cn, translate_status FROM reviews WHERE id = 1").fetchone()
    assert row["headline_cn"] == "很棒的绞肉机"
    assert row["translate_status"] == "done"
    conn.close()


def test_analyze_and_translate_batch_saves_analysis(tmp_path, monkeypatch):
    """Analysis fields must be saved to review_analysis table."""
    from qbu_crawler import models
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO products (id, url, site, name, sku) VALUES (1, 'http://x', 'test', '1 HP Grinder', 'SKU1')")
    conn.execute("INSERT INTO reviews (id, product_id, headline, body, body_hash, rating) VALUES (1, 1, 'Great', 'Good', 'h1', 5.0)")
    conn.commit()
    conn.close()

    worker = TranslationWorker.__new__(TranslationWorker)
    worker._client = MagicMock()
    worker._prompt_version = "v1"

    with patch.object(worker, "_call_llm", return_value=SAMPLE_LLM_RESPONSE):
        worker._analyze_and_translate_batch(SAMPLE_REVIEWS)

    analysis = models.get_review_analysis(review_id=1)
    assert analysis is not None
    assert analysis["sentiment"] == "positive"
    assert analysis["sentiment_score"] == 0.92
    features = json.loads(analysis["features"])
    assert "做工扎实" in features


def test_analyze_and_translate_fallback_on_bad_json(tmp_path, monkeypatch):
    """If analysis fields are missing, still save translation."""
    from qbu_crawler import models
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO products (id, url, site, name, sku) VALUES (1, 'http://x', 'test', 'P', 'S')")
    conn.execute("INSERT INTO reviews (id, product_id, headline, body, body_hash, rating) VALUES (1, 1, 'H', 'B', 'h1', 3.0)")
    conn.commit()
    conn.close()

    # Response has translation but missing analysis fields
    partial_response = json.dumps([{"index": 0, "headline_cn": "标题", "body_cn": "内容"}])

    worker = TranslationWorker.__new__(TranslationWorker)
    worker._client = MagicMock()
    worker._prompt_version = "v1"

    with patch.object(worker, "_call_llm", return_value=partial_response):
        translated, skipped = worker._analyze_and_translate_batch(SAMPLE_REVIEWS)

    assert translated == 1  # Translation still saved

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT headline_cn, translate_status FROM reviews WHERE id = 1").fetchone()
    assert row["headline_cn"] == "标题"
    assert row["translate_status"] == "done"
    conn.close()

    # Analysis may or may not be saved (graceful degradation)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_translator_analysis.py -v`
Expected: FAIL — `AttributeError: 'TranslationWorker' object has no attribute '_analyze_and_translate_batch'`

- [ ] **Step 3: Implement _analyze_and_translate_batch()**

In `translator.py`, replace the `_translate_batch()` method (~line 178-255) with:

```python
    # Class attribute for prompt version
    _prompt_version = "v1"

    def _build_analysis_prompt(self, items_payload: list[dict]) -> str:
        """Build the combined translation + analysis prompt."""
        from qbu_crawler import config
        threshold = config.NEGATIVE_THRESHOLD
        return (
            "你是一位产品质量分析师。请翻译以下英文产品评论并进行结构化分析。\n"
            "以 JSON 数组返回，每个元素包含以下字段：\n"
            "- index: 原始序号\n"
            "- headline_cn: 中文标题翻译\n"
            "- body_cn: 中文正文翻译\n"
            f"- sentiment: 情感判定（positive/negative/mixed/neutral，≤{threshold}星通常为negative）\n"
            "- sentiment_score: 情感分数 0.0-1.0（0=极度负面，1=极度正面）\n"
            "- labels: 问题标签数组，每个元素 {code, polarity, severity, confidence}\n"
            "  标签 taxonomy（可多选）：\n"
            "  负面: quality_stability, structure_design, assembly_installation, "
            "material_finish, cleaning_maintenance, noise_power, "
            "packaging_shipping, service_fulfillment\n"
            "  正面: easy_to_use, solid_build, good_value, easy_to_clean, "
            "strong_performance, good_packaging\n"
            "- features: 具体产品特征/问题，用中文描述的字符串数组（如[\"手柄松动\",\"电机噪音大\"]）\n"
            "- insight_cn: 一句话中文洞察总结\n"
            "- insight_en: 一句话英文洞察总结\n\n"
            "不要返回其他内容，只返回 JSON 数组。\n\n"
            f"输入：\n{json.dumps(items_payload, ensure_ascii=False)}"
        )

    def _analyze_and_translate_batch(self, reviews: list) -> tuple[int, int] | None:
        """Translate + analyze a batch of reviews in a single LLM call.

        Returns (translated_count, skipped_count) or None on transient error.
        """
        items_payload = [
            {
                "index": i,
                "headline": r.get("headline") or "",
                "body": r.get("body") or "",
                "rating": r.get("rating"),
                "product_name": r.get("product_name") or "",
            }
            for i, r in enumerate(reviews)
        ]

        try:
            prompt = self._build_analysis_prompt(items_payload)
            raw = self._call_llm(self._client, [{"role": "user", "content": prompt}])
            cleaned = _strip_markdown_json(raw)
            results = json.loads(cleaned)
        except (json.JSONDecodeError, Exception) as exc:
            # Same transient/non-transient error handling as before
            if _is_transient_error(exc):
                # Inline backoff (matching existing _translate_batch pattern)
                return None
            logger.warning("Analysis batch failed: %s", exc)
            for r in reviews:
                models.increment_translate_retries(r["id"], config.TRANSLATE_MAX_RETRIES)
            return (0, len(reviews))

        translated = 0
        skipped = 0

        for item in results:
            idx = item.get("index")
            if idx is None or idx >= len(reviews):
                continue
            review = reviews[idx]
            review_id = review["id"]

            # ── Always save translation (priority) ──
            headline_cn = (item.get("headline_cn") or "").strip()
            body_cn = (item.get("body_cn") or "").strip()
            # Fallback: if cn fields empty, try bare field names
            if not headline_cn and not body_cn:
                headline_cn = (item.get("headline") or "").strip()
                body_cn = (item.get("body") or "").strip()

            orig_headline = (review.get("headline") or "").strip()
            orig_body = (review.get("body") or "").strip()

            if not headline_cn and not body_cn and (orig_headline or orig_body):
                skipped += 1
                continue

            models.update_translation(review_id, headline_cn, body_cn, "done")
            translated += 1

            # ── Save analysis (graceful degradation) ──
            try:
                sentiment = item.get("sentiment", "neutral")
                if sentiment not in ("positive", "negative", "mixed", "neutral"):
                    sentiment = "neutral"
                models.save_review_analysis(
                    review_id=review_id,
                    sentiment=sentiment,
                    sentiment_score=item.get("sentiment_score"),
                    labels=item.get("labels") or [],
                    features=item.get("features") or [],
                    insight_cn=item.get("insight_cn"),
                    insight_en=item.get("insight_en"),
                    llm_model=config.LLM_MODEL,
                    prompt_version=self._prompt_version,
                    token_usage=item.get("token_usage"),
                )
            except Exception as exc:
                logger.warning("Analysis save failed for review %s: %s", review_id, exc)
                # Translation is already saved — analysis failure is non-blocking

        return (translated, skipped)
```

- [ ] **Step 4: Update _translate_batch reference**

In `translator.py`, find where `_translate_batch` is called (in `_process_round` or similar). Replace all calls from `_translate_batch` to `_analyze_and_translate_batch`. Keep `_translate_batch` as an alias for backward compatibility:

```python
    # Backward compatibility alias
    _translate_batch = _analyze_and_translate_batch
```

- [ ] **Step 5: Run tests to verify**

Run: `uv run pytest tests/test_translator_analysis.py -v`
Expected: all PASS

- [ ] **Step 6: Run existing translator tests**

Run: `uv run pytest tests/ -k "translat" -v`
Expected: all existing tests still PASS (backward compatible)

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/translator.py tests/test_translator_analysis.py
git commit -m "feat: Translation++ pipeline — combine translation + LLM analysis in single call"
```

---

### Task 4: Backfill CLI Command

**Files:**
- Modify: `qbu_crawler/cli.py`
- Test: `tests/test_cli_backfill.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_backfill.py
import subprocess
import sys

def test_backfill_analysis_help():
    """CLI backfill-analysis subcommand should be recognized."""
    result = subprocess.run(
        [sys.executable, "-m", "qbu_crawler.cli", "backfill-analysis", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    # Should not error with "unknown command"
    assert result.returncode == 0 or "backfill-analysis" in result.stdout.lower() or "usage" in result.stdout.lower()
```

- [ ] **Step 2: Implement backfill-analysis in cli.py**

In `cli.py`, add after the `workflow` subcommand block:

```python
    if len(sys.argv) >= 2 and sys.argv[1] == "backfill-analysis":
        from qbu_crawler import models
        from qbu_crawler.server.translator import TranslationWorker
        init_db()
        if "--help" in sys.argv:
            print("Usage: qbu-crawler backfill-analysis [--batch-size N] [--dry-run]")
            print("Re-analyze all reviews through the Translation++ pipeline.")
            sys.exit(0)
        batch_size = 20
        dry_run = "--dry-run" in sys.argv
        for i, arg in enumerate(sys.argv):
            if arg == "--batch-size" and i + 1 < len(sys.argv):
                batch_size = int(sys.argv[i + 1])

        # Count reviews without analysis
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        total = conn.execute(
            "SELECT COUNT(*) FROM reviews r WHERE NOT EXISTS "
            "(SELECT 1 FROM review_analysis ra WHERE ra.review_id = r.id)"
        ).fetchone()[0]
        conn.close()

        print(f"Reviews without analysis: {total}")
        if dry_run:
            print("Dry run — no changes made.")
            sys.exit(0)
        if total == 0:
            print("Nothing to backfill.")
            sys.exit(0)

        # Reset translate_status to re-process
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute(
            "UPDATE reviews SET translate_status = NULL WHERE id IN "
            "(SELECT r.id FROM reviews r WHERE NOT EXISTS "
            "(SELECT 1 FROM review_analysis ra WHERE ra.review_id = r.id))"
        )
        conn.commit()
        conn.close()

        print(f"Reset {total} reviews. Starting Translation++ backfill...")
        print("Run 'qbu-crawler serve' or start TranslationWorker to process.")
        sys.exit(0)
```

- [ ] **Step 3: Run test and commit**

Run: `uv run pytest tests/test_cli_backfill.py -v`

```bash
git add qbu_crawler/cli.py tests/test_cli_backfill.py
git commit -m "feat: add backfill-analysis CLI command for re-processing existing reviews"
```

---

### Task 5: Update pyproject.toml Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add plotly, keep matplotlib for now (removed in Phase 2)**

In `pyproject.toml` dependencies array, add:

```toml
    "plotly>=5.20.0",
```

- [ ] **Step 2: Verify installation**

Run: `uv sync && uv run python -c "import plotly; print(plotly.__version__)"`
Expected: prints version ≥ 5.20.0

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add plotly>=5.20.0 for chart generation"
```

---

## Phase 2: Report Output Redesign

### Task 6: Plotly Theme + Chart Builders

**Files:**
- Create: `qbu_crawler/server/report_charts.py`
- Test: `tests/test_report_charts.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_charts.py
import pytest
from qbu_crawler.server.report_charts import (
    build_chart_html_fragments, QBU_THEME,
    _build_health_gauge, _build_bar_chart, _build_heatmap,
    _build_radar_chart, _build_quadrant_scatter,
)

def test_qbu_theme_exists():
    assert QBU_THEME is not None
    assert "layout" in QBU_THEME

def test_health_gauge_returns_html():
    html = _build_health_gauge(72)
    assert "<div" in html
    assert "72" in html

def test_health_gauge_red():
    html = _build_health_gauge(45)
    assert "<div" in html

def test_bar_chart_returns_html():
    html = _build_bar_chart(
        labels=["手柄松动", "密封漏油", "电机过热"],
        values=[12, 8, 5],
        title="问题频次",
        colors=["#6b3328", "#b7633f", "#a89070"],
    )
    assert "<div" in html

def test_heatmap_returns_html():
    html = _build_heatmap(
        z=[[0.8, -0.3], [-0.6, 0.5]],
        x_labels=["Product A", "Product B"],
        y_labels=["做工", "性能"],
        title="特征情感热力图",
    )
    assert "<div" in html

def test_radar_chart_returns_html():
    html = _build_radar_chart(
        categories=["做工", "性能", "易用", "清洁", "性价比"],
        own_values=[0.3, 0.5, 0.6, 0.4, 0.7],
        competitor_values=[0.8, 0.7, 0.6, 0.5, 0.4],
        title="竞品对标",
    )
    assert "<div" in html

def test_quadrant_scatter_returns_html():
    html = _build_quadrant_scatter(
        products=[
            {"name": "A", "price": 100, "rating": 4.5, "ownership": "own"},
            {"name": "B", "price": 200, "rating": 3.5, "ownership": "competitor"},
        ],
        title="价格-评分象限",
    )
    assert "<div" in html

def test_build_chart_html_fragments_all_keys():
    """Full analytics dict should produce all expected chart keys."""
    analytics = _make_test_analytics()
    fragments = build_chart_html_fragments(analytics)
    assert "health_gauge" in fragments
    assert "self_risk_products" in fragments
    assert "self_negative_clusters" in fragments
    assert "competitor_positive_themes" in fragments

def _make_test_analytics():
    return {
        "kpis": {
            "health_index": 72,
            "product_count": 9,
            "own_product_count": 3,
            "competitor_product_count": 6,
        },
        "self": {
            "risk_products": [
                {"product_name": "A", "product_sku": "S1", "risk_score": 14,
                 "negative_review_rows": 12, "total_reviews": 50},
            ],
            "top_negative_clusters": [
                {"label_display": "手柄松动", "review_count": 12, "severity": "high"},
            ],
        },
        "competitor": {
            "top_positive_themes": [
                {"label_display": "做工扎实", "review_count": 56},
            ],
        },
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_charts.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create report_charts.py with Plotly theme + all chart builders**

```python
# qbu_crawler/server/report_charts.py
"""Plotly chart builders for the daily report PDF.

All functions return HTML fragment strings (include_plotlyjs=False).
The main template inlines plotly.min.js once.
"""
from __future__ import annotations
import plotly.graph_objects as go
import plotly.io as pio

# ── Design Tokens (matching daily_report.css) ─────
_ACCENT = "#93543f"
_ACCENT_SOFT = "#ead6c8"
_GREEN = "#345f57"
_GREEN_SOFT = "#dce9e3"
_GOLD = "#b0823a"
_INK = "#201b16"
_MUTED = "#766d62"
_PAPER = "#f5f0e8"
_PANEL = "#fffaf3"
_WHITE = "#ffffff"

_SEVERITY_COLORS = {"high": "#6b3328", "medium": "#b7633f", "low": "#a89070"}
_FONT_FAMILY = "Microsoft YaHei, Noto Sans CJK SC, sans-serif"

# ── Plotly Template ───────────────────────────────
QBU_THEME = go.layout.Template(
    layout=go.Layout(
        font=dict(family=_FONT_FAMILY, color=_INK, size=11),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=_WHITE,
        margin=dict(l=10, r=10, t=36, b=10),
        title=dict(font=dict(size=13, color=_INK), x=0, xanchor="left"),
        colorway=[_ACCENT, _GREEN, _GOLD, "#5b8a72", "#c97b5e", "#8a6d4b"],
    )
)
pio.templates["qbu"] = QBU_THEME
pio.templates.default = "qbu"

_CHART_HEIGHT = 240
_CHART_CONFIG = {"displayModeBar": False, "staticPlot": True}


def _to_html(fig: go.Figure) -> str:
    """Render figure to HTML div fragment."""
    return pio.to_html(
        fig, full_html=False, include_plotlyjs=False,
        config=_CHART_CONFIG,
    )


# ── Chart Builders ────────────────────────────────

def _build_health_gauge(value: float, threshold_red: int = 60,
                         threshold_yellow: int = 80) -> str:
    """Health index gauge: 0-100 with red/yellow/green segments."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number=dict(font=dict(size=42, color=_INK)),
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=1, tickcolor=_MUTED),
            bar=dict(color=_ACCENT, thickness=0.25),
            bgcolor=_PANEL,
            borderwidth=0,
            steps=[
                dict(range=[0, threshold_red], color="#f2d9d0"),
                dict(range=[threshold_red, threshold_yellow], color="#f5ecd4"),
                dict(range=[threshold_yellow, 100], color=_GREEN_SOFT),
            ],
            threshold=dict(
                line=dict(color=_INK, width=2),
                thickness=0.8, value=value,
            ),
        ),
    ))
    fig.update_layout(height=180, margin=dict(t=10, b=0, l=30, r=30))
    return _to_html(fig)


def _build_bar_chart(labels: list[str], values: list[float],
                      title: str, colors: list[str] | str | None = None) -> str:
    """Horizontal bar chart (sorted, top items at top)."""
    if isinstance(colors, str):
        colors = [colors] * len(labels)
    elif colors is None:
        colors = [_ACCENT] * len(labels)

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, cornerradius=4),
        text=[f"{v:.0f}" for v in values],
        textposition="outside",
        textfont=dict(size=10, color=_MUTED),
    ))
    fig.update_layout(
        title=title, height=max(160, len(labels) * 36 + 50),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        xaxis=dict(showgrid=True, gridcolor="#f0ebe3", zeroline=False),
        bargap=0.35,
    )
    return _to_html(fig)


def _build_heatmap(z: list[list[float]], x_labels: list[str],
                    y_labels: list[str], title: str) -> str:
    """Feature×Product sentiment heatmap (red-green diverging)."""
    fig = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=y_labels,
        colorscale=[
            [0.0, "#c0392b"], [0.25, "#e8a89a"],
            [0.5, "#f5f0e8"],
            [0.75, "#a3d5c2"], [1.0, _GREEN],
        ],
        zmid=0, zmin=-1, zmax=1,
        text=[[f"{v:.1f}" for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(size=10),
        hovertemplate="产品: %{x}<br>特征: %{y}<br>情感分: %{z:.2f}<extra></extra>",
        colorbar=dict(
            title="情感", titleside="right", thickness=12,
            tickvals=[-1, -0.5, 0, 0.5, 1],
            ticktext=["极负面", "负面", "中性", "正面", "极正面"],
        ),
    ))
    fig.update_layout(
        title=title,
        height=max(200, len(y_labels) * 32 + 80),
        xaxis=dict(tickangle=-30, tickfont=dict(size=9)),
        yaxis=dict(tickfont=dict(size=10)),
    )
    return _to_html(fig)


def _build_radar_chart(categories: list[str],
                        own_values: list[float],
                        competitor_values: list[float],
                        title: str) -> str:
    """Competitive radar: own vs competitor multi-dimensional comparison."""
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=own_values + [own_values[0]],
        theta=categories + [categories[0]],
        fill="toself", fillcolor=f"rgba(147,84,63,0.15)",
        line=dict(color=_ACCENT, width=2),
        name="自有",
    ))
    fig.add_trace(go.Scatterpolar(
        r=competitor_values + [competitor_values[0]],
        theta=categories + [categories[0]],
        fill="toself", fillcolor=f"rgba(52,95,87,0.15)",
        line=dict(color=_GREEN, width=2),
        name="竞品",
    ))
    fig.update_layout(
        title=title, height=280,
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], tickfont=dict(size=8)),
            angularaxis=dict(tickfont=dict(size=10)),
            bgcolor=_WHITE,
        ),
        legend=dict(x=0.85, y=1.1, font=dict(size=10)),
    )
    return _to_html(fig)


def _build_quadrant_scatter(products: list[dict], title: str) -> str:
    """Price-Rating quadrant: own (▲) vs competitor (●)."""
    own = [p for p in products if p.get("ownership") == "own"]
    comp = [p for p in products if p.get("ownership") != "own"]

    fig = go.Figure()
    if comp:
        fig.add_trace(go.Scatter(
            x=[p["price"] for p in comp],
            y=[p["rating"] for p in comp],
            mode="markers+text",
            marker=dict(size=12, color=_GREEN, symbol="circle", opacity=0.7),
            text=[p["name"][:12] for p in comp],
            textposition="top center", textfont=dict(size=8),
            name="竞品",
        ))
    if own:
        fig.add_trace(go.Scatter(
            x=[p["price"] for p in own],
            y=[p["rating"] for p in own],
            mode="markers+text",
            marker=dict(size=14, color=_ACCENT, symbol="triangle-up", opacity=0.9),
            text=[p["name"][:12] for p in own],
            textposition="top center", textfont=dict(size=8),
            name="自有",
        ))

    # Quadrant lines at median
    all_prices = [p["price"] for p in products if p.get("price")]
    all_ratings = [p["rating"] for p in products if p.get("rating")]
    if all_prices and all_ratings:
        mid_price = sorted(all_prices)[len(all_prices) // 2]
        mid_rating = sorted(all_ratings)[len(all_ratings) // 2]
        fig.add_hline(y=mid_rating, line=dict(dash="dot", color=_MUTED, width=1))
        fig.add_vline(x=mid_price, line=dict(dash="dot", color=_MUTED, width=1))

    fig.update_layout(
        title=title, height=_CHART_HEIGHT,
        xaxis=dict(title="价格 ($)", gridcolor="#f0ebe3"),
        yaxis=dict(title="评分", gridcolor="#f0ebe3"),
    )
    return _to_html(fig)


def _build_trend_line(dates: list[str], values: list[float],
                       title: str, y_label: str = "") -> str:
    """Simple line chart for trend data."""
    fig = go.Figure(go.Scatter(
        x=dates, y=values, mode="lines+markers",
        line=dict(color=_ACCENT, width=2),
        marker=dict(size=6, color=_ACCENT),
    ))
    fig.update_layout(
        title=title, height=200,
        xaxis=dict(tickangle=-30, tickfont=dict(size=9)),
        yaxis=dict(title=y_label, gridcolor="#f0ebe3"),
    )
    return _to_html(fig)


def _build_stacked_bar(categories: list[str],
                        positive: list[int], neutral: list[int],
                        negative: list[int], title: str) -> str:
    """Stacked bar chart for sentiment distribution by product."""
    fig = go.Figure()
    fig.add_trace(go.Bar(name="正面", x=categories, y=positive, marker_color=_GREEN))
    fig.add_trace(go.Bar(name="中性", x=categories, y=neutral, marker_color=_GOLD))
    fig.add_trace(go.Bar(name="负面", x=categories, y=negative, marker_color=_ACCENT))
    fig.update_layout(
        title=title, barmode="stack", height=_CHART_HEIGHT,
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center", font=dict(size=10)),
        xaxis=dict(tickangle=-30, tickfont=dict(size=9)),
    )
    return _to_html(fig)


# ── Main Entry Point ─────────────────────────────

def build_chart_html_fragments(analytics: dict) -> dict[str, str]:
    """Build all chart HTML fragments from analytics data.

    Returns dict of chart_name → HTML fragment string.
    """
    from qbu_crawler import config
    charts: dict[str, str] = {}
    kpis = analytics.get("kpis", {})
    self_data = analytics.get("self", {})
    comp_data = analytics.get("competitor", {})

    # 1. Health gauge
    health = kpis.get("health_index", 0)
    charts["health_gauge"] = _build_health_gauge(
        health, config.HEALTH_RED, config.HEALTH_YELLOW,
    )

    # 2. Risk products bar
    risk_products = self_data.get("risk_products", [])[:6]
    if risk_products:
        charts["self_risk_products"] = _build_bar_chart(
            labels=[p["product_name"][:18] for p in risk_products],
            values=[p["risk_score"] for p in risk_products],
            title="高风险产品排序",
            colors=_ACCENT,
        )

    # 3. Negative clusters bar (colored by severity)
    clusters = self_data.get("top_negative_clusters", [])[:6]
    if clusters:
        charts["self_negative_clusters"] = _build_bar_chart(
            labels=[c["label_display"] for c in clusters],
            values=[c["review_count"] for c in clusters],
            title="问题簇排序",
            colors=[_SEVERITY_COLORS.get(c.get("severity", "medium"), _ACCENT)
                    for c in clusters],
        )

    # 4. Competitor positive themes
    themes = comp_data.get("top_positive_themes", [])[:6]
    if themes:
        charts["competitor_positive_themes"] = _build_bar_chart(
            labels=[t["label_display"] for t in themes],
            values=[t["review_count"] for t in themes],
            title="竞品正向主题 Top",
            colors=_GREEN,
        )

    # 5. Quadrant (if we have products with price + rating)
    all_products = analytics.get("_products_for_charts", [])
    if len(all_products) >= 3:
        charts["price_rating_quadrant"] = _build_quadrant_scatter(
            all_products, "价格-评分象限",
        )

    # 6. Feature heatmap (if available)
    heatmap_data = analytics.get("_heatmap_data")
    if heatmap_data:
        charts["feature_heatmap"] = _build_heatmap(**heatmap_data)

    # 7. Radar chart (if gap analysis available)
    radar_data = analytics.get("_radar_data")
    if radar_data:
        charts["competitive_radar"] = _build_radar_chart(**radar_data)

    # 8. Sentiment distribution (if available)
    sentiment_data = analytics.get("_sentiment_distribution")
    if sentiment_data:
        charts["sentiment_distribution"] = _build_stacked_bar(**sentiment_data)

    # 9. Trend line (if multi-day snapshots)
    trend_data = analytics.get("_trend_data")
    if trend_data:
        charts["rating_trend"] = _build_trend_line(**trend_data)

    return charts
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_report_charts.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_charts.py tests/test_report_charts.py
git commit -m "feat: Plotly chart builders with QBU theme (gauge, heatmap, radar, quadrant, bars)"
```

---

### Task 7: CSS Design System

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report.css`

- [ ] **Step 1: Rewrite CSS with design tokens and dashboard density**

Replace the full content of `daily_report.css` with the new design system. Key changes:
- Tighter spacing (padding 12-14px)
- Design tokens centralized in `:root`
- Table-based data sections
- Health gauge container
- Severity color classes
- Responsive chart containers for Plotly
- Print-optimized page breaks

The complete CSS is large (~600 lines). Key design token block:

```css
:root {
  /* ── Color Tokens ── */
  --paper: #f5f0e8;
  --panel: #fffaf3;
  --panel-strong: #f1e6d7;
  --ink: #201b16;
  --muted: #766d62;
  --line: #d9ccb9;
  --accent: #93543f;
  --accent-soft: #ead6c8;
  --green: #345f57;
  --green-soft: #dce9e3;
  --gold: #b0823a;
  --gold-soft: #f5ecd4;
  --red-bg: #f2d9d0;

  /* ── Spacing Tokens ── */
  --sp-xs: 4px;
  --sp-sm: 8px;
  --sp-md: 12px;
  --sp-lg: 16px;
  --sp-xl: 20px;

  /* ── Typography ── */
  --fs-xs: 9px;
  --fs-sm: 10px;
  --fs-base: 11px;
  --fs-md: 13px;
  --fs-lg: 18px;
  --fs-xl: 26px;
  --fs-hero: 34px;

  /* ── Radius ── */
  --r-sm: 8px;
  --r-md: 14px;
  --r-lg: 20px;

  /* ── Shadow ── */
  --shadow: 0 6px 20px rgba(34, 23, 13, 0.06);
}
```

Additional classes to add:

```css
/* ── Health Gauge Container ── */
.health-gauge-wrap {
  display: flex;
  align-items: center;
  gap: var(--sp-lg);
}
.health-gauge-chart {
  width: 160px;
  flex-shrink: 0;
}
.health-gauge-meta {
  flex: 1;
}

/* ── Data Table ── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-base);
}
.data-table th {
  background: var(--panel-strong);
  font-weight: 700;
  font-size: var(--fs-sm);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  padding: var(--sp-sm) var(--sp-md);
  text-align: left;
  border-bottom: 2px solid var(--line);
}
.data-table td {
  padding: var(--sp-sm) var(--sp-md);
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.data-table tr:last-child td { border-bottom: none; }

/* ── Severity Badges ── */
.severity-high { background: var(--accent-soft); color: var(--accent); }
.severity-medium { background: var(--gold-soft); color: var(--gold); }
.severity-low { background: var(--green-soft); color: var(--green); }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: var(--fs-xs);
  font-weight: 700;
}

/* ── Plotly Chart Containers ── */
.chart-container {
  border-radius: var(--r-md);
  background: var(--panel);
  border: 1px solid var(--line);
  padding: var(--sp-md);
  margin-bottom: var(--sp-md);
  break-inside: avoid;
}
.chart-container .js-plotly-plot {
  width: 100% !important;
}

/* ── Two Column Grid ── */
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-md);
}

/* ── Issue Cards ── */
.issue-card {
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--panel);
  padding: var(--sp-lg);
  margin-bottom: var(--sp-md);
  break-inside: avoid;
}
.issue-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--sp-md);
}
.issue-stats {
  display: flex;
  gap: var(--sp-lg);
  color: var(--muted);
  font-size: var(--fs-sm);
  margin-bottom: var(--sp-md);
}
.issue-timeline {
  font-size: var(--fs-sm);
  color: var(--muted);
}

/* ── Evidence Strip ── */
.evidence-strip {
  display: flex;
  gap: var(--sp-sm);
  margin-top: var(--sp-md);
}
.evidence-thumb {
  position: relative;
  width: 100px;
  height: 80px;
  border-radius: var(--r-sm);
  overflow: hidden;
  flex-shrink: 0;
}
.evidence-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* ── Quote Block ── */
.quote-block {
  padding: var(--sp-md);
  border-left: 3px solid var(--accent-soft);
  background: rgba(241, 230, 215, 0.2);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  margin-bottom: var(--sp-sm);
}
.quote-cn { font-weight: 600; font-size: var(--fs-base); }
.quote-en { font-size: var(--fs-sm); color: var(--muted); margin-top: var(--sp-xs); }
.quote-meta { font-size: var(--fs-xs); color: var(--muted); margin-top: var(--sp-xs); }

/* ── LLM Recommendation Box ── */
.recommendation-box {
  padding: var(--sp-md);
  border: 1px dashed var(--accent-soft);
  border-radius: var(--r-md);
  background: rgba(234, 214, 200, 0.15);
  font-size: var(--fs-base);
  margin-top: var(--sp-md);
}
.recommendation-box::before {
  content: "💡 改良建议（AI 生成）";
  display: block;
  font-size: var(--fs-sm);
  font-weight: 700;
  color: var(--accent);
  margin-bottom: var(--sp-sm);
  letter-spacing: 0.08em;
}
```

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report.css
git commit -m "style: redesign CSS with dashboard-density design system and tokens"
```

---

### Task 8: PDF Template Redesign

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report.html.j2`

- [ ] **Step 1: Rewrite the Jinja2 template**

Complete redesign following the 5-page information architecture from the spec. The template must include:

1. **Plotly.js inline**: `<script>{{ plotly_js | safe }}</script>` at the top
2. **P1**: Executive Dashboard with health gauge, 6 KPI cards, alert, hero headline, bullets
3. **P2**: Product Health Matrix with scorecard table + charts
4. **P3**: Issue Deep Dive with feature-based cards, quotes, evidence, LLM recommendations
5. **P4**: Competitive Intelligence with gap table, radar, opportunities
6. **P5**: Feature Sentiment Panorama (conditional)

Key template structure (abbreviated for plan — full template in implementation):

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>产品评论深度分析报告 {{ snapshot.logical_date }}</title>
  <style>{{ css_text | safe }}</style>
  <script>{{ plotly_js | safe }}</script>
</head>
<body class="report-shell">

  <!-- P1: Executive Dashboard -->
  <section class="report-page report-page-hero">
    <div class="page-frame hero-frame">
      <div class="hero-topline">Daily Product Intelligence</div>
      <div class="health-gauge-wrap">
        <div class="health-gauge-chart">{{ charts.health_gauge | safe }}</div>
        <div class="health-gauge-meta">
          <h1>产品评论<br>深度分析</h1>
          <p class="hero-headline">{{ analytics.report_copy.hero_headline }}</p>
          <p class="hero-meta">Run #{{ snapshot.run_id }} · {{ snapshot.logical_date }} · {{ analytics.mode_display }}</p>
        </div>
      </div>

      <div class="kpi-grid">
        {% for kpi in analytics.kpi_cards %}
        <div class="metric-card">
          <span class="metric-label">{{ kpi.label }}</span>
          <strong class="metric-value">{{ kpi.value }}</strong>
          {% if kpi.delta_display %}
          <span class="delta {{ kpi.delta_class }}">{{ kpi.delta_display }}</span>
          {% endif %}
        </div>
        {% endfor %}
      </div>

      {% if analytics.alert_level %}
      <div class="alert-signal alert-{{ analytics.alert_level }}">{{ analytics.alert_text }}</div>
      {% endif %}

      <div class="hero-support">
        <article class="hero-block">
          <p class="section-kicker">关键判断</p>
          <ul class="hero-bullets">
            {% for item in analytics.report_copy.executive_bullets[:3] %}
            <li>{{ item }}</li>
            {% endfor %}
          </ul>
        </article>
        <article class="hero-block hero-block-mode">
          <p class="section-kicker">报告口径</p>
          <p>{{ analytics.mode_display }} · 差评定义：≤{{ threshold }}星</p>
          <p>自有 {{ analytics.kpis.own_product_count }} · 竞品 {{ analytics.kpis.competitor_product_count }}</p>
        </article>
      </div>
    </div>
  </section>

  <!-- P2: Product Health Matrix -->
  <section class="report-page report-section">
    <div class="page-frame">
      <div class="page-head">
        <p class="section-kicker">产品健康矩阵</p>
        <h2>产品健康度排名</h2>
      </div>
      <table class="data-table">
        <thead>
          <tr><th>产品</th><th>SKU</th><th>评分</th><th>差评率</th><th>风险分</th><th>主要问题</th><th>趋势</th></tr>
        </thead>
        <tbody>
          {% for p in analytics.self.risk_products %}
          <tr>
            <td><strong>{{ p.product_name }}</strong></td>
            <td>{{ p.product_sku }}</td>
            <td>{{ "%.1f" | format(p.rating_avg or 0) }}</td>
            <td>{{ "%.0f%%" | format((p.negative_rate or 0) * 100) }}</td>
            <td>{{ p.risk_score }}</td>
            <td>{{ p.top_features_display }}</td>
            <td>{{ p.trend_display }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <div class="grid-2">
        {% if charts.price_rating_quadrant %}
        <div class="chart-container">{{ charts.price_rating_quadrant | safe }}</div>
        {% endif %}
        {% if charts.rating_trend %}
        <div class="chart-container">{{ charts.rating_trend | safe }}</div>
        {% endif %}
      </div>
    </div>
  </section>

  <!-- P3: Issue Deep Dive -->
  <section class="report-page report-section">
    <div class="page-frame">
      <div class="page-head">
        <p class="section-kicker">问题深度诊断</p>
        <h2>按影响规模排序</h2>
      </div>
      {% for issue in analytics.self.issue_cards[:4] %}
      <article class="issue-card">
        <div class="issue-header">
          <div>
            <h3>{{ issue.feature_display }}</h3>
            <div class="issue-stats">
              <span>{{ issue.review_count }} 条差评</span>
              <span>{{ issue.affected_product_count }} 个产品</span>
            </div>
            {% if issue.first_seen %}
            <p class="issue-timeline">{{ issue.first_seen }} → {{ issue.last_seen }} · {{ issue.duration_display }}</p>
            {% endif %}
          </div>
          <span class="badge severity-{{ issue.severity }}">{{ issue.severity_display }}</span>
        </div>

        {% for quote in issue.example_reviews[:2] %}
        <div class="quote-block">
          <p class="quote-cn">"{{ quote.insight_cn or quote.summary_text }}"</p>
          {% if quote.headline_en %}
          <p class="quote-en">"{{ quote.headline_en }}: {{ quote.body_en[:80] }}"</p>
          {% endif %}
          <p class="quote-meta">— ★{{ quote.rating }} · {{ quote.author or '匿名' }}{% if quote.date_published %} · {{ quote.date_published }}{% endif %}</p>
        </div>
        {% endfor %}

        {% if issue.image_evidence %}
        <div class="evidence-strip">
          {% for img in issue.image_evidence[:3] %}
          <div class="evidence-thumb">
            <img src="{{ img.data_uri or img.url }}" alt="证据">
          </div>
          {% endfor %}
        </div>
        {% endif %}

        {% if issue.recommendation %}
        <div class="recommendation-box">{{ issue.recommendation }}</div>
        {% endif %}
      </article>
      {% endfor %}
    </div>
  </section>

  <!-- P4: Competitive Intelligence -->
  <section class="report-page report-section">
    <div class="page-frame">
      <div class="page-head">
        <p class="section-kicker">竞品情报</p>
        <h2>竞品差距分析与机会</h2>
      </div>
      {% if analytics.competitor.gap_analysis %}
      <table class="data-table">
        <thead><tr><th>维度</th><th>竞品好评</th><th>自有差评</th><th>差距</th><th>优先级</th></tr></thead>
        <tbody>
          {% for g in analytics.competitor.gap_analysis %}
          <tr>
            <td>{{ g.label_display }}</td>
            <td>{{ g.competitor_positive_count }}</td>
            <td>{{ g.own_negative_count }}</td>
            <td>{{ g.gap }}</td>
            <td><span class="badge severity-{{ g.priority }}">{{ g.priority_display }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}

      {% if analytics.report_copy.competitive_insight %}
      <div class="recommendation-box">{{ analytics.report_copy.competitive_insight }}</div>
      {% endif %}

      <div class="grid-2">
        {% if charts.competitive_radar %}
        <div class="chart-container">{{ charts.competitive_radar | safe }}</div>
        {% endif %}
        {% if charts.competitor_positive_themes %}
        <div class="chart-container">{{ charts.competitor_positive_themes | safe }}</div>
        {% endif %}
      </div>
    </div>
  </section>

  <!-- P5: Sentiment Panorama (conditional) -->
  {% if charts.feature_heatmap %}
  <section class="report-page report-section">
    <div class="page-frame">
      <div class="page-head">
        <p class="section-kicker">特征情感全景</p>
        <h2>产品×特征 情感矩阵</h2>
      </div>
      <div class="chart-container">{{ charts.feature_heatmap | safe }}</div>
      <div class="grid-2">
        {% if charts.sentiment_distribution %}
        <div class="chart-container">{{ charts.sentiment_distribution | safe }}</div>
        {% endif %}
        {% if charts.rating_trend %}
        <div class="chart-container">{{ charts.rating_trend | safe }}</div>
        {% endif %}
      </div>
    </div>
  </section>
  {% endif %}

</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report.html.j2
git commit -m "feat: redesign PDF template with 5-section info architecture and Plotly charts"
```

---

### Task 9: Email Template Redesign

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_email.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2`

- [ ] **Step 1: Rewrite email HTML template**

Executive decision dashboard layout with health index, 5 KPI cards, alert, 3 action items. Full HTML email with table-based layout for Outlook compatibility. Design must match the warm-tone palette.

Key structure:
```html
<!-- Health Index hero -->
<td style="background:#93543f;color:#fff;text-align:center;padding:20px;border-radius:12px 12px 0 0;">
  <p style="font-size:11px;letter-spacing:0.15em;margin:0;">PRODUCT HEALTH INDEX</p>
  <p style="font-size:48px;font-weight:700;margin:8px 0 4px;">{{ analytics.kpis.health_index }}</p>
  <p style="font-size:13px;margin:0;">{{ analytics.alert_text }}</p>
</td>

<!-- 5 KPI cards as table cells -->
<!-- 3 action items as numbered list -->
<!-- Attachment guide -->
<!-- Footer with threshold annotation -->
```

- [ ] **Step 2: Update plain text template**

```
{{ snapshot.logical_date }} 产品评论{{ "基线建档" if analytics.mode == "baseline" else "深度日报" }}

健康指数: {{ analytics.kpis.health_index }}/100
差评数: {{ analytics.kpis.negative_review_rows }}{% if analytics.kpis.negative_review_rows_delta_display %} ({{ analytics.kpis.negative_review_rows_delta_display }}){% endif %}

差评率: {{ analytics.kpis.negative_review_rate_display }}

需要关注:
{% for item in analytics.report_copy.executive_bullets[:3] %}
{{ loop.index }}. {{ item }}
{% endfor %}

详见附件 PDF（分析报告）和 Excel（数据明细）。
差评定义: ≤{{ threshold }}星 | 内部资料
```

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_email.html.j2
git add qbu_crawler/server/report_templates/daily_report_email_body.txt.j2
git commit -m "feat: redesign email as executive decision dashboard with health index"
```

---

### Task 10: Analytics Engine Rewrite

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_llm.py`
- Tests: Update existing `tests/test_report_analytics.py`, `tests/test_report_common.py`, `tests/test_report_llm.py`

This is the largest task. Key changes:

- [ ] **Step 1: Add health_index computation to report_common.py**

```python
def compute_health_index(analytics: dict) -> float:
    """Compute 0-100 health index from KPIs."""
    from qbu_crawler import config
    kpis = analytics.get("kpis", {})
    own_count = kpis.get("own_product_count", 0)

    # Component 1: Average rating (0-5 → 0-1)
    avg_rating = kpis.get("own_avg_rating", 0) or 0
    rating_score = min(avg_rating / 5.0, 1.0)

    # Component 2: Inverse negative rate
    neg_rate = kpis.get("negative_review_rate", 0) or 0
    neg_score = 1.0 - min(neg_rate, 1.0)

    # Component 3: Inverse high-risk ratio
    high_risk_count = sum(
        1 for p in analytics.get("self", {}).get("risk_products", [])
        if p.get("risk_score", 0) >= config.HIGH_RISK_THRESHOLD
    )
    risk_ratio = high_risk_count / max(own_count, 1)
    risk_score = 1.0 - min(risk_ratio, 1.0)

    # Weighted composite
    index = (rating_score * 0.40 + neg_score * 0.35 + risk_score * 0.25) * 100
    return round(max(0, min(100, index)), 1)
```

- [ ] **Step 2: Add feature-based aggregation to report_analytics.py**

Replace the keyword-based `classify_review_labels()` with a function that reads from `review_analysis`:

```python
def _build_feature_clusters(reviews_with_analysis: list[dict]) -> list[dict]:
    """Aggregate review_analysis.features into issue clusters.
    
    Returns clusters sorted by review_count descending.
    Each cluster has: feature_display, review_count, affected_products,
    severity, example_reviews, first_seen, last_seen.
    """
    from collections import defaultdict
    clusters = defaultdict(lambda: {
        "reviews": [], "products": set(), "severities": [],
    })
    for r in reviews_with_analysis:
        features = json.loads(r.get("features") or "[]")
        labels = json.loads(r.get("analysis_labels") or "[]")
        severity = max((l.get("severity", "low") for l in labels), 
                       key=lambda s: {"high": 3, "medium": 2, "low": 1}.get(s, 0),
                       default="low") if labels else "low"
        for feat in features:
            feat_lower = feat.strip()
            if not feat_lower:
                continue
            clusters[feat_lower]["reviews"].append(r)
            clusters[feat_lower]["products"].add(r.get("product_sku", ""))
            clusters[feat_lower]["severities"].append(severity)
    
    result = []
    for feat, data in clusters.items():
        reviews = data["reviews"]
        dates = [r.get("date_published") for r in reviews if r.get("date_published")]
        max_sev = max(data["severities"], 
                      key=lambda s: {"high": 3, "medium": 2, "low": 1}.get(s, 0))
        result.append({
            "feature_display": feat,
            "review_count": len(reviews),
            "affected_product_count": len(data["products"]),
            "severity": max_sev,
            "first_seen": min(dates) if dates else None,
            "last_seen": max(dates) if dates else None,
            "example_reviews": sorted(reviews, key=lambda r: r.get("rating", 5))[:3],
        })
    
    result.sort(key=lambda c: (-c["review_count"], -{"high": 3, "medium": 2, "low": 1}.get(c["severity"], 0)))
    return result
```

- [ ] **Step 3: Replace report_llm.py with generate_report_insights()**

```python
def generate_report_insights(analytics: dict) -> dict:
    """Single LLM call to generate executive summary, headline, and recommendations.
    
    Input: aggregated analytics with KPIs, issue clusters, gap analysis.
    Output: dict with executive_summary, hero_headline, improvement_priorities, competitive_insight.
    """
    from qbu_crawler import config
    if not config.LLM_API_BASE:
        return _fallback_insights(analytics)
    
    prompt = _build_insights_prompt(analytics)
    # ... LLM call and JSON parsing
    # ... with fallback to _fallback_insights() on failure
```

- [ ] **Step 4: Update tests for all changed functions**

Each modified function needs its tests updated. Key test patterns:
- Health index: verify 0-100 range, verify color thresholds
- Feature clusters: verify grouping, sorting, severity extraction
- Report insights: mock LLM, verify output structure

- [ ] **Step 5: Commit each module separately**

```bash
git commit -m "feat: health index computation with configurable thresholds"
git commit -m "feat: feature-based issue clustering from review_analysis"
git commit -m "feat: LLM-generated report insights replacing hardcoded recommendations"
```

---

### Task 11: Excel 6-Sheet Workbook

**Files:**
- Modify: `qbu_crawler/server/report.py` (the `_legacy_generate_excel()` function at line 148-296)
- Test: Update `tests/test_report.py`

- [ ] **Step 1: Write tests for 6-sheet structure**

```python
def test_generate_excel_has_six_sheets(sample_data, tmp_path):
    """Excel must have 6 sheets."""
    products, reviews = sample_data
    path = report.generate_excel(products, reviews, analytics=analytics_fixture)
    wb = openpyxl.load_workbook(path)
    expected = ["Executive Summary", "Product Scorecard", "Issue Analysis",
                "Competitive Benchmark", "Review Details", "Trend Data"]
    assert wb.sheetnames == expected

def test_executive_summary_has_kpis(sample_data, tmp_path):
    """First sheet must contain KPI table."""
    # ... verify KPI rows exist with correct values
```

- [ ] **Step 2: Implement 6-sheet generation**

Refactor `_legacy_generate_excel()` into `_generate_analytical_excel()` with 6 sheets. Each sheet follows the design from spec Section 11.

Key implementation pattern for conditional formatting:

```python
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill

red_fill = PatternFill(start_color="F2D9D0", end_color="F2D9D0", fill_type="solid")
yellow_fill = PatternFill(start_color="F5ECD4", end_color="F5ECD4", fill_type="solid")
green_fill = PatternFill(start_color="DCE9E3", end_color="DCE9E3", fill_type="solid")

# Apply to negative rate column
ws.conditional_formatting.add(f"D2:D{last_row}",
    CellIsRule(operator="greaterThan", formula=["0.3"], fill=red_fill))
ws.conditional_formatting.add(f"D2:D{last_row}",
    CellIsRule(operator="between", formula=["0.15", "0.3"], fill=yellow_fill))
ws.conditional_formatting.add(f"D2:D{last_row}",
    CellIsRule(operator="lessThan", formula=["0.15"], fill=green_fill))
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: 6-sheet analytical Excel workbook with conditional formatting"
```

---

### Task 12: Integration Wiring

**Files:**
- Modify: `qbu_crawler/server/report_pdf.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report.py`

- [ ] **Step 1: Wire Plotly charts into report_pdf.py**

Replace Matplotlib imports with `report_charts` imports. Update `render_report_html()` to:
1. Call `report_charts.build_chart_html_fragments(analytics)` instead of `build_chart_assets()`
2. Pass chart HTML fragments to the Jinja2 template
3. Inline `plotly.min.js` into the template context

```python
# report_pdf.py changes
from qbu_crawler.server.report_charts import build_chart_html_fragments

def render_report_html(snapshot, analytics, asset_dir=None):
    # ... existing normalization, delta, headline, alert logic ...
    
    charts = build_chart_html_fragments(analytics)
    
    # Load plotly.js for inline embedding (official API)
    from plotly.offline import get_plotlyjs
    plotly_js = get_plotlyjs()
    
    html = template.render(
        snapshot=snapshot,
        analytics=analytics,
        charts=charts,
        plotly_js=plotly_js,
        css_text=css_text,
        threshold=config.NEGATIVE_THRESHOLD,
        # ... other context
    )
    return html
```

- [ ] **Step 2: Update report_snapshot.py call chain**

Replace the old `report_llm.run_llm_report_analysis()` → `validate_findings()` → `merge_final_analytics()` chain with:

```python
# report_snapshot.py
from qbu_crawler.server.report_llm import generate_report_insights

def generate_full_report_from_snapshot(snapshot, ...):
    # ... existing snapshot loading ...
    
    analytics = report_analytics.build_report_analytics(snapshot)
    
    # New: LLM-generated insights (replaces old 3-function chain)
    insights = generate_report_insights(analytics)
    analytics["report_copy"] = insights
    
    # ... rest of pipeline (Excel, PDF, email) ...
```

- [ ] **Step 3: Remove matplotlib from pyproject.toml**

```toml
# Remove this line:
# "matplotlib>=3.9.0",
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All tests pass (with updated test fixtures)

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: wire Plotly charts + LLM insights into report pipeline, remove matplotlib"
```

---

### Task 13: Full Integration Test

**Files:**
- Test: `tests/test_report_integration.py` (new)

- [ ] **Step 1: Write end-to-end test**

```python
# tests/test_report_integration.py
"""End-to-end test: sample data → analytics → charts → PDF → Excel → email."""
import json
import pytest
from unittest.mock import patch, MagicMock
from qbu_crawler.server import report_snapshot

def test_full_report_pipeline(tmp_path, monkeypatch, sample_snapshot_with_analysis):
    """Generate full report from a snapshot with review_analysis data."""
    snapshot = sample_snapshot_with_analysis
    
    with patch("qbu_crawler.server.report_llm.generate_report_insights") as mock_llm:
        mock_llm.return_value = {
            "executive_summary": "测试执行摘要",
            "hero_headline": "测试主标题",
            "improvement_priorities": [],
            "competitive_insight": "测试竞品洞察",
        }
        result = report_snapshot.generate_full_report_from_snapshot(
            snapshot, send_email=False,
        )
    
    assert result["pdf_path"] is not None
    assert result["excel_path"] is not None
    assert Path(result["pdf_path"]).exists()
    assert Path(result["excel_path"]).exists()
    
    # Verify Excel has 6 sheets
    import openpyxl
    wb = openpyxl.load_workbook(result["excel_path"])
    assert len(wb.sheetnames) == 6
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_report_integration.py -v`

- [ ] **Step 3: Commit**

```bash
git commit -m "test: add end-to-end report pipeline integration test"
```

---

## Summary: Task Dependency Graph

```
Phase 1 (Data Layer):
  Task 1 (Config) ──┐
  Task 2 (Models) ──┤── Task 3 (Translator++) ── Task 4 (Backfill CLI)
  Task 5 (Deps)  ───┘

Phase 2 (Report Output):
  Task 6 (Charts) ──┐
  Task 7 (CSS)    ──┤
  Task 8 (PDF)    ──┤── Task 12 (Wiring) ── Task 13 (Integration)
  Task 9 (Email)  ──┤
  Task 10 (Analytics)┤
  Task 11 (Excel) ──┘
```

Phase 1 tasks are sequential (1→2→3→4). Phase 2 tasks 6-11 can be parallelized, then converge at Task 12 (wiring).

---

## Plan Review Resolutions

Plan review performed 2026-04-06. Verdict: Needs Revision (Minor). All fixes applied.

### Critical fixes (C1-C4, applied in-place above)

- **C1**: All `_connect()` calls replaced with `get_conn()` (the actual function in models.py).
- **C2**: `_is_transient()` replaced with `_is_transient_error()`. `self._backoff()` replaced with inline return pattern.
- **C3**: DDL insertion instruction updated to add inside the existing `executescript()` string block, with indexes as separate `conn.execute()` calls.
- **C4**: `_config_val()` replaced with `from qbu_crawler import config as _cfg` + `_cfg.TRANSLATE_MAX_RETRIES`.

### Important fixes (I1-I7)

- **I1 (Excel signature)**: The 6-sheet rewrite replaces the function at line 148. The alias at line 586 (`_legacy_generate_excel`) and wrapper at line 858 (`generate_excel`) must be updated to call the new function. Implementer should search for all callers.
- **I2 (render_report_html signature)**: `asset_dir` parameter becomes optional with default `None`. Update callers `generate_pdf_report()` and `write_report_html_preview()` to pass `None` or omit it.
- **I3 (plotly.js path)**: Fixed to use `plotly.offline.get_plotlyjs()` official API.
- **I4 (missing test assertion)**: Added `rating` and `product_sku` assertions to `test_get_pending_translations_includes_product_name`.
- **I5 (Task 10 granularity)**: Task 10 should be decomposed during implementation into 3 sub-tasks: (10a) report_common.py health index + competitive gap, (10b) report_analytics.py feature clustering, (10c) report_llm.py generate_report_insights. Each sub-task has its own test-implement-commit cycle.
- **I6 (Backfill re-translation)**: The backfill command resets `translate_status=NULL`, causing re-translation. This is by design: the new combined prompt produces both translation and analysis together. **Existing snapshot-based reports are unaffected** since they freeze data. Document this in the CLI `--help` text.
- **I7 (sync_review_labels)**: Keep `sync_review_labels()` call in `report_snapshot.py` as-is during transition. It is idempotent and cheap. The rule-engine labels serve as fallback when `review_analysis` data is missing.

### Additional steps (from suggestions)

- **S4**: Add a step to update `.env.example` with the 5 new `REPORT_*` threshold variables. Include in Task 1 commit.
- **S5**: The `_build_analysis_prompt()` should include instruction text: "Product name and rating are provided per-review for context-aware analysis." Applied in Task 3 prompt.
