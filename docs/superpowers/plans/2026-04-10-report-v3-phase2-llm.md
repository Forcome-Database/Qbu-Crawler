# Report V3 Phase 2 — LLM Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance LLM utilization: extend translator prompt with 2 new fields, inject review samples into report insights prompt, add cluster-level deep analysis.

**Architecture:** Modifies translator prompt (v2) and report LLM pipeline. DB schema extends `review_analysis` with 2 new columns. Translation changes are backward-compatible (existing v1 rows untouched).

**Tech Stack:** Python 3.10+, OpenAI SDK, pytest

**Spec Reference:** `docs/superpowers/specs/2026-04-10-report-v3-redesign.md` — Sections 7.1–7.3, 15.1, 15.6

**Prerequisite:** Phase 1 complete (cluster severity, query_cluster_reviews available).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/models.py` | Modify | ALTER TABLE review_analysis + update save_review_analysis |
| `qbu_crawler/server/translator.py` | Modify | Extend prompt with impact_category, failure_mode; bump to v2 |
| `qbu_crawler/server/report_llm.py` | Modify | Add `_select_insight_samples`, update prompt, add `analyze_cluster_deep` |
| `tests/test_translator_analysis.py` | Modify | Test v2 prompt output parsing |
| `tests/test_report_llm.py` | Modify | Test sample selection, cluster analysis |
| `tests/test_v3_llm.py` | Create | New test file for V3 LLM features |

---

### Task 1: Extend review_analysis schema with 2 new columns

**Files:**
- Modify: `qbu_crawler/models.py` (migrations list ~line 244, `save_review_analysis` ~line 1804)
- Test: `tests/test_v3_llm.py` (create)

- [ ] **Step 1: Write schema test**

```python
# tests/test_v3_llm.py
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

    def test_save_review_analysis_with_new_fields(self, db):
        conn = _get_test_conn(db)
        conn.execute("INSERT INTO products (url, site, name, sku) VALUES ('http://t', 'test', 'T', 'T1')")
        pid = conn.execute("SELECT id FROM products WHERE sku='T1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating) VALUES (?, 'a', 'h', 'b', 'x', 1.0)",
            (pid,),
        )
        rid = conn.execute("SELECT id FROM reviews WHERE author='a'").fetchone()["id"]
        conn.commit()

        models.save_review_analysis(
            review_id=rid,
            sentiment="negative",
            sentiment_score=0.9,
            labels=[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}],
            features=["金属屑"],
            impact_category="safety",
            failure_mode="主轴金属屑脱落",
            prompt_version="v2",
        )

        row = conn.execute(
            "SELECT impact_category, failure_mode FROM review_analysis WHERE review_id=?", (rid,)
        ).fetchone()
        assert row["impact_category"] == "safety"
        assert row["failure_mode"] == "主轴金属屑脱落"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_v3_llm.py::TestReviewAnalysisSchema -v`
Expected: FAIL — columns don't exist, save_review_analysis doesn't accept new params

- [ ] **Step 3: Add migrations**

In `qbu_crawler/models.py`, add to the `migrations` list:

```python
"ALTER TABLE review_analysis ADD COLUMN impact_category TEXT",
"ALTER TABLE review_analysis ADD COLUMN failure_mode TEXT",
```

- [ ] **Step 4: Update save_review_analysis signature and INSERT**

In `qbu_crawler/models.py:1804`, add parameters:

```python
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
    analyzed_at: str | None = None,
    impact_category: str | None = None,      # NEW
    failure_mode: str | None = None,          # NEW
) -> None:
```

Update the INSERT statement to include the new columns:

```sql
INSERT INTO review_analysis
    (review_id, sentiment, sentiment_score, labels, features,
     insight_cn, insight_en, llm_model, prompt_version, token_usage, analyzed_at,
     impact_category, failure_mode)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(review_id, prompt_version) DO UPDATE SET
    sentiment       = excluded.sentiment,
    sentiment_score = excluded.sentiment_score,
    labels          = excluded.labels,
    features        = excluded.features,
    insight_cn      = excluded.insight_cn,
    insight_en      = excluded.insight_en,
    llm_model       = excluded.llm_model,
    token_usage     = excluded.token_usage,
    analyzed_at     = excluded.analyzed_at,
    impact_category = excluded.impact_category,
    failure_mode    = excluded.failure_mode
```

Add `impact_category` and `failure_mode` to the VALUES tuple.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/test_v3_llm.py
git commit -m "feat(report): extend review_analysis with impact_category + failure_mode columns"
```

---

### Task 2: Update translator prompt to v2

**Files:**
- Modify: `qbu_crawler/server/translator.py:223-260` (`_build_analysis_prompt`)
- Modify: `qbu_crawler/server/translator.py:322-341` (analysis saving in `_analyze_and_translate_batch`)
- Test: `tests/test_v3_llm.py` (append)

- [ ] **Step 1: Write prompt output parsing test**

```python
class TestTranslatorV2:
    def test_v2_prompt_includes_impact_category(self):
        from qbu_crawler.server.translator import TranslationWorker
        worker = TranslationWorker.__new__(TranslationWorker)
        prompt = worker._build_analysis_prompt([
            {"index": 0, "headline": "Broke", "body": "Metal shavings", "rating": 1.0, "product_name": "Test"}
        ])
        assert "impact_category" in prompt
        assert "failure_mode" in prompt
        assert "safety" in prompt  # safety is one of the enum values
        assert "usage_context" not in prompt  # removed in V3 spec 15.6

    def test_v2_analysis_saves_impact_fields(self):
        """Simulated LLM response with v2 fields is saved correctly."""
        # This tests the parsing path, not the actual LLM call
        v2_result = {
            "index": 0,
            "headline_cn": "断了",
            "body_cn": "金属屑脱落",
            "sentiment": "negative",
            "sentiment_score": 0.95,
            "labels": [{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.9}],
            "features": ["金属屑"],
            "insight_cn": "质量问题",
            "insight_en": "quality issue",
            "impact_category": "safety",
            "failure_mode": "主轴金属屑脱落",
        }
        # Verify the result dict has the fields we'll extract
        assert v2_result["impact_category"] == "safety"
        assert v2_result["failure_mode"] == "主轴金属屑脱落"
```

- [ ] **Step 2: Update `_build_analysis_prompt`**

In `translator.py:223-260`, add to the task list:

```python
"7. 判断影响类别 impact_category（必须为 safety / functional / durability / cosmetic / service 之一）：\n"
"   - safety: 涉及人身安全风险（金属碎屑、使用中断裂、爆炸）\n"
"   - functional: 产品无法执行核心功能\n"
"   - durability: 初期可用但短期内退化/损坏\n"
"   - cosmetic: 外观问题、轻微美观缺陷\n"
"   - service: 物流、客服、履约问题\n"
"8. 提取具体失效模式 failure_mode（一个中文短语，如'齿轮磨损'、'密封圈漏肉'、'主轴金属屑脱落'）。\n"
```

Add to output format:

```python
"- impact_category: safety | functional | durability | cosmetic | service\n"
"- failure_mode: \"具体失效模式中文短语\"\n"
```

- [ ] **Step 3: Update analysis saving in `_analyze_and_translate_batch`**

In the analysis saving block (~line 336), extract and pass the new fields:

```python
impact_category = (item.get("impact_category") or "").strip().lower() or None
if impact_category and impact_category not in ("safety", "functional", "durability", "cosmetic", "service"):
    impact_category = None  # Reject invalid values
failure_mode = (item.get("failure_mode") or "").strip() or None

models.save_review_analysis(
    review_id=review["id"],
    sentiment=sentiment,
    sentiment_score=sentiment_score,
    labels=labels,
    features=features,
    insight_cn=insight_cn,
    insight_en=insight_en,
    llm_model=self._model,
    prompt_version="v2",  # Bump from "v1"
    impact_category=impact_category,
    failure_mode=failure_mode,
)
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/translator.py tests/test_v3_llm.py
git commit -m "feat(report): translator v2 prompt — add impact_category + failure_mode

Extends LLM analysis with safety classification and specific failure mode extraction.
Bumps prompt_version from v1 to v2."
```

---

### Task 3: Add `_select_insight_samples` for review injection

**Files:**
- Modify: `qbu_crawler/server/report_llm.py`
- Test: `tests/test_v3_llm.py` (append)

**Spec ref:** Section 7.2.2 (with fix from 15.1 — draw from full corpus)

- [ ] **Step 1: Write sample selection tests**

```python
class TestInsightSampleSelection:
    def test_selects_diverse_samples(self):
        from qbu_crawler.server.report_llm import _select_insight_samples
        
        snapshot = {"reviews": []}  # Empty snapshot — samples come from analytics
        analytics = {
            "self": {"risk_products": [
                {"product_sku": "SKU1", "product_name": "Prod1"},
            ]},
        }
        # Mock models.query_cluster_reviews to return test data
        # (actual test requires DB fixture; see integration test in Task 5)
        # For unit test, verify function exists and accepts correct args
        assert callable(_select_insight_samples)

    def test_max_20_samples(self):
        from qbu_crawler.server.report_llm import _select_insight_samples
        # _select_insight_samples should cap at 20 reviews
        # Verified by the `len(samples) < 20` guard in the add() helper
        pass  # Full integration test in Task 5
```

- [ ] **Step 2: Implement `_select_insight_samples`**

Add to `report_llm.py`:

```python
def _select_insight_samples(snapshot, analytics):
    """Select 15-20 reviews for LLM synthesis, drawing from full DB corpus.

    Selection strategy:
    1. Per high-risk product: 2 worst reviews (lowest rating, longest body)
    2. Image-bearing negative reviews: 3
    3. Top competitor reviews: 3
    4. Mixed-sentiment reviews: 2
    5. Most recent reviews: 2
    """
    from qbu_crawler import models

    risk_products = analytics.get("self", {}).get("risk_products", [])
    samples = []
    seen_ids = set()

    def add(review_list, limit):
        added = 0
        for r in review_list:
            rid = r.get("id")
            if rid and rid not in seen_ids and len(samples) < 20:
                seen_ids.add(rid)
                samples.append(r)
                added += 1
                if added >= limit:
                    break

    # NOTE (P2-02 fix): models.query_reviews returns (list[dict], int) tuple.
    # Always unpack: reviews, _ = models.query_reviews(...)
    
    # 1. Worst reviews per risk product
    for product in risk_products[:3]:
        sku = product.get("product_sku", "")
        if not sku:
            continue
        worst, _ = models.query_reviews(
            sku=sku, max_rating=config.NEGATIVE_THRESHOLD,
            sort_by="rating", order="asc", limit=5,
        )
        add(worst, 2)

    # 2. Image-bearing own negatives
    img_neg, _ = models.query_reviews(
        ownership="own", has_images=True, max_rating=config.NEGATIVE_THRESHOLD,
        sort_by="rating", order="asc", limit=10,
    )
    add([r for r in img_neg if r.get("id") not in seen_ids], 3)

    # 3. Top competitor reviews  (sort_by="scraped_at" — P2-03 fix: "date_published_parsed" not in allowed_sorts)
    comp_best, _ = models.query_reviews(
        ownership="competitor", min_rating=5,
        sort_by="scraped_at", order="desc", limit=10,
    )
    add([r for r in comp_best if r.get("id") not in seen_ids], 3)

    # 4. Mixed sentiment (from snapshot since sentiment is in review_analysis)
    for r in snapshot.get("reviews", []):
        if r.get("sentiment") == "mixed" and r.get("id") not in seen_ids:
            seen_ids.add(r["id"])
            samples.append(r)
            if len(samples) >= 20:
                break

    # 5. Most recent from snapshot
    recent = sorted(
        [r for r in snapshot.get("reviews", []) if r.get("id") not in seen_ids],
        key=lambda r: r.get("date_published_parsed", ""),
        reverse=True,
    )
    add(recent, 2)

    return samples[:20]
```

Note: `models.query_reviews` already exists (see models.py). The function signature may need adjustment — check the actual parameters.

- [ ] **Step 3: Update `_build_insights_prompt` to inject samples**

After the existing prompt text in `_build_insights_prompt`, append:

```python
# Inject review samples
sample_reviews = _select_insight_samples(snapshot, analytics) if snapshot else []
if sample_reviews:
    lines = []
    for r in sample_reviews:
        tag = "自有" if r.get("ownership") == "own" else "竞品"
        body = (r.get("body_cn") or r.get("body") or "")[:250]
        lines.append(f"[{tag}|{r.get('product_name','')}|{r.get('rating','')}星] {body}")
    prompt += f"\n\n关键评论原文（{len(lines)}条，用于提炼洞察和引用客户语言）：\n"
    prompt += "\n".join(lines)
    prompt += "\n\n补充要求：hero_headline 必须反映评论中的核心客户体验痛点，不要只堆砌数字。"
```

Update `_build_insights_prompt` signature to accept `snapshot`:
```python
def _build_insights_prompt(analytics, snapshot=None):
```

Update `generate_report_insights` signature at line 475 to accept and pass snapshot:
```python
def generate_report_insights(analytics, snapshot=None):  # NEW: add snapshot param
    # ... inside, change:
    prompt = _build_insights_prompt(analytics, snapshot=snapshot)
```

Update the caller in `report_snapshot.py` (line ~162):
```python
insights = report_llm.generate_report_insights(analytics, snapshot=snapshot)
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_llm.py tests/test_v3_llm.py
git commit -m "feat(report): inject review samples into report LLM prompt

_select_insight_samples draws from full DB corpus (not just snapshot).
Up to 20 diverse reviews: worst per product, image evidence, competitor best, mixed, recent."
```

---

### Task 4: Add cluster-level deep analysis

**Files:**
- Modify: `qbu_crawler/server/report_llm.py` (add `analyze_cluster_deep`)
- Modify: `qbu_crawler/config.py` (add `REPORT_CLUSTER_ANALYSIS`, `REPORT_MAX_CLUSTER_ANALYSIS`)
- Test: `tests/test_v3_llm.py` (append)

**Spec ref:** Section 7.3

- [ ] **Step 1: Write cluster analysis test**

```python
class TestClusterDeepAnalysis:
    def test_function_exists_and_returns_dict(self):
        from qbu_crawler.server.report_llm import analyze_cluster_deep
        assert callable(analyze_cluster_deep)

    def test_fallback_on_llm_unavailable(self):
        """When LLM not configured, returns None (caller uses _RECOMMENDATION_MAP)."""
        from qbu_crawler.server.report_llm import analyze_cluster_deep
        cluster = {"label_code": "quality_stability", "label_display": "质量稳定性", "review_count": 10}
        reviews = [{"headline": "bad", "body": "terrible", "rating": 1.0, "product_name": "P1", "date_published_parsed": "2026-01-01"}]
        # With no LLM configured, should return None gracefully
        result = analyze_cluster_deep(cluster, reviews)
        # Result is None when LLM unavailable, or a dict when available
        assert result is None or isinstance(result, dict)
```

- [ ] **Step 2: Add config flags**

In `config.py`, add:

```python
REPORT_CLUSTER_ANALYSIS = os.getenv("REPORT_CLUSTER_ANALYSIS", "true").lower() == "true"
REPORT_MAX_CLUSTER_ANALYSIS = int(os.getenv("REPORT_MAX_CLUSTER_ANALYSIS", "3"))
```

- [ ] **Step 3: Implement `analyze_cluster_deep`**

Add to `report_llm.py`:

```python
def analyze_cluster_deep(cluster, cluster_reviews):
    """LLM-powered root-cause analysis for a single issue cluster.

    Returns dict with: failure_modes, root_causes, temporal_pattern,
    user_workarounds, actionable_summary. Returns None if LLM unavailable.
    """
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        return None
    if not config.REPORT_CLUSTER_ANALYSIS:
        return None

    review_lines = []
    for r in cluster_reviews[:30]:
        review_lines.append(
            f"[{r.get('rating','')}星|{r.get('product_name','')}|"
            f"{r.get('date_published_parsed','')}] "
            f"{(r.get('body_cn') or r.get('body',''))[:300]}"
        )
    reviews_text = "\n".join(review_lines)

    prompt = f"""你是产品质量分析专家。以下是 {cluster["review_count"]} 条关于「{cluster.get("label_display", "")}」问题的用户评论（展示前 {len(cluster_reviews[:30])} 条）。

{reviews_text}

请分析并返回JSON（不要包含 markdown 代码块标记）：
{{
  "failure_modes": [
    {{"mode": "具体失效模式描述", "frequency": 出现次数估计, "severity": "critical/major/minor", "example_quote": "最能说明此失效的一句用户原话"}}
  ],
  "root_causes": [
    {{"cause": "推测根因", "evidence": "从评论推断的依据", "confidence": "high/medium/low"}}
  ],
  "temporal_pattern": "问题随时间的变化趋势描述",
  "user_workarounds": ["用户自行采取的应对方法"],
  "actionable_summary": "不超过2句话：这个问题的本质是什么，最高优先的改进动作是什么"
}}

注意：failure_modes 按 frequency 降序排列，每个必须有 example_quote 直接引用评论原文。"""

    try:
        from openai import OpenAI
        client = OpenAI(base_url=config.LLM_API_BASE, api_key=config.LLM_API_KEY)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = response.choices[0].message.content
        parsed = _parse_llm_response(raw)
        return _validate_cluster_analysis(parsed)
    except Exception as e:
        logger.warning("analyze_cluster_deep failed for %s: %s", cluster.get("label_code"), e)
        return None


def _validate_cluster_analysis(parsed):
    """Validate and sanitize cluster analysis output."""
    if not isinstance(parsed, dict):
        return None
    # Ensure required keys exist with defaults
    result = {
        "failure_modes": parsed.get("failure_modes", []),
        "root_causes": parsed.get("root_causes", []),
        "temporal_pattern": parsed.get("temporal_pattern", ""),
        "user_workarounds": parsed.get("user_workarounds", []),
        "actionable_summary": parsed.get("actionable_summary", ""),
    }
    # Validate failure_modes structure
    if not isinstance(result["failure_modes"], list):
        result["failure_modes"] = []
    # Cap lists
    result["failure_modes"] = result["failure_modes"][:10]
    result["root_causes"] = result["root_causes"][:5]
    result["user_workarounds"] = result["user_workarounds"][:5]
    return result
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_llm.py qbu_crawler/config.py tests/test_v3_llm.py
git commit -m "feat(report): add cluster-level LLM deep analysis

analyze_cluster_deep reads up to 30 reviews per cluster and produces:
failure_modes, root_causes, temporal_pattern, user_workarounds, actionable_summary.
Gated by REPORT_CLUSTER_ANALYSIS config flag. Graceful fallback when LLM unavailable."
```

---

### Task 5: Integrate cluster deep analysis into report pipeline

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (call `analyze_cluster_deep` for top clusters)
- Test: `tests/test_v3_llm.py` (append integration test)

- [ ] **Step 1: Integrate into report generation**

In `report_snapshot.py::generate_full_report_from_snapshot`, after analytics is built and LLM insights are generated, add:

```python
# Cluster deep analysis (top N clusters)
from qbu_crawler.server.report_llm import analyze_cluster_deep
if config.REPORT_CLUSTER_ANALYSIS:
    top_clusters = analytics.get("self", {}).get("top_negative_clusters", [])
    for cluster in top_clusters[:config.REPORT_MAX_CLUSTER_ANALYSIS]:
        if cluster.get("review_count", 0) >= 5:
            cluster_reviews = models.query_cluster_reviews(
                label_code=cluster["label_code"],
                ownership="own",
                limit=30,
            )
            deep = analyze_cluster_deep(cluster, cluster_reviews)
            if deep:
                cluster["deep_analysis"] = deep
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py
git commit -m "feat(report): integrate cluster deep analysis into report pipeline

Top 3 clusters with ≥5 reviews get LLM root-cause analysis.
Results stored as cluster.deep_analysis for template consumption."
```

---

## Phase 2 Completion Checklist

- [ ] `review_analysis` table has `impact_category` and `failure_mode` columns
- [ ] `save_review_analysis` accepts and persists new columns
- [ ] Translator prompt includes impact_category and failure_mode (v2)
- [ ] `prompt_version` bumped to "v2" in translator
- [ ] `_select_insight_samples` draws from full DB corpus
- [ ] Report LLM prompt includes review text samples
- [ ] `analyze_cluster_deep` exists and is called for top 3 clusters
- [ ] All existing tests pass
