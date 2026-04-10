# Report V3 Phase 3b — Three Report Modes + Change Detection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three report modes (Full/Change/Quiet Day) with snapshot change detection, cluster change tracking, and 3 email templates. Every calendar day produces meaningful output.

**Architecture:** `determine_report_mode()` routes the pipeline. Full mode uses existing V3 analytics + HTML. Change and Quiet modes use lightweight templates with data from previous analytics. Email templates match each mode.

**Tech Stack:** Python 3.10+, Jinja2, pytest

**Spec Reference:** `docs/superpowers/specs/2026-04-10-report-v3-redesign.md` — Sections 4.1, 5.2, 5.4 (Quiet Day content), 8.1 edge cases, 14.8–14.14, 15.3–15.5, 15.9

**Prerequisite:** Phase 3a complete (V3 HTML template available).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/server/report_snapshot.py` | Modify | `determine_report_mode`, `detect_snapshot_changes`, `compute_cluster_changes`, `generate_report_from_snapshot` (rename + 3-mode routing) |
| `qbu_crawler/server/report.py` | Modify | `send_email` updates for 3 templates, dynamic subject prefix |
| `qbu_crawler/server/report_templates/quiet_day_report.html.j2` | Create | Compact quiet day template |
| `qbu_crawler/server/report_templates/email_full.html.j2` | Create | Full report email |
| `qbu_crawler/server/report_templates/email_change.html.j2` | Create | Change report email |
| `qbu_crawler/server/report_templates/email_quiet.html.j2` | Create | Quiet day email |
| `tests/test_v3_modes.py` | Create | Mode detection, change detection, cluster changes tests |

---

### Task 0: Implement `load_previous_report_context` (P3b-01 fix)

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/models.py` (no change needed — `get_previous_completed_run` already filters `analytics_path IS NOT NULL`, per spec 15.2)
- Test: `tests/test_v3_modes.py` (create)

**Spec ref:** Section 4.1.5, 15.2

**Critical note (P3b-01):** Without this function, Change and Quiet modes cannot access previous analytics. The existing `get_previous_completed_run` at `models.py:767` already includes `AND analytics_path IS NOT NULL AND analytics_path != ''`, which satisfies spec 15.2's requirement to skip non-full runs.

- [ ] **Step 1: Write tests**

```python
# tests/test_v3_modes.py
"""Tests for Report V3 three-mode routing (Phase 3b)."""

import json
import sqlite3
from pathlib import Path
import pytest
from qbu_crawler import config, models
from qbu_crawler.server.report_snapshot import load_previous_report_context


def _get_test_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


class TestLoadPreviousContext:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "test.db")
        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
        models.init_db()
        return tmp_path

    def test_returns_none_when_no_previous(self, db):
        analytics, snapshot = load_previous_report_context(run_id=1)
        assert analytics is None
        assert snapshot is None

    def test_loads_from_previous_full_run(self, db):
        # Create a completed run with analytics file
        analytics_path = str(db / "analytics.json")
        Path(analytics_path).write_text('{"kpis": {"test": 1}}')
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-08", "trigger_key": "daily:2026-04-08",
            "analytics_path": analytics_path,
        })
        analytics, snapshot = load_previous_report_context(run_id=999)
        assert analytics is not None
        assert analytics["kpis"]["test"] == 1

    def test_skips_quiet_run_without_analytics(self, db):
        # Run 1: full with analytics
        analytics_path = str(db / "analytics.json")
        Path(analytics_path).write_text('{"kpis": {"from": "full"}}')
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-07", "trigger_key": "daily:2026-04-07",
            "analytics_path": analytics_path,
        })
        # Run 2: quiet without analytics
        models.create_workflow_run({
            "workflow_type": "daily", "status": "completed", "report_phase": "full_done",
            "logical_date": "2026-04-08", "trigger_key": "daily:2026-04-08",
            "analytics_path": None,
        })
        # Should skip run 2 and return run 1's analytics
        analytics, _ = load_previous_report_context(run_id=999)
        assert analytics["kpis"]["from"] == "full"
```

- [ ] **Step 2: Implement `load_previous_report_context`**

Add to `report_snapshot.py`:

```python
def load_previous_report_context(run_id):
    """Load the most recent completed run's analytics and snapshot.
    
    Skips runs without analytics (quiet/change mode runs).
    Returns (analytics_dict, snapshot_dict) or (None, None).
    """
    prev_run = models.get_previous_completed_run(run_id)
    if not prev_run or not prev_run.get("analytics_path"):
        return None, None
    
    try:
        analytics = json.loads(Path(prev_run["analytics_path"]).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("Failed to load previous analytics: %s", e)
        return None, None
    
    snapshot = None
    if prev_run.get("snapshot_path"):
        try:
            snapshot = json.loads(Path(prev_run["snapshot_path"]).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("Failed to load previous snapshot: %s", e)
    
    return analytics, snapshot
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_v3_modes.py::TestLoadPreviousContext -v
git add qbu_crawler/server/report_snapshot.py tests/test_v3_modes.py
git commit -m "feat(report): implement load_previous_report_context

Loads most recent completed run with analytics. Skips quiet/change runs
(analytics_path IS NULL). Handles missing files gracefully."
```

---

### Task 1: Implement `detect_snapshot_changes`

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_v3_modes.py` (append)

**Spec ref:** Section 4.1.4, 14.4 (float tolerance), 14.12 (partial scrape)

**Note (P3b-03):** The implementation MUST handle `previous_snapshot=None` with an early return guard.

- [ ] **Step 1: Write change detection tests**

```python
# tests/test_v3_modes.py
"""Tests for Report V3 three-mode routing (Phase 3b)."""

from qbu_crawler.server.report_snapshot import detect_snapshot_changes


class TestDetectSnapshotChanges:
    def test_no_changes(self):
        current = {"products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is False

    def test_price_change_detected(self):
        current = {"products": [{"sku": "A", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["price_changes"]) == 1

    def test_float_precision_no_phantom_change(self):
        """169.99 stored as float should not trigger phantom change."""
        current = {"products": [{"sku": "A", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        previous = {"products": [{"sku": "A", "price": 169.99000000000001, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is False

    def test_new_product_detected(self):
        current = {"products": [
            {"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50},
            {"sku": "B", "price": 20.0, "stock_status": "in_stock", "rating": 4.0, "review_count": 10},
        ]}
        previous = {"products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["new_products"]) == 1

    def test_removed_product_detected(self):
        current = {"products": []}
        previous = {"products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, previous)
        assert result["has_changes"] is True
        assert len(result["removed_products"]) == 1

    def test_no_previous_snapshot(self):
        current = {"products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        result = detect_snapshot_changes(current, None)
        assert result["has_changes"] is False
```

- [ ] **Step 2: Implement `detect_snapshot_changes`**

Add to `report_snapshot.py` the full implementation from spec Section 4.1.4, including the float tolerance fix (Section 14.4) and dynamic email subject helper (Section 14.8).

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_v3_modes.py::TestDetectSnapshotChanges -v
git add qbu_crawler/server/report_snapshot.py tests/test_v3_modes.py
git commit -m "feat(report): implement detect_snapshot_changes with float tolerance"
```

---

### Task 2: Implement `determine_report_mode` + `compute_cluster_changes`

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_v3_modes.py` (append)

**Spec ref:** Section 8.2, 5.2.2, 15.3

- [ ] **Step 1: Write mode routing tests**

```python
from qbu_crawler.server.report_snapshot import determine_report_mode, compute_cluster_changes


class TestDetermineReportMode:
    def test_full_when_reviews_present(self):
        snapshot = {"reviews": [{"id": 1}]}
        mode, ctx = determine_report_mode(snapshot, None, None)
        assert mode == "full"

    def test_change_when_price_changed(self):
        snapshot = {"reviews": [], "products": [{"sku": "A", "price": 149.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        prev_snapshot = {"products": [{"sku": "A", "price": 169.99, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        mode, ctx = determine_report_mode(snapshot, prev_snapshot, None)
        assert mode == "change"

    def test_quiet_when_nothing_changed(self):
        snapshot = {"reviews": [], "products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        prev_snapshot = {"products": [{"sku": "A", "price": 10.0, "stock_status": "in_stock", "rating": 4.5, "review_count": 50}]}
        mode, ctx = determine_report_mode(snapshot, prev_snapshot, {"kpis": {}})
        assert mode == "quiet"


class TestComputeClusterChanges:
    def test_new_cluster_detected(self):
        current = [{"label_code": "quality_stability", "label_display": "质量稳定性",
                     "review_count": 5, "affected_product_count": 1, "severity": "high",
                     "review_dates": []}]
        changes = compute_cluster_changes(current, [], date(2026, 4, 10))
        assert len(changes["new"]) == 1

    def test_escalated_cluster(self):
        current = [{"label_code": "qc", "label_display": "QC", "review_count": 10,
                     "affected_product_count": 1, "severity": "high", "review_dates": []}]
        previous = [{"label_code": "qc", "review_count": 7, "severity": "medium"}]
        changes = compute_cluster_changes(current, previous, date(2026, 4, 10))
        assert len(changes["escalated"]) == 1
        assert changes["escalated"][0]["delta"] == 3
```

- [ ] **Step 2: Implement both functions**

From spec Section 8.2 and Section 5.2.2 (with the fix from holistic review).

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_v3_modes.py -v
git add qbu_crawler/server/report_snapshot.py tests/test_v3_modes.py
git commit -m "feat(report): implement determine_report_mode + compute_cluster_changes"
```

---

### Task 3: Create Quiet Day template

**Files:**
- Create: `qbu_crawler/server/report_templates/quiet_day_report.html.j2`

**Spec ref:** Section 15.4

- [ ] **Step 1: Build template following spec 15.4 structure**

Single-page layout: status bar, KPI cards (from previous analytics), outstanding issues, translation progress, link to last full report.

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/quiet_day_report.html.j2
git commit -m "feat(report): quiet day HTML template — single-page status summary"
```

---

### Task 4: Create 3 email templates

**Files:**
- Create: `qbu_crawler/server/report_templates/email_full.html.j2`
- Create: `qbu_crawler/server/report_templates/email_change.html.j2`
- Create: `qbu_crawler/server/report_templates/email_quiet.html.j2`

**Spec ref:** Section 4.2.6, 14.8 (dynamic subject), 15.8 (freshness), 15.12 (deep links)

- [ ] **Step 1: Build email templates**

Port from existing `daily_report_email.html.j2` structure:
- `email_full.html.j2`: KPI cards + What Changed digest + Top 3 actions + report link
- `email_change.html.j2`: KPI snapshot + change details
- `email_quiet.html.j2`: KPI snapshot + outstanding issues + "上期报告" link

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/email_*.html.j2
git commit -m "feat(report): 3 email templates for full/change/quiet modes"
```

---

### Task 5: Refactor `generate_report_from_snapshot` with 3-mode routing

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_v3_modes.py` (append)

**Spec ref:** Section 14.14, 15.9 (failure notification)

- [ ] **Step 1: Write routing integration test**

```python
class TestReportModeRouting:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        # ... standard DB fixture ...

    def test_full_mode_produces_html_and_excel(self, db):
        """Full mode: generates V3 HTML + Excel + analytics."""
        # Insert products + reviews, build snapshot
        # Call generate_report_from_snapshot
        # Assert html_path and excel_path are non-None

    def test_quiet_mode_produces_html_only(self, db):
        """Quiet mode: generates quiet day HTML, no Excel or analytics."""
        # Build snapshot with 0 reviews, same prices
        # Assert mode == "quiet", html_path exists, excel_path is None

    def test_change_mode_produces_html_only(self, db):
        """Change mode: generates change HTML, no Excel or analytics."""
        # Build snapshot with 0 reviews, changed price
        # Assert mode == "change", html_path exists, excel_path is None
```

- [ ] **Step 2: Implement 3-mode routing**

Rename `generate_full_report_from_snapshot` → `generate_report_from_snapshot` (keep old name as wrapper).

```python
def generate_report_from_snapshot(snapshot, previous_analytics=None,
                                   previous_snapshot=None, send_email=True):
    mode, context = determine_report_mode(snapshot, previous_snapshot, previous_analytics)
    models.update_workflow_run(snapshot.get("run_id"), report_mode=mode)

    if mode == "full":
        return _generate_full_report(snapshot, send_email)
    elif mode == "change":
        return _generate_change_report(snapshot, context, previous_analytics, send_email)
    else:
        return _generate_quiet_report(snapshot, previous_analytics, send_email)
```

Where `_generate_full_report` is the existing logic, and `_generate_change_report` / `_generate_quiet_report` render the lightweight templates.

- [ ] **Step 3: Update send_email for dynamic subject**

Use the subject prefix helper from spec Section 14.8.

- [ ] **Step 4: Add failure notification** (spec 15.9)

Wrap the entire `generate_report_from_snapshot` in try/except, send plain-text error email on failure.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py qbu_crawler/server/report.py tests/test_v3_modes.py
git commit -m "feat(report): 3-mode report routing — full/change/quiet

Every day produces output. Quiet day: KPI snapshot + outstanding issues.
Change day: price/stock/rating delta. Full day: complete analytics.
Failure notification email on pipeline crash."
```

---

### Task 6: Implement adaptive quiet-day email frequency

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_v3_modes.py` (append)

**Spec ref:** Section 15.5

- [ ] **Step 1: Write frequency test**

```python
class TestQuietDayFrequency:
    def test_first_three_quiet_days_send(self):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        assert should_send_quiet_email(consecutive_quiet=1)[0] is True
        assert should_send_quiet_email(consecutive_quiet=3)[0] is True

    def test_days_4_to_6_skip(self):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        assert should_send_quiet_email(consecutive_quiet=4)[0] is False
        assert should_send_quiet_email(consecutive_quiet=6)[0] is False

    def test_day_7_sends_weekly(self):
        from qbu_crawler.server.report_snapshot import should_send_quiet_email
        send, mode = should_send_quiet_email(consecutive_quiet=7)
        assert send is True
        assert mode == "weekly_digest"
```

- [ ] **Step 2: Implement**

```python
def should_send_quiet_email(consecutive_quiet):
    threshold = int(os.getenv("REPORT_QUIET_EMAIL_DAYS", "3"))
    if consecutive_quiet <= threshold:
        return True, None
    if consecutive_quiet % 7 == 0:
        return True, "weekly_digest"
    return False, None
```

Count consecutive quiet runs by querying `workflow_runs WHERE report_mode='quiet' ORDER BY id DESC`.

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_v3_modes.py -v
git add qbu_crawler/server/report_snapshot.py tests/test_v3_modes.py
git commit -m "feat(report): adaptive quiet-day email — daily for 3 days, then weekly"
```

---

## Phase 3b Completion Checklist

- [ ] `determine_report_mode` routes to full/change/quiet correctly
- [ ] `detect_snapshot_changes` detects price/stock/rating/product changes with float tolerance
- [ ] `compute_cluster_changes` detects new/escalated/improving clusters
- [ ] Quiet day template renders from previous analytics
- [ ] Change report template shows change details
- [ ] 3 email templates with dynamic subject prefix
- [ ] Baseline mode hides "What Changed" tab
- [ ] Failure notification email sent on pipeline crash
- [ ] Adaptive quiet-day email frequency (3 days daily, then weekly)
- [ ] `report_mode` written to `workflow_runs` after mode determination
- [ ] All existing tests pass
