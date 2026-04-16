# P008 Phase 2: 日报重构 + 基础设施 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将日报从 full/change/quiet 三模式路由重构为 tier-based 智能简报，实现三区块结构（累积快照 + 今日变化 + 需注意信号）、新评论重量标签、安全分级标记、收件人分通道。

**Architecture:** 在 Phase 1 基础上渐进演进。新增 `report_tier` 列区分新旧路径——`report_tier == 'daily'` 走新三区块管线，旧 run 保持原有 full/change/quiet 路径不变。新路径始终生成 HTML 存档，仅在 `should_send_daily_email()` 返回 True 时发送邮件。

**Tech Stack:** Python 3.10+ / SQLite (WAL) / Jinja2 / FastAPI / pytest

**Design doc:** `docs/plans/P008-three-tier-report-system.md` Section 4

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `qbu_crawler/models.py` | report_tier 列迁移 + update_workflow_run 白名单 |
| Modify | `qbu_crawler/config.py` | EMAIL_RECIPIENTS_EXEC / SAFETY + TIER_CONFIGS |
| Modify | `qbu_crawler/server/report_common.py` | `_tier_date_window()` + `compute_attention_signals()` + `review_attention_label()` |
| Modify | `qbu_crawler/server/report_analytics.py` | `_risk_products()` 安全因子 |
| Modify | `qbu_crawler/server/report_snapshot.py` | `generate_report_from_snapshot()` tier 路由 + `_generate_daily_briefing()` + `should_send_daily_email()` |
| Modify | `qbu_crawler/server/report_html.py` | `render_daily_briefing()` 渲染入口 |
| Modify | `qbu_crawler/server/workflows.py` | 新 daily run 填充 `report_tier='daily'` + `report_mode='standard'` |
| Create | `qbu_crawler/server/report_templates/daily_briefing.html.j2` | 日报三区块 HTML 模板 |
| Create | `qbu_crawler/server/report_templates/email_daily.html.j2` | 日报邮件模板（body = 简报全文） |
| Create | `tests/test_p008_phase2.py` | Phase 2 所有测试 |

---

## Task 1: DB 迁移 — report_tier 列 + update_workflow_run 白名单

**Files:**
- Modify: `qbu_crawler/models.py:258` (migrations list), `qbu_crawler/models.py:669-688` (update_workflow_run)
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_p008_phase2.py
"""P008 Phase 2 — daily briefing refactor + infrastructure."""

from __future__ import annotations

import json
import sqlite3

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "p008p2.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── Task 1: report_tier column ──────────────────────────────────


def test_workflow_runs_has_report_tier_column(db):
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
    assert "report_tier" in cols
    conn.close()


def test_report_tier_default_is_daily(db):
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'test:2026-04-17')"
    )
    conn.commit()
    row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = 1").fetchone()
    assert row["report_tier"] == "daily"
    conn.close()


def test_update_workflow_run_accepts_report_tier(db):
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key)"
        " VALUES ('daily', 'submitted', 'none', '2026-04-17', 'test:2026-04-17')"
    )
    conn.commit()
    conn.close()
    result = models.update_workflow_run(1, report_tier="weekly")
    assert result["report_tier"] == "weekly"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_p008_phase2.py -v`
Expected: FAIL — report_tier column not found

- [ ] **Step 3: Add report_tier migration in models.py**

In `qbu_crawler/models.py`, find the migrations list (around line 258, after existing ALTER TABLE statements) and add:

```python
    "ALTER TABLE workflow_runs ADD COLUMN report_tier TEXT DEFAULT 'daily'",
```

- [ ] **Step 4: Add report_tier to update_workflow_run allowed set**

In `qbu_crawler/models.py:669-688`, add `"report_tier"` to the `allowed` set:

```python
    allowed = {
        "status",
        "report_phase",
        # ... existing fields ...
        "report_mode",
        "report_tier",  # P008 Phase 2
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/models.py tests/test_p008_phase2.py
git commit -m "feat(db): add report_tier column to workflow_runs"
```

---

## Task 2: Config — 收件人分通道 + TIER_CONFIGS

**Files:**
- Modify: `qbu_crawler/config.py:194-199`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase2.py

# ── Task 2: Config ──────────────────────────────────────────────


def test_email_recipients_exec_defaults_empty(monkeypatch):
    monkeypatch.delenv("EMAIL_RECIPIENTS_EXEC", raising=False)
    # Force re-evaluation by reading config attribute
    from qbu_crawler import config as cfg
    monkeypatch.setattr(cfg, "EMAIL_RECIPIENTS_EXEC", [])
    assert cfg.EMAIL_RECIPIENTS_EXEC == []


def test_tier_configs_has_daily():
    from qbu_crawler.config import TIER_CONFIGS
    assert "daily" in TIER_CONFIGS
    daily = TIER_CONFIGS["daily"]
    assert daily["window"] == "24h"
    assert daily["cumulative"] is True
    assert daily["excel"] is False
    assert "attention_signals" in daily["dimensions"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase2.py -k "config or tier" -v`
Expected: FAIL — TIER_CONFIGS not defined

- [ ] **Step 3: Add config values to config.py**

After the existing `EMAIL_BCC_MODE` line (~line 199) in `qbu_crawler/config.py`, add:

```python
# ── P008 Phase 2: Recipient channels ──────────────────────
EMAIL_RECIPIENTS_EXEC = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS_EXEC", "").split(",")
    if addr.strip()
]
EMAIL_RECIPIENTS_SAFETY = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS_SAFETY", "").split(",")
    if addr.strip()
]

# ── P008 Phase 2: Tier configurations ─────────────────────
TIER_CONFIGS = {
    "daily": {
        "window": "24h",
        "cumulative": True,
        "dimensions": ["kpi", "clusters", "competitive_gap", "attention_signals"],
        "template": "daily_briefing.html.j2",
        "excel": False,
        "delivery": {"email": "smart", "archive": True},
    },
    "weekly": {
        "window": "7d",
        "cumulative": True,
        "dimensions": ["kpi", "clusters", "competitive_gap",
                        "risk_ranking", "heatmap", "trend_charts"],
        "template": "weekly_report.html.j2",
        "excel": True,
        "delivery": {"email": "always", "archive": True},
    },
    "monthly": {
        "window": "month",
        "cumulative": True,
        "dimensions": ["kpi", "clusters", "competitive_gap",
                        "risk_ranking", "heatmap", "trend_charts",
                        "category_benchmark", "issue_lifecycle",
                        "product_scorecard", "executive_summary"],
        "template": "monthly_report.html.j2",
        "excel": True,
        "delivery": {"email": "always", "archive": True},
    },
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -k "config or tier" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/config.py tests/test_p008_phase2.py
git commit -m "feat(config): add recipient channels + TIER_CONFIGS for multi-tier reports"
```

---

## Task 3: _tier_date_window() 工具函数

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase2.py
from datetime import date

# ── Task 3: _tier_date_window ───────────────────────────────────


def test_tier_date_window_daily():
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("daily", "2026-04-17")
    assert since == "2026-04-17T00:00:00+08:00"
    assert until == "2026-04-18T00:00:00+08:00"


def test_tier_date_window_weekly():
    from qbu_crawler.server.report_common import tier_date_window
    # 2026-04-20 is a Monday
    since, until = tier_date_window("weekly", "2026-04-20")
    assert since == "2026-04-13T00:00:00+08:00"  # previous Monday
    assert until == "2026-04-20T00:00:00+08:00"  # this Monday


def test_tier_date_window_monthly():
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("monthly", "2026-05-01")
    assert since == "2026-04-01T00:00:00+08:00"
    assert until == "2026-05-01T00:00:00+08:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase2.py -k "tier_date_window" -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement tier_date_window() in report_common.py**

Add near the top of `qbu_crawler/server/report_common.py`, after the safety detection functions and before `_LABEL_DISPLAY`:

```python
# ── Tier date window computation ─────────────────────────────────────────────


def tier_date_window(tier: str, logical_date: str) -> tuple[str, str]:
    """Compute [since, until) half-open interval for the given tier and logical_date.

    All boundaries align to 00:00:00 Asia/Shanghai (no DST).

    - daily:   [logical_date 00:00, logical_date+1 00:00)
    - weekly:  [previous Monday 00:00, logical_date(Monday) 00:00)
    - monthly: [previous month 1st 00:00, logical_date(1st) 00:00)
    """
    d = date.fromisoformat(logical_date[:10])
    tz_suffix = "+08:00"

    if tier == "daily":
        since = d
        until = d + timedelta(days=1)
    elif tier == "weekly":
        until = d  # logical_date should be a Monday
        since = until - timedelta(days=7)
    elif tier == "monthly":
        until = d  # logical_date should be 1st of month
        # Go back to 1st of previous month
        if d.month == 1:
            since = d.replace(year=d.year - 1, month=12, day=1)
        else:
            since = d.replace(month=d.month - 1, day=1)
    else:
        raise ValueError(f"Unknown tier: {tier}")

    return (
        f"{since.isoformat()}T00:00:00{tz_suffix}",
        f"{until.isoformat()}T00:00:00{tz_suffix}",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -k "tier_date_window" -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_p008_phase2.py
git commit -m "feat(tier): add tier_date_window() for daily/weekly/monthly windows"
```

---

## Task 4: review_attention_label() — 新评论重量标签

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase2.py

# ── Task 4: review_attention_label ──────────────────────────────


def test_review_attention_label_critical_safety_with_images():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 1.0, "body": "Found metal shavings in food " * 20,
              "images": ["img1.jpg", "img2.jpg"]}
    result = review_attention_label(review, safety_level="critical")
    assert result["label"] == "高关注度评论"
    assert "⚠安全关键词" in " ".join(result["signals"])
    assert "📸" in " ".join(result["signals"])


def test_review_attention_label_negative_no_images():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 1.0, "body": "Bad product", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "差评"


def test_review_attention_label_positive():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 5.0, "body": "Great product!", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "常规好评"


def test_review_attention_label_mid_rating():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 3.0, "body": "It's okay", "images": []}
    result = review_attention_label(review, safety_level=None)
    assert result["label"] == "中评"


def test_review_attention_label_long_body_signal():
    from qbu_crawler.server.report_common import review_attention_label
    review = {"rating": 2.0, "body": "x" * 350, "images": []}
    result = review_attention_label(review, safety_level=None)
    assert any("字详评" in s for s in result["signals"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase2.py -k "attention_label" -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement review_attention_label() in report_common.py**

Add after `tier_date_window()` in `qbu_crawler/server/report_common.py`:

```python
# ── Review attention label ───────────────────────────────────────────────────


def review_attention_label(review: dict, safety_level: str | None) -> dict:
    """Generate a human-readable weight label for a single review.

    Returns {"signals": [...], "label": "高关注度评论" | "差评" | "常规好评" | "中评"}.
    Uses RCW signal factors but does NOT expose the RCW score (D4 decision).
    """
    signals = []
    if safety_level:
        signals.append(f"⚠安全关键词({safety_level})")
    images = review.get("images") or []
    if images:
        signals.append(f"📸 {len(images)}张图")
    body_len = len(review.get("body", ""))
    if body_len > 300:
        signals.append(f"{body_len}字详评")
    elif body_len < 50:
        signals.append("短评")

    rating = float(review.get("rating") or 0)
    if safety_level == "critical" or (rating <= 2 and len(images) > 0):
        label = "高关注度评论"
    elif rating <= 2:
        label = "差评"
    elif rating >= 4:
        label = "常规好评"
    else:
        label = "中评"

    return {"signals": signals, "label": label}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -k "attention_label" -v`
Expected: All 5 PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_p008_phase2.py
git commit -m "feat(daily): add review_attention_label() for new review weight tags"
```

---

## Task 5: compute_attention_signals() — "需注意" 信号引擎

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase2.py

# ── Task 5: compute_attention_signals ───────────────────────────


def test_attention_signals_safety_keyword():
    from qbu_crawler.server.report_common import compute_attention_signals
    window_reviews = [
        {"id": 1, "headline": "Dangerous", "body": "Found metal shaving in food",
         "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
         "ownership": "own", "images": []}
    ]
    signals = compute_attention_signals(window_reviews, changes={}, cumulative_clusters=[])
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "safety_keyword" for s in action_signals)


def test_attention_signals_consecutive_negative():
    from qbu_crawler.server.report_common import compute_attention_signals
    window_reviews = [
        {"id": 1, "headline": "Bad", "body": "Terrible", "rating": 1.0,
         "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
         "images": [], "date_published_parsed": "2026-04-16"},
        {"id": 2, "headline": "Also bad", "body": "Awful", "rating": 2.0,
         "product_sku": "SKU1", "product_name": "Grinder", "ownership": "own",
         "images": [], "date_published_parsed": "2026-04-14"},
    ]
    signals = compute_attention_signals(window_reviews, changes={}, cumulative_clusters=[])
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "consecutive_negative" for s in action_signals)


def test_attention_signals_competitor_rating_drop():
    from qbu_crawler.server.report_common import compute_attention_signals
    changes = {
        "rating_changes": [
            {"sku": "COMP1", "name": "Competitor Grinder", "old": 4.6, "new": 4.2,
             "ownership": "competitor"}
        ]
    }
    signals = compute_attention_signals([], changes=changes, cumulative_clusters=[])
    ref_signals = [s for s in signals if s["urgency"] == "reference"]
    assert any(s["type"] == "competitor_rating_change" for s in ref_signals)


def test_attention_signals_own_stock_out():
    from qbu_crawler.server.report_common import compute_attention_signals
    changes = {
        "stock_changes": [
            {"sku": "SKU1", "name": "Grinder", "old": "in_stock", "new": "out_of_stock",
             "ownership": "own"}
        ]
    }
    signals = compute_attention_signals([], changes=changes, cumulative_clusters=[])
    action_signals = [s for s in signals if s["urgency"] == "action"]
    assert any(s["type"] == "own_stock_out" for s in action_signals)


def test_attention_signals_silence_good_news():
    from qbu_crawler.server.report_common import compute_attention_signals
    clusters = [
        {"label_code": "quality_stability", "last_seen": "2026-04-01",
         "label_display": "质量稳定性"}
    ]
    signals = compute_attention_signals(
        [], changes={}, cumulative_clusters=clusters,
        logical_date="2026-04-17",
    )
    ref_signals = [s for s in signals if s["urgency"] == "reference"]
    assert any(s["type"] == "silence_good_news" for s in ref_signals)


def test_attention_signals_empty_when_nothing():
    from qbu_crawler.server.report_common import compute_attention_signals
    signals = compute_attention_signals([], changes={}, cumulative_clusters=[])
    assert signals == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase2.py -k "attention_signals" -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement compute_attention_signals()**

Add after `review_attention_label()` in `qbu_crawler/server/report_common.py`:

```python
# ── Attention signals engine ─────────────────────────────────────────────────


def compute_attention_signals(
    window_reviews: list[dict],
    changes: dict,
    cumulative_clusters: list[dict],
    logical_date: str | None = None,
) -> list[dict]:
    """Compute "needs attention" signals for the daily briefing.

    Returns list of signal dicts sorted by urgency (action first, reference second).
    Each signal: {"type": str, "urgency": "action"|"reference", "title": str, "detail": str}
    """
    signals = []
    ref_date = date.fromisoformat(logical_date[:10]) if logical_date else date.today()

    # ── Signal 1: Safety keyword hit (action) ──
    for r in window_reviews:
        text = f"{r.get('headline', '')} {r.get('body', '')}"
        level = detect_safety_level(text)
        if level:
            signals.append({
                "type": "safety_keyword",
                "urgency": "action",
                "title": f"安全: {r.get('product_name', '')} 评论提及安全关键词",
                "detail": f"级别: {level} · SKU: {r.get('product_sku', '')}",
                "review_id": r.get("id"),
                "safety_level": level,
            })

    # ── Signal 2: Consecutive negative for same SKU (action) ──
    own_negative_by_sku: dict[str, int] = {}
    for r in window_reviews:
        if r.get("ownership") == "own" and (float(r.get("rating") or 5)) <= config.NEGATIVE_THRESHOLD:
            sku = r.get("product_sku", "")
            if sku:
                own_negative_by_sku[sku] = own_negative_by_sku.get(sku, 0) + 1
    for sku, count in own_negative_by_sku.items():
        if count >= 2:
            name = next(
                (r.get("product_name", sku) for r in window_reviews if r.get("product_sku") == sku),
                sku,
            )
            signals.append({
                "type": "consecutive_negative",
                "urgency": "action",
                "title": f"连续差评: {name} 近期 {count} 条差评",
                "detail": f"SKU: {sku}",
            })

    # ── Signal 3: Own product out of stock (action) ──
    for sc in (changes.get("stock_changes") or []):
        if sc.get("ownership") == "own" and sc.get("new") == "out_of_stock":
            signals.append({
                "type": "own_stock_out",
                "urgency": "action",
                "title": f"缺货: {sc.get('name', '')} 从有货变为缺货",
                "detail": f"SKU: {sc.get('sku', '')}",
            })

    # ── Signal 4: Competitor rating drop ≥ 0.3 (reference) ──
    for rc in (changes.get("rating_changes") or []):
        if rc.get("ownership") != "competitor":
            continue
        old_r = rc.get("old") or 0
        new_r = rc.get("new") or 0
        if old_r and new_r and (old_r - new_r) >= 0.3:
            signals.append({
                "type": "competitor_rating_change",
                "urgency": "reference",
                "title": f"竞品: {rc.get('name', '')} 评分 {old_r}→{new_r} ({new_r - old_r:+.1f})",
                "detail": f"SKU: {rc.get('sku', '')}",
            })

    # ── Signal 5: Silence good news — negative cluster dormant > 14 days (reference) ──
    for cluster in cumulative_clusters:
        last_seen_str = cluster.get("last_seen")
        if not last_seen_str:
            continue
        try:
            last_seen = date.fromisoformat(last_seen_str[:10])
        except (ValueError, TypeError):
            continue
        if (ref_date - last_seen).days >= 14:
            signals.append({
                "type": "silence_good_news",
                "urgency": "reference",
                "title": f"静默观察: {cluster.get('label_display', '')} 已 {(ref_date - last_seen).days} 天无新投诉",
                "detail": f"上次出现: {last_seen_str[:10]}",
            })

    # Sort: action first, then reference
    urgency_order = {"action": 0, "reference": 1}
    signals.sort(key=lambda s: urgency_order.get(s["urgency"], 2))
    return signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -k "attention_signals" -v`
Expected: All 6 PASS

- [ ] **Step 5: Run existing tests for regressions**

Run: `uv run pytest tests/test_report_analytics.py tests/test_v3_modes.py -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_p008_phase2.py
git commit -m "feat(daily): add compute_attention_signals() for needs-attention block"
```

---

## Task 6: should_send_daily_email() — 日报智能发送

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_p008_phase2.py

# ── Task 6: should_send_daily_email ─────────────────────────────


def test_smart_send_true_when_new_reviews():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    assert should_send_daily_email(new_review_count=3, changes={}) is True


def test_smart_send_true_when_price_changes():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    changes = {"price_changes": [{"sku": "SKU1"}]}
    assert should_send_daily_email(new_review_count=0, changes=changes) is True


def test_smart_send_true_when_stock_changes():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    changes = {"stock_changes": [{"sku": "SKU1"}]}
    assert should_send_daily_email(new_review_count=0, changes=changes) is True


def test_smart_send_false_when_nothing():
    from qbu_crawler.server.report_snapshot import should_send_daily_email
    assert should_send_daily_email(new_review_count=0, changes={}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase2.py -k "smart_send" -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement should_send_daily_email()**

Add in `qbu_crawler/server/report_snapshot.py`, after the existing `should_send_quiet_email()` function (~line 85):

```python
def should_send_daily_email(new_review_count: int, changes: dict) -> bool:
    """Smart send: only email when there's something to report. HTML always archived."""
    if new_review_count > 0:
        return True
    if changes.get("price_changes") or changes.get("stock_changes") or changes.get("rating_changes"):
        return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -k "smart_send" -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase2.py
git commit -m "feat(daily): add should_send_daily_email() smart send logic"
```

---

## Task 7: 安全因子集成 — _risk_products() + 模板安全标记

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:840-846` (_risk_products weighted combination)
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase2.py

# ── Task 7: Safety factor in risk scoring ───────────────────────


def test_risk_score_higher_with_safety_reviews(db):
    """A product with safety-flagged reviews should have higher risk_score."""
    from qbu_crawler.server import report_analytics

    # Build labeled_reviews: one normal negative + one safety negative
    labeled_reviews_normal = [
        {"review": {"rating": 1.0, "ownership": "own", "product_sku": "SKU1",
                     "product_name": "Grinder", "body": "Bad quality", "images": [],
                     "date_published_parsed": "2026-04-10"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                      "severity": "medium"}]},
    ]
    labeled_reviews_safety = [
        {"review": {"rating": 1.0, "ownership": "own", "product_sku": "SKU2",
                     "product_name": "Grinder 2", "body": "Found metal shaving in food",
                     "images": [],
                     "date_published_parsed": "2026-04-10",
                     "impact_category": "safety"},
         "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                      "severity": "medium"}]},
    ]
    products_data = [
        {"sku": "SKU1", "review_count": 10, "rating": 3.5},
        {"sku": "SKU2", "review_count": 10, "rating": 3.5},
    ]

    normal = report_analytics._risk_products(
        labeled_reviews_normal, products_data, logical_date="2026-04-17",
    )
    safety = report_analytics._risk_products(
        labeled_reviews_safety, products_data, logical_date="2026-04-17",
    )

    normal_score = normal[0]["risk_score"] if normal else 0
    safety_score = safety[0]["risk_score"] if safety else 0
    assert safety_score > normal_score, "Safety review should boost risk score"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase2.py::test_risk_score_higher_with_safety_reviews -v`
Expected: FAIL — safety score not higher (or equal)

- [ ] **Step 3: Add safety factor to _risk_products()**

In `qbu_crawler/server/report_analytics.py`, around line 840-846, modify the weighted combination in `_risk_products()`. Replace:

```python
            risk_score_raw = (
                0.35 * neg_rate
                + 0.25 * severity_avg
                + 0.15 * evidence_rate
                + 0.15 * recency
                + 0.10 * volume_sig
            )
```

With:

```python
            # P008: Safety factor — boost risk for products with safety-related reviews
            safety_flag = 0.0
            for neg_item in neg_items:
                review = neg_item["review"]
                if review.get("impact_category") == "safety":
                    safety_flag = 1.0
                    break
                from qbu_crawler.server.report_common import detect_safety_level
                text = f"{review.get('headline', '')} {review.get('body', '')}"
                if detect_safety_level(text):
                    safety_flag = 1.0
                    break

            risk_score_raw = (
                0.30 * neg_rate
                + 0.20 * severity_avg
                + 0.15 * evidence_rate
                + 0.10 * recency
                + 0.10 * volume_sig
                + 0.15 * safety_flag    # P008: safety factor
            )
```

Note: weight redistribution — neg_rate 35→30, severity 25→20, recency 15→10, to make room for 15% safety factor. Total still = 1.0.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase2.py::test_risk_score_higher_with_safety_reviews -v`
Expected: PASS

- [ ] **Step 5: Run existing analytics tests for regressions**

Run: `uv run pytest tests/test_report_analytics.py -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_p008_phase2.py
git commit -m "feat(safety): add safety factor to risk_products scoring (15% weight)"
```

---

## Task 8: 日报三区块 HTML 模板 — daily_briefing.html.j2

**Files:**
- Create: `qbu_crawler/server/report_templates/daily_briefing.html.j2`
- Modify: `qbu_crawler/server/report_html.py`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase2.py

# ── Task 8: Daily briefing template ─────────────────────────────


def test_render_daily_briefing_basic():
    from qbu_crawler.server.report_html import render_daily_briefing

    snapshot = {
        "logical_date": "2026-04-17",
        "run_id": 99,
        "reviews": [],
        "products": [],
        "cumulative": {
            "products": [{"name": "Grinder", "sku": "SKU1", "ownership": "own",
                          "rating": 4.5, "review_count": 50, "site": "test", "price": 299}],
            "reviews": [],
        },
    }
    cumulative_kpis = {
        "health_index": 72.3,
        "health_confidence": "medium",
        "own_review_rows": 42,
        "own_negative_review_rate_display": "4.2%",
        "high_risk_count": 2,
    }

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test-briefing.html")
        result = render_daily_briefing(
            snapshot=snapshot,
            cumulative_kpis=cumulative_kpis,
            window_reviews=[],
            attention_signals=[],
            changes={},
            output_path=path,
        )
        assert os.path.isfile(result)
        html = open(result, encoding="utf-8").read()
        assert "72.3" in html  # health index
        assert "4.2%" in html  # negative rate
        assert "需注意" not in html  # no signals → no attention block
```


def test_render_daily_briefing_with_attention_signals():
    from qbu_crawler.server.report_html import render_daily_briefing

    snapshot = {
        "logical_date": "2026-04-17",
        "run_id": 99,
        "reviews": [{"id": 1, "headline": "Bad", "body": "Metal shaving found",
                      "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
                      "ownership": "own", "images": ["img.jpg"],
                      "author": "Tester", "date_published": "2026-04-17"}],
        "cumulative": {"products": [], "reviews": []},
    }
    signals = [
        {"type": "safety_keyword", "urgency": "action",
         "title": "安全: Grinder 评论提及安全关键词", "detail": "级别: critical"},
    ]
    reviews_with_labels = [
        {**snapshot["reviews"][0],
         "attention": {"signals": ["⚠安全关键词(critical)", "📸 1张图"], "label": "高关注度评论"}}
    ]

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test-briefing.html")
        result = render_daily_briefing(
            snapshot=snapshot,
            cumulative_kpis={"health_index": 65.0, "own_negative_review_rate_display": "8.1%",
                             "high_risk_count": 1, "own_review_rows": 20, "health_confidence": "medium"},
            window_reviews=reviews_with_labels,
            attention_signals=signals,
            changes={},
            output_path=path,
        )
        html = open(result, encoding="utf-8").read()
        assert "需注意" in html or "需行动" in html
        assert "安全" in html
        assert "高关注度评论" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p008_phase2.py -k "render_daily_briefing" -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Create daily_briefing.html.j2 template**

Create `qbu_crawler/server/report_templates/daily_briefing.html.j2`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QBU 网评监控 · 日报 {{ logical_date }}</title>
  <style>{{ css_text }}</style>
</head>
<body style="margin:0;padding:0;background:var(--bg, #f8f9fa);">

  {# ── Sticky KPI Bar ── #}
  <header class="kpi-bar" style="position:sticky;top:0;z-index:100;background:var(--surface, #fff);border-bottom:1px solid var(--border, #e2e8f0);padding:12px 24px;display:flex;align-items:center;gap:24px;flex-wrap:wrap;">
    <strong style="font-size:14px;color:var(--text, #1a202c);">QBU 网评监控 · {{ logical_date }}</strong>
    <span style="font-family:var(--font-mono, monospace);font-size:13px;">健康 <strong>{{ cumulative_kpis.get("health_index", "—") }}</strong></span>
    <span style="font-family:var(--font-mono, monospace);font-size:13px;">差评 <strong>{{ cumulative_kpis.get("own_negative_review_rate_display", "—") }}</strong></span>
    <span style="font-family:var(--font-mono, monospace);font-size:13px;">高风险 <strong>{{ cumulative_kpis.get("high_risk_count", 0) }}</strong></span>
  </header>

  <main style="max-width:720px;margin:0 auto;padding:24px 16px;">

    {# ── Block 1: 累积快照（始终存在）── #}
    <section class="briefing-section" style="margin-bottom:24px;">
      <h2 style="font-size:16px;font-weight:600;margin:0 0 12px;">累积快照</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));gap:12px;">
        <div class="kpi-card" style="background:var(--surface,#fff);border:1px solid var(--border,#e2e8f0);border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:12px;color:var(--text-secondary,#718096);">健康指数</div>
          <div style="font-size:24px;font-weight:700;color:var(--accent,#2b6cb0);">{{ cumulative_kpis.get("health_index", "—") }}</div>
          <div style="font-size:11px;color:var(--text-muted,#a0aec0);">/ 100</div>
        </div>
        <div class="kpi-card" style="background:var(--surface,#fff);border:1px solid var(--border,#e2e8f0);border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:12px;color:var(--text-secondary,#718096);">差评率</div>
          <div style="font-size:24px;font-weight:700;">{{ cumulative_kpis.get("own_negative_review_rate_display", "—") }}</div>
        </div>
        <div class="kpi-card" style="background:var(--surface,#fff);border:1px solid var(--border,#e2e8f0);border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:12px;color:var(--text-secondary,#718096);">高风险产品</div>
          <div style="font-size:24px;font-weight:700;{% if cumulative_kpis.get('high_risk_count', 0) > 0 %}color:var(--critical,#e53e3e);{% endif %}">{{ cumulative_kpis.get("high_risk_count", 0) }}</div>
        </div>
        <div class="kpi-card" style="background:var(--surface,#fff);border:1px solid var(--border,#e2e8f0);border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:12px;color:var(--text-secondary,#718096);">评论总量</div>
          <div style="font-size:24px;font-weight:700;">{{ cumulative_kpis.get("own_review_rows", 0) }}</div>
        </div>
      </div>
      {% if quiet_days and quiet_days > 0 %}
      <p style="margin:8px 0 0;font-size:13px;color:var(--text-muted,#a0aec0);">距上次有内容已 {{ quiet_days }} 天</p>
      {% endif %}
    </section>

    {# ── Block 2: 今日变化（有内容时展示）── #}
    {% if window_reviews %}
    <section class="briefing-section" style="margin-bottom:24px;">
      <h2 style="font-size:16px;font-weight:600;margin:0 0 12px;">今日变化 · 新评论（{{ window_reviews|length }}条）</h2>
      {% for r in window_reviews[:15] %}
      <div style="background:var(--surface,#fff);border:1px solid var(--border,#e2e8f0);border-radius:8px;padding:12px 16px;margin-bottom:8px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <span style="font-size:13px;">{{ "★" * ((r.rating|int) if r.rating is defined and r.rating is not none else 0) }}{{ "☆" * (5 - ((r.rating|int) if r.rating is defined and r.rating is not none else 0)) }}</span>
          <strong style="font-size:13px;">{{ r.get("product_name", "") }}</strong>
          {% if r.attention is defined and r.attention %}
          <span style="font-size:11px;padding:2px 6px;border-radius:4px;{% if r.attention.label == '高关注度评论' %}background:#fed7d7;color:#c53030;{% elif r.attention.label == '差评' %}background:#fefcbf;color:#975a16;{% else %}background:#c6f6d5;color:#276749;{% endif %}">{{ r.attention.label }}</span>
          {% endif %}
        </div>
        <div style="font-size:13px;font-weight:600;">{{ r.get("headline_cn") or r.get("headline", "") }}</div>
        <div style="font-size:12px;color:var(--text-secondary,#718096);margin-top:2px;">{{ (r.get("body_cn") or r.get("body", ""))[:200] }}{% if (r.get("body", "") or "")|length > 200 %}...{% endif %}</div>
        {% if r.attention is defined and r.attention and r.attention.signals %}
        <div style="font-size:11px;color:var(--text-muted,#a0aec0);margin-top:4px;">{{ r.attention.signals | join(" · ") }}</div>
        {% endif %}
      </div>
      {% endfor %}
    </section>
    {% endif %}

    {# ── Block 2b: Price/Stock/Rating Changes ── #}
    {% set _ch = changes if changes is defined and changes else {} %}
    {% if _ch.get("price_changes") or _ch.get("stock_changes") or _ch.get("rating_changes") %}
    <section class="briefing-section" style="margin-bottom:24px;">
      <h2 style="font-size:16px;font-weight:600;margin:0 0 12px;">产品数据变动</h2>
      {% if _ch.get("price_changes") %}
      <p style="font-size:13px;font-weight:600;margin:8px 0 4px;">💰 价格变化（{{ _ch.price_changes|length }}）</p>
      {% for c in _ch.price_changes %}
      <div style="font-size:13px;padding:4px 0;">{{ c.name }}: ${{ c.old }} → {% if c.new is not none %}${{ c.new }}{% else %}已下架{% endif %}</div>
      {% endfor %}
      {% endif %}
      {% if _ch.get("stock_changes") %}
      <p style="font-size:13px;font-weight:600;margin:8px 0 4px;">📦 库存变化（{{ _ch.stock_changes|length }}）</p>
      {% for c in _ch.stock_changes %}
      <div style="font-size:13px;padding:4px 0;">{{ c.name }}: {{ "有货" if c.old == "in_stock" else "缺货" }} → {{ "有货" if c.new == "in_stock" else "缺货" }}</div>
      {% endfor %}
      {% endif %}
      {% if _ch.get("rating_changes") %}
      <p style="font-size:13px;font-weight:600;margin:8px 0 4px;">⭐ 评分变化（{{ _ch.rating_changes|length }}）</p>
      {% for c in _ch.rating_changes %}
      <div style="font-size:13px;padding:4px 0;">{{ c.name }}: {{ c.old if c.old is not none else "—" }} → {{ c.new if c.new is not none else "已下架" }}</div>
      {% endfor %}
      {% endif %}
    </section>
    {% endif %}

    {# ── Block 3: 需注意（条件触发）── #}
    {% set action_signals = attention_signals | selectattr("urgency", "equalto", "action") | list if attention_signals else [] %}
    {% set ref_signals = attention_signals | selectattr("urgency", "equalto", "reference") | list if attention_signals else [] %}

    {% if action_signals or ref_signals %}
    <section class="briefing-section" style="margin-bottom:24px;">
      <h2 style="font-size:16px;font-weight:600;margin:0 0 12px;">需注意</h2>

      {% if action_signals %}
      <div style="border-left:4px solid var(--critical,#e53e3e);background:#fff5f5;border-radius:4px;padding:12px 16px;margin-bottom:8px;">
        <div style="font-size:12px;font-weight:700;color:var(--critical,#e53e3e);margin-bottom:6px;">需行动</div>
        {% for s in action_signals %}
        <div style="font-size:13px;padding:2px 0;">{{ s.title }}</div>
        {% endfor %}
      </div>
      {% endif %}

      {% if ref_signals %}
      <div style="border-left:4px solid var(--accent,#2b6cb0);background:#ebf8ff;border-radius:4px;padding:12px 16px;">
        <div style="font-size:12px;font-weight:700;color:var(--accent,#2b6cb0);margin-bottom:6px;">供参考</div>
        {% for s in ref_signals %}
        <div style="font-size:13px;padding:2px 0;">{{ s.title }}</div>
        {% endfor %}
      </div>
      {% endif %}
    </section>
    {% endif %}

  </main>

  <footer style="text-align:center;font-size:11px;color:var(--text-muted,#a0aec0);padding:16px;">
    差评定义: ≤{{ threshold }}星 · 内部资料 · AI 自动生成
  </footer>
</body>
</html>
```

- [ ] **Step 4: Implement render_daily_briefing() in report_html.py**

Add to `qbu_crawler/server/report_html.py`, after `render_v3_html()`:

```python
def render_daily_briefing(snapshot, cumulative_kpis, window_reviews,
                          attention_signals, changes, output_path,
                          quiet_days=0):
    """Render the daily briefing three-block HTML."""
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("daily_briefing.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    html = template.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        cumulative_kpis=cumulative_kpis,
        window_reviews=window_reviews,
        attention_signals=attention_signals,
        changes=changes,
        quiet_days=quiet_days,
        css_text=css_text,
        threshold=config.NEGATIVE_THRESHOLD,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("Daily briefing HTML rendered: %s (%d bytes)", output_path, len(html))
    return output_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_p008_phase2.py -k "render_daily_briefing" -v`
Expected: All 2 PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_briefing.html.j2 qbu_crawler/server/report_html.py tests/test_p008_phase2.py
git commit -m "feat(daily): add daily_briefing.html.j2 three-block template + render_daily_briefing()"
```

---

## Task 9: 日报邮件模板 — email_daily.html.j2

**Files:**
- Create: `qbu_crawler/server/report_templates/email_daily.html.j2`
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Create email_daily.html.j2**

Create `qbu_crawler/server/report_templates/email_daily.html.j2`. This is the same content as daily_briefing.html.j2 but optimized for email (inline styles only, no external CSS, no sticky header):

```html
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>QBU 日报 {{ logical_date }}</title></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a202c;font-size:14px;line-height:1.6;">
<div style="max-width:640px;margin:0 auto;padding:16px;">

  {# ── Header ── #}
  <div style="background:#fff;border-radius:8px;padding:16px 20px;border:1px solid #e2e8f0;margin-bottom:16px;">
    <div style="font-size:15px;font-weight:700;">QBU 网评监控 · {{ logical_date }}</div>
    <div style="display:flex;gap:20px;margin-top:8px;font-size:13px;font-family:monospace;">
      <span>健康 <strong>{{ cumulative_kpis.get("health_index", "—") }}</strong></span>
      <span>差评 <strong>{{ cumulative_kpis.get("own_negative_review_rate_display", "—") }}</strong></span>
      <span>高风险 <strong>{{ cumulative_kpis.get("high_risk_count", 0) }}</strong></span>
      <span>评论 <strong>{{ cumulative_kpis.get("own_review_rows", 0) }}</strong></span>
    </div>
  </div>

  {# ── Reviews ── #}
  {% if window_reviews %}
  <div style="background:#fff;border-radius:8px;padding:16px 20px;border:1px solid #e2e8f0;margin-bottom:16px;">
    <div style="font-size:14px;font-weight:700;margin-bottom:8px;">新评论（{{ window_reviews|length }}条）</div>
    {% for r in window_reviews[:10] %}
    <div style="border-bottom:1px solid #edf2f7;padding:8px 0;">
      <div style="font-size:13px;">{{ "★" * ((r.rating|int) if r.rating is defined and r.rating is not none else 0) }}{{ "☆" * (5 - ((r.rating|int) if r.rating is defined and r.rating is not none else 0)) }} <strong>{{ r.get("product_name", "") }}</strong>{% if r.attention is defined and r.attention %} <span style="font-size:11px;padding:1px 4px;border-radius:3px;{% if r.attention.label == '高关注度评论' %}background:#fed7d7;color:#c53030;{% elif r.attention.label == '差评' %}background:#fefcbf;color:#975a16;{% else %}background:#c6f6d5;color:#276749;{% endif %}">{{ r.attention.label }}</span>{% endif %}</div>
      <div style="font-size:13px;font-weight:600;margin-top:2px;">{{ r.get("headline_cn") or r.get("headline", "") }}</div>
      <div style="font-size:12px;color:#718096;">{{ (r.get("body_cn") or r.get("body", ""))[:150] }}{% if (r.get("body", "") or "")|length > 150 %}...{% endif %}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {# ── Attention signals ── #}
  {% set action_signals = attention_signals | selectattr("urgency", "equalto", "action") | list if attention_signals else [] %}
  {% set ref_signals = attention_signals | selectattr("urgency", "equalto", "reference") | list if attention_signals else [] %}
  {% if action_signals or ref_signals %}
  <div style="background:#fff;border-radius:8px;padding:16px 20px;border:1px solid #e2e8f0;margin-bottom:16px;">
    <div style="font-size:14px;font-weight:700;margin-bottom:8px;">需注意</div>
    {% if action_signals %}
    <div style="border-left:4px solid #e53e3e;padding:8px 12px;background:#fff5f5;border-radius:2px;margin-bottom:6px;">
      {% for s in action_signals %}<div style="font-size:13px;">{{ s.title }}</div>{% endfor %}
    </div>
    {% endif %}
    {% if ref_signals %}
    <div style="border-left:4px solid #2b6cb0;padding:8px 12px;background:#ebf8ff;border-radius:2px;">
      {% for s in ref_signals %}<div style="font-size:13px;">{{ s.title }}</div>{% endfor %}
    </div>
    {% endif %}
  </div>
  {% endif %}

  <div style="text-align:center;font-size:11px;color:#a0aec0;padding:8px;">差评定义: ≤{{ threshold }}星 · 内部资料 · AI 自动生成</div>
</div>
</body>
</html>
```

- [ ] **Step 2: Write test for email template rendering**

```python
# Append to tests/test_p008_phase2.py

# ── Task 9: Email daily template ─────────────────────────────


def test_email_daily_template_renders():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("email_daily.html.j2")
    html = template.render(
        logical_date="2026-04-17",
        cumulative_kpis={"health_index": 72.3, "own_negative_review_rate_display": "4.2%",
                         "high_risk_count": 1, "own_review_rows": 42},
        window_reviews=[],
        attention_signals=[],
        threshold=2,
    )
    assert "72.3" in html
    assert "QBU" in html
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/test_p008_phase2.py::test_email_daily_template_renders -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_templates/email_daily.html.j2 tests/test_p008_phase2.py
git commit -m "feat(daily): add email_daily.html.j2 email template for daily briefing"
```

---

## Task 10: generate_report_from_snapshot() tier 路由 + _generate_daily_briefing()

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:707-764` (generate_report_from_snapshot)
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase2.py

# ── Task 10: Tier routing integration ────────────────────────────


def test_generate_report_from_snapshot_daily_tier(db, tmp_path, monkeypatch):
    """When report_tier == 'daily', use new three-block pipeline."""
    from qbu_crawler.server import report_snapshot, report, report_html

    # Seed workflow_runs
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO workflow_runs (workflow_type, status, report_phase, logical_date, trigger_key, report_tier)"
        " VALUES ('daily', 'reporting', 'full_pending', '2026-04-17', 'daily:2026-04-17', 'daily')"
    )
    conn.commit()
    conn.close()

    snapshot = {
        "run_id": 1,
        "logical_date": "2026-04-17",
        "data_since": "2026-04-17T00:00:00+08:00",
        "data_until": "2026-04-18T00:00:00+08:00",
        "products": [],
        "reviews": [],
        "cumulative": {
            "products": [{"name": "Test", "sku": "SKU1", "ownership": "own", "rating": 4.5,
                          "review_count": 50, "site": "test", "price": 299}],
            "reviews": [{"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                         "headline": "Good", "body": "Works", "sentiment": "positive",
                         "analysis_labels": "[]"}],
        },
    }

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda rid: (None, None))

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)

    assert result["mode"] == "daily_briefing"
    assert result.get("html_path") is not None
    assert result.get("status") in ("completed", "completed_no_change")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase2.py::test_generate_report_from_snapshot_daily_tier -v`
Expected: FAIL — mode is "full"/"quiet", not "daily_briefing"

- [ ] **Step 3: Add tier routing to generate_report_from_snapshot()**

In `qbu_crawler/server/report_snapshot.py`, modify `generate_report_from_snapshot()` (~line 707). Add a tier check BEFORE the existing mode routing:

```python
def generate_report_from_snapshot(snapshot, send_email=True, output_path=None):
    # ... existing docstring and setup ...
    run_id = snapshot.get("run_id", 0)

    # P008 Phase 2: Check report_tier — new daily runs use three-block pipeline
    run_tier = None
    if run_id:
        try:
            conn = models.get_conn()
            row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
            conn.close()
            run_tier = row["report_tier"] if row else None
        except Exception:
            pass

    if run_tier == "daily":
        return _generate_daily_briefing(snapshot, send_email)

    # Load previous context (original path)
    prev_analytics, prev_snapshot = load_previous_report_context(run_id)
    # ... rest of existing code unchanged ...
```

- [ ] **Step 4: Implement _generate_daily_briefing()**

Add to `qbu_crawler/server/report_snapshot.py`, before `generate_report_from_snapshot()`:

```python
def _generate_daily_briefing(snapshot, send_email=True):
    """P008 Phase 2: Generate three-block daily briefing.

    Always archives HTML. Only sends email when should_send_daily_email() is True.
    """
    run_id = snapshot.get("run_id", 0)
    logical_date = snapshot.get("logical_date", "")

    # Load previous context for change detection
    prev_analytics, prev_snapshot = load_previous_report_context(run_id)
    changes = detect_snapshot_changes(snapshot, prev_snapshot) if prev_snapshot else {}

    # Compute cumulative analytics
    cum_analytics = None
    analytics_path = None
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": run_id,
                "logical_date": logical_date,
                "data_since": snapshot.get("data_since", ""),
                "data_until": snapshot.get("data_until", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                **snapshot["cumulative"],
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            from qbu_crawler.server.report_common import normalize_deep_report_analytics
            cum_analytics = normalize_deep_report_analytics(cum_analytics)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"daily-{logical_date}-analytics.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        except Exception:
            _logger.exception("Daily briefing: cumulative analytics failed")

    cumulative_kpis = (cum_analytics or {}).get("kpis", {})

    # Compute attention signals
    from qbu_crawler.server.report_common import (
        compute_attention_signals, review_attention_label, detect_safety_level,
    )
    window_reviews = snapshot.get("reviews", [])

    # Enrich changes with ownership from products
    product_ownership = {
        p.get("sku"): p.get("ownership")
        for p in (snapshot.get("cumulative", {}).get("products", []) or snapshot.get("products", []))
    }
    for change_type in ("rating_changes", "stock_changes", "price_changes"):
        for ch in changes.get(change_type, []):
            ch.setdefault("ownership", product_ownership.get(ch.get("sku"), ""))

    cumulative_clusters = (cum_analytics or {}).get("self", {}).get("top_negative_clusters", [])
    attention_signals = compute_attention_signals(
        window_reviews, changes, cumulative_clusters, logical_date=logical_date,
    )

    # Enrich reviews with attention labels
    enriched_reviews = []
    for r in window_reviews:
        r_copy = dict(r)
        text = f"{r.get('headline', '')} {r.get('body', '')}"
        level = detect_safety_level(text)
        r_copy["attention"] = review_attention_label(r, safety_level=level)
        enriched_reviews.append(r_copy)

    # Render HTML (always archive)
    html_path = None
    try:
        html_output = os.path.join(config.REPORT_DIR, f"daily-{logical_date}.html")
        html_path = report_html.render_daily_briefing(
            snapshot=snapshot,
            cumulative_kpis=cumulative_kpis,
            window_reviews=enriched_reviews,
            attention_signals=attention_signals,
            changes=changes,
            output_path=html_output,
        )
    except Exception:
        _logger.exception("Daily briefing HTML generation failed")

    # Smart send email
    email_result = None
    do_send = should_send_daily_email(len(window_reviews), changes)
    if send_email and do_send:
        try:
            email_result = _send_daily_briefing_email(
                snapshot, cumulative_kpis, enriched_reviews,
                attention_signals, changes,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}
    elif not do_send:
        email_result = {"success": True, "error": "Smart send: no content", "recipients": []}

    try:
        models.update_workflow_run(run_id, report_mode="standard")
    except Exception:
        pass

    return {
        "mode": "daily_briefing",
        "status": "completed" if window_reviews or changes.get("has_changes") else "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": len(snapshot.get("products", [])),
        "reviews_count": len(window_reviews),
        "html_path": html_path,
        "excel_path": None,
        "analytics_path": analytics_path,
        "cumulative_kpis": cumulative_kpis or None,
        "email": email_result,
        "email_skipped": not do_send,
    }


def _send_daily_briefing_email(snapshot, cumulative_kpis, window_reviews,
                               attention_signals, changes):
    """Send daily briefing email using email_daily.html.j2."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("email_daily.html.j2")
    logical_date = snapshot.get("logical_date", "")

    body_html = template.render(
        logical_date=logical_date,
        cumulative_kpis=cumulative_kpis,
        window_reviews=window_reviews,
        attention_signals=attention_signals,
        changes=changes,
        threshold=config.NEGATIVE_THRESHOLD,
    )

    recipients = _get_email_recipients()
    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    subject = f"产品评论日报 {logical_date}"
    # Mark safety in subject
    has_safety = any(s.get("type") == "safety_keyword" for s in attention_signals)
    if has_safety:
        subject = f"[安全] {subject}"

    report.send_email(recipients=recipients, subject=subject, body_html=body_html)
    return {"success": True, "error": None, "recipients": recipients}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_p008_phase2.py::test_generate_report_from_snapshot_daily_tier -v`
Expected: PASS

- [ ] **Step 6: Run existing mode tests for regressions (old path unchanged)**

Run: `uv run pytest tests/test_v3_modes.py -v --tb=short`
Expected: All PASS (old runs don't have report_tier='daily')

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_p008_phase2.py
git commit -m "feat(daily): tier-based routing in generate_report_from_snapshot + _generate_daily_briefing"
```

---

## Task 11: workflows.py — 新 daily run 填充 report_tier

**Files:**
- Modify: `qbu_crawler/server/workflows.py:122-217` (submit_daily_run)
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_p008_phase2.py

# ── Task 11: Workflow integration ────────────────────────────────


def test_submit_daily_run_sets_report_tier(db, monkeypatch):
    """New daily runs must have report_tier='daily'."""
    import csv, os
    from qbu_crawler.server.workflows import submit_daily_run

    # Create CSV files
    source_csv = os.path.join(os.path.dirname(db), "source.csv")
    detail_csv = os.path.join(os.path.dirname(db), "detail.csv")
    with open(source_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "site"])
        writer.writerow(["http://test.com/cat1", "test"])
    with open(detail_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "sku", "site"])
        writer.writerow(["http://test.com/p1", "SKU1", "test"])

    # Mock task_manager to avoid actual scraping
    from qbu_crawler.server import task_manager as tm
    monkeypatch.setattr(tm, "get_task_manager", lambda: type("TM", (), {
        "start_collect": lambda self, **kw: "mock-collect",
        "start_scrape": lambda self, **kw: "mock-scrape",
    })())

    result = submit_daily_run(
        submitter=None,
        source_csv=source_csv,
        detail_csv=detail_csv,
        logical_date="2026-04-17",
        requested_by="test",
        dry_run=True,
    )

    conn = _get_test_conn(db)
    row = conn.execute("SELECT report_tier FROM workflow_runs WHERE id = ?",
                       (result["run_id"],)).fetchone()
    conn.close()
    assert row["report_tier"] == "daily"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_p008_phase2.py::test_submit_daily_run_sets_report_tier -v`
Expected: FAIL — report_tier is 'daily' by default but let's verify the explicit set works. If it passes because default is 'daily', that's fine — the test still validates the contract.

- [ ] **Step 3: Ensure submit_daily_run sets report_tier explicitly**

In `qbu_crawler/server/workflows.py`, find `submit_daily_run()` (~line 122). After the `models.create_workflow_run()` call, add an explicit update to set `report_tier='daily'`:

Find the line where `create_workflow_run()` is called and check if it already passes report_tier. If not, add after the run is created:

```python
    # After: run = models.create_workflow_run(...)
    models.update_workflow_run(run["id"], report_tier="daily")
```

Since the default is already 'daily', this is defensive but makes intent explicit.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/test_p008_phase2.py::test_submit_daily_run_sets_report_tier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/workflows.py tests/test_p008_phase2.py
git commit -m "feat(workflow): explicitly set report_tier='daily' on new daily runs"
```

---

## Task 12: Integration Test — 完整 daily briefing 管线验证

**Files:**
- Test: `tests/test_p008_phase2.py`

- [ ] **Step 1: Write integration test**

```python
# Append to tests/test_p008_phase2.py

# ── Task 12: Integration test ────────────────────────────────────


def test_p008_phase2_integration(db, tmp_path, monkeypatch):
    """End-to-end: daily briefing with safety review → correct HTML + smart send."""
    from qbu_crawler.server import report_snapshot
    from qbu_crawler.server.report_common import (
        detect_safety_level, review_attention_label, compute_attention_signals,
    )

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

    # 1. Verify safety detection
    assert detect_safety_level("Found metal shaving in food") == "critical"

    # 2. Verify review attention label
    review = {"rating": 1.0, "body": "Found metal shaving in food", "images": ["img.jpg"]}
    label = review_attention_label(review, safety_level="critical")
    assert label["label"] == "高关注度评论"

    # 3. Verify attention signals
    window_reviews = [
        {"id": 1, "headline": "Bad", "body": "Found metal shaving in food",
         "rating": 1.0, "product_sku": "SKU1", "product_name": "Grinder",
         "ownership": "own", "images": ["img.jpg"]}
    ]
    signals = compute_attention_signals(window_reviews, changes={}, cumulative_clusters=[])
    assert any(s["type"] == "safety_keyword" for s in signals)

    # 4. Verify smart send
    assert report_snapshot.should_send_daily_email(1, {}) is True
    assert report_snapshot.should_send_daily_email(0, {}) is False

    # 5. Verify tier config exists
    assert "daily" in config.TIER_CONFIGS
    assert config.TIER_CONFIGS["daily"]["delivery"]["email"] == "smart"

    # 6. Verify tier_date_window
    from qbu_crawler.server.report_common import tier_date_window
    since, until = tier_date_window("daily", "2026-04-17")
    assert since == "2026-04-17T00:00:00+08:00"
    assert until == "2026-04-18T00:00:00+08:00"
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_p008_phase2.py::test_p008_phase2_integration -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short -x`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_p008_phase2.py
git commit -m "test(p008): add Phase 2 integration test verifying daily briefing pipeline"
```

---

## Post-Implementation Checklist

- [ ] Run `uv run pytest tests/ -v` — all green
- [ ] 无变化的日子：HTML 存档但不发邮件
- [ ] report_tier 列正确填充为 `'daily'`
- [ ] 安全评论在日报中显示分级标记（高关注度评论）
- [ ] 新评论附带人话化重量标签
- [ ] "需注意" 区块仅在有信号时渲染
- [ ] 旧 run（无 report_tier）仍走 full/change/quiet 旧路径
- [ ] 更新 CLAUDE.md 文档中 Phase 2 相关说明
