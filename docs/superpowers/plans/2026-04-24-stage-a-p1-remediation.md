# Stage A · Phase 1 P1 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Phase 1 遗留的 5 条 P1（1 条 P1-C 已在 T0 合入）全部修掉，让"健康指数单一口径 / 趋势 mixed-state 渲染 / LLM incremental prompt 不再写'今日新增' / bootstrap 违禁词与 fallback 全覆盖"在 bootstrap + incremental 两种模式下均可验证。

**Architecture:**
- **不引入新字段**：Stage A 只做口径统一、清理、扩面，严格不改 `change_digest / trend_digest / kpis` 顶层键名。
- **趋势桶位健康指数复用 `compute_health_index` 的核心算法**：抽出 `_bayesian_bucket_health(own_total, own_neg, own_pos)` pure helper，`_build_sentiment_trend` 循环调用。
- **Template 改为按组件 status 独立渲染**（`kpis.status / primary_chart.status / table.status` 三者分别判定），`_build_competition_trend` 后端同步改成组件级输出。
- **LLM prompt 收口到 `change_digest.summary`**：删除 L531-541 重复 "`--- 今日变化 ---`" 段；violation detector 覆盖 6 个文本字段 + 加 `新增\s*\d+\s*条\s*评论` 通配模式；`_fallback_executive_bullets` 与 `email_full.html.j2:221-223` 都感知 `report_semantics`。

**Tech Stack:** Python 3.10+, pytest, Jinja2

**Spec:** `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md`
**Source findings:** `docs/reviews/2026-04-24-report-upgrade-best-practice.md` §3 修 1-2、修 4-6（修 3 已在 `v0.3.17-t0-hotfix` 合入）
**Entry assumption:** `HEAD = dadaf81` (T0 hotfix) · 30 个已有 test_report_llm.py 用例全绿

---

## File Map

| File | Responsibility | Tasks |
|------|----------------|-------|
| `qbu_crawler/server/report_common.py` | 抽出 `_bayesian_bucket_health()`；改 `METRIC_TOOLTIPS["健康指数"]` 文案；让 `_fallback_executive_bullets` / `_fallback_hero_headline` 感知 `report_semantics` | T1, T5 |
| `qbu_crawler/server/report_analytics.py` | `_build_sentiment_trend` 趋势桶位复用贝叶斯健康；`_build_competition_trend` 改为组件级 status | T1, T2 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | `<section id="tab-trends">` 里按 `kpis/primary_chart/table` 独立 if；year 视图暂不处理（留给 Stage B） | T2 |
| `qbu_crawler/server/report_llm.py` | 删 L531-541 重复段；`_build_insights_prompt` incremental 分支只从 `change_digest.summary` 取；`_has_bootstrap_language_violation` 字段面扩到 6 类、模式加 `新增\s*\d+\s*条\s*评论` | T3, T4 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | `_bullets` 空时的 fallback 文案感知 `_semantics`；bootstrap 改成"建立监控基线"、incremental 改成"近30天业务新增 X / 历史补采 Y" | T5 |
| `tests/test_report_common.py` | 新增 `_bayesian_bucket_health` 单测；tooltip 文案断言；fallback bullets 语义回归 | T1, T5 |
| `tests/test_report_analytics.py` | 新增 `_build_competition_trend` 组件级 status 断言；sentiment 趋势桶位健康值回归 | T1, T2 |
| `tests/test_v3_html.py` | 新增 "accumulating 维度的 ready KPI/table 仍渲染" 回归；邮件 fallback 文案回归 | T2, T5 |
| `tests/test_report_llm.py` | 删 incremental prompt 重复段回归；违禁词扩面回归 | T3, T4 |
| `tests/test_report_integration.py` | Stage A 最终联测：grep 门禁 + KPI 三处同口径 + 无"今日新增"/"新增评论" | T6 |
| `pyproject.toml` / `qbu_crawler/__init__.py` / `uv.lock` | 版本号 bump 0.3.17 → 0.3.18 | T6 |

---

## Task 1: 统一健康指数口径 — 抽出贝叶斯 bucket helper，趋势复用

**Files:**
- Modify: `qbu_crawler/server/report_common.py:50-60`（tooltip）
- Modify: `qbu_crawler/server/report_common.py`（append `_bayesian_bucket_health` after `compute_health_index` at line ~533）
- Modify: `qbu_crawler/server/report_analytics.py:1434-1458`（`_build_sentiment_trend` 追加 `own_positive_by_bucket` 统计 + `health_scores` 改调 helper）
- Test: `tests/test_report_common.py`
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1.1: 写失败测试 — `_bayesian_bucket_health` 核心行为**

加到 `tests/test_report_common.py` 末尾：

```python
def test_bayesian_bucket_health_empty_returns_none():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    assert _bayesian_bucket_health(own_total=0, own_neg=0, own_pos=0) is None


def test_bayesian_bucket_health_large_sample_is_raw_nps():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    # 100 reviews, 90 promoters, 5 detractors → NPS = (90-5)/100*100 = 85
    # raw_health = (85+100)/2 = 92.5, sample >= 30 so no shrinkage
    assert _bayesian_bucket_health(own_total=100, own_neg=5, own_pos=90) == 92.5


def test_bayesian_bucket_health_small_sample_shrinks_toward_prior():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    # 10 reviews, 10 detractors, 0 promoters → NPS = -100, raw = 0
    # weight = 10/30, shrunk = 10/30*0 + 20/30*50 = 33.33
    result = _bayesian_bucket_health(own_total=10, own_neg=10, own_pos=0)
    assert 33.0 <= result <= 34.0


def test_bayesian_bucket_health_single_positive_review_not_perfect():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    # Should not be 100 — shrinkage must pull toward 50
    result = _bayesian_bucket_health(own_total=1, own_neg=0, own_pos=1)
    assert result is not None
    assert result < 70, f"1 promoter should not yield health > 70, got {result}"
```

- [ ] **Step 1.2: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py -v -k "_bayesian_bucket_health"`
Expected: 4 个 FAIL · `ImportError: cannot import name '_bayesian_bucket_health'`

- [ ] **Step 1.3: 实现 `_bayesian_bucket_health`**

加到 `qbu_crawler/server/report_common.py` 紧跟在 `compute_health_index` 函数之后（line 534 处）：

```python
def _bayesian_bucket_health(own_total: int, own_neg: int, own_pos: int) -> float | None:
    """Bayesian-shrunk health score for a single trend bucket.

    Mirrors compute_health_index() but operates on bucket-local counts rather
    than top-level analytics. Returns None for empty buckets so the chart can
    render a break point (null) instead of a misleading 0 or 50.
    """
    if own_total <= 0:
        return None
    nps = ((own_pos - own_neg) / own_total) * 100
    raw_health = (nps + 100) / 2
    MIN_RELIABLE = 30
    PRIOR = 50.0
    if own_total < MIN_RELIABLE:
        weight = own_total / MIN_RELIABLE
        health = weight * raw_health + (1 - weight) * PRIOR
    else:
        health = raw_health
    return round(max(0.0, min(100.0, health)), 1)
```

- [ ] **Step 1.4: 跑 Step 1.1 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py -v -k "_bayesian_bucket_health"`
Expected: 4 PASS

- [ ] **Step 1.5: 写失败测试 — tooltip 文案**

加到 `tests/test_report_common.py`：

```python
def test_health_index_tooltip_reflects_bayesian_formula():
    from qbu_crawler.server.report_common import METRIC_TOOLTIPS
    tooltip = METRIC_TOOLTIPS["健康指数"]
    # Old weighted formula must be gone
    assert "20%站点评分" not in tooltip
    assert "25%样本评分" not in tooltip
    # New Bayesian-NPS description must be present
    assert "NPS" in tooltip or "贝叶斯" in tooltip
    assert "50" in tooltip  # prior mentioned
    assert "30" in tooltip  # min-reliable sample mentioned
```

- [ ] **Step 1.6: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py -v -k "test_health_index_tooltip_reflects_bayesian_formula"`
Expected: FAIL · 旧 tooltip 仍含 "20%站点评分"

- [ ] **Step 1.7: 更新 tooltip 文案**

Edit `qbu_crawler/server/report_common.py:54`，把

```python
"健康指数": "综合评分 = 20%站点评分 + 25%样本评分 + 35%(1−差评率) + 20%(1−高风险占比)，满分100",
```

替换为

```python
"健康指数": "贝叶斯 NPS 代理：(promoters − detractors) / own_reviews × 100 线性映射到 0-100；自有评论 < 30 时按样本量向先验 50 收缩，避免小样本极端值",
```

- [ ] **Step 1.8: 跑 tooltip 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py -v -k "test_health_index_tooltip_reflects_bayesian_formula"`
Expected: PASS

- [ ] **Step 1.9: 写失败测试 — 趋势桶位用贝叶斯**

加到 `tests/test_report_analytics.py`：

```python
def test_sentiment_trend_bucket_health_is_bayesian_shrunk():
    """趋势 health_scores 必须用 _bayesian_bucket_health，
    不能再是 100 - own_negative_rate 的简化公式。

    场景：某 bucket 只有 1 条 5 星评论 → 旧公式给 100，新公式必须 < 70。
    """
    from qbu_crawler.server.report_analytics import _build_sentiment_trend
    from datetime import date

    logical_day = date(2026, 4, 24)
    labeled_reviews = [
        # 只在 '2026-04' bucket 有 1 条 5 星自有评论，其它 bucket 空
        {
            "review": {
                "ownership": "own",
                "rating": 5,
                "date_published_parsed": "2026-04-10",
            },
            "published": date(2026, 4, 10),
        },
    ]
    result = _build_sentiment_trend("month", logical_day, labeled_reviews)
    # 找到 primary_chart 里名为 '健康分' 的 series
    series = next(
        s for s in result["primary_chart"]["series"]
        if "健康" in s["name"]
    )
    # 非空 bucket 的值必须 < 70（贝叶斯收缩后）；空 bucket 必须 None
    non_null = [v for v in series["data"] if v is not None]
    assert non_null, "expected at least one non-null bucket"
    assert all(v < 70 for v in non_null), \
        f"small-sample bucket should shrink toward 50, got {non_null}"
    # 空 bucket 应该是 None 而不是 0
    assert series["data"].count(None) >= 1
```

- [ ] **Step 1.10: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py -v -k "test_sentiment_trend_bucket_health_is_bayesian_shrunk"`
Expected: FAIL · 1 条 5 星 bucket 返回 100

- [ ] **Step 1.11: 改 `_build_sentiment_trend` 追加 positive 统计 + 调 helper**

在 `qbu_crawler/server/report_analytics.py` 的 `_build_sentiment_trend` 里：

- 在 `own_negative_by_bucket` 初始化后（line 1436 附近）加一行：
  ```python
  own_positive_by_bucket = {label: 0 for label in labels}
  ```
- 在统计循环里（line 1445-1448）把
  ```python
  own_total_by_bucket[bucket] += 1
  if float(review.get("rating") or 0) <= config.NEGATIVE_THRESHOLD:
      own_negative_by_bucket[bucket] += 1
  ```
  改为
  ```python
  own_total_by_bucket[bucket] += 1
  rating = float(review.get("rating") or 0)
  if rating <= config.NEGATIVE_THRESHOLD:
      own_negative_by_bucket[bucket] += 1
  elif rating >= 4:
      own_positive_by_bucket[bucket] += 1
  ```
- 把 line 1458 的
  ```python
  health_scores = [round(100 - rate, 1) if own_total_by_bucket[label] else 0 for label, rate in zip(labels, own_negative_rates)]
  ```
  改为
  ```python
  from qbu_crawler.server.report_common import _bayesian_bucket_health
  health_scores = [
      _bayesian_bucket_health(
          own_total=own_total_by_bucket[label],
          own_neg=own_negative_by_bucket[label],
          own_pos=own_positive_by_bucket[label],
      )
      for label in labels
  ]
  ```

注意：`_bayesian_bucket_health` 对空 bucket 返回 `None`，`own_negative_rates` 下游消费是否也对齐？检查并把 `own_negative_rates` 空桶从 `0` 改成 `None`：

```python
own_negative_rates = [
    round((own_negative_by_bucket[label] / own_total_by_bucket[label]) * 100, 1)
    if own_total_by_bucket[label]
    else None   # 原来是 0
    for label in labels
]
```

- [ ] **Step 1.12: 跑 Step 1.9 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py -v -k "test_sentiment_trend_bucket_health_is_bayesian_shrunk"`
Expected: PASS

- [ ] **Step 1.13: 跑 Task 1 全部相关测试 + 现有回归**

Run:
```bash
uv run --extra dev python -m pytest tests/test_report_common.py tests/test_report_analytics.py tests/test_v3_html.py -v
```
Expected: 全部 PASS（特别是已有的 `test_report_analytics` 里关于 sentiment trend 的测试，若已写死旧 health 值 0 需同步修正 — 这时暴露就当场修改，然后再跑）

- [ ] **Step 1.14: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py tests/test_report_common.py tests/test_report_analytics.py
git commit -m "fix(report): 统一健康指数为贝叶斯 NPS（T-A-1 · Stage A 修 1）

- 抽出 _bayesian_bucket_health(own_total, own_neg, own_pos) pure helper，
  与 compute_health_index 同公式（NPS × 线性映射 + 样本<30 向先验 50 收缩）
- _build_sentiment_trend 趋势桶位改调 helper；空桶返回 None（Chart.js 断点）
- METRIC_TOOLTIPS[健康指数] 文案改为真实贝叶斯 NPS 说明

现象修复：测试2 月/2025-11 桶 health_index=0.0 是 100 − 100 差评率的简化
公式产物；新版对 1-2 条的小样本桶主动向 50 收缩，避免 0.0/100 极端值。"
```

---

## Task 2: 趋势 mixed-state — 模板组件级 if + competition 后端组件级

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1708-1742`（`_build_competition_trend` 移除整块 `_empty_trend_dimension`，改为组件级）
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:294-337`（trend panel 整块 if 拆成组件级 if）
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 2.1: 写失败测试 — competition 维度组件级 status**

加到 `tests/test_report_analytics.py`：

```python
def test_competition_trend_mixed_state_keeps_ready_table_when_chart_accumulating():
    """spec §8.5 要求：竞品趋势允许按子组件混合状态输出，
    不能整维度一刀切成同一状态。

    场景：自有有评论但竞品无评论 → primary_chart 无法 ready，
    但表格仍应列出自有侧数据（status=ready）。
    """
    from qbu_crawler.server.report_analytics import _build_competition_trend
    from datetime import date

    labeled_reviews = [
        {
            "review": {"ownership": "own", "rating": 5, "date_published_parsed": "2026-04-10"},
            "published": date(2026, 4, 10),
        },
        {
            "review": {"ownership": "own", "rating": 1, "date_published_parsed": "2026-03-15"},
            "published": date(2026, 3, 15),
        },
    ]
    result = _build_competition_trend("month", date(2026, 4, 24), labeled_reviews)
    # 顶层 status 允许是 accumulating
    assert result["status"] in {"accumulating", "ready"}
    # 但表格组件必须 ready（因为自有侧有数据）
    assert result["table"]["status"] == "ready"
    assert len(result["table"]["rows"]) >= 1
    # primary_chart 可以 accumulating（缺竞品不能对比）
    assert result["primary_chart"]["status"] in {"accumulating", "ready"}
```

- [ ] **Step 2.2: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py -v -k "test_competition_trend_mixed_state"`
Expected: FAIL · 当前 `_empty_trend_dimension("accumulating",...)` 让 table.rows = []

- [ ] **Step 2.3: `_build_competition_trend` 改为组件级**

编辑 `qbu_crawler/server/report_analytics.py:1734-1742`：

把

```python
shared_points = sum(1 for label in labels if own_total[label] > 0 and competitor_total[label] > 0)
ready = shared_points > 0 and (view != "year" or shared_points >= 2)
if not ready:
    return _empty_trend_dimension(
        "accumulating",
        "自有与竞品的可比样本仍在积累，当前不足以形成稳定趋势。",
        "竞品趋势",
        ["日期", "自有均分", "竞品均分", "自有差评率", "竞品好评率"],
    )
```

替换为

```python
shared_points = sum(1 for label in labels if own_total[label] > 0 and competitor_total[label] > 0)
chart_ready = shared_points > 0 and (view != "year" or shared_points >= 2)
own_points = sum(1 for label in labels if own_total[label] > 0)
competitor_points = sum(1 for label in labels if competitor_total[label] > 0)
any_side_has_data = own_points > 0 or competitor_points > 0

if not any_side_has_data:
    # Neither side has data → integral accumulating is correct.
    return _empty_trend_dimension(
        "accumulating",
        "自有与竞品的可比样本仍在积累，当前不足以形成稳定趋势。",
        "竞品趋势",
        ["日期", "自有均分", "竞品均分", "自有差评率", "竞品好评率"],
    )
```

然后继续往下走（不要 return），让现有 `own_avg_rating / competitor_avg_rating / own_negative_rate / competitor_positive_rate / rows` 计算继续运行。**最后** return 部分要改：

找到 function 末尾的 `_trend_dimension_payload(...)` 返回语句（约 line 1800 附近），把 `primary_chart.status` 改为 `"ready" if chart_ready else "accumulating"`，把 `table.status` 改为 `"ready" if any_side_has_data else "accumulating"`，kpis 按 shared_points 决定：

```python
kpis_ready = shared_points > 0
kpi_status = "ready" if kpis_ready else "accumulating"
# ... 构造 kpi items（例如 shared_points、own_avg、competitor_avg）...
return _trend_dimension_payload(
    status="ready" if chart_ready else "accumulating",
    message="" if chart_ready else "可比样本仍在积累，图表暂未稳定但已有数据点可查。",
    kpis={"status": kpi_status, "items": [...]},  # 已有逻辑保持
    primary_chart={
        "status": "ready" if chart_ready else "accumulating",
        "chart_type": "line",
        "title": "自有 vs 竞品评分趋势",
        "labels": labels if chart_ready else [],
        "series": [...] if chart_ready else [],
    },
    table={
        "status": "ready" if any_side_has_data else "accumulating",
        "columns": [...],
        "rows": rows,  # 已有 rows 计算保持
    },
)
```

> 注意：function 本来在 `_trend_dimension_payload(...)` 前已经算好了 `rows`；改动后 rows 可能只有自有侧数据 — 在 row 构造时对空竞品字段用 `None` 占位（既有 code 已如此）。

- [ ] **Step 2.4: 跑 Step 2.1 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py -v -k "test_competition_trend_mixed_state"`
Expected: PASS

- [ ] **Step 2.5: 写失败测试 — HTML 模板组件级 if**

加到 `tests/test_v3_html.py`：

```python
def test_trend_panel_renders_ready_components_when_block_accumulating():
    """spec §8.5 + Codex P1-B：趋势组件必须按 kpis.status / primary_chart.status /
    table.status 独立判断，不能被外层 block.status='accumulating' 一刀切。"""
    from qbu_crawler.server.report_html import render_report_html
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics_raw = {
        "report_semantics": "bootstrap",
        "kpis": {"product_count": 1, "own_review_rows": 5},
        "trend_digest": {
            "views": ["week", "month", "year"],
            "dimensions": ["sentiment", "issues", "products", "competition"],
            "default_view": "month",
            "default_dimension": "products",
            "data": {
                "month": {
                    "products": {
                        "status": "accumulating",
                        "status_message": "产品快照样本不足，连续状态趋势仍在积累。",
                        "kpis": {"status": "ready", "items": [
                            {"label": "跟踪 SKU", "value": 3},
                            {"label": "累计快照", "value": 12},
                        ]},
                        "primary_chart": {"status": "accumulating", "chart_type": "line",
                                          "title": "", "labels": [], "series": []},
                        "table": {"status": "ready", "columns": ["SKU"], "rows": [
                            {"SKU": "SKU-1"}, {"SKU": "SKU-2"}, {"SKU": "SKU-3"},
                        ]},
                    },
                    "sentiment": {"status": "ready", "kpis": {"status":"ready","items":[]},
                                  "primary_chart":{"status":"ready","labels":[],"series":[]},
                                  "table":{"status":"ready","columns":[],"rows":[]}},
                    "issues": {"status": "ready", "kpis": {"status":"ready","items":[]},
                               "primary_chart":{"status":"ready","labels":[],"series":[]},
                               "table":{"status":"ready","columns":[],"rows":[]}},
                    "competition": {"status": "ready", "kpis": {"status":"ready","items":[]},
                                    "primary_chart":{"status":"ready","labels":[],"series":[]},
                                    "table":{"status":"ready","columns":[],"rows":[]}},
                },
                "week": {d: {"status":"accumulating","kpis":{"status":"accumulating","items":[]},
                             "primary_chart":{"status":"accumulating","labels":[],"series":[]},
                             "table":{"status":"accumulating","columns":[],"rows":[]}}
                         for d in ["sentiment","issues","products","competition"]},
                "year": {d: {"status":"accumulating","kpis":{"status":"accumulating","items":[]},
                             "primary_chart":{"status":"accumulating","labels":[],"series":[]},
                             "table":{"status":"accumulating","columns":[],"rows":[]}}
                         for d in ["sentiment","issues","products","competition"]},
            },
        },
        "change_digest": {"enabled": True, "view_state": "bootstrap", "summary": {},
                          "warnings": {}, "empty_state": {"enabled": False}},
    }
    normalized = normalize_deep_report_analytics(analytics_raw)
    html = render_report_html(normalized, charts={}, logical_date="2026-04-24")

    # month/products 块必须渲染 KPI 与 table（status ready 的组件），而不是被整块吞掉
    assert "跟踪 SKU" in html
    assert "SKU-1" in html
    # status_message（主图未就绪的说明）也应该可见
    assert "产品快照样本不足" in html
```

- [ ] **Step 2.6: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_v3_html.py -v -k "test_trend_panel_renders_ready_components"`
Expected: FAIL · 整块 if 导致 KPI 卡和 table 都被吞掉，找不到 "跟踪 SKU" 和 "SKU-1"

- [ ] **Step 2.7: 改模板 `daily_report_v3.html.j2:294-337`**

把

```jinja2
{% if trend_block.status == "ready" %}
<div class="trend-kpi-grid">
  {% for item in (trend_kpis["items"] if "items" in trend_kpis else []) %}
  ...
  {% endfor %}
</div>

{% if chart_key in charts %}
<div class="chart-container trend-chart-container">
  ...
</div>
{% endif %}

{% if trend_table.rows %}
<div class="table-wrap trend-table-wrap">
  ...
</div>
{% endif %}
{% else %}
<div class="trend-status trend-status-{{ trend_block.status or 'degraded' }}">
  {{ trend_block.status_message or "样本暂未就绪，请继续积累日报样本。" }}
</div>
{% endif %}
```

替换为

```jinja2
{% set _kpi_ready = (trend_kpis.get("status") == "ready") and trend_kpis.get("items") %}
{% set _chart_ready = trend_block.primary_chart and trend_block.primary_chart.get("status") == "ready" %}
{% set _table_ready = (trend_table.get("status") == "ready") and trend_table.get("rows") %}

{% if not (_kpi_ready or _chart_ready or _table_ready) %}
<div class="trend-status trend-status-{{ trend_block.status or 'degraded' }}">
  {{ trend_block.status_message or "样本暂未就绪，请继续积累日报样本。" }}
</div>
{% else %}
  {% if trend_block.status != "ready" and trend_block.status_message %}
  <div class="trend-partial-note">{{ trend_block.status_message }}</div>
  {% endif %}

  {% if _kpi_ready %}
  <div class="trend-kpi-grid">
    {% for item in trend_kpis["items"] %}
    <article class="trend-kpi-card">
      <span class="trend-kpi-label">{{ item.label or "" }}</span>
      <strong class="trend-kpi-value">{{ item.value if item.value is not none else "-" }}</strong>
    </article>
    {% endfor %}
  </div>
  {% endif %}

  {% if _chart_ready and chart_key in charts %}
  <div class="chart-container trend-chart-container">
    {% if trend_block.primary_chart and trend_block.primary_chart.title %}
    <h3>{{ trend_block.primary_chart.title }}</h3>
    {% endif %}
    <canvas data-chart-config='{{ charts[chart_key] | tojson }}'></canvas>
  </div>
  {% elif trend_block.primary_chart and trend_block.primary_chart.get("status") != "ready" %}
  <div class="trend-chart-placeholder">主图数据积累中</div>
  {% endif %}

  {% if _table_ready %}
  <div class="table-wrap trend-table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          {% for column in trend_table.columns or [] %}
          <th>{{ column }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in trend_table.rows %}
        <tr>
          {% for value in row.values() %}
          <td>{{ value if value is not none else "-" }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
{% endif %}
```

- [ ] **Step 2.8: 跑 Step 2.5 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_v3_html.py -v -k "test_trend_panel_renders_ready_components"`
Expected: PASS

- [ ] **Step 2.9: 跑 Task 2 相关回归（HTML + analytics）**

Run:
```bash
uv run --extra dev python -m pytest tests/test_report_analytics.py tests/test_v3_html.py tests/test_report_integration.py -v
```
Expected: 全绿（若已有 test 写死了"trend_block.status=accumulating 时无 KPI"，这时暴露 → 就地修改期望值并再跑）

- [ ] **Step 2.10: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_templates/daily_report_v3.html.j2 tests/test_report_analytics.py tests/test_v3_html.py
git commit -m "fix(report): 趋势页按组件级 status 独立渲染（T-A-2 · Stage A 修 2）

- _build_competition_trend 移除整块 _empty_trend_dimension 一刀切，
  改为 any_side_has_data / chart_ready / kpis_ready 三条线独立判断
- daily_report_v3.html.j2 趋势 panel 整块 if (trend_block.status == ready)
  拆成 kpis/primary_chart/table 三个独立 if；主图未就绪时展示占位说明
  不再把已 ready 的 KPI/table 吞掉

现象修复：测试2 月/产品 block.status=accumulating 但 kpis.status=ready(4 items)
+ table.status=ready(5 rows) 被整块 if 吞光 → 现在两者都能渲染。"
```

---

## Task 3: 清理 LLM incremental prompt 的重复"今日新增"段

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:531-541`（删第二段）+ `L510-521`（加 backfill_dominant 禁令）
- Test: `tests/test_report_llm.py`

- [ ] **Step 3.1: 写失败测试 — prompt 不得出现 "今日新增评论" 字面**

加到 `tests/test_report_llm.py`：

```python
def test_incremental_prompt_drops_window_today_new_segment():
    """spec §5.2 / §10.2：incremental 路径禁止把 window.reviews_count
    叙述为「今日新增评论」；只能用 change_digest.summary 的口径。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "report_semantics": "incremental",
        "kpis": {"ingested_review_rows": 50, "own_review_rows": 40,
                 "own_negative_review_rows": 3, "negative_review_rows": 5,
                 "own_product_count": 3, "competitor_product_count": 2,
                 "competitor_review_rows": 10, "health_index": 80,
                 "negative_review_rate": 0.1, "own_negative_review_rate": 0.075},
        "window": {"reviews_count": 50, "own_reviews_count": 40,
                   "competitor_reviews_count": 10, "new_negative_count": 3},
        "change_digest": {"summary": {
            "ingested_review_count": 50,
            "fresh_review_count": 4,
            "historical_backfill_count": 46,
            "fresh_own_negative_count": 0,
        }},
        "self": {"top_negative_clusters": [], "recommendations": [], "risk_products": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
    }
    prompt = _build_insights_prompt(analytics)
    # 违禁字面必须消失
    assert "今日新增评论" not in prompt, "L531-541 重复段未清理"
    # 应改用 fresh/backfill 叙述
    assert "本次入库评论" in prompt
    assert "近30天业务新增" in prompt or "近 30 天业务新增" in prompt
    assert "历史补采" in prompt


def test_incremental_prompt_forbids_business_new_when_backfill_dominant():
    """spec §7.6：backfill >= 70% 时 prompt 必须显式禁止把补采计入业务新增。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "report_semantics": "incremental",
        "kpis": {"ingested_review_rows": 500, "own_review_rows": 400,
                 "own_negative_review_rows": 10, "negative_review_rows": 15,
                 "own_product_count": 3, "competitor_product_count": 2,
                 "competitor_review_rows": 100, "health_index": 80,
                 "negative_review_rate": 0.03, "own_negative_review_rate": 0.025},
        "window": {"reviews_count": 500},
        "change_digest": {"summary": {
            "ingested_review_count": 500,
            "fresh_review_count": 10,
            "historical_backfill_count": 490,  # 98% backfill
        }},
        "self": {"top_negative_clusters": [], "recommendations": [], "risk_products": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
    }
    prompt = _build_insights_prompt(analytics)
    assert "补采" in prompt
    assert any(kw in prompt for kw in ["禁止", "不得", "不要"])
```

- [ ] **Step 3.2: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v -k "incremental_prompt_drops_window_today_new or incremental_prompt_forbids_business_new"`
Expected: FAIL · L535 的 `今日新增评论 {window['reviews_count']} 条` 仍在

- [ ] **Step 3.3: 删 L531-541 重复段，并在 L510-521 加 backfill_dominant 禁令**

编辑 `qbu_crawler/server/report_llm.py`：

**删除** L531-541（从 `# Window summary section (P007 Task 5)` 到 `elif report_semantics != "bootstrap" and analytics.get("perspective") == "dual":` 之前的整段）。具体 old_string：

```python
    # Window summary section (P007 Task 5)
    window = analytics.get("window", {})
    if report_semantics != "bootstrap" and window.get("reviews_count", 0) > 0:
        prompt += f"\n\n--- 今日变化 ---"
        prompt += f"\n今日新增评论 {window['reviews_count']} 条"
        prompt += f"（自有 {window.get('own_reviews_count', 0)}，竞品 {window.get('competitor_reviews_count', 0)}）"
        if window.get("new_negative_count", 0) > 0:
            prompt += f"\n注意：新增自有差评 {window['new_negative_count']} 条"
        prompt += "\n请在 executive_bullets 中提及今日新增变化（如有值得关注的新评论）。"
    elif report_semantics != "bootstrap" and analytics.get("perspective") == "dual":
        prompt += "\n\n今日无新增评论。executive_bullets 应聚焦累积数据中的关键洞察和持续存在的问题。"
```

替换为（只保留 elif 分支、不重复今日变化段）：

```python
    # Fallback for dual-perspective incremental with zero fresh reviews —
    # the main "--- 今日变化 ---" section is already written above (L510-521).
    if report_semantics != "bootstrap" and analytics.get("perspective") == "dual" \
            and not (change_digest.get("summary") or {}).get("fresh_review_count", 0):
        prompt += "\n\n本期无近30天业务新增评论。executive_bullets 应聚焦累积数据中的持续性问题。"
```

**然后** 改 L510-521（上面那段正牌的 incremental 分支）为：

```python
    else:
        summary = change_digest.get("summary") or {}
        if summary:
            ingested = summary.get("ingested_review_count", 0)
            fresh = summary.get("fresh_review_count", 0)
            backfill = summary.get("historical_backfill_count", 0)
            fresh_neg = summary.get("fresh_own_negative_count", 0)
            prompt += "\n\n--- 今日变化 ---"
            prompt += f"\n本次入库评论 {ingested} 条（近30天业务新增 {fresh} 条、历史补采 {backfill} 条）"
            if fresh_neg > 0:
                prompt += f"\n其中自有近30天差评 {fresh_neg} 条，请在 executive_bullets 中优先提示。"
            if ingested > 0 and backfill / ingested >= 0.7:
                prompt += (
                    "\n⚠️ 本次入库以历史补采为主。禁止把补采评论计入业务新增，"
                    "不要使用「今日新增」或「暴增」等措辞。"
                )
            prompt += "\n叙述请使用「本次入库」「近30天业务新增」，不要使用「今日新增」。"
```

- [ ] **Step 3.4: 跑 Step 3.1 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v -k "incremental_prompt"`
Expected: 2 PASS + 既有 `test_build_insights_prompt_includes_window_summary` 可能 FAIL（因为旧测试断言 prompt 里有 "今日新增评论"）

- [ ] **Step 3.5: 同步修正既有的 `test_build_insights_prompt_includes_window_summary`**

改 `tests/test_report_llm.py` 的 `test_build_insights_prompt_includes_window_summary`：
- 把断言 `"今日新增评论" in prompt` 改为 `"本次入库评论" in prompt`
- 把断言 `str(window_count) in prompt` 保留（数量应仍在 prompt 里，只是措辞不同）

- [ ] **Step 3.6: 再跑**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v`
Expected: 32/32 全绿（原 30 + 新增 2）

- [ ] **Step 3.7: Commit**

```bash
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "fix(report_llm): 清理 incremental prompt 重复段并收口到 change_digest（T-A-3 · Stage A 修 4）

- 删除 L531-541 残留的「--- 今日变化 ---」二段（直接写 window.reviews_count 为今日新增评论）
- L510-521 incremental 主路径只从 change_digest.summary 取 ingested/fresh/backfill
- backfill >= 70% 时 prompt 显式禁止 LLM 把补采计入业务新增

现象修复：本轮 bootstrap 测试中不激活，但 Phase 1 首个 incremental run 起
此段立即向 LLM 注入「今日新增评论 {window}」，会把 LLM headline 重新拖回
漂移状态。"
```

---

## Task 4: 扩大 bootstrap 违禁词检测（字段面 + 模式）

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:280-298`
- Test: `tests/test_report_llm.py`

- [ ] **Step 4.1: 写失败测试 — 字段面扩展**

加到 `tests/test_report_llm.py`：

```python
def test_bootstrap_violation_covers_competitive_insight():
    from qbu_crawler.server.report_llm import _has_bootstrap_language_violation
    analytics = {"report_semantics": "bootstrap"}
    result = {"hero_headline": "ok", "competitive_insight": "今日新增 20 条评论说明竞品领先"}
    assert _has_bootstrap_language_violation(result, analytics) is True


def test_bootstrap_violation_covers_benchmark_takeaway():
    from qbu_crawler.server.report_llm import _has_bootstrap_language_violation
    analytics = {"report_semantics": "bootstrap"}
    result = {"hero_headline": "ok", "benchmark_takeaway": "较昨日提升明显"}
    assert _has_bootstrap_language_violation(result, analytics) is True


def test_bootstrap_violation_covers_priority_actions():
    from qbu_crawler.server.report_llm import _has_bootstrap_language_violation
    analytics = {"report_semantics": "bootstrap"}
    result = {"hero_headline": "ok",
              "improvement_priorities": [{"action": "针对今日暴增的投诉立即介入"}]}
    assert _has_bootstrap_language_violation(result, analytics) is True


def test_bootstrap_violation_catches_generic_new_review_pattern():
    from qbu_crawler.server.report_llm import _has_bootstrap_language_violation
    analytics = {"report_semantics": "bootstrap"}
    result = {"hero_headline": "新增 450 条评论说明用户基础增长"}
    assert _has_bootstrap_language_violation(result, analytics) is True


def test_bootstrap_violation_passes_clean_baseline_copy():
    from qbu_crawler.server.report_llm import _has_bootstrap_language_violation
    analytics = {"report_semantics": "bootstrap"}
    result = {
        "hero_headline": "首次基线扫描 593 条评论完成",
        "executive_summary": "当前截面 5 款自有产品健康指数 94.9",
        "competitive_insight": "竞品在做工维度 gap_rate=13 暂无增长性叙述",
        "benchmark_takeaway": "自有可借鉴竞品的售后沟通机制",
        "executive_bullets": ["监控起点已建立"],
        "improvement_priorities": [{"action": "优先处理 Walton's Quick Patty Maker 的结构设计问题"}],
    }
    assert _has_bootstrap_language_violation(result, analytics) is False
```

- [ ] **Step 4.2: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v -k "bootstrap_violation_covers or bootstrap_violation_catches_generic or bootstrap_violation_passes_clean"`
Expected: 4 FAIL + 1 PASS（`_covers_competitive_insight` 等失败因为 competitive_insight 当前不在扫描范围）

- [ ] **Step 4.3: 扩大检测范围**

编辑 `qbu_crawler/server/report_llm.py:280-298`，把

```python
def _has_bootstrap_language_violation(result, analytics):
    if _report_semantics(analytics) != "bootstrap":
        return False

    texts = [
        result.get("hero_headline", ""),
        result.get("executive_summary", ""),
        *[str(item) for item in (result.get("executive_bullets") or [])],
    ]
    merged = "\n".join(texts)
    forbidden_patterns = (
        r"今日新增",
        r"今日暴增",
        r"较昨日",
        r"较上期",
        r"环比",
        r"今日.*新增",
    )
    return any(re.search(pattern, merged) for pattern in forbidden_patterns)
```

替换为

```python
def _has_bootstrap_language_violation(result, analytics):
    if _report_semantics(analytics) != "bootstrap":
        return False

    priorities = result.get("improvement_priorities") or []
    texts = [
        result.get("hero_headline", ""),
        result.get("executive_summary", ""),
        result.get("competitive_insight", ""),
        result.get("benchmark_takeaway", ""),
        *[str(item) for item in (result.get("executive_bullets") or [])],
        *[str((p or {}).get("action", "")) for p in priorities],
    ]
    merged = "\n".join(texts)
    forbidden_patterns = (
        r"今日新增",
        r"今日暴增",
        r"较昨日",
        r"较上期",
        r"环比",
        r"同比",
        r"今日.*新增",
        r"本日.*新增",
        r"新增\s*\d+\s*条\s*评论",   # generic fallback pattern — covers "新增 450 条评论" etc.
    )
    return any(re.search(pattern, merged) for pattern in forbidden_patterns)
```

- [ ] **Step 4.4: 跑 Step 4.1 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v -k "bootstrap_violation"`
Expected: 全绿（含先前 `test_generate_report_insights_bootstrap_forbidden_new_language_falls_back`）

- [ ] **Step 4.5: Commit**

```bash
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "fix(report_llm): 扩大 bootstrap 违禁词检测（T-A-4 · Stage A 修 5）

- 字段面：competitive_insight / benchmark_takeaway / improvement_priorities[*].action
  全部纳入扫描
- 模式：新增 同比 / 本日.*新增 / 新增\s*\d+\s*条\s*评论 三条通配模式
  覆盖 LLM 可能用的 generic 增量叙述

现象修复：Codex P1 指出 competitive_insight 里若出现「今日新增」当前检测器
不会触发 fallback；扩面后任一字段命中都会 fallback。"
```

---

## Task 5: Fallback / 邮件感知 `report_semantics`

**Files:**
- Modify: `qbu_crawler/server/report_common.py:600-643`（`_fallback_hero_headline` + `_fallback_executive_bullets`）
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2:220-224`
- Test: `tests/test_report_common.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 5.1: 写失败测试 — fallback bullets 感知 semantics**

加到 `tests/test_report_common.py`：

```python
def test_fallback_executive_bullets_bootstrap_uses_baseline_wording():
    """spec §10.3：deterministic fallback 在 bootstrap 下禁用「新增评论」
    措辞，改用「建立监控基线」话术。"""
    from qbu_crawler.server.report_common import _fallback_executive_bullets
    normalized = {
        "report_semantics": "bootstrap",
        "is_bootstrap": True,
        "kpis": {"product_count": 5, "ingested_review_rows": 593},
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "negative_opportunities": []},
        "change_digest": {"summary": {}},
    }
    bullets = _fallback_executive_bullets(normalized)
    merged = "\n".join(bullets)
    assert "新增评论" not in merged, "bootstrap fallback 仍在写「新增评论」"
    assert "基线" in merged or "监控起点" in merged


def test_fallback_executive_bullets_incremental_cites_change_digest_fields():
    from qbu_crawler.server.report_common import _fallback_executive_bullets
    normalized = {
        "report_semantics": "incremental",
        "is_bootstrap": False,
        "kpis": {"product_count": 5, "ingested_review_rows": 100},
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "negative_opportunities": []},
        "change_digest": {"summary": {
            "fresh_review_count": 3, "historical_backfill_count": 97,
        }},
    }
    bullets = _fallback_executive_bullets(normalized)
    merged = "\n".join(bullets)
    assert "本次入库评论" in merged or "本次入库" in merged
    assert "近30天业务新增" in merged or "近 30 天业务新增" in merged


def test_fallback_hero_headline_bootstrap_falls_back_to_baseline_when_no_risk():
    from qbu_crawler.server.report_common import _fallback_hero_headline
    normalized = {
        "report_semantics": "bootstrap",
        "is_bootstrap": True,
        "kpis": {"ingested_review_rows": 593},
        "self": {"risk_products": [], "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
    }
    headline = _fallback_hero_headline(normalized)
    assert "基线" in headline or "监控起点" in headline
    assert "今日新增" not in headline
```

- [ ] **Step 5.2: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py -v -k "test_fallback_executive_bullets or test_fallback_hero_headline_bootstrap"`
Expected: 3 FAIL · fallback 写 "新增评论"

- [ ] **Step 5.3: 改 `_fallback_executive_bullets`**

编辑 `qbu_crawler/server/report_common.py:616-643`，把

```python
def _fallback_executive_bullets(normalized):
    bullets = []
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    if top_product:
        product_name = top_product.get("product_name") or "自有产品"
        product_sku = top_product.get("product_sku") or ""
        sku_text = f"（SKU: {product_sku}）" if product_sku else ""
        bullets.append(
            f"{product_name}{sku_text}：{top_product.get('top_labels_display') or '暂无主要问题'}"
        )
    top_theme = (normalized["competitor"]["top_positive_themes"] or [None])[0]
    if top_theme:
        bullets.append(
            f"{top_theme.get('label_display')}：{top_theme.get('review_count') or 0} 条"
        )
    top_opportunity = (normalized["competitor"]["negative_opportunities"] or [None])[0]
    if top_opportunity:
        product_name = top_opportunity.get("product_name") or "竞品"
        product_sku = top_opportunity.get("product_sku") or ""
        sku_text = f"（SKU: {product_sku}）" if product_sku else ""
        bullets.append(
            f"{product_name}{sku_text}：{top_opportunity.get('label_display_list') or '暂无主要短板'}"
        )
    if not bullets:
        bullets.append(
            f"当前纳入分析产品 {normalized['kpis']['product_count']} 个，新增评论 {normalized['kpis']['ingested_review_rows']} 条。"
        )
    return bullets[:3]
```

替换为

```python
def _fallback_executive_bullets(normalized):
    bullets = []
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    if top_product:
        product_name = top_product.get("product_name") or "自有产品"
        product_sku = top_product.get("product_sku") or ""
        sku_text = f"（SKU: {product_sku}）" if product_sku else ""
        bullets.append(
            f"{product_name}{sku_text}：{top_product.get('top_labels_display') or '暂无主要问题'}"
        )
    top_theme = (normalized["competitor"]["top_positive_themes"] or [None])[0]
    if top_theme:
        bullets.append(
            f"{top_theme.get('label_display')}：{top_theme.get('review_count') or 0} 条"
        )
    top_opportunity = (normalized["competitor"]["negative_opportunities"] or [None])[0]
    if top_opportunity:
        product_name = top_opportunity.get("product_name") or "竞品"
        product_sku = top_opportunity.get("product_sku") or ""
        sku_text = f"（SKU: {product_sku}）" if product_sku else ""
        bullets.append(
            f"{product_name}{sku_text}：{top_opportunity.get('label_display_list') or '暂无主要短板'}"
        )
    if not bullets:
        semantics = normalized.get("report_semantics") or "incremental"
        is_boot = bool(normalized.get("is_bootstrap")) or semantics == "bootstrap"
        ingested = normalized["kpis"].get("ingested_review_rows", 0)
        products = normalized["kpis"].get("product_count", 0)
        if is_boot:
            bullets.append(
                f"当前纳入分析产品 {products} 个，本次入库评论 {ingested} 条，"
                f"用于建立监控基线。"
            )
        else:
            digest_summary = (normalized.get("change_digest") or {}).get("summary", {}) or {}
            fresh = digest_summary.get("fresh_review_count", 0)
            backfill = digest_summary.get("historical_backfill_count", 0)
            bullets.append(
                f"当前纳入分析产品 {products} 个，本次入库评论 {ingested} 条"
                f"（近30天业务新增 {fresh}，历史补采 {backfill}）。"
            )
    return bullets[:3]
```

- [ ] **Step 5.4: 改 `_fallback_hero_headline`**

编辑 `qbu_crawler/server/report_common.py:600-613`，把

```python
def _fallback_hero_headline(normalized):
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    top_cluster = (normalized["self"]["top_negative_clusters"] or [None])[0]
    if top_product and top_cluster:
        return (
            f"自有产品 {top_product.get('product_name')} 的{top_cluster.get('label_display')}问题最值得优先处理。"
        )
    if top_product:
        return f"自有产品 {top_product.get('product_name')} 当前风险最高，建议优先排查。"
    if normalized["competitor"]["top_positive_themes"]:
        return (
            f"当前竞品用户认可以 {normalized['competitor']['top_positive_themes'][0].get('label_display')} 为主。"
        )
    return "当前样本不足以形成明确主结论，建议继续积累样本后再判断。"
```

替换为

```python
def _fallback_hero_headline(normalized):
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    top_cluster = (normalized["self"]["top_negative_clusters"] or [None])[0]
    if top_product and top_cluster:
        return (
            f"自有产品 {top_product.get('product_name')} 的{top_cluster.get('label_display')}问题最值得优先处理。"
        )
    if top_product:
        return f"自有产品 {top_product.get('product_name')} 当前风险最高，建议优先排查。"
    if normalized["competitor"]["top_positive_themes"]:
        return (
            f"当前竞品用户认可以 {normalized['competitor']['top_positive_themes'][0].get('label_display')} 为主。"
        )
    # Final baseline fallback — must be mode-aware
    semantics = normalized.get("report_semantics") or "incremental"
    is_boot = bool(normalized.get("is_bootstrap")) or semantics == "bootstrap"
    ingested = (normalized.get("kpis") or {}).get("ingested_review_rows", 0)
    if is_boot:
        return f"首次基线扫描 {ingested} 条评论完成，建立监控起点。"
    return "当前样本不足以形成明确主结论，建议继续积累样本后再判断。"
```

- [ ] **Step 5.5: 跑 fallback 测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py -v -k "test_fallback_executive_bullets or test_fallback_hero_headline_bootstrap"`
Expected: 3 PASS

- [ ] **Step 5.6: 写失败测试 — 邮件 fallback 感知**

真实入口是 `qbu_crawler.server.report_snapshot._render_full_email_html(snapshot, analytics)`，内部会调 `load_previous_report_context(run_id)` 读 DB；单测里用 `monkeypatch` 打掉或传 `run_id=0` 绕过。

加到 `tests/test_v3_html.py`：

```python
def _email_fallback_analytics(semantics, ingested, fresh, backfill):
    return {
        "report_semantics": semantics,
        "is_bootstrap": semantics == "bootstrap",
        "mode": "baseline" if semantics == "bootstrap" else "incremental",
        "kpis": {"own_product_count": 5, "health_index": 94.9,
                 "own_review_rows": 450, "high_risk_count": 1,
                 "competitor_product_count": 3, "product_count": 8,
                 "ingested_review_rows": ingested},
        "cumulative_kpis": {},
        "change_digest": {
            "enabled": True,
            "view_state": "bootstrap" if semantics == "bootstrap" else "active",
            "summary": {"ingested_review_count": ingested,
                        "fresh_review_count": fresh,
                        "historical_backfill_count": backfill,
                        "fresh_own_negative_count": 0,
                        "issue_new_count": 0, "issue_escalated_count": 0,
                        "issue_improving_count": 0, "state_change_count": 0,
                        "ingested_own_review_count": 0,
                        "ingested_competitor_review_count": 0,
                        "ingested_own_negative_count": 0},
            "warnings": {"translation_incomplete": {"enabled": False, "message": ""},
                         "estimated_dates": {"enabled": False, "message": ""},
                         "backfill_dominant": {"enabled": False, "message": ""}},
            "empty_state": {"enabled": False, "title": "", "description": ""},
            "issue_changes": {"new": [], "escalated": [], "improving": [], "de_escalated": []},
            "product_changes": {"price_changes": [], "stock_changes": [],
                                "rating_changes": [], "new_products": [], "removed_products": []},
            "review_signals": {"fresh_competitor_positive_reviews": [], "fresh_negative_reviews": []},
        },
        "self": {"risk_products": [], "top_negative_clusters": [],
                 "top_positive_themes": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "negative_opportunities": [], "gap_analysis": []},
        "window": {"reviews_count": ingested, "new_reviews": []},
        "report_copy": {"executive_bullets": []},  # trigger email fallback branch
    }


def test_email_fallback_bootstrap_uses_baseline_wording(monkeypatch):
    """email_full.html.j2 在 _bullets 为空时的 fallback 必须按 semantics 分路。"""
    from qbu_crawler.server import report_snapshot
    # Stub DB lookup: no previous context
    monkeypatch.setattr(report_snapshot, "load_previous_report_context",
                        lambda run_id: (None, None))

    analytics = _email_fallback_analytics("bootstrap", ingested=593, fresh=4, backfill=589)
    snapshot = {"run_id": 0, "logical_date": "2026-04-24",
                "reviews": [], "products": [], "untranslated_count": 0}
    html = report_snapshot._render_full_email_html(snapshot, analytics)
    assert "新增评论" not in html, "bootstrap email fallback 仍写「新增评论」"
    assert "建立监控基线" in html or "监控起点" in html


def test_email_fallback_incremental_cites_fresh_and_backfill(monkeypatch):
    from qbu_crawler.server import report_snapshot
    monkeypatch.setattr(report_snapshot, "load_previous_report_context",
                        lambda run_id: (None, None))

    analytics = _email_fallback_analytics("incremental", ingested=50, fresh=8, backfill=42)
    snapshot = {"run_id": 0, "logical_date": "2026-04-24",
                "reviews": [], "products": [], "untranslated_count": 0}
    html = report_snapshot._render_full_email_html(snapshot, analytics)
    assert "近30天业务新增" in html or "近 30 天业务新增" in html
    assert "历史补采" in html
```

- [ ] **Step 5.7: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_v3_html.py -v -k "test_email_fallback_bootstrap or test_email_fallback_incremental"`
Expected: 2 FAIL · 模板仍输出"新增评论 593 条"

- [ ] **Step 5.8: 改 `email_full.html.j2:220-224`**

把

```jinja2
            {% else %}
            <div style="padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;font-size:12px;color:#64748b;">
              当前纳入分析产品 {{ _kpis.get("own_product_count", 0) }} 个，新增评论 {{ _summary.get("ingested_review_count", 0) }} 条。
            </div>
            {% endif %}
```

替换为

```jinja2
            {% else %}
            <div style="padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;font-size:12px;color:#64748b;">
              {% if _semantics == "bootstrap" or _view_state == "bootstrap" %}
              首次基线已完成，本次入库评论 {{ _summary.get("ingested_review_count", 0) }} 条，用于建立监控基线。
              {% else %}
              {% set _fresh = _summary.get("fresh_review_count", 0) %}
              {% set _backfill = _summary.get("historical_backfill_count", 0) %}
              本次入库评论 {{ _summary.get("ingested_review_count", 0) }} 条（近30天业务新增 {{ _fresh }}，历史补采 {{ _backfill }}）。
              {% endif %}
            </div>
            {% endif %}
```

- [ ] **Step 5.9: 跑邮件测试变绿**

Run: `uv run --extra dev python -m pytest tests/test_v3_html.py -v -k "test_email_fallback"`
Expected: 2 PASS

- [ ] **Step 5.10: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_templates/email_full.html.j2 tests/test_report_common.py tests/test_v3_html.py
git commit -m "fix(report): fallback 与邮件兜底文案感知 report_semantics（T-A-5 · Stage A 修 6）

- _fallback_executive_bullets / _fallback_hero_headline 按 semantics 分路
  bootstrap -> 「建立监控基线 / 监控起点」
  incremental -> 「本次入库 N 条（近30天业务新增 X / 历史补采 Y）」
- email_full.html.j2 的 _bullets 空分支同步切语义
- 彻底消除「新增评论 N 条」这句模糊叙述

现象修复：若 LLM 不可用 + executive_bullets 为空 + bootstrap，之前会在邮件
兜底里再次漏出增量措辞；现在 fallback 链路三层全部感知 semantics。"
```

---

## Task 6: Stage A 最终验收 · 版本号 bump + grep 门禁 + 全量回归

**Files:**
- Modify: `pyproject.toml` / `qbu_crawler/__init__.py` / `uv.lock`
- Test: 全量 pytest

- [ ] **Step 6.1: Bump 版本号 0.3.17 → 0.3.18**

改 `pyproject.toml`：`version = "0.3.17"` → `version = "0.3.18"`
改 `qbu_crawler/__init__.py`：`__version__ = "0.3.17"` → `__version__ = "0.3.18"`

跑 `uv sync` 同步 uv.lock：

```bash
uv sync 2>&1 | tail -3
```
Expected: `uv.lock` 里 `name = "qbu-crawler"` 块的 version 同步到 0.3.18

- [ ] **Step 6.2: 跑 grep 门禁 5 条**

```bash
# 1. 源码不得再用 "今日新增"（除违禁词表）
grep -rn "今日新增" qbu_crawler/ | grep -vE "forbidden_patterns|禁止|不得|不要|L531|today_new"
# Expected: 0 行

# 2. 模板不得出现 "新增评论 "（带空格结尾，避开注释/禁令）
grep -rn "新增评论" qbu_crawler/server/report_templates/ qbu_crawler/server/report_common.py qbu_crawler/server/report_llm.py | grep -v "本次入库"
# Expected: 0 行

# 3. 模板不得直接解释 window.reviews_count / cumulative_kpis
grep -rn "cumulative_kpis\|window\.reviews_count\|_cumulative" qbu_crawler/server/report_templates/
# Expected: 0 行

# 4. trend 模板不得再用整块 status == ready
grep -n 'trend_block.status == "ready"' qbu_crawler/server/report_templates/daily_report_v3.html.j2
# Expected: 0 行

# 5. 健康指数 tooltip 必须含 贝叶斯 或 NPS
grep '"健康指数"' qbu_crawler/server/report_common.py | grep -E "贝叶斯|NPS"
# Expected: 1 行
```

若任一条未通过 → 回到对应 Task 排查。

- [ ] **Step 6.3: 跑全量报告相关回归**

```bash
uv run --extra dev python -m pytest \
  tests/test_report.py \
  tests/test_report_snapshot.py \
  tests/test_report_analytics.py \
  tests/test_report_common.py \
  tests/test_report_llm.py \
  tests/test_v3_html.py \
  tests/test_v3_excel.py \
  tests/test_report_integration.py \
  tests/test_metric_semantics.py \
  tests/test_v3_modes.py \
  tests/test_v3_mode_semantics.py \
  -v 2>&1 | tail -40
```
Expected: 全绿，任何失败就地分析修复

- [ ] **Step 6.4: 预发联测 · bootstrap 场景**

在预发环境触发一次真实 bootstrap run（手动或等 daily scheduler），然后：

```bash
# 在预发机执行
sqlite3 $QBU_DATA_DIR/products.db \
  "SELECT id, service_version, report_mode, report_phase FROM workflow_runs ORDER BY id DESC LIMIT 1"
# Expected: service_version=0.3.18, report_mode=baseline

# 读产物
jq '.report_semantics, .is_bootstrap, .kpis.health_index, .trend_digest.data.month.products.kpis.status, .trend_digest.data.month.products.table.status' \
   $QBU_DATA_DIR/reports/workflow-run-N-analytics-*.json
# Expected: "bootstrap", true, 94.9 附近, "ready", "ready"

# HTML 肉眼
# - tooltip "健康指数" 悬停应显示"贝叶斯 NPS"
# - month/products 块即便整块 accumulating 也能看到 KPI + 表格
# - executive_bullets 不得出现"领跑"指向非 top SKU
# - 全局 grep "今日新增" 应 0 命中
```

- [ ] **Step 6.5: 预发联测 · incremental 场景（fake）**

手动把 DB 某个 run 的 `report_mode` 改为非 `baseline` 触发一次 re-generate：

```bash
sqlite3 $QBU_DATA_DIR/products.db "UPDATE workflow_runs SET report_mode='incremental' WHERE id=<N>"
# 然后通过 API 重新生成报告
curl -X POST http://localhost:8000/api/reports/<N>/regenerate -H "Authorization: Bearer $API_KEY"

# 验证
jq '.report_semantics, .change_digest.summary.fresh_review_count, .change_digest.summary.historical_backfill_count' \
   $QBU_DATA_DIR/reports/workflow-run-<N>-analytics-*.json
# Expected: "incremental", 数字, 数字

# 检查 prompt（需临时开 debug 日志）或直接跑 pytest 回归
grep "今日新增评论" $QBU_DATA_DIR/logs/*.log
# Expected: 0 行
```

- [ ] **Step 6.6: Commit 版本号 bump + 打 tag**

```bash
git add pyproject.toml qbu_crawler/__init__.py uv.lock
git commit -m "chore: bump version 0.3.17 -> 0.3.18（Stage A 完成）"
git tag -a v0.3.18-stage-a -m "Stage A · Phase 1 P1 remediation (6 fixes)"
git log --oneline -10
git tag -l "v0.3*"
```

- [ ] **Step 6.7: 更新 continuity 文件**

编辑 `docs/reviews/2026-04-24-report-upgrade-continuity.md`：

- `status` 改为 `Stage-A-COMPLETE · Stage-B-PLAN-NOT-WRITTEN`
- `last_commit` 改为刚才的版本号 bump commit
- `last_tag` 改为 `v0.3.18-stage-a`
- `next_action` 改为 "写 Stage B implementation plan via superpowers:writing-plans"
- 在 "进度日志" 最上方加一条 Stage A 完成记录

然后：
```bash
git add docs/reviews/2026-04-24-report-upgrade-continuity.md
git commit -m "docs: Stage A 完成 · 更新 continuity pointer"
```

- [ ] **Step 6.8: 契约冻结期启动宣告**

连续 3 个 daily run 不允许改 `change_digest / trend_digest / kpis` 顶层键名。观测项见 continuity 文件 "禁止改动清单"。

---

## 实施顺序

严格按下面顺序执行（Task 内部 Red/Green/Commit，Task 间不得跳过）：

1. **Task 1** 健康指数贝叶斯统一（修 1）
2. **Task 2** 趋势 mixed-state（修 2）
3. **Task 3** LLM incremental prompt 清理（修 4）
4. **Task 4** 违禁词扩面（修 5）
5. **Task 5** fallback/邮件 semantics（修 6）
6. **Task 6** 最终验收 + tag + 冻结期启动

---

## 风险提示

- **最大风险**：Task 2 的 competition 后端重写可能触发已有的 `test_report_analytics.py::test_build_competition_trend_*` 回归测试 — 这些测试当前是针对"整维度一刀切"写的。修复时直接把期望值改为组件级，不要绕过。
- **Task 1 副作用**：`_build_sentiment_trend` 的 `own_negative_rates` 空桶从 `0` 改成 `None` 会影响下游 Chart.js 配置 — 检查 `report_charts.py` 里 sentiment 图的 null 处理（Chart.js 原生支持 null 断点，应该没问题，但值得在 Step 1.13 肉眼确认一次）。
- **Task 5 `_render_email_full` 入口**：plan 里假设有这个函数；实际可能在 `report_snapshot.py` 或 `report.py` 里，Step 5.6 执行前先 grep 确认真实入口，必要时调整导入。
- **版本号 0.3.18 不冲突**：当前 master 最新 commit 已是 0.3.17；Stage A 独占这个 bump。若 Stage B 并行开工（plan 中允许）→ Stage B 需要 0.3.19，要在 Stage B plan 里明确。
- **契约冻结期不能被 Stage B 违反**：Stage B 修 8（kpis 消歧：`negative_review_rate` 迁走）本质是键名变更 — 必须在 Stage A 合入**立即**完成，否则冻结期开始后不能改。所以 Stage B plan 里的修 8 要前置。

---

## 完成定义

以下条件全部满足，Stage A 才算完成：

- 6 个 Task 全部 Commit
- grep 门禁 5 条全绿
- 全量报告相关 pytest 全绿（约 200+ 用例）
- 预发 bootstrap + incremental 两次 run 产物人工验收通过
- tag `v0.3.18-stage-a` 已打
- continuity 文件已更新为 `Stage-A-COMPLETE`

---

Plan complete and saved to `docs/superpowers/plans/2026-04-24-stage-a-p1-remediation.md`.
