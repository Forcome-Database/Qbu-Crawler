# 日报 PDF 与邮件重设计方案

> 日期：2026-04-06
> 状态：Implemented
> 范围：方案 B — 模板重设计 + 邮件升级 + 代码质量

---

## 1. 背景与目标

### 1.1 当前问题

经多角度深度审查（5 个并行 agent 探索 + 人工交叉验证 + 双视角专项审核），确认以下核心问题：

| 编号 | 问题 | 根因 |
|------|------|------|
| P1 | PDF 每页下半部空白，11 页内容只需 5-6 页 | `min-height:274mm` + `break-after:page` 强制每 section 占满整页 |
| P2 | 证据附录占 6/11 页，与问题簇脱节 | 证据独立成附录，每条独占大半页 |
| P3 | 图表无数据标签，无法精确读数 | matplotlib 未调用 `bar_label()` |
| P4 | 三个横条图视觉单调 | 缺少图表类型多样性 |
| P5 | 改良建议空泛不可执行 | 规则引擎模板输出"可能与...有关"式套话 |
| P6 | 邮件正文是数据罗列不是人话 | executive_bullets 直接输出标签代码和计数 |
| P7 | 邮件只有纯文本，无 HTML 版本 | 只用 `MIMEText("plain")` |
| P8 | 无页码/页眉 | `@page` 未配 margin box，Playwright 未启用 header/footer |
| P9 | 增量模式无变化量 | 未对比前日 snapshot |
| P10 | 两套 analytics 规范化函数 | report.py 和 report_pdf.py 各有一套 normalize |
| P11 | Hero 主标题是静态模板，不是数据驱动结论 | `_fallback_hero_headline` 生成的文案缺乏趋势信息 |
| P12 | 问题簇缺时间维度和产品覆盖面 | `_cluster_summary_items` 不输出 date_published 和 affected_product_count |
| P13 | 竞品部分无交叉对比 | 只展示竞品好评，不对比自有同维度表现 |
| P14 | 证据图片 base64 内嵌未缩放 | 原图 3000x2000 直接编码，PDF 体积暴涨 |

### 1.2 目标

- **主受众**：研发/品控团队 — 高信息密度、精准定位问题、快速检索证据
- **次受众**：管理层 — 前 1-2 页 10 秒内看完要点
- **量化目标**：PDF 从 11 页压缩到约 5 页（当前数据量），随数据规模线性增长

### 1.3 不做什么

- 不拆分双版本报告（管理层版/研发版）
- 不改数据采集、分类、翻译管道
- 不做完整 delta 基础设施（只做 KPI 级轻量标注，不做产品级 delta）
- 不做数据质量预检门槛
- 不引入产品主图（当前数据管道不抓取产品主图，评论图片通过内嵌缩略图展示）
- 不做竞品分产品统计（当前 analytics 按 label_code 聚合，不按竞品产品分组）
- 不做生成与投递解耦（架构改动大，留到后续迭代）

---

## 2. PDF 信息架构重设计

### 2.1 新的页面结构

从"每页一主题 + 独立附录"改为"流式排版 + 证据内嵌"：

```
旧结构（11 页，固定分页）          新结构（约 5 页，流式排版）
─────────────────────           ─────────────────────
P1  Hero 页                      P1  Hero 页（独占一页，含行动信号）
P2  自有产品风险总览               P2  自有产品风险总览 + 重点产品深挖
P3  重点产品深挖                   P3  问题簇（事实版 + 内嵌证据缩略图）
P4  问题簇与改良建议               P4  竞品 Benchmark（含 gap analysis）
P5  竞品 Benchmark                P5  （如有溢出内容）
P6-P11  证据附录（取消）
```

### 2.2 分页规则

```css
/* 新：只有 Hero 页强制换页，其余流式 */
.report-page-hero { break-after: page; }
.report-page      { break-after: auto; }
.page-frame       { min-height: auto; }

/* 逻辑断点加 margin-top + 色条做视觉分隔 */
.report-section + .report-section {
  margin-top: 28px;
  padding-top: 20px;
  border-top: 3px solid var(--accent);  /* 色条替代细线，增强视觉分隔 */
}

/* 问题簇卡片：block 纵向堆叠（非 grid）*/
/* Chromium 已知 bug：break-inside:avoid 在 grid/flex 子项中不可靠。 */
/* 使用 block 布局作为默认方案，卡片更宽、缩略图更舒适。 */
.issue-grid {
  display: block;  /* 非 grid，单列纵向堆叠 */
}

.issue-card + .issue-card {
  margin-top: 14px;
}

/* 卡片级防断 */
.analysis-block,
.issue-card,
.focus-card {
  break-inside: avoid;
  overflow: hidden;
}
```

### 2.3 Hero 页改进

Hero 页保持独占一页，增加三项内容：

#### 2.3.1 KPI Delta 标记

```html
<div class="metric-card">
  <span>差评数</span>
  <strong>78</strong>
  {% if analytics.kpis.negative_review_rows_delta is defined
        and analytics.kpis.negative_review_rows_delta != 0 %}
  <span class="delta {{ 'delta-up' if analytics.kpis.negative_review_rows_delta > 0 else 'delta-down' }}">
    {{ analytics.kpis.negative_review_rows_delta_display }} vs 上期
  </span>
  {% endif %}
</div>
```

#### 2.3.2 数据驱动的 Hero 主标题

旧：`_fallback_hero_headline` 输出静态模板文字"自有产品 X 的 Y 问题最值得优先处理"。

新：`_generate_hero_headline()` 使用 delta + 趋势语言生成本期独特的结论：

```python
def _generate_hero_headline(normalized):
    """生成数据驱动的 Hero 页主标题。"""
    top = (normalized["self"]["risk_products"] or [None])[0]
    if not top:
        return _fallback_hero_headline(normalized)

    top_labels = top.get("top_labels") or []
    cluster_name = _LABEL_DISPLAY.get(
        top_labels[0]["label_code"], ""
    ) if top_labels else "差评"

    neg_delta = normalized["kpis"].get("negative_review_rows_delta")
    total_reviews = top.get("total_reviews") or 0
    neg_count = top["negative_review_rows"]

    # 趋势语言
    if neg_delta and neg_delta > 0:
        rate = f"环比增加 {neg_delta} 条" if neg_delta < 10 else f"环比激增 {neg_delta} 条"
        return f"本期最高风险：{top['product_name']} {cluster_name}问题{rate}，需优先跟进。"
    elif total_reviews > 0:
        pct = neg_count / total_reviews
        return f"自有产品 {top['product_name']} 差评率 {pct:.0%}，{cluster_name}问题集中。"
    else:
        return _fallback_hero_headline(normalized)
```

#### 2.3.3 行动信号灯

在 Hero 页"关键判断"栏旁增加一个状态标签：

```python
def _compute_alert_level(normalized):
    """返回 ('red'|'yellow'|'green', 说明文字)"""
    top_neg = normalized["self"]["top_negative_clusters"]
    high_sev = [c for c in top_neg if c.get("severity") == "high" and c.get("review_count", 0) >= 5]
    delta = normalized["kpis"].get("negative_review_rows_delta", 0) or 0
    if high_sev or delta >= 10:
        return "red", "存在高严重度问题簇，建议今日跟进"
    elif delta > 0:
        return "yellow", "差评数较上期有所上升，请持续关注"
    else:
        return "green", "无新增高风险信号"
```

模板中用一个色块 + 一句话展示：

```html
<div class="alert-signal alert-{{ analytics.alert_level }}">
  {{ analytics.alert_text }}
</div>
```

```css
.alert-signal { padding: 8px 14px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.alert-red    { background: var(--accent-soft); color: var(--accent); }
.alert-yellow { background: #f5ecd4; color: var(--gold); }
.alert-green  { background: var(--green-soft); color: var(--green); }
```

---

## 3. 证据与问题簇合并

### 3.1 取消独立附录

新设计：证据直接内嵌到问题簇卡片中，不再有独立附录页。

### 3.2 问题簇卡片新布局

```html
<article class="issue-card">
  <div class="issue-top">
    <h3>质量稳定性</h3>
    <span class="priority-tag severity-high">高</span>
  </div>
  <div class="issue-facts">
    <p>差评 13 条 | 涉及 2 个产品 | 图片证据 3 条</p>
    <p class="issue-timeline">
      首次出现：2026-02-14 ｜ 最近一条：2026-03-29
    </p>
  </div>
  <!-- 代表性评论：中英双语 + 日期 -->
  <div class="issue-quotes">
    <blockquote>
      <p class="quote-cn">"支撑梁在第二次使用时就断裂了"</p>
      <p class="quote-en">"The support beam snapped on my second use"</p>
      <cite>— 评分 1.0 · JennyS · 2026-03-12</cite>
    </blockquote>
  </div>
  <!-- 内嵌证据缩略图（最多 3 张） -->
  {% if item.image_evidence %}
  <div class="issue-evidence-strip">
    {% for img in item.image_evidence[:3] %}
    <div class="evidence-thumb">
      <img src="{{ img.data_uri }}" alt="{{ img.evidence_id }}">
      <span class="evidence-label">{{ img.evidence_id }}</span>
    </div>
    {% endfor %}
    {% if item.image_evidence | length > 3 %}
    <div class="evidence-more">+{{ item.image_evidence | length - 3 }}</div>
    {% endif %}
  </div>
  {% endif %}
  <!-- Excel 交叉引用 -->
  <p class="issue-xref">详见 Excel →「评论」页 → 筛选 SKU 列</p>
</article>
```

### 3.3 CSS 布局

```css
.issue-evidence-strip {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  overflow: hidden;
}

.evidence-thumb {
  position: relative;
  width: 100px;
  height: 80px;
  border-radius: 10px;
  overflow: hidden;
  flex-shrink: 0;
}

.evidence-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.evidence-label {
  position: absolute;
  top: 4px;
  left: 4px;
  background: rgba(0,0,0,0.6);
  color: #fff;
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
}

.evidence-more {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 60px;
  height: 80px;
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.quote-cn { font-weight: 600; }
.quote-en { font-size: 10px; color: var(--muted); margin-top: 4px; }

.issue-timeline {
  font-size: 10px;
  color: var(--muted);
  margin-top: 4px;
}

.issue-xref {
  margin-top: 10px;
  font-size: 9px;
  color: var(--muted);
  font-style: italic;
}
```

### 3.4 改良建议改为事实呈现

移除 `possible_cause_boundary` 和 `improvement_direction` 字段。替换为：
- `issue-facts`：差评数 + 涉及产品数 + 图片证据数
- `issue-timeline`：首次出现日期 + 最近一条日期
- `issue-quotes`：中英双语代表性评论 + 评论日期
- `issue-xref`：Excel 交叉引用指引

### 3.5 数据层改动（report_analytics.py）

在 `_cluster_summary_items()` 中补充以下字段：

```python
# 在 cluster 字典初始化时
cluster["affected_products"] = set()
cluster["dates"] = []

# 在循环里
cluster["affected_products"].add(review.get("product_sku") or review.get("product_name"))
if review.get("date_published"):
    cluster["dates"].append(review["date_published"])

# example_reviews 补充 date_published
example["date_published"] = review.get("date_published", "")
# example_reviews 补充英文原文
example["headline_en"] = review.get("headline", "")
example["body_en"] = review.get("body", "")

# 在 items 导出时
item["affected_product_count"] = len(cluster["affected_products"])
item["first_seen"] = min(cluster["dates"]) if cluster["dates"] else None
item["last_seen"] = max(cluster["dates"]) if cluster["dates"] else None
```

在 `_risk_products()` 中补充 `total_reviews` 字段（从 snapshot products 的 `review_count` 读取）。

### 3.6 竞品 Gap Analysis

在 `normalize_deep_report_analytics()` 中新增交叉对比逻辑：

```python
def _competitor_gap_analysis(normalized):
    """找出竞品被夸、我们被差评的交集主题。"""
    comp_positive = {t["label_code"]: t for t in normalized["competitor"]["top_positive_themes"]}
    own_negative = {c["label_code"]: c for c in normalized["self"]["top_negative_clusters"]}
    gap_codes = set(comp_positive) & set(own_negative)
    gaps = []
    for code in gap_codes:
        gaps.append({
            "label_code": code,
            "label_display": _LABEL_DISPLAY.get(code, code),
            "competitor_positive_count": comp_positive[code]["review_count"],
            "own_negative_count": own_negative[code]["review_count"],
        })
    return sorted(gaps, key=lambda g: g["own_negative_count"], reverse=True)
```

在 PDF 竞品 Benchmark 页展示 gap 结果（如有）：

```html
{% if analytics.competitor.gap_analysis %}
<div class="gap-callout">
  <p class="section-kicker">竞品优势 vs 自有短板</p>
  {% for gap in analytics.competitor.gap_analysis %}
  <p>{{ gap.label_display }}：竞品好评 {{ gap.competitor_positive_count }} 条，自有差评 {{ gap.own_negative_count }} 条</p>
  {% endfor %}
</div>
{% endif %}
```

---

## 4. 图表改进

### 4.1 数据标签

```python
bars = ax.barh(labels, values, color=color, height=0.56)
ax.bar_label(bars, fmt="%.0f", padding=4, fontsize=9, color="#4a4a4a")
```

### 4.2 Y 轴标签截断（视觉宽度感知）

```python
def _truncate_label(label, max_visual_width=36):
    """按视觉宽度截断：中文字符计 2，ASCII 字符计 1。"""
    width = 0
    for i, ch in enumerate(label):
        width += 2 if ord(ch) > 127 else 1
        if width > max_visual_width:
            return label[:i] + "..."
    return label
```

### 4.3 风险矩阵散点图（带数据量门槛）

仅当自有产品数 >= 6 时启用散点图，否则保留横条图：

```python
def build_chart_assets(analytics, output_dir):
    # ... 横条图照旧 ...
    risk_products = analytics["self"]["risk_products"]
    if len(risk_products) >= 6:
        _save_risk_matrix(risk_products, output_path / "self-risk-matrix.svg")
        chart_specs["self_risk_matrix"] = str(chart_file)
```

模板中条件渲染：

```html
{% if chart_svgs.self_risk_matrix %}
<div class="chart-wrap">{{ chart_svgs.self_risk_matrix }}</div>
{% endif %}
```

散点图标注改用 SKU 而非产品名（SKU 字符固定短），完整产品名在下方列表展示。

### 4.4 严重度分色（修正后）

调整色值，与现有色彩体系拉开区分度：

```python
severity_colors = {
    "high": "#6b3328",    # 深砖红（与 --accent #93543f 明显区分）
    "medium": "#b7633f",  # 红褐色（保持不变）
    "low": "#a89070",     # 偏灰中性色（避免与 --gold #b0823a 混淆）
}
```

色彩语义表：

| 颜色 | 变量/色值 | 使用场景 |
|------|----------|---------|
| `--accent` #93543f | KPI 数值、品牌强调 |
| `--green` #345f57 | 竞品正向、delta 下降（好事） |
| `--gold` #b0823a | 亮点标注 |
| severity-high #6b3328 | 高严重度标签和图表 bar |
| severity-medium #b7633f | 中严重度标签和图表 bar |
| severity-low #a89070 | 低严重度标签和图表 bar |
| delta-up = --accent | KPI 差评上升（坏事） |
| delta-down = --green | KPI 差评下降（好事） |

---

## 5. 页眉页脚

### 5.1 实现

使用 Playwright `displayHeaderFooter`。页眉页脚模板使用 `float` 布局（非 flex），因为 Playwright 的 header/footer 隔离渲染上下文中 flex 宽度计算存在已知偏移。

```python
page.pdf(
    path=str(output_file),
    format="A4",
    print_background=True,
    prefer_css_page_size=False,
    display_header_footer=True,
    margin={"top": "18mm", "bottom": "16mm", "left": "10mm", "right": "10mm"},
    header_template="""
        <div style="width:100%;font-size:8px;color:#766d62;overflow:hidden;">
            <span style="float:left;">Daily Product Intelligence · 内部资料</span>
            <span style="float:right;">{report_date}</span>
        </div>
    """.format(report_date=snapshot["logical_date"]),
    footer_template="""
        <div style="width:100%;font-size:8px;color:#766d62;overflow:hidden;">
            <span style="float:left;">Run #{run_id}</span>
            <span style="float:right;"><span class="pageNumber"></span> / <span class="totalPages"></span></span>
        </div>
    """.format(run_id=snapshot.get("run_id", "")),
)
```

**关键注意**：
- `prefer_css_page_size=False` — margin 由 Python 侧控制
- CSS `@page` 修改为 `@page { size: A4; margin: 0; }` — 避免双重 margin
- top margin 18mm = 页眉高度 ~8mm + 间距 ~10mm（实现时需实测调整）
- 页眉包含"内部资料"标识

---

## 6. 邮件系统升级

### 6.1 纯文本邮件精简

```jinja2
各位好，

附件为 {{ snapshot.logical_date }} 产品评论深度日报，数据覆盖截至 {{ snapshot.data_until }}。

今日要点：
{% for item in analytics.report_copy.executive_bullets_human[:3] %}
{{ loop.index }}. {{ item }}
{% else %}
- 当前暂无足够样本形成明确判断。
{% endfor %}

详见附件 PDF（分析版）和 Excel（明细版）。
```

不再包含 baseline/incremental 系统状态说明（对管理层无决策价值）。

### 6.2 executive_bullets 人话化

```python
def _humanize_bullets(normalized):
    """生成 3 条自然语言结论。"""
    bullets = []
    # Bullet 1: 最高风险产品 — 含差评率分母和 delta
    top = (normalized["self"]["risk_products"] or [None])[0]
    if top:
        top_labels = top.get("top_labels") or []
        cluster_code = top_labels[0].get("label_code") if top_labels else ""
        cluster_name = _LABEL_DISPLAY.get(cluster_code, cluster_code)
        total = top.get("total_reviews") or 0
        neg = top["negative_review_rows"]
        rate_str = f"（差评率 {neg/total:.0%}）" if total else ""
        neg_delta = normalized["kpis"].get("negative_review_rows_delta", 0) or 0
        delta_str = f"，较上期新增 {neg_delta} 条" if neg_delta > 0 else ""
        bullets.append(
            f"自有产品 {top['product_name']} 累计 {neg} 条差评"
            f"{rate_str}，问题集中在{cluster_name}{delta_str}"
        )

    # Bullet 2: 竞品对比 — 含 gap analysis
    gaps = normalized["competitor"].get("gap_analysis") or []
    themes = normalized["competitor"]["top_positive_themes"]
    if gaps:
        g = gaps[0]
        bullets.append(
            f"竞品在{g['label_display']}方面好评 {g['competitor_positive_count']} 条，"
            f"同期自有同维度差评 {g['own_negative_count']} 条，存在差距"
        )
    elif themes:
        bullets.append(
            f"竞品好评聚焦在{themes[0].get('label_display','')}（{themes[0].get('review_count',0)} 条）"
        )

    # Bullet 3: 覆盖摘要 — 翻译完成率仅在异常时显示
    kpis = normalized["kpis"]
    translation_rate = kpis.get("translation_completion_rate") or 1.0
    if translation_rate < 0.7:
        bullets.append(
            f"注意：{kpis['untranslated_count']} 条评论翻译未完成，中文分析可能不完整"
        )
    else:
        bullets.append(
            f"本期覆盖 {kpis['product_count']} 个产品、{kpis['ingested_review_rows']} 条评论"
        )
    return bullets[:3]
```

### 6.3 邮件主题行改进

```python
def _build_email_subject(normalized, logical_date):
    alert_level, _ = _compute_alert_level(normalized)
    prefix = {"red": "[需关注] ", "yellow": "[注意] ", "green": ""}[alert_level]
    top = (normalized["self"]["risk_products"] or [None])[0]
    top_name = top["product_name"] if top else ""
    count = normalized["kpis"]["product_count"]
    return f"{prefix}产品评论日报 {logical_date} — {top_name} 等 {count} 个产品"
```

### 6.4 HTML 富文本邮件

新增模板 `daily_report_email.html.j2`，使用 table 布局，所有样式手工内联。

TOP3 风险产品表格列改为：**产品名 | 主要问题 | 差评数**（删除"风险分"列，管理层不理解合成指标）。

```
┌─────────────────────────────────┐
│ Daily Product Intelligence      │
│ 产品评论日报 2026-04-01          │
├───────────┬─────────────────────┤
│ 产品数 9  │ 新增评论 636        │
│ 差评数 78 │ 差评率 12.3%        │
├───────────┴─────────────────────┤
│ 今日要点：                       │
│ 1. ...                          │
│ 2. ...                          │
│ 3. ...                          │
├─────────────────────────────────┤
│ 风险产品 TOP 3                   │
│ 产品名       主要问题    差评数   │
│ Product A    质量稳定性    18     │
│ Product B    材料与做工     9     │
│ Product C    质量稳定性     2     │
├─────────────────────────────────┤
│ 详见附件 PDF 和 Excel            │
└─────────────────────────────────┘
```

600px 宽度保持不变（2026 年邮件设计主流标准）。为 Outlook Windows 桌面版添加条件注释确保 `table-layout: fixed`。

### 6.5 邮件发送改造

```python
# report.py send_email() 签名
def send_email(recipients, subject, body_text, body_html=None,
               attachment_path=None, attachment_paths=None):

# 正文结构：MIMEMultipart("mixed") > MIMEMultipart("alternative")
msg = MIMEMultipart("mixed")
body_part = MIMEMultipart("alternative")
body_part.attach(MIMEText(body_text, "plain", "utf-8"))
if body_html:
    body_part.attach(MIMEText(body_html, "html", "utf-8"))
msg.attach(body_part)
```

### 6.6 HTML 邮件渲染入口

由 `report_snapshot.py` 的 `generate_full_report_from_snapshot()` 渲染：

```python
subject, body_text = report.build_daily_deep_report_email(snapshot, analytics)
body_html = report.render_daily_email_html(snapshot, analytics)
email_result = report.send_email(
    recipients=config.EMAIL_RECIPIENTS,
    subject=subject,
    body_text=body_text,
    body_html=body_html,
    attachment_paths=[excel_path, pdf_path],
)
```

`report.py` 新增：

```python
def render_daily_email_html(snapshot, analytics):
    normalized = normalize_deep_report_analytics(analytics)
    env = _report_template_env()
    template = env.get_template("daily_report_email.html.j2")
    return template.render(snapshot=snapshot, analytics=normalized)
```

### 6.7 BCC 配置

```python
# config.py
EMAIL_BCC_MODE = os.getenv("EMAIL_BCC_MODE", "false").lower() == "true"
```

---

## 7. 图片缩放（解决 P14）

当前 `_inline_image_data_uri()` 下载原图直接 base64 编码，可能为 3000x2000 的手机照片。需加入 Pillow 缩略图压缩：

```python
from PIL import Image
import io

def _inline_image_data_uri(url, max_size=(300, 240), quality=75):
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except Exception:
        return None
    if len(response.content) > 2 * 1024 * 1024:
        return None

    # 缩放到 300x240（3x 物理像素，高 DPI 清晰），JPEG quality=75
    try:
        img = Image.open(io.BytesIO(response.content))
        img.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        payload = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"
    except Exception:
        # Pillow 解码失败，退回原始编码
        payload = base64.b64encode(response.content).decode("ascii")
        content_type = response.headers.get("Content-Type") or "image/jpeg"
        return f"data:{content_type};base64,{payload}"
```

---

## 8. 代码重构

### 8.1 合并 normalize 函数

创建 `qbu_crawler/server/report_common.py`，迁入共享常量和归一化逻辑。

迁移顺序（避免中间状态 ImportError）：
1. 创建 `report_common.py`，定义所有共享函数
2. 修改 `report_pdf.py` 的 import 指向 `report_common`
3. 修改 `report.py` 的 import 指向 `report_common`
4. `report.py` 中保留重导出，防止外部导入依赖

### 8.2 时区修正

```python
from zoneinfo import ZoneInfo
_SHANGHAI = ZoneInfo("Asia/Shanghai")

def _report_ts(ts_str):
    if not ts_str:
        return None
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_SHANGHAI)
    return dt.replace(tzinfo=None)
```

---

## 9. Delta 轻量实现

### 9.1 数据获取

```python
def _load_previous_analytics(current_run_id):
    prev_run = models.get_previous_completed_run(current_run_id)
    if not prev_run or not prev_run.get("analytics_path"):
        return None
    path = prev_run["analytics_path"]
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

### 9.2 Delta 计算

```python
def _compute_kpi_deltas(current_kpis, prev_analytics):
    if not prev_analytics:
        return {}
    prev_kpis = prev_analytics.get("kpis", {})
    deltas = {}
    # prev_kpis.get(key, 0) 的默认值 0 必须保留，兼容旧版 analytics JSON
    for key in ("negative_review_rows", "ingested_review_rows", "product_count"):
        curr = current_kpis.get(key, 0) or 0
        prev = prev_kpis.get(key, 0) or 0
        diff = curr - prev
        deltas[f"{key}_delta"] = diff
        deltas[f"{key}_delta_display"] = (
            f"+{diff}" if diff > 0 else str(diff)
        ) if diff != 0 else "—"
    return deltas
```

---

## 10. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `report_templates/daily_report.css` | 修改 | 流式排版、issue-grid 改 block、证据内嵌样式、delta/alert 样式、`@page margin: 0`、色彩语义表 |
| `report_templates/daily_report.html.j2` | 修改 | 取消独立证据附录、问题簇事实呈现+中英双语+时间线+缩略图+交叉引用、Hero 主标题/信号灯/delta、竞品 gap callout |
| `report_templates/daily_report_email.html.j2` | **新建** | HTML 邮件模板（table 布局、内联样式） |
| `report_templates/daily_report_email_body.txt.j2` | 修改 | 精简版纯文本 |
| `report_pdf.py` | 修改 | 图表数据标签、风险矩阵（带门槛）、页眉页脚（float）、Y 轴视觉宽度截断、图片 Pillow 缩放、import report_common |
| `report.py` | 修改 | _humanize_bullets、_generate_hero_headline、_compute_alert_level、render_daily_email_html、HTML 邮件发送、BCC、import report_common |
| `report_analytics.py` | 修改 | _cluster_summary_items 补充 affected_product_count/first_seen/last_seen/date_published/英文原文、_risk_products 补充 total_reviews、_competitor_gap_analysis 新函数 |
| `report_snapshot.py` | 修改 | 渲染 HTML 邮件模板并传入 body_html |
| `report_common.py` | **新建** | 共享常量和 normalize 函数 |
| `models.py` | 修改 | 新增 get_previous_completed_run() |
| `config.py` | 修改 | 新增 EMAIL_BCC_MODE |
| `pyproject.toml` | 修改 | dependencies 新增 `pillow>=10.0` |
| `tests/test_report.py` | 修改 | 适配新邮件模板 |
| `tests/test_report_pdf.py` | 修改 | 适配新 PDF 参数 |
| `tests/test_report_common.py` | **新建** | normalize、humanize_bullets、compute_kpi_deltas、gap_analysis 测试 |

---

## 11. 依赖变更

**新增**：`pillow>=10.0`（图片缩放压缩，解决证据图片 base64 体积问题）

**不引入**：premailer（HTML 邮件模板简单，手工内联更可控）

---

## 12. 测试策略

### 12.1 自动化测试

- `tests/test_report.py`：适配 MIMEMultipart alternative、BCC、_humanize_bullets
- `tests/test_report_pdf.py`：更新 PDF 参数契约（prefer_css_page_size=False、display_header_footer=True、margin、float 布局页眉）
- `tests/test_report_common.py`（新建）：normalize、humanize_bullets、compute_kpi_deltas、gap_analysis
- delta 测试覆盖：prev_analytics 为 None / 字段缺失 / 正常

### 12.2 手工验证（仅本地开发，不纳入 CI）

- 生成新旧 PDF 对比
- 验证项：页数约 5 页、图表有数据标签、证据内嵌在问题簇中、有页码页眉、邮件有 HTML 版本

### 12.3 实施前的技术验证

以下项目需在正式开发前用最小 HTML 页面验证：
1. `displayHeaderFooter + prefer_css_page_size=False` 的实际 margin 效果（top 18mm 是否足够）
2. block 布局下 `break-inside: avoid` 的跨页行为
3. Pillow 缩放后的 base64 图片在 Playwright PDF 中的渲染质量

### 12.4 report_common.py 迁移顺序

1. 创建 `report_common.py`，定义所有共享函数
2. 修改 `report_pdf.py` import → `report_common`
3. 修改 `report.py` import → `report_common`，删除重复定义
4. `report.py` 保留重导出，防止外部导入依赖
