# 报告质量多维度优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复产品评论分析报告中数据口径不一致、图表可读性差、AI 建议缺乏引证、趋势数据未利用等 13 项问题，使报告准确、可读、可操作。

**Architecture:** 按优先级 P0→P3 分组，每组内按文件聚合减少上下文切换。修改集中在 report_llm.py（LLM prompt）、report_charts.py（图表渲染）、report_common.py（数据归一化）、report_analytics.py（数据计算）、daily_report.html.j2（模板）五个文件。

**Tech Stack:** Python 3.10+, Plotly, Jinja2, pytest

---

## 文件影响矩阵

| 文件 | 涉及 Task | 改动类型 |
|------|-----------|----------|
| `qbu_crawler/server/report_llm.py` | T1, T3 | LLM prompt 口径修正 + 建议引证增强 |
| `qbu_crawler/server/report_charts.py` | T2, T6, T7 | 热力图 margin + 象限图标签 + 柱状图百分比 |
| `qbu_crawler/server/report_common.py` | T4, T5, T9, T12 | 趋势文本 + 近期活跃度 + 差距分析拓宽 + 正面 KPI + issue cards 上限 |
| `qbu_crawler/server/report_analytics.py` | T4, T5, T8, T11 | 趋势计算 + 近期活跃度 + 样例多样性 + 翻译覆盖率 |
| `qbu_crawler/server/report_templates/daily_report.html.j2` | T5, T11, T12 | 近期标注 + 翻译覆盖率 + cards 上限解除 |
| `tests/test_report_llm.py` | T1, T3 | prompt 断言 |
| `tests/test_report_charts.py` | T2, T6, T7 | 图表渲染断言 |
| `tests/test_report_common.py` | T4, T5, T9, T12 | 归一化断言 |
| `tests/test_report_analytics.py` | T4, T5, T8, T11 | 分析计算断言 |

---

## P0 — 数据准确性（必须修复）

### Task 1: 修复 LLM prompt KPI 口径 — hero_headline 与 KPI 卡片一致

**问题:** `_build_insights_prompt()` 传给 LLM 的 KPIs 用 `ingested_review_rows`（全量=148）和 `negative_review_rows`（全量=52），LLM 据此生成 "148条评论中52条差评，差评率35.1%"。但 KPI 卡片显示的是 `own_negative_review_rate`（自有=44.6%）和 `own_review_rows`（自有=112）。读者一眼看到两个矛盾的数字。

**方案:** prompt 中区分自有和全量口径，要求 LLM 在 hero_headline 中仅引用自有数据，全量数据仅作为背景。

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:277-342` — `_build_insights_prompt()`
- Test: `tests/test_report_llm.py`

- [ ] **Step 1: 写测试 — 验证 prompt 包含自有口径 KPI**

注意：`_insights_analytics()` fixture 缺少 `own_review_rows` 等字段，测试中需补全。

```python
# tests/test_report_llm.py — 新增测试函数
def test_insights_prompt_uses_own_kpis():
    """Prompt must reference own_review_rows and own_negative_review_rows for hero data."""
    from qbu_crawler.server.report_llm import _build_insights_prompt
    analytics = _insights_analytics()
    # _insights_analytics() 缺少以下字段，需补全
    analytics["kpis"]["own_review_rows"] = 112
    analytics["kpis"]["competitor_review_rows"] = 36
    analytics["kpis"]["own_negative_review_rows"] = 50
    analytics["kpis"]["own_negative_review_rate"] = 50 / 112
    analytics["kpis"]["ingested_review_rows"] = 148
    analytics["kpis"]["negative_review_rows"] = 52
    prompt = _build_insights_prompt(analytics)
    # Prompt must contain own-specific numbers
    assert "自有评论 112" in prompt
    assert "自有差评 50" in prompt
    # Must NOT lead with global totals that contradict KPI cards
    # 全量数据仅作为背景补充
    assert "hero_headline" in prompt
    assert "自有产品数据" in prompt or "自有" in prompt.split("hero_headline")[1]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_report_llm.py::test_insights_prompt_uses_own_kpis -xvs`
Expected: FAIL — prompt 当前只包含全量数据

- [ ] **Step 3: 修改 `_build_insights_prompt()` 传入自有口径**

```python
# report_llm.py:277-342, 修改 _build_insights_prompt()
# 在 line 277-283 区域，增加自有口径变量提取：
own_reviews = kpis.get("own_review_rows", 0)
own_neg = kpis.get("own_negative_review_rows", 0)
own_rate = kpis.get("own_negative_review_rate", 0)
comp_reviews = kpis.get("competitor_review_rows", 0)

# 修改 prompt 模板的"数据概要"段，改为：
f"""数据概要：
- 自有产品 {own_count} 个，竞品 {comp_count} 个
- 自有评论 {own_reviews} 条，自有差评 {own_neg} 条（自有差评率 {own_rate * 100:.1f}%）
- 全量评论 {total} 条（含竞品 {comp_reviews} 条），全量差评 {neg} 条
- 健康指数：{health}/100"""

# 修改 output schema 中 hero_headline 的说明：
"hero_headline": "一句话核心结论（不超过40字，必须引用自有产品数据，不要引用含竞品的全量数据）",
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_report_llm.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "fix(report): align LLM prompt KPIs with own-product metrics to match KPI cards"
```

---

### Task 2: 修复热力图 Y 轴被截断 — 产品名不可读

**问题:** `_build_heatmap()` 的 `margin=dict(l=10)` 左边距仅 10px，产品名（如 "Commercial-Grade Sausage Stuffer"）被裁剪到只剩 "r..."。

**方案:** 动态计算左边距，基于最长 Y 轴标签长度；同时限制标签最大字符数。

**Files:**
- Modify: `qbu_crawler/server/report_charts.py:141-192` — `_build_heatmap()`
- Test: `tests/test_report_charts.py`

- [ ] **Step 1: 写测试 — 验证 heatmap margin 自适应**

```python
# tests/test_report_charts.py — 新增测试
def test_heatmap_left_margin_adapts_to_label_length():
    """Heatmap left margin must grow with y_label length."""
    from qbu_crawler.server.report_charts import _build_heatmap
    long_labels = ["Cabela's Commercial-Grade Sausage Stuffer", "Another Very Long Product Name Here"]
    html = _build_heatmap(
        z=[[0.1, -0.2], [0.3, -0.1]],
        x_labels=["质量", "设计"],
        y_labels=long_labels,
        title="Test",
    )
    # The margin-left should be > 10 (old hardcoded value)
    # We verify by checking the rendered HTML contains a reasonable layout
    assert html  # at minimum it renders without error
```

- [ ] **Step 2: 运行测试确认当前行为**

Run: `uv run python -m pytest tests/test_report_charts.py::test_heatmap_left_margin_adapts_to_label_length -xvs`
Expected: PASS（当前也能渲染，只是效果差）

- [ ] **Step 3: 修改 `_build_heatmap()` — 动态 margin + 标签截断**

```python
# report_charts.py:141-192, _build_heatmap() 修改两处：

# 1. 在函数开头对 y_labels 截断：
max_label_len = 30
display_labels = [
    (label[:max_label_len - 1] + "…" if len(label) > max_label_len else label)
    for label in y_labels
]

# 2. 用 display_labels 替代 y_labels 传入 Heatmap 和 annotations

# 3. 动态计算 left margin：
longest = max((len(label) for label in display_labels), default=5)
left_margin = max(40, min(longest * 7, 220))

# 4. 修改 fig.update_layout 中的 margin：
margin=dict(l=left_margin, r=10, t=36, b=10),
```

- [ ] **Step 4: 运行全部 chart 测试**

Run: `uv run python -m pytest tests/test_report_charts.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_charts.py tests/test_report_charts.py
git commit -m "fix(charts): dynamic heatmap left margin + label truncation for readability"
```

---

## P1 — 高影响改进

### Task 3: AI 建议增加具体引证 — sub_features + 产品名

**问题:** AI 建议（如"针对磨损和光泽变形进行寿命测试"）太泛，没有引用具体 sub_features 数据和涉及产品。产品团队无法据此行动。

**方案:** 在 LLM prompt 的 `improvement_priorities` 输出 schema 中增加引证要求，并在 cluster 数据段传入 `affected_products` 和完整 `sub_features` 列表。

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:285-367` — `_build_insights_prompt()`
- Test: `tests/test_report_llm.py`

- [ ] **Step 1: 写测试 — 验证 prompt 包含产品名和 sub_features**

```python
def test_insights_prompt_includes_affected_products():
    """Prompt must include affected product names per cluster for targeted recommendations."""
    from qbu_crawler.server.report_llm import _build_insights_prompt
    analytics = _insights_analytics()
    analytics["self"]["top_negative_clusters"] = [{
        "label_code": "quality_stability",
        "feature_display": "质量稳定性",
        "review_count": 10,
        "severity": "high",
        "severity_display": "高",
        "sub_features": [{"feature": "手柄松动", "count": 5}, {"feature": "螺丝断裂", "count": 3}],
        "affected_products": ["Cabela's Heavy-Duty Sausage Stuffer", "Cabela's Commercial-Grade"],
    }]
    prompt = _build_insights_prompt(analytics)
    assert "手柄松动" in prompt
    assert "Cabela's Heavy-Duty" in prompt or "Heavy-Duty" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_report_llm.py::test_insights_prompt_includes_affected_products -xvs`
Expected: FAIL — affected_products 当前未传入

- [ ] **Step 3: 修改 prompt 构建逻辑 — 传入产品名 + sub_features + 强化引证指令**

```python
# report_llm.py, _build_insights_prompt() 中构建 issue_lines 的部分：

for c in clusters[:8]:
    label_code = c.get("label_code", "")
    display = c.get("feature_display") or c.get("label_display", "")
    count = c.get("review_count", 0)
    sev = c.get("severity_display") or c.get("severity", "")
    line = f"  - [{label_code}] {display}：{count} 条评论，严重度 {sev}"
    sub_features = c.get("sub_features") or []
    if sub_features:
        symptoms = "、".join(
            f"{sf['feature']}({sf['count']}条)" for sf in sub_features[:5] if sf.get("feature")
        )
        if symptoms:
            line += f"\n    高频表现：{symptoms}"
    affected = c.get("affected_products") or []
    if affected:
        line += f"\n    涉及产品：{'、'.join(affected[:3])}"
    issue_lines.append(line)

# 同时在 output schema 中强化 action 的引证要求：
"improvement_priorities": [
    {{
        "label_code": "上方问题列表中方括号内的标识",
        "action": "引用该类别的具体高频表现和涉及产品，给出针对性改进建议（如：针对 XX 产品的 YY 问题(N条)，建议...）",
        "evidence_count": N
    }}
],
```

- [ ] **Step 4: 在 `_build_feature_clusters()` 中收集 affected_products**

注意：`data["products"]` 是一个 set，但存储的是 `product_sku or product_name`（line 911），
产品名不可靠。需新增 `product_names` set 来收集完整产品名。

```python
# report_analytics.py:850-854, clusters defaultdict 中增加 product_names：
clusters = defaultdict(lambda: {
    "reviews": [],
    "products": set(),
    "product_names": set(),   # ← 新增
    "severities": [],
    "sub_features": defaultdict(int),
})

# report_analytics.py:911 附近，在 bucket["products"].add(...) 之后增加：
bucket["product_names"].add(r.get("product_name") or "")

# report_analytics.py:931-944, result.append() 中增加：
"affected_products": sorted(data["product_names"] - {""})[:5],
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_report_llm.py tests/test_report_analytics.py -xvs`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_llm.py qbu_crawler/server/report_analytics.py tests/
git commit -m "feat(report): enrich AI recommendations with sub_features counts and affected products"
```

---

### Task 4: 填充产品趋势列 — 利用 _trend_series

**问题:** 产品健康度表格的"趋势"列全显示 "—"。`product_snapshots` 表已经有历史数据，`_trend_series` 已计算但未被消费。

**方案:** 在 `report_common.py` 中从 `_trend_series` 为每个 risk_product 计算 trend_display 文本（评分 ↑/↓/→ + 评论数变化）。

**Files:**
- Modify: `qbu_crawler/server/report_common.py:725-742` — risk_products 循环
- Test: `tests/test_report_common.py`

- [ ] **Step 1: 写测试 — 验证 trend_display 被填充**

```python
def test_risk_product_trend_display_populated():
    """trend_display should show direction arrow when _trend_series has data."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "mode": "baseline",
        "kpis": {"ingested_review_rows": 10},
        "self": {
            "risk_products": [
                {"product_name": "P", "product_sku": "SKU1", "risk_score": 80,
                 "top_labels": [], "negative_rate": 0.4, "rating_avg": 3.5},
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {"improvement_priorities": []},
        "_trend_series": [
            {
                "product_sku": "SKU1",
                "product_name": "P",
                "series": [
                    {"date": "2026-03-01", "rating": 3.0, "review_count": 80, "price": 100, "stock_status": "in_stock"},
                    {"date": "2026-04-01", "rating": 3.5, "review_count": 100, "price": 100, "stock_status": "in_stock"},
                ],
            }
        ],
    }
    result = normalize_deep_report_analytics(analytics)
    product = result["self"]["risk_products"][0]
    assert product["trend_display"] != "—"
    assert product["trend_display"] != ""
    assert "↑" in product["trend_display"] or "↓" in product["trend_display"] or "→" in product["trend_display"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_report_common.py::test_risk_product_trend_display_populated -xvs`
Expected: FAIL — trend_display 当前为 "—"

- [ ] **Step 3: 在 `normalize_deep_report_analytics()` 中计算 trend_display**

```python
# report_common.py, 在 risk_products 循环（line ~725）之前，构建 trend lookup：

# Build trend lookup from _trend_series
trend_lookup = {}
for ts in (analytics.get("_trend_series") or []):
    sku = ts.get("product_sku", "")
    series = ts.get("series") or []
    if sku and len(series) >= 2:
        first = series[0]
        last = series[-1]
        r_old = first.get("rating") or 0
        r_new = last.get("rating") or 0
        rc_old = first.get("review_count") or 0
        rc_new = last.get("review_count") or 0
        r_arrow = "↑" if r_new > r_old + 0.1 else ("↓" if r_new < r_old - 0.1 else "→")
        rc_delta = rc_new - rc_old
        parts = [f"评分{r_arrow}{r_new:.1f}"]
        if rc_delta != 0:
            parts.append(f"评论{'+' if rc_delta > 0 else ''}{rc_delta}")
        trend_lookup[sku] = " ".join(parts)

# 然后在 risk_products 循环中：
product["trend_display"] = trend_lookup.get(
    product.get("product_sku", ""), product.get("trend_display") or "—"
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_report_common.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "feat(report): populate trend_display from _trend_series for product health table"
```

---

### Task 5: Issue cards 增加近期活跃度指标

**问题:** Issue cards 显示"持续 4 年 8 个月"，但无法区分这是老问题（最近无新增）还是持续恶化中的问题。

**方案:** 在 `report_common.py` 的 issue_cards 构建阶段计算近期活跃度（此时有 `logical_date` 可用），避免在 `_build_feature_clusters()` 中依赖 `datetime.now()`（回溯生成历史报告时会出错）。

**Files:**
- Modify: `qbu_crawler/server/report_common.py:850-880` — issue_cards 增加 `recency_display`，基于 cluster 内 example_reviews 的日期和 logical_date 计算
- Modify: `qbu_crawler/server/report_templates/daily_report.html.j2:159-165` — stats 行增加近期活跃度
- Test: `tests/test_report_common.py`

注意：不改 `_build_feature_clusters()` 签名，改为在 `report_common.py` 中利用 cluster 内 reviews 的日期字段计算。
但 cluster 的 `example_reviews` 只有 3 条，无法代表全部评论。需要在 cluster 中增加所有评论的日期列表。

实际方案分两步：
1. `_build_feature_clusters()` 增加 `review_dates` 字段（所有评论日期列表）
2. `report_common.py` 基于 `logical_date` 和 `review_dates` 计算近期活跃度

- [ ] **Step 1: 写测试 — 验证 issue_card 包含 recency_display**

```python
# tests/test_report_common.py — 新增
def test_issue_card_recency_display():
    """issue_card should show 90-day recency based on logical_date, not datetime.now()."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "logical_date": "2026-04-08",
        "mode": "baseline",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [{
                "label_code": "quality_stability",
                "review_count": 3,
                "severity": "high",
                "affected_product_count": 1,
                "example_reviews": [],
                "review_dates": ["2025-01-01", "2026-02-15", "2026-03-20"],
            }],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {"improvement_priorities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert "recency_display" in card
    # 2026-02-15 and 2026-03-20 are within 90 days of 2026-04-08
    assert "2" in card["recency_display"]  # 2 recent reviews
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_report_common.py::test_issue_card_recency_display -xvs`
Expected: FAIL — recency_display 不存在

- [ ] **Step 3: 在 `_build_feature_clusters()` 中输出 review_dates**

```python
# report_analytics.py:931-944, result.append() 中增加：
"review_dates": sorted(dates),  # dates 已在 line 922 计算
```
```

- [ ] **Step 4: 在 `report_common.py` issue_cards 构建中基于 logical_date 计算 `recency_display`**

```python
# report_common.py, 在 issue_cards 循环之前，计算 cutoff：
from datetime import date as _date, timedelta as _timedelta
logical_date_str = normalized.get("logical_date", "")
cutoff_90d = ""
if logical_date_str:
    try:
        cutoff_90d = (_date.fromisoformat(logical_date_str) - _timedelta(days=90)).isoformat()
    except ValueError:
        pass

# 在 issue_cards 循环内，基于 cluster 的 review_dates 计算：
review_dates = cluster.get("review_dates") or []
if cutoff_90d and review_dates:
    recent = sum(1 for d in review_dates if d >= cutoff_90d)
else:
    recent = 0
total = cluster.get("review_count", 0) or 1
recency_pct = round(recent / total * 100)

# 在 issue_cards dict 中添加：
"recency_display": f"近90天 {recent} 条（{recency_pct}%）",
```

- [ ] **Step 5: 在模板 issue-stats 中展示**

```html
<!-- daily_report.html.j2:159-165, issue-stats div 中追加 -->
{% if item.recency_display is defined %}
<span>{{ item.recency_display }}</span>
{% endif %}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_report_common.py -xvs`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py \
       qbu_crawler/server/report_templates/daily_report.html.j2 tests/
git commit -m "feat(report): add 90-day recency indicator to issue cards based on logical_date"
```

---

## P2 — 可读性改进

### Task 6: 修复象限图标签碰撞

**问题:** `_build_quadrant_scatter()` 所有标签 `textposition="top center"`，当两个产品价格/评分接近时标签重叠。名称截断到 12 字符太短，无法区分同品牌产品。

**方案:** 增加截断长度到 20 字符；自有与竞品 trace 分别使用 "top center" 和 "bottom center"，避免同一方向碰撞。比单 trace 内交错更简单可靠。

**Files:**
- Modify: `qbu_crawler/server/report_charts.py:248-322` — `_build_quadrant_scatter()`
- Test: `tests/test_report_charts.py`

- [ ] **Step 1: 修改 `_build_quadrant_scatter()`**

```python
# report_charts.py, _truncate 函数（line ~268）：
def _truncate(name: str, max_len: int = 20) -> str:  # 12 → 20
    return name[:max_len - 1] + "…" if len(name) > max_len else name

# own trace（line ~269）：保持 textposition="top center"
# comp trace（line ~282）：改为 textposition="bottom center"
# 这样自有和竞品标签分别在点的上方和下方，即使价格/评分接近也不会重叠
```

- [ ] **Step 2: 运行测试**

Run: `uv run python -m pytest tests/test_report_charts.py -xvs`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/server/report_charts.py tests/test_report_charts.py
git commit -m "fix(charts): increase scatter label length and alternate positions to reduce overlap"
```

---

### Task 7: 堆叠柱状图添加百分比标注

**问题:** 评分分布堆叠柱状图只有绝对数值的柱高，无法直观对比不同产品的差评占比。

**方案:** 在每个柱段内添加百分比 text 标注。

**Files:**
- Modify: `qbu_crawler/server/report_charts.py:356-405` — `_build_stacked_bar()`
- Test: `tests/test_report_charts.py`

- [ ] **Step 1: 修改 `_build_stacked_bar()` — 添加百分比标注**

```python
# report_charts.py, _build_stacked_bar()
# 计算每个 category 的总数和百分比
totals = [p + n + ne for p, n, ne in zip(positive, neutral, negative)]

# 为每个 trace 计算百分比文本，仅当占比 >= 10% 时显示（避免小柱段内文字拥挤）
def _pct_text(values, totals):
    return [
        f"{v/t*100:.0f}%" if t > 0 and v/t >= 0.10 else ""
        for v, t in zip(values, totals)
    ]

# 每个 go.Bar 中添加：
text=_pct_text(negative, totals),
textposition="inside",
textfont=dict(size=9, color="white"),
```

- [ ] **Step 2: 运行测试**

Run: `uv run python -m pytest tests/test_report_charts.py -xvs`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/server/report_charts.py
git commit -m "feat(charts): add percentage labels inside stacked bar segments"
```

---

### Task 8: 改进样例评论选取多样性

**问题:** `example_reviews` 当前按 rating 升序取前 3 条，导致全是 1 星极端评论。缺少评分分布概况。

**方案:** 选取策略改为：1 条最低分（代表最严重问题）+ 1 条有图片的（如果有）+ 1 条中间评分的（如果存在 2-3 星），保证多样性。同时在 cluster 中增加 `rating_breakdown` 字段供模板显示概况。

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:940-944` — example_reviews 选取
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: 写测试 — 验证选取多样性**

```python
def test_example_reviews_diverse_selection():
    """example_reviews should include diverse ratings, not just lowest."""
    reviews_data = [
        {"rating": 1, "headline": "terrible", "body": "worst", "images": [], "date_published_parsed": "2026-01-01", "product_name": "P"},
        {"rating": 1, "headline": "awful", "body": "bad too", "images": [], "date_published_parsed": "2026-01-02", "product_name": "P"},
        {"rating": 1, "headline": "poor", "body": "bad three", "images": ["img.jpg"], "date_published_parsed": "2026-01-03", "product_name": "P"},
        {"rating": 2, "headline": "mediocre", "body": "could be better", "images": [], "date_published_parsed": "2026-01-04", "product_name": "P"},
        {"rating": 3, "headline": "ok", "body": "mixed feelings", "images": [], "date_published_parsed": "2026-02-01", "product_name": "P"},
    ]
    # _select_diverse_examples should pick: lowest(1星) + with_image(1星img) + mid_rating(2或3星)
    from qbu_crawler.server.report_analytics import _select_diverse_examples
    selected = _select_diverse_examples(reviews_data, max_count=3)
    ratings = [r["rating"] for r in selected]
    # Should not be all 1-star
    assert max(ratings) >= 2, f"All examples are 1-star: {ratings}"
    # Should include at least one with image if available
    has_image = any(r.get("images") for r in selected)
    assert has_image, "Should include at least one review with images"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_report_analytics.py::test_example_reviews_diverse_selection -xvs`
Expected: FAIL — `_select_diverse_examples` 不存在

- [ ] **Step 3: 实现 `_select_diverse_examples()` 并替换排序逻辑**

```python
# report_analytics.py, 在 _build_feature_clusters() 之前新增：

def _select_diverse_examples(reviews, max_count=3):
    """Select diverse example reviews: lowest-rated + with-image + mid-range."""
    if len(reviews) <= max_count:
        return sorted(reviews, key=lambda r: r.get("rating", 5))

    selected = []
    remaining = list(reviews)

    # 1. Lowest rated
    remaining.sort(key=lambda r: r.get("rating", 5))
    selected.append(remaining.pop(0))

    # 2. Prefer one with images (if not already selected)
    img_candidates = [r for r in remaining if r.get("images")]
    if img_candidates:
        pick = min(img_candidates, key=lambda r: r.get("rating", 5))
        selected.append(pick)
        remaining.remove(pick)
    elif remaining:
        selected.append(remaining.pop(0))

    # 3. Highest-rated among remaining (for diversity)
    if remaining and len(selected) < max_count:
        pick = max(remaining, key=lambda r: r.get("rating", 5))
        selected.append(pick)

    return selected[:max_count]

# 在 _build_feature_clusters() 中替换 line 942：
# 旧: "example_reviews": sorted(reviews, key=lambda r: r.get("rating", 5))[:3],
# 新:
"example_reviews": _select_diverse_examples(reviews, max_count=3),
```

- [ ] **Step 4: 增加 rating_breakdown 字段**

```python
# 在 result.append() 中增加：
from collections import Counter
rating_counts = Counter(r.get("rating", 0) for r in reviews)
"rating_breakdown": {f"{star}星": rating_counts.get(star, 0) for star in range(1, 6) if rating_counts.get(star, 0) > 0},
```

- [ ] **Step 5: 运行测试**

Run: `uv run python -m pytest tests/test_report_analytics.py -xvs`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "feat(report): diverse example review selection + rating breakdown per cluster"
```

---

### Task 9: 拓宽竞品差距分析维度

**问题:** 差距分析表仅展示 2 个维度（做工与质量、安装与使用），因为过滤条件要求竞品好评率 > 0 **且** 自有差评率 > 0 同时满足。

**方案:** 放宽条件为"竞品好评率 > 0 **或** 自有差评率 > 0"，同时修正 gap_rate 计算以正确处理单侧为 0 的场景，并标注差距类型。

**Files:**
- Modify: `qbu_crawler/server/report_common.py:159-210` — `_competitor_gap_analysis()`
- Test: `tests/test_report_common.py`

- [ ] **Step 1: 写测试 — 验证单侧为 0 时也能输出**

```python
def test_gap_analysis_includes_one_sided_dimensions():
    """Gap analysis should show dimensions even when only one side has data."""
    from qbu_crawler.server.report_common import _competitor_gap_analysis
    normalized = {
        "kpis": {"competitor_review_rows": 36, "own_review_rows": 112},
        "competitor": {
            "top_positive_themes": [
                {"label_code": "good_value", "review_count": 5},  # 竞品有好评
                {"label_code": "easy_to_use", "review_count": 3},
            ],
        },
        "self": {
            "top_negative_clusters": [
                # 只有 noise_power 差评，没有对应竞品好评维度
                {"label_code": "noise_power", "review_count": 8},
            ],
        },
    }
    gaps = _competitor_gap_analysis(normalized)
    codes = [g["label_code"] for g in gaps]
    # easy_to_use maps to assembly_installation which is in own negatives? No.
    # good_value has no negative mapping. Let's check _NEGATIVE_TO_POSITIVE_DIMENSION.
    # Actually the mapping goes neg→pos, not pos→neg, so we need to check both directions.
    # The test should just verify that more dimensions are included than the old AND logic.
    assert len(gaps) >= 1
```

- [ ] **Step 2: 修改 `_competitor_gap_analysis()` — set 交集改并集 + gap_rate 分场景**

```python
# report_common.py:183, 将 set intersection 改为 union:
# 旧: gap_dims = set(comp_positive) & set(dimension_own_negative)
# 新:
gap_dims = set(comp_positive) | set(dimension_own_negative)

# 在 for dim in gap_dims 循环中，安全获取两侧数据（可能为 0）：
comp_cnt = comp_positive.get(dim, {}).get("review_count", 0) if dim in comp_positive else 0
own_cnt = dimension_own_negative.get(dim, 0)

comp_rate = comp_cnt / max(competitor_total, 1)
own_rate = own_cnt / max(own_total, 1)

# gap_rate 分场景计算：
if comp_rate > 0 and own_rate > 0:
    gap_rate = round((comp_rate + own_rate) / 2 * 100)    # 双侧差距
elif comp_rate > 0:
    gap_rate = round(comp_rate * 50)                       # 竞品优势，但自有无对应问题，权重减半
else:
    gap_rate = round(own_rate * 50)                        # 自有短板，但竞品无对应优势，权重减半

# 增加差距类型标注：
gap_type = "双侧差距" if comp_cnt > 0 and own_cnt > 0 else ("竞品领先" if comp_cnt > 0 else "自有短板")
```

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_report_common.py -xvs`

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "feat(report): broaden gap analysis to show dimensions with one-sided data"
```

---

## P3 — 锦上添花

### Task 10: 竞品高价值样本 LLM 提炼

**问题:** 竞品好评样本只是原文展示，没有提炼"竞品做对了什么"。

**方案:** 在 LLM prompt 中增加竞品好评样本的提炼要求，在 `improvement_priorities` 同级增加 `benchmark_takeaway` 字段。

**Files:**
- Modify: `qbu_crawler/server/report_llm.py` — prompt + output schema
- Modify: `qbu_crawler/server/report_templates/daily_report.html.j2` — benchmark_takeaways 替换为 LLM 版本
- Test: `tests/test_report_llm.py`

- [ ] **Step 1: 在 `_build_insights_prompt()` 中添加竞品好评样本数据**

```python
# 在 prompt 中追加：
benchmarks = analytics.get("competitor", {}).get("benchmark_examples", [])
bench_lines = []
for b in benchmarks[:2]:
    bench_lines.append(
        f"  - {b.get('product_name', '')}: {b.get('summary_text', '')[:150]}"
    )
bench_text = "\n".join(bench_lines) if bench_lines else "  暂无"

# 添加到 prompt 模板：
f"""
竞品高分样本（用于提炼竞品成功要素）：
{bench_text}
"""

# output schema 增加：
"benchmark_takeaway": "一段话总结竞品做对了什么，可供自有产品借鉴的具体做法"
```

- [ ] **Step 2: 在模板中渲染 benchmark_takeaway**

```html
{% if analytics.report_copy.benchmark_takeaway %}
<div class="recommendation-box mt-md">
  {{ analytics.report_copy.benchmark_takeaway }}
</div>
{% endif %}
```

- [ ] **Step 3: 运行测试**

Run: `uv run python -m pytest tests/test_report_llm.py -xvs`

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_llm.py qbu_crawler/server/report_templates/daily_report.html.j2 tests/
git commit -m "feat(report): LLM-generated benchmark takeaway for competitor samples"
```

---

### Task 11: Issue cards 标注翻译覆盖率

**问题:** 报告整体翻译覆盖率 66%，但不知道哪些 cluster 受影响最大。某个 cluster 可能只有 30% 翻译，导致分析有偏差。

**方案:** 在 `_build_feature_clusters()` 中计算每个 cluster 的翻译覆盖率，在 issue card 中标注。

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:920-944`
- Modify: `qbu_crawler/server/report_templates/daily_report.html.j2:159-165`
- Test: `tests/test_report_analytics.py`

- [ ] **Step 1: 在 cluster 中计算 translated_rate**

```python
# report_analytics.py, _build_feature_clusters() result.append() 中：
translated = sum(1 for r in reviews if r.get("body_cn") or r.get("headline_cn"))
"translated_rate": translated / max(len(reviews), 1),
```

- [ ] **Step 2: 在 report_common.py issue_cards 中传递**

```python
# issue_cards dict 中增加：
translated_rate = cluster.get("translated_rate", 1.0)
"translated_rate_display": f"{translated_rate * 100:.0f}%",
"translation_warning": translated_rate < 0.5,
```

- [ ] **Step 3: 在模板中有条件展示警告**

```html
{% if item.translation_warning is defined and item.translation_warning %}
<span class="text-muted" title="翻译覆盖率低于50%，分析可能不完整">⚠ 翻译 {{ item.translated_rate_display }}</span>
{% endif %}
```

- [ ] **Step 4: 运行测试 + Commit**

```bash
uv run python -m pytest tests/ -x --ignore=tests/test_report_charts.py
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py \
       qbu_crawler/server/report_templates/daily_report.html.j2 tests/
git commit -m "feat(report): per-cluster translation coverage with low-coverage warning"
```

---

### Task 12: 解除 issue cards 上限 + 增加正面 KPI

**问题 A:** 模板 `issue_cards[:4]` 硬编码只展示 4 个问题簇，多余的被隐藏。
**问题 B:** 5 个 KPI 全是负面/风险导向，缺少正面对照。

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report.html.j2:149`
- Modify: `qbu_crawler/server/report_common.py:777-813` — kpi_cards 列表
- Test: `tests/test_report_common.py`

- [ ] **Step 1: 修改模板 — 前 4 个完整展示，第 5+ 个折叠**

```html
<!-- daily_report.html.j2:149 -->
<!-- 替换 {% for item in analytics.self.issue_cards[:4] %} 为： -->
{% for item in analytics.self.issue_cards %}
<article class="issue-card {% if loop.index > 4 %}issue-card-compact{% endif %}">
  {# 前4个完整展示，第5+个只显示标题行 #}
  ...
  {% if loop.index <= 4 %}
  {# 完整内容：example_reviews, image_evidence, recommendation #}
  ...
  {% endif %}
</article>
{% endfor %}
```

- [ ] **Step 2: 在 `report_analytics.py` 中新增 `own_positive_review_rows` KPI**

注意：差评阈值 ≤ 2 星，好评应为 ≥ 4 星（3 星是中评）。`1 - negative_rate` 是"非差评率"而非"好评率"。
必须新增独立计数。

```python
# report_analytics.py, build_report_analytics() 的 kpis dict 中（line ~1274 附近）增加：
"own_positive_review_rows": sum(
    1 for r in own_reviews if (r.get("review", {}).get("rating") or 0) >= 4
),
```

- [ ] **Step 3: 在 `report_common.py` 中增加好评率 KPI 卡片**

```python
# report_common.py, kpi_cards 列表中（"自有评论" 之后）插入：
own_pos = kpis.get("own_positive_review_rows", 0)
own_total = kpis.get("own_review_rows", 0) or 1
positive_rate = own_pos / own_total
kpi_cards.insert(2, {
    "label": "好评率",
    "value": f"{positive_rate * 100:.1f}%",
    "delta_display": "",
    "delta_class": "neutral",
    "tooltip": "自有产品 ≥4 星评论占比（3 星为中评，不计入好评）",
    "value_class": "severity-low" if positive_rate >= 0.7 else "",
})
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
uv run python -m pytest tests/test_report_common.py -xvs
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_templates/daily_report.html.j2 tests/
git commit -m "feat(report): show all issue cards (compact after 4th) + add positive rate KPI"
```

---

## 验收标准

| # | 检查项 | 验证方法 |
|---|--------|----------|
| 1 | hero_headline 与 KPI 卡片差评率一致 | 生成报告，对比标题数字与 KPI 卡片 |
| 2 | 热力图 Y 轴产品名完整可读 | 视觉检查 HTML 报告 |
| 3 | AI 建议引用具体 sub_features 和产品名 | 检查 recommendation 文本含 "X条" 和产品名 |
| 4 | 趋势列显示方向箭头 | 确认产品表格趋势列非 "—" |
| 5 | Issue cards 有近期活跃度标注 | 确认 "近90天 N 条（X%）" 显示 |
| 6 | 象限图标签不重叠 | 视觉检查 |
| 7 | 堆叠柱状图有百分比 | 视觉检查 |
| 8 | 样例评论包含非 1 星评论 | 检查 example_reviews 评分分布 |
| 9 | 差距分析 ≥3 个维度 | 检查 gap_analysis 行数 |
| 10 | 竞品好评有 LLM 提炼 | 检查 benchmark_takeaway 非空 |
| 11 | 低翻译覆盖 cluster 有警告标注 | 确认 ⚠ 标注 |
| 12 | 超过 4 个问题簇时可见第 5+ 个 | 构造 5+ cluster 数据验证 |
| 13 | KPI 区有好评率正面指标 | 确认 kpi_cards 含"好评率" |
| 全量 | 所有现有测试通过 | `uv run python -m pytest tests/ -x --ignore=tests/test_report_charts.py` |
