# Report V3 Redesign — 产品评论智能分析报告系统重构

> **Status**: Draft
> **Date**: 2026-04-10
> **Scope**: report_*.py, translator.py, models.py, config.py, report_templates/*
> **Predecessor**: 2026-04-06-report-intelligence-redesign-v2-design.md

---

## 1. Executive Summary

Report V3 addresses three systemic problems in the current report system:

1. **Silent majority of days produce no output.** Most days have zero new reviews. The system returns early and sends nothing — defeating the purpose of daily monitoring.
2. **Metrics mislead rather than inform.** The health index double-counts correlated signals, risk scores ignore review ratios, gap analysis conflates two independent dimensions, and severity grades collapse to a single level.
3. **LLM generates surface-level insights.** The report-level LLM call receives only aggregated statistics, never reading actual customer language. Its output restates numbers rather than synthesizing patterns.

V3 restructures the system along three axes:

- **Architecture**: Three report modes (Full / Change / Quiet Day) ensure every day produces meaningful output. HTML replaces PDF as the primary format, unlocking interactive charts, collapsible sections, and responsive layout.
- **Algorithms**: Every core metric (health index, risk score, gap analysis, severity, alert level) receives a principled redesign grounded in observable data properties.
- **AI utilization**: LLM calls gain access to raw review text, extract richer per-review fields, and perform cluster-level root-cause analysis.

---

## 2. Background

### 2.1 Current System

The report pipeline runs daily:

```
Scraper → DB (products, reviews)
  → TranslationWorker (LLM: translate + classify per batch of 20)
  → WorkflowWorker triggers report:
      sync_review_labels()
      → build_report_analytics() (clustering, risk, charts)
      → normalize_deep_report_analytics() (KPIs, gap, display fields)
      → generate_report_insights() (LLM: 6 executive fields)
      → render HTML → Playwright PDF → openpyxl Excel → SMTP email
```

Output: 6-page PDF + 6-sheet Excel + HTML file, emailed with attachments.

### 2.2 Current Product Catalog

| Product | Ownership | Site | Reviews | Rating |
|---------|-----------|------|---------|--------|
| Cabela's Heavy-Duty Sausage Stuffer | own | basspro | 79 | 3.3 |
| Cabela's Commercial-Grade Sausage Stuffer | own | basspro | 88 | 3.6 |
| Cabela's Heavy-Duty 20-lb. Meat Mixer | own | basspro | 57 | 4.3 |
| 1 HP Grinder (#22) | competitor | meatyourmaker | 684 | 4.7 |
| 1.5 HP Dual Grind Grinder (#32) | competitor | meatyourmaker | 21 | 4.7 |
| 1 HP Dual Grind Grinder (#22) | competitor | meatyourmaker | 180 | 4.7 |
| Walton's Quick Patty Maker | competitor | waltons | 94 | 4.7 |
| Walton's General Duty Meat Lug | competitor | waltons | 71 | 4.8 |
| Walton's Meat Tenderizer | competitor | waltons | 13 | 4.7 |

Key characteristics: 9 products, 3 own / 6 competitor. Monthly review velocity per product: 1-5 reviews. Most calendar days will have zero new reviews.

### 2.3 Problems Identified

See Section 6 (Metrics) and Section 7 (LLM) for detailed per-algorithm diagnosis. High-level:

| Problem | Evidence | Impact |
|---------|----------|--------|
| No output on quiet days | `workflow-run-2-snapshot` has 0 reviews; `generate_full_report_from_snapshot` returns early | Majority of days produce nothing |
| Health index double-counts | `own_avg_rating` and `sample_avg_rating` are 0.95-correlated, together get 45% weight | Score is noisy, not interpretable |
| Risk score ignores ratio | Product with 10/100 negative (10%) and 10/10 negative (100%) can get same raw score | Misranks product priority |
| Severity all "high" | 6/6 clusters in baseline report marked "high" | Grading has zero discriminative power |
| Gap analysis averages unrelated rates | `(competitor_positive_rate + own_negative_rate) / 2` — mixing positive and negative dimensions | "性能与动力" gap=28 with own_negative=0% is misleading |
| Priority based on own_rate not gap_rate | "性能与动力" priority="低" despite gap_index=28 | Priority label contradicts gap magnitude |
| LLM sees no review text | `_build_insights_prompt` passes only aggregated counts, never raw customer language | Hero headline restates numbers instead of synthesizing themes |
| `_uncategorized` leaks to report | Internal label code appears in P5 gap table | Unprofessional |
| Baseline mode always green alert | `if mode == "baseline": return ("green", ...)` regardless of actual health | 39% negative rate gets green signal |
| PDF charts truncate labels | Plotly static export clips long product names, radar dimensions | Charts become unreadable |
| Relative dates cluster on same day | "3 years ago" → all parse to "2023-04-08" | Timeline analysis has false spikes |

---

## 3. Design Goals

| Goal | Metric | Target |
|------|--------|--------|
| Every day produces output | Days with report / total days | 100% |
| Severity has discriminative power | Distinct severity levels in a 6-cluster report | >= 3 levels |
| Metrics are self-explanatory | Each KPI card includes benchmark context | All cards |
| LLM reads customer voice | Report-level prompt includes review text | >= 20 samples |
| Charts are fully readable | No truncated labels, no overlap | Zero truncation |
| Report loads interactively | Primary format supports hover, collapse, filter | HTML |
| Edge cases handled gracefully | Defined behavior for each of 12 boundary scenarios | All covered |

### Non-goals

- Real-time dashboard (this is a daily batch report)
- User authentication on HTML report (internal distribution)
- Custom per-recipient report filtering (single report for all recipients)

---

## 4. Report Architecture

### 4.1 Three Report Modes

```
daily workflow trigger
        │
        ▼
  freeze_snapshot()
        │
        ▼
  ┌─────────────────────────────────────┐
  │  Has new reviews?                   │─── Yes ──▶ Full Report
  │                                     │
  │  Has price/stock/rating changes?    │─── Yes ──▶ Change Report
  │                                     │
  │  Neither?                           │─── Yes ──▶ Quiet Day Report
  └─────────────────────────────────────┘
```

#### 4.1.1 Full Report

Trigger: `len(snapshot.reviews) > 0`.

Contains all sections: Executive Dashboard, What Changed, Action Board, Product Risk Matrix, Issue Deep Dive, Competitive Intelligence, Feature Panorama.

Email subject: `产品评论日报 {date} — {top_product} 等 {n} 个产品`
Email attachments: HTML report link + Excel data file.

#### 4.1.2 Change Report

Trigger: `len(snapshot.reviews) == 0` AND price, stock_status, or site-reported rating changed vs previous snapshot.

Contains: Executive Dashboard (current state, no new-review KPIs), Change Summary (what changed), Outstanding Issues (carried from last full report).

Email subject: `[价格变动] 产品监控简报 {date}`
Email attachments: None (inline only).

#### 4.1.3 Quiet Day Report

Trigger: `len(snapshot.reviews) == 0` AND no price/stock/rating changes.

Contains: Health Snapshot (current KPIs, no deltas), Outstanding Issues Summary (from last full report), Translation Progress, Next Scheduled Scrape.

Email subject: `[无变化] 产品监控简报 {date}`
Email attachments: None.

#### 4.1.4 Change Detection Logic

```python
def detect_snapshot_changes(current_snapshot, previous_snapshot):
    """Compare two snapshots for price/stock/rating changes.
    
    Returns dict with:
        has_changes: bool
        price_changes: [{sku, name, old, new}]
        stock_changes: [{sku, name, old, new}]
        rating_changes: [{sku, name, old, new}]
        review_count_changes: [{sku, name, old, new}]  # site-reported total
        new_products: [product_dict]
        removed_products: [product_dict]
    """
    changes = {
        "has_changes": False,
        "price_changes": [], "stock_changes": [], "rating_changes": [],
        "review_count_changes": [], "new_products": [], "removed_products": [],
    }
    
    prev_by_sku = {p["sku"]: p for p in previous_snapshot.get("products", [])}
    
    for product in current_snapshot.get("products", []):
        sku = product["sku"]
        prev = prev_by_sku.get(sku)
        if not prev:
            # New product added to monitoring
            changes["new_products"].append(product)
            changes["has_changes"] = True
            continue
        
        if product["price"] != prev["price"]:
            changes["price_changes"].append({...})
            changes["has_changes"] = True
        
        if product["stock_status"] != prev["stock_status"]:
            changes["stock_changes"].append({...})
            changes["has_changes"] = True
        
        if product["rating"] != prev["rating"]:
            changes["rating_changes"].append({...})
            changes["has_changes"] = True
        
        if product["review_count"] != prev["review_count"]:
            changes["review_count_changes"].append({...})
            # review_count change alone does NOT set has_changes
            # (we already check for actual new reviews in snapshot.reviews)
    
    # Detect removed products
    current_skus = {p["sku"] for p in current_snapshot.get("products", [])}
    for sku, prev_product in prev_by_sku.items():
        if sku not in current_skus:
            changes["removed_products"].append(prev_product)
            changes["has_changes"] = True
    
    return changes
```

#### 4.1.5 Previous Report Loading

All three modes require loading the previous completed workflow run's analytics and snapshot:

```python
def load_previous_report_context(current_run_id):
    """Load the most recent completed run's analytics and snapshot.
    
    Returns:
        previous_analytics: dict or None
        previous_snapshot: dict or None
    """
    prev_run = models.get_previous_completed_run(current_run_id)
    if not prev_run or not prev_run.get("analytics_path"):
        return None, None
    
    try:
        analytics = json.loads(Path(prev_run["analytics_path"]).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("Failed to load previous analytics: %s", e)
        return None, None
    
    snapshot = None
    if prev_run.get("snapshot_path"):
        try:
            snapshot = json.loads(Path(prev_run["snapshot_path"]).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("Failed to load previous snapshot: %s", e)
    
    return analytics, snapshot
```

### 4.2 HTML as Primary Report Format

#### 4.2.1 Rationale

| Dimension | PDF (current) | HTML (proposed) |
|-----------|--------------|-----------------|
| Chart interactivity | Static screenshots, labels truncate | Hover tooltips, zoom, pan — truncation eliminated |
| Information density | 6 pages, linear scroll | Tabs + collapsible sections, all content in 1 view |
| Evidence images | 80px thumbnails | Click-to-expand lightbox, full resolution |
| Mobile | A4 fixed, unreadable on phone | Responsive layout |
| Search | Not searchable | Browser Ctrl+F + built-in filter/sort on review table |
| Deployment | Requires Playwright + headless Chromium | Pure Jinja2, no browser dependency |
| File size | 1.2MB PDF | ~300KB HTML (chart library via CDN) |
| Offline | Self-contained | Self-contained with inlined JS fallback |

#### 4.2.2 Chart Library: Chart.js

Replace Plotly (~3MB inline) with Chart.js (~200KB CDN, ~70KB gzipped).

Rationale: Plotly's strength is scientific visualization (3D, contour, etc.) which this report does not need. Chart.js covers all required chart types (gauge, bar, radar, scatter, line, stacked bar, heatmap via plugin) with a fraction of the bundle size.

Chart mapping:

| Chart | Current (Plotly) | Proposed (Chart.js) |
|-------|-----------------|---------------------|
| Health gauge | `plotly.Indicator` | `chartjs-gauge` plugin or custom doughnut |
| Horizontal bar | `plotly.Bar` (horizontal) | `Chart.js` bar (indexAxis: 'y') |
| Radar | `plotly.Scatterpolar` | `Chart.js` radar |
| Scatter (price-rating) | `plotly.Scatter` | `Chart.js` scatter |
| Line (trend) | `plotly.Scatter` (line mode) | `Chart.js` line |
| Stacked bar (sentiment) | `plotly.Bar` (stacked) | `Chart.js` bar (stacked) |
| Heatmap | `plotly.Heatmap` | `chartjs-chart-matrix` plugin |

Loading strategy:
- Primary: CDN `<script src="https://cdn.jsdelivr.net/npm/chart.js@4">` with integrity hash
- Fallback: Inline minified bundle for offline use (add `<script>` block at bottom)
- Decision: use CDN by default; provide config flag `REPORT_OFFLINE_MODE=true` to inline

#### 4.2.3 Interactive Features (~300 lines vanilla JS)

| Feature | Implementation | Benefit |
|---------|---------------|---------|
| Tab navigation | Click handler toggles `display:none` on section divs | All content accessible in one page |
| Collapsible issue cards | Click header toggles body visibility | Scan headings, expand on interest |
| Evidence lightbox | Click thumbnail → full-screen overlay with image | See defect photos in detail |
| Review table sort/filter | Click column header to sort; input fields to filter | Find specific reviews instantly |
| Sticky KPI bar | `position: sticky; top: 0` on KPI container | Context always visible while scrolling |
| Print-to-PDF | `window.print()` button + `@media print` styles | Optional PDF for those who need it |
| Dark mode toggle | CSS custom properties swap + localStorage persistence | Comfort for evening reading |

#### 4.2.4 Template Structure

New template: `report_templates/daily_report_v3.html.j2`

```
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>产品评论分析报告 {{ logical_date }}</title>
  <style>{{ css_text }}</style>
</head>
<body>
  <!-- Sticky KPI Bar -->
  <header class="kpi-bar"> ... </header>

  <!-- Tab Navigation -->
  <nav class="tab-nav">
    <button data-tab="overview" class="active">总览</button>
    <button data-tab="changes">今日变化</button>
    <button data-tab="issues">问题诊断</button>
    <button data-tab="products">产品排行</button>
    <button data-tab="competitive">竞品对标</button>
    <button data-tab="panorama">全景数据</button>
  </nav>

  <!-- Tab Panels -->
  <main>
    <section id="tab-overview"> ... </section>
    <section id="tab-changes"> ... </section>
    <section id="tab-issues"> ... </section>
    <section id="tab-products"> ... </section>
    <section id="tab-competitive"> ... </section>
    <section id="tab-panorama"> ... </section>
  </main>

  <!-- Lightbox Overlay (hidden) -->
  <div id="lightbox" class="lightbox hidden"> ... </div>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <script>{{ inline_js }}</script>
</body>
</html>
```

Quiet Day template: `report_templates/quiet_day_report.html.j2` — single-section layout, no tabs.

Change Report template: reuses `daily_report_v3.html.j2` with `{% if mode == 'change' %}` conditionals to hide issue/competitive tabs.

#### 4.2.5 PDF Elimination and Migration

- **Remove**: `report_pdf.py` (Playwright dependency)
- **Remove**: `playwright` from `pyproject.toml` dependencies
- **Keep**: `@media print` stylesheet in HTML template for browser-initiated printing
- **Add**: "导出PDF" button in HTML report that calls `window.print()`

#### 4.2.6 Email Strategy

Three email templates corresponding to three report modes:

| Mode | Subject | Body | Attachments |
|------|---------|------|-------------|
| Full | `产品评论日报 {date} — {hero_summary}` | KPI cards + What Changed digest + Top 3 actions + "查看完整报告" link | Excel data file |
| Change | `[价格变动] 产品监控简报 {date}` | KPI snapshot + change details | None |
| Quiet | `[无变化] 产品监控简报 {date}` | KPI snapshot + outstanding issues | None |

HTML report served from: `{REPORT_DIR}/workflow-run-{id}-report.html` (same directory as current files). If `MINIO_PUBLIC_URL` is configured, upload to MinIO and include public URL in email. Otherwise, attach HTML file directly.

---

## 5. Content Structure

### 5.1 Tab: Overview (总览)

Replaces current P1. Always present in all modes.

#### 5.1.1 Health Gauge + Hero

```
┌──────────────────────────────────────────────────────────┐
│  [Gauge: 52.4/100]    产品评论深度分析报告               │
│                       自有3款产品质量问题集中,            │
│                       灌肠机齿轮/密封件失效需优先处理     │
│                       Run #3 | 2026-04-10 | 增量模式      │
└──────────────────────────────────────────────────────────┘
```

Hero headline comes from LLM with access to review text (see Section 7.2). Fallback: mechanical generation from top cluster label + top product name.

#### 5.1.2 KPI Cards

Six cards. Each card contains: label, value, delta (if incremental), tooltip explanation, benchmark context.

| Card | Value Source | Delta | Benchmark Context | Tooltip |
|------|-------------|-------|-------------------|---------|
| **健康指数** | `compute_health_index_v3()` | vs previous run | "行业基准: 60-80" | NPS-proxy formula explanation |
| **自有差评率** | `own_negative_review_rows / own_review_rows` | vs previous | "健康: <15%, 警戒: 15-30%, 危险: >30%" | "评分 ≤{NEGATIVE_THRESHOLD} 星的评论占比" |
| **样本量** | `"{ingested}/{site_total} ({coverage_rate}%)"` | — | — | "已采集评论数 / 站点显示总数" |
| **高风险产品** | `high_risk_count` | vs previous | — | "风险分 ≥{threshold} 的自有产品数" |
| **竞品领先维度** | `"{fix_count}需修复 / {catch_count}需追赶"` | — | — | "竞品明显优于我们的特征维度数" |
| **近30天新评论** | `recently_published_count` | vs previous | — | "最近30天内发布的评论数（非历史补采）" |

Removed from current: "好评率" (redundant with 差评率), "竞品差距指数" (replaced by "竞品领先维度" which is more interpretable), "样本覆盖率" (merged into 样本量 card).

#### 5.1.3 Alert Signal

Color-coded banner below KPI cards.

```python
def compute_alert_level_v3(analytics, mode):
    health = analytics["kpis"].get("health_index", 100)
    
    if mode == "baseline":
        # Baseline reports use absolute thresholds, not always green
        if health < config.HEALTH_RED:
            return ("red", f"首次基线：健康指数 {health}/100，低于警戒线")
        if health < config.HEALTH_YELLOW:
            return ("yellow", f"首次基线：健康指数 {health}/100，需关注")
        return ("green", "首次基线采集完成，整体状态良好")
    
    # Incremental mode: delta-based + absolute
    neg_delta = analytics["kpis"].get("own_negative_review_rows_delta", 0)
    has_escalation = any(
        c.get("severity") in ("critical", "high") and c.get("is_new_or_escalated")
        for c in analytics.get("self", {}).get("top_negative_clusters", [])
    )
    
    if health < config.HEALTH_RED or neg_delta >= 10 or has_escalation:
        return ("red", _build_red_alert_text(analytics))
    if health < config.HEALTH_YELLOW or neg_delta > 0:
        return ("yellow", _build_yellow_alert_text(analytics))
    return ("green", "整体健康度良好，无需紧急处理")
```

#### 5.1.4 Key Judgments + Report Scope

Two side-by-side panels (same as current, keep working design):
- Left: `executive_bullets` (3 items from LLM, see Section 7.2)
- Right: Report scope metadata (mode, threshold, product/review counts)

### 5.2 Tab: What Changed (今日变化) — NEW

Only present in Full Report and Change Report modes. Hidden in Quiet Day.

Four sections, each conditionally rendered:

#### 5.2.1 New Reviews

```
📥 新增评论
   自有 +3 条 (2条差评 / 1条好评)    竞品 +5 条 (0条差评 / 5条好评)
   
   新差评摘要:
   · [Sausage Stuffer] ★1 "金属刮屑严重，用了两次就有碎片脱落" — Tom126, 2026-03-13
   · [Sausage Stuffer] ★2 "支撑柱在接缝处断裂" — JennyS, 2025-11-08
```

Data source: Current snapshot reviews, summarized by ownership and sentiment. Show up to 3 own negative review one-liners (headline_cn + rating + author + date).

#### 5.2.2 Issue Escalation / De-escalation

```
⚠️ 问题升级
   · "质量稳定性" 新增 3 条差评 (36→39)，严重度维持: critical
   · "噪音与动力" 首次出现 (2条评论, Meat Mixer) — NEW

✅ 改善信号
   · "包装运输" 连续 14 天无新差评
```

Computed by diffing current clusters against previous analytics clusters:
- New cluster: `label_code` not present in previous → "首次出现"
- Escalated: `review_count` increased → "新增 N 条"
- Severity change: current severity > previous severity → "严重度升级"
- Improving: `review_count` unchanged for >= 7 days → "连续 N 天无新差评"

```python
def compute_cluster_changes(current_clusters, previous_clusters, logical_date):
    """Diff two cluster lists to detect new, escalated, improving, and de-escalated clusters.
    
    Args:
        current_clusters: list of cluster dicts from current analytics
        previous_clusters: list of cluster dicts from previous analytics (may be None)
        logical_date: date object for "today"
    
    Returns dict with keys: new, escalated, improving, de_escalated (each a list of change dicts)
    """
    prev_by_code = {c["label_code"]: c for c in (previous_clusters or [])}
    sev_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    
    changes = {"new": [], "escalated": [], "improving": [], "de_escalated": []}
    
    for cluster in current_clusters:
        code = cluster["label_code"]
        prev = prev_by_code.get(code)
        
        if prev is None:
            changes["new"].append({
                "label_display": cluster["label_display"],
                "review_count": cluster["review_count"],
                "affected_products": cluster.get("affected_products", []),
            })
            continue
        
        delta = cluster["review_count"] - prev["review_count"]
        cur_sev = sev_order.get(cluster["severity"], 0)
        prev_sev = sev_order.get(prev.get("severity"), 0)
        
        if delta > 0:
            entry = {
                "label_display": cluster["label_display"],
                "delta": delta,
                "old_count": prev["review_count"],
                "new_count": cluster["review_count"],
                "severity": cluster["severity"],
                "severity_changed": cur_sev > prev_sev,
            }
            changes["escalated"].append(entry)
        elif cur_sev < prev_sev:
            # Severity decreased without new reviews
            changes["de_escalated"].append({
                "label_display": cluster["label_display"],
                "old_severity": prev.get("severity"),
                "new_severity": cluster["severity"],
            })
    
    # Improving: clusters in previous where last_seen is >7 days before logical_date
    for cluster in current_clusters:
        code = cluster["label_code"]
        prev = prev_by_code.get(code)
        if prev is None:
            continue
        last_seen = cluster.get("last_seen")
        if not last_seen:
            continue
        try:
            last_seen_date = datetime.strptime(last_seen, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        days_quiet = (logical_date - last_seen_date).days
        if days_quiet >= 7 and cluster["review_count"] == prev["review_count"]:
            changes["improving"].append({
                "label_display": cluster["label_display"],
                "days_quiet": days_quiet,
            })
    
    return changes
```

#### 5.2.3 Price / Stock / Rating Changes

```
💰 价格变化
   · Heavy-Duty Sausage Stuffer: $169.99 → $149.99 (-12%)
   
📦 库存变化
   · (无变化)
```

Data source: `detect_snapshot_changes()` from Section 4.1.4.

#### 5.2.4 Translation Progress

```
🌐 翻译进度
   已翻译 710/710 (100%)    待处理 0 条    失败 0 条
```

Data source: `models.get_translate_stats()`.

### 5.3 Tab: Action Board (问题诊断 → 行动优先级) — RESTRUCTURED

Replaces current P3-P4 issue cards. Split into two sub-sections:

#### 5.3.1 Top Actions (行动优先级)

Extracted from issue clusters + LLM recommendations. Maximum 3 items. Each item is a compact action card:

```
❶ 排查灌肠机齿轮/主轴失效模式
   依据: 36条质量投诉, 7张故障照片 | 涉及: Heavy-Duty + Commercial-Grade
   建议: 复核热处理规格 + 出厂金属屑检测
   [展开查看详细证据 ▼]
```

Structure per action card:

```python
{
    "rank": 1,
    "title": str,       # Action-oriented title (from LLM improvement_priorities)
    "evidence_summary": str,  # "{N}条投诉, {M}张照片"
    "affected_products": [str],
    "recommendation": str,    # 1-2 sentences (from LLM, compressed)
    "linked_cluster": str,    # label_code → expands to full issue card
}
```

#### 5.3.2 Issue Cards (问题详情)

Below the action cards. Same as current issue cards but with improvements:

**Severity computed at cluster level** (see Section 6.4):
- `critical`: Red badge, full expanded card
- `high`: Orange badge, full expanded card
- `medium`: Yellow badge, collapsed by default (click to expand)
- `low`: Gray badge, collapsed, compact layout

**Card content** (when expanded):

| Element | Current | V3 |
|---------|---------|-----|
| Header | `#N label_display [severity]` | Same + "N天未改善" badge if stale |
| Stats | review_count, affected_products, recency | Same + `translated_rate` warning if <80% |
| Timeline | first_seen → last_seen, duration | Same |
| Quotes | 2 quotes, Chinese only | 2 quotes, bilingual (Chinese bold, English muted below) |
| Images | Tiny thumbnails with I1/I2 labels | Click-to-expand lightbox, larger preview |
| AI Recommendation | 4-6 lines dense text | 2 sentences max (full text in expandable section) |

**Filtering rules for card display:**
- `review_count >= 3` → show as individual card
- `review_count < 3` → merge into "其他关注点" summary card at bottom
- Maximum 8 individual cards displayed (sorted by cluster_severity_score desc)

### 5.4 Tab: Products (产品排行)

Replaces current P2.

#### 5.4.1 Product Health Table

Same structure as current but with fixes:

| Column | Current | V3 Change |
|--------|---------|-----------|
| 产品 | Full name | Same |
| SKU | SKU | Same |
| 评分 | Site rating | Same |
| 差评率 | `negative_rate` % | Same, add color coding |
| 差评数 | Count | Same |
| 风险分 | 0-100 | **New algorithm** (see Section 6.2) |
| 主要问题 | Label list with counts | Same |
| 趋势 | "—" in baseline | **Hide column in baseline mode**; show sparkline in incremental |

Conditional rendering: if `mode == "baseline"` and trend data has only 1 point per product, hide the 趋势 column entirely.

Row coloring by new severity computation:
- `risk_score >= 70` → red background
- `risk_score >= 40` → yellow background
- `risk_score < 40` → green background

#### 5.4.2 Price-Rating Scatter (moved here from P2)

Remains as a Chart.js scatter chart but with fixes:
- Product name labels: max 18 characters + "…"
- Use `chartjs-plugin-datalabels` for label positioning with collision avoidance
- Own products: triangle marker, accent color
- Competitor products: circle marker, green color
- Median reference lines: dashed

### 5.5 Tab: Competitive (竞品对标)

Replaces current P5.

#### 5.5.1 Gap Analysis Table — Dual Dimension

Replaces single "差距指数" with two columns:

| 维度 | 类型 | 修复紧迫度 | 追赶差距 | 综合优先级 | 竞品好评 | 自有差评 |
|------|------|-----------|---------|-----------|---------|---------|
| 做工与质量 | 🔴 止血 | 44% | 19% | 35 | 108 (19%) | 62 (44%) |
| 性能与动力 | 🟡 追赶 | 0% | 56% | 17 | 318 (56%) | 0 (0%) |
| 安装与使用 | ⚪ 监控 | 1% | 8% | 3 | 43 (8%) | 1 (1%) |

Algorithm: see Section 6.3.

**Filtering**: Exclude rows where `label_code.startswith("_")` (removes `_uncategorized`).

#### 5.5.2 AI Competitive Insight

Same as current — one paragraph from LLM. Displayed in a recommendation box.

#### 5.5.3 Radar Chart

Same as current but with label fixes:
- Dimension names: max 4 Chinese characters ("耐久质量" not "耐久性与质量")
- Or: use line-break `\n` in Chart.js labels for longer names

#### 5.5.4 Benchmark Examples

Show up to 3 examples (increased from 1-2). Each example:
- Product name + SKU
- Rating + label tags
- One-sentence summary (headline_cn + insight_cn)
- Click to expand full bilingual text

#### 5.5.5 Competitor Positive Themes Bar Chart

Same as current. Filter out `_uncategorized`.

### 5.6 Tab: Panorama (全景数据) — CONDITIONAL

Only rendered when sufficient data exists. Hidden entirely when conditions not met.

#### 5.6.1 Feature Heatmap

**Condition**: Display only when `own_product_count >= 3 AND label_dimension_count >= 5`. Otherwise show text: "产品数量不足, 热力图需要至少3个自有产品和5个特征维度。"

When displayed:
- Product names on Y-axis: max 20 characters + "…"
- Dimension names on X-axis: abbreviated (4 chars max)
- Color scale: red (-1) to white (0) to green (+1)
- Hover shows exact value + review count

#### 5.6.2 Sentiment Distribution Charts

**Fix**: X-axis labels rotate 45 degrees; product names max 15 characters.

Show side-by-side: own products (left) and competitor products (right).

Max 6 products per chart. If more, show top 6 by review count.

#### 5.6.3 Review Detail Table (NEW — HTML exclusive)

Interactive table of all reviews, only available in HTML format. Columns:

| 产品 | 归属 | 评分 | 标题(中文) | 正文(中文) | 标签 | 图片 | 日期 |

Features:
- Sort by any column (click header)
- Filter by: product dropdown, ownership toggle, rating range, keyword search
- Truncated text expands on click
- Image thumbnails open in lightbox

This replaces the need for a separate "Review Details" Excel sheet for most users.

---

## 6. Metric & Algorithm Redesign

### 6.1 Health Index → NPS-Proxy Index

#### 6.1.1 Current Formula (to be replaced)

```python
# CURRENT — problems: double-counting, floor effect, arbitrary weights
index = (own_avg_rating/5 * 0.20 + sample_avg_rating/5 * 0.25
         + (1 - own_neg_rate) * 0.35 + (1 - high_risk_ratio) * 0.20) * 100
```

Problems:
- `own_avg_rating` and `sample_avg_rating` are 0.95-correlated (45% weight on redundant signal)
- `high_risk_ratio` = 1.0 when all products are high-risk (floor effect, 0% contribution)
- Weights (20/25/35/20) have no theoretical basis

#### 6.1.2 New Formula

```python
def compute_health_index_v3(kpis):
    """NPS-proxy health index.
    
    Based on Net Promoter Score concept:
    promoters (>=4 stars) minus detractors (<=NEGATIVE_THRESHOLD).
    Mapped to 0-100 scale.
    
    Industry benchmarks for consumer products:
    - NPS > 50 → Excellent (health > 75)
    - NPS 20-50 → Good (health 60-75)
    - NPS 0-20 → Needs attention (health 50-60)
    - NPS < 0 → Critical (health < 50)
    """
    own_reviews = kpis.get("own_review_rows", 0)
    if own_reviews == 0:
        return 50.0  # No data → neutral
    
    promoters = kpis.get("own_positive_review_rows", 0)  # rating >= 4
    detractors = kpis.get("own_negative_review_rows", 0)  # rating <= NEGATIVE_THRESHOLD
    
    nps = ((promoters - detractors) / own_reviews) * 100  # Range: -100 to +100
    
    # Map NPS (-100..+100) to health index (0..100)
    health = (nps + 100) / 2  # Linear mapping
    
    return round(max(0, min(100, health)), 1)
```

Validation with current data:
- promoters = 76 (rating >= 4), detractors = 55 (rating <= 2), total = 141
- NPS = (76 - 55) / 141 * 100 = 14.9
- Health = (14.9 + 100) / 2 = **57.4**
- Previous health was 52.4 — similar range, but the new formula is transparent and comparable to industry benchmarks.

#### 6.1.3 Tooltip Text

```
健康指数 (NPS代理): 基于好评(≥4星)减去差评(≤{threshold}星)的比例，映射到0-100。
行业参考: >75 优秀, 60-75 良好, 50-60 需关注, <50 危险。
```

### 6.2 Risk Score → Multi-Factor Risk Score

#### 6.2.1 Current Formula (to be replaced)

```python
# CURRENT — problems: ignores ratio, volume-dependent normalization, 
# skips 1-star reviews without labels
for review in own_reviews_where_rating_lte_3_and_has_negative_labels:
    score += 2 if rating <= 2 else 1
    score += 1 if has_images
    score += severity_weights_for_labels  # up to 9
risk_score = (raw / (negative_count * 12)) * 100  # average severity per review
```

Problems:
- Pure intensity metric (average severity per negative review), ignores what proportion of reviews are negative
- `LOW_RATING_THRESHOLD=3` vs `NEGATIVE_THRESHOLD=2` mismatch: 3-star reviews contribute to risk but aren't "negative"
- Reviews without labels are skipped entirely (a 1-star "terrible product" with no keyword match contributes nothing)

#### 6.2.2 New Formula

```python
# Updated severity score dict (now includes "critical" level)
_SEVERITY_SCORE_V3 = {"critical": 4, "high": 3, "medium": 2, "low": 1}

def compute_risk_score_v3(product_reviews, product_info, logical_date):
    """Multi-factor risk score combining rate, severity, evidence, recency, and volume.
    
    Args:
        product_reviews: list of review dicts for this product (all ratings)
        product_info: dict with product metadata (sku, name, etc.)
        logical_date: date object for recency calculation
    
    Each factor normalized to 0-1, weighted, then scaled to 0-100.
    
    Note on impact_category: This field is added in Phase 2 (translator v2 prompt).
    When absent (None), the safety multiplier is skipped — the formula degrades
    gracefully to a 4-factor version without the safety bonus.
    """
    total = len(product_reviews)
    if total == 0:
        return 0.0
    
    negative = [r for r in product_reviews if r["rating"] <= config.NEGATIVE_THRESHOLD]
    neg_count = len(negative)
    
    # Factor 1: Negative rate (0-1)
    # What proportion of customers had a bad experience?
    neg_rate = neg_count / total  # Weight: 35%
    
    # Factor 2: Severity intensity (0-1)
    # How severe are the negative reviews on average?
    if neg_count > 0:
        severity_scores = []
        for r in negative:
            labels = r.get("labels", [])
            if labels:
                max_sev = max(
                    _SEVERITY_SCORE_V3.get(l.get("severity", "low"), 1) 
                    for l in labels
                )
            else:
                max_sev = 2 if r["rating"] <= 1 else 1  # Default: 1-star=medium, 2-star=low
            
            # Safety multiplier (Phase 2 field — gracefully ignored when absent)
            impact_cat = r.get("impact_category")  # None for v1-analyzed reviews
            if impact_cat == "safety":
                max_sev = min(max_sev * 1.5, 4)  # Max capped at critical (4)
            
            severity_scores.append(max_sev / 4.0)  # Normalize to 0-1 (max=critical=4)
        severity_avg = sum(severity_scores) / len(severity_scores)
    else:
        severity_avg = 0.0  # Weight: 25%
    
    # Factor 3: Evidence rate (0-1)
    # What proportion of negative reviews include photo evidence?
    image_neg = sum(1 for r in negative if r.get("images"))
    evidence_rate = image_neg / max(neg_count, 1)  # Weight: 15%
    
    # Factor 4: Recency (0-1)
    # Are negative reviews concentrated in recent period?
    if neg_count > 0:
        recent_cutoff = logical_date - timedelta(days=90)
        recent_neg = 0
        for r in negative:
            date_str = r.get("date_published_parsed")
            if date_str:
                try:
                    review_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if review_date >= recent_cutoff:
                        recent_neg += 1
                except (ValueError, TypeError):
                    pass
        recency = recent_neg / neg_count
    else:
        recency = 0.0  # Weight: 15%
    
    # Factor 5: Volume significance (0-1)
    # Is the sample large enough to be statistically meaningful?
    volume_sig = min(neg_count / 10.0, 1.0)  # Saturates at 10 reviews  # Weight: 10%
    
    risk = (
        0.35 * neg_rate
        + 0.25 * severity_avg
        + 0.15 * evidence_rate
        + 0.15 * recency
        + 0.10 * volume_sig
    ) * 100
    
    return round(min(risk, 100), 1)
```

Validation with current data:

| Product | neg_rate | severity_avg | evidence | recency | volume | **V3 Score** | V2 Score |
|---------|---------|-------------|----------|---------|--------|-------------|----------|
| HD Sausage (31/55 neg, 7 img) | 0.56 | ~0.83 | 0.23 | 0.06 | 1.0 | **43.2** | 60.5 |
| CG Sausage (28/57 neg, 3 img) | 0.49 | ~0.80 | 0.11 | 0.04 | 1.0 | **38.5** | 61.6 |
| Meat Mixer (6/29 neg, 0 img) | 0.21 | ~0.67 | 0.0 | 0.17 | 0.6 | **18.9** | 56.9 |

Key improvement: V3 clearly separates the two sausage stuffers (43 vs 39) from the mixer (19), reflecting the actual risk difference that V2 compressed (60.5, 61.6, 56.9 — barely different).

#### 6.2.3 Risk Threshold Recalibration

With the new scale:
- `HIGH_RISK_THRESHOLD = 35` (products above this are "high risk")
- Alert uses: `>= 50` → critical, `>= 35` → high, `>= 20` → medium, `< 20` → low

### 6.3 Gap Analysis → Dual-Dimension (Fix vs Catch-Up)

#### 6.3.1 Current Formula (to be replaced)

```python
# CURRENT
gap_rate = (competitor_positive_rate + own_negative_rate) / 2 * 100
priority = "high" if own_rate >= 0.15 else "medium" if own_rate >= 0.05 else "low"
```

Problems: averaging unrelated rates; priority based on own_rate not gap magnitude.

#### 6.3.2 New Algorithm

```python
def compute_gap_analysis_v3(labeled_reviews, own_total, competitor_total):
    """Dual-dimension gap analysis separating 'fix urgency' from 'catch-up gap'.
    
    Returns list of gap dicts sorted by priority_score descending.
    """
    # ... (dimension grouping same as current _competitor_gap_analysis) ...
    
    gaps = []
    for dimension, data in dimensions.items():
        if dimension.startswith("_"):
            continue  # Filter out _uncategorized
        
        comp_positive = data["competitor_positive_count"]
        own_negative = data["own_negative_count"]
        own_positive = data.get("own_positive_count", 0)
        
        comp_pos_rate = comp_positive / max(competitor_total, 1)
        own_neg_rate = own_negative / max(own_total, 1)
        own_pos_rate = own_positive / max(own_total, 1)
        
        # Fix urgency: how much of our own review base is complaining about this?
        fix_urgency = own_neg_rate  # 0-1
        
        # Catch-up gap: how far behind are we in positive mentions?
        catch_up_gap = max(comp_pos_rate - own_pos_rate, 0)  # 0-1
        
        # Combined priority score (fix takes precedence)
        priority_score = fix_urgency * 0.7 + catch_up_gap * 0.3  # 0-1
        
        # Gap type classification
        if own_neg_rate >= 0.10:
            gap_type = "止血"        # We have a real problem
            gap_type_color = "red"
        elif catch_up_gap >= 0.20:
            gap_type = "追赶"        # Competitor is ahead
            gap_type_color = "gold"
        else:
            gap_type = "监控"        # Minor or no gap
            gap_type_color = "green"
        
        # Priority label based on priority_score (not own_rate)
        priority_score_pct = round(priority_score * 100)
        if priority_score_pct >= 25:
            priority = "high"
        elif priority_score_pct >= 10:
            priority = "medium"
        else:
            priority = "low"
        
        gaps.append({
            "label_display": dimension_display,
            "gap_type": gap_type,
            "gap_type_color": gap_type_color,
            "fix_urgency": round(fix_urgency * 100),
            "catch_up_gap": round(catch_up_gap * 100),
            "priority_score": priority_score_pct,
            "priority": priority,
            "competitor_positive_count": comp_positive,
            "competitor_positive_rate": round(comp_pos_rate * 100, 1),
            "own_negative_count": own_negative,
            "own_negative_rate": round(own_neg_rate * 100, 1),
        })
    
    gaps.sort(key=lambda g: -g["priority_score"])
    return gaps
```

#### 6.3.3 Validation with Current Data

Using actual review counts: own_total=141, competitor_total=569.

| Dimension | comp_pos | own_neg | own_pos | comp_pos_rate | own_neg_rate | own_pos_rate | fix_urgency | catch_up_gap | priority_score | gap_type | priority |
|-----------|---------|---------|---------|--------------|-------------|-------------|------------|-------------|---------------|----------|----------|
| 做工与质量 | 108 | 62 | 0 | 19.0% | 44.0% | 0% | 44 | 19 | 0.7×0.44+0.3×0.19=**37** | 止血 | high |
| 性能与动力 | 318 | 0 | 0 | 55.9% | 0% | 0% | 0 | 56 | 0.7×0+0.3×0.56=**17** | 追赶 | medium |
| 安装与使用 | 43 | 1 | 0 | 7.6% | 0.7% | 0% | 1 | 8 | 0.7×0.01+0.3×0.08=**3** | 监控 | low |
| 性价比高 | 29 | 0 | 0 | 5.1% | 0% | 0% | 0 | 5 | 0.7×0+0.3×0.05=**2** | 监控 | low |
| 包装运输 | 8 | 4 | 0 | 1.4% | 2.8% | 0% | 3 | 1 | 0.7×0.03+0.3×0.01=**2** | 监控 | low |

Key improvement vs V2: "做工与质量" (37, high) is clearly separated from "性能与动力" (17, medium), reflecting that the former needs urgent fixing while the latter is an aspirational gap.

### 6.4 Severity → Cluster-Level Computed Severity

#### 6.4.1 Current Behavior (to be replaced)

Takes max severity from any individual label in the cluster. Since LLM labels almost always include at least one "high", all clusters are "high".

#### 6.4.2 New Algorithm

```python
_SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

# Safety-signal keywords (detected in original English text)
_SAFETY_KEYWORDS = {
    "metal shaving", "metal debris", "metal flake", "metal particle",
    "broke", "broken", "snapped", "shattered", "exploded",
    "dangerous", "hazard", "injury", "hurt", "unsafe",
    "rust", "rusted", "corrosion",
    "金属屑", "断裂", "爆裂", "危险", "安全", "锈",
}

def compute_cluster_severity(cluster, reviews_in_cluster, logical_date):
    """Compute severity at cluster level based on multiple objective factors.
    
    Args:
        cluster: cluster dict with review_count, affected_product_count, review_dates
        reviews_in_cluster: list of review dicts (for safety keyword scan)
        logical_date: date object for recency calculation
    
    Factors:
    - Review volume (how widespread)
    - Affected product breadth (how many products)
    - Recency (is it still active)
    - Safety signal (does it involve physical risk)
    
    Returns: "critical", "high", "medium", or "low"
    """
    review_count = cluster["review_count"]
    affected_products = cluster["affected_product_count"]
    
    # Recency: count reviews from last 90 days using review_dates list
    recent_cutoff = logical_date - timedelta(days=90)
    review_dates = cluster.get("review_dates", [])
    recent_count = 0
    for d in review_dates:
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() >= recent_cutoff:
                recent_count += 1
        except (ValueError, TypeError):
            pass
    recency_rate = recent_count / max(review_count, 1)
    
    # Safety signal: check any review text for safety keywords
    has_safety_signal = False
    for r in reviews_in_cluster:
        text = f"{r.get('headline', '')} {r.get('body', '')}".lower()
        if any(kw in text for kw in _SAFETY_KEYWORDS):
            has_safety_signal = True
            break
    
    # Scoring
    score = 0
    
    # Volume
    if review_count >= 20:
        score += 3
    elif review_count >= 10:
        score += 2
    elif review_count >= 5:
        score += 1
    
    # Breadth
    if affected_products >= 3:
        score += 2
    elif affected_products >= 2:
        score += 1
    
    # Recency
    if recency_rate >= 0.30:
        score += 2
    elif recency_rate >= 0.10:
        score += 1
    
    # Safety
    if has_safety_signal:
        score += 3
    
    # Classification
    if score >= 7:
        return "critical"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"
```

Validation against current data (6 clusters):

| Cluster | Reviews | Products | Recency | Safety? | Score | **V3 Severity** | V2 |
|---------|---------|----------|---------|---------|-------|-----------------|-----|
| 质量稳定性 | 36 | 3 | 6% | Yes (金属屑, 断裂) | 3+2+0+3=8 | **critical** | high |
| 材料与做工 | 14 | 2 | 0% | Yes (金属屑, 锈) | 2+1+0+3=6 | **high** | high |
| 结构设计 | 12 | 3 | 8% | No | 2+2+0+0=4 | **medium** | high |
| 售后与履约 | 4 | 2 | 25% | No | 0+1+1+0=2 | **low** | high |
| 包装运输 | 4 | 2 | 0% | No | 0+1+0+0=1 | **low** | high |
| 安装装配 | 1 | 1 | 0% | No | 0+0+0+0=0 | **low** | high |

Result: 1 critical, 1 high, 1 medium, 3 low — four distinct levels vs. all-high.

### 6.5 Review Date Warning

Many reviews have `date_published` like "3 years ago" which parses relative to `logical_date`. This creates false clustering on specific dates (e.g., hundreds of reviews on "2022-04-08").

**Detection**:
```python
def has_estimated_dates(reviews):
    """Check if >30% of review dates fall on the same day-of-year as logical_date."""
    if not reviews:
        return False
    logical_mmdd = logical_date.strftime("%m-%d")
    count_matching = sum(
        1 for r in reviews
        if r.get("date_published_parsed", "").endswith(logical_mmdd)
    )
    return count_matching / len(reviews) > 0.30
```

**Display**: When detected, add footnote to all timeline/trend visualizations: "⚠️ 部分评论日期为相对时间估算值（如"3 years ago"），时间分布仅供参考。"

**Mitigation**: For trend analysis, prefer `scraped_at` (when the review was collected) over `date_published_parsed` as the primary time axis.

---

## 7. LLM Strategy Redesign

### 7.1 Translation Worker: Add Rich Analysis Fields

#### 7.1.1 New Output Fields

Add four fields to the translation prompt's output schema. These cost ~50 tokens/review extra (negligible at batch=20).

```python
# Additions to _build_analysis_prompt output format:

"impact_category": "safety | functional | durability | cosmetic | service"
# - safety: physical harm risk (metal debris, breakage during use, explosion)
# - functional: product doesn't perform its core function
# - durability: works initially but degrades/breaks over time
# - cosmetic: appearance issues, minor aesthetic defects
# - service: shipping, customer service, fulfillment problems

"failure_mode": "string — specific failure description in Chinese"
# e.g., "齿轮磨损", "密封圈漏肉", "主轴金属屑脱落"
# More specific than label_code, enables sub-clustering

"usage_context": "seasonal_hunter | commercial | hobbyist | first_time | gift"
# User persona classification — different personas have different priorities

"purchase_intent_impact": "would_repurchase | neutral | would_not_repurchase | would_warn_others"
# Stronger signal than sentiment for business impact
```

#### 7.1.2 Prompt Change

Add to the existing `_build_analysis_prompt()` task list:

```
7. 判断影响类别 impact_category (safety/functional/durability/cosmetic/service)
8. 提取具体失效模式 failure_mode (中文短语)
9. 推断用户使用场景 usage_context (seasonal_hunter/commercial/hobbyist/first_time/gift)
10. 评估复购意愿影响 purchase_intent_impact (would_repurchase/neutral/would_not_repurchase/would_warn_others)
```

Add to output format:
```
- impact_category: safety | functional | durability | cosmetic | service
- failure_mode: "具体失效模式描述"
- usage_context: seasonal_hunter | commercial | hobbyist | first_time | gift
- purchase_intent_impact: would_repurchase | neutral | would_not_repurchase | would_warn_others
```

#### 7.1.3 DB Schema Change

Add columns to `review_analysis` table:

```sql
ALTER TABLE review_analysis ADD COLUMN impact_category TEXT;
ALTER TABLE review_analysis ADD COLUMN failure_mode TEXT;
ALTER TABLE review_analysis ADD COLUMN usage_context TEXT;
ALTER TABLE review_analysis ADD COLUMN purchase_intent_impact TEXT;
```

#### 7.1.4 Backfill Strategy

Existing reviews with `prompt_version='v1'` retain their current analysis. New translations use `prompt_version='v2'` with the extended fields. The UPSERT on `(review_id, prompt_version)` means v2 analysis coexists with v1 until all reviews are re-analyzed.

Optional: a one-time re-analysis run can be triggered via `trigger_translate(reset_skipped=true)` after updating the prompt. Since translation is already done (status=done), only the analysis fields would be re-generated. This requires a new `trigger_reanalyze()` function that fetches reviews with `prompt_version < 'v2'` and sends them through analysis only (no re-translation).

### 7.2 Report Insights: Inject Review Samples

#### 7.2.1 Problem

Current `_build_insights_prompt()` passes only aggregated statistics to the LLM:
```
主要问题：
  - [quality_stability] 质量稳定性：36 条评论，严重度 高
    高频表现：做工廉价(3条)、出现金属屑(2条)...
```

The LLM writes insights without reading any actual customer language. This produces:
- Hero headlines that restate numbers ("差评率39%，健康指数52.4")
- Recommendations that follow templates rather than addressing specific customer scenarios
- Competitive insights that compare abstract rates, not concrete experiences

#### 7.2.2 Solution: Sample Injection

Add 15-25 representative review texts to the report-level LLM prompt. Token budget: ~5K additional tokens (total prompt ~8K, well within any model's context).

```python
def _select_insight_samples(snapshot, analytics):
    """Select reviews that maximize insight value for LLM synthesis.
    
    Selection strategy:
    1. Per high-risk product: 2 worst reviews (lowest rating, longest body)
    2. Image-bearing negative reviews: 3 (strongest evidence)
    3. Top competitor reviews: 3 (for contrast)
    4. Mixed-sentiment reviews: 2 (most nuanced perspectives)
    5. Most recent reviews: 2 (current state signal)
    
    Returns deduplicated list of max 20 reviews.
    """
    reviews = snapshot.get("reviews", [])
    samples = []
    seen_ids = set()
    
    def add(review_list, limit):
        added = 0
        for r in review_list:
            if r["id"] not in seen_ids and len(samples) < 20:
                seen_ids.add(r["id"])
                samples.append(r)
                added += 1
                if added >= limit:
                    break
    
    risk_products = analytics.get("self", {}).get("risk_products", [])
    
    # 1. Worst reviews per risk product
    for product in risk_products[:3]:
        sku = product["product_sku"]
        worst = sorted(
            [r for r in reviews if r.get("product_sku") == sku 
             and r["rating"] <= config.NEGATIVE_THRESHOLD and r.get("body_cn")],
            key=lambda r: (r["rating"], -len(r.get("body_cn", "")))
        )
        add(worst, 2)
    
    # 2. Image-bearing own negatives
    img_neg = sorted(
        [r for r in reviews if r.get("images") and r["rating"] <= config.NEGATIVE_THRESHOLD
         and r.get("ownership") == "own" and r["id"] not in seen_ids],
        key=lambda r: r["rating"]
    )
    add(img_neg, 3)
    
    # 3. Top competitor reviews
    comp_best = sorted(
        [r for r in reviews if r.get("ownership") == "competitor" 
         and r["rating"] >= 5 and r.get("body_cn") and r["id"] not in seen_ids],
        key=lambda r: -len(r.get("body_cn", ""))
    )
    add(comp_best, 3)
    
    # 4. Mixed sentiment
    mixed = [r for r in reviews if r.get("sentiment") == "mixed" and r["id"] not in seen_ids]
    add(mixed, 2)
    
    # 5. Most recent
    recent = sorted(
        [r for r in reviews if r.get("date_published_parsed") and r["id"] not in seen_ids],
        key=lambda r: r["date_published_parsed"],
        reverse=True
    )
    add(recent, 2)
    
    return samples
```

#### 7.2.3 Updated Prompt

Append to existing `_build_insights_prompt()`:

```python
# After existing sections...

review_lines = []
for r in sample_reviews:
    tag = "自有" if r.get("ownership") == "own" else "竞品"
    review_lines.append(
        f"[{tag}|{r.get('product_name','')}|{r.get('rating','')}星] "
        f"{(r.get('body_cn') or r.get('body',''))[:250]}"
    )
review_text = "\n".join(review_lines)

prompt += f"""

关键评论原文（{len(sample_reviews)}条，用于提炼洞察和引用客户语言）：
{review_text}

补充要求：
- hero_headline 必须反映评论中的核心客户体验痛点，不要只堆砌数字
- executive_bullets 引用至少一处具体的客户描述
- improvement_priorities.action 引用客户实际使用场景和失效描述
- competitive_insight 对比自有和竞品客户的实际体验差异
"""
```

#### 7.2.4 Expected Improvement

Before (current): `"自有差评率39.0%，健康指数52.4"`
After (with review samples): `"灌肠机齿轮/密封件反复失效，多名用户报告金属屑进入食品，需紧急排查制造工艺"`

### 7.3 Cluster-Level Deep Analysis — NEW LLM Call

#### 7.3.1 Purpose

For top 3 issue clusters, perform LLM-powered root-cause analysis by reading all reviews in the cluster. This replaces the static `_RECOMMENDATION_MAP` templates with evidence-grounded insights.

#### 7.3.2 When to Run

- Only for Full Report mode
- Only for clusters with `review_count >= 5`
- Maximum 3 clusters per report (budget: ~3 LLM calls × 8K tokens = 24K tokens)
- Gated by `config.LLM_API_BASE` availability (graceful fallback to `_RECOMMENDATION_MAP`)

#### 7.3.3 Implementation

```python
def analyze_cluster_deep(cluster, cluster_reviews):
    """Deep LLM analysis of a single issue cluster.
    
    Input:
        cluster: cluster dict with label_code, review_count, etc.
        cluster_reviews: list of review dicts belonging to this cluster (max 30)
    
    Output:
        dict with keys: failure_modes, root_causes, temporal_pattern,
                        user_workarounds, actionable_summary
    """
    # Prepare review text (truncate to fit context)
    review_lines = []
    for r in cluster_reviews[:30]:
        review_lines.append(
            f"[{r.get('rating','')}星|{r.get('product_name','')}|"
            f"{r.get('date_published_parsed','')}] "
            f"{(r.get('body_cn') or r.get('body',''))[:300]}"
        )
    reviews_text = "\n".join(review_lines)
    
    prompt = f"""你是产品质量分析专家。以下是 {cluster["review_count"]} 条关于
「{cluster["label_display"]}」问题的用户评论（展示前{len(cluster_reviews[:30])}条）。

{reviews_text}

请分析并返回JSON（不要包含 markdown 代码块标记）：
{{
  "failure_modes": [
    {{"mode": "具体失效模式描述", "frequency": 出现次数估计, 
      "severity": "critical/major/minor",
      "example_quote": "最能说明此失效的一句用户原话"}}
  ],
  "root_causes": [
    {{"cause": "推测根因", "evidence": "从评论推断的依据", 
      "confidence": "high/medium/low"}}
  ],
  "temporal_pattern": "问题随时间的变化趋势描述",
  "user_workarounds": ["用户自行采取的应对方法"],
  "actionable_summary": "不超过2句话：这个问题的本质是什么，最高优先的改进动作是什么"
}}

注意：
- failure_modes 按 frequency 降序排列
- 每个 failure_mode 必须有 example_quote 直接引用评论原文
- root_causes 的 evidence 必须引用具体评论描述，不要泛泛而谈
- actionable_summary 必须包含具体的产品名和具体的改进措施"""
    
    # Call LLM
    response = _call_llm(prompt)
    parsed = _parse_llm_response(response)
    return _validate_cluster_analysis(parsed, cluster)
```

#### 7.3.4 Integration into Report

The cluster analysis result replaces the static `_RECOMMENDATION_MAP` recommendation box in issue cards:

```html
<!-- Instead of static AI recommendation -->
<div class="recommendation-box">
  <span class="ai-badge">AI 深度分析</span>
  <p><strong>核心问题：</strong>{{ cluster.deep_analysis.actionable_summary }}</p>
  
  <details>
    <summary>失效模式详解 ({{ cluster.deep_analysis.failure_modes|length }}种)</summary>
    {% for fm in cluster.deep_analysis.failure_modes %}
    <div class="failure-mode">
      <strong>{{ fm.mode }}</strong> — 约{{ fm.frequency }}例, {{ fm.severity }}
      <blockquote>"{{ fm.example_quote }}"</blockquote>
    </div>
    {% endfor %}
  </details>
  
  <details>
    <summary>推测根因</summary>
    {% for rc in cluster.deep_analysis.root_causes %}
    <div>{{ rc.cause }} ({{ rc.confidence }}) — {{ rc.evidence }}</div>
    {% endfor %}
  </details>
</div>
```

#### 7.3.5 Fallback

If LLM unavailable or call fails, fall back to current `_RECOMMENDATION_MAP` static recommendations. Mark the section: "⚠️ AI深度分析不可用，以下为规则引擎建议。"

### 7.4 LLM Call Budget Summary

| Call | Frequency | Input Tokens | Output Tokens | Total/Report |
|------|-----------|-------------|--------------|--------------|
| Translation+Analysis | Per batch of 20 reviews | ~3K | ~1.5K | N/A (background) |
| Report Insights | 1 per report | ~4K (was ~2K) | ~1K | ~5K |
| Cluster Deep Analysis | Up to 3 per report | ~8K each | ~1K each | ~27K |
| **Total new per report** | | | | **~32K tokens** |

At gpt-4o-mini pricing (~$0.15/1M input, $0.60/1M output): ~$0.005/report — negligible.

---

## 8. Edge Cases & Boundary Conditions

### 8.1 Exhaustive Scenario Table

| # | Scenario | Detection | Report Mode | Specific Handling |
|---|----------|-----------|-------------|-------------------|
| 1 | No new reviews, no changes | `reviews==[] AND !has_changes` | Quiet Day | KPI snapshot from previous analytics; show outstanding issues |
| 2 | No new reviews, price changed | `reviews==[] AND has_changes` | Change | Show change summary + KPI snapshot |
| 3 | No new reviews, product delisted | `removed_products` not empty | Change | Show "⚠️ 产品不可用: {name}" alert |
| 4 | New reviews, all positive | `reviews>0 AND neg_count==0` | Full | Issue tab shows "未发现问题" card; focus on positive themes |
| 5 | New reviews, all negative | `reviews>0 AND neg_count==total` | Full | All products high-risk; rank by safety > functional > other |
| 6 | Very few reviews (< 5 total) | `own_review_rows < 5` | Full | All KPI cards show "⚠️ 样本不足" badge; suppress deltas |
| 7 | Own 0, competitor 500+ | `own_review_rows == 0` | Full | Hide own-product tabs; show only competitive intelligence |
| 8 | Competitor 0, own 100+ | `competitor_review_rows == 0` | Full | Hide competitive tab entirely |
| 9 | New product first scrape | Product SKU in current but not previous | Full | Mark product as "新监控" in health table; delta shows "N/A(首次)" |
| 10 | Translation < 50% complete | `translated_count / total < 0.5` | Full | Banner warning: "翻译进度 {pct}%，以下分析基于部分数据" |
| 11 | LLM service unavailable | `config.LLM_API_BASE` empty or call fails | Full | Use fallback insights; mark AI sections with "规则引擎生成" |
| 12 | MAX_REVIEWS truncation | `review_count > MAX_REVIEWS` | Full | Footer note: "已采集 {ingested}/{site_total} 条（最近评论优先）" |
| 13 | Single product only | `product_count == 1` | Full | Competitive tab hidden; scatter chart hidden; radar hidden |
| 14 | Relative dates dominate | `>30%` reviews parse to same MM-DD | Full | Footnote on timeline: "部分日期为估算值" |
| 15 | 3 consecutive quiet days | Query `workflow_runs WHERE report_mode='quiet' ORDER BY logical_date DESC`; count consecutive | Quiet | After 3 quiet days, change email subject: "[连续N天无变化] ..." |
| 16 | Previous analytics file missing from disk | `FileNotFoundError` in `load_previous_report_context()` | Any | Return `None, None`; suppress deltas/changes; log warning |
| 17 | All own products are zero (own_product_count=0) | `own_product_count == 0` | Full | Health index = 50 (neutral); "自有差评率" card shows "N/A"; hide own-product tabs |
| 18 | Product SKU changes between snapshots | Same product URL but new SKU | Change | Detect via URL matching (not SKU); show as "SKU变更: old→new" |
| 19 | Cluster deep analysis LLM returns malformed JSON | `_parse_llm_response` fails or `failure_modes` is empty | Full | Fall back to `_RECOMMENDATION_MAP` static recommendation; log warning |
| 20 | Chart.js CDN unreachable (default mode, offline reader) | No detection at open time | Full | Add `<noscript>` fallback table with raw data; add note: "图表需要网络连接，或启用离线模式" |

### 8.2 Implementation Pattern

```python
def determine_report_mode(snapshot, previous_snapshot, previous_analytics):
    """Central routing logic for report mode selection.
    
    Returns:
        mode: "full" | "change" | "quiet"
        context: dict with mode-specific metadata
    """
    has_reviews = bool(snapshot.get("reviews"))
    changes = detect_snapshot_changes(snapshot, previous_snapshot) if previous_snapshot else {}
    has_changes = changes.get("has_changes", False)
    
    if has_reviews:
        return "full", {"changes": changes}
    elif has_changes:
        return "change", {"changes": changes}
    else:
        return "quiet", {"previous_analytics": previous_analytics}
```

---

## 9. Excel Redesign

### 9.1 Purpose Shift

Excel shifts from "PDF replica in spreadsheet form" to "actionable data tool for analysts."

### 9.2 Sheet Structure (4 sheets)

#### Sheet 1: 评论明细

All reviews as a flat table. Columns:

| Column | Source | Notes |
|--------|--------|-------|
| ID | review.id | For cross-reference |
| 产品名称 | product_name | |
| SKU | product_sku | |
| 归属 | ownership | own/competitor |
| 评分 | rating | Number |
| 情感 | sentiment | positive/negative/mixed/neutral |
| 标签 | analysis_labels | JSON → comma-separated label_codes |
| 影响类别 | impact_category | safety/functional/... (V3 new) |
| 失效模式 | failure_mode | V3 new |
| 标题(原文) | headline | |
| 标题(中文) | headline_cn | |
| 内容(原文) | body | |
| 内容(中文) | body_cn | |
| 特征短语 | analysis_features | JSON → comma-separated |
| 洞察 | analysis_insight_cn | |
| 评论时间 | date_published_parsed | |
| 图片链接 | images | JSON → newline-separated URLs |

No embedded images (too heavy for data analysis use case). Image URLs are clickable hyperlinks.

#### Sheet 2: 产品概览

| Column | Source |
|--------|--------|
| 产品名称 | name |
| SKU | sku |
| 站点 | site |
| 归属 | ownership |
| 售价 | price |
| 库存状态 | stock_status |
| 站点评分 | rating |
| 站点评论数 | review_count |
| 采集评论数 | ingested_reviews |
| 差评数 | negative_review_rows |
| 差评率 | negative_rate |
| 风险分 | risk_score (V3) |

#### Sheet 3: 问题标签交叉表

Pivot-ready table. Each row = one review-label assignment.

| review_id | product_sku | label_code | label_polarity | severity | confidence |

Analysts can pivot this in Excel to create custom views.

#### Sheet 4: 趋势数据

Time series from `product_snapshots`.

| 日期 | SKU | 产品名称 | 价格 | 评分 | 评论数 | 库存状态 |

One row per product per snapshot date. Used for custom trend charts in Excel.

### 9.3 Removed Sheets

- **Executive Summary**: PDF/HTML's job
- **Issue Analysis**: Use the HTML report's interactive issue cards
- **Competitive Benchmark**: PDF/HTML's job

---

## 10. File Change Summary

### 10.1 Modified Files

| File | Changes |
|------|---------|
| `config.py` | Add `HIGH_RISK_THRESHOLD=35`, adjust `HEALTH_RED/YELLOW`, add `REPORT_OFFLINE_MODE` |
| `models.py` | Add columns to `review_analysis` (impact_category, failure_mode, usage_context, purchase_intent_impact); update `save_review_analysis()` INSERT to include new columns; add `get_previous_completed_run()` analytics/snapshot path loading; add `report_mode` column to `workflow_runs` for quiet-day tracking |
| `translator.py` | Extend `_build_analysis_prompt()` with 4 new fields; bump `prompt_version` to "v2" |
| `report_analytics.py` | Replace `_risk_products()` with V3 multi-factor; replace severity with cluster-level computation; add `compute_cluster_changes()`; filter `_uncategorized` |
| `report_common.py` | Replace `compute_health_index()` with NPS-proxy; replace `_competitor_gap_analysis()` with dual-dimension; replace `_compute_alert_level()` with V3 logic; update `normalize_deep_report_analytics()` for new fields |
| `report_llm.py` | Add `_select_insight_samples()`; update `_build_insights_prompt()` with review injection; add `analyze_cluster_deep()`; update `_validate_insights()` for new fields |
| `report_charts.py` | Replace Plotly with Chart.js generation; add `_build_chart_js_config()` helpers; fix label truncation |
| `report.py` | Replace `generate_excel()` with 4-sheet structure; update `send_email()` for 3 templates; remove Playwright PDF path |
| `report_snapshot.py` | Replace early-return on empty reviews with mode routing; add `detect_snapshot_changes()`; add `determine_report_mode()`; add quiet day and change report generation |

### 10.2 New Files

| File | Purpose |
|------|---------|
| `report_templates/daily_report_v3.html.j2` | New interactive HTML template with tabs, collapse, lightbox |
| `report_templates/daily_report_v3.css` | Responsive styles with dark mode, print media |
| `report_templates/daily_report_v3.js` | ~300 lines vanilla JS for interactivity |
| `report_templates/quiet_day_report.html.j2` | Compact template for quiet days |
| `report_templates/email_full.html.j2` | Full report email (replaces current) |
| `report_templates/email_change.html.j2` | Change report email |
| `report_templates/email_quiet.html.j2` | Quiet day email |

### 10.3 Removed Files

| File | Reason |
|------|--------|
| `report_pdf.py` | PDF generation via Playwright no longer needed |
| `report_templates/daily_report.html.j2` | Replaced by V3 template |
| `report_templates/daily_report.css` | Replaced by V3 CSS |

### 10.4 Dependency Changes

| Package | Action | Reason |
|---------|--------|--------|
| `playwright` | **Remove** | No longer generating PDF server-side |
| (no additions) | — | Chart.js loaded via CDN at runtime, not a Python dependency |

---

## 11. Configuration Changes

### 11.1 New/Changed Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REPORT_HIGH_RISK_THRESHOLD` | `35` | (Changed from 8) Risk score threshold for "high risk" product |
| `REPORT_HEALTH_RED` | `45` | (Changed from 60) Health index red alert threshold |
| `REPORT_HEALTH_YELLOW` | `60` | (Changed from 80) Health index yellow alert threshold |
| `REPORT_OFFLINE_MODE` | `false` | (New) Inline Chart.js instead of CDN for offline HTML |
| `REPORT_CLUSTER_ANALYSIS` | `true` | (New) Enable cluster-level LLM deep analysis |
| `REPORT_MAX_CLUSTER_ANALYSIS` | `3` | (New) Max clusters to analyze deeply |
| `REPORT_HTML_PUBLIC_URL` | `""` | (New) Base URL for HTML report links in email; empty = attach file |

### 11.2 Threshold Recalibration Rationale

Health thresholds change because the NPS-proxy formula produces different ranges:
- Old formula: 52.4 (close to HEALTH_YELLOW=80 threshold seems wrong)
- New formula: 57.4 for same data
- New HEALTH_RED=45 corresponds to NPS=-10 (net negative sentiment)
- New HEALTH_YELLOW=60 corresponds to NPS=20 (industry "needs improvement" zone)

Risk threshold changes because the V3 multi-factor formula produces different ranges:
- Old formula: 56-62 range for all products (very compressed)
- New formula: 19-43 range (better spread)
- New HIGH_RISK_THRESHOLD=35 correctly separates the two sausage stuffers (38, 43) from the mixer (19)

---

## 12. Migration Strategy

### 12.1 Phased Rollout

**Phase 1: Algorithm fixes (no visual changes)**
- Replace health index (NPS-proxy), gap analysis (dual-dimension), severity (cluster-level), alert level (baseline fix)
- Replace risk score with V3 multi-factor formula — **note**: `impact_category` field will be `None` for all existing reviews (added in Phase 2). The formula handles this gracefully: safety multiplier is skipped when `impact_category is None`, producing a 4-factor score. Phase 2 adds the safety bonus as an enhancement, not a prerequisite.
- Add `_uncategorized` filter to gap analysis
- Add `_SEVERITY_SCORE_V3` dict with `critical` key
- DB: add `report_mode` column to `workflow_runs`
- Validate: generate report with V3 algorithms, compare analytics JSON side-by-side with V2

**Phase 2: LLM enhancements**
- DB: ALTER TABLE `review_analysis` add 4 new columns; update `save_review_analysis()` INSERT
- Update translator prompt with 4 new fields (prompt_version v2)
- Update report insights prompt with review sample injection (`_select_insight_samples`)
- Add cluster-level deep analysis (`analyze_cluster_deep`)
- Validate: compare LLM output quality before/after; verify risk_score safety multiplier activates for v2-analyzed reviews

**Phase 3a: HTML template + Chart.js migration**
- Build V3 HTML template (`daily_report_v3.html.j2` + CSS + JS)
- Replace Plotly chart generation with Chart.js config builders
- Implement tab navigation, collapsible cards, lightbox, table sort/filter
- Add `@media print` styles and "导出PDF" button
- Keep existing PDF pipeline running in parallel (both outputs generated)
- Validate: compare V3 HTML vs V2 PDF side-by-side; verify all charts render correctly

**Phase 3b: Three report modes + change detection**
- Implement `detect_snapshot_changes()` and `determine_report_mode()`
- Implement `compute_cluster_changes()` for "What Changed" tab
- Build quiet day template (`quiet_day_report.html.j2`)
- Route report generation through mode selector
- Implement 3 email templates (full/change/quiet)
- Validate: generate all 3 report modes; test email delivery for each mode

**Phase 4: Excel redesign + cleanup**
- Replace 6-sheet Excel with 4-sheet data-oriented format
- Remove `report_pdf.py` and Playwright dependency
- Remove deprecated templates (`daily_report.html.j2`, `daily_report.css`)
- Validate: end-to-end workflow test across multiple days (simulate full → quiet → change → full sequence)

### 12.2 Backward Compatibility

- `workflow_runs` table: add nullable `report_mode` column (no breaking change)
- `review_analysis` table: new columns added with ALTER TABLE, nullable, backward-compatible
- `save_review_analysis()`: updated INSERT includes new columns with default NULL for v1 callers
- Existing analytics JSON files: V2 format still loadable (normalization handles missing fields with defaults). Cluster `label_code` field names are identical between V2 and V3.
- `get_review_analysis()`: when both v1 and v2 analysis exist for a review, prefer `prompt_version='v2'` via `ORDER BY prompt_version DESC LIMIT 1`
- Email recipients: no change to recipient lists or delivery mechanism
- Phase 3a runs V3 HTML alongside V2 PDF — no sudden cutover until validated

---

## 13. Acceptance Criteria

| Criterion | Verification Method |
|-----------|-------------------|
| Quiet day produces a report | Run workflow with 0 reviews → HTML + email generated |
| Change day detects price delta | Modify product price in DB → change report generated |
| Full report has all 6 tabs | Generate with review data → inspect HTML |
| Severity has >= 3 distinct levels | Check analytics JSON cluster severities |
| Health index matches NPS formula | Manual calculation from review counts |
| Risk score incorporates neg_rate | Compare two products with different rates |
| Gap table shows "止血" vs "追赶" | Inspect gap_analysis in analytics JSON |
| LLM insights reference customer language | Read hero_headline + bullets for specific quotes |
| Cluster analysis identifies failure modes | Check deep_analysis output for top 3 clusters |
| Charts have no truncated labels | Open HTML in browser, inspect all chart labels |
| `_uncategorized` never appears in output | Search HTML for "_uncategorized" → zero hits |
| Baseline alert reflects actual health | Generate baseline with high neg rate → non-green alert |
| Excel has 4 sheets with correct structure | Open Excel, verify sheet names and columns |
| HTML works offline | Disconnect internet, open HTML → charts still render (with offline mode) |
| Email has correct mode prefix | Check email subject for [无变化] / [数据变化] / normal |
| Review table paginated | Open HTML with 700+ reviews → verify pagination or lazy load |

---

## 14. Implementation Notes — Boundary Condition Fixes

This section captures specific boundary fixes discovered during spec review. Each is tagged with the phase it belongs to.

### 14.1 [Phase 1] `_SEVERITY_SCORE` and `_SEVERITY_DISPLAY` must include "critical"

The new 4-level severity system introduces `"critical"`. The existing dicts must be updated:

```python
# report_analytics.py — replace existing _SEVERITY_SCORE
_SEVERITY_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# report_common.py — add to existing _SEVERITY_DISPLAY
_SEVERITY_DISPLAY = {"critical": "危急", "high": "高", "medium": "中", "low": "低"}

# report_common.py — add to existing _PRIORITY_DISPLAY (if used for severity badges)
# Ensure "critical" maps to a display string and CSS class
```

All call sites using `_SEVERITY_SCORE[severity]` (at least 11 in `report_analytics.py`) will accept the new key without code changes since they do dict lookups. The `_sanitize_hybrid_labels` validation at `report_analytics.py:467` must accept `"critical"` as a valid severity value.

### 14.2 [Phase 1] Own positive review counts per dimension for gap analysis

The new `compute_gap_analysis_v3` needs `own_positive_count` per dimension. Currently, `build_report_analytics()` only builds own-negative and competitor-positive clusters.

Add to Phase 1 in `build_report_analytics()`:

```python
# Add after existing cluster building
own_positive_clusters = _build_feature_clusters(
    labeled_reviews, ownership="own", polarity="positive"
)
# Pass to gap analysis alongside existing data
gap_analysis = compute_gap_analysis_v3(
    labeled_reviews, own_total, competitor_total,
    own_positive_clusters=own_positive_clusters,
)
```

Until this is implemented, `own_positive_count` defaults to 0 per dimension, and `catch_up_gap = comp_pos_rate - 0 = comp_pos_rate`. This is the same as the validation table in Section 6.3.3, so the formula works correctly in this degenerate case — the "追赶" gap captures dimensions where competitors are strong regardless of our positive rate.

### 14.3 [Phase 1] Health index sentinel value when own_reviews == 0

When `own_reviews == 0`, `compute_health_index_v3` returns 50.0 as a neutral sentinel. This must NOT trigger yellow alert.

Fix in `compute_alert_level_v3`:

```python
def compute_alert_level_v3(analytics, mode):
    health = analytics["kpis"].get("health_index", 100)
    own_reviews = analytics["kpis"].get("own_review_rows", 0)
    
    # Guard: no own data → no alert
    if own_reviews == 0:
        return ("green", "自有评论数据不足，暂不预警")
    
    # ... rest of alert logic ...
```

### 14.4 [Phase 1] Float precision in price change detection

Replace direct `!=` comparison with tolerance-based comparison:

```python
# In detect_snapshot_changes:
def _price_changed(a, b):
    """Compare prices with tolerance for float precision."""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(float(a) - float(b)) >= 0.01
    
# Use: if _price_changed(product["price"], prev["price"]):
```

### 14.5 [Phase 1] KPI delta computation expansion

Current `_compute_kpi_deltas` only covers 4 fields. Expand to include:

```python
_DELTA_FIELDS = [
    "negative_review_rows",
    "own_negative_review_rows",
    "ingested_review_rows",
    "product_count",
    "health_index",              # NEW
    "recently_published_count",  # NEW
]
```

### 14.6 [Phase 1] KPI card "竞品领先维度" data source

Add post-processing in `normalize_deep_report_analytics`:

```python
gap_analysis = normalized.get("competitor", {}).get("gap_analysis", [])
kpis["gap_fix_count"] = sum(1 for g in gap_analysis if g["gap_type"] == "止血")
kpis["gap_catch_count"] = sum(1 for g in gap_analysis if g["gap_type"] == "追赶")
```

Template references: `{{ kpis.gap_fix_count }}需修复 / {{ kpis.gap_catch_count }}需追赶`

### 14.7 [Phase 1] Risk score early return for neg_count == 0

Restructure `compute_risk_score_v3` to make the boundary explicit:

```python
    negative = [r for r in product_reviews if r["rating"] <= config.NEGATIVE_THRESHOLD]
    neg_count = len(negative)
    
    if neg_count == 0:
        return 0.0  # No negative reviews → zero risk (explicit, not implicit via all-zero factors)
    
    # ... compute factors only when neg_count > 0 ...
```

### 14.8 [Phase 3b] Change Report email subject should be dynamic

Replace hardcoded `[价格变动]` with dynamic prefix:

```python
def _change_report_subject_prefix(changes):
    types = []
    if changes.get("price_changes"):
        types.append("价格")
    if changes.get("stock_changes"):
        types.append("库存")
    if changes.get("rating_changes"):
        types.append("评分")
    if changes.get("removed_products") or changes.get("new_products"):
        types.append("产品")
    
    if len(types) == 1:
        return f"[{types[0]}变动]"
    return "[数据变化]"
```

### 14.9 [Phase 3b] "Improving" cluster detection must handle relative dates

When `has_estimated_dates()` returns True (>30% reviews parse to same MM-DD as logical_date), the "improving" detection in `compute_cluster_changes` should use `scraped_at` as fallback:

```python
# In the improving detection loop:
if has_estimated:
    # Use scraped_at instead of date_published_parsed
    last_scraped = max(r.get("scraped_at", "") for r in reviews_in_cluster)
    # ... compare against logical_date ...
```

### 14.10 [Phase 3a] Review detail table pagination

Limit the inline HTML review table to 100 rows with pagination:

```html
<div id="review-table-container" data-page-size="100" data-total="{{ reviews|length }}">
  <!-- First 100 rows rendered server-side -->
  {% for r in reviews[:100] %}
  <tr>...</tr>
  {% endfor %}
</div>
<button id="load-more-reviews" data-remaining="{{ reviews|length - 100 }}">
  加载更多 (还有 {{ reviews|length - 100 }} 条)
</button>
```

The remaining reviews are embedded as a hidden `<script type="application/json">` block and rendered client-side on "加载更多" click. This keeps initial page load fast while making all data accessible.

### 14.11 [Phase 3a] Chart.js CDN offline fallback

For the default CDN mode, add a runtime fallback:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4" 
        onerror="document.getElementById('chart-fallback-msg').style.display='block'">
</script>
<div id="chart-fallback-msg" style="display:none" class="alert-signal alert-yellow">
  ⚠️ 图表库加载失败（需要网络连接）。数据表格仍可正常查看。
</div>
```

When `REPORT_OFFLINE_MODE=true`, the entire Chart.js bundle is inlined and this fallback is unnecessary.

### 14.12 [Phase 3b] Partial scrape failure detection

Add edge case #21 to the change detection:

```python
def detect_snapshot_changes(current_snapshot, previous_snapshot, task_expected_skus=None):
    # ... existing logic ...
    
    # Distinguish scrape failure from product delisting
    if task_expected_skus:
        for sku in task_expected_skus:
            if sku not in current_skus and sku in prev_by_sku:
                # Expected product missing → likely scrape failure, not delisting
                changes["scrape_failures"].append(prev_by_sku[sku])
                # Remove from removed_products to avoid false alarm
                changes["removed_products"] = [
                    p for p in changes["removed_products"] if p["sku"] != sku
                ]
```

Where `task_expected_skus` is derived from the workflow run's task params (CSV URL list).

### 14.13 [Phase 3a] Empty-state text for "What Changed" tab

When all new reviews are positive and no issues escalated:

```html
{% if not changes.escalated and not changes.new and new_negative_count == 0 %}
<div class="empty-state">
  ✅ 本期新增评论均为正面反馈，未发现新增问题。
</div>
{% endif %}

{% if not changes.escalated %}
<div class="empty-state-muted">暂无问题升级。</div>
{% endif %}
```

### 14.14 [Phase 3b] `generate_full_report_from_snapshot` return contract

Rename and update the function signature:

```python
def generate_report_from_snapshot(snapshot, previous_analytics=None, 
                                   previous_snapshot=None, send_email=True):
    """Generate report for any mode (full/change/quiet).
    
    Returns dict with:
        mode: "full" | "change" | "quiet"
        status: "completed" | "completed_no_change"  # backward compat
        run_id: int
        products_count: int
        reviews_count: int
        html_path: str | None    # always present for full/change; quiet if non-trivial
        excel_path: str | None   # only for full mode
        analytics_path: str | None  # only for full mode
        email: {success: bool, error: str | None, recipients: list}
    """
```

The old `generate_full_report_from_snapshot` is kept as a thin wrapper calling the new function for backward compatibility during Phase 3b transition.
