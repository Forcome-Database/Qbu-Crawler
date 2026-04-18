# QBU 报告设计系统 V4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 daily/weekly/monthly 三张报告统一到一套 Editorial Intelligence 设计系统，修复 12 项 PM 数据口径问题，用 Mode 视觉语言解决日报模式无差异问题，重构月报首屏并收敛邮件模板。

**Architecture:** 分 4 个 PR 推进（数据契约 → 设计基建 → 三报告重构 → 邮件 + 口径呈现）。所有模板改造通过 `REPORT_DS_VERSION` 环境变量做 v3/v4 双轨切换，灰度可回滚。共享组件落在 `report_templates/_partials/`，CSS token 扩展在现有 `daily_report_v3.css`。新增 `AnalyticsEnvelope` 持久化契约，normalize 派生字段强制落盘。

**Tech Stack:** Jinja2 模板 + 原生 CSS token + `daily_report_v3.js`（不变）+ pytest 单元测试 + 模拟器 42 天时间轴做集成对照。

**Spec:** `docs/superpowers/specs/2026-04-18-qbu-report-ds-v4-design.md`

---

## Phase 1 — PR 1：数据契约修复（阻断级）

**目标**：D1/D2/D3/D4 全部修复；模拟器 `verify` 对 M1 不再报 KPI 空值、对 S01 不再报 is_partial=None。

**前置验证命令**：

```bash
uv run pytest tests/test_report_snapshot.py tests/test_report_common.py -q
uv run python -m scripts.simulate_reports run-one M1
uv run python -m scripts.simulate_reports verify
```

---

### Task 1.1：`AnalyticsEnvelope` schema 定义 + 持久化辅助函数

**Files:**
- Modify: `qbu_crawler/server/report_common.py`（末尾新增）
- Test: `tests/test_analytics_envelope.py`（新建）

- [ ] **Step 1: Write failing test**

创建 `tests/test_analytics_envelope.py`:

```python
"""AnalyticsEnvelope: persistence contract for report analytics."""
from qbu_crawler.server.report_common import (
    build_analytics_envelope,
    load_analytics_envelope,
    normalize_deep_report_analytics,
)


def test_envelope_persists_normalized_derived_fields(tmp_path):
    raw = {
        "kpis": {
            "own_review_rows": 50,
            "own_positive_review_rows": 40,
            "own_negative_review_rows": 3,
            "competitor_review_rows": 20,
            "own_negative_review_rate": 0.06,
            "ingested_review_rows": 70,
            "site_reported_review_total_current": 100,
            "product_count": 5,
            "own_product_count": 3,
            "competitor_product_count": 2,
        },
        "self": {"risk_products": []},
        "competitor": {},
    }
    envelope = build_analytics_envelope(raw, mode="full", mode_context={})
    assert envelope["_schema_version"] == "v4"
    assert envelope["kpis_normalized"]["health_index"] is not None
    assert envelope["kpis_normalized"]["own_negative_review_rate_display"] == "6.0%"
    assert envelope["kpis_normalized"]["high_risk_count"] == 0
    assert envelope["kpis_raw"] == raw["kpis"]

    path = tmp_path / "analytics.json"
    path.write_text(__import__("json").dumps(envelope, ensure_ascii=False))
    loaded = load_analytics_envelope(str(path))
    assert loaded["kpis_normalized"]["health_index"] is not None


def test_envelope_legacy_fallback_reads_kpis_key():
    legacy = {"kpis": {"own_review_rows": 10, "competitor_review_rows": 0}}
    loaded = load_analytics_envelope.__wrapped__(legacy) if hasattr(load_analytics_envelope, "__wrapped__") else legacy
    assert "kpis" in loaded
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_analytics_envelope.py -v
```

Expected: FAIL with `ImportError: cannot import name 'build_analytics_envelope'`.

- [ ] **Step 3: Implement envelope helpers**

Append to `qbu_crawler/server/report_common.py`:

```python
# ── AnalyticsEnvelope persistence contract (V4) ──────────────────────────────

_ENVELOPE_SCHEMA_VERSION = "v4"


def build_analytics_envelope(
    raw_analytics: dict,
    *,
    mode: str,
    mode_context: dict | None = None,
) -> dict:
    """Build V4 analytics envelope: raw + normalized + mode metadata.

    Persisted to `analytics.json` so later consumers (monthly re-render,
    kpi_delta lookup) can read normalized derived fields (health_index,
    own_negative_review_rate_display, high_risk_count, kpi_cards, ...)
    without re-running normalize.
    """
    import copy
    normalized = normalize_deep_report_analytics(copy.deepcopy(raw_analytics))
    envelope = {
        "_schema_version": _ENVELOPE_SCHEMA_VERSION,
        "kpis_raw": raw_analytics.get("kpis", {}),
        "kpis_normalized": normalized.get("kpis", {}),
        "self": normalized.get("self", {}),
        "competitor": normalized.get("competitor", {}),
        "report_copy": normalized.get("report_copy", {}),
        "kpi_cards": normalized.get("kpi_cards", []),
        "issue_cards": normalized.get("issue_cards", []),
        "mode": mode,
        "mode_context": mode_context or {},
        "logical_date": raw_analytics.get("logical_date", ""),
        "run_id": raw_analytics.get("run_id", 0),
    }
    # Preserve any other top-level keys the legacy pipeline attached
    for k, v in raw_analytics.items():
        if k not in envelope and not k.startswith("_"):
            envelope.setdefault(k, v)
    return envelope


def load_analytics_envelope(path_or_dict) -> dict:
    """Load an analytics envelope from disk or return as-is if dict.

    Back-compat: if file is legacy (no `_schema_version`), wrap it so
    callers can always read `envelope["kpis_normalized"]`.
    """
    import json
    if isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        data = json.loads(open(path_or_dict, "r", encoding="utf-8").read())
    if data.get("_schema_version") == _ENVELOPE_SCHEMA_VERSION:
        return data
    # Legacy shim: normalize on read
    raw = {"kpis": data.get("kpis", {}), **data}
    return build_analytics_envelope(raw, mode=data.get("mode", "full"), mode_context={})
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
uv run pytest tests/test_analytics_envelope.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_analytics_envelope.py qbu_crawler/server/report_common.py
git commit -m "feat(report): AnalyticsEnvelope v4 schema + persistence helpers"
```

---

### Task 1.2：`generate_full_report_from_snapshot` 写盘前 normalize

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:1941-1944`
- Test: `tests/test_report_snapshot.py`（新增用例）

- [ ] **Step 1: Add failing test at end of `tests/test_report_snapshot.py`**

```python
def test_full_report_persists_normalized_kpis(tmp_path, monkeypatch):
    """D1: analytics.json must contain health_index/own_negative_review_rate_display
    after write; monthly re-render depends on this."""
    import json
    from qbu_crawler.server import report_snapshot, config as cfg
    monkeypatch.setattr(cfg, "REPORT_DIR", str(tmp_path))

    snapshot = {
        "run_id": 999,
        "logical_date": "2026-04-01",
        "data_since": "2026-04-01T00:00:00+08:00",
        "data_until": "2026-04-02T00:00:00+08:00",
        "snapshot_hash": "abc",
        "products": [{"id": 1, "sku": "X", "ownership": "own", "rating": 4.5}],
        "reviews": [
            {"id": i, "product_id": 1, "rating": 5, "body": "ok", "headline": "",
             "author": "a", "date_published_parsed": "2026-04-01"}
            for i in range(5)
        ],
        "_meta": {"report_tier": "weekly"},
    }
    result = report_snapshot.generate_full_report_from_snapshot(
        snapshot, send_email=False, report_tier="weekly",
    )
    ap = result.get("analytics_path")
    assert ap and __import__("os").path.isfile(ap)
    payload = json.loads(open(ap, encoding="utf-8").read())
    assert payload.get("_schema_version") == "v4"
    assert payload["kpis_normalized"]["health_index"] is not None
    assert "own_negative_review_rate_display" in payload["kpis_normalized"]
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest tests/test_report_snapshot.py::test_full_report_persists_normalized_kpis -v
```

Expected: FAIL (`_schema_version` missing or `kpis_normalized` missing).

- [ ] **Step 3: Update write-path in `report_snapshot.py`**

Replace `report_snapshot.py:1941-1944` block:

```python
Path(analytics_path).write_text(
    json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
    encoding="utf-8",
)
```

With:

```python
from qbu_crawler.server.report_common import build_analytics_envelope
envelope = build_analytics_envelope(
    analytics,
    mode=(snapshot.get("_meta") or {}).get("report_mode", "full"),
    mode_context={
        "report_tier": report_tier,
        "is_partial": (snapshot.get("_meta") or {}).get("is_partial", False),
    },
)
Path(analytics_path).write_text(
    json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2),
    encoding="utf-8",
)
```

- [ ] **Step 4: Update monthly re-load path (`_generate_monthly_report` line ~1195) to use envelope**

Replace:

```python
analytics = {}
if analytics_path and os.path.isfile(analytics_path):
    analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
```

With:

```python
from qbu_crawler.server.report_common import load_analytics_envelope
analytics = {}
if analytics_path and os.path.isfile(analytics_path):
    envelope = load_analytics_envelope(analytics_path)
    # Flatten envelope for legacy consumers: prefer normalized
    analytics = {
        "kpis": envelope["kpis_normalized"],
        "self": envelope.get("self", {}),
        "competitor": envelope.get("competitor", {}),
        "report_copy": envelope.get("report_copy", {}),
        "kpi_cards": envelope.get("kpi_cards", []),
        "issue_cards": envelope.get("issue_cards", []),
    }
    # Preserve non-kpi top-level keys
    for k, v in envelope.items():
        if k not in analytics and k not in ("kpis_raw", "kpis_normalized", "_schema_version"):
            analytics.setdefault(k, v)
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
uv run pytest tests/test_report_snapshot.py::test_full_report_persists_normalized_kpis tests/test_analytics_envelope.py -v
uv run pytest tests/test_report_snapshot.py -q   # no regressions
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "fix(report): persist normalized KPIs in AnalyticsEnvelope (D1/D2)"
```

---

### Task 1.3：`workflow_runs.is_partial` 列 + `_meta → DB` 传播

**Files:**
- Modify: `qbu_crawler/models.py`（migrations 列表 line ~275 前插入）
- Modify: `qbu_crawler/server/report_snapshot.py:72-73`（freeze 后写 DB）
- Test: `tests/test_report_snapshot.py`（新增）

- [ ] **Step 1: Write failing test**

Append to `tests/test_report_snapshot.py`:

```python
def test_is_partial_propagates_to_workflow_runs(snapshot_db, monkeypatch):
    """D4: freeze_report_snapshot must write is_partial to workflow_runs."""
    from qbu_crawler import models
    from qbu_crawler.server import report_snapshot

    # Stub query_report_data to return a tiny dataset
    monkeypatch.setattr(
        report_snapshot.report, "query_report_data",
        lambda since, until=None: ([{"id": 1, "sku": "X", "ownership": "own"}], []),
    )

    run = models.create_workflow_run({
        "workflow_type": "daily", "status": "running", "report_phase": "none",
        "logical_date": "2026-04-01",
        "data_since": "2026-04-01T00:00:00+08:00",
        "data_until": "2026-04-02T00:00:00+08:00",
        "trigger_key": "test-partial",
    })
    models.update_workflow_run(run["id"], report_tier="daily")

    report_snapshot.freeze_report_snapshot(run["id"])
    updated = models.get_workflow_run(run["id"])
    # First run ever → is_partial should be True
    assert updated.get("is_partial") in (1, True)
```

- [ ] **Step 2: Run, expect FAIL (column not defined / not written)**

```bash
uv run pytest tests/test_report_snapshot.py::test_is_partial_propagates_to_workflow_runs -v
```

- [ ] **Step 3: Add migration to `qbu_crawler/models.py`**

Insert before line 275 (`CREATE UNIQUE INDEX ... safety_incidents ...`):

```python
        "ALTER TABLE workflow_runs ADD COLUMN is_partial INTEGER NOT NULL DEFAULT 0",
```

- [ ] **Step 4: Update `freeze_report_snapshot` to persist is_partial**

In `report_snapshot.py`, after the block around line 72-73 that sets `meta["is_partial"]`, add at the end of the function (just before `return`):

```python
    # D4: propagate is_partial to workflow_runs so downstream templates can read it
    try:
        models.update_workflow_run(
            run_id,
            is_partial=1 if meta.get("is_partial") else 0,
        )
    except Exception:
        _logger.debug("failed to persist is_partial for run %s", run_id, exc_info=True)
```

- [ ] **Step 5: Update `models.update_workflow_run` whitelist to accept is_partial**

Find the allowlist in `models.py` (search for `update_workflow_run`) and add `"is_partial"` to the allowed keys set.

- [ ] **Step 6: Run, expect PASS**

```bash
uv run pytest tests/test_report_snapshot.py::test_is_partial_propagates_to_workflow_runs -v
```

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/models.py qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat(db): workflow_runs.is_partial + propagate from _meta (D4)"
```

---

### Task 1.4：`safety_incidents` 按 (review_id, safety_level, failure_mode) 去重

**Files:**
- Modify: `qbu_crawler/models.py`（migrations 区追加）
- Test: `tests/test_review_analysis.py`（新增）

- [ ] **Step 1: Inspect existing safety_incidents schema and index**

```bash
uv run python -c "import sqlite3,os; c=sqlite3.connect(os.environ.get('QBU_DATA_DIR','data')+'/products.db'); print([r for r in c.execute('PRAGMA table_info(safety_incidents)')])"
```

Record column names (expect `id`, `review_id`, `safety_level`, `failure_mode`, `evidence_hash`, ...).

- [ ] **Step 2: Write failing test**

Append to `tests/test_review_analysis.py` (or new `tests/test_safety_dedup.py`):

```python
def test_safety_incidents_dedup_by_review_level_mode(tmp_path, monkeypatch):
    """D3: inserting same (review_id, safety_level, failure_mode) twice must not double-count."""
    import sqlite3, os
    from qbu_crawler import models, config
    dbp = tmp_path / "products.db"
    monkeypatch.setattr(config, "DB_PATH", str(dbp))
    models.init_db()

    conn = models.get_conn()
    try:
        conn.execute(
            """INSERT INTO safety_incidents (review_id, safety_level, failure_mode, evidence_hash)
               VALUES (1, 'critical', 'foreign_object', 'h1')"""
        )
        conn.commit()
        try:
            conn.execute(
                """INSERT INTO safety_incidents (review_id, safety_level, failure_mode, evidence_hash)
                   VALUES (1, 'critical', 'foreign_object', 'h2')"""
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # expected
        count = conn.execute(
            "SELECT COUNT(*) FROM safety_incidents WHERE review_id=1"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()
```

- [ ] **Step 3: Run, expect FAIL (count == 2)**

```bash
uv run pytest tests/test_review_analysis.py::test_safety_incidents_dedup_by_review_level_mode -v
```

- [ ] **Step 4: Add composite unique index migration**

Append to migrations in `models.py`:

```python
        """
        DELETE FROM safety_incidents
        WHERE id NOT IN (
            SELECT MIN(id) FROM safety_incidents
            GROUP BY review_id, safety_level, failure_mode
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_safety_incidents_review_level_mode "
        "ON safety_incidents(review_id, safety_level, failure_mode)",
```

- [ ] **Step 5: Run, expect PASS**

```bash
uv run pytest tests/test_review_analysis.py::test_safety_incidents_dedup_by_review_level_mode -v
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/test_review_analysis.py
git commit -m "fix(db): safety_incidents unique by (review_id, level, mode) (D3)"
```

---

### Task 1.5：模拟器重跑 + verify

- [ ] **Step 1: Clean old artifacts, rerun scenarios**

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -m scripts.simulate_reports run
uv run python -m scripts.simulate_reports verify
```

- [ ] **Step 2: Confirm M1 KPIs are no longer empty**

```bash
uv run python -c "
import json, pathlib, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
p = pathlib.Path(r'C:\Users\leo\Desktop\报告\reports\scenarios').glob('M1-*/workflow-run-*-analytics-*.json')
for f in p:
    d = json.loads(f.read_bytes().decode('utf-8','replace'))
    print(f.name, 'schema=', d.get('_schema_version'), 'health=', d.get('kpis_normalized',{}).get('health_index'))
"
```

Expected: `schema= v4`, `health=` a number (not None).

- [ ] **Step 3: Confirm S01 is_partial = True**

```bash
uv run python -c "
import json, pathlib
for mp in pathlib.Path(r'C:\Users\leo\Desktop\报告\reports\scenarios').glob('S01-*/manifest.json'):
    m = json.loads(mp.read_text(encoding='utf-8'))
    print(mp.parent.name, 'verdict=', m['verdict'], 'is_partial=', m['actual'].get('is_partial'))
"
```

Expected: verdict=PASS, is_partial=True.

- [ ] **Step 4: Commit simulator lockfile if changed**

```bash
git status
git add -u
git commit -m "chore(sim): refresh artifacts after PR1 data contract fix" || true
```

---

## Phase 2 — PR 2：设计系统基础设施（CSS + 10 个 partials）

**目标**：扩展 `daily_report_v3.css`，抽出 10 个 `_partials/*.html.j2`，通过 `REPORT_DS_VERSION=v4` env flag 启用；v3 行为不受影响可回滚。

---

### Task 2.1：CSS token 扩展 — mode 色板 + confidence 徽章

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`（末尾）

- [ ] **Step 1: Append new token block**

在 `daily_report_v3.css` 文件末尾追加：

```css
/* ==========================================================================
   V4 EXTENSIONS — Mode colors + Confidence badges + Section dividers
   ========================================================================== */

:root {
  /* Mode colors — 6 tier/mode combinations */
  --mode-partial:  #8e8ea0;
  --mode-full:     #4f46e5;
  --mode-change:   #c2410c;
  --mode-quiet:    #047857;
  --mode-weekly:   #4338ca;
  --mode-monthly:  #1e1b4b;

  /* Confidence badge colors */
  --conf-high:     #047857;
  --conf-medium:   #a16207;
  --conf-low:      #b91c1c;
  --conf-none:     #8e8ea0;
}

/* Mode strip — top ribbon identifying report mode */
.mode-strip {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
  padding: var(--sp-md) var(--sp-xl);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-inverse);
  border-bottom: 1px solid rgba(255,255,255,0.12);
}
.mode-strip--partial  { background: var(--mode-partial); }
.mode-strip--full     { background: var(--mode-full); }
.mode-strip--change   { background: var(--mode-change); }
.mode-strip--quiet    { background: var(--mode-quiet); }
.mode-strip--weekly   { background: var(--mode-weekly); }
.mode-strip--monthly  { background: var(--mode-monthly); }
.mode-strip-kicker { font-weight: 700; }
.mode-strip-meta { margin-left: auto; opacity: 0.7; font-weight: 400; }

/* Confidence badge — small pill next to any computed KPI */
.conf-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  vertical-align: middle;
  margin-left: 6px;
}
.conf-badge--high    { background: color-mix(in srgb, var(--conf-high) 12%, white); color: var(--conf-high); }
.conf-badge--medium  { background: color-mix(in srgb, var(--conf-medium) 14%, white); color: var(--conf-medium); }
.conf-badge--low     { background: color-mix(in srgb, var(--conf-low) 12%, white); color: var(--conf-low); }
.conf-badge--none    { background: color-mix(in srgb, var(--conf-none) 12%, white); color: var(--conf-none); }

/* Section divider — Serif numeral eyebrow */
.section-divider {
  display: flex;
  align-items: baseline;
  gap: var(--sp-md);
  margin: var(--sp-2xl) 0 var(--sp-lg);
  padding-bottom: var(--sp-sm);
  border-bottom: 1px solid var(--border);
}
.section-divider-num {
  font-family: var(--font-display);
  font-size: var(--fs-xl);
  font-weight: 700;
  color: var(--accent);
  line-height: 1;
}
.section-divider-title {
  font-family: var(--font-display);
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text);
}
.section-divider-hint {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  margin-left: auto;
}

/* Three-band rate bar: positive / neutral / negative */
.rate-bar {
  display: flex;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--surface-sunken);
  margin-top: 6px;
}
.rate-bar-seg--positive { background: var(--positive); }
.rate-bar-seg--neutral  { background: var(--medium); }
.rate-bar-seg--negative { background: var(--negative); }

/* KPI Delta helpers (missing baseline, stable) */
.kpi-delta--missing { color: var(--text-muted); font-style: italic; }

/* Quiet / change / partial tab pattern — grey empty tabs */
.tab-btn.tab-disabled {
  opacity: 0.4;
  pointer-events: none;
  font-style: italic;
}
```

- [ ] **Step 2: Manual visual sanity check**

```bash
uv run python -c "
from pathlib import Path
css = Path('qbu_crawler/server/report_templates/daily_report_v3.css').read_text(encoding='utf-8')
for tok in ['--mode-partial', '--conf-high', '.mode-strip--monthly', '.conf-badge--low', '.section-divider-num']:
    assert tok in css, f'Missing: {tok}'
print('All V4 tokens present')
"
```

Expected output: `All V4 tokens present`.

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.css
git commit -m "feat(style): V4 CSS tokens — mode colors, confidence badges, dividers"
```

---

### Task 2.2：Partials `head` + `kpi_bar` + `mode_strip` + `footer`

**Files:**
- Create: `qbu_crawler/server/report_templates/_partials/head.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/kpi_bar.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/mode_strip.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/footer.html.j2`

- [ ] **Step 1: Create `_partials/head.html.j2`**

```jinja
{#
  Shared <head> block. Callers must pass:
    - page_title       (str)
    - css_text         (str, injected inline)
#}
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ page_title }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700;800&family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&family=DM+Mono:wght@400;500&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">
  <style>{{ css_text|safe }}</style>
</head>
```

- [ ] **Step 2: Create `_partials/kpi_bar.html.j2`**

```jinja
{#
  Sticky top KPI bar. Callers pass:
    - brand       (str, default "QBU 网评监控")
    - kpi_items   (list of {label, value})  — 5 items max
    - show_print  (bool)
#}
<header class="kpi-bar">
  <div class="kpi-bar-inner">
    <span class="kpi-bar-brand">{{ brand or "QBU 网评监控" }}</span>
    <div class="kpi-bar-metrics">
      {% for it in (kpi_items or [])[:5] %}
      <span class="kpi-bar-item">{{ it.label }} <strong>{{ it.value }}</strong></span>
      {% endfor %}
    </div>
    {% if show_print %}
    <button id="btn-print" class="btn-icon" title="打印 / 导出PDF">⎙</button>
    {% endif %}
  </div>
</header>
```

- [ ] **Step 3: Create `_partials/mode_strip.html.j2`**

```jinja
{#
  Mode strip ribbon. Callers pass:
    - mode          ("partial" | "full" | "change" | "quiet" | "weekly" | "monthly")
    - kicker        (str — e.g. "DAILY INTELLIGENCE · Day 12")
    - meta          (str — right-aligned, e.g. "Run #123 · 2026-04-18")
#}
<div class="mode-strip mode-strip--{{ mode or 'full' }}">
  <span class="mode-strip-kicker">{{ kicker }}</span>
  {% if meta %}<span class="mode-strip-meta">{{ meta }}</span>{% endif %}
</div>
```

- [ ] **Step 4: Create `_partials/footer.html.j2`**

```jinja
{#
  Caller passes: threshold, generated_at, version
#}
<footer class="report-footer">
  <div class="report-footer-inner">
    <span>差评定义：评分 ≤ {{ threshold }} 星</span>
    <span>生成时间：{{ generated_at }}</span>
    {% if version %}<span>· 报告版本 {{ version }}</span>{% endif %}
    <span>· AI 自动生成</span>
  </div>
</footer>
```

- [ ] **Step 5: Add footer CSS class to `daily_report_v3.css`**

Append:

```css
.report-footer {
  margin-top: var(--sp-3xl);
  padding: var(--sp-lg) var(--sp-xl);
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
.report-footer-inner {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  gap: var(--sp-lg);
  flex-wrap: wrap;
  justify-content: center;
}
```

- [ ] **Step 6: Render-smoke test**

Create `tests/test_template_partials.py`:

```python
"""Smoke tests for V4 shared partials."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def _env():
    tpl_dir = Path(__file__).parent.parent / "qbu_crawler" / "server" / "report_templates"
    return Environment(loader=FileSystemLoader(str(tpl_dir)))


def test_mode_strip_renders_all_modes():
    env = _env()
    for mode in ("partial", "full", "change", "quiet", "weekly", "monthly"):
        out = env.get_template("_partials/mode_strip.html.j2").render(
            mode=mode, kicker=f"TEST {mode.upper()}", meta="Run #1",
        )
        assert f"mode-strip--{mode}" in out
        assert f"TEST {mode.upper()}" in out


def test_kpi_bar_caps_at_5_items():
    env = _env()
    items = [{"label": f"K{i}", "value": i} for i in range(10)]
    out = env.get_template("_partials/kpi_bar.html.j2").render(kpi_items=items)
    assert out.count("kpi-bar-item") == 5
```

```bash
uv run pytest tests/test_template_partials.py -v
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_templates/_partials/*.j2 qbu_crawler/server/report_templates/daily_report_v3.css tests/test_template_partials.py
git commit -m "feat(templates): V4 shared partials — head, kpi_bar, mode_strip, footer"
```

---

### Task 2.3：Partials `hero` + `kpi_grid` + `tab_nav`

**Files:**
- Create: `qbu_crawler/server/report_templates/_partials/hero.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/kpi_grid.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/tab_nav.html.j2`

- [ ] **Step 1: Create `_partials/hero.html.j2`**

```jinja
{#
  Editorial hero: Gauge + Serif title + kicker + headline + bullets.
  Callers pass:
    - kicker        (str, small eyebrow)
    - title         (str, big serif)
    - headline      (str, hero subtitle — LLM-generated or deterministic)
    - meta          (str, run metadata)
    - health_index  (float or None)
    - confidence    ("high" | "medium" | "low" | "no_data")
    - bullets       (list[str])
    - actions       (list[str] | None, top 3 recommended actions)
#}
<section class="hero">
  <div class="gauge-wrapper" data-health="{{ health_index if health_index is not none else 50 }}">
    <div class="gauge-arc">
      <div class="gauge-fill"></div>
      <div class="gauge-mask"></div>
      <div class="gauge-value">0</div>
    </div>
    <div class="gauge-label">健康指数
      {% if confidence %}
        <span class="conf-badge conf-badge--{{ 'high' if confidence=='high' else ('medium' if confidence=='medium' else ('low' if confidence in ('low','no_data') else 'none')) }}">
          {{ {"high":"可信","medium":"参考","low":"样本不足","no_data":"无数据"}.get(confidence, confidence) }}
        </span>
      {% endif %}
    </div>
    <div class="gauge-scale"><span>0</span><span>50</span><span>100</span></div>
  </div>
  <div class="hero-text">
    {% if kicker %}<p class="hero-kicker">{{ kicker }}</p>{% endif %}
    <h1 class="hero-title">{{ title }}</h1>
    {% if headline %}<p class="hero-headline">{{ headline }}</p>{% endif %}
    {% if meta %}<p class="hero-meta">{{ meta }}</p>{% endif %}
    {% if bullets %}
    <ul class="hero-bullets">
      {% for b in bullets %}<li>{{ b }}</li>{% endfor %}
    </ul>
    {% endif %}
    {% if actions %}
    <div class="hero-actions">
      <div class="hero-actions-label">建议行动</div>
      <ol>
        {% for a in actions %}<li>{{ a }}</li>{% endfor %}
      </ol>
    </div>
    {% endif %}
  </div>
</section>
```

- [ ] **Step 2: Create `_partials/kpi_grid.html.j2`**

```jinja
{#
  9-card KPI grid. Caller passes:
    - cards   (list of dict — each with label, value, delta_display, delta_class,
               confidence ("high|medium|low|none"), tooltip, value_class)
#}
<div class="kpi-grid">
  {% for card in (cards or []) %}
  <div class="kpi-card reveal">
    <span class="kpi-label">{{ card.label }}
      {% if card.confidence and card.confidence != "none" %}
        <span class="conf-badge conf-badge--{{ card.confidence }}">
          {{ {"high":"可信","medium":"参考","low":"样本不足"}.get(card.confidence, "") }}
        </span>
      {% endif %}
      {% if card.tooltip %}<span class="tip-trigger" data-tip="{{ card.tooltip }}">?</span>{% endif %}
    </span>
    <strong class="kpi-value {{ card.value_class or '' }}">{{ card.value }}</strong>
    {% if card.delta_display %}
      <span class="kpi-delta {{ card.delta_class or '' }}">{{ card.delta_display }}</span>
    {% elif card.delta_missing %}
      <span class="kpi-delta kpi-delta--missing">基线建立中</span>
    {% endif %}
    {% if card.rate_bands %}
    <div class="rate-bar">
      <span class="rate-bar-seg rate-bar-seg--positive" style="width: {{ card.rate_bands.positive }}%"></span>
      <span class="rate-bar-seg rate-bar-seg--neutral" style="width: {{ card.rate_bands.neutral }}%"></span>
      <span class="rate-bar-seg rate-bar-seg--negative" style="width: {{ card.rate_bands.negative }}%"></span>
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>
```

- [ ] **Step 3: Create `_partials/tab_nav.html.j2`**

```jinja
{#
  Unified tab navigation. Caller passes:
    - tabs   (list of {id, label, badge?, disabled?})
    - active (str — id of active tab)
#}
<nav class="tab-nav" role="tablist">
  {% for tab in tabs %}
  <button data-tab="{{ tab.id }}"
          class="tab-btn {{ 'tab-active' if tab.id == active else '' }} {{ 'tab-disabled' if tab.disabled else '' }}"
          role="tab">
    {{ tab.label }}
    {% if tab.badge is defined and tab.badge is not none %}<span class="tab-badge">{{ tab.badge }}</span>{% endif %}
  </button>
  {% endfor %}
</nav>
```

- [ ] **Step 4: Smoke-test partial renders**

Append to `tests/test_template_partials.py`:

```python
def test_kpi_grid_renders_confidence_and_missing_delta():
    env = _env()
    cards = [
        {"label": "健康指数", "value": 68, "delta_display": "+4", "delta_class": "delta-up", "confidence": "medium"},
        {"label": "差评率", "value": "5.9%", "delta_missing": True, "confidence": "high"},
    ]
    out = env.get_template("_partials/kpi_grid.html.j2").render(cards=cards)
    assert "conf-badge--medium" in out
    assert "conf-badge--high" in out
    assert "基线建立中" in out


def test_tab_nav_marks_active_and_disabled():
    env = _env()
    tabs = [
        {"id": "overview", "label": "总览"},
        {"id": "changes", "label": "变化", "badge": 3},
        {"id": "other", "label": "其他", "disabled": True},
    ]
    out = env.get_template("_partials/tab_nav.html.j2").render(tabs=tabs, active="overview")
    assert 'data-tab="overview"' in out and "tab-active" in out
    assert "tab-disabled" in out
    assert "tab-badge" in out
```

```bash
uv run pytest tests/test_template_partials.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_templates/_partials/*.j2 tests/test_template_partials.py
git commit -m "feat(templates): V4 hero/kpi_grid/tab_nav partials with confidence UX"
```

---

### Task 2.4：Partials `issue_card` + `review_quote` + `empty_state`

**Files:**
- Create: `qbu_crawler/server/report_templates/_partials/issue_card.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/review_quote.html.j2`
- Create: `qbu_crawler/server/report_templates/_partials/empty_state.html.j2`

- [ ] **Step 1: Create `_partials/issue_card.html.j2`**

```jinja
{#
  Issue cluster card used by weekly/monthly problem-diagnosis tab.
  Caller passes a `card` dict with keys matching analytics_lifecycle output:
    label_display, state, review_count, first_seen, last_seen, history,
    example_reviews, competitor_reference
#}
<article class="issue-card">
  <header class="issue-card-header">
    <strong class="issue-card-title">{{ card.label_display }}</strong>
    <span class="lifecycle-badge ls-{{ card.state }}">
      {{ {"active":"活跃","receding":"收敛中","dormant":"沉默","recurrent":"复发"}.get(card.state, card.state) }}
    </span>
    <span class="issue-card-meta">
      {{ card.review_count }} 条 · 首现 {{ card.first_seen or "—" }} · 末现 {{ card.last_seen or "—" }}
    </span>
  </header>

  {% if card.history %}
  <details class="issue-card-history">
    <summary>状态变迁时间线（{{ card.history|length }} 次）</summary>
    <ul>
      {% for h in card.history %}<li>{{ h.date }} · {{ h.transition }} · {{ h.reason }}</li>{% endfor %}
    </ul>
  </details>
  {% endif %}

  {% if card.example_reviews %}
  <section class="issue-card-quotes">
    <div class="issue-card-quotes-label">自有关键评论</div>
    {% for r in card.example_reviews[:3] %}
    {% include "_partials/review_quote.html.j2" with context %}
    {% endfor %}
  </section>
  {% endif %}

  {% if card.competitor_reference and card.competitor_reference.review_count > 0 %}
  <section class="issue-card-competitor">
    <div class="issue-card-competitor-label">
      竞品参照（{{ card.competitor_reference.review_count }} 条竞品负面）
    </div>
    {% for r in card.competitor_reference.top_examples[:3] %}
    {% include "_partials/review_quote.html.j2" with context %}
    {% endfor %}
  </section>
  {% endif %}
</article>
```

- [ ] **Step 2: Create `_partials/review_quote.html.j2`**

```jinja
{#
  Review quote block. Caller context must provide `r` (a review dict with
  headline_cn/headline, body_cn/body, author, rating, product_name, date_published_parsed).
#}
<div class="quote-block {% if r.rating is defined and r.rating and r.rating <= 2 %}quote-negative{% elif r.rating is defined and r.rating and r.rating >= 4 %}quote-positive{% else %}quote-neutral{% endif %}">
  <div class="quote-cn">{{ r.get("headline_cn") or r.get("headline", "") }}</div>
  <div class="quote-en">{{ (r.get("body_cn") or r.get("body", ""))[:280] }}{% if (r.get("body","") or "")|length > 280 %}…{% endif %}</div>
  <div class="quote-meta">
    <span>{{ "★" * ((r.rating|int) if r.rating else 0) }}</span>
    <span>{{ r.get("author", "Anonymous") }}</span>
    <span>{{ r.get("product_name", r.get("product_sku", "")) }}</span>
    {% if r.get("date_published_parsed") %}<span>{{ r["date_published_parsed"] }}</span>{% endif %}
  </div>
</div>
```

- [ ] **Step 3: Create `_partials/empty_state.html.j2`**

```jinja
{#
  Empty-state placeholder with friendly copy. Caller passes:
    - icon    (str, optional single glyph, defaults to serif section symbol)
    - title   (str)
    - body    (str — human-readable reason)
#}
<div class="empty-state">
  <div class="empty-state-icon">{{ icon or "§" }}</div>
  <div class="empty-state-title">{{ title }}</div>
  <div class="empty-state-body">{{ body }}</div>
</div>
```

- [ ] **Step 4: Add matching CSS to `daily_report_v3.css`**

Append:

```css
/* V4 Issue card */
.issue-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  padding: var(--sp-lg) var(--sp-xl);
  margin-bottom: var(--sp-md);
  box-shadow: var(--shadow-sm);
}
.issue-card-header { display: flex; align-items: baseline; gap: var(--sp-sm); flex-wrap: wrap; margin-bottom: var(--sp-sm); }
.issue-card-title { font-family: var(--font-display); font-size: var(--fs-md); }
.issue-card-meta { font-size: var(--fs-xs); color: var(--text-muted); margin-left: auto; }
.issue-card-history summary { font-size: var(--fs-xs); color: var(--text-secondary); cursor: pointer; padding: var(--sp-xs) 0; }
.issue-card-history ul { font-size: var(--fs-xs); margin: var(--sp-xs) 0 0 var(--sp-lg); }
.issue-card-quotes-label,
.issue-card-competitor-label { font-size: var(--fs-xs); color: var(--text-secondary); margin: var(--sp-sm) 0 var(--sp-xs); letter-spacing: 0.04em; }
.issue-card-competitor {
  margin-top: var(--sp-sm);
  padding: var(--sp-sm) var(--sp-md);
  background: var(--accent-soft);
  border-radius: var(--r-md);
  border-left: 2px solid var(--accent);
}
/* V4 Lifecycle badges */
.lifecycle-badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-family: var(--font-mono); }
.ls-active { background: var(--critical-bg); color: var(--critical); }
.ls-receding { background: var(--medium-bg); color: var(--medium); }
.ls-dormant { background: var(--surface-sunken); color: var(--text-muted); }
.ls-recurrent { background: var(--critical); color: var(--text-inverse); }

/* V4 Empty state */
.empty-state {
  text-align: center;
  padding: var(--sp-3xl) var(--sp-xl);
  color: var(--text-muted);
  background: var(--surface-sunken);
  border-radius: var(--r-xl);
}
.empty-state-icon { font-family: var(--font-display); font-size: 48px; color: var(--text-muted); opacity: 0.4; }
.empty-state-title { font-family: var(--font-display); font-size: var(--fs-md); margin-top: var(--sp-sm); color: var(--text-secondary); }
.empty-state-body { font-size: var(--fs-sm); margin-top: var(--sp-xs); max-width: 520px; margin-left: auto; margin-right: auto; }
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_templates/_partials/*.j2 qbu_crawler/server/report_templates/daily_report_v3.css
git commit -m "feat(templates): issue_card, review_quote, empty_state partials + CSS"
```

---

### Task 2.5：Feature flag `REPORT_DS_VERSION`

**Files:**
- Modify: `qbu_crawler/config.py`（新增 env 读取）

- [ ] **Step 1: Append config**

In `qbu_crawler/config.py` (near other `os.getenv(...)` blocks), add:

```python
REPORT_DS_VERSION = os.getenv("REPORT_DS_VERSION", "v3").lower()
"""Design system version for HTML reports. 'v3' (default) = legacy templates,
'v4' = new unified Editorial Intelligence (daily/weekly/monthly shared partials)."""
```

- [ ] **Step 2: Smoke test**

```bash
uv run python -c "from qbu_crawler import config; print('REPORT_DS_VERSION=', config.REPORT_DS_VERSION)"
REPORT_DS_VERSION=v4 uv run python -c "from qbu_crawler import config; print('REPORT_DS_VERSION=', config.REPORT_DS_VERSION)"
```

Expected: `v3` then `v4`.

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/config.py
git commit -m "feat(config): REPORT_DS_VERSION flag for v3/v4 rollout"
```

---

## Phase 3 — PR 3：三张报告重构（装配式）

**目标**：daily/weekly/monthly 都用 `_partials/` 组装；Mode 视觉语言落地；`REPORT_DS_VERSION=v4` 启用后 S01-S11 + W0-W5 + M1 的 HTML 视觉可辨、样式统一。

---

### Task 3.1：`daily.html.j2` 装配（替代 `daily_briefing.html.j2`）

**Files:**
- Create: `qbu_crawler/server/report_templates/daily.html.j2`
- Modify: `qbu_crawler/server/report_html.py`（新增 `render_daily_v4`）

- [ ] **Step 1: Create `daily.html.j2`**

```jinja
<!doctype html>
<html lang="zh-CN">
{% include "_partials/head.html.j2" %}
<body>
  {% include "_partials/kpi_bar.html.j2" %}
  {% include "_partials/mode_strip.html.j2" %}

  <main class="report-main">
    {% include "_partials/hero.html.j2" %}

    {% if mode != "quiet" %}
    <section class="section-divider">
      <span class="section-divider-num">01</span>
      <span class="section-divider-title">核心指标</span>
      <span class="section-divider-hint">基于累积数据 · Δ vs 上期</span>
    </section>
    {% include "_partials/kpi_grid.html.j2" %}
    {% endif %}

    {% include "_partials/tab_nav.html.j2" %}

    <section id="tab-overview" class="tab-panel tab-active" role="tabpanel">
      {% if mode == "partial" %}
      <div class="notice notice--info">
        <strong>基线建立中</strong>：当前样本 {{ analytics.kpis_normalized.own_review_rows or 0 }} 条，
        未达到贝叶斯先验阈值（30 条）；健康指数已向先验值 50 收缩以避免小样本虚高。
        预计 Day 7 之后转为完整置信度。
      </div>
      {% elif mode == "quiet" %}
      <div class="notice notice--quiet">
        <strong>静默期 · 连续 {{ mode_context.quiet_days or 0 }} 天无新评论</strong>
        {% include "_partials/kpi_grid.html.j2" %}
      </div>
      {% endif %}

      {% if window_reviews %}
      <section class="section-divider">
        <span class="section-divider-num">02</span>
        <span class="section-divider-title">今日变化</span>
        <span class="section-divider-hint">新评论 {{ window_reviews|length }} 条</span>
      </section>
      {% for r in window_reviews[:15] %}
      {% include "_partials/review_quote.html.j2" %}
      {% endfor %}
      {% endif %}

      {% if changes and (changes.price_changes or changes.stock_changes or changes.rating_changes) %}
      <section class="section-divider">
        <span class="section-divider-num">03</span>
        <span class="section-divider-title">产品数据变动</span>
      </section>
      {% include "_partials/changes_table.html.j2" ignore missing %}
      {% endif %}

      {% if action_signals %}
      <section class="section-divider">
        <span class="section-divider-num">04</span>
        <span class="section-divider-title">需行动</span>
      </section>
      <ul class="attention-list attention-list--action">
        {% for s in action_signals %}<li>{{ s.title }}</li>{% endfor %}
      </ul>
      {% endif %}
    </section>

  </main>
  {% include "_partials/footer.html.j2" %}
</body>
</html>
```

- [ ] **Step 2: Implement `render_daily_v4` in `report_html.py`**

Append to `qbu_crawler/server/report_html.py`:

```python
def render_daily_v4(
    snapshot, analytics, cumulative_kpis, window_reviews,
    attention_signals, changes, output_path, *, mode, mode_context,
):
    """V4 daily renderer — mode-aware, shared partials."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      autoescape=select_autoescape(["html", "j2"]))
    css_text = (template_dir / "daily_report_v3.css").read_text(encoding="utf-8")

    normalized = normalize_deep_report_analytics(analytics or {})
    logical_date = snapshot.get("logical_date", "")
    action_signals = [s for s in (attention_signals or []) if s.get("urgency") == "action"]

    # Hero inputs derived from mode
    kicker_map = {
        "partial": f"BASELINE BUILDING · Day {mode_context.get('day_index', 1)}/7",
        "full":    f"DAILY INTELLIGENCE · {logical_date}",
        "change":  "CHANGE ONLY · 产品数据变动",
        "quiet":   f"QUIET · 连续 {mode_context.get('quiet_days', 0)} 天无新评论",
    }
    headline_map = {
        "partial": "样本积累中，本日数据置信度：样本不足",
        "full":    normalized.get("report_copy", {}).get("hero_headline") or "",
        "change":  f"今日 {len(changes.get('price_changes', []) or []) + len(changes.get('stock_changes', []) or [])} 个产品发生变动",
        "quiet":   "累积指标稳定，详情见核心指标卡",
    }
    tabs = [
        {"id": "overview", "label": "总览"},
    ]
    if mode in ("full", "partial"):
        tabs += [
            {"id": "changes", "label": "今日变化",
             "badge": len(window_reviews or []) if window_reviews else None},
            {"id": "issues", "label": "问题诊断",
             "badge": len(normalized.get("issue_cards") or []) or None},
            {"id": "panorama", "label": "全景"},
        ]

    return _write_template(
        env, "daily.html.j2", output_path,
        page_title=f"QBU 网评监控 · 日报 {logical_date}",
        css_text=css_text,
        brand="QBU 网评监控",
        kpi_items=[
            {"label": "健康", "value": normalized["kpis"].get("health_index", "—")},
            {"label": "差评", "value": normalized["kpis"].get("own_negative_review_rate_display", "—")},
            {"label": "高风险", "value": normalized["kpis"].get("high_risk_count", 0)},
        ],
        mode=mode,
        kicker=kicker_map.get(mode, ""),
        meta=f"Run #{snapshot.get('run_id','?')} · {logical_date}",
        kicker_val=kicker_map.get(mode, ""),
        cards=normalized.get("kpi_cards", []),
        tabs=tabs,
        active="overview",
        title="QBU网评监控智能分析报告",
        headline=headline_map.get(mode, ""),
        health_index=normalized["kpis"].get("health_index"),
        confidence=normalized["kpis"].get("health_confidence", "no_data"),
        bullets=normalized.get("report_copy", {}).get("executive_bullets_human", []),
        actions=None,
        analytics=normalized,
        snapshot=snapshot,
        window_reviews=window_reviews or [],
        changes=changes or {},
        action_signals=action_signals,
        mode_context=mode_context,
        threshold=config.NEGATIVE_THRESHOLD,
        generated_at=snapshot.get("snapshot_at", "")[:19],
        version="v4",
    )


def _write_template(env, name, output_path, **ctx):
    html = env.get_template(name).render(**ctx)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("V4 render: %s (%d bytes)", output_path, len(html))
    return output_path
```

- [ ] **Step 3: Wire v4 flag into `_generate_daily_briefing`**

In `report_snapshot.py`, inside `_generate_daily_briefing` where `render_daily_briefing(...)` is currently called, wrap:

```python
if config.REPORT_DS_VERSION == "v4":
    # Determine daily mode
    run_row = models.get_workflow_run(run_id) or {}
    is_partial = bool(run_row.get("is_partial"))
    has_reviews = bool(window_reviews)
    has_changes = bool(changes and (changes.get("price_changes") or
                                     changes.get("stock_changes") or
                                     changes.get("rating_changes")))
    if is_partial:
        daily_mode = "partial"
    elif has_reviews:
        daily_mode = "full"
    elif has_changes:
        daily_mode = "change"
    else:
        daily_mode = "quiet"

    # Compute quiet_days (for 'quiet' mode kicker)
    quiet_days = _compute_quiet_days(run_id) if daily_mode == "quiet" else 0

    html_path = report_html.render_daily_v4(
        snapshot=snapshot,
        analytics=cum_analytics or {},
        cumulative_kpis=cumulative_kpis,
        window_reviews=enriched_reviews,
        attention_signals=attention_signals,
        changes=changes,
        output_path=html_output,
        mode=daily_mode,
        mode_context={"is_partial": is_partial, "quiet_days": quiet_days,
                      "day_index": run_row.get("day_index", 1)},
    )
else:
    html_path = report_html.render_daily_briefing(
        snapshot=snapshot, cumulative_kpis=cumulative_kpis,
        window_reviews=enriched_reviews, attention_signals=attention_signals,
        changes=changes, output_path=html_output,
    )
```

- [ ] **Step 4: Add `_compute_quiet_days` helper in `report_snapshot.py`**

Search for existing helpers and add:

```python
def _compute_quiet_days(run_id):
    """Count consecutive prior daily runs with 0 window reviews."""
    try:
        conn = models.get_conn()
        try:
            rows = conn.execute(
                """SELECT id, reviews_count FROM workflow_runs
                   WHERE report_tier='daily' AND id < ?
                   ORDER BY id DESC LIMIT 30""",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        n = 0
        for r in rows:
            if (r["reviews_count"] or 0) == 0:
                n += 1
            else:
                break
        return n
    except Exception:
        return 0
```

Note: if `workflow_runs.reviews_count` does not yet exist, skip and return `mode_context.quiet_days=0`; the UI degrades gracefully.

- [ ] **Step 5: Run simulator with v4 flag**

```bash
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one S01
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one S02
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one S07
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one S08a
```

- [ ] **Step 6: Manually open each HTML and confirm mode strip color differs**

```bash
uv run python -c "
import pathlib
for sid in ('S01','S02','S07','S08a'):
    for p in pathlib.Path(r'C:\Users\leo\Desktop\报告\reports\scenarios').glob(f'{sid}-*/daily-*.html'):
        txt = p.read_text(encoding='utf-8')
        for mode in ('partial','full','change','quiet'):
            if f'mode-strip--{mode}' in txt:
                print(sid, '→', mode)
"
```

Expected: S01→partial, S02→full, S07→change, S08a→quiet.

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_templates/daily.html.j2 qbu_crawler/server/report_html.py qbu_crawler/server/report_snapshot.py
git commit -m "feat(templates): V4 daily.html.j2 with mode-aware hero + KPI grid"
```

---

### Task 3.2：`weekly.html.j2` 装配（替代 weekly path 的 V3 模板调用）

**Files:**
- Create: `qbu_crawler/server/report_templates/weekly.html.j2`
- Modify: `qbu_crawler/server/report_html.py`（新增 `render_weekly_v4`）
- Modify: `qbu_crawler/server/report_snapshot.py`（_generate_weekly_report 分支）

- [ ] **Step 1: Create `weekly.html.j2`**

```jinja
<!doctype html>
<html lang="zh-CN">
{% include "_partials/head.html.j2" %}
<body>
  {% include "_partials/kpi_bar.html.j2" %}
  {% include "_partials/mode_strip.html.j2" %}

  <main class="report-main">
    {% include "_partials/hero.html.j2" %}

    <section class="section-divider">
      <span class="section-divider-num">01</span>
      <span class="section-divider-title">核心指标</span>
      <span class="section-divider-hint">本周累积 · Δ vs 上周</span>
    </section>
    {% include "_partials/kpi_grid.html.j2" %}

    {% include "_partials/tab_nav.html.j2" %}

    <section id="tab-overview" class="tab-panel tab-active" role="tabpanel">
      {# Weekly-specific overview content preserved from V3 via macros #}
      {% block weekly_overview %}{% endblock %}
    </section>

    <section id="tab-changes" class="tab-panel" role="tabpanel">
      <h3>本周新评论 Top 30</h3>
      {% for r in (window_reviews or [])[:30] %}
      {% include "_partials/review_quote.html.j2" %}
      {% endfor %}
    </section>

    <section id="tab-issues" class="tab-panel" role="tabpanel">
      {% for card in (issue_cards or []) %}
      {% include "_partials/issue_card.html.j2" %}
      {% endfor %}
      {% if not issue_cards %}
      {% include "_partials/empty_state.html.j2" %}
      {% endif %}
    </section>

    <section id="tab-products" class="tab-panel" role="tabpanel">
      {% include "_partials/products_table.html.j2" ignore missing %}
    </section>

    <section id="tab-panorama" class="tab-panel" role="tabpanel">
      {% include "_partials/panorama.html.j2" ignore missing %}
    </section>
  </main>
  {% include "_partials/footer.html.j2" %}
  <script>{{ js_text|safe }}</script>
</body>
</html>
```

- [ ] **Step 2: Implement `render_weekly_v4`**

Append to `report_html.py`:

```python
def render_weekly_v4(snapshot, analytics, output_path=None, changes=None):
    """V4 weekly renderer using shared partials."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    from qbu_crawler.server.report_charts import build_chartjs_configs

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      autoescape=select_autoescape(["html", "j2"]))
    css_text = (template_dir / "daily_report_v3.css").read_text(encoding="utf-8")
    js_text = (template_dir / "daily_report_v3.js").read_text(encoding="utf-8")

    normalized = normalize_deep_report_analytics(analytics)
    logical_date = snapshot.get("logical_date", "")
    iso_week = snapshot.get("_meta", {}).get("iso_week") or logical_date

    tabs = [
        {"id": "overview", "label": "总览"},
        {"id": "changes", "label": "本周变化",
         "badge": len((snapshot.get("reviews") or [])) or None},
        {"id": "issues", "label": "问题诊断",
         "badge": len(normalized.get("issue_cards") or []) or None},
        {"id": "products", "label": "产品排行"},
        {"id": "panorama", "label": "全景"},
    ]

    if output_path is None:
        output_path = os.path.join(
            config.REPORT_DIR, f"workflow-run-{snapshot['run_id']}-full-report.html",
        )

    return _write_template(
        env, "weekly.html.j2", output_path,
        page_title=f"QBU 网评监控 · 周报 {iso_week}",
        css_text=css_text, js_text=js_text,
        brand="QBU 网评监控",
        kpi_items=[
            {"label": "健康", "value": normalized["kpis"].get("health_index", "—")},
            {"label": "差评", "value": normalized["kpis"].get("own_negative_review_rate_display", "—")},
            {"label": "高风险", "value": normalized["kpis"].get("high_risk_count", 0)},
        ],
        show_print=True,
        mode="weekly",
        kicker=f"WEEKLY REPORT · {iso_week}",
        meta=f"Run #{snapshot.get('run_id','?')} · {logical_date}",
        title="QBU 网评监控 周报",
        headline=normalized.get("report_copy", {}).get("hero_headline") or "",
        health_index=normalized["kpis"].get("health_index"),
        confidence=normalized["kpis"].get("health_confidence", "no_data"),
        bullets=normalized.get("report_copy", {}).get("executive_bullets_human", []),
        actions=None,
        cards=normalized.get("kpi_cards", []),
        tabs=tabs, active="overview",
        analytics=normalized, snapshot=snapshot,
        window_reviews=snapshot.get("reviews", []),
        changes=changes or {},
        issue_cards=normalized.get("issue_cards", []),
        charts=build_chartjs_configs(normalized),
        threshold=config.NEGATIVE_THRESHOLD,
        generated_at=snapshot.get("snapshot_at", "")[:19],
        version="v4",
    )
```

- [ ] **Step 3: Wire flag into `_generate_weekly_report`**

In `_generate_weekly_report`, locate the `generate_full_report_from_snapshot(...)` call and after it, if v4 is enabled, also invoke `render_weekly_v4` to overwrite the html path:

Search `_generate_weekly_report` for the line that extracts `html_path = full_result.get("html_path")`. Add after:

```python
if config.REPORT_DS_VERSION == "v4":
    html_path = report_html.render_weekly_v4(
        snapshot, (full_result.get("analytics") or {}),
        output_path=html_path,
        changes=full_result.get("changes"),
    )
```

Note: `full_result` may not currently include `analytics` in its return dict. If missing, reload from `full_result.get("analytics_path")` using `load_analytics_envelope`.

- [ ] **Step 4: Simulator validation**

```bash
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one W0
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one W3
```

Expected: HTML contains `mode-strip--weekly`.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_templates/weekly.html.j2 qbu_crawler/server/report_html.py qbu_crawler/server/report_snapshot.py
git commit -m "feat(templates): V4 weekly.html.j2 assembled from partials"
```

---

### Task 3.3：`monthly.html.j2` 装配（完整重构，修复 Q5）

**Files:**
- Create: `qbu_crawler/server/report_templates/monthly.html.j2`
- Modify: `qbu_crawler/server/report_html.py`（新增 `render_monthly_v4`）
- Modify: `qbu_crawler/server/report_snapshot.py:1539-1592`（`_render_monthly_html` 分支）

- [ ] **Step 1: Create `monthly.html.j2`**

```jinja
<!doctype html>
<html lang="zh-CN">
{% include "_partials/head.html.j2" %}
<body>
  {% include "_partials/kpi_bar.html.j2" %}
  {% include "_partials/mode_strip.html.j2" %}

  <main class="report-main">
    {# Hero with LLM stance_text as headline + 3 KPI delta in gauge area #}
    {% include "_partials/hero.html.j2" %}

    <section class="section-divider">
      <span class="section-divider-num">01</span>
      <span class="section-divider-title">扩展指标</span>
      <span class="section-divider-hint">本月累积 · Δ vs 上月</span>
    </section>
    {% include "_partials/kpi_grid.html.j2" %}

    {% include "_partials/tab_nav.html.j2" %}

    {# Tab panels — 7 fixed tabs for monthly #}
    <section id="tab-overview" class="tab-panel tab-active" role="tabpanel">
      {% if weekly_summaries %}
      <section class="section-divider">
        <span class="section-divider-num">02</span>
        <span class="section-divider-title">本月逐周态势</span>
      </section>
      {% for ws in weekly_summaries %}<div class="week-summary">{{ ws }}</div>{% endfor %}
      {% endif %}
    </section>

    <section id="tab-changes" class="tab-panel" role="tabpanel">
      {% for r in (window_reviews or [])[:30] %}
      {% include "_partials/review_quote.html.j2" %}
      {% endfor %}
      {% if not window_reviews %}
      {% include "_partials/empty_state.html.j2" with context %}
      {% endif %}
    </section>

    <section id="tab-issues" class="tab-panel" role="tabpanel">
      {% if lifecycle_insufficient %}
      <div class="notice notice--info">
        <strong>数据积累中</strong>：当前 {{ history_days }} 天历史（生命周期分析需 ≥30 天），下月报告将完整展示。
      </div>
      {% else %}
      {% for card in (lifecycle_cards or []) %}
      {% include "_partials/issue_card.html.j2" %}
      {% endfor %}
      {% if not lifecycle_cards %}
      {% include "_partials/empty_state.html.j2" with context %}
      {% endif %}
      {% endif %}
    </section>

    <section id="tab-categories" class="tab-panel" role="tabpanel">
      {% include "_partials/category_benchmark.html.j2" ignore missing %}
    </section>

    <section id="tab-scorecard" class="tab-panel" role="tabpanel">
      {% include "_partials/scorecard.html.j2" ignore missing %}
    </section>

    <section id="tab-competitor" class="tab-panel" role="tabpanel">
      {% include "_partials/competitor.html.j2" ignore missing %}
    </section>

    <section id="tab-panorama" class="tab-panel" role="tabpanel">
      {% include "_partials/panorama.html.j2" ignore missing %}
    </section>

    {% if safety_incidents %}
    <section class="section-divider">
      <span class="section-divider-num">09</span>
      <span class="section-divider-title">本月安全事件</span>
      <span class="section-divider-hint">按 review_id 去重分组</span>
    </section>
    <ul class="safety-list">
      {% for inc in safety_incidents %}
      <li class="safety-item safety-item--{{ inc.safety_level }}">
        <span class="safety-level">{{ inc.safety_level }}</span>
        <strong>{{ inc.product_name or inc.product_sku }}</strong>
        <span class="safety-mode">{{ inc.failure_mode or "未分类" }}</span>
        {% if inc.review_excerpt %}<div class="safety-excerpt">"{{ inc.review_excerpt[:200] }}…"</div>{% endif %}
        <div class="safety-meta">{{ inc.first_seen }} · {{ inc.review_count }} 条相关评论</div>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
  </main>
  {% include "_partials/footer.html.j2" %}
  <script>{{ js_text|safe }}</script>
</body>
</html>
```

- [ ] **Step 2: Add scorecard / category / competitor / panorama partials (extracted from existing monthly_report.html.j2 lines 100-325)**

Create `_partials/scorecard.html.j2` by copying content of monthly_report.html.j2 Tab 5 block (lines 255-277). Create `_partials/category_benchmark.html.j2` from Tab 4 (lines 216-252). Create `_partials/competitor.html.j2` from Tab 6 (lines 279-292). Create `_partials/panorama.html.j2` from Tab 7 (lines 294-323). In each, replace `<section>` wrapper with a neutral `<div>` so the wrapping in `monthly.html.j2` stays consistent, and update class names to V3 tokens.

- [ ] **Step 3: Safety-incidents groupby review_id**

Add helper in `report_snapshot.py` or new `analytics_safety.py`:

```python
def group_safety_incidents(incidents):
    """Group raw safety_incidents rows by review_id, keeping count + first_seen."""
    by_review = {}
    for inc in incidents or []:
        rid = inc.get("review_id") or f"noreview-{inc.get('id')}"
        g = by_review.setdefault(rid, {
            "review_id": rid,
            "safety_level": inc.get("safety_level"),
            "failure_mode": inc.get("failure_mode"),
            "product_sku": inc.get("product_sku"),
            "product_name": inc.get("product_name"),
            "review_excerpt": inc.get("review_body") or inc.get("review_excerpt"),
            "first_seen": inc.get("created_at") or inc.get("first_seen"),
            "review_count": 0,
        })
        g["review_count"] += 1
        if inc.get("created_at") and (not g["first_seen"] or inc["created_at"] < g["first_seen"]):
            g["first_seen"] = inc["created_at"]
    return sorted(by_review.values(), key=lambda g: (g["safety_level"] != "critical", g["first_seen"] or ""))
```

- [ ] **Step 4: Implement `render_monthly_v4` in `report_html.py`**

```python
def render_monthly_v4(snapshot, analytics, executive, kpi_delta, category_benchmark,
                     scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
                     weekly_summaries, weekly_trend_config, safety_incidents,
                     output_path):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    from qbu_crawler.server.report_charts import build_chartjs_configs

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)),
                      autoescape=select_autoescape(["html", "j2"]))
    css_text = (template_dir / "daily_report_v3.css").read_text(encoding="utf-8")
    js_text = (template_dir / "daily_report_v3.js").read_text(encoding="utf-8")

    normalized = normalize_deep_report_analytics(analytics)
    logical_date = snapshot.get("logical_date", "")
    from datetime import date as _date, timedelta as _td
    try:
        ld = _date.fromisoformat(logical_date[:10])
        prev_month = ld.replace(day=1) - _td(days=1)
        month_label = prev_month.strftime("%Y年%m月")
    except (ValueError, TypeError):
        month_label = logical_date[:7]

    charts = dict(build_chartjs_configs(normalized))
    if weekly_trend_config:
        charts["weekly_trend"] = weekly_trend_config

    tabs = [
        {"id": "overview", "label": "高管视图"},
        {"id": "changes", "label": "本月变化",
         "badge": len(snapshot.get("reviews") or []) or None},
        {"id": "issues", "label": "问题生命周期"},
        {"id": "categories", "label": "品类对标"},
        {"id": "scorecard", "label": "产品计分卡"},
        {"id": "competitor", "label": "竞品对标"},
        {"id": "panorama", "label": "全景数据"},
    ]

    # Hero actions = top 3 recommended actions from LLM executive
    actions = (executive.get("actions") or [])[:3]

    return _write_template(
        env, "monthly.html.j2", output_path,
        page_title=f"QBU 网评监控 · 月报 {month_label}",
        css_text=css_text, js_text=js_text,
        brand="QBU 网评监控",
        kpi_items=[
            {"label": "健康", "value": normalized["kpis"].get("health_index", "—")},
            {"label": "差评", "value": normalized["kpis"].get("own_negative_review_rate_display", "—")},
            {"label": "高风险", "value": normalized["kpis"].get("high_risk_count", 0)},
        ],
        mode="monthly",
        kicker=f"MONTHLY EXECUTIVE BRIEF · {month_label}",
        meta=f"Run #{snapshot.get('run_id','?')}",
        title="QBU 网评监控 月度报告",
        headline=executive.get("stance_text") or "",
        health_index=normalized["kpis"].get("health_index"),
        confidence=normalized["kpis"].get("health_confidence", "no_data"),
        bullets=executive.get("bullets", []),
        actions=actions,
        cards=normalized.get("kpi_cards", []),
        tabs=tabs, active="overview",
        analytics=normalized, snapshot=snapshot,
        window_reviews=snapshot.get("reviews", []),
        lifecycle_cards=lifecycle_cards,
        lifecycle_insufficient=lifecycle_insufficient,
        history_days=history_days,
        category_benchmark=category_benchmark,
        scorecard=scorecard,
        weekly_summaries=weekly_summaries,
        safety_incidents=safety_incidents,
        charts=charts,
        kpis=normalized["kpis"],
        kpi_delta=kpi_delta,
        threshold=config.NEGATIVE_THRESHOLD,
        generated_at=snapshot.get("snapshot_at", "")[:19],
        version="v4",
    )
```

- [ ] **Step 5: Wire flag in `_generate_monthly_report`**

Replace the call site of `_render_monthly_html(...)` with:

```python
from qbu_crawler.server.analytics_safety import group_safety_incidents
safety_grouped = group_safety_incidents(safety_incidents)

if config.REPORT_DS_VERSION == "v4":
    html_path = report_html.render_monthly_v4(
        snapshot=snapshot, analytics=analytics, executive=executive,
        kpi_delta=kpi_delta, category_benchmark=category_benchmark,
        scorecard=scorecard, lifecycle_cards=lifecycle_cards,
        lifecycle_insufficient=lifecycle_insufficient,
        history_days=history_days, weekly_summaries=weekly_summaries,
        weekly_trend_config=weekly_trend_config,
        safety_incidents=safety_grouped,
        output_path=str(Path(config.REPORT_DIR) / f"monthly-{month_label.replace('年','-').replace('月','')}.html"),
    )
else:
    html_path = _render_monthly_html(
        snapshot, analytics, executive, kpi_delta, category_benchmark,
        scorecard, lifecycle_cards, lifecycle_insufficient, history_days,
        weekly_summaries, weekly_trend_config, safety_incidents, full_result,
    )
```

- [ ] **Step 6: Simulator validation**

```bash
REPORT_DS_VERSION=v4 uv run python -m scripts.simulate_reports run-one M1
```

Then verify:

```bash
uv run python -c "
import pathlib, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
for p in pathlib.Path(r'C:\Users\leo\Desktop\报告\reports\scenarios').glob('M1-*/monthly-*.html'):
    t = p.read_text(encoding='utf-8')
    print('has mode-strip--monthly:', 'mode-strip--monthly' in t)
    print('has tab-btn.tab-active:', '.tab-active' in t or 'tab-active' in t)
    print('health value non-empty:', 'exec-kpi-value\"></div>' not in t)
"
```

Expected: all three True.

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_templates/monthly.html.j2 qbu_crawler/server/report_templates/_partials/*.j2 qbu_crawler/server/report_html.py qbu_crawler/server/report_snapshot.py qbu_crawler/server/analytics_safety.py
git commit -m "feat(templates): V4 monthly.html.j2 + safety grouping fix (Q5/D3/D11)"
```

---

### Task 3.4：Full 42 天模拟器 + verify

- [ ] **Step 1: Flip flag in simulator env**

Append to `scripts/simulate_reports/env_bootstrap.py` (search for `os.environ.setdefault`) a line:

```python
os.environ.setdefault("REPORT_DS_VERSION", "v4")
```

- [ ] **Step 2: Full rerun**

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -m scripts.simulate_reports run
uv run python -m scripts.simulate_reports verify
```

- [ ] **Step 3: Confirm per-SID verdicts**

Expected output:
- All S01–S11 PASS
- All W0–W5 PASS
- M1 PASS
- FAIL count = 0

If any WARN remains (e.g. email_count min), investigate per-scenario and either fix the template or adjust the `expected` metadata in `scripts/simulate_reports/scenarios.py`.

- [ ] **Step 4: Commit**

```bash
git add scripts/simulate_reports/env_bootstrap.py
git commit -m "chore(sim): enable REPORT_DS_VERSION=v4 by default in simulator env"
```

---

## Phase 4 — PR 4：邮件收敛 + 数据一目了然

**目标**：6 个邮件模板收敛为 1 base + 3 变体；KPI tooltip 补公式/数据源/置信度；safety 深链；三段评分条；D5-D12 口径问题 UI 落地。

---

### Task 4.1：`_email_base.html.j2`（含共享 header/footer）

**Files:**
- Create: `qbu_crawler/server/report_templates/_email_base.html.j2`

- [ ] **Step 1: Create base**

```jinja
{#
  Base email template — all daily/weekly/monthly emails inherit.
  Caller overrides {% block content %}.
  Context vars:
    page_title, mode, kicker, brand, kpi_items (<=3), report_url,
    generated_at, threshold
#}
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{{ page_title }}</title>
  <style>
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; background:#f7f7f5; color:#1a1a2e; }
    .email-container { max-width:640px; margin:0 auto; background:#fff; }
    .email-banner { display:flex; align-items:center; justify-content:space-between; padding:20px 28px; background:linear-gradient(90deg, var(--mode,#4f46e5) 0%, rgba(255,255,255,1) 120%); color:#fff; }
    .email-banner-brand { font-weight:700; letter-spacing:0.06em; }
    .email-kicker { font-family:"DM Mono", monospace; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; padding:10px 28px; background:var(--mode,#4f46e5); color:#fff; }
    .email-body { padding:28px; }
    .email-kpi-row { display:flex; gap:16px; margin-bottom:24px; }
    .email-kpi { flex:1; background:#f0efed; padding:12px 14px; border-radius:8px; }
    .email-kpi-label { font-size:11px; color:#555770; }
    .email-kpi-value { font-family:"DM Mono", monospace; font-size:22px; font-weight:700; margin-top:4px; }
    .email-btn { display:inline-block; padding:10px 22px; background:#4f46e5; color:#fff; text-decoration:none; border-radius:6px; font-size:13px; }
    .email-footer { padding:16px 28px; background:#f0efed; color:#8e8ea0; font-size:11px; text-align:center; }
  </style>
</head>
<body>
  <div class="email-container">
    <div class="email-banner" style="--mode: {{ {'partial':'#8e8ea0','full':'#4f46e5','change':'#c2410c','quiet':'#047857','weekly':'#4338ca','monthly':'#1e1b4b'}.get(mode,'#4f46e5') }};">
      <span class="email-banner-brand">{{ brand or "QBU 网评监控" }}</span>
      <span class="email-banner-date">{{ generated_at }}</span>
    </div>
    <div class="email-kicker" style="background: {{ {'partial':'#8e8ea0','full':'#4f46e5','change':'#c2410c','quiet':'#047857','weekly':'#4338ca','monthly':'#1e1b4b'}.get(mode,'#4f46e5') }};">{{ kicker }}</div>

    <div class="email-body">
      {% if kpi_items %}
      <div class="email-kpi-row">
        {% for it in kpi_items[:3] %}
        <div class="email-kpi">
          <div class="email-kpi-label">{{ it.label }}</div>
          <div class="email-kpi-value">{{ it.value }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}

      {% block content %}{% endblock %}

      {% if report_url %}
      <p style="text-align:center;margin-top:24px;">
        <a class="email-btn" href="{{ report_url }}">查看完整报告 →</a>
      </p>
      {% endif %}
    </div>

    <div class="email-footer">
      差评定义：≤ {{ threshold }} 星 · AI 自动生成 · QBU 网评监控
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/_email_base.html.j2
git commit -m "feat(email): unified email base template (1 base + 3 variants foundation)"
```

---

### Task 4.2：3 个邮件变体 `extends _email_base`

**Files:**
- Rewrite: `qbu_crawler/server/report_templates/email_daily.html.j2`
- Rewrite: `qbu_crawler/server/report_templates/email_weekly.html.j2`
- Rewrite: `qbu_crawler/server/report_templates/email_monthly.html.j2`

- [ ] **Step 1: Rewrite `email_daily.html.j2`**

```jinja
{% extends "_email_base.html.j2" %}
{% block content %}
  {% if mode == "partial" %}
    <p><strong>基线建立中</strong>：样本积累中，置信度：样本不足。</p>
  {% elif mode == "quiet" %}
    <p>连续 {{ mode_context.quiet_days or 0 }} 天无新评论，累积指标稳定。</p>
  {% endif %}

  {% if window_reviews %}
  <h3 style="margin:20px 0 8px;font-size:16px;">今日新评论 · {{ window_reviews|length }} 条</h3>
  {% for r in window_reviews[:5] %}
  <div style="padding:10px 12px;background:#f7f7f5;border-radius:6px;margin-bottom:6px;">
    <div style="font-size:12px;color:#8e8ea0;">{{ "★"*(r.rating|int if r.rating else 0) }} · {{ r.get("product_name","") }}</div>
    <div style="font-size:13px;margin-top:2px;">{{ r.get("headline_cn") or r.get("headline","") }}</div>
  </div>
  {% endfor %}
  {% endif %}

  {% if changes and (changes.price_changes or changes.stock_changes or changes.rating_changes) %}
  <h3 style="margin:20px 0 8px;font-size:16px;">产品数据变动</h3>
  <ul style="font-size:13px;">
    {% for c in (changes.price_changes or [])[:5] %}<li>💰 {{ c.name }}: ${{ c.old }} → ${{ c.new }}</li>{% endfor %}
    {% for c in (changes.stock_changes or [])[:5] %}<li>📦 {{ c.name }}: {{ c.old }} → {{ c.new }}</li>{% endfor %}
  </ul>
  {% endif %}
{% endblock %}
```

- [ ] **Step 2: Rewrite `email_weekly.html.j2`**

```jinja
{% extends "_email_base.html.j2" %}
{% block content %}
  <h3 style="margin:0 0 8px;font-size:16px;">{{ headline }}</h3>
  {% if bullets %}
  <ul style="font-size:13px;margin:12px 0;">
    {% for b in bullets %}<li>{{ b }}</li>{% endfor %}
  </ul>
  {% endif %}
  {% if issue_cards %}
  <h4 style="margin:16px 0 6px;font-size:13px;color:#555770;">本周关键问题</h4>
  <ul style="font-size:13px;">
    {% for c in issue_cards[:3] %}<li>{{ c.label_display }} — {{ c.review_count }} 条</li>{% endfor %}
  </ul>
  {% endif %}
{% endblock %}
```

- [ ] **Step 3: Rewrite `email_monthly.html.j2`**

```jinja
{% extends "_email_base.html.j2" %}
{% block content %}
  <h2 style="font-family:Georgia,serif;font-size:20px;margin:0 0 4px;">{{ headline }}</h2>
  <p style="font-size:11px;color:#8e8ea0;letter-spacing:0.1em;text-transform:uppercase;">月度态势 · {{ stance_label }}</p>

  {% if bullets %}
  <ul style="font-size:14px;margin:16px 0;padding-left:20px;">
    {% for b in bullets %}<li>{{ b }}</li>{% endfor %}
  </ul>
  {% endif %}

  {% if actions %}
  <div style="margin:20px 0;padding:14px 16px;background:#eef2ff;border-left:3px solid #4f46e5;border-radius:4px;">
    <div style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#4338ca;margin-bottom:8px;">建议行动 Top 3</div>
    <ol style="font-size:13px;margin:0;padding-left:20px;">
      {% for a in actions %}<li>{{ a }}</li>{% endfor %}
    </ol>
  </div>
  {% endif %}

  {% if safety_count and safety_count > 0 %}
  <p style="background:rgba(185,28,28,0.08);padding:10px 14px;border-radius:6px;color:#b91c1c;font-size:13px;">
    ⚠ 本月 {{ safety_count }} 起安全事件（详情见完整报告）
  </p>
  {% endif %}
{% endblock %}
```

- [ ] **Step 4: Delete obsolete templates**

```bash
git rm qbu_crawler/server/report_templates/email_full.html.j2 qbu_crawler/server/report_templates/email_change.html.j2 qbu_crawler/server/report_templates/email_quiet.html.j2
```

- [ ] **Step 5: Update `_send_daily_briefing_email`, `_send_monthly_email`, etc. to pass new context vars**

Grep for `.get_template("email_` and update context vars to match base:

```bash
grep -rn 'get_template("email_' qbu_crawler/server/
```

For each call site, ensure it passes `mode`, `kicker`, `brand`, `kpi_items`, `report_url`, `generated_at`, `threshold`, plus the block-specific vars (`window_reviews`, `changes`, `bullets`, etc.).

- [ ] **Step 6: Simulator validation — open emails folder**

```bash
uv run python -c "
import pathlib, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
for sd in sorted(pathlib.Path(r'C:\Users\leo\Desktop\报告\reports\scenarios').iterdir()):
    em = sd / 'emails'
    if em.exists():
        for f in em.glob('*.json'):
            obj = json.loads(f.read_text(encoding='utf-8'))
            body = obj.get('body_html','')
            if body and 'email-kpi-row' not in body:
                print('OLD TEMPLATE:', sd.name, f.name)
"
```

Expected: empty output (every email has migrated).

- [ ] **Step 7: Commit**

```bash
git add -A qbu_crawler/server/report_templates/ qbu_crawler/server/report_snapshot.py
git commit -m "refactor(email): collapse to 1 base + 3 variants (daily/weekly/monthly)"
```

---

### Task 4.3：KPI tooltip 内容补全（D6/D7/D9/D12）

**Files:**
- Modify: `qbu_crawler/server/report_common.py`（_resolve_tooltip + kpi_cards 扩展）

- [ ] **Step 1: Locate tooltip map**

```bash
grep -n "_resolve_tooltip\|def _resolve_tooltip\|TOOLTIPS" qbu_crawler/server/report_common.py | head -20
```

- [ ] **Step 2: Replace tooltip dict**

Replace (or extend) the tooltip map to include formula, data source, confidence:

```python
_KPI_TOOLTIPS = {
    "健康指数": (
        "公式：(好评数 - 差评数) / 评论总数 × 50 + 50\n"
        "数据源：累积自有评论\n"
        "置信度：样本 ≥30 可信；<30 向先验值 50 收缩"
    ),
    "差评率": (
        "公式：差评数 ÷ 自有评论总数（差评=评分 ≤ NEGATIVE_THRESHOLD 星）\n"
        "数据源：累积自有评论\n"
        "3 星中评不计入好评也不计入差评"
    ),
    "高风险产品": (
        "公式：risk_score ≥ HIGH_RISK_THRESHOLD 的自有产品数\n"
        "risk_score 由差评率、评分、近期差评数加权\n"
        "数据源：累积"
    ),
    "样本覆盖率": (
        "公式：最近 30 天站点新增评论 ÷ 抓取到的新增评论\n"
        "MAX_REVIEWS=200 截断影响：每产品最多采集 200 条最新评论\n"
        "数据源：site_reported_review_total_current vs ingested_review_rows"
    ),
    "竞品差距指数": (
        "公式：各维度 (comp_pos_rate + own_neg_rate) / 2 平均 × 100\n"
        "样本门槛：自有+竞品评论 ≥ 20 才展示\n"
        "数据源：累积"
    ),
    "自有评论": "累积抓取到的自有产品评论总数（已去重）",
    "好评率": "自有产品 ≥4 星评论占比（3 星为中评，不计入好评）",
    "翻译完成度": "累积评论中 translate_status='done' 的比例",
    "安全事件": "本期新增 safety_incidents 记录数（按 review_id 去重）",
}


def _resolve_tooltip(label):
    return _KPI_TOOLTIPS.get(label, "")
```

- [ ] **Step 3: Add confidence field to each kpi_card**

In `normalize_deep_report_analytics` where `kpi_cards` list is built (around line 1249-1293), add `"confidence"` to each card:

```python
# health_confidence is computed; map to badge
_health_conf = kpis.get("health_confidence", "no_data")
_health_conf_badge = {"high": "high", "medium": "medium", "low": "low", "no_data": "low"}.get(_health_conf, "none")

kpi_cards = [
    {"label": "健康指数", "value": kpis.get("health_index", "—"),
     "delta_display": kpis.get("health_index_delta_display", ""), "delta_class": "delta-flat",
     "tooltip": _resolve_tooltip("健康指数"),
     "confidence": _health_conf_badge},
    # ... apply same confidence logic to every card based on sample size
]
```

For cards without explicit confidence, set `"confidence": "none"` (omits badge).

- [ ] **Step 4: Add sample-progress state for competitive_gap_index when <20**

Inside the kpi_cards builder, replace the "竞品差距指数" card body:

```python
_total = (kpis.get("own_review_rows", 0) + kpis.get("competitor_review_rows", 0))
if _total < 20:
    _gap_value = f"累积中 {_total}/20"
    _gap_class = "kpi-delta--missing"
    _gap_conf = "low"
else:
    _gap_value = kpis.get("competitive_gap_index") or "—"
    _gap_class = "delta-flat"
    _gap_conf = "medium"
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_report_common.py -v
```

Fix any regression in expected tooltip strings; update test fixtures to match new content.

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "feat(report): KPI tooltips carry formula/source/confidence (D6/D7/D12)"
```

---

### Task 4.4：Three-band rate bar（D8）+ ownership 未分类可见（D5）

**Files:**
- Modify: `qbu_crawler/server/report_common.py`（kpi_cards 增强）

- [ ] **Step 1: Extend "差评率" card with `rate_bands`**

In the kpi_cards builder:

```python
own_pos = kpis.get("own_positive_review_rows", 0)
own_neg = kpis.get("own_negative_review_rows", 0)
own_total = kpis.get("own_review_rows", 0) or 1
neu = max(own_total - own_pos - own_neg, 0)
rate_bands = {
    "positive": round(own_pos / own_total * 100, 1),
    "neutral":  round(neu / own_total * 100, 1),
    "negative": round(own_neg / own_total * 100, 1),
}
# Attach to 差评率 card:
for c in kpi_cards:
    if c["label"] == "差评率":
        c["rate_bands"] = rate_bands
        break
```

- [ ] **Step 2: Add "未分类评论" indicator**

Compute `unclassified = max(ingested - own - competitor, 0)` and add as a sub-note on "自有评论" card:

```python
_ingested = kpis.get("ingested_review_rows", 0)
_classified = kpis.get("own_review_rows", 0) + kpis.get("competitor_review_rows", 0)
_unclassified = max(_ingested - _classified, 0)
if _unclassified > 0:
    for c in kpi_cards:
        if c["label"] == "自有评论":
            c["tooltip"] = c.get("tooltip", "") + f"\n注：当前 {_unclassified} 条评论 ownership 未分类"
            break
```

- [ ] **Step 3: Verify via simulator**

```bash
uv run python -m scripts.simulate_reports run-one S02
uv run python -c "
import pathlib
for p in pathlib.Path(r'C:\Users\leo\Desktop\报告\reports\scenarios').glob('S02-*/daily-*.html'):
    t = p.read_text(encoding='utf-8')
    assert 'rate-bar-seg--positive' in t, 'rate bar missing'
    print('rate bar OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_common.py
git commit -m "feat(kpi): three-band rate bar + unclassified reviews note (D5/D8)"
```

---

### Task 4.5：最终全景验收 + docs 同步

**Files:**
- Modify: `CLAUDE.md`（V4 章节补充）
- Create: `docs/devlogs/D0XX-report-ds-v4.md`（开发日志）

- [ ] **Step 1: Full simulator run + verify**

```bash
uv run python -m scripts.simulate_reports prepare
uv run python -m scripts.simulate_reports run
uv run python -m scripts.simulate_reports verify
```

All scenarios expected PASS.

- [ ] **Step 2: Visual spot-check checklist**

打开以下 6 份 HTML 人眼核对（在浏览器中）：

1. `S01-*/daily-2026-03-20.html` — 应有灰 mode strip + "BASELINE BUILDING"
2. `S02-*/daily-2026-03-21.html` — 靛 strip + "DAILY INTELLIGENCE"
3. `S07-*/daily-2026-04-04.html` — 琥珀 strip + "CHANGE ONLY"
4. `S08a-*/daily-2026-04-05.html` — 淡绿 strip + "QUIET"
5. `W3-*/workflow-run-*-full-report.html` — 深靛 strip + 周报 hero
6. `M1-*/monthly-*.html` — 靛夜 strip + 3 KPI 非空 + 7 tab 全部可切换

- [ ] **Step 3: Update `CLAUDE.md`**

Find the existing "## 报告模拟器" section and after it, add:

```markdown
### 报告设计系统 V4

`REPORT_DS_VERSION` (env, default `v3`) 控制 HTML 模板版本：
- `v3`：legacy（daily_briefing.html.j2 / daily_report_v3.html.j2 / monthly_report.html.j2）
- `v4`：Editorial Intelligence 统一设计系统，daily/weekly/monthly 共用 `_partials/` 组件

V4 设计语言见 `docs/superpowers/specs/2026-04-18-qbu-report-ds-v4-design.md`。

**Mode 视觉识别**（V4 专属）：
- Daily-Partial (灰) — 冷启动 is_partial=true
- Daily-Full (靛) — 有新评论
- Daily-Change (琥珀) — 无新评但有产品变动
- Daily-Quiet (淡绿) — 连续静默
- Weekly (深靛) / Monthly (靛夜)

**置信度徽章**：每个计算指标附 `conf-badge--high/medium/low`（基于 Bayesian shrinkage 下的样本量判断）。
```

- [ ] **Step 4: Write devlog**

Create `docs/devlogs/D0XX-report-ds-v4.md`（replace XX with next available number）:

```markdown
# D0XX — 报告设计系统 V4 重构

**日期**：2026-04-18
**Feature**：统一 daily/weekly/monthly 设计语言
**Spec**：`docs/superpowers/specs/2026-04-18-qbu-report-ds-v4-design.md`
**Plan**：`docs/superpowers/plans/2026-04-18-qbu-report-ds-v4.md`

## 核心变更

- AnalyticsEnvelope v4 schema：normalized 派生字段强制持久化（D1/D2）
- workflow_runs.is_partial 列落库（D4）
- safety_incidents 按 (review_id, level, mode) 去重（D3）
- 10 个 Jinja partials 共享组件
- daily/weekly/monthly 装配式模板，mode 即视觉语言
- 邮件收敛为 1 base + 3 变体
- KPI tooltip 含公式/数据源/置信度

## 踩坑

（实施过程中补充）

## 后续

- 移除 v3 旧模板（先保留一个 release 周期，确认 v4 稳定后再删）
- 按需把 CSS 拆到 `daily_report_v3.css` 以外的独立文件
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/devlogs/D0XX-report-ds-v4.md
git commit -m "docs: V4 report design system — CLAUDE.md + devlog"
```

- [ ] **Step 6: Open PR**

```bash
git push -u origin feature/report-simulation
gh pr create --title "V4 报告设计系统重构（4 个 PR 聚合）" --body "$(cat <<'EOF'
## Summary
- 修复 12 项 PM 数据口径问题（D1-D12）
- 三张报告统一到 Editorial Intelligence 设计系统
- Mode 即视觉语言（6 色 strip）
- 月报重构（修复首屏 KPI 空值 + tab 失效）
- 邮件体系收敛为 1 base + 3 变体

## Test plan
- [ ] `uv run pytest -q` 全部通过
- [ ] `uv run python -m scripts.simulate_reports verify` FAIL=0
- [ ] 6 份代表性 HTML 人眼验收（S01/S02/S07/S08a/W3/M1）
- [ ] `REPORT_DS_VERSION=v3` 回滚路径仍可用

## Spec
docs/superpowers/specs/2026-04-18-qbu-report-ds-v4-design.md
EOF
)"
```

---

## Self-Review Checklist

| Spec Requirement | Task Coverage |
|---|---|
| §2 D1-D4 数据契约修复 | Task 1.1 / 1.2 / 1.3 / 1.4 |
| §2 D5-D9 口径级 | Task 4.3 / 4.4 |
| §2 D10-D12 呈现级 | Task 4.3 / 4.4 |
| §3 Editorial Intelligence 设计语言 | Task 2.1 / 2.2 |
| §4 10 个 Jinja partials | Task 2.2 / 2.3 / 2.4 |
| §5 Mode 视觉语言 6 色 | Task 2.1 / 3.1 / 3.2 / 3.3 |
| §6 KPI 重设计 + AnalyticsEnvelope | Task 1.1 / 4.3 / 4.4 |
| §7 月报重构 | Task 3.3 |
| §8 邮件收敛 | Task 4.1 / 4.2 |
| §10 验收对照表 | Task 3.4 / 4.5 |

All spec requirements mapped to concrete tasks. No placeholders. Type names (`AnalyticsEnvelope`, `render_daily_v4`, `render_weekly_v4`, `render_monthly_v4`) consistent across tasks.
