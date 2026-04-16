# P007 — 双视角报告架构升级（累积全景 + 今日增量）

> **关联需求**：解决"基线后失明"——用户第一天看到全貌，后续只能看到日增量碎片
> **前置条件**：P006（报告 Bug 修复）完成
> **优先级**：P0
> **预估工作量**：4-5 天
> **参考实践**：Brandwatch, ReviewTrackers, Yotpo 等产品监控平台的日报设计

---

## 问题陈述

### 当前架构

```
每日采集 → 仅新增评论入库（UPSERT 去重）
         → 快照仅含当日 24h 窗口数据
         → 全部分析（KPI/风险/聚类/差距/图表）基于窗口计算
```

### 后果

| 维度 | 基线日（首次，2577 评论） | 第 N 天（2 条新评论） | 问题 |
|------|------------------------|---------------------|------|
| 自有评论数 | 1610 | 1 | 看不到历史 |
| 健康指数 | 95.0（稳健） | 51.7*（修正后） | 单日波动剧烈 |
| 风险产品 | 12 个（2 高风险） | 0 个 | 高风险产品"消失" |
| 竞品差距 | 5（差距小） | null*（样本不足） | 指标失效 |
| 雷达图/热力图 | 完整分布 | 仅 1-2 维度 | 图表价值归零 |
| 聚类分析 | 完整问题谱 | 0-1 个聚类 | 看不到问题全貌 |
| 风险评分 | volume_sig=1.0 | volume_sig≈0 | 评分公式对窗口敏感 |

*表示 P006 修复后的行为

### 核心矛盾

报告的分析维度（风险评分、健康指数、竞品差距、聚类分析、雷达图/热力图）都是为**大样本**设计的，但日增量窗口通常只有 **0~5 条**新评论。

---

## 设计方案

### 核心思路：双层数据 + 双份分析

```
┌─────────────────────────────────────────────┐
│ 每日报告                                      │
│                                               │
│  ┌─ 累积视角（Cumulative）──────────────┐     │
│  │  数据源：全量 DB（products + reviews）  │     │
│  │  用途：核心 KPI、风险排行、聚类分析、  │     │
│  │        竞品差距、图表、LLM 分析        │     │
│  │  特点：稳定、有统计意义               │     │
│  └──────────────────────────────────────┘     │
│                                               │
│  ┌─ 增量视角（Window）─────────────────┐     │
│  │  数据源：当日 24h 窗口的新增数据       │     │
│  │  用途：今日新增评论、价格变动、库存变化 │     │
│  │  特点：突出当天变化、引起注意          │     │
│  └──────────────────────────────────────┘     │
│                                               │
│  Delta = 今日累积 - 昨日累积                   │
│  （反映因新增数据引起的真实变化趋势）          │
└─────────────────────────────────────────────┘
```

### 数据规模评估

基于生产数据库（2026-04-15 快照）：

| 表 | 行数 | 预估内存 | 查询耗时 |
|----|------|---------|---------|
| products | 41 | ~20 KB | <1ms |
| reviews | 2,579 | ~1.5 MB | ~5ms |
| review_analysis | 2,579 | ~500 KB | ~3ms |
| review_issue_labels | 5,311 | ~200 KB | ~2ms |
| product_snapshots | 123 | ~10 KB | <1ms |

**结论**：当前规模下全量查询毫秒级完成，无需预聚合或缓存。直接运行时双查询即可。

**未来扩展**（评论达到 10 万级别时）：
- 累积视角改为只存统计摘要（不含评论原文）
- 聚类和风险评分基于预聚合的每日 rollup 表
- 评论原文按需从 DB 分页查询

---

## 实施步骤

### Step 1：数据层——新增累积查询函数

**文件**：`qbu_crawler/server/report.py` + `qbu_crawler/models.py`

**新增函数**：

```python
# report.py
def query_cumulative_data() -> tuple[list[dict], list[dict]]:
    """
    查询全量产品（最新状态）和全量评论（含 review_analysis 分析结果）。
    用于累积视角分析。不接受时间参数——就是所有数据。
    """
    conn = models.get_conn()
    try:
        # 产品：products 表本身是 UPSERT 最新值
        products = conn.execute("""
            SELECT url, name, sku, price, stock_status, rating,
                   review_count, scraped_at, site, ownership
            FROM products
            ORDER BY site, name
        """).fetchall()

        # 评论：全量 + LEFT JOIN review_analysis
        reviews = conn.execute("""
            SELECT r.id, p.name AS product_name, p.sku AS product_sku,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.date_published_parsed,
                   r.images, p.ownership,
                   r.headline_cn, r.body_cn, r.translate_status,
                   ra.sentiment, ra.labels AS analysis_labels,
                   ra.features AS analysis_features,
                   ra.insight_cn, ra.insight_en,
                   ra.impact_category, ra.failure_mode
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            LEFT JOIN review_analysis ra
                ON ra.review_id = r.id
            ORDER BY r.scraped_at DESC
        """).fetchall()

        return _to_dict_list(products), _to_dict_list(reviews)
    finally:
        conn.close()
```

**替代方案**：复用已有的 Scope 系统：

```python
from qbu_crawler.server.scope import Scope, WindowScope
# 空 Scope = 无时间过滤 = 累积
cumulative_products, cumulative_reviews = query_scope_report_data(Scope())
```

需确认 `query_scope_report_data()` 是否包含 `review_analysis` JOIN。如果不包含，需要扩展或单独写。

---

### Step 2：快照层——双层快照结构

**文件**：`qbu_crawler/server/report_snapshot.py`

**改造 `freeze_report_snapshot()`**：

```python
def freeze_report_snapshot(run: dict) -> dict:
    # === 原有：窗口数据 ===
    window_products, window_reviews = report.query_report_data(
        run["data_since"], until=run["data_until"])
    window_reviews = _enrich_reviews_with_analysis(window_reviews)

    # === 新增：累积数据 ===
    cum_products, cum_reviews = report.query_cumulative_data()
    # cum_reviews 已含 review_analysis 字段（JOIN 获取）

    snapshot = {
        # 元数据
        "run_id": run["id"],
        "logical_date": run["logical_date"],
        "data_since": run["data_since"],
        "data_until": run["data_until"],
        "snapshot_at": now_shanghai().isoformat(),

        # 窗口层（今日增量）
        "products": window_products,
        "reviews": window_reviews,
        "products_count": len(window_products),
        "reviews_count": len(window_reviews),
        "translated_count": sum(1 for r in window_reviews if r.get("translate_status") == "done"),
        "untranslated_count": sum(1 for r in window_reviews if r.get("translate_status") != "done"),

        # 累积层（全景）
        "cumulative": {
            "products": cum_products,
            "reviews": cum_reviews,
            "products_count": len(cum_products),
            "reviews_count": len(cum_reviews),
            "translated_count": sum(1 for r in cum_reviews if r.get("translate_status") == "done"),
            "untranslated_count": sum(1 for r in cum_reviews if r.get("translate_status") != "done"),
        },
    }

    # 写入 JSON + 计算 hash
    # ...（现有逻辑不变）
```

**快照大小控制**：

当前 window-only 快照约 4MB（Run-1 基线，2577 评论）。加上累积层后：
- 正常日（2 条新评论）：window ~20KB + cumulative ~2MB = **~2MB**
- 基线日：window = cumulative，总量 ~4MB（与现在一样）
- 未来 1 万评论时：cumulative ~8MB → 仍可接受

如需控制大小，可在累积层中不存评论原文（`body`/`body_cn`），仅存统计所需字段。但当前规模下无此必要。

---

### Step 3：分析层——双份 Analytics

**文件**：`qbu_crawler/server/report_analytics.py`

**新增入口函数**：

```python
def build_dual_report_analytics(snapshot: dict, synced_labels=None) -> dict:
    """
    构建双视角分析。
    - cumulative_analytics: 基于全量数据，用于核心 KPI、风险排行、聚类等
    - window_analytics: 基于当日增量，用于"今日变化"区块
    """

    # 1. 累积分析（主体）
    cumulative_snapshot = {
        "run_id": snapshot["run_id"],
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products": snapshot["cumulative"]["products"],
        "reviews": snapshot["cumulative"]["reviews"],
        "translated_count": snapshot["cumulative"]["translated_count"],
        "untranslated_count": snapshot["cumulative"]["untranslated_count"],
    }
    cum_analytics = build_report_analytics(cumulative_snapshot, synced_labels)

    # 2. 窗口分析（增量）
    window_analytics = None
    if snapshot.get("reviews"):
        window_analytics = build_report_analytics(snapshot, synced_labels)

    # 3. 合并
    merged = {
        **cum_analytics,          # 累积分析作为主体
        "perspective": "dual",    # 标记为双视角模式

        # 窗口增量摘要
        "window": {
            "reviews_count": len(snapshot.get("reviews", [])),
            "own_reviews_count": sum(
                1 for r in snapshot.get("reviews", [])
                if r.get("ownership") == "own"),
            "competitor_reviews_count": sum(
                1 for r in snapshot.get("reviews", [])
                if r.get("ownership") == "competitor"),
            "new_negative_count": sum(
                1 for r in snapshot.get("reviews", [])
                if r.get("ownership") == "own"
                and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD),
            "new_reviews": snapshot.get("reviews", []),
            "analytics": window_analytics,  # 可选：窗口级分析（聚类、标签等）
        },

        # 累积 KPI（显式保存，方便模板引用）
        "cumulative_kpis": cum_analytics["kpis"],
    }

    return merged
```

**对现有 `build_report_analytics()` 的修改**：无。它已经是纯函数（输入 snapshot → 输出 analytics），双调用即可。

**KPI Delta 改造**：

```python
# 在 build_dual_report_analytics() 末尾：
if cum_analytics.get("mode") != "baseline":
    prev_analytics, _ = load_previous_report_context(run_id)
    if prev_analytics and prev_analytics.get("cumulative_kpis"):
        # 累积 vs 累积 delta（稳定、有意义）
        deltas = _compute_kpi_deltas(
            merged["cumulative_kpis"],
            prev_analytics["cumulative_kpis"])
        merged["cumulative_kpis"].update(deltas)
    elif prev_analytics and prev_analytics.get("kpis"):
        # 兼容老格式（P006 阶段生成的报告）
        deltas = _compute_kpi_deltas(
            merged["cumulative_kpis"],
            prev_analytics["kpis"])
        merged["cumulative_kpis"].update(deltas)
```

---

### Step 4：报告生成层——适配双视角

**文件**：`qbu_crawler/server/report_snapshot.py`

**改造 `generate_full_report_from_snapshot()`**：

```python
def generate_full_report_from_snapshot(run_id, snapshot, ...):
    # 同步标签（对累积评论）
    all_reviews = snapshot.get("cumulative", {}).get("reviews", snapshot.get("reviews", []))
    synced_labels = sync_review_labels_from_reviews(all_reviews)

    # 构建双视角分析（替换现有的单视角调用）
    analytics = build_dual_report_analytics(snapshot, synced_labels)

    # Normalize
    normalized = normalize_deep_report_analytics(analytics)

    # LLM 生成洞察（基于累积数据，自然一致）
    insights = report_llm.generate_report_insights(normalized, snapshot=snapshot)
    analytics["report_copy"] = insights

    # 聚类深度分析（基于累积数据）
    # ...（现有逻辑不变，数据自然来自累积）

    # 生成 Excel（评论明细用窗口数据 or 累积数据？→ 见下方设计）
    # 生成 V3 HTML
    # 发送邮件
    # ...
```

---

### Step 5：LLM 分析——累积上下文

**文件**：`qbu_crawler/server/report_llm.py`

因为 `build_dual_report_analytics()` 的主体是累积数据，LLM 收到的 analytics 已经是累积口径。无需额外改动 `_build_insights_prompt()`。

`_select_insight_samples()` 改为从累积评论中选样（P006 Fix-2 已将其改为从 snapshot 选样，这里只需确保选的是 `snapshot["cumulative"]["reviews"]`）：

```python
def _select_insight_samples(analytics, snapshot):
    # 优先从累积评论中选样
    reviews = (snapshot.get("cumulative", {}).get("reviews")
               or snapshot.get("reviews", []))
    # ... 选样逻辑不变
```

**新增**：在 prompt 中增加"今日变化"上下文：

```python
# _build_insights_prompt() 中追加：
window = analytics.get("window", {})
if window.get("reviews_count", 0) > 0:
    prompt += f"\n\n--- 今日新增 ---"
    prompt += f"\n新增评论 {window['reviews_count']} 条"
    prompt += f"（自有 {window['own_reviews_count']}，竞品 {window['competitor_reviews_count']}）"
    if window.get("new_negative_count", 0) > 0:
        prompt += f"\n⚠ 新增差评 {window['new_negative_count']} 条"
    prompt += "\n请在 executive_bullets 中提及今日变化（如有值得关注的新增）。"
else:
    prompt += "\n\n今日无新增评论。executive_bullets 应聚焦累积数据中的关键洞察。"
```

---

### Step 6：邮件模板——重构布局

**文件**：`qbu_crawler/server/report_templates/email_full.html.j2`

**新结构**：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background:#f8fafc; font-family:system-ui,-apple-system,sans-serif;">

<!-- 1. Header -->
<div style="background:#4f46e5; color:white; padding:16px 24px;">
  <strong>QBU 网评监控</strong>
  <span style="float:right;">{{ logical_date }}</span>
</div>

<!-- 2. Health Hero（基于累积数据，稳定可靠） -->
<div style="text-align:center; padding:32px 24px; background:{{ hero_bg_color }};">
  <div style="font-size:14px; color:rgba(255,255,255,0.8);">产品健康指数</div>
  <div style="font-size:52px; font-weight:700; color:white;">
    {{ cumulative_kpis.health_index }}
    {% if cumulative_kpis.health_index_delta_display %}
      <span style="font-size:16px;">{{ cumulative_kpis.health_index_delta_display }}</span>
    {% endif %}
  </div>
  <div style="font-size:12px; color:rgba(255,255,255,0.7);">
    / 100 · 基于 {{ cumulative_kpis.own_review_rows }} 条自有评论
  </div>
  {% if health_confidence != 'high' %}
  <div style="margin-top:8px; padding:4px 12px; background:rgba(0,0,0,0.2); border-radius:12px; display:inline-block; font-size:12px; color:white;">
    ⚠ 样本量不足，指数可能不稳定
  </div>
  {% endif %}
</div>

<!-- 3. Alert Banner -->
{% if alert_text %}
<div style="padding:10px 24px; background:{{ alert_bg_color }}; color:{{ alert_text_color }}; font-size:13px;">
  {{ alert_text }}
</div>
{% endif %}

<!-- 4. 累积概览 KPI（核心指标，稳定的大局） -->
<div style="padding:16px 24px;">
  <div style="font-size:14px; font-weight:600; color:#374151; margin-bottom:12px;">
    📊 累积概览
  </div>
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <!-- 自有评论总量 -->
      <td style="text-align:center; padding:12px; background:white; border-radius:8px;">
        <div style="font-size:24px; font-weight:700; color:#111827;">
          {{ cumulative_kpis.own_review_rows }}
        </div>
        <div style="font-size:11px; color:#6b7280;">自有评论</div>
        {% if cumulative_kpis.ingested_review_rows_delta_display %}
          <div style="font-size:11px; color:#6b7280;">{{ cumulative_kpis.ingested_review_rows_delta_display }}</div>
        {% endif %}
      </td>
      <!-- 自有差评率 -->
      <td style="text-align:center; padding:12px; background:white; border-radius:8px;">
        <div style="font-size:24px; font-weight:700; color:#dc2626;">
          {{ cumulative_kpis.own_negative_review_rate_display }}
        </div>
        <div style="font-size:11px; color:#6b7280;">差评率</div>
      </td>
      <!-- 高风险产品 -->
      <td style="text-align:center; padding:12px; background:white; border-radius:8px;">
        <div style="font-size:24px; font-weight:700; color:{{ '#dc2626' if cumulative_kpis.high_risk_count > 0 else '#16a34a' }};">
          {{ cumulative_kpis.high_risk_count }}
        </div>
        <div style="font-size:11px; color:#6b7280;">高风险产品</div>
        <div style="font-size:10px; color:#9ca3af;">自有 {{ cumulative_kpis.own_product_count }} / 竞品 {{ cumulative_kpis.competitor_product_count }}</div>
      </td>
    </tr>
  </table>
</div>

<!-- 5. 今日变化（增量区块） -->
<div style="padding:16px 24px;">
  <div style="font-size:14px; font-weight:600; color:#374151; margin-bottom:12px;">
    📌 今日变化 <span style="font-weight:400; color:#9ca3af;">({{ logical_date }})</span>
  </div>
  <div style="background:white; border-radius:8px; padding:16px; border-left:4px solid {{ '#16a34a' if window.new_negative_count == 0 else '#dc2626' }};">
    {% if window.reviews_count > 0 %}
      <div>新增评论 <strong>{{ window.reviews_count }}</strong> 条
        （自有 {{ window.own_reviews_count }} / 竞品 {{ window.competitor_reviews_count }}）
      </div>
      {% if window.new_negative_count > 0 %}
        <div style="color:#dc2626; margin-top:4px;">
          ⚠ 新增差评 {{ window.new_negative_count }} 条
        </div>
      {% endif %}
    {% else %}
      <div style="color:#6b7280;">今日无新增评论</div>
    {% endif %}

    {% if changes and changes.price_changes %}
    <div style="margin-top:12px; padding-top:12px; border-top:1px solid #e5e7eb;">
      <div style="font-size:12px; font-weight:600; color:#374151;">💰 价格变动</div>
      {% for c in changes.price_changes[:5] %}
        <div style="font-size:12px; color:#6b7280; margin-top:4px;">
          {{ c.product_name }}:
          <span style="text-decoration:line-through;">{{ c.old_price }}</span> →
          <span style="color:{{ '#dc2626' if c.new_price > c.old_price else '#16a34a' }};">{{ c.new_price }}</span>
        </div>
      {% endfor %}
    </div>
    {% endif %}

    {% if changes and changes.stock_changes %}
    <div style="margin-top:12px; padding-top:12px; border-top:1px solid #e5e7eb;">
      <div style="font-size:12px; font-weight:600; color:#374151;">📦 库存变动</div>
      {% for c in changes.stock_changes[:5] %}
        <div style="font-size:12px; color:#6b7280; margin-top:4px;">
          {{ c.product_name }}: {{ c.old_stock }} → {{ c.new_stock }}
        </div>
      {% endfor %}
    </div>
    {% endif %}
  </div>
</div>

<!-- 6. 持续关注（风险产品 TOP 3，基于累积数据） -->
<div style="padding:16px 24px;">
  <div style="font-size:14px; font-weight:600; color:#374151; margin-bottom:12px;">
    ⚠️ 持续关注
  </div>
  {% for rp in risk_products[:3] %}
  <div style="background:white; border-radius:8px; padding:12px 16px; margin-bottom:8px; border-left:4px solid {{ '#dc2626' if rp.risk_score >= 35 else '#f59e0b' }};">
    <div style="font-weight:600;">{{ rp.product_name }}</div>
    <div style="font-size:12px; color:#6b7280;">
      风险分 {{ rp.risk_score }} · 差评 {{ rp.negative_review_rows }} 条 · {{ rp.top_labels_display }}
    </div>
  </div>
  {% endfor %}
</div>

<!-- 7. AI 行动建议 -->
<div style="padding:16px 24px;">
  <div style="font-size:14px; font-weight:600; color:#374151; margin-bottom:12px;">
    💡 行动建议
  </div>
  {% for bullet in report_copy.executive_bullets[:3] %}
  <div style="display:flex; margin-bottom:8px;">
    <div style="width:24px; height:24px; background:#4f46e5; color:white; border-radius:50%; text-align:center; line-height:24px; font-size:12px; flex-shrink:0;">{{ loop.index }}</div>
    <div style="margin-left:12px; font-size:13px; color:#374151;">{{ bullet }}</div>
  </div>
  {% endfor %}
</div>

<!-- 8. Footer -->
<div style="padding:16px 24px; font-size:11px; color:#9ca3af; border-top:1px solid #e5e7eb;">
  QBU 网评监控智能分析报告 · 差评阈值 ≤ {{ threshold }} 星 · 附件含 Excel 明细和交互式 HTML 报告
</div>

</body>
</html>
```

**关键变化**：
1. Hero 区的健康指数基于 `cumulative_kpis`（稳定）
2. KPI 卡片基于 `cumulative_kpis`（不再因日窗口为空而归零）
3. 新增"今日变化"区块（基于 `window` 增量数据 + `changes` 变动检测）
4. 风险产品基于累积数据（不会消失）
5. AI 建议基于累积数据（与 KPI 一致，不矛盾）

---

### Step 7：V3 HTML 报告——启用"今日变化" Tab

**文件**：`qbu_crawler/server/report_templates/daily_report_v3.html.j2`

当前 Tab 2（今日变化）是占位符。改造为：

```html
<!-- Tab 2: 今日变化 -->
<div class="tab-panel" id="tab-changes">
  {% if window.reviews_count == 0 and not changes.has_changes %}
    <div class="empty-state">今日无新增评论和数据变动</div>
  {% else %}

    {% if window.reviews_count > 0 %}
    <h3>新增评论 ({{ window.reviews_count }} 条)</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>产品</th><th>归属</th><th>评分</th>
          <th>标题</th><th>内容摘要</th><th>发布日期</th>
        </tr>
      </thead>
      <tbody>
        {% for r in window.new_reviews %}
        <tr>
          <td>{{ r.product_name }}</td>
          <td>{{ '自有' if r.ownership == 'own' else '竞品' }}</td>
          <td>{{ '★' * (r.rating|int) }}{{ '☆' * (5 - r.rating|int) }}</td>
          <td>{{ r.headline_cn or r.headline }}</td>
          <td>{{ (r.body_cn or r.body)[:120] }}...</td>
          <td>{{ r.date_published }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if changes and changes.has_changes %}
    <h3>数据变动</h3>
    <!-- 价格变动表 -->
    <!-- 库存变动表 -->
    <!-- 评分变动表 -->
    <!-- 复用 quiet_day_report.html.j2 中的变动表结构 -->
    {% endif %}

  {% endif %}
</div>
```

**其他 Tab 改动**：
- **总览 Tab**：KPI 卡片改为 `cumulative_kpis`
- **问题诊断 Tab**：聚类基于累积数据（自然获得）
- **产品排行 Tab**：风险产品基于累积数据
- **竞品对标 Tab**：差距分析基于累积数据
- **全景数据 Tab**：评论明细增加"全量/今日新增"切换按钮

---

### Step 8：Excel 报告——双口径标注

**文件**：`qbu_crawler/server/report.py`

Excel 的 4-sheet V3 格式改造：

| Sheet | 当前数据源 | 新数据源 | 变化 |
|-------|----------|---------|------|
| 评论明细 | 窗口评论 | 累积评论（增加"本次新增"列标记） | 改动大 |
| 产品概览 | 窗口产品统计 | 累积产品统计 | 中等改动 |
| 问题标签 | 窗口标签 | 累积标签 | 中等改动 |
| 趋势数据 | 30 天快照 | 不变 | 无改动 |

**评论明细 Sheet 改造**：
- 新增列："采集时间"（`scraped_at`），用于区分新旧
- 新增列："本次新增"（布尔值，`scraped_at` 在当日窗口内的标记为 Yes）
- 默认按"本次新增"降序 + 评分升序 排列
- Sheet 标题注明口径："评论明细（累积全量，截至 {logical_date}）"

---

### Step 9：Change/Quiet 模式适配

**文件**：`qbu_crawler/server/report_snapshot.py`

有了累积视角后，change/quiet 模式的价值大增：

**Change 模式**（无新评论 + 有价格/库存/评分变动）：
- 邮件中的 KPI 卡片：使用**当前累积 analytics**（而非"上次报告的 analytics"）
  - 为此需要在 change 模式下也调用 `build_dual_report_analytics()`
  - 但可以跳过 LLM 分析（省时省钱）
- 价格/库存/评分变动：使用现有的 `detect_snapshot_changes()`

**Quiet 模式**（无任何变化）：
- 邮件中的 KPI 卡片：同样使用当前累积 analytics
- "未解决问题"：使用当前累积的聚类数据

```python
# generate_report_from_snapshot() 中 change/quiet 模式改造：
if mode in ("change", "quiet"):
    # 即使没有新评论，也计算累积分析（轻量，不含 LLM）
    cum_snapshot = {
        "run_id": snapshot["run_id"],
        "logical_date": snapshot["logical_date"],
        "products": snapshot["cumulative"]["products"],
        "reviews": snapshot["cumulative"]["reviews"],
        ...
    }
    cum_analytics = build_report_analytics(cum_snapshot)
    # 传给 change/quiet 模板
```

---

### Step 10：Delta 计算验证

有了累积视角，delta 终于有了稳定基础：

```
                    Run-1 (基线)    Run-3 (增量)    Delta
累积自有评论         1610            1612           +2
累积自有差评率       3.48%           3.47%          -0.01%
累积健康指数         95.0            95.0           ±0.0
累积高风险产品       2               2              ±0
累积竞品差距指数     5               5              ±0
```

对比当前的窗口 delta：

```
                    Run-1 (窗口)    Run-3 (窗口)    Delta
窗口自有评论         1610            1              -1609 ← 荒谬
窗口差评率           3.48%           0.00%          -3.48% ← 误导
```

---

## 向后兼容

### 渐进式迁移

1. **快照格式兼容**：新快照包含 `cumulative` 字段，老快照没有。分析代码检测 `snapshot.get("cumulative")` 存在与否来决定走双视角还是单视角
2. **Analytics JSON 兼容**：新增 `cumulative_kpis` 和 `window` 字段，保留原有 `kpis`（等于 `cumulative_kpis`）
3. **之前的报告 HTML/Excel**：已生成的不受影响。delta 计算在找不到 `cumulative_kpis` 时 fallback 到 `kpis`

### 配置开关

考虑添加环境变量 `REPORT_PERSPECTIVE=dual|window`（默认 `dual`），允许回退到单视角模式：

```python
# report_snapshot.py
if config.REPORT_PERSPECTIVE == "dual" and snapshot.get("cumulative"):
    analytics = build_dual_report_analytics(snapshot, ...)
else:
    analytics = build_report_analytics(snapshot, ...)  # 原逻辑
```

---

## 测试计划

### 单元测试

1. `query_cumulative_data()` 返回全量数据，行数与 `SELECT COUNT(*)` 一致
2. `build_dual_report_analytics()` 的 `cumulative_kpis` 基于全量数据
3. `build_dual_report_analytics()` 的 `window` 基于增量数据
4. 累积 delta 计算：模拟两次累积 analytics，验证 delta 正确

### 集成测试

1. 用生产 DB 副本，模拟 Run-4（假设新增 3 条评论）：
   - 累积 KPI 应与 Run-3 接近（仅微调）
   - 窗口显示 3 条新评论
   - 风险产品列表与 Run-1 基线一致
   - 健康指数稳定在 95 附近
2. 模拟 Run-5（0 条新评论，1 个价格变动）：
   - 触发 change 模式
   - 邮件显示价格变动 + 累积 KPI 卡片
3. LLM 输出与 KPI 一致性检查

### 邮件视觉测试

1. 用真实数据生成 3 种模式的邮件 HTML
2. 在邮件客户端（Outlook/Gmail）中预览渲染效果
3. 检查 KPI 卡片、今日变化区块、风险产品列表的数据正确性

---

## 未来扩展

### 周报/月报

双视角架构天然支持聚合报告：
- **窗口改为 7 天**：`data_since = T-7, data_until = T`
- **累积不变**：仍是全量
- 邮件"今日变化"改为"本周变化"
- 新增配置：`REPORT_FREQUENCY=daily|weekly|monthly`

### 告警升级

累积视角下的告警更有意义：
- 累积健康指数持续下降 3 天 → 红色预警
- 某产品风险分突破 50 → 单品预警
- 新增聚类（之前不存在的问题类型）→ 新问题预警

### 大规模数据优化

当评论突破 10 万时：
- 累积分析改为增量更新（每天在前一天基础上加入新评论，不重算全量）
- 引入 `cumulative_rollup` 表（每日一行，存预聚合统计）
- 快照中不存累积评论原文，仅存统计摘要

---

## 审查修正（2026-04-15 代码对齐审查）

对照实际代码逐项核实后，发现以下**必须修正**的问题和遗漏：

### 修正 A（严重）：`generate_full_report_from_snapshot()` 的 early return 阻止双视角

`report_snapshot.py` 约 line 673-674 有：

```python
if not snapshot.get("reviews"):
    return {"status": "completed_no_change", "reason": "No new reviews"}
```

当窗口无新评论时直接返回，`build_dual_report_analytics()` 永远不会被调用。而双视角架构下，即使窗口为空也应生成累积分析报告。

**方案**：在双视角模式下跳过此 guard，改为由 `determine_report_mode()` 统一路由。或者仅在 `REPORT_PERSPECTIVE == "window"` 时保留此 guard。

```python
if not snapshot.get("reviews") and not snapshot.get("cumulative"):
    return {"status": "completed_no_change", "reason": "No new reviews"}
# 有 cumulative 数据时继续执行，走 change/quiet 路径
```

### 修正 B（严重）：`query_scope_report_data()` 缺少 `review_analysis` JOIN

`report.py` 的 `query_scope_report_data(Scope())` 只 JOIN `products`，不 JOIN `review_analysis`。返回的评论缺少 `sentiment`、`analysis_labels`、`analysis_features` 等字段。

**方案选择**：

- **方案 1（推荐）**：使用计划中独立的 `query_cumulative_data()` 函数（已包含 `LEFT JOIN review_analysis`）
- **方案 2**：对 `query_scope_report_data()` 的返回结果做 post-query enrichment，复用 `freeze_report_snapshot` 中已有的 `get_reviews_with_analysis()` 模式
- **方案 3**：扩展 `query_scope_report_data()` 添加 `LEFT JOIN review_analysis`（改动较大，影响其他调用方）

### 修正 C（严重）：快照 hash 计算受累积数据影响

`report_snapshot.py` 约 line 311-314 对整个 snapshot dict 做 `json.dumps` 计算 SHA-1 hash。添加 `cumulative` 字段后，每天的累积数据必然不同（新增翻译、分析结果更新），导致 hash 永远变化，`detect_snapshot_changes()` 的 hash 对比失效。

**方案**：在计算 hash 前排除 `cumulative` 字段：

```python
# 只对窗口数据计算 hash（保持与现有行为一致）
hash_payload = {k: v for k, v in snapshot.items() if k != "cumulative"}
hash_str = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True)
snapshot_hash = hashlib.sha1(hash_str.encode()).hexdigest()
```

### 修正 D（严重）：老快照无 `cumulative` 字段时 `build_dual_report_analytics()` 崩溃

计划 Step 3 中直接访问 `snapshot["cumulative"]["products"]`，老快照无此字段会抛 `TypeError: 'NoneType' is not subscriptable`。

**方案**：在入口加 guard：

```python
def build_dual_report_analytics(snapshot, synced_labels=None):
    if not snapshot.get("cumulative"):
        # 降级为单视角
        return build_report_analytics(snapshot, synced_labels)
    # ... 双视角逻辑
```

### 修正 E（中等）：`_render_full_email_html()` 未传递新模板变量

`report_snapshot.py` 约 line 640-665 的 `_render_full_email_html()` 当前传给模板的变量不包含 `cumulative_kpis`、`window`、`changes`、`health_confidence`。

**方案**：扩展传参：

```python
def _render_full_email_html(snapshot, analytics):
    normalized = normalize_deep_report_analytics(analytics)
    alert_level, alert_text = _compute_alert_level(normalized)
    changes = detect_snapshot_changes(snapshot, previous_snapshot)  # 需要 previous_snapshot 参数

    return tpl.render(
        # 原有参数
        logical_date=..., snapshot=snapshot, analytics=normalized,
        alert_level=alert_level, alert_text=alert_text,
        report_copy=..., risk_products=..., threshold=...,
        # 新增参数
        cumulative_kpis=normalized.get("cumulative_kpis", normalized.get("kpis", {})),
        window=normalized.get("window", {}),
        changes=changes,
        health_confidence=normalized["kpis"].get("health_confidence", "high"),
    )
```

**注意**：`_render_full_email_html` 当前不接收 `previous_snapshot` 参数，需要从调用链上游传入或在函数内获取。

### 修正 F（中等）：`sync_review_labels()` 应只调用一次

`sync_review_labels()` 对每个 review_id 执行 DELETE + INSERT。对累积评论调用一次即可，不需要对窗口评论再调用一次（窗口是累积的子集）。

**方案**：在 `build_dual_report_analytics()` 外部调用一次，传入结果：

```python
# generate_full_report_from_snapshot() 中：
all_reviews = snapshot.get("cumulative", {}).get("reviews", snapshot.get("reviews", []))
synced_labels = sync_review_labels_from_reviews(all_reviews)

analytics = build_dual_report_analytics(snapshot, synced_labels)
# build_dual_report_analytics 内部两次调用 build_report_analytics 都传入同一个 synced_labels
```

### 修正 G（低）：`config.py` 需新增 `REPORT_PERSPECTIVE` 配置

计划引用了 `config.REPORT_PERSPECTIVE` 但未说明在 `config.py` 中的定义。

**方案**：

```python
# config.py 新增
REPORT_PERSPECTIVE = os.getenv("REPORT_PERSPECTIVE", "dual")  # "dual" | "window"
```

### 修正 H（低）：Excel "本次新增" 列需要 `scraped_at` 或 review ID 匹配

`query_scope_report_data()` 的评论 SELECT 不包含 `r.scraped_at`。Excel 中标记"本次新增"需要此字段或用 review ID 与窗口评论做匹配。

**推荐方案**：用 review ID 匹配（更简单）：

```python
window_review_ids = {r["id"] for r in snapshot.get("reviews", [])}
for review in cumulative_reviews:
    review["is_new"] = review["id"] in window_review_ids
```

### 修正 I（低）：`_build_trend_data()` 会被累积分析冗余调用

`build_report_analytics()` 内部调用 `_build_trend_data(products, days=30)`，对每个产品查 DB。双视角下调用两次意味着 41×2 = 82 次 DB 查询。

**优化方案**：趋势数据只在累积分析中计算一次，窗口分析跳过：

```python
def build_dual_report_analytics(snapshot, synced_labels=None):
    cum_analytics = build_report_analytics(cumulative_snapshot, synced_labels)

    # 窗口分析跳过趋势数据
    window_analytics = build_report_analytics(
        snapshot, synced_labels, skip_trend=True)  # 需要新增参数
```

或者更简单：在 merge 时用累积的趋势数据覆盖即可（已经是这个效果，因为 `{**cum_analytics, ...}` 保留了累积的 `_trend_series`）。

### 审查确认（无问题的设计点）

以下设计点经代码验证**无问题**，确认可按计划执行：

1. `build_report_analytics()` 无全局状态，可安全调用两次
2. `detect_snapshot_changes()` 操作 `snapshot["products"]`（窗口层），不受 cumulative 影响
3. LLM prompt token 量可控（~5K chars），即使用累积 analytics 也不会超限
4. 当前数据规模下（2579 评论）性能无忧，全量分析 <1 秒
5. 老快照 `.get("cumulative")` 返回 None，加 guard 后安全降级
6. 第一次 run 时 cumulative = window，双分析退化为单分析，行为正确
7. `analyze_cluster_deep()` 与累积聚类不冲突（互补关系）
8. Chart 数据（radar/heatmap/sentiment）从 `cum_analytics` 顶层键获取，自然是累积视角
