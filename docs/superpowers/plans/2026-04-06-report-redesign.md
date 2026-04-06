# 日报 PDF 与邮件重设计 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重设计日报 PDF（流式排版 + 证据内嵌）和邮件系统（HTML 富文本 + 人话化），信息密度提升 2 倍，页数从 11 页压缩到约 5 页。

**Architecture:** 提取 report_common.py 统一归一化逻辑 → 增强 report_analytics.py 数据层（时间线、产品覆盖面、gap analysis）→ 重写 CSS/HTML 模板（block 布局 + 证据内嵌）→ 升级邮件系统（HTML + 人话化）→ 改进 PDF 渲染参数（页眉页脚、图表）。

**Tech Stack:** Python 3.10+, Jinja2, matplotlib, Playwright, Pillow, openpyxl, SQLite

**Spec:** `docs/superpowers/specs/2026-04-06-report-redesign-design.md`

---

## 文件结构总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `qbu_crawler/server/report_common.py` | 新建 | 共享常量（_LABEL_DISPLAY 等）、归一化函数、人话化 bullets、hero headline、alert level |
| `qbu_crawler/server/report_analytics.py` | 修改 | _cluster_summary_items 补字段、_risk_products 补 total_reviews、新增 _competitor_gap_analysis |
| `qbu_crawler/models.py` | 修改 | 新增 get_previous_completed_run() |
| `qbu_crawler/server/report.py` | 修改 | import 改用 report_common、send_email 加 body_html/BCC、render_daily_email_html |
| `qbu_crawler/server/report_pdf.py` | 修改 | import 改用 report_common、图表改进、图片 Pillow 缩放、页眉页脚 |
| `qbu_crawler/server/report_snapshot.py` | 修改 | 接入 HTML 邮件渲染 |
| `qbu_crawler/server/report_templates/daily_report.css` | 修改 | 流式排版、block issue-grid、证据内嵌、delta/alert 样式 |
| `qbu_crawler/server/report_templates/daily_report.html.j2` | 修改 | 全面重构模板结构 |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | 新建 | HTML 邮件模板 |
| `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2` | 修改 | 精简版纯文本 |
| `qbu_crawler/config.py` | 修改 | EMAIL_BCC_MODE |
| `pyproject.toml` | 修改 | pillow 依赖 |
| `tests/test_report_common.py` | 新建 | report_common 单元测试 |
| `tests/test_report.py` | 修改 | 适配邮件改动 |
| `tests/test_report_pdf.py` | 修改 | 适配 PDF 参数 |

---

### Task 1: 创建 report_common.py — 提取共享常量和函数

**Files:**
- Create: `qbu_crawler/server/report_common.py`
- Create: `tests/test_report_common.py`
- Modify: `qbu_crawler/server/report_pdf.py:18-27` (import 改指向)
- Modify: `qbu_crawler/server/report.py` (import 改指向 + 保留重导出)

- [ ] **Step 1: 确认当前共享常量和函数清单**

确认从 `report.py` 和 `report_pdf.py` 中需要迁移的符号：

```
_LABEL_DISPLAY, _SEVERITY_DISPLAY, _PRIORITY_DISPLAY
_label_display, _summary_text, _join_label_codes, _join_label_counts
_derive_review_label_codes
normalize_deep_report_analytics
```

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && grep -n "_LABEL_DISPLAY\|_SEVERITY_DISPLAY\|_PRIORITY_DISPLAY" qbu_crawler/server/report.py | head -20`

- [ ] **Step 2: 写 report_common.py 的失败测试**

```python
# tests/test_report_common.py
from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _SEVERITY_DISPLAY,
    _PRIORITY_DISPLAY,
    label_display,
    summary_text,
    normalize_deep_report_analytics,
)

def test_label_display_known_code():
    assert label_display("quality_stability") == "质量稳定性"

def test_label_display_unknown_code():
    assert label_display("unknown_xyz") == "unknown_xyz"

def test_summary_text_cn_preferred():
    review = {"headline_cn": "标题", "body_cn": "内容", "headline": "Title", "body": "Content"}
    result = summary_text(review)
    assert "标题" in result
    assert "内容" in result

def test_normalize_handles_none():
    result = normalize_deep_report_analytics(None)
    assert result["kpis"]["product_count"] == 0
    assert result["mode"] == "baseline"

def test_normalize_computes_rates():
    analytics = {"kpis": {"ingested_review_rows": 100, "negative_review_rows": 10, "translated_count": 90}}
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["negative_review_rate_display"] == "10.0%"
    assert result["kpis"]["translation_completion_rate_display"] == "90.0%"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qbu_crawler.server.report_common'`

- [ ] **Step 4: 创建 report_common.py**

从 `report.py` 中复制 `_LABEL_DISPLAY`、`_SEVERITY_DISPLAY`、`_PRIORITY_DISPLAY` 字典和 `_label_display`、`_summary_text`、`_join_label_codes`、`_join_label_counts`、`_derive_review_label_codes`、`normalize_deep_report_analytics` 函数到新文件。公开函数去掉下划线前缀的别名（保留原名以兼容）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -v`
Expected: PASS

- [ ] **Step 6: 修改 report_pdf.py import**

将 `report_pdf.py:18-27` 的 import 从 `from qbu_crawler.server.report import ...` 改为 `from qbu_crawler.server.report_common import ...`。

- [ ] **Step 7: 修改 report.py — 删除重复定义 + 保留重导出**

在 `report.py` 顶部加 `from qbu_crawler.server.report_common import ...`，删除重复的常量和函数定义。保留重导出以防外部依赖。

- [ ] **Step 8: 运行全量测试确认无回归**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py tests/test_report_pdf.py tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py qbu_crawler/server/report.py qbu_crawler/server/report_pdf.py
git commit -m "refactor: extract report_common.py with shared constants and normalize logic"
```

---

### Task 2: 增强 report_analytics.py 数据层

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:452-555` (_cluster_summary_items, _risk_products)
- Modify: `tests/test_report_common.py` (新增数据层测试)

- [ ] **Step 1: 写 _cluster_summary_items 新字段的失败测试**

```python
# tests/test_report_common.py (追加)
from qbu_crawler.server.report_analytics import _cluster_summary_items

def _make_labeled_review(ownership, polarity, label_code, severity="medium",
                         product_sku="SKU-1", product_name="Product A",
                         date_published="2026-03-01", headline="Title", body="Body",
                         headline_cn="标题", body_cn="正文", images=None):
    return {
        "review": {
            "ownership": ownership, "product_sku": product_sku,
            "product_name": product_name, "date_published": date_published,
            "headline": headline, "body": body,
            "headline_cn": headline_cn, "body_cn": body_cn,
        },
        "labels": [{"label_code": label_code, "label_polarity": polarity, "severity": severity, "confidence": 0.9}],
        "images": images or [],
    }

def test_cluster_has_affected_product_count():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="B"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["affected_product_count"] == 2

def test_cluster_has_timeline():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-02-14"),
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-03-29"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] == "2026-02-14"
    assert items[0]["last_seen"] == "2026-03-29"

def test_cluster_example_has_en_and_date():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             headline="Broke!", body="Support beam snapped",
                             date_published="2026-03-12"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    ex = items[0]["example_reviews"][0]
    assert ex["headline_en"] == "Broke!"
    assert ex["body_en"] == "Support beam snapped"
    assert ex["date_published"] == "2026-03-12"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py::test_cluster_has_affected_product_count -v`
Expected: FAIL

- [ ] **Step 3: 修改 _cluster_summary_items — 补充字段**

在 `report_analytics.py:461-492` 的 `grouped.setdefault()` 中增加 `"affected_products": set()` 和 `"dates": []`。在循环中增加 `cluster["affected_products"].add(...)` 和 `cluster["dates"].append(...)`。在 `example_reviews.append()` 字典中增加 `"headline_en"`, `"body_en"`, `"date_published"`。在最终导出时计算 `affected_product_count`, `first_seen`, `last_seen` 并 pop `affected_products` 和 `dates`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -k "cluster" -v`
Expected: PASS

- [ ] **Step 5: 写 _risk_products total_reviews 的失败测试**

```python
from qbu_crawler.server.report_analytics import _risk_products

def test_risk_products_has_total_reviews():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    # 需要传入 snapshot_products 来查 review_count
    items = _risk_products(reviews, snapshot_products=[
        {"sku": "SKU-1", "review_count": 50},
    ])
    assert items[0]["total_reviews"] == 50
```

- [ ] **Step 6: 修改 _risk_products — 补充 total_reviews**

在 `_risk_products` 签名中增加 `snapshot_products=None` 参数。构建 `sku_to_review_count` 字典。在产品字典初始化时加 `"total_reviews": sku_to_review_count.get(key, 0)`。

**必须同步修改调用处**（`report_analytics.py` 的 `build_report_analytics()` 函数）：

```python
# build_report_analytics() 中，将：
risk_products = _risk_products(labeled_reviews)
# 改为：
risk_products = _risk_products(labeled_reviews, snapshot_products=snapshot.get("products", []))
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -k "risk_products" -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_common.py
git commit -m "feat: add timeline, affected_product_count, total_reviews to analytics data layer"
```

---

### Task 3: 竞品 Gap Analysis + models.py delta 基础

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py` (新增 _competitor_gap_analysis)
- Modify: `qbu_crawler/models.py` (新增 get_previous_completed_run)
- Modify: `qbu_crawler/server/report_common.py` (新增 _compute_kpi_deltas, _load_previous_analytics)
- Modify: `tests/test_report_common.py`

- [ ] **Step 1: 写 gap analysis 失败测试**

```python
def test_competitor_gap_analysis():
    normalized = {
        "self": {"top_negative_clusters": [
            {"label_code": "quality_stability", "review_count": 13},
            {"label_code": "material_finish", "review_count": 7},
        ]},
        "competitor": {"top_positive_themes": [
            {"label_code": "solid_build", "review_count": 69},
            {"label_code": "quality_stability", "review_count": 5},  # 交集
        ]},
    }
    from qbu_crawler.server.report_common import _competitor_gap_analysis
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    assert gaps[0]["label_code"] == "quality_stability"
    assert gaps[0]["competitor_positive_count"] == 5
    assert gaps[0]["own_negative_count"] == 13
```

- [ ] **Step 2: 实现 _competitor_gap_analysis 并通过测试**

在 `report_common.py` 中实现函数（按 spec §3.6）。

- [ ] **Step 3: 写 _compute_kpi_deltas 失败测试**

```python
def test_compute_kpi_deltas_normal():
    from qbu_crawler.server.report_common import _compute_kpi_deltas
    current = {"negative_review_rows": 78, "ingested_review_rows": 636, "product_count": 9}
    prev = {"kpis": {"negative_review_rows": 66, "ingested_review_rows": 500, "product_count": 9}}
    deltas = _compute_kpi_deltas(current, prev)
    assert deltas["negative_review_rows_delta"] == 12
    assert deltas["negative_review_rows_delta_display"] == "+12"
    assert deltas["product_count_delta"] == 0
    assert deltas["product_count_delta_display"] == "—"

def test_compute_kpi_deltas_no_prev():
    from qbu_crawler.server.report_common import _compute_kpi_deltas
    deltas = _compute_kpi_deltas({"negative_review_rows": 78}, None)
    assert deltas == {}

def test_compute_kpi_deltas_missing_field():
    from qbu_crawler.server.report_common import _compute_kpi_deltas
    deltas = _compute_kpi_deltas({"negative_review_rows": 10}, {"kpis": {}})
    assert deltas["negative_review_rows_delta"] == 10
```

- [ ] **Step 4: 实现 _compute_kpi_deltas 并通过测试**

- [ ] **Step 5: 实现 models.get_previous_completed_run()**

注意：使用项目中 models.py 的实际数据库连接模式（查看现有函数如 `create_workflow_run` 的写法来确定连接方式，可能是 `sqlite3.connect(config.DB_PATH)` 或类似方式）。以下为逻辑参考：

```python
# qbu_crawler/models.py — 适配实际连接模式
def get_previous_completed_run(current_run_id):
    # 使用项目现有的连接模式（参照其他函数）
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """SELECT * FROM workflow_runs
               WHERE workflow_type = 'daily'
                 AND status = 'completed'
                 AND analytics_path IS NOT NULL
                 AND analytics_path != ''
                 AND id < ?
               ORDER BY id DESC LIMIT 1""",
            (current_run_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

- [ ] **Step 6: 运行全部 report_common 测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_analytics.py qbu_crawler/models.py tests/test_report_common.py
git commit -m "feat: add competitor gap analysis, KPI delta computation, and previous run query"
```

---

### Task 4: Hero 页逻辑 — headline + alert + humanize_bullets

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `tests/test_report_common.py`

- [ ] **Step 1: 写 _generate_hero_headline 失败测试**

```python
def test_hero_headline_with_delta():
    from qbu_crawler.server.report_common import _generate_hero_headline
    normalized = {
        "self": {"risk_products": [{"product_name": "Cabela's Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 14}]}],
                 "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
        "kpis": {"negative_review_rows_delta": 12, "product_count": 9,
                 "own_product_count": 3, "competitor_product_count": 6},
    }
    result = _generate_hero_headline(normalized)
    assert "环比" in result
    assert "Cabela's Stuffer" in result
    assert "质量稳定性" in result
```

- [ ] **Step 2: 实现 _generate_hero_headline（按 spec §2.3.2）**

- [ ] **Step 3: 写 _compute_alert_level 失败测试**

```python
def test_alert_level_red():
    from qbu_crawler.server.report_common import _compute_alert_level
    normalized = {
        "self": {"top_negative_clusters": [{"severity": "high", "review_count": 10}]},
        "kpis": {"negative_review_rows_delta": 0},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "red"

def test_alert_level_green():
    from qbu_crawler.server.report_common import _compute_alert_level
    normalized = {
        "self": {"top_negative_clusters": []},
        "kpis": {"negative_review_rows_delta": 0},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "green"
```

- [ ] **Step 4: 实现 _compute_alert_level（按 spec §2.3.3）**

- [ ] **Step 5: 写 _humanize_bullets 失败测试**

```python
def test_humanize_bullets_has_rate():
    from qbu_crawler.server.report_common import _humanize_bullets
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 14}]}]},
        "competitor": {"top_positive_themes": [{"label_display": "做工扎实", "review_count": 69, "label_code": "solid_build"}],
                       "gap_analysis": []},
        "kpis": {"product_count": 9, "ingested_review_rows": 636, "untranslated_count": 0,
                 "negative_review_rows_delta": 5, "translation_completion_rate": 1.0},
    }
    bullets = _humanize_bullets(normalized)
    assert len(bullets) == 3
    assert "36%" in bullets[0]  # 差评率 18/50
    assert "新增 5 条" in bullets[0]
```

- [ ] **Step 6: 实现 _humanize_bullets（按 spec §6.2）**

- [ ] **Step 7: 运行测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add qbu_crawler/server/report_common.py tests/test_report_common.py
git commit -m "feat: add data-driven hero headline, alert level, and humanized bullets"
```

---

### Task 5: 图片 Pillow 缩放 + 依赖

**Files:**
- Modify: `pyproject.toml`
- Modify: `qbu_crawler/server/report_pdf.py` (_inline_image_data_uri)

- [ ] **Step 1: pyproject.toml 加 pillow 依赖**

在 `dependencies` 列表中加入 `"pillow>=10.0"`.

- [ ] **Step 2: 安装依赖**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv sync`

- [ ] **Step 3: 修改 _inline_image_data_uri 加入 Pillow 缩放**

按 spec §7 实现。下载原图后用 `Image.thumbnail((300, 240), Image.LANCZOS)` 缩放，JPEG quality=75 重新编码。Pillow 解码失败时 fallback 到原始编码。

- [ ] **Step 4: 运行现有 PDF 测试确认无回归**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_pdf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock qbu_crawler/server/report_pdf.py
git commit -m "feat: add Pillow image thumbnail compression for PDF evidence images"
```

---

### Task 6: 图表改进 — 数据标签 + 截断 + 严重度分色 + 风险矩阵

**Files:**
- Modify: `qbu_crawler/server/report_pdf.py:98-145` (图表函数)

- [ ] **Step 1: 修改 _save_bar_chart — 加数据标签**

在 `ax.barh()` 后加 `ax.bar_label(bars, fmt="%.0f", padding=4, fontsize=9, color="#4a4a4a")`。

- [ ] **Step 2: 新增 _truncate_label — 视觉宽度感知截断**

```python
def _truncate_label(label, max_visual_width=36):
    width = 0
    for i, ch in enumerate(label):
        width += 2 if ord(ch) > 127 else 1
        if width > max_visual_width:
            return label[:i] + "..."
    return label
```

修改 `_chart_series` 使用 `_truncate_label`。

- [ ] **Step 3: 修改 build_chart_assets — 严重度分色**

问题簇图表从单色改为按严重度分色（`high=#6b3328, medium=#b7633f, low=#a89070`）。需要在 `_save_bar_chart` 签名中支持 `color` 参数接收列表。

- [ ] **Step 4: 新增 _save_risk_matrix — 风险矩阵散点图（带门槛）**

按 spec §4.3 实现，仅在产品数 >= 6 时生成。标注使用 SKU 而非产品名。

- [ ] **Step 5: 修改 build_chart_assets 接入风险矩阵**

在 `risk_products` 长度 >= 6 时调用 `_save_risk_matrix`。

- [ ] **Step 6: 运行 PDF 测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_pdf.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_pdf.py
git commit -m "feat: chart improvements — data labels, visual truncation, severity colors, risk matrix"
```

---

### Task 7: CSS 重设计 — 流式排版 + 证据内嵌样式

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report.css`

- [ ] **Step 1: 修改 @page 和 分页规则**

```css
@page { size: A4; margin: 0; }  /* margin 由 Playwright 控制 */

.report-page-hero { break-after: page; }
.report-page { break-after: auto; }
.page-frame { min-height: auto; }
```

- [ ] **Step 2: 添加 section 分隔样式**

```css
.report-section + .report-section {
  margin-top: 28px;
  padding-top: 20px;
  border-top: 3px solid var(--accent);
}
```

- [ ] **Step 3: issue-grid 改为 block 布局**

```css
.issue-grid { display: block; }
.issue-card + .issue-card { margin-top: 14px; }
```

- [ ] **Step 4: 添加证据内嵌样式**

按 spec §3.3 添加 `.issue-evidence-strip`、`.evidence-thumb`、`.evidence-label`、`.evidence-more`、`.quote-cn`、`.quote-en`、`.issue-timeline`、`.issue-xref` 样式。

- [ ] **Step 5: 添加 delta 和 alert 样式**

按 spec §2.3 添加 `.delta`、`.delta-up`、`.delta-down`、`.alert-signal`、`.alert-red`、`.alert-yellow`、`.alert-green` 样式。

- [ ] **Step 6: 添加 gap-callout 样式**

```css
.gap-callout {
  margin-top: 14px;
  padding: 14px;
  border: 2px solid var(--accent-soft);
  border-radius: 16px;
  background: rgba(234, 214, 200, 0.3);
}
```

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report.css
git commit -m "feat: CSS redesign — flow layout, block issue-grid, evidence strip, delta/alert styles"
```

---

### Task 8: HTML 模板重构

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report.html.j2`

- [ ] **Step 1: 修改 Hero 页 — 增加 delta + alert + 数据化 headline**

在 metric-card 中加 delta span（条件渲染）。在 hero-support 区域加 alert-signal div。将 `hero_headline` 改用 `analytics.report_copy.hero_headline`（由 _generate_hero_headline 生成）。

- [ ] **Step 2: 修改 section class — 流式化**

所有 `<section class="report-page">` 改为 `<section class="report-page report-section">`（Hero 除外），去掉固定分页语义。

- [ ] **Step 3: 重写问题簇区域 — 事实呈现 + 中英双语 + 证据内嵌**

按 spec §3.2 重写 issue-card：
- `issue-facts` 展示差评数 + 涉及产品数 + 图片证据数
- `issue-timeline` 展示首次出现/最近一条日期
- `issue-quotes` 中英双语 blockquote + 评论日期
- `issue-evidence-strip` 条件渲染缩略图（最多 3 张 + "+N"）
- `issue-xref` Excel 交叉引用

移除旧的 `possible_cause_boundary` 和 `improvement_direction`。

- [ ] **Step 4: 删除独立证据附录 section**

移除模板底部的 `<section class="report-page">` 证据附录（`evidence-directory` 块）。

- [ ] **Step 5: 修改竞品 Benchmark 页 — 加 gap callout**

在竞品部分顶部增加 gap_analysis 条件渲染块。

- [ ] **Step 6: 用测试脚本本地验证 HTML 渲染**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run python scripts/test_report_generation.py`
Expected: 生成 HTML 预览文件，手工检查结构正确。

- [ ] **Step 7: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report.html.j2
git commit -m "feat: HTML template redesign — flow layout, evidence inline, gap callout, dual-language quotes"
```

---

### Task 9: PDF 渲染改进 — 页眉页脚 + prefer_css_page_size

**Files:**
- Modify: `qbu_crawler/server/report_pdf.py:236-269` (generate_pdf_report)
- Modify: `tests/test_report_pdf.py`

- [ ] **Step 1: 修改 generate_pdf_report — 更新 page.pdf() 参数**

按 spec §5.1：
- `prefer_css_page_size=False`
- `display_header_footer=True`
- `margin={"top": "18mm", "bottom": "16mm", "left": "10mm", "right": "10mm"}`
- `header_template` 和 `footer_template` 使用 float 布局
- 需要将 `snapshot` 传入 `generate_pdf_report` 函数（当前签名只有 `snapshot, analytics, output_path`，snapshot 已有）

- [ ] **Step 2: 修改 render_report_html — 接入新数据（含 delta 完整链路）**

在 `render_report_html` 中，必须完整连接 delta 数据链路和所有新函数：

```python
def render_report_html(snapshot, analytics, asset_dir):
    analytics = _normalized_analytics(analytics)

    # 1. Delta: 加载前一次 run 的 analytics，计算 KPI delta
    prev_analytics = _load_previous_analytics(snapshot.get("run_id"))
    kpi_deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)
    analytics["kpis"].update(kpi_deltas)

    # 2. Hero headline (数据驱动)
    analytics["report_copy"]["hero_headline"] = _generate_hero_headline(analytics)

    # 3. Alert level
    alert_level, alert_text = _compute_alert_level(analytics)
    analytics["alert_level"] = alert_level
    analytics["alert_text"] = alert_text

    # 4. Humanized bullets
    analytics["report_copy"]["executive_bullets_human"] = _humanize_bullets(analytics)

    # 5. Gap analysis
    analytics["competitor"]["gap_analysis"] = _competitor_gap_analysis(analytics)

    # ... 其余渲染逻辑不变（图片 data URI、图表、模板渲染）
```

注意 `_load_previous_analytics` 在 Task 3 已实现，需从 `report_common` import。

- [ ] **Step 3: 更新 test_report_pdf.py — 适配新参数**

更新 FakePage mock 的 `pdf()` 断言：
- `prefer_css_page_size` 改为 `False`
- 新增 `display_header_footer=True`
- 新增 `margin` 断言
- FakePage.pdf() stub 需要接受 `header_template`/`footer_template` 关键字参数

- [ ] **Step 4: 运行测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report_pdf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report_pdf.py tests/test_report_pdf.py
git commit -m "feat: PDF header/footer with float layout, prefer_css_page_size=False"
```

---

### Task 10: 邮件系统升级 — 纯文本精简 + HTML 模板 + 发送改造

**Files:**
- Modify: `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2`
- Create: `qbu_crawler/server/report_templates/daily_report_email.html.j2`
- Modify: `qbu_crawler/server/report.py` (send_email, render_daily_email_html, _build_email_subject)
- Modify: `qbu_crawler/config.py` (EMAIL_BCC_MODE)
- Modify: `qbu_crawler/server/report_snapshot.py` (接入 HTML 邮件)
- Modify: `tests/test_report.py`

- [ ] **Step 1: 修改纯文本邮件模板**

按 spec §6.1 精简 `daily_report_email_body.txt.j2`。删除 baseline/incremental 系统状态说明。使用 `executive_bullets_human`。

- [ ] **Step 2: 创建 HTML 邮件模板**

按 spec §6.4 创建 `daily_report_email.html.j2`。使用 table 布局，600px 宽度，所有样式手工内联。KPI 2x2 表格 + 3 条要点 + TOP3 风险产品表格（产品名 | 主要问题 | 差评数）。为 Outlook 添加条件注释。

- [ ] **Step 3: 修改 config.py — 新增 EMAIL_BCC_MODE**

```python
EMAIL_BCC_MODE = os.getenv("EMAIL_BCC_MODE", "false").lower() == "true"
```

- [ ] **Step 4: 修改 report.py — send_email 加 body_html 和 BCC**

按 spec §6.5：
- 签名加 `body_html=None`
- `MIMEMultipart("mixed")` 包裹 `MIMEMultipart("alternative")`
- BCC 模式：`msg["To"] = config.SMTP_FROM`，`msg["Bcc"] = recipients`

- [ ] **Step 5: 新增 render_daily_email_html 和 _build_email_subject**

按 spec §6.6 和 §6.3 在 `report.py` 中实现。

**关键**：`_build_email_subject` 必须替换现有 `build_daily_deep_report_email` 中使用 `daily_report_email_subject.txt.j2` 模板渲染主题行的逻辑（当前位于 `report.py:719` 附近）。改为直接调用 `_build_email_subject(normalized, logical_date)` 返回主题行字符串，不再使用模板文件。

- [ ] **Step 5b: 删除或保留 daily_report_email_subject.txt.j2**

`daily_report_email_subject.txt.j2` 模板文件不再被使用。将其删除并从 git 中移除，避免维护两套主题行逻辑。

- [ ] **Step 6: 修改 report_snapshot.py — 接入 HTML 邮件渲染**

在 `generate_full_report_from_snapshot()` 中，调用 `report.render_daily_email_html(snapshot, analytics)` 获取 `body_html`，传入 `send_email()`。

- [ ] **Step 7: 更新 test_report.py — 适配邮件改动**

更新 `send_email` 的测试用例：验证 `MIMEMultipart("alternative")` 结构、BCC 模式、`body_html` 参数。

- [ ] **Step 8: 运行测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_email_body.txt.j2 \
        qbu_crawler/server/report_templates/daily_report_email.html.j2 \
        qbu_crawler/server/report.py qbu_crawler/config.py \
        qbu_crawler/server/report_snapshot.py tests/test_report.py
git rm qbu_crawler/server/report_templates/daily_report_email_subject.txt.j2
git commit -m "feat: email upgrade — HTML template, humanized text, BCC, dynamic subject line"
```

---

### Task 11: 时区修正 + 集成验证

**Files:**
- Modify: `qbu_crawler/server/report.py` (_report_ts)

- [ ] **Step 1: 修改 _report_ts 时区处理**

按 spec §8.2：如果收到带时区的字符串，先 `astimezone(_SHANGHAI)` 再剥离。

- [ ] **Step 2: 全量测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py tests/test_report_pdf.py tests/test_report_common.py -v`
Expected: ALL PASS

- [ ] **Step 3: 生成测试 PDF 对比**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run python scripts/test_report_generation.py`

手工验证：
- [ ] 页数约 5 页（vs 旧 11 页）
- [ ] 图表有数据标签
- [ ] 证据内嵌在问题簇中（非独立附录）
- [ ] 有页码和页眉
- [ ] 问题簇有时间线和涉及产品数
- [ ] 评论中英双语显示
- [ ] 邮件有 HTML 版本
- [ ] Hero 主标题是数据驱动的

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report.py
git commit -m "fix: timezone handling in _report_ts, integration verification pass"
```

---

### Task 12: 文档同步

**Files:**
- Modify: `CLAUDE.md` (如有结构变更需更新项目结构图)
- Modify: `docs/superpowers/specs/2026-04-06-report-redesign-design.md` (状态改为 Implemented)

- [ ] **Step 1: 更新设计文档状态**

将 spec 文档状态从 `Review v2` 改为 `Implemented`。

- [ ] **Step 2: 更新 CLAUDE.md 项目结构图**

在项目结构中加入 `report_common.py`。

- [ ] **Step 3: 记录开发日志**

在 `docs/devlogs/` 中创建 `D013-report-redesign.md`，记录关键改动和踩坑经验。

- [ ] **Step 4: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: update spec status, project structure, and devlog for report redesign"
```
