# P008 Phase 1: 日报正确性修复 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前日报系统中所有已知 Bug（N/A KPI、None 渲染、数据口径不一致、impact_category 管线断裂），并建立安全基础设施（三级分级 + 证据冻结），使日报在 Phase 2 重构前即可正确运行。

**Architecture:** 在现有 snapshot-first 架构上做增量修复。不新建入口函数，不改变模块结构，不拆分 report_analytics.py。所有改动均为现有函数的扩展或修复，保持向后兼容。

**Tech Stack:** Python 3.10+ / SQLite (WAL) / Jinja2 / pytest / openpyxl

**Design doc:** `docs/plans/P008-three-tier-report-system.md` Section 3

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `qbu_crawler/models.py` | DB schema (safety_incidents 建表, label_anomaly_flags 列, busy_timeout) + query 补字段 |
| Modify | `qbu_crawler/server/report.py` | query_cumulative_data() 补 impact_category/failure_mode |
| Modify | `qbu_crawler/server/report_snapshot.py` | freeze enrichment 补字段 + _meta 版本戳 + cumulative KPI 注入 |
| Modify | `qbu_crawler/server/report_analytics.py` | SAFETY_TIERS 替换 _SAFETY_KEYWORDS + compute_cluster_severity() |
| Modify | `qbu_crawler/server/report_common.py` | detect_safety_level() 共享函数 |
| Modify | `qbu_crawler/server/report_html.py` | V3 HTML Tab 2 + 全景 Tab 数据源修复 |
| Modify | `qbu_crawler/server/translator.py` | 标签一致性检查 + 安全证据冻结 |
| Modify | `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | Tab 2 填充 + 全景 Tab 改读累积 |
| Modify | `qbu_crawler/server/report_templates/quiet_day_report.html.j2` | N/A → 累积 KPI 显示 |
| Modify | `qbu_crawler/config.py` | SAFETY_TIERS_PATH env var |
| Create | `data/safety_tiers.json` | 安全关键词三级配置 |
| Create | `tests/test_p008_phase1.py` | Phase 1 所有测试 |

---

## Task 1: SQLite busy_timeout + safety_incidents 建表 + label_anomaly_flags 列

**Files:**
- Modify: `qbu_crawler/models.py:68-73` (get_conn), `qbu_crawler/models.py:76-248` (init_db)
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing tests for DB schema changes**

```python
# tests/test_p008_phase1.py
import sqlite3
import pytest
from qbu_crawler import models

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()
    return db_path

def test_busy_timeout_is_set(fresh_db):
    conn = models.get_conn()
    result = conn.execute("PRAGMA busy_timeout").fetchone()
    assert result[0] >= 5000
    conn.close()

def test_safety_incidents_table_exists(fresh_db):
    conn = sqlite3.connect(fresh_db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "safety_incidents" in tables
    conn.close()

def test_safety_incidents_columns(fresh_db):
    conn = sqlite3.connect(fresh_db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(safety_incidents)").fetchall()]
    for expected in ("review_id", "product_sku", "safety_level",
                     "failure_mode", "evidence_snapshot", "evidence_hash",
                     "detected_at", "created_at"):
        assert expected in cols
    conn.close()

def test_review_analysis_has_label_anomaly_flags(fresh_db):
    conn = sqlite3.connect(fresh_db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(review_analysis)").fetchall()]
    assert "label_anomaly_flags" in cols
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_p008_phase1.py -v`
Expected: FAIL — safety_incidents table not found, busy_timeout not 5000, label_anomaly_flags not in columns

- [ ] **Step 3: Implement get_conn() busy_timeout**

In `qbu_crawler/models.py:68-73`, add busy_timeout after existing PRAGMAs:

```python
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # P008: prevent SQLITE_BUSY under concurrent reports
    return conn
```

- [ ] **Step 4: Implement safety_incidents table in init_db()**

In `qbu_crawler/models.py`, add CREATE TABLE in init_db() after existing tables (before migrations section ~line 225):

```python
    # P008: Safety audit log
    CREATE TABLE IF NOT EXISTS safety_incidents (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id         INTEGER NOT NULL REFERENCES reviews(id),
        product_sku       TEXT NOT NULL,
        safety_level      TEXT NOT NULL,
        failure_mode      TEXT,
        evidence_snapshot TEXT NOT NULL,
        evidence_hash     TEXT NOT NULL,
        detected_at       TEXT NOT NULL,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    );
```

And add migration for label_anomaly_flags in the migrations list (~line 225-248):

```python
    "ALTER TABLE review_analysis ADD COLUMN label_anomaly_flags TEXT",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase1.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/test_p008_phase1.py
git commit -m "feat(db): add safety_incidents table, busy_timeout, label_anomaly_flags column"
```

---

## Task 2: Safety three-tier grading — configurable JSON + detect_safety_level()

**Files:**
- Create: `data/safety_tiers.json`
- Modify: `qbu_crawler/config.py`
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_analytics.py:265-306`
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Create safety_tiers.json**

```json
{
  "critical": [
    "metal shaving", "metal debris", "metal particle", "metal flake",
    "grease in food", "oil contamination", "black substance",
    "contamina", "foreign object", "foreign material",
    "injury", "injured", "cut myself", "sliced finger",
    "burned", "electric shock", "exploded", "shattered"
  ],
  "high": [
    "rust on blade", "rust on plate", "rusty", "corrosion",
    "worn blade", "chipped blade", "blade broke",
    "motor overheating", "smoking", "burning smell",
    "seal failure", "leaking grease"
  ],
  "moderate": [
    "misaligned", "not aligned", "loose screw",
    "bolt came off", "wobbles", "tips over", "unstable"
  ]
}
```

- [ ] **Step 2: Add SAFETY_TIERS_PATH to config.py**

```python
# In config.py, after existing env var loading
SAFETY_TIERS_PATH = os.getenv("SAFETY_TIERS_PATH", os.path.join(DATA_DIR, "safety_tiers.json"))
```

- [ ] **Step 3: Write failing tests for safety detection**

```python
# Append to tests/test_p008_phase1.py
from qbu_crawler.server.report_common import detect_safety_level, load_safety_tiers

def test_load_safety_tiers_from_json(tmp_path):
    import json
    cfg = {"critical": ["metal shaving"], "high": ["rust"], "moderate": ["loose screw"]}
    path = tmp_path / "tiers.json"
    path.write_text(json.dumps(cfg))
    tiers = load_safety_tiers(str(path))
    assert tiers["critical"] == ["metal shaving"]
    assert tiers["high"] == ["rust"]

def test_load_safety_tiers_fallback():
    """Non-existent path falls back to built-in defaults."""
    tiers = load_safety_tiers("/nonexistent/path.json")
    assert "critical" in tiers
    assert len(tiers["critical"]) > 0

def test_detect_safety_level_critical():
    assert detect_safety_level("Found metal shaving in my ground beef") == "critical"

def test_detect_safety_level_high():
    assert detect_safety_level("The blade is rusty after 2 months") == "high"

def test_detect_safety_level_moderate():
    assert detect_safety_level("Motor housing is misaligned with the body") == "moderate"

def test_detect_safety_level_none():
    assert detect_safety_level("Great product, works perfectly") is None

def test_detect_safety_level_returns_highest():
    """When multiple tiers match, return the highest."""
    assert detect_safety_level("Rusty blade caused injury to my hand") == "critical"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase1.py::test_detect_safety_level_critical -v`
Expected: FAIL — ImportError (detect_safety_level not defined)

- [ ] **Step 5: Implement load_safety_tiers() and detect_safety_level() in report_common.py**

Add at the top of `qbu_crawler/server/report_common.py` (after imports):

```python
import json as _json
from qbu_crawler import config as _config

# ── Safety Tier Detection ───────────────────────────────────────────
_BUILTIN_SAFETY_TIERS = {
    "critical": [
        "metal shaving", "metal debris", "metal particle", "metal flake",
        "grease in food", "oil contamination", "black substance",
        "contamina", "foreign object", "foreign material",
        "injury", "injured", "cut myself", "sliced finger",
        "burned", "electric shock", "exploded", "shattered",
    ],
    "high": [
        "rust on blade", "rust on plate", "rusty", "corrosion",
        "worn blade", "chipped blade", "blade broke",
        "motor overheating", "smoking", "burning smell",
        "seal failure", "leaking grease",
    ],
    "moderate": [
        "misaligned", "not aligned", "loose screw",
        "bolt came off", "wobbles", "tips over", "unstable",
    ],
}

_SAFETY_TIER_ORDER = ["critical", "high", "moderate"]

def load_safety_tiers(path: str | None = None) -> dict:
    path = path or getattr(_config, "SAFETY_TIERS_PATH", None)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return _json.load(f)
        except (FileNotFoundError, _json.JSONDecodeError):
            pass
    return _BUILTIN_SAFETY_TIERS

_safety_tiers_cache: dict | None = None

def _get_safety_tiers() -> dict:
    global _safety_tiers_cache
    if _safety_tiers_cache is None:
        _safety_tiers_cache = load_safety_tiers()
    return _safety_tiers_cache

def detect_safety_level(text: str) -> str | None:
    """Return highest matching safety tier ('critical'/'high'/'moderate') or None."""
    text_lower = text.lower()
    tiers = _get_safety_tiers()
    for level in _SAFETY_TIER_ORDER:
        keywords = tiers.get(level, [])
        if any(kw in text_lower for kw in keywords):
            return level
    return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase1.py -k "safety" -v`
Expected: All 7 safety tests PASS

- [ ] **Step 7: Update report_analytics.py to use SAFETY_TIERS**

In `qbu_crawler/server/report_analytics.py:265-306`, replace `_SAFETY_KEYWORDS` with calls to `detect_safety_level()`:

Replace lines 265-271 (`_SAFETY_KEYWORDS` definition) with:
```python
from qbu_crawler.server.report_common import detect_safety_level

# _SAFETY_KEYWORDS removed — replaced by configurable SAFETY_TIERS in report_common.py
_SAFETY_SEVERITY_BONUS = {"critical": 5, "high": 3, "moderate": 1}
```

Replace lines 301-306 in `compute_cluster_severity()`:
```python
    # Old code:
    # has_safety = False
    # for r in reviews_in_cluster:
    #     text = f"{r.get('headline', '')} {r.get('body', '')}".lower()
    #     if any(kw in text for kw in _SAFETY_KEYWORDS):
    #         has_safety = True
    #         break

    # P008: Three-tier safety grading
    max_safety_level = None
    for r in reviews_in_cluster:
        text = f"{r.get('headline', '')} {r.get('body', '')}"
        level = detect_safety_level(text)
        if level == "critical":
            max_safety_level = "critical"
            break  # can't get higher
        if level and (max_safety_level is None or
                      _SAFETY_SEVERITY_BONUS.get(level, 0) > _SAFETY_SEVERITY_BONUS.get(max_safety_level, 0)):
            max_safety_level = level
    
    # Also check LLM impact_category as supplementary signal
    if max_safety_level is None:
        for r in reviews_in_cluster:
            if r.get("impact_category") == "safety":
                max_safety_level = "moderate"
                break

    safety_bonus = _SAFETY_SEVERITY_BONUS.get(max_safety_level, 0)
```

Then replace `score += 3 if has_safety else 0` with `score += safety_bonus`.

- [ ] **Step 8: Run existing analytics tests to verify no regressions**

Run: `uv run pytest tests/test_report_analytics.py -v --tb=short`
Expected: All existing tests PASS (safety keyword behavior preserved with new API)

- [ ] **Step 9: Commit**

```bash
git add data/safety_tiers.json qbu_crawler/config.py qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py tests/test_p008_phase1.py
git commit -m "feat(safety): three-tier safety grading with configurable JSON keywords"
```

---

## Task 3: impact_category / failure_mode 端到端管线修复

**Files:**
- Modify: `qbu_crawler/server/report.py:1048-1091` (query_cumulative_data)
- Modify: `qbu_crawler/models.py:1912-1961` (get_reviews_with_analysis)
- Modify: `qbu_crawler/server/report_snapshot.py:307-311` (freeze enrichment)
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase1.py
def test_query_cumulative_data_includes_impact_category(fresh_db):
    """query_cumulative_data() must SELECT impact_category and failure_mode."""
    from qbu_crawler.server import report
    # Insert a product and review with analysis
    conn = models.get_conn()
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://test.com/p1", "Test Product", "SKU001", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating) VALUES (?, ?, ?, ?, ?)",
                 (1, "Tester", "Title", "Body text", 4.0))
    conn.execute("""INSERT INTO review_analysis 
                    (review_id, sentiment, sentiment_score, labels, features, 
                     insight_cn, insight_en, impact_category, failure_mode, llm_model, prompt_version)
                    VALUES (1, 'positive', 0.9, '[]', '[]', '', '', 'safety', 'rust_corrosion', 'test', 'v1')""")
    conn.commit()
    conn.close()
    
    products, reviews = report.query_cumulative_data()
    assert len(reviews) == 1
    assert reviews[0]["impact_category"] == "safety"
    assert reviews[0]["failure_mode"] == "rust_corrosion"

def test_get_reviews_with_analysis_includes_impact_fields(fresh_db):
    conn = models.get_conn()
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://test.com/p1", "Test Product", "SKU001", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating) VALUES (?, ?, ?, ?, ?)",
                 (1, "Tester", "Title", "Body", 3.0))
    conn.execute("""INSERT INTO review_analysis 
                    (review_id, sentiment, sentiment_score, labels, features,
                     insight_cn, insight_en, impact_category, failure_mode, llm_model, prompt_version)
                    VALUES (1, 'negative', 0.2, '[]', '[]', '', '', 'functional', 'motor_failure', 'test', 'v1')""")
    conn.commit()
    conn.close()
    
    reviews = models.get_reviews_with_analysis([1])
    assert len(reviews) == 1
    assert reviews[0]["impact_category"] == "functional"
    assert reviews[0]["failure_mode"] == "motor_failure"

def test_freeze_snapshot_enriches_impact_fields(fresh_db):
    """freeze_report_snapshot() must copy impact_category/failure_mode into snapshot reviews."""
    from qbu_crawler.server.report_snapshot import _enrich_reviews_with_analysis
    reviews = [{"id": 1, "product_id": 1}]
    analysis = {1: {
        "sentiment": "negative",
        "analysis_labels": "[]",
        "analysis_features": "[]",
        "analysis_insight_cn": "",
        "analysis_insight_en": "",
        "impact_category": "safety",
        "failure_mode": "metal_contamination",
    }}
    enriched = _enrich_reviews_with_analysis(reviews, analysis)
    assert enriched[0]["impact_category"] == "safety"
    assert enriched[0]["failure_mode"] == "metal_contamination"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase1.py -k "impact" -v`
Expected: FAIL — impact_category/failure_mode not in query results

- [ ] **Step 3: Fix query_cumulative_data() in report.py**

In `qbu_crawler/server/report.py`, around line 1074-1078, add two fields to the SELECT:

```python
                ra.sentiment,
                ra.sentiment_score,
                ra.labels   AS analysis_labels,
                ra.features AS analysis_features,
                ra.insight_cn AS analysis_insight_cn,
                ra.insight_en AS analysis_insight_en,
                ra.impact_category,           -- P008: safety pipeline
                ra.failure_mode               -- P008: safety pipeline
```

- [ ] **Step 4: Fix get_reviews_with_analysis() in models.py**

In `qbu_crawler/models.py`, around line 1949-1954, add two fields to the SELECT:

```python
                ra.sentiment,
                ra.sentiment_score,
                ra.labels AS analysis_labels,
                ra.features AS analysis_features,
                ra.insight_cn AS analysis_insight_cn,
                ra.insight_en AS analysis_insight_en,
                ra.impact_category,           -- P008: safety pipeline
                ra.failure_mode               -- P008: safety pipeline
```

- [ ] **Step 5: Fix freeze_report_snapshot() enrichment in report_snapshot.py**

In `qbu_crawler/server/report_snapshot.py`, around line 307-311, extend the key list:

```python
            for _key in ("sentiment", "analysis_features", "analysis_labels",
                         "analysis_insight_cn", "analysis_insight_en",
                         "impact_category", "failure_mode"):  # P008: safety pipeline
                _val = ea.get(_key)
                if _val is not None:
                    r.setdefault(_key, _val)
```

Note: The test references `_enrich_reviews_with_analysis` — if this internal function doesn't exist as a standalone, the test should call `freeze_report_snapshot()` instead and inspect the snapshot file output. Adjust test to match actual code structure.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase1.py -k "impact" -v`
Expected: All 3 impact tests PASS

- [ ] **Step 7: Run full existing test suite to check for regressions**

Run: `uv run pytest tests/test_report_snapshot.py tests/test_report.py -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 8: Commit**

```bash
git add qbu_crawler/server/report.py qbu_crawler/models.py qbu_crawler/server/report_snapshot.py tests/test_p008_phase1.py
git commit -m "fix(pipeline): add impact_category/failure_mode to cumulative query, analysis fetch, and snapshot enrichment"
```

---

## Task 4: 累积 KPI 所有模式永远计算（消灭 N/A）

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:683-740` (generate_report_from_snapshot)
- Modify: `qbu_crawler/server/report_templates/quiet_day_report.html.j2:196-201`
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase1.py
def test_quiet_mode_has_cumulative_kpis(fresh_db, tmp_path):
    """In quiet mode, cumulative_kpis must be populated (not empty/N/A)."""
    from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
    
    # Create a minimal snapshot with cumulative data but empty window
    snapshot = {
        "logical_date": "2026-04-14",
        "data_since": "2026-04-14T00:00:00+08:00",
        "data_until": "2026-04-15T00:00:00+08:00",
        "products": [],
        "reviews": [],
        "cumulative": {
            "products": [
                {"name": "Test", "sku": "SKU1", "rating": 4.5, "review_count": 10,
                 "ownership": "own", "site": "test", "price": 100, "stock_status": "in_stock"}
            ],
            "reviews": [
                {"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                 "headline": "Great", "body": "Works well", "sentiment": "positive",
                 "analysis_labels": "[]"}
            ],
        },
    }
    
    result = generate_report_from_snapshot(
        snapshot, send_email=False, output_dir=str(tmp_path)
    )
    
    # The result should contain cumulative_kpis with real values
    assert result.get("cumulative_kpis") is not None
    assert result["cumulative_kpis"].get("health_index") is not None
    assert result["cumulative_kpis"]["health_index"] != "N/A"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase1.py::test_quiet_mode_has_cumulative_kpis -v`
Expected: FAIL — cumulative_kpis is None or missing health_index

- [ ] **Step 3: Implement cumulative KPI injection in generate_report_from_snapshot()**

In `qbu_crawler/server/report_snapshot.py`, in `generate_report_from_snapshot()` (~line 683), add cumulative KPI computation before the mode routing:

```python
def generate_report_from_snapshot(snapshot, send_email=True, output_dir=None, ...):
    # ... existing setup code ...
    
    # P008: Always compute cumulative KPIs — never allow N/A
    cumulative_data = snapshot.get("cumulative", {})
    cumulative_reviews = cumulative_data.get("reviews", [])
    cumulative_products = cumulative_data.get("products", [])
    if cumulative_reviews:
        from qbu_crawler.server.report_common import compute_health_index
        own_reviews = [r for r in cumulative_reviews if r.get("ownership") == "own"]
        own_negative = [r for r in own_reviews if (r.get("rating") or 5) <= 2]
        health_idx, health_conf = compute_health_index(own_reviews)
        cumulative_kpis = {
            "health_index": round(health_idx, 1),
            "health_confidence": health_conf,
            "own_review_rows": len(own_reviews),
            "own_negative_review_rate": round(len(own_negative) / len(own_reviews) * 100, 1) if own_reviews else 0,
            "own_negative_review_rate_display": f"{round(len(own_negative) / len(own_reviews) * 100, 1)}%" if own_reviews else "0%",
            "high_risk_count": 0,  # computed in full analytics, fallback 0
        }
    else:
        cumulative_kpis = {
            "health_index": "—",
            "health_confidence": "no_data",
            "own_review_rows": 0,
            "own_negative_review_rate_display": "—",
            "high_risk_count": 0,
        }
    
    # Make cumulative_kpis available to all mode renderers
    # ... pass to template context ...
```

The exact injection point depends on how the current code passes data to templates. The key principle: `cumulative_kpis` must be computed BEFORE the mode routing (full/change/quiet) and passed to ALL templates.

- [ ] **Step 4: Fix quiet_day_report.html.j2 to use cumulative_kpis**

In `qbu_crawler/server/report_templates/quiet_day_report.html.j2`, replace lines 196-201:

```html
<!-- Old: kpis.get("health_index", "N/A") -->
<!-- New: use cumulative_kpis passed from generate_report_from_snapshot -->
{% set _ckpi = cumulative_kpis if cumulative_kpis is defined else {} %}
<strong class="kpi-value" style="color:var(--accent);">{{ _ckpi.get("health_index", "—") }}</strong>
<span class="kpi-delta delta-flat">/ 100</span>
...
<strong class="kpi-value">{{ _ckpi.get("own_negative_review_rate_display", "—") }}</strong>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase1.py::test_quiet_mode_has_cumulative_kpis -v`
Expected: PASS

- [ ] **Step 6: Run existing mode tests for regressions**

Run: `uv run pytest tests/test_v3_modes.py -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_templates/quiet_day_report.html.j2 tests/test_p008_phase1.py
git commit -m "fix(kpi): always compute cumulative KPIs in all report modes, eliminate N/A"
```

---

## Task 5: V3 HTML 双视角收口（Tab 2 + 全景 Tab）

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:138-144` (Tab 2)
- Modify: `qbu_crawler/server/report_html.py:21-81` (render context)
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase1.py
def test_v3_html_tab2_not_placeholder(fresh_db, tmp_path):
    """Tab 2 must contain actual change data, not placeholder text."""
    from qbu_crawler.server.report_html import render_v3_html
    
    snapshot = {
        "logical_date": "2026-04-15",
        "products": [],
        "reviews": [{"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                      "headline": "Good", "body": "Works", "author": "Test"}],
        "cumulative": {
            "products": [{"name": "Test", "sku": "SKU1", "ownership": "own", "rating": 4.5,
                          "review_count": 10, "site": "test", "price": 100, "stock_status": "in_stock"}],
            "reviews": [{"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                          "headline": "Good", "body": "Works", "sentiment": "positive",
                          "analysis_labels": "[]"}],
        },
    }
    analytics = {"mode": "incremental", "kpis": {}, "self": {"risk_products": [], "top_negative_clusters": []}}
    
    html_path = render_v3_html(snapshot, analytics, output_path=str(tmp_path / "test.html"))
    content = open(html_path, encoding="utf-8").read()
    
    assert "变化追踪将在后续版本中启用" not in content  # Placeholder text must be gone
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase1.py::test_v3_html_tab2_not_placeholder -v`
Expected: FAIL — placeholder text still present

- [ ] **Step 3: Replace Tab 2 placeholder in daily_report_v3.html.j2**

Replace lines 138-144 in `daily_report_v3.html.j2`:

```html
{% if mode != "baseline" %}
<section id="tab-changes" class="tab-panel" role="tabpanel">
  <h2 class="section-title">今日变化</h2>
  <p class="section-sub">采集窗口内的新增评论和产品数据变动。</p>

  {% set win_reviews = snapshot.reviews if snapshot.reviews is defined else [] %}
  {% if win_reviews %}
  <h3 style="margin-top:var(--sp-lg);">新增评论（{{ win_reviews|length }} 条）</h3>
  {% for r in win_reviews[:20] %}
  <div class="quote-block {% if r.rating is defined and r.rating <= 2 %}quote-negative{% elif r.rating is defined and r.rating >= 4 %}quote-positive{% else %}quote-neutral{% endif %}" style="margin-bottom:var(--sp-md);">
    <div class="quote-cn">{{ r.get("headline_cn") or r.get("headline", "") }}</div>
    <div class="quote-en">{{ r.get("body", "")[:200] }}{% if r.get("body", "")|length > 200 %}...{% endif %}</div>
    <div class="quote-meta">
      <span class="quote-stars">{{ "★" * (r.rating|int if r.rating else 0) }}{{ "☆" * (5 - (r.rating|int if r.rating else 0)) }}</span>
      <span>{{ r.get("author", "Anonymous") }}</span>
      <span>{{ r.get("product_name", r.get("product_sku", "")) }}</span>
    </div>
  </div>
  {% endfor %}
  {% else %}
  <div class="empty-state">本期无新增评论。</div>
  {% endif %}

  {# Price/stock/rating changes — reuse existing change detection data #}
  {% set _changes = changes if changes is defined else {} %}
  {% if _changes.get("price") or _changes.get("stock") or _changes.get("rating") %}
  <h3 style="margin-top:var(--sp-2xl);">产品数据变动</h3>
  {# Render change tables here — same structure as email_change.html.j2 #}
  {% include "_change_tables_partial.html.j2" ignore missing %}
  {% endif %}
</section>
{% endif %}
```

- [ ] **Step 4: Fix panorama Tab to read cumulative data**

Find the panorama tab section in `daily_report_v3.html.j2` (search for `tab-panorama`). Change the data source from `snapshot.reviews` to `snapshot.cumulative.reviews`:

```html
{# In the panorama/全景数据 tab section: #}
{% set _panorama_reviews = snapshot.cumulative.reviews if snapshot.cumulative is defined and snapshot.cumulative.reviews is defined else snapshot.reviews %}
```

Use `_panorama_reviews` instead of direct `snapshot.reviews` references throughout the panorama tab.

- [ ] **Step 5: Update render_v3_html() to pass cumulative data to template**

In `qbu_crawler/server/report_html.py`, ensure the template context includes the `snapshot` object with its `cumulative` field, and the `changes` dict from analytics:

```python
# In render_v3_html(), where template.render() is called:
html = template.render(
    snapshot=snapshot,
    analytics=analytics,
    changes=analytics.get("changes", {}),  # P008: for Tab 2
    # ... existing context ...
)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase1.py::test_v3_html_tab2_not_placeholder -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 qbu_crawler/server/report_html.py tests/test_p008_phase1.py
git commit -m "fix(html): populate V3 Tab 2 with window changes, panorama Tab reads cumulative data"
```

---

## Task 6: None 渲染人话化

**Files:**
- Modify: `qbu_crawler/server/report_templates/quiet_day_report.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase1.py
def test_none_rating_renders_as_dash():
    """When rating changes to None, template must render '—' or '已下架', not 'None'."""
    from jinja2 import Environment
    env = Environment()
    # Simulate the rating change rendering
    template = env.from_string(
        "{{ value if value is not none else '—' }}"
    )
    assert template.render(value=None) == "—"
    assert template.render(value=3.6) == "3.6"

def test_none_rating_not_styled_as_critical():
    """Rating becoming None (product delisted) should not use critical red color."""
    from jinja2 import Environment
    env = Environment()
    template = env.from_string(
        "{% if new_val is none %}color:var(--text-muted){% elif new_val < old_val %}color:var(--critical){% else %}color:var(--positive){% endif %}"
    )
    assert "text-muted" in template.render(new_val=None, old_val=3.6)
```

- [ ] **Step 2: Run tests to verify they pass (these are template logic tests, should pass immediately)**

Run: `uv run pytest tests/test_p008_phase1.py -k "none_rating" -v`
Expected: PASS (these test the rendering logic, not the template files)

- [ ] **Step 3: Fix rating rendering in quiet_day_report.html.j2**

Search for any remaining `"N/A"` default values and replace with `"—"`. Search for rating change rendering and add None check:

```html
{# Where rating changes are rendered: #}
<td style="text-align:center;font-weight:700;font-family:var(--font-mono);
  color:{% if item.get('new') is none %}var(--text-muted){% elif (item.get('new') or 0) > (item.get('old') or 0) %}var(--positive){% else %}var(--critical){% endif %};">
  {{ item.get("new") if item.get("new") is not none else "已下架" }}
</td>
```

- [ ] **Step 4: Fix daily_report_v3.html.j2 similar patterns**

Search for `N/A` in the template and replace with `—`. Fix negative_rate rendering at line 266:

```html
<!-- Old: {{ (p.negative_rate * 100) | round(0) if p.negative_rate else 'N/A' }}% -->
<!-- New: -->
{{ (p.negative_rate * 100) | round(0) if p.negative_rate is not none else '—' }}{% if p.negative_rate is not none %}%{% endif %}
```

- [ ] **Step 5: Run V3 HTML rendering tests**

Run: `uv run pytest tests/test_v3_html.py tests/test_v3_modes.py -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_templates/quiet_day_report.html.j2 qbu_crawler/server/report_templates/daily_report_v3.html.j2 tests/test_p008_phase1.py
git commit -m "fix(template): render None values as '—' or '已下架', not 'None' with critical red"
```

---

## Task 7: 产物版本戳 _meta

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py` (freeze_report_snapshot)
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase1.py
def test_snapshot_has_meta_field(fresh_db, tmp_path):
    """Frozen snapshots must include _meta with schema_version and generator_version."""
    import json
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot
    
    # Create a minimal workflow run and snapshot
    snapshot_path = str(tmp_path / "snapshot.json")
    snapshot = {
        "logical_date": "2026-04-16",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "products": [],
        "reviews": [],
        "cumulative": {"products": [], "reviews": []},
    }
    
    # Simulate writing with _meta injection
    from qbu_crawler.server.report_snapshot import _inject_meta
    enriched = _inject_meta(snapshot)
    
    assert "_meta" in enriched
    assert enriched["_meta"]["schema_version"] == "3"
    assert "generator_version" in enriched["_meta"]
    assert enriched["_meta"]["taxonomy_version"] == "v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase1.py::test_snapshot_has_meta_field -v`
Expected: FAIL — _inject_meta not defined

- [ ] **Step 3: Implement _inject_meta() in report_snapshot.py**

```python
# Add to report_snapshot.py
from qbu_crawler import __version__

def _inject_meta(snapshot: dict, tier: str = "daily") -> dict:
    """Add version metadata to snapshot for traceability."""
    snapshot["_meta"] = {
        "schema_version": "3",
        "generator_version": __version__,
        "taxonomy_version": snapshot.get("taxonomy_version", "v1"),
        "report_tier": tier,
    }
    return snapshot
```

Call `_inject_meta(snapshot)` in `freeze_report_snapshot()` before writing to disk.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase1.py::test_snapshot_has_meta_field -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase1.py
git commit -m "feat(meta): add _meta version stamps to snapshots for traceability"
```

---

## Task 8: 标签一致性检查 + 安全证据冻结（translator 回调）

**Files:**
- Modify: `qbu_crawler/server/translator.py:271-367` (_analyze_and_translate_batch)
- Modify: `qbu_crawler/models.py` (new helper: save_safety_incident)
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase1.py
import hashlib, json

def test_label_consistency_detects_mismatch():
    """Flag when negative label has high sentiment_score."""
    from qbu_crawler.server.report_common import check_label_consistency
    labels = [{"code": "quality_stability", "polarity": "negative", "confidence": 0.9}]
    anomalies = check_label_consistency(sentiment_score=0.85, labels=labels)
    assert len(anomalies) == 1
    assert anomalies[0]["type"] == "sentiment_label_mismatch"

def test_label_consistency_no_false_positive():
    """No flag when negative label has low sentiment_score (consistent)."""
    from qbu_crawler.server.report_common import check_label_consistency
    labels = [{"code": "quality_stability", "polarity": "negative", "confidence": 0.9}]
    anomalies = check_label_consistency(sentiment_score=0.2, labels=labels)
    assert len(anomalies) == 0

def test_save_safety_incident(fresh_db):
    """Safety incidents are stored with frozen evidence and SHA-256 hash."""
    evidence = {"review_text": "metal shavings in food", "product": "Grinder #22"}
    evidence_json = json.dumps(evidence, sort_keys=True)
    evidence_hash = hashlib.sha256(evidence_json.encode()).hexdigest()
    
    models.save_safety_incident(
        review_id=1, product_sku="SKU001", safety_level="critical",
        failure_mode="metal_contamination",
        evidence_snapshot=evidence_json, evidence_hash=evidence_hash,
    )
    
    conn = models.get_conn()
    rows = conn.execute("SELECT * FROM safety_incidents WHERE review_id = 1").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["safety_level"] == "critical"
    assert rows[0]["evidence_hash"] == evidence_hash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase1.py -k "label_consistency or save_safety" -v`
Expected: FAIL — functions not defined

- [ ] **Step 3: Implement check_label_consistency() in report_common.py**

```python
# Add to report_common.py
def check_label_consistency(sentiment_score: float, labels: list[dict]) -> list[dict]:
    """Detect mismatches between sentiment_score and label polarity."""
    anomalies = []
    for label in labels:
        polarity = label.get("polarity", "")
        code = label.get("code", "")
        if polarity == "negative" and sentiment_score > 0.7:
            anomalies.append({
                "type": "sentiment_label_mismatch",
                "label_code": code,
                "polarity": polarity,
                "sentiment_score": sentiment_score,
            })
        elif polarity == "positive" and sentiment_score < 0.3:
            anomalies.append({
                "type": "sentiment_label_mismatch",
                "label_code": code,
                "polarity": polarity,
                "sentiment_score": sentiment_score,
            })
    return anomalies
```

- [ ] **Step 4: Implement save_safety_incident() in models.py**

```python
# Add to models.py
def save_safety_incident(review_id: int, product_sku: str, safety_level: str,
                         failure_mode: str | None, evidence_snapshot: str,
                         evidence_hash: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO safety_incidents 
               (review_id, product_sku, safety_level, failure_mode,
                evidence_snapshot, evidence_hash, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (review_id, product_sku, safety_level, failure_mode,
             evidence_snapshot, evidence_hash),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase1.py -k "label_consistency or save_safety" -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Integrate into translator.py**

In `qbu_crawler/server/translator.py`, after `models.save_review_analysis()` call (~line 349), add:

```python
            # P008: Label consistency check
            if labels and sentiment_score is not None:
                from qbu_crawler.server.report_common import check_label_consistency
                anomalies = check_label_consistency(sentiment_score, labels)
                if anomalies:
                    import json as _json
                    models.update_review_analysis_flags(
                        review_id, _json.dumps(anomalies)
                    )
            
            # P008: Safety evidence freezing (runs on original English text)
            review_text = f"{review.get('headline', '')} {review.get('body', '')}"
            from qbu_crawler.server.report_common import detect_safety_level
            safety_level = detect_safety_level(review_text)
            if safety_level or impact_category == "safety":
                effective_level = safety_level or "moderate"
                import json as _json, hashlib
                evidence = {
                    "review_id": review["id"],
                    "headline": review.get("headline", ""),
                    "body": review.get("body", ""),
                    "rating": review.get("rating"),
                    "product_name": review.get("product_name", ""),
                    "product_sku": review.get("product_sku", ""),
                    "images": review.get("images"),
                    "detected_keywords": [kw for kw in _get_safety_tiers().get(effective_level, []) if kw in review_text.lower()] if safety_level else [],
                    "llm_impact_category": impact_category,
                }
                evidence_json = _json.dumps(evidence, sort_keys=True, ensure_ascii=False)
                evidence_hash = hashlib.sha256(evidence_json.encode()).hexdigest()
                try:
                    models.save_safety_incident(
                        review_id=review["id"],
                        product_sku=review.get("product_sku", ""),
                        safety_level=effective_level,
                        failure_mode=failure_mode,
                        evidence_snapshot=evidence_json,
                        evidence_hash=evidence_hash,
                    )
                except Exception:
                    log.warning("Failed to save safety incident for review %s", review["id"])
```

Also add `update_review_analysis_flags()` to models.py:

```python
def update_review_analysis_flags(review_id: int, flags_json: str):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE review_analysis SET label_anomaly_flags = ? WHERE review_id = ?",
            (flags_json, review_id),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 7: Run translator tests for regressions**

Run: `uv run pytest tests/test_translator.py tests/test_translator_analysis.py -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 8: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/models.py qbu_crawler/server/translator.py tests/test_p008_phase1.py
git commit -m "feat(safety): label consistency check + safety evidence freezing in translator pipeline"
```

---

## Task 9: Integration Test — 完整管线验证

**Files:**
- Test: `tests/test_p008_phase1.py`

- [ ] **Step 1: Write integration test**

```python
# Append to tests/test_p008_phase1.py
def test_p008_phase1_integration(fresh_db, tmp_path):
    """End-to-end: a safety review goes through the full pipeline correctly."""
    # 1. Insert a product
    conn = models.get_conn()
    conn.execute("INSERT INTO products (url, name, sku, site, ownership) VALUES (?, ?, ?, ?, ?)",
                 ("http://test.com/p1", "1HP Grinder #22", "1159179", "meatyourmaker", "own"))
    
    # 2. Insert a safety-relevant review
    conn.execute("""INSERT INTO reviews (product_id, author, headline, body, rating, ownership)
                    VALUES (1, 'TestUser', 'Dangerous metal debris', 
                    'Found metal shaving in my ground beef after using this grinder', 1.0, 'own')""")
    
    # 3. Insert analysis with impact_category = safety
    conn.execute("""INSERT INTO review_analysis 
                    (review_id, sentiment, sentiment_score, labels, features,
                     insight_cn, insight_en, impact_category, failure_mode, llm_model, prompt_version)
                    VALUES (1, 'negative', 0.05, 
                    '[{"code":"quality_stability","polarity":"negative","severity":"critical","confidence":0.95}]',
                    '["metal debris in food"]', '食品中发现金属碎屑', 'Metal debris found in food',
                    'safety', 'metal_contamination', 'test', 'v1')""")
    conn.commit()
    conn.close()
    
    # 4. Verify impact_category in cumulative query
    from qbu_crawler.server.report import query_cumulative_data
    products, reviews = query_cumulative_data()
    assert reviews[0]["impact_category"] == "safety"
    
    # 5. Verify safety detection
    from qbu_crawler.server.report_common import detect_safety_level
    level = detect_safety_level("Found metal shaving in my ground beef")
    assert level == "critical"
    
    # 6. Verify safety_incidents table can be written
    import json, hashlib
    evidence = json.dumps({"text": "metal shaving"}, sort_keys=True)
    models.save_safety_incident(
        review_id=1, product_sku="1159179", safety_level="critical",
        failure_mode="metal_contamination",
        evidence_snapshot=evidence,
        evidence_hash=hashlib.sha256(evidence.encode()).hexdigest(),
    )
    
    conn = models.get_conn()
    incidents = conn.execute("SELECT * FROM safety_incidents").fetchall()
    conn.close()
    assert len(incidents) == 1
    assert incidents[0]["safety_level"] == "critical"
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_p008_phase1.py::test_p008_phase1_integration -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short -x`
Expected: All tests PASS (no regressions)

- [ ] **Step 4: Final commit**

```bash
git add tests/test_p008_phase1.py
git commit -m "test(p008): add integration test verifying end-to-end safety pipeline"
```

---

## Post-Implementation Checklist

- [ ] Run `uv run pytest tests/ -v` — all green
- [ ] Manually trigger a daily workflow run and inspect the output:
  - Health index and negative rate must NOT be "N/A" in any mode
  - V3 HTML Tab 2 must show review data (not placeholder)
  - Panorama tab must show cumulative data
  - None ratings must render as "—" or "已下架"
  - Snapshot JSON must have `_meta` field
  - safety_incidents table must have entries for any safety-keyword reviews
- [ ] Compare output against `data/reports2/` baseline to verify improvements
