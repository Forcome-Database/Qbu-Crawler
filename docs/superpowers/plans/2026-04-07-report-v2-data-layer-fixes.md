# Report V2 Data-Layer Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PDF 布局错乱，补全产品健康表/问题簇/竞品差距三处字段缺失，并接通 review_analysis 数据管道，使 LLM 特征聚类真正生效。

**Architecture:** 六个独立任务，前五个修复输出层（CSS + Python 字段），第六个修复数据输入层（snapshot 接通 review_analysis）。每个任务均可独立测试和提交，互不依赖。

**Tech Stack:** Python 3.10+, CSS/Playwright, pytest, SQLite, `models.get_reviews_with_analysis()`

---

## 文件影响清单

| 文件 | 任务 | 操作 |
|------|------|------|
| `qbu_crawler/server/report_templates/daily_report.css` | Task 1 | 修改 |
| `qbu_crawler/server/report_analytics.py` | Task 2, 5 | 修改 |
| `qbu_crawler/server/report_common.py` | Task 3, 4 | 修改 |
| `qbu_crawler/server/report_pdf.py` | Task 3 | 修改（image_evidence data URI） |
| `qbu_crawler/server/report_snapshot.py` | Task 6 | 修改 |
| `tests/test_report_analytics.py` | Task 2, 5 | 修改 |
| `tests/test_report_common.py` | Task 3, 4 | 修改 |
| `tests/test_report_snapshot.py` | Task 6 | 修改 |

---

## Task 1: CSS Hero Layout Fix

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report.css:366-378`

**问题根因：** `.health-gauge-wrap` 是 flex 容器，gauge 的 `.chart-container` 没有限制宽度，Plotly SVG 的 intrinsic size 占满 ~65% 宽度，将 `.hero-main` 挤成窄列导致文字极端换行。`hero-main h1` 的 `max-width: 8ch` 在 34px 字号下限制标题为约 4 行。

- [ ] **Step 1: 给 gauge chart-container 设固定宽度，给 hero-main 设最小宽度**

在 `daily_report.css` 中找到 `.health-gauge-wrap` 的 CSS（约第 366 行），在其后**新增**：

```css
/* Gauge chart: fixed share of hero row — prevents Plotly SVG from crowding hero-main */
.health-gauge-wrap > .chart-container {
  flex: 0 0 52%;
  max-width: 340px;
}

.health-gauge-wrap > .hero-main {
  flex: 1 1 0;
  min-width: 180px;
}
```

- [ ] **Step 2: 移除 hero-main h1 的 max-width 限制**

在 `daily_report.css` 中找到 `.hero-main h1`（约第 380 行），删除 `max-width: 8ch;` 这一行。

- [ ] **Step 3: 用 preview 脚本验证 PDF 视觉**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
uv run python scripts/preview_v2_report.py
```

打开生成的 PDF，确认：
- gauge 占左侧约 50% 宽度
- 右侧"产品评论深度分析报告"标题不再极端换行（单行或最多两行）
- hero headline 文字正常展示

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report.css
git commit -m "fix: constrain gauge chart width in hero flex layout to prevent text squeeze"
```

---

## Task 2: `_risk_products()` 补全 rating_avg / negative_rate / top_features_display

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:520-573`
- Modify: `qbu_crawler/server/report_common.py:484-500`
- Modify: `tests/test_report_common.py`

**问题根因：** 模板访问 `item.rating_avg`、`item.negative_rate`、`item.top_features_display`，但 `_risk_products()` 只返回 `negative_review_rows`、`risk_score`、`top_labels`。`normalize_deep_report_analytics()` 只生成 `top_labels_display` 而非 `top_features_display`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_common.py` 中添加：

```python
def test_risk_products_has_rating_avg_and_negative_rate():
    """_risk_products via normalize returns rating_avg, negative_rate, top_features_display."""
    from qbu_crawler.server.report_analytics import _risk_products
    labeled_reviews = [
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 1},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                        "severity": "high", "confidence": 0.9}],
            "images": [],
        },
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 5},
            "labels": [],
            "images": [],
        },
    ]
    snapshot_products = [{"sku": "SKU1", "rating": 3.5, "review_count": 20}]
    result = _risk_products(labeled_reviews, snapshot_products=snapshot_products)
    assert len(result) == 1
    p = result[0]
    assert p["rating_avg"] == 3.5          # from snapshot_products
    assert p["negative_rate"] == pytest.approx(1 / 20)  # 1 negative / 20 site total
    assert "top_features_display" in p
```

运行：`uv run pytest tests/test_report_common.py::test_risk_products_has_rating_avg_and_negative_rate -v`
期望：**FAIL** — `KeyError: 'rating_avg'`

- [ ] **Step 2: 修改 `_risk_products()` 加入 rating_avg / negative_rate**

在 `report_analytics.py` 的 `_risk_products()` 中，在构建 `sku_to_review_count` 之后，新增 `sku_to_rating`：

```python
def _risk_products(labeled_reviews, snapshot_products=None):
    sku_to_review_count = {}
    sku_to_rating = {}
    for p in (snapshot_products or []):
        sku = p.get("sku") or ""
        sku_to_review_count[sku] = p.get("review_count") or 0
        sku_to_rating[sku] = p.get("rating")   # ← 新增
```

在 `grouped.setdefault(...)` 的初始化 dict 中加入两个字段：

```python
product = grouped.setdefault(
    key,
    {
        ...
        "total_reviews": sku_to_review_count.get(review.get("product_sku", ""), 0),
        "rating_avg": sku_to_rating.get(review.get("product_sku", "")),          # ← 新增
        "negative_rate": None,    # ← 新增，计算后填充
        "top_labels": {},
    },
)
```

在 items 排序后、return 前，计算 `negative_rate`：

```python
for item in items:
    label_counts = item.pop("top_labels")
    item["top_labels"] = [...]
    # 计算 negative_rate
    total = item.get("total_reviews") or 0
    neg = item.get("negative_review_rows", 0)
    item["negative_rate"] = neg / total if total else None
```

- [ ] **Step 3: 修改 `normalize_deep_report_analytics()` 加入 top_features_display 别名**

在 `report_common.py` 的 `normalize_deep_report_analytics()` 中，找到 risk_products 处理循环（约第 485 行）：

```python
product["top_labels_display"] = _join_label_counts(product.get("top_labels") or [])
product["top_features_display"] = product["top_labels_display"]   # ← 新增别名
```

- [ ] **Step 4: 运行测试验证通过**

```bash
uv run pytest tests/test_report_common.py::test_risk_products_has_rating_avg_and_negative_rate -v
```
期望：**PASS**

- [ ] **Step 5: 运行回归测试**

```bash
uv run pytest tests/test_report_common.py tests/test_report_analytics.py -v
```
期望：全部通过

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "fix: add rating_avg, negative_rate, top_features_display to risk products"
```

---

## Task 3: `issue_cards` 完整补全（所有模板缺失字段）

**Files:**
- Modify: `qbu_crawler/server/report_common.py:568-578`
- Modify: `qbu_crawler/server/report_pdf.py` (`render_report_html`，处理 image_evidence data URI)
- Modify: `tests/test_report_common.py`

**问题根因：** `normalize_deep_report_analytics()` 构建 `issue_cards` 时只保留了 6 个字段，模板所需的以下字段全部缺失，导致 P3 页面的时间线、引用评论、图片证据、改良建议永远空白：

| 字段 | 模板位置 | 缺失原因 |
|------|---------|---------|
| `first_seen` / `last_seen` | `html.j2:167` | 未从 cluster 传入 |
| `duration_display` | `html.j2:169` | 从未计算 |
| `example_reviews` | `html.j2:174` | 未从 cluster 传入 |
| `image_evidence` | `html.j2:199` | 从未构建 |
| `recommendation` | `html.j2:214` | `improvement_priorities` 从未注入 |

- [ ] **Step 1: 写失败测试（覆盖所有 5 个字段）**

```python
def test_issue_cards_complete_fields():
    """issue_cards must carry all fields required by the P3 template."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "logical_date": "2026-04-07",
        "mode": "baseline",
        "snapshot_hash": "abc",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "review_count": 3,
                    "severity": "high",
                    "affected_product_count": 1,
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-04-01",
                    "image_review_count": 1,
                    "example_reviews": [
                        {"product_name": "P", "rating": 1, "headline": "bad",
                         "headline_cn": "差", "body": "broke", "body_cn": "坏了",
                         "images": ["https://example.com/img1.jpg"],
                         "author": "A", "date_published": "2026-01-01"}
                    ],
                }
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {
            "improvement_priorities": [
                {"rank": 1, "target": "P", "issue": "手柄松动", "action": "加强出厂耐久测试", "evidence_count": 3}
            ]
        },
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert card["first_seen"] == "2026-01-01"
    assert card["last_seen"] == "2026-04-01"
    assert card["duration_display"] is not None
    assert "月" in card["duration_display"] or "天" in card["duration_display"]
    assert len(card["example_reviews"]) == 1
    assert len(card["image_evidence"]) == 1
    assert card["image_evidence"][0]["url"] == "https://example.com/img1.jpg"
    assert card["recommendation"] == "加强出厂耐久测试"
```

运行：`uv run pytest tests/test_report_common.py::test_issue_cards_complete_fields -v`
期望：**FAIL**

- [ ] **Step 2: 在 `report_common.py` 添加 `_duration_display()` 辅助函数**

在 `_humanize_bullets` 函数之前添加：

```python
def _duration_display(first_seen: str | None, last_seen: str | None) -> str | None:
    """Human-readable duration from ISO date strings."""
    if not first_seen or not last_seen:
        return None
    try:
        from datetime import date
        d1 = date.fromisoformat(first_seen[:10])
        d2 = date.fromisoformat(last_seen[:10])
        days = (d2 - d1).days
        if days <= 0:
            return None
        if days < 30:
            return f"{days} 天"
        return f"约 {days // 30} 个月"
    except Exception:
        return None
```

- [ ] **Step 3: 修改 `normalize_deep_report_analytics()` 的 issue_cards 构建**

找到约第 568 行的 issue_cards 循环，替换为：

```python
report_priorities = (normalized.get("report_copy") or {}).get("improvement_priorities") or []
priority_by_rank = {p.get("rank", i + 1): p.get("action", "") for i, p in enumerate(report_priorities)}

issue_cards = []
for i, cluster in enumerate(normalized["self"]["top_negative_clusters"]):
    # Collect image URLs from example_reviews (max 3 unique)
    image_evidence = []
    seen_urls: set[str] = set()
    for ex in cluster.get("example_reviews") or []:
        for url in ex.get("images") or []:
            if url and url not in seen_urls and len(image_evidence) < 3:
                seen_urls.add(url)
                image_evidence.append({"url": url, "data_uri": None,
                                        "evidence_id": f"I{len(image_evidence)+1}"})
    issue_cards.append({
        "feature_display": cluster.get("feature_display") or cluster.get("label_display", ""),
        "label_display": cluster.get("label_display", ""),
        "review_count": cluster.get("review_count", 0),
        "severity": cluster.get("severity", "low"),
        "severity_display": cluster.get("severity_display", ""),
        "affected_product_count": cluster.get("affected_product_count", 0),
        "first_seen": cluster.get("first_seen"),
        "last_seen": cluster.get("last_seen"),
        "duration_display": _duration_display(cluster.get("first_seen"), cluster.get("last_seen")),
        "image_review_count": cluster.get("image_review_count", 0),
        "example_reviews": cluster.get("example_reviews") or [],
        "image_evidence": image_evidence,
        "recommendation": priority_by_rank.get(i + 1, ""),
    })
normalized["self"]["issue_cards"] = issue_cards
```

- [ ] **Step 4: 在 `report_pdf.py` 的 `render_report_html()` 中处理 issue_cards 图片 data URI**

找到约第 146 行已有的 appendix 图片处理，在其**之后**添加：

```python
# issue_cards image_evidence: convert URLs to data URIs for offline PDF rendering
for card in normalized.get("self", {}).get("issue_cards", []):
    for img_item in card.get("image_evidence") or []:
        img_item["data_uri"] = _inline_image_data_uri(img_item.get("url"))
```

- [ ] **Step 5: 运行测试**

```bash
uv run pytest tests/test_report_common.py::test_issue_cards_complete_fields -v
```
期望：**PASS**

- [ ] **Step 6: 回归测试**

```bash
uv run pytest tests/test_report_common.py tests/test_report_pdf.py -v
```

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_pdf.py tests/test_report_common.py
git commit -m "fix: complete issue_cards with timeline, duration, quotes, image_evidence, recommendation"
```

---

## Task 4: `_competitor_gap_analysis()` 补全 gap / priority_display

**Files:**
- Modify: `qbu_crawler/server/report_common.py:78-97`
- Modify: `tests/test_report_common.py`

**问题根因：** 模板竞品差距表访问 `gap.gap` 和 `gap.priority_display`，但 `_competitor_gap_analysis()` 只返回 4 个字段。

- [ ] **Step 1: 写失败测试**

```python
def test_gap_analysis_has_gap_and_priority_display():
    """Gap analysis items must include 'gap' and 'priority_display'."""
    from qbu_crawler.server.report_common import _competitor_gap_analysis
    normalized = {
        "competitor": {
            "top_positive_themes": [
                {"label_code": "solid_build", "review_count": 10}
            ]
        },
        "self": {
            "top_negative_clusters": [
                {"label_code": "solid_build", "review_count": 6, "severity": "high"}
            ]
        },
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    g = gaps[0]
    assert "gap" in g            # gap = competitor_positive - own_negative
    assert "priority_display" in g
    assert g["gap"] == 10 - 6    # 4
    assert g["priority_display"] in ("高", "中", "低")
```

运行：`uv run pytest tests/test_report_common.py::test_gap_analysis_has_gap_and_priority_display -v`
期望：**FAIL**

- [ ] **Step 2: 修改 `_competitor_gap_analysis()`**

```python
def _competitor_gap_analysis(normalized):
    comp_positive = {
        t["label_code"]: t
        for t in normalized.get("competitor", {}).get("top_positive_themes", [])
    }
    own_negative = {
        c["label_code"]: c
        for c in normalized.get("self", {}).get("top_negative_clusters", [])
    }
    gap_codes = set(comp_positive) & set(own_negative)
    gaps = []
    for code in gap_codes:
        comp_cnt = comp_positive[code].get("review_count", 0)
        own_cnt = own_negative[code].get("review_count", 0)
        gap_val = comp_cnt - own_cnt   # 正值=竞品优势更大，负值=我方被批更多
        # priority: 自有差评数越多越优先处理
        if own_cnt >= 5:
            priority = "high"
            priority_display = "高"
        elif own_cnt >= 2:
            priority = "medium"
            priority_display = "中"
        else:
            priority = "low"
            priority_display = "低"
        gaps.append({
            "label_code": code,
            "label_display": _LABEL_DISPLAY.get(code, code),
            "competitor_positive_count": comp_cnt,
            "own_negative_count": own_cnt,
            "gap": gap_val,
            "priority": priority,
            "priority_display": priority_display,
        })
    return sorted(gaps, key=lambda g: g["own_negative_count"], reverse=True)
```

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/test_report_common.py::test_gap_analysis_has_gap_and_priority_display -v
```
期望：**PASS**

- [ ] **Step 4: 回归测试**

```bash
uv run pytest tests/test_report_common.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "fix: add gap and priority_display fields to competitor gap analysis"
```

---

## Task 5: 补全 `_products_for_charts` — 启用价格-评分象限图

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:718-821`
- Modify: `tests/test_report_analytics.py`

**问题根因：** `build_chart_html_fragments()` 需要 `analytics["_products_for_charts"]`（含 `name`, `price`, `rating`, `ownership` 字段列表），但 `build_report_analytics()` 从未生成此字段。价格-评分象限图因此永远不渲染。

- [ ] **Step 1: 写失败测试**

注意：`analytics_db` fixture 返回字符串（db 文件路径），不是 dict。使用已有的 `_create_daily_run()` 和 `_build_snapshot()` helper（与文件中其他测试保持一致）。

```python
def test_build_report_analytics_includes_products_for_charts(analytics_db):
    """_products_for_charts must be present in analytics for the quadrant chart."""
    from qbu_crawler.server.report_analytics import build_report_analytics
    # analytics_db fixture returns db_file path; use existing helpers for snapshot construction
    run = _create_daily_run("2026-03-29", status="reporting")
    snapshot = _build_snapshot(run["id"], "2026-03-29")
    result = build_report_analytics(snapshot)
    assert "_products_for_charts" in result
    pfc = result["_products_for_charts"]
    assert isinstance(pfc, list)
    # _build_snapshot products have price + rating, so pfc should be non-empty
    assert len(pfc) >= 1
    assert "name" in pfc[0]
    assert "price" in pfc[0]
    assert "ownership" in pfc[0]
```

运行：`uv run pytest tests/test_report_analytics.py::test_build_report_analytics_includes_products_for_charts -v`
期望：**FAIL** — `AssertionError: '_products_for_charts' not in result`

- [ ] **Step 2: 在 `build_report_analytics()` 末尾 return dict 中加入 `_products_for_charts`**

在 `report_analytics.py` 的 `build_report_analytics()` 中，在 `return {...}` 之前新增：

```python
# _products_for_charts: 用于价格-评分象限图，包含有 price/rating 的产品
products_for_charts = [
    {
        "name": p.get("name", ""),
        "sku": p.get("sku", ""),
        "price": float(p.get("price") or 0),
        "rating": float(p.get("rating") or 0),
        "ownership": p.get("ownership", "competitor"),
    }
    for p in (snapshot.get("products") or [])
    if p.get("price") and p.get("rating")
]
```

然后在 return dict 中加入 `"_products_for_charts": products_for_charts`。

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/test_report_analytics.py::test_build_report_analytics_includes_products_for_charts -v
```
期望：**PASS**

- [ ] **Step 4: 回归测试**

```bash
uv run pytest tests/test_report_analytics.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py
git commit -m "fix: add _products_for_charts to analytics to enable price-rating quadrant chart"
```

---

## Task 6: 接通 review_analysis — snapshot 中的评论携带 LLM 分析字段

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:41-43`
- Modify: `tests/test_report_snapshot.py`

**重要背景（已验证）：**
`translator.py:359` 已有 `_translate_batch = _analyze_and_translate_batch`，翻译器在处理每条评论时**已同时产出 review_analysis 数据**。`backfill-analysis` CLI 也已实现（`cli.py:142`），可对历史评论补跑分析。

**问题根因：** 翻译器已在生产数据，但 `freeze_report_snapshot()` 调用的 `query_report_data()` SQL 不含 `review_analysis` JOIN，导致 snapshot.reviews 的 `analysis_features` 永远为 `None`，`_has_review_analysis_data()` 永远返回 `False`，LLM feature clusters 永远不激活。

`models.get_reviews_with_analysis(review_ids=[...])` 已实现并含完整 LEFT JOIN，可直接用于补充分析字段。

**运维前置步骤（一次性，代码合并后执行）：**
```bash
# 对历史未分析评论补跑 Translation++ 分析
uv run python main.py backfill-analysis --dry-run   # 先确认数量
uv run python main.py backfill-analysis             # 重置 translate_status
uv run python main.py serve                          # 启动服务，TranslationWorker 自动处理
```

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_snapshot.py` 中添加（在现有 fixture 下方）：

```python
def test_freeze_snapshot_reviews_enriched_with_analysis_fields(snapshot_db):
    """After freezing, snapshot reviews contain analysis_features when review_analysis exists."""
    import json
    from qbu_crawler.server.report_snapshot import freeze_report_snapshot
    from qbu_crawler import models

    # snapshot_db fixture returns {"db_file": ..., "run": ..., "tmp_path": ...}
    run_id = snapshot_db["run"]["id"]

    # 查询 review id（snapshot_db fixture 只插入了一条评论）
    conn = _get_test_conn(snapshot_db["db_file"])
    review_id = conn.execute("SELECT id FROM reviews LIMIT 1").fetchone()["id"]
    conn.close()

    # 向 review_analysis 表插入一条分析记录
    models.save_review_analysis(
        review_id=review_id,
        sentiment="negative",
        sentiment_score=0.9,
        labels=[{"code": "quality_stability", "polarity": "negative", "severity": "high", "confidence": 0.95}],
        features=["手柄松动"],
        insight_cn="产品质量问题",
        insight_en="quality issue",
        llm_model="gpt-4o-mini",
        prompt_version="v1",
        token_usage=100,
    )

    run = freeze_report_snapshot(run_id)
    # reload snapshot
    from pathlib import Path
    snapshot = json.loads(Path(run["snapshot_path"]).read_text())

    enriched = [r for r in snapshot["reviews"] if r.get("id") == review_id]
    assert enriched, "review not found in snapshot"
    r = enriched[0]
    assert r.get("analysis_features") is not None, "analysis_features should be set after enrichment"
    assert "手柄松动" in (r.get("analysis_features") or "")
```

运行：`uv run pytest tests/test_report_snapshot.py::test_freeze_snapshot_reviews_enriched_with_analysis_fields -v`
期望：**FAIL** — `AssertionError: analysis_features should be set after enrichment`

- [ ] **Step 2: 修改 `freeze_report_snapshot()` 做 review_analysis 富化**

在 `report_snapshot.py` 的 `freeze_report_snapshot()` 中，在 `products, reviews = report.query_report_data(...)` 之后添加富化逻辑（约第 43 行）：

```python
products, reviews = report.query_report_data(run["data_since"], until=run["data_until"])

# ── 富化 review_analysis 字段（LLM 分析数据，如有则优先使用） ──
_review_ids = [r["id"] for r in reviews if r.get("id")]
if _review_ids:
    _enriched_map = {
        ea["id"]: ea
        for ea in models.get_reviews_with_analysis(review_ids=_review_ids)
    }
    for r in reviews:
        ea = _enriched_map.get(r.get("id"))
        if ea:
            r.setdefault("sentiment", ea.get("sentiment"))
            r.setdefault("analysis_features", ea.get("analysis_features"))
            r.setdefault("analysis_labels", ea.get("analysis_labels"))
            r.setdefault("analysis_insight_cn", ea.get("analysis_insight_cn"))
            r.setdefault("analysis_insight_en", ea.get("analysis_insight_en"))
```

注意：`setdefault` 保证只有字段不存在时才覆盖，不破坏已有字段。

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/test_report_snapshot.py::test_freeze_snapshot_reviews_enriched_with_analysis_fields -v
```
期望：**PASS**

- [ ] **Step 4: 回归测试**

```bash
uv run pytest tests/test_report_snapshot.py -v
```

- [ ] **Step 5: 完整测试套件**

```bash
uv run pytest tests/ -v --tb=short -x
```

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat: enrich snapshot reviews with review_analysis fields to activate LLM feature clusters"
```

---

## 完成后验证

所有 6 个任务完成后，运行端到端预览验证：

```bash
uv run python scripts/preview_v2_report.py
```

预期改善：
1. PDF hero 页面 gauge 和文字布局正常
2. 产品健康度表出现评分和差评率数值（而非全"—"）
3. 问题深度诊断页面：时间线、持续时长、引用评论、图片证据、改良建议全部显示
4. 竞品差距表显示差距数值和优先级
5. 价格-评分象限图出现（当产品有价格+评分数据时）
6. 执行 `backfill-analysis` 后，新一轮报告中问题簇显示 LLM 特征（如"手柄松动"）而非抽象标签

**说明：** translator.py 已于此前修改（`_translate_batch = _analyze_and_translate_batch`），V2 Phase 1 翻译器实现已完成，无需 Task 7。
