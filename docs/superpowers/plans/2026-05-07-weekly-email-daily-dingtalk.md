# Weekly Email Daily DingTalk Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将业务邮件从每日发送改为首次基线 + 每周周报，同时每天在钉钉发送基于真实入库评论的轻量业务摘要。

**Architecture:** 保留现有 daily workflow、每日 snapshot 和本地产物链路，在报告发送层增加集中邮件 cadence 策略。新增 `daily_digest` 负责从当天窗口评论构建确定性钉钉摘要；周报日派生 7 天窗口 snapshot 生成邮件与附件，并通过 `report_window` 驱动“今日变化 / 本周变化”文案。

**Tech Stack:** Python 3.10, SQLite, FastAPI background workers, Jinja2 templates, openpyxl, pytest, existing notification_outbox + OpenClaw bridge

---

## File Structure

**Create:**
- `qbu_crawler/server/report_cadence.py` — 业务邮件发送频率策略，输出 send/skip、reason、cadence、window_type。
- `qbu_crawler/server/daily_digest.py` — 构建每日钉钉业务摘要 payload，负责 TOP3 选择、文案截断、确定性分析 fallback。
- `tests/server/test_weekly_email_cadence.py` — 覆盖首次基线、周报日、非周报日、daily 模式兼容。
- `tests/server/test_daily_dingtalk_digest.py` — 覆盖有新增、无新增、自有 TOP3、竞品 TOP3、分析事实来源。
- `tests/server/test_weekly_report_window.py` — 覆盖 weekly snapshot 7 天窗口、累计全景不混淆、HTML / 邮件窗口文案。
- `docs/devlogs/D030-weekly-email-daily-dingtalk.md` — 记录本次实现、验证和生产注意事项。

**Modify:**
- `qbu_crawler/config.py` — 新增 `REPORT_EMAIL_CADENCE`、`REPORT_WEEKLY_EMAIL_WEEKDAY`、`REPORT_WEEKLY_WINDOW_DAYS`、`REPORT_EMAIL_SEND_BOOTSTRAP`。
- `.env.example` — 补充邮件频率与周报窗口配置示例。
- `qbu_crawler/server/workflows.py` — 在 snapshot 后入队 `workflow_daily_digest`；在 full_pending 阶段调用 cadence 策略；周报日传入 weekly snapshot；状态和通知 payload 写清邮件 sent/skipped。
- `qbu_crawler/server/report_snapshot.py` — 新增 weekly snapshot 派生入口；`generate_report_from_snapshot()` 接受 `delivery_context` 或读取 snapshot 内 `report_window`。
- `qbu_crawler/server/report.py` — 邮件 subject / body 识别 `report_window`；`render_email_full()` 将 `snapshot` 传给邮件模板。
- `qbu_crawler/server/report_html.py` — HTML 渲染前确保 analytics/snapshot 带 `report_window`。
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2` — 将“今日变化”改为由 `report_window` / bootstrap 语义驱动。
- `qbu_crawler/server/report_templates/email_full.html.j2` — 邮件正文改为基线/周报双语义，周报展示“本周概览”和累计快照。
- `qbu_crawler/server/notifier.py` — 为 `workflow_daily_digest` 准备 bridge template vars；full report 通知显示“业务邮件：已发送 / 已跳过（周报频率）”。
- `qbu_crawler/server/openclaw/bridge/app.py` — 新增 `workflow_daily_digest` Markdown 模板，调整 full report 模板措辞。
- `AGENTS.md` — 更新 OpenClaw 定时工作流、报告配置、报表语义治理增量。

**Do Not Modify Unless Tests Force It:**
- `qbu_crawler/models.py` — 第一版不新增表字段，继续使用 `workflow_runs.email_delivery_status`、`delivery_last_error`、`notification_outbox.kind/dedupe_key`。
- `scrapers/*` — 本需求不涉及采集站点逻辑。

---

## Chunk 1: 回归测试先行

### Task 1: 为邮件 cadence 写失败测试

**Files:**
- Create: `tests/server/test_weekly_email_cadence.py`
- Create: `qbu_crawler/server/report_cadence.py`
- Modify: `qbu_crawler/config.py`

- [ ] **Step 1: 编写首次基线发送测试**

在 `tests/server/test_weekly_email_cadence.py` 中新增：

```python
def test_bootstrap_run_sends_email_when_enabled(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr("qbu_crawler.config.REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr("qbu_crawler.config.REPORT_EMAIL_SEND_BOOTSTRAP", True, raising=False)

    decision = decide_business_email(
        run={"id": 1, "logical_date": "2026-05-07"},
        snapshot={"report_semantics": "bootstrap", "reviews_count": 10},
        mode="full",
    )

    assert decision.send_email is True
    assert decision.cadence == "bootstrap"
    assert decision.report_window_type == "bootstrap"
```

- [ ] **Step 2: 编写周报日发送测试**

新增：

```python
def test_weekly_report_day_sends_weekly_email(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr("qbu_crawler.config.REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr("qbu_crawler.config.REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)
    monkeypatch.setattr("qbu_crawler.config.REPORT_WEEKLY_WINDOW_DAYS", 7, raising=False)

    decision = decide_business_email(
        run={"id": 2, "logical_date": "2026-05-04"},
        snapshot={"report_semantics": "incremental", "reviews_count": 3},
        mode="full",
    )

    assert decision.send_email is True
    assert decision.cadence == "weekly"
    assert decision.report_window_type == "weekly"
    assert decision.window_days == 7
```

说明：`2026-05-04` 是周一，ISO weekday = 1。

- [ ] **Step 3: 编写非周报日跳过测试**

新增：

```python
def test_non_weekly_day_skips_business_email(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr("qbu_crawler.config.REPORT_EMAIL_CADENCE", "weekly", raising=False)
    monkeypatch.setattr("qbu_crawler.config.REPORT_WEEKLY_EMAIL_WEEKDAY", 1, raising=False)

    decision = decide_business_email(
        run={"id": 3, "logical_date": "2026-05-05"},
        snapshot={"report_semantics": "incremental", "reviews_count": 4},
        mode="full",
    )

    assert decision.send_email is False
    assert decision.reason == "weekly_cadence_skip"
    assert decision.report_window_type == "daily"
```

- [ ] **Step 4: 编写 daily 兼容测试**

新增：

```python
def test_daily_cadence_keeps_existing_email_behavior(monkeypatch):
    from qbu_crawler.server.report_cadence import decide_business_email

    monkeypatch.setattr("qbu_crawler.config.REPORT_EMAIL_CADENCE", "daily", raising=False)

    decision = decide_business_email(
        run={"id": 4, "logical_date": "2026-05-05"},
        snapshot={"report_semantics": "incremental", "reviews_count": 0},
        mode="quiet",
    )

    assert decision.send_email is True
    assert decision.cadence == "daily"
```

- [ ] **Step 5: 运行测试确认失败**

Run:

`uv run pytest tests/server/test_weekly_email_cadence.py -v`

Expected:

- FAIL，原因是 `qbu_crawler.server.report_cadence` 或 `decide_business_email` 尚不存在。

### Task 2: 为每日钉钉摘要写失败测试

**Files:**
- Create: `tests/server/test_daily_dingtalk_digest.py`
- Create: `qbu_crawler/server/daily_digest.py`

- [ ] **Step 1: 编写有新增评论摘要测试**

测试数据必须只使用 snapshot 中的真实字段：

```python
def test_daily_digest_builds_own_and_competitor_top3():
    from qbu_crawler.server.daily_digest import build_daily_digest

    snapshot = {
        "run_id": 9,
        "logical_date": "2026-05-07",
        "reviews_count": 4,
        "cumulative": {
            "reviews": [
                {"id": 1, "ownership": "own"},
                {"id": 2, "ownership": "competitor"},
            ]
        },
        "reviews": [
            {
                "id": 101,
                "product_sku": "OWN-1",
                "product_name": "Own Grinder",
                "ownership": "own",
                "rating": 1,
                "headline": "Broken",
                "body": "Switch broke after one use",
                "body_cn": "用一次开关就坏了",
                "analysis_labels": '[{"code":"after_sales","display":"售后履约"}]',
                "analysis_insight_cn": "自有产品出现低分质量信号，需要优先复核开关可靠性。",
            },
            {
                "id": 201,
                "product_sku": "CMP-1",
                "product_name": "Competitor Mixer",
                "ownership": "competitor",
                "rating": 5,
                "headline": "Easy",
                "body": "Very easy to clean",
                "body_cn": "非常容易清洁",
                "analysis_labels": '[{"code":"cleaning","display":"清洁便利"}]',
                "analysis_insight_cn": "竞品好评集中在清洁便利，可作为自有说明和结构优化参考。",
            },
        ],
    }

    digest = build_daily_digest(snapshot)

    assert digest["new_review_count"] == 4
    assert digest["own_top"][0]["sku"] == "OWN-1"
    assert digest["own_top"][0]["issue"] == "售后履约"
    assert digest["competitor_top"][0]["sku"] == "CMP-1"
    assert "清洁便利" in digest["analysis"]
```

- [ ] **Step 2: 编写无新增评论摘要测试**

```python
def test_daily_digest_handles_no_new_reviews():
    from qbu_crawler.server.daily_digest import build_daily_digest

    digest = build_daily_digest({
        "run_id": 10,
        "logical_date": "2026-05-07",
        "reviews_count": 0,
        "reviews": [],
        "cumulative": {"reviews": [{"ownership": "own"}, {"ownership": "competitor"}]},
    })

    assert digest["new_review_count"] == 0
    assert digest["message_title"] == "今日无新增评论"
    assert digest["own_top"] == []
    assert digest["competitor_top"] == []
    assert "累计样本" in digest["analysis"]
```

- [ ] **Step 3: 编写文案长度和事实来源测试**

新增断言：

```python
def test_daily_digest_truncates_original_text_without_inventing_sku():
    from qbu_crawler.server.daily_digest import build_daily_digest

    long_body = "A" * 500
    digest = build_daily_digest({
        "run_id": 11,
        "logical_date": "2026-05-07",
        "reviews_count": 1,
        "reviews": [{
            "id": 301,
            "product_sku": "SKU-ONLY",
            "product_name": "Only Product",
            "ownership": "own",
            "rating": 2,
            "headline": "Long",
            "body": long_body,
        }],
    })

    text = digest["own_top"][0]["original"]
    assert len(text) <= 140
    assert "SKU-ONLY" in digest["markdown"]
    assert "UNKNOWN" not in digest["markdown"]
```

- [ ] **Step 4: 运行测试确认失败**

Run:

`uv run pytest tests/server/test_daily_dingtalk_digest.py -v`

Expected:

- FAIL，原因是 `daily_digest.py` 或构建函数尚不存在。

### Task 3: 为周报窗口写失败测试

**Files:**
- Create: `tests/server/test_weekly_report_window.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`

- [ ] **Step 1: 编写 weekly snapshot 窗口测试**

使用 monkeypatch 避免真实 DB：

```python
def test_build_weekly_snapshot_uses_7_day_window(monkeypatch):
    from qbu_crawler.server import report_snapshot

    calls = {}

    def fake_query_report_data(since, until=None):
        calls["since"] = since
        calls["until"] = until
        return ([{"sku": "WEEK"}], [{"id": 1, "product_sku": "WEEK"}])

    monkeypatch.setattr("qbu_crawler.server.report.query_report_data", fake_query_report_data)
    monkeypatch.setattr("qbu_crawler.server.report.query_cumulative_data", lambda: ([], [{"id": 9}]))

    snapshot = report_snapshot.build_windowed_report_snapshot(
        {
            "run_id": 20,
            "logical_date": "2026-05-07",
            "data_until": "2026-05-08T00:00:00+08:00",
        },
        window_type="weekly",
        window_days=7,
    )

    assert snapshot["report_window"]["type"] == "weekly"
    assert snapshot["reviews_count"] == 1
    assert snapshot["cumulative"]["reviews_count"] == 1
    assert calls["until"] == "2026-05-08T00:00:00+08:00"
    assert str(calls["since"]).startswith("2026-05-01")
```

- [ ] **Step 2: 编写 HTML tab 文案测试**

```python
def test_html_uses_weekly_change_title():
    from qbu_crawler.server.report_html import _render_v3_html_string

    html = _render_v3_html_string(
        {"logical_date": "2026-05-07", "report_window": {"type": "weekly", "label": "本周"}},
        {"report_semantics": "incremental", "change_digest": {}, "kpis": {}},
    )

    assert "本周变化" in html
    assert "今日变化" not in html
```

- [ ] **Step 3: 编写邮件 subject / body 文案测试**

```python
def test_email_full_uses_weekly_language():
    from qbu_crawler.server.report import render_email_full

    html = render_email_full(
        {
            "logical_date": "2026-05-07",
            "data_since": "2026-05-01T00:00:00+08:00",
            "data_until": "2026-05-08T00:00:00+08:00",
            "report_window": {"type": "weekly", "label": "本周", "days": 7},
        },
        {"kpis": {"ingested_review_rows": 8}, "report_user_contract": {"kpis": {}}},
    )

    assert "本周" in html
    assert "今日新增" not in html
```

- [ ] **Step 4: 运行测试确认失败**

Run:

`uv run pytest tests/server/test_weekly_report_window.py -v`

Expected:

- FAIL，原因是 weekly snapshot 或模板文案尚未实现。

- [ ] **Step 5: 提交失败测试**

Run:

```bash
git add tests/server/test_weekly_email_cadence.py tests/server/test_daily_dingtalk_digest.py tests/server/test_weekly_report_window.py
git commit -m "test: 增加周报邮件和每日钉钉摘要回归"
```

Expected:

- 如果当前分支不适合提交，记录原因，继续执行后续任务；不要回滚已有未提交改动。

---

## Chunk 2: 配置与邮件频率策略

### Task 4: 新增配置项

**Files:**
- Modify: `qbu_crawler/config.py`
- Modify: `.env.example`

- [ ] **Step 1: 在 `config.py` 报告配置段新增配置**

在现有 `REPORT_LABEL_MODE` / `REPORT_PERSPECTIVE` 附近加入：

```python
REPORT_EMAIL_CADENCE = _enum_env("REPORT_EMAIL_CADENCE", "weekly", ("daily", "weekly"))
REPORT_WEEKLY_EMAIL_WEEKDAY = int(os.getenv("REPORT_WEEKLY_EMAIL_WEEKDAY", "1"))
if REPORT_WEEKLY_EMAIL_WEEKDAY < 1 or REPORT_WEEKLY_EMAIL_WEEKDAY > 7:
    raise ValueError("REPORT_WEEKLY_EMAIL_WEEKDAY must be between 1 and 7")
REPORT_WEEKLY_WINDOW_DAYS = int(os.getenv("REPORT_WEEKLY_WINDOW_DAYS", "7"))
if REPORT_WEEKLY_WINDOW_DAYS < 1:
    raise ValueError("REPORT_WEEKLY_WINDOW_DAYS must be >= 1")
REPORT_EMAIL_SEND_BOOTSTRAP = os.getenv("REPORT_EMAIL_SEND_BOOTSTRAP", "true").lower() == "true"
```

- [ ] **Step 2: 更新 `.env.example`**

在报告配置段加入：

```env
REPORT_EMAIL_CADENCE=weekly            # daily | weekly；默认首次基线 + 每周邮件
REPORT_WEEKLY_EMAIL_WEEKDAY=1          # ISO weekday：1=周一，7=周日
REPORT_WEEKLY_WINDOW_DAYS=7            # 周报窗口天数
REPORT_EMAIL_SEND_BOOTSTRAP=true       # 首次基线是否发送邮件
```

- [ ] **Step 3: 运行配置导入测试**

Run:

`uv run python -c "from qbu_crawler import config; print(config.REPORT_EMAIL_CADENCE, config.REPORT_WEEKLY_EMAIL_WEEKDAY, config.REPORT_WEEKLY_WINDOW_DAYS)"`

Expected:

- 输出 `weekly 1 7` 或当前 `.env` 覆盖后的合法值。

### Task 5: 实现 `report_cadence.py`

**Files:**
- Create: `qbu_crawler/server/report_cadence.py`
- Test: `tests/server/test_weekly_email_cadence.py`

- [ ] **Step 1: 新建决策数据结构**

实现：

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qbu_crawler import config


@dataclass(frozen=True)
class EmailDecision:
    send_email: bool
    reason: str
    cadence: str
    report_window_type: str
    window_days: int
```

- [ ] **Step 2: 实现日期解析 helper**

```python
def _logical_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])
```

- [ ] **Step 3: 实现 bootstrap 判断**

```python
def _is_bootstrap(snapshot: dict) -> bool:
    if snapshot.get("report_semantics") == "bootstrap":
        return True
    if snapshot.get("is_bootstrap") is True:
        return True
    return False
```

`report_cadence.py` 不访问 DB，也不使用 `run_id == 1` 猜首次运行。workflow 调用方必须基于 `load_previous_report_context(run_id)` 或等价的历史已完成报告上下文显式传入 `snapshot["is_bootstrap"]`。

- [ ] **Step 4: 实现 `decide_business_email()`**

```python
def decide_business_email(*, run: dict, snapshot: dict, mode: str) -> EmailDecision:
    window_days = int(getattr(config, "REPORT_WEEKLY_WINDOW_DAYS", 7))
    if _is_bootstrap(snapshot):
        if bool(getattr(config, "REPORT_EMAIL_SEND_BOOTSTRAP", True)):
            return EmailDecision(True, "bootstrap", "bootstrap", "bootstrap", window_days)
        return EmailDecision(False, "bootstrap_email_disabled", "bootstrap", "daily", window_days)

    cadence = getattr(config, "REPORT_EMAIL_CADENCE", "weekly")
    if cadence == "daily":
        return EmailDecision(True, "daily_cadence", "daily", "daily", window_days)

    logical_date = _logical_date(run.get("logical_date") or snapshot.get("logical_date"))
    if logical_date.isoweekday() == int(getattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1)):
        return EmailDecision(True, "weekly_report_day", "weekly", "weekly", window_days)
    return EmailDecision(False, "weekly_cadence_skip", "weekly", "daily", window_days)
```

- [ ] **Step 5: 运行 cadence 测试**

Run:

`uv run pytest tests/server/test_weekly_email_cadence.py -v`

Expected:

- PASS。

- [ ] **Step 6: 提交配置和策略**

Run:

```bash
git add qbu_crawler/config.py .env.example qbu_crawler/server/report_cadence.py tests/server/test_weekly_email_cadence.py
git commit -m "feat: 增加业务邮件周报频率策略"
```

---

## Chunk 3: 每日钉钉业务摘要

### Task 6: 实现 `daily_digest.py`

**Files:**
- Create: `qbu_crawler/server/daily_digest.py`
- Test: `tests/server/test_daily_dingtalk_digest.py`

- [ ] **Step 1: 新建模块和常量**

```python
from __future__ import annotations

import json

from qbu_crawler import config

MAX_ORIGINAL_LENGTH = 120
```

- [ ] **Step 2: 实现安全文本 helper**

```python
def _text(value) -> str:
    return str(value or "").strip()


def _truncate(value, limit=MAX_ORIGINAL_LENGTH) -> str:
    text = _text(value).replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
```

- [ ] **Step 3: 实现标签解析**

```python
def _label_display(review: dict) -> str:
    labels = review.get("analysis_labels")
    if isinstance(labels, str) and labels.strip():
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    if isinstance(labels, list) and labels:
        first = labels[0] or {}
        return _text(first.get("display") or first.get("label") or first.get("code"))
    return _text(review.get("impact_category") or review.get("failure_mode") or review.get("headline") or "未分类")
```

- [ ] **Step 4: 实现评论展示转换**

```python
def _review_item(review: dict) -> dict:
    return {
        "id": review.get("id"),
        "sku": _text(review.get("product_sku") or review.get("sku") or "未知 SKU"),
        "product_name": _text(review.get("product_name") or review.get("name")),
        "rating": review.get("rating"),
        "sentiment": _text(review.get("sentiment")),
        "issue": _label_display(review),
        "original": _truncate(review.get("body_cn") or review.get("body") or review.get("headline")),
        "analysis": _truncate(review.get("analysis_insight_cn") or review.get("analysis_insight_en") or _label_display(review), 160),
    }
```

- [ ] **Step 5: 实现 TOP 排序**

```python
def _rating_value(review: dict, default=0) -> float:
    try:
        return float(review.get("rating"))
    except (TypeError, ValueError):
        return default


def _own_rank(review: dict):
    rating = _rating_value(review, 5)
    negative = rating <= config.NEGATIVE_THRESHOLD
    has_analysis = bool(_text(review.get("analysis_insight_cn")))
    return (0 if negative else 1, rating, 0 if has_analysis else 1, _text(review.get("scraped_at")))


def _competitor_rank(review: dict):
    rating = _rating_value(review, 0)
    positive = rating >= 5 or _text(review.get("sentiment")).lower() == "positive"
    has_analysis = bool(_text(review.get("analysis_insight_cn")))
    return (0 if positive else 1, -rating, 0 if has_analysis else 1, _text(review.get("scraped_at")))
```

- [ ] **Step 6: 实现 Markdown 渲染**

模板必须固定、短、事实来源清晰：

```python
def _render_markdown(payload: dict) -> str:
    if payload["new_review_count"] == 0:
        return (
            f"## QBU 今日评论监控 · {payload['logical_date']}\n\n"
            "今日无新增评论。\n\n"
            f"当前累计样本：自有 {payload['cumulative_own_count']} 条 / "
            f"竞品 {payload['cumulative_competitor_count']} 条。\n\n"
            f"分析：{payload['analysis']}"
        )
    lines = [
        f"## QBU 今日评论监控 · {payload['logical_date']}",
        "",
        f"今日新增评论 `{payload['new_review_count']}` 条",
        f"自有新增 {payload['own_new_count']} 条，竞品新增 {payload['competitor_new_count']} 条",
        "",
        "### 自有 TOP3",
    ]
    lines.extend(_render_items(payload["own_top"], empty="暂无自有差评或重点评论"))
    lines.extend(["", "### 竞品 TOP3"])
    lines.extend(_render_items(payload["competitor_top"], empty="暂无竞品好评或重点评论"))
    lines.extend(["", f"分析：{payload['analysis']}"])
    return "\n".join(lines)
```

同时实现 `_render_items()`，每条格式为：

```md
- SKU:xxx，差评，评分 2 分，问题 售后履约
  原文：...
```

- [ ] **Step 7: 实现 `build_daily_digest()`**

```python
def build_daily_digest(snapshot: dict) -> dict:
    reviews = list(snapshot.get("reviews") or [])
    own_reviews = [r for r in reviews if r.get("ownership") == "own"]
    competitor_reviews = [r for r in reviews if r.get("ownership") == "competitor"]
    cumulative_reviews = list((snapshot.get("cumulative") or {}).get("reviews") or [])
    own_top = [_review_item(r) for r in sorted(own_reviews, key=_own_rank)[:3]]
    competitor_top = [_review_item(r) for r in sorted(competitor_reviews, key=_competitor_rank)[:3]]
    payload = {
        "run_id": snapshot.get("run_id"),
        "logical_date": snapshot.get("logical_date", ""),
        "new_review_count": int(snapshot.get("reviews_count") or len(reviews)),
        "own_new_count": len(own_reviews),
        "competitor_new_count": len(competitor_reviews),
        "own_negative_count": sum(1 for r in own_reviews if _rating_value(r, 5) <= config.NEGATIVE_THRESHOLD),
        "competitor_positive_count": sum(1 for r in competitor_reviews if _rating_value(r, 0) >= 5),
        "cumulative_own_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "own"),
        "cumulative_competitor_count": sum(1 for r in cumulative_reviews if r.get("ownership") == "competitor"),
        "own_top": own_top,
        "competitor_top": competitor_top,
        "message_title": "今日无新增评论" if not reviews else "今日新增评论",
    }
    payload["analysis"] = _build_analysis(payload)
    payload["markdown"] = _render_markdown(payload)
    return payload
```

- [ ] **Step 8: 运行摘要测试**

Run:

`uv run pytest tests/server/test_daily_dingtalk_digest.py -v`

Expected:

- PASS。

### Task 7: 接入 notification outbox 和 bridge 模板

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `qbu_crawler/server/notifier.py`
- Modify: `qbu_crawler/server/openclaw/bridge/app.py`
- Test: `tests/server/test_daily_dingtalk_digest.py`
- Test: `tests/server/test_workflow_ops_alert_wiring.py`

- [ ] **Step 1: 在 workflow snapshot 冻结后入队每日摘要**

在 `workflows.py` 中 `freeze_report_snapshot()` 之后、质量告警之前或 report_phase 路由之前加入：

```python
from qbu_crawler.server.daily_digest import build_daily_digest

snapshot = load_report_snapshot(run["snapshot_path"])
digest = build_daily_digest(snapshot)
_enqueue_workflow_notification(
    kind="workflow_daily_digest",
    target=config.WORKFLOW_NOTIFICATION_TARGET,
    payload=digest,
    dedupe_key=f"workflow:{run_id}:daily-digest",
)
```

注意：

- 必须使用 dedupe key，避免 worker 重试重复发。
- 不要把运维质量告警混入 digest。
- 该通知每日都发，包括 `reviews_count == 0`。

- [ ] **Step 2: 避免重复入队**

如果 `_advance_run()` 每次重进都会经过该段，使用 `notification_outbox` 的 dedupe 约束即可；若现有 `models.enqueue_notification()` 对重复 key 抛错，则包一层安全调用或在 models 内已有忽略逻辑基础上复用，不新增表结构。

- [ ] **Step 3: 在 `notifier.py` 透传 daily digest vars**

在 `_template_vars_for()` 中加入：

```python
if kind == "workflow_daily_digest":
    return {
        "logical_date": payload.get("logical_date", ""),
        "run_id": payload.get("run_id", ""),
        "new_review_count": payload.get("new_review_count", 0),
        "own_new_count": payload.get("own_new_count", 0),
        "competitor_new_count": payload.get("competitor_new_count", 0),
        "markdown": payload.get("markdown", ""),
    }
```

- [ ] **Step 4: 在 bridge 模板中新增 `workflow_daily_digest`**

在 `DEFAULT_TEMPLATES` 中加入：

```python
"workflow_daily_digest": "{markdown}",
```

- [ ] **Step 5: 排除 daily digest 对完整报告状态的污染**

修改 `notifier._sync_workflow_notification_status()` 或其调用条件：

```python
if notification.get("kind") == "workflow_daily_digest":
    return
```

并补充测试：`workflow_daily_digest` deadletter 不会触发 `downgrade_report_phase_on_deadletter()`，也不改变 `workflow_runs.report_phase`。

- [ ] **Step 6: 调整 full report 通知模板措辞**

把 `workflow_full_report` 标题从“每日完整报告已生成”改为“报告产物已生成”，正文保留：

```md
- **业务邮件**：{email_status}
```

这样非周报日显示 `已跳过（周报频率）` 时不会误导。

- [ ] **Step 7: 增加 workflow 入队测试**

在 `tests/server/test_daily_dingtalk_digest.py` 或新建 workflow wiring 测试中 monkeypatch：

- `workflows.freeze_report_snapshot`
- `workflows.load_report_snapshot`
- `workflows.generate_report_from_snapshot`
- `workflows._enqueue_workflow_notification`

断言 `_advance_run()` 至少入队一次 kind=`workflow_daily_digest`，dedupe key 为 `workflow:{run_id}:daily-digest`。

- [ ] **Step 8: 运行相关测试**

Run:

`uv run pytest tests/server/test_daily_dingtalk_digest.py tests/server/test_workflow_ops_alert_wiring.py -v`

Expected:

- PASS。

- [ ] **Step 9: 提交每日钉钉摘要**

Run:

```bash
git add qbu_crawler/server/daily_digest.py qbu_crawler/server/workflows.py qbu_crawler/server/notifier.py qbu_crawler/server/openclaw/bridge/app.py tests/server/test_daily_dingtalk_digest.py
git commit -m "feat: 增加每日钉钉业务摘要"
```

---

## Chunk 4: 周报窗口与邮件发送接入

### Task 8: 实现 weekly snapshot 派生

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/server/test_weekly_report_window.py`

- [ ] **Step 1: 新增窗口日期计算**

在 `report_snapshot.py` 中新增：

```python
from datetime import timedelta


def _window_since(data_until: str, window_days: int):
    until_dt = datetime.fromisoformat(data_until)
    return until_dt - timedelta(days=window_days)
```

使用文件里已有 datetime import 风格，不重复引入冲突。

- [ ] **Step 2: 新增 `build_windowed_report_snapshot()`**

实现：

```python
def build_windowed_report_snapshot(base_snapshot: dict, *, window_type: str, window_days: int) -> dict:
    if window_type != "weekly":
        result = dict(base_snapshot)
        result.setdefault("report_window", {"type": "daily", "label": "今日", "days": 1})
        return result

    data_until = base_snapshot["data_until"]
    data_since = _window_since(data_until, window_days)
    products, reviews = report.query_report_data(data_since, until=data_until)
    products = _merge_products_for_window_reviews(products, reviews, base_snapshot)
    _attach_ingested_counts(products, reviews)
    for item in reviews:
        item.setdefault("headline_cn", "")
        item.setdefault("body_cn", "")
    cumulative = base_snapshot.get("cumulative")
    if not cumulative and config.REPORT_PERSPECTIVE == "dual":
        cum_products, cum_reviews = report.query_cumulative_data()
        cumulative = {
            "products": cum_products,
            "reviews": cum_reviews,
            "products_count": len(cum_products),
            "reviews_count": len(cum_reviews),
            "translated_count": sum(1 for r in cum_reviews if r.get("translate_status") == "done"),
            "untranslated_count": sum(1 for r in cum_reviews if r.get("translate_status") != "done"),
        }
    result = dict(base_snapshot)
    result.update({
        "data_since": data_since.isoformat(),
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": sum(1 for r in reviews if r.get("translate_status") == "done"),
        "untranslated_count": sum(1 for r in reviews if r.get("translate_status") != "done"),
        "report_window": {"type": "weekly", "label": "本周", "days": window_days},
    })
    if cumulative:
        result["cumulative"] = cumulative
    return result
```

注意：

- 不要覆盖原 daily snapshot 文件；weekly snapshot 是发送时派生对象。
- `_merge_products_for_window_reviews()` 必须按窗口内 review 的 `product_url` 或 `product_sku + site` 从累计产品 / DB 查询补齐产品，避免“有新评论但产品未在窗口内刷新”时漏产品。
- 如果后续需要审计 weekly artifact，可在 full_report result 中记录 `report_window`，第一版不新增单独 snapshot 文件。

- [ ] **Step 3: 运行 weekly window 测试**

Run:

`uv run pytest tests/server/test_weekly_report_window.py::test_build_weekly_snapshot_uses_7_day_window -v`

Expected:

- PASS。

### Task 9: 在 workflow 中应用 cadence 与 weekly snapshot

**Files:**
- Modify: `qbu_crawler/server/workflows.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/server/test_weekly_email_cadence.py`
- Test: `tests/server/test_weekly_report_window.py`

- [ ] **Step 1: 导入新策略**

在 `workflows.py` 顶部导入：

```python
from qbu_crawler.server.report_cadence import decide_business_email
```

如果导入导致循环依赖，则改为在 `full_pending` 块内局部导入。

- [ ] **Step 2: 替换 `_should_send_workflow_email()` 调用**

在 `full_pending` 块中：

```python
snapshot = load_report_snapshot(run["snapshot_path"])
prev_analytics, prev_snapshot = load_previous_report_context(run_id)
snapshot_for_decision = dict(snapshot)
snapshot_for_decision["is_bootstrap"] = prev_snapshot is None
decision = decide_business_email(
    run=run,
    snapshot=snapshot_for_decision,
    mode=run.get("report_mode") or "",
)
report_snapshot_for_delivery = snapshot
if decision.report_window_type == "bootstrap":
    report_snapshot_for_delivery = dict(snapshot)
    report_snapshot_for_delivery["report_window"] = {"type": "bootstrap", "label": "监控起点", "days": 0}
elif decision.report_window_type == "weekly":
    report_snapshot_for_delivery = build_windowed_report_snapshot(
        snapshot,
        window_type="weekly",
        window_days=decision.window_days,
    )
else:
    report_snapshot_for_delivery = dict(snapshot)
    report_snapshot_for_delivery.setdefault("report_window", {"type": "daily", "label": "今日", "days": 1})
full_report = generate_report_from_snapshot(
    report_snapshot_for_delivery,
    send_email=decision.send_email,
)
```

保留 `_should_send_workflow_email()` 可作为兼容 wrapper，但不再由它决定所有邮件都发。

- [ ] **Step 3: 修改邮件状态文案**

新增 helper：

```python
def _workflow_email_status_from_decision(decision, email_success, untranslated_count):
    if not decision.send_email:
        if decision.reason == "weekly_cadence_skip":
            return "已跳过（周报频率）"
        return f"已跳过（{decision.reason}）"
    return _workflow_email_status(email_success, untranslated_count)
```

在 `workflow_full_report` payload 中使用新 helper。

- [ ] **Step 4: 修改 DB 状态**

现有逻辑：

```python
email_delivery_status = "skipped"
if should_send_email:
    email_delivery_status = "sent" if email_ok else "failed"
```

改为：

```python
email_delivery_status = "skipped"
delivery_last_error = None
if decision.send_email:
    email_delivery_status = "sent" if email_ok else "failed"
    delivery_last_error = (email or {}).get("error")
else:
    delivery_last_error = decision.reason
```

再传给 `models.update_workflow_report_status()`。

- [ ] **Step 5: 确保生成本地产物不被跳过**

`generate_report_from_snapshot(..., send_email=False)` 必须仍生成 analytics / HTML / Excel。若 quiet 模式旧逻辑在 send_email=False 时跳过 Excel，是现有行为可接受；full 模式必须保留本地产物。

- [ ] **Step 6: 增加 workflow cadence 接入测试**

在 `tests/server/test_weekly_email_cadence.py` 中加入：

- 非周报日 `_advance_run()` 调用 `generate_report_from_snapshot(..., send_email=False)`。
- 周报日 `_advance_run()` 调用 `build_windowed_report_snapshot(..., window_type="weekly")` 且 `send_email=True`。
- bootstrap run 不调用 `build_windowed_report_snapshot()`，且 `report_window.type == "bootstrap"`。

用 monkeypatch 捕获参数，不依赖真实邮件。

- [ ] **Step 7: 运行 cadence 和 weekly 测试**

Run:

`uv run pytest tests/server/test_weekly_email_cadence.py tests/server/test_weekly_report_window.py -v`

Expected:

- PASS。

### Task 10: 调整 full/change/quiet 与 bootstrap 语义边界

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/server/test_weekly_email_cadence.py`

- [ ] **Step 1: 确认 bootstrap 判断来源**

运行：

`rg -n "report_semantics|is_bootstrap|determine_report_mode" qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py`

Expected:

- 找到现有 bootstrap 语义产出点。

- [ ] **Step 2: 如 snapshot 阶段没有 bootstrap 字段，补最小判断**

不要新增 DB 字段。必须在 workflow 调用前先通过 `load_previous_report_context(run_id)` 或同等历史报告上下文判断 previous snapshot 是否存在，再显式传入 `snapshot_for_decision["is_bootstrap"]`。

建议优先：

```python
is_first_report = not report_snapshot.load_previous_report_context(run_id)[1]
snapshot_for_decision = dict(snapshot)
snapshot_for_decision["is_bootstrap"] = is_first_report
decision = decide_business_email(run=run, snapshot=snapshot_for_decision, mode=...)
```

- [ ] **Step 3: 确保首次运行发全量而非 weekly window**

首次 baseline 的 `report_window` 应为：

```python
{"type": "bootstrap", "label": "监控起点", "days": 0}
```

并且使用原始 snapshot 的 full/cumulative 数据，不调用 weekly 派生。

- [ ] **Step 4: 确保 weekly cadence 绕过 quiet 旧节流**

周报日如果 `determine_report_mode()` 返回 quiet，仍必须发送邮件。实现方式二选一：

- 在 `generate_report_from_snapshot()` 增加 delivery context，让 `_generate_quiet_report()` 在 weekly cadence 下跳过 `should_send_quiet_email()`。
- 或在 `snapshot["report_window"].type == "weekly"` 时，`_generate_quiet_report()` 将 `should_send=True` 固定为 True。

新增测试：周报日 `reviews_count == 0` 且无变化时，`generate_report_from_snapshot(..., send_email=True)` 最终会调用邮件发送，不被 `should_send_quiet_email()` 拦截。

- [ ] **Step 5: 跑 bootstrap cadence 测试**

Run:

`uv run pytest tests/server/test_weekly_email_cadence.py::test_bootstrap_run_sends_email_when_enabled -v`

Expected:

- PASS。

- [ ] **Step 6: 提交周报窗口接入**

Run:

```bash
git add qbu_crawler/server/workflows.py qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_cadence.py tests/server/test_weekly_email_cadence.py tests/server/test_weekly_report_window.py
git commit -m "feat: 接入首次基线和每周邮件窗口"
```

---

## Chunk 5: 报告模板与邮件正文

### Task 11: HTML “今日变化 / 本周变化”窗口化

**Files:**
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/server/test_weekly_report_window.py`
- Test: `tests/server/test_historical_trend_template.py`

- [ ] **Step 1: 在渲染入口提供默认 `report_window`**

在 `report_html.py` 的 HTML 渲染前：

```python
snapshot = dict(snapshot or {})
snapshot.setdefault("report_window", {"type": "daily", "label": "今日", "days": 1})
```

- [ ] **Step 2: 在模板顶部设置标题变量**

在 `daily_report_v3.html.j2` 顶部变量区加入：

```jinja2
{% set report_window = snapshot.report_window or {"type": "daily", "label": "今日"} %}
{% if analytics.report_semantics == "bootstrap" or report_window.type == "bootstrap" %}
  {% set change_title = "监控起点" %}
{% elif report_window.type == "weekly" %}
  {% set change_title = "本周变化" %}
{% else %}
  {% set change_title = "今日变化" %}
{% endif %}
```

- [ ] **Step 3: 替换固定文案**

将模板中固定的：

- `今日变化` tab
- `<h2 class="section-title">今日变化</h2>`

改为：

```jinja2
{{ change_title }}
```

- [ ] **Step 4: 运行 HTML 测试**

Run:

`uv run pytest tests/server/test_weekly_report_window.py::test_html_uses_weekly_change_title tests/server/test_historical_trend_template.py -v`

Expected:

- PASS，且趋势页现有测试不回归。

### Task 12: 邮件正文和 subject 窗口化

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`
- Test: `tests/server/test_weekly_report_window.py`
- Test: `tests/server/test_email_full_template.py`

- [ ] **Step 1: 修改 `_build_email_subject()`**

当前 `_build_email_subject(normalized, logical_date)` 只按日期生成动态标题。扩展为接受 snapshot 或 report_window：

```python
def _build_email_subject(normalized, logical_date, snapshot=None):
    window = (snapshot or {}).get("report_window") or {}
    if window.get("type") == "bootstrap":
        return f"QBU 评论分析基线 · {logical_date}"
    if window.get("type") == "weekly":
        since = str((snapshot or {}).get("data_since", ""))[:10]
        until = str((snapshot or {}).get("data_until", ""))[:10]
        return f"QBU 网评周报 · {since} 至 {until}"
    ...
```

保留现有告警前缀逻辑时，把前缀加在返回 subject 前，不删除现有风险等级表达。

- [ ] **Step 2: 修改调用点**

在 `build_full_report_email()` 或对应调用处，把 snapshot 传给 `_build_email_subject()`。

- [ ] **Step 3: 修改 `email_full.html.j2` 顶部标题**

先修改 `report.render_email_full()`，确保模板收到真实 snapshot：

```python
return tpl.render(
    snapshot=snapshot or {},
    logical_date=snapshot.get("logical_date", "") if snapshot else "",
    analytics=email_analytics,
)
```

这是必改项；当前 `render_email_full()` 没有把 `snapshot` 传入模板，模板直接读取 `snapshot.report_window` 会失败或为空。

然后在 `email_full.html.j2` 增加：

```jinja2
{% set report_window = snapshot.report_window or {"type": "daily", "label": "今日"} %}
{% set window_label = "本周" if report_window.type == "weekly" else ("监控起点" if report_window.type == "bootstrap" else "今日") %}
```

把正文里的“本次 / 今日新增”类文案改成 `{{ window_label }}` 驱动。

- [ ] **Step 4: 周报正文结构**

邮件正文推荐顺序：

1. `{{ window_label }}概览`
2. 关键判断
3. TOP 3 行动建议
4. 累计健康快照
5. 附件说明

只替换文案和取值入口，不重做邮件视觉系统。

- [ ] **Step 5: 运行邮件模板测试**

Run:

`uv run pytest tests/server/test_weekly_report_window.py::test_email_full_uses_weekly_language tests/server/test_email_full_template.py -v`

Expected:

- PASS。

- [ ] **Step 6: 提交模板调整**

Run:

```bash
git add qbu_crawler/server/report.py qbu_crawler/server/report_html.py qbu_crawler/server/report_templates/daily_report_v3.html.j2 qbu_crawler/server/report_templates/email_full.html.j2 tests/server/test_weekly_report_window.py
git commit -m "feat: 调整周报邮件和报告窗口文案"
```

---

## Chunk 6: 集成验证、模拟和文档

### Task 13: 集成测试全量相关集合

**Files:**
- Test only

- [ ] **Step 1: 运行新增测试**

Run:

`uv run pytest tests/server/test_weekly_email_cadence.py tests/server/test_daily_dingtalk_digest.py tests/server/test_weekly_report_window.py -v`

Expected:

- PASS。

- [ ] **Step 2: 运行报告与通知相关回归**

Run:

`uv run pytest tests/server/test_email_full_template.py tests/server/test_report_contract_renderers.py tests/server/test_historical_report_paths.py tests/server/test_historical_trend_template.py tests/server/test_workflow_ops_alert_wiring.py -v`

Expected:

- PASS。

- [ ] **Step 3: 运行测试14回归**

Run:

`uv run pytest tests/server/test_test14_report_regressions.py tests/server/test_simulate_daily_report_script.py -v`

Expected:

- PASS，确认累计全景修复没有被 weekly window 破坏。

### Task 14: 30 天模拟验证

**Files:**
- Existing: `scripts/simulate_daily_report.py`
- Output: `data/simulations/...`

- [ ] **Step 1: 运行隔离模拟**

Run:

`uv run python scripts/simulate_daily_report.py 30 --output-dir data/simulations/weekly-email-dingtalk-30days`

Expected:

- 生成 `data/simulations/weekly-email-dingtalk-30days` 目录。
- 模拟过程不发送真实邮件、不调用真实外部钉钉。

- [ ] **Step 2: 检查第 1 天报告**

Expected:

- 首次报告语义为 baseline/bootstrap。
- 邮件决策为发送。
- 全景数据为累计基线。

- [ ] **Step 3: 检查非周报日**

Expected:

- 每天有 `workflow_daily_digest` 或对应模拟 outbox 记录。
- `email_delivery_status=skipped`。
- `delivery_last_error=weekly_cadence_skip`。
- 本地产物仍生成。

- [ ] **Step 4: 检查周报日**

Expected:

- 邮件决策为发送。
- HTML 中出现“本周变化”。
- 周报窗口新增评论数等于近 7 天入库评论数。
- 全景累计评论数等于截至该日的累计评论数，不回退成当天数据。

### Task 15: 文档同步

**Files:**
- Modify: `AGENTS.md`
- Modify: `.env.example`
- Create: `docs/devlogs/D030-weekly-email-daily-dingtalk.md`

- [ ] **Step 1: 更新 `AGENTS.md` 配置表**

在报告配置中加入：

- `REPORT_EMAIL_CADENCE`
- `REPORT_WEEKLY_EMAIL_WEEKDAY`
- `REPORT_WEEKLY_WINDOW_DAYS`
- `REPORT_EMAIL_SEND_BOOTSTRAP`

- [ ] **Step 2: 更新 OpenClaw 定时工作流说明**

写清：

- DailySchedulerWorker 每天仍运行。
- 每日钉钉摘要由 `workflow_daily_digest` 发出。
- 业务邮件默认首次基线 + 每周一次。
- 非周报日 `email_delivery_status=skipped` 是预期状态，不是失败。

- [ ] **Step 3: 更新报表语义治理**

补充：

- `report_window.type=daily|weekly|bootstrap` 驱动用户可见窗口文案。
- 周报“本周变化”消费 7 天窗口。
- “全景数据”继续消费 `snapshot.cumulative`。

- [ ] **Step 4: 新增 devlog**

`docs/devlogs/D030-weekly-email-daily-dingtalk.md` 内容包含：

- 背景
- 方案摘要
- 修改文件
- 测试命令与结果
- 30 天模拟结果
- 生产配置建议

- [ ] **Step 5: 提交文档**

Run:

```bash
git add AGENTS.md .env.example docs/devlogs/D030-weekly-email-daily-dingtalk.md
git commit -m "docs: 记录周报邮件和每日钉钉摘要方案"
```

### Task 16: 最终验收清单

**Files:**
- All touched files

- [ ] **Step 1: 搜索禁词和旧文案**

Run:

`rg -n "每日完整报告已生成|今日变化|今日新增" qbu_crawler/server/report_templates qbu_crawler/server/openclaw/bridge/app.py qbu_crawler/server/report.py`

Expected:

- `今日变化` 只在 daily fallback 或测试 fixture 中出现。
- weekly 模式不出现“今日变化”。
- bridge full report 不再叫“每日完整报告已生成”。

- [ ] **Step 2: 检查新增配置导入**

Run:

`uv run python -c "from qbu_crawler import config; print('ok')"`

Expected:

- 输出 `ok`。

- [ ] **Step 3: 运行最终测试集合**

Run:

`uv run pytest tests/server/test_weekly_email_cadence.py tests/server/test_daily_dingtalk_digest.py tests/server/test_weekly_report_window.py tests/server/test_test14_report_regressions.py -v`

Expected:

- PASS。

- [ ] **Step 4: 检查工作区改动**

Run:

`git status --short`

Expected:

- 只包含本需求相关改动和用户/既有未提交改动。
- 不回滚任何非本任务文件。

- [ ] **Step 5: 形成交付说明**

最终说明必须包含：

- 每日采集仍执行。
- 每日钉钉摘要新增/无新增都会发。
- 邮件默认首次基线 + 每周一次。
- 周报“本周变化”基于 7 天窗口。
- 全景数据仍为累计，不再退化为当天数据。
- 已运行的测试和模拟结果。

---

## Execution Notes

- 实施前使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`。
- 遇到现有未提交改动时，只读并兼容，不要回滚。
- 所有新增业务分析文案必须来自 snapshot / DB 已有字段，不调用 LLM 编造额外 SKU、评论或数字。
- 第一版不新增数据库迁移；若后续要审计“某自然周是否已发送”，再单独设计字段或 outbox kind。
- 如果生产希望周五发周报，把 `REPORT_WEEKLY_EMAIL_WEEKDAY=5`，不要改代码。
