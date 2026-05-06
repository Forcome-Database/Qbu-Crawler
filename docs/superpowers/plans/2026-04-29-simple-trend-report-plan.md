# 历史口径变化趋势页 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“变化趋势”页改为基于历史库的清晰趋势工作台，支持近7天、近30天、近12个月和四个业务维度切换。

**Architecture:** 保留当前 V3 报告整体模板和顶层 `trend_digest` 契约，不新增平行的 `simple_trend_digest`。新增历史趋势查询函数，以报告 `data_until` 为截止点读取评论历史和产品状态历史；`trend_digest` 内新增 `workspace` 结构供新模板消费，旧 `primary_chart + drill_downs` 作为兼容 fallback 保留。

**Tech Stack:** Python、SQLite、Jinja2、Chart.js、pytest、Playwright CLI。

---

## File Structure

- `qbu_crawler/server/report.py`
  - 新增历史趋势查询函数，负责按报告截止时间读取历史评论和产品状态。
- `qbu_crawler/models.py`
  - 新增或扩展产品历史查询函数，支持 `until` 锚点，避免使用 `datetime('now')`。
- `qbu_crawler/server/report_analytics.py`
  - 新增历史趋势工作台 builder，把历史评论和产品状态聚合成 `trend_digest.workspace`。
- `qbu_crawler/server/report_snapshot.py`
  - full report 生成时把历史趋势输入传给 analytics，确保 `REPORT_PERSPECTIVE=window` 也能展示历史趋势。
- `qbu_crawler/server/report_charts.py`
  - 为 `trend_digest.workspace` 生成 Chart.js 配置。
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
  - 趋势页优先消费 `trend_digest.workspace`，缺失时回退旧结构。
- `qbu_crawler/server/report_templates/daily_report_v3.css`
  - 趋势工作台布局和状态样式。
- `qbu_crawler/server/report_templates/daily_report_v3.js`
  - 趋势页时间和维度切换，不再展示无真实数据支撑的按钮。
- `tests/server/test_historical_trend_queries.py`
  - 锁定历史查询截止时间、未来数据隔离和跨站点 SKU 不串数据。
- `tests/server/test_historical_trend_digest.py`
  - 锁定四维度趋势数据口径。
- `tests/server/test_historical_trend_template.py`
  - 锁定 HTML 展示、新旧 fallback 禁词和默认面板。
- `tests/server/test_attachment_html_trends.py`
  - 更新现有趋势页回归。

---

## Chunk 1: 历史查询层

### Task 1: 查询历史评论时按报告截止时间截断

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_historical_trend_queries.py`

- [ ] **Step 1: 写失败测试**

新增测试：构造四条评论，一条在当前窗口内，一条在前30天内，一条发布时间在 `data_until` 之后，一条发布时间早但 `scraped_at` 在 `data_until` 之后。断言历史趋势查询只返回报告截止时间之前已经入库、且发布时间不晚于报告截止时间的数据。

```python
def test_query_trend_history_reviews_excludes_future_rows(tmp_path, monkeypatch):
    # arrange: 初始化测试 DB，插入 own / competitor 产品和三条评论
    products, reviews = report.query_trend_history(
        until="2026-04-30T00:00:00+08:00",
        lookback_days=730,
    )

    assert {r["headline"] for r in reviews} == {"current", "previous"}
    assert all(str(r["date_published_parsed"]) < "2026-04-30" for r in reviews)
    assert all(str(r["scraped_at"]) < "2026-04-30 00:00:00" for r in reviews)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_query_trend_history_reviews_excludes_future_rows -q`

Expected: `AttributeError: module 'qbu_crawler.server.report' has no attribute 'query_trend_history'`

- [ ] **Step 3: 实现 `query_trend_history()`**

在 `report.py` 新增：

```python
def query_trend_history(until, lookback_days=730):
    until_str = _report_ts(until)
    conn = models.get_conn()
    try:
        products = [dict(row) for row in conn.execute(
            """
            SELECT DISTINCT
                   p.url, p.name, p.sku, p.site, p.ownership
            FROM products p
            JOIN product_snapshots ps ON ps.product_id = p.id
            WHERE ps.scraped_at < ?
            ORDER BY p.site, p.ownership, p.sku
            """,
            (until_str,),
        ).fetchall()]
        reviews = _query_reviews_with_latest_analysis_for_trend(conn, until_str, lookback_days)
        return products, reviews
    finally:
        conn.close()
```

实现内部 SQL 时：

- JOIN `products`
- LEFT JOIN 最新 `review_analysis`
- SELECT 字段至少包含：`id`、`product_name`、`product_sku`、`product_url`、`site`、`ownership`、`scraped_at`、`headline`、`body`、`rating`、`date_published`、`date_published_parsed`、`images`、`headline_cn`、`body_cn`、`translate_status`、`sentiment`、`sentiment_score`、`analysis_labels`、`analysis_features`、`analysis_insight_cn`、`analysis_insight_en`、`impact_category`、`failure_mode`
- `r.scraped_at < ?`，保证旧报告回放不会读到未来才采集入库的历史评论
- `COALESCE(r.date_published_parsed, substr(r.date_published, 1, 10)) IS NOT NULL`
- `datetime(COALESCE(r.date_published_parsed, substr(r.date_published, 1, 10))) < datetime(?)`，避免 `data_until` 不是零点时误删截止日当天已发布评论
- `datetime(COALESCE(r.date_published_parsed, substr(r.date_published, 1, 10))) >= datetime(?, ?)`，第二个参数传 `f"-{lookback_days} days"`
- 趋势分桶用发布时间，不用 `r.scraped_at`
- `products` 返回值只作为 SKU / 名称 / 归属身份列表，不作为产品趋势指标来源

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_query_trend_history_reviews_excludes_future_rows -q`

Expected: PASS

### Task 2: 产品历史查询支持 `until` 锚点

**Files:**
- Modify: `qbu_crawler/models.py`
- Test: `tests/server/test_historical_trend_queries.py`

- [ ] **Step 1: 写失败测试**

新增测试：同一个产品有三条产品历史记录，其中一条在报告日之后；另有一条不同站点 / 不同 URL 但 SKU 相同的记录。断言新查询不会读到未来记录，也不会把跨站点同 SKU 记录混进来。

```python
def test_get_product_snapshots_until_excludes_future_rows_and_same_sku_other_site(tmp_path, monkeypatch):
    rows = models.get_product_snapshots_until(
        product_url="https://example.com/product-1",
        until="2026-04-30T00:00:00+08:00",
        days=30,
    )

    assert [row["scraped_at"][:10] for row in rows] == ["2026-04-15", "2026-04-29"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_get_product_snapshots_until_excludes_future_rows -q`

Expected: `AttributeError: module 'qbu_crawler.models' has no attribute 'get_product_snapshots_until'`

- [ ] **Step 3: 实现 `get_product_snapshots_until()`**

在 `models.py` 中新增函数，不改动现有 `get_product_snapshots()`：

```python
def get_product_snapshots_until(product_url=None, until=None, days=30, sku=None, site=None):
    if hasattr(until, "tzinfo") and until.tzinfo is not None:
        until_str = until.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    else:
        until_str = str(until).replace("T", " ")[:19]
    where = ["ps.scraped_at < ?", "ps.scraped_at >= datetime(?, ? || ' days')"]
    params = [until_str, until_str, f"-{days}"]
    if product_url:
        where.insert(0, "p.url = ?")
        params.insert(0, product_url)
    else:
        where.insert(0, "p.sku = ?")
        params.insert(0, sku)
        if site:
            where.insert(1, "p.site = ?")
            params.insert(1, site)
    conn = get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT ps.price, ps.stock_status, ps.review_count, ps.rating,
                   ps.ratings_only_count, ps.scraped_at
            FROM product_snapshots ps
            JOIN products p ON ps.product_id = p.id
            WHERE {' AND '.join(where)}
            ORDER BY ps.scraped_at ASC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
```

该函数可以在内部做最小时间格式处理，不新增通用抽象；如果调用方有 `product_url`，优先用 `product_url` 查询，避免 SKU 跨站点串数据；如果只有 SKU，则可同时传 `site` 缩小范围。需要 `timezone/timedelta` 时，复用 `models.py` 文件顶部已有的 datetime imports。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_get_product_snapshots_until_excludes_future_rows -q`

Expected: PASS

### Task 3: 构建按报告截止时间锚定的产品历史 series

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_historical_trend_queries.py`

- [ ] **Step 1: 写失败测试**

断言新产品趋势 series 使用 `get_product_snapshots_until()`，不会继续走旧的 `_build_trend_data()` / `datetime('now')` 口径。

```python
def test_build_historical_product_trend_series_uses_report_until(monkeypatch):
    called = {}

    def fake_get_product_snapshots_until(product_url=None, until=None, days=30, sku=None, site=None):
        called[(product_url, sku, site, until, days)] = True
        return [{"scraped_at": "2026-04-29 09:00:00", "rating": 4.1, "review_count": 10}]

    monkeypatch.setattr(models, "get_product_snapshots_until", fake_get_product_snapshots_until)

    series = report_analytics.build_historical_product_trend_series(
        [{"url": "https://example.com/product-1", "sku": "SKU-1", "site": "basspro", "name": "Product 1"}],
        until="2026-04-30T00:00:00+08:00",
        days=30,
    )

    assert called[("https://example.com/product-1", "SKU-1", "basspro", "2026-04-30T00:00:00+08:00", 30)]
    assert series[0]["series"][0]["date"] == "2026-04-29 09:00:00"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_build_historical_product_trend_series_uses_report_until -q`

Expected: `AttributeError`

- [ ] **Step 3: 实现 `build_historical_product_trend_series()`**

在 `report_analytics.py` 中新增公开的小函数：

```python
def build_historical_product_trend_series(products, until, days=365):
    result = []
    for product in products or []:
        sku = product.get("sku")
        product_url = product.get("url") or product.get("product_url")
        snapshots = models.get_product_snapshots_until(
            product_url=product_url,
            sku=sku,
            site=product.get("site"),
            until=until,
            days=days,
        ) if (product_url or sku) else []
        result.append({
            "product_name": product.get("name", ""),
            "product_sku": sku or "",
            "product_url": product_url or "",
            "site": product.get("site", ""),
            "ownership": product.get("ownership", ""),
            "series": [
                {
                    "date": s.get("scraped_at", ""),
                    "price": s.get("price"),
                    "rating": s.get("rating"),
                    "review_count": s.get("review_count"),
                    "ratings_only_count": s.get("ratings_only_count"),
                    "stock_status": s.get("stock_status"),
                }
                for s in snapshots
            ],
        })
    return result
```

保留旧 `_build_trend_data()` 给旧图表兼容，不把它用于新 `workspace`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_build_historical_product_trend_series_uses_report_until -q`

Expected: PASS

### Task 4: full / change / quiet 报告路径接入历史趋势输入

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_historical_trend_queries.py`
- Test: `tests/server/test_historical_report_paths.py`

- [ ] **Step 1: 写失败测试**

构造 `REPORT_PERSPECTIVE=window` 的 snapshot，`snapshot["reviews"]` 为空，但 DB 有历史评论。断言生成 analytics 后 `trend_digest.workspace` 有历史数据。

```python
def test_window_perspective_still_builds_historical_trends(monkeypatch):
    analytics = report_analytics.build_report_analytics(
        snapshot,
        trend_history={
            "products": history_products,
            "reviews": history_reviews,
            "product_series": history_product_series,
        },
    )

    assert analytics["trend_digest"]["workspace"]["data"]["month"]["reputation"]["status"] == "ready"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/server/test_historical_trend_queries.py::test_window_perspective_still_builds_historical_trends -q`

Expected: `TypeError` 或缺少 `workspace`

- [ ] **Step 3: 扩展 analytics 参数**

把 `build_report_analytics()` 签名改为：

```python
def build_report_analytics(snapshot, synced_labels=None, skip_delta=False, conn=None, trend_history=None):
```

不传 `trend_history` 时保持现有行为。

同时把 `build_dual_report_analytics()` 签名改为：

```python
def build_dual_report_analytics(snapshot, synced_labels=None, trend_history=None):
```

内部调用累积 analytics 时传入同一份 `trend_history`；窗口 analytics 仍不需要生成趋势工作台，避免“本次窗口趋势”和“历史趋势”混在一起。

- [ ] **Step 4: 增加报告路径历史趋势输入 helper**

在 `report_snapshot.py` 中新增内部 helper，full / change / quiet 路径共用：

```python
def _build_trend_history_for_snapshot(snapshot):
    until = snapshot.get("data_until") or f"{snapshot['logical_date']}T23:59:59+08:00"
    trend_products, trend_reviews = report.query_trend_history(until, lookback_days=730)
    product_series = report_analytics.build_historical_product_trend_series(
        trend_products,
        until=until,
        days=730,
    )
    return {
        "products": trend_products,
        "reviews": trend_reviews,
        "product_series": product_series,
        "until": until,
    }
```

- [ ] **Step 5: 在 full report 生成时传入历史**

在 `generate_full_report_from_snapshot()` 中，构建 analytics 前调用：

```python
trend_history = _build_trend_history_for_snapshot(snapshot)
```

然后传入 `build_dual_report_analytics()` 或 `build_report_analytics()`。

- [ ] **Step 6: 在 change / quiet 报告生成时传入历史**

`_generate_change_report()` 和 `_generate_quiet_report()` 当前也会构造 `cum_snapshot` 并调用 `build_report_analytics()`。这两个路径也要调用 `_build_trend_history_for_snapshot(snapshot)`，否则无新增评论或仅状态变化时趋势页仍会回退旧数据。

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_queries.py -q`

Expected: PASS

- [ ] **Step 8: 补充报告路径回归测试**

在 `tests/server/test_historical_report_paths.py` 中分别覆盖 full / change / quiet 三条路径：

- full：monkeypatch `report.query_trend_history()`，断言 `generate_full_report_from_snapshot()` 构建 analytics 时传入 `trend_history`
- change：构造只有产品状态变化的 snapshot，断言 `_generate_change_report()` 生成的 analytics 含 `trend_digest.workspace`
- quiet：构造无新增评论、无状态变化的 snapshot，断言 `_generate_quiet_report()` 生成的 analytics 含 `trend_digest.workspace`

Run: `uv run pytest tests/server/test_historical_report_paths.py -q`

Expected: PASS

---

## Chunk 2: 趋势工作台 digest

### Task 5: 在 `trend_digest` 内新增 `workspace`

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_historical_trend_digest.py`

- [ ] **Step 1: 写失败测试**

断言 `build_report_analytics()` 输出仍包含旧字段，同时新增工作台结构：

```python
def test_trend_digest_keeps_legacy_and_adds_workspace():
    analytics = build_report_analytics(snapshot, trend_history=trend_history)
    digest = analytics["trend_digest"]

    assert "primary_chart" in digest
    assert "drill_downs" in digest
    assert digest["workspace"]["views"] == ["week", "month", "year"]
    assert digest["workspace"]["dimensions"] == ["reputation", "issues", "products", "competition"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/server/test_historical_trend_digest.py::test_trend_digest_keeps_legacy_and_adds_workspace -q`

Expected: `KeyError: 'workspace'`

- [ ] **Step 3: 实现 `build_trend_workspace_digest()` 外壳**

在 `report_analytics.py` 中新增：

```python
def build_trend_workspace_digest(snapshot, trend_history, trend_product_series):
    return {
        "views": ["week", "month", "year"],
        "dimensions": ["reputation", "issues", "products", "competition"],
        "default_view": "month",
        "default_dimension": "reputation",
        "data": {...},
    }
```

把结果挂到现有 `trend_digest["workspace"]`，不要新增顶层 `simple_trend_digest`。

`trend_product_series` 必须来自 `trend_history["product_series"]`；不能复用 `_trend_series`，因为 `_trend_series` 当前通过 `_build_trend_data()` 使用 `datetime('now')`，会导致历史报告回放漂移。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_digest.py::test_trend_digest_keeps_legacy_and_adds_workspace -q`

Expected: PASS

### Task 6: 实现口碑趋势和明确对比窗口

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_historical_trend_digest.py`

- [ ] **Step 1: 写失败测试**

断言 `month/reputation`：

- 标题为 `近30天 / 口碑趋势`
- 主图 series 为 `自有平均评分`、`竞品平均评分`
- KPI 不超过 3 个
- 对比文案是 `较前30天`
- digest 内不出现 `上期`

- [ ] **Step 2: 实现口碑趋势**

按 `date_published_parsed` 聚合历史评论：

- week：当前7天和前7天
- month：当前30天和前30天
- year：当前12个月和前12个月

历史不足时：

```python
comparison = {
    "status": "insufficient_history",
    "label": "暂无足够历史对比",
}
```

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_digest.py::test_reputation_trend_uses_historical_reviews_and_explicit_comparison -q`

Expected: PASS

### Task 7: 实现问题趋势

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_historical_trend_digest.py`

- [ ] **Step 1: 写失败测试**

断言 `month/issues`：

- 主图是 Top 3 问题占比趋势
- KPI 为 `问题评论占比`、`Top 1 问题`、`影响产品数`
- 表格列为 `问题/当前评论数/占比/对比变化/影响 SKU`
- 只统计自有负面标签

- [ ] **Step 2: 实现问题趋势**

复用现有标签解析逻辑，统计同一 label code：

- 当前窗口问题评论数
- 当前窗口自有评论数
- 当前窗口影响 SKU 集合
- 前置窗口同 label code 的评论数

变化值没有前置窗口时显示“暂无足够历史对比”。

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_digest.py::test_issue_trend_uses_own_negative_labels_only -q`

Expected: PASS

### Task 8: 实现产品趋势

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/models.py`
- Test: `tests/server/test_historical_trend_digest.py`

- [ ] **Step 1: 写失败测试**

断言 `month/products`：

- KPI 为 `评分下降产品数`、`差评率上升产品数`、`评论增长但评分下降产品数`
- 表格不出现 `快照`
- 产品差评率变化来自历史评论聚合
- 未来产品历史记录不会进入计算

- [ ] **Step 2: 实现产品状态趋势**

产品评分和评论增长来自 `trend_history["product_series"]`，该 series 由 `get_product_snapshots_until()` 按报告 `data_until` 生成：

- 评分变化 = 窗口末值 - 窗口初值
- 评论增长数 = 窗口末值 review_count - 窗口初值 review_count

产品差评率来自历史评论：

- 当前窗口 SKU 差评率
- 前置窗口 SKU 差评率
- 两边都有样本时才计算差评率变化

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_digest.py::test_product_trend_combines_snapshots_and_review_history -q`

Expected: PASS

### Task 9: 实现竞品对比

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_historical_trend_digest.py`

- [ ] **Step 1: 写失败测试**

断言 `month/competition`：

- 主图是评分差趋势
- KPI 为 `当前评分差`、`差评率差`、`竞品优势主题 Top 1`
- 自有相关问题只匹配同 label code 或同 taxonomy category
- 没有匹配时显示 `暂无匹配`

- [ ] **Step 2: 实现竞品对比**

计算：

- 当前评分差 = 竞品均分 - 自有均分
- 差评率差 = 自有差评率 - 竞品差评率
- 竞品优势主题 = 竞品正向标签最高频主题

启示文案使用确定性规则：

- 有同 label code 自有负面问题：`优先对照该主题下的自有负面反馈复核体验短板`
- 只有同 category：`可参考竞品优势主题，回看同类自有问题`
- 无匹配：`暂无匹配`

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_digest.py::test_competition_trend_uses_deterministic_matching -q`

Expected: PASS

---

## Chunk 3: 模板和交互

### Task 10: Chart.js 配置支持 `trend_digest.workspace`

**Files:**
- Modify: `qbu_crawler/server/report_charts.py`
- Test: `tests/server/test_historical_trend_template.py`

- [ ] **Step 1: 写失败测试**

构造带 `trend_digest.workspace` 的 analytics，断言生成：

- `trend_workspace_month_reputation`
- `trend_workspace_month_issues`
- `trend_workspace_month_products`
- `trend_workspace_month_competition`

- [ ] **Step 2: 实现配置生成**

在 `build_chartjs_configs()` 中读取：

```python
workspace = (analytics.get("trend_digest") or {}).get("workspace") or {}
```

只为 `primary_chart.status == "ready"` 且有 labels / series 的面板生成图表配置。

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_template.py::test_chart_configs_include_trend_workspace -q`

Expected: PASS

### Task 11: 替换 V3 趋势页模板

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`
- Test: `tests/server/test_historical_trend_template.py`

- [ ] **Step 1: 写失败测试**

断言 HTML 中：

- 有 `近7天 / 近30天 / 近12个月`
- 有 `口碑趋势 / 问题趋势 / 产品趋势 / 竞品对比`
- 不出现 `快照`、`声浪`、`声量`、`上期`
- 默认面板是 `近30天 / 口碑趋势`
- 每个面板最多 3 个 KPI

- [ ] **Step 2: 实现模板优先消费 workspace**

趋势页逻辑：

```jinja2
{% set trend_workspace = (analytics.trend_digest or {}).workspace or {} %}
{% if trend_workspace.data %}
  渲染新工作台
{% else %}
  渲染旧 primary_chart + drill_downs
{% endif %}
```

- [ ] **Step 3: 实现切换 JS**

JS 只切换已经渲染的数据面板：

- `.trend-workspace-view-btn`
- `.trend-workspace-dimension-btn`
- `.trend-workspace-panel`

不要复用旧测试禁止的 class：`trend-view-btn`、`trend-subtab-btn`、`trend-panel`、`trend-toolbar`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/server/test_historical_trend_template.py tests/server/test_attachment_html_trends.py -q`

Expected: PASS

- [ ] **Step 5: 锁定旧 fallback 也不出现禁词**

补充一条没有 `trend_digest.workspace`、只有旧 `primary_chart + drill_downs` 的 HTML fixture，断言趋势区用户可见文本仍不出现：

- `快照`
- `声浪`
- `声量`
- `上期`

当前模板里存在 `vs 上期平均`，实现时必须改为明确窗口文案，例如 `较前30天` 或 `对比前30天平均`。

Run: `uv run pytest tests/server/test_historical_trend_template.py::test_legacy_trend_fallback_uses_allowed_words -q`

Expected: PASS

---

## Chunk 4: 回归和模拟验证

### Task 12: 更新现有趋势阈值测试

**Files:**
- Modify: `tests/server/test_trend_digest_thresholds.py`
- Modify: `tests/server/test_attachment_html_trends.py`
- Test: `tests/server/test_trend_digest_thresholds.py`
- Test: `tests/server/test_attachment_html_trends.py`

- [ ] **Step 1: 补充兼容断言**

现有 `build_trend_digest()` 测试继续断言旧结构存在，同时新增断言：没有 workspace 时旧结构仍可用。

- [ ] **Step 2: 更新旧模板路径禁用测试**

`tests/server/test_attachment_html_trends.py::test_trend_section_uses_primary_chart_data_source` 当前禁止模板访问 `trend_digest.data[...]`。新方案允许访问 `trend_digest.workspace.data`，但仍禁止回到旧 12 panel 的 `trend_digest.data[view][dimension]`。

把断言改成：

```python
assert "trend_digest.data[" not in template_source
assert "trend_digest.workspace" in template_source or ".workspace" in template_source
```

并补充一条 fixture：当 `trend_digest.workspace` 存在时，趋势区优先渲染工作台；当不存在时，旧 `primary_chart + drill_downs` 仍可渲染。

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/server/test_trend_digest_thresholds.py tests/server/test_attachment_html_trends.py -q`

Expected: PASS

- [ ] **Step 4: 更新旧断言中的“上期”预期**

`tests/server/test_attachment_html_trends.py::test_trend_section_shows_primary_chart_in_mature` 当前允许 `vs 上期平均`。改为只允许明确窗口文案：

```python
assert "对比前30天平均" in html or "较前30天" in html
assert "上期" not in html
```

Run: `uv run pytest tests/server/test_attachment_html_trends.py::test_trend_section_shows_primary_chart_in_mature -q`

Expected: PASS

### Task 13: 重新生成 30 天模拟报告并浏览器核验

**Files:**
- No code changes

- [ ] **Step 1: 运行 30 天模拟**

Run: `uv run python scripts\simulate_daily_report.py 30`

Expected: 输出新的 `daily-report-*/reports/workflow-run-30-full-report.html`

- [ ] **Step 2: 用 Playwright 打开报告**

通过本地 HTTP server 打开 HTML，点击 `变化趋势`。

检查：

- 默认是 `近30天 / 口碑趋势`
- 有一张趋势图
- KPI 不超过 3 个
- 表格可见
- 页面不出现 `快照`、`声浪`、`声量`、`上期`
- 近30天对比前30天历史不足时显示 `暂无足够历史对比`

- [ ] **Step 3: 保存截图**

保存到 `output/playwright/historical-trend-run30.png`。

- [ ] **Step 4: 最终回归**

Run:

```powershell
uv run pytest tests/server/test_historical_trend_queries.py tests/server/test_historical_trend_digest.py tests/server/test_historical_trend_template.py tests/server/test_attachment_html_trends.py tests/server/test_trend_digest_thresholds.py
```

Expected: PASS
