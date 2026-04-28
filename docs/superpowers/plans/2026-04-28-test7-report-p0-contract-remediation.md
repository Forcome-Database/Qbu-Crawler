# Test7 Report P0 Contract Remediation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按测试7审计结论先完成 P0 止血：建立轻量报告语义契约，修复 LLM 产品集合校验、fallback 重复建议、诊断卡缺证据、热力图解释错位、近30天筛选、竞品英文和 delivery deadletter 状态问题。

**Architecture:** 采用 B 方案：轻量 contract-first，不做完整报表重构。先在现有 analytics / normalize 链路中补 `report_user_contract` 和兼容字段，让 HTML、Excel、邮件优先消费稳定语义；旧字段保留作为兼容 fallback。LLM 只改写规则层锁定的事实，fallback 必须证据化。

**Tech Stack:** Python 3.10+, pytest, SQLite, Jinja2, openpyxl, HTML/JS template, existing workflow/notifier workers.

---

## Entry Context

- 审计文档：`docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- 设计文档：`docs/superpowers/specs/2026-04-28-test7-report-p0-contract-design.md`
- 生产测试目录：`C:\Users\leo\Desktop\生产测试\报告\测试7`
- P0 原则：
  - 不直接做完整报表重构。
  - 不新增 DB migration。
  - 不改变 `report_semantics = bootstrap | incremental`。
  - 所有用户可见建议必须绑定证据或明确证据不足。

---

## File Map

| File | Responsibility | Tasks |
|---|---|---|
| `qbu_crawler/server/report_llm.py` | LLM v3 schema、prompt、`assert_consistency()` 事实校验 | T1 |
| `qbu_crawler/server/report_analytics.py` | fallback priorities、竞品短板、热力图 cell、风险产品灯号数据 | T2, T5, T6, T8 |
| `qbu_crawler/server/report_common.py` | 归一化、轻量 `report_user_contract`、issue cards、KPI 语义字段 | T2, T3, T8 |
| `qbu_crawler/server/report_snapshot.py` | full report 链路中 LLM/fallback/deep analysis 合并后刷新 contract | T2, T3 |
| `qbu_crawler/server/report_html.py` | 全景近 30 天标注 | T7 |
| `qbu_crawler/server/report.py` | Excel “现在该做什么”“竞品启示”字段消费 | T2, T6 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 诊断卡图片/AI建议/deep analysis、热力图完整产品名、全景 data-recent | T3, T5, T7 |
| `qbu_crawler/server/report_templates/daily_report_v3.js` | 热力图点击下钻筛选 | T5 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | 需关注产品统一字段 | T8 |
| `qbu_crawler/server/workflows.py` | completed run 的 delivery deadletter reconcile | T9 |
| `qbu_crawler/server/notifier.py` | deadletter 统计和降级 helper | T9 |
| `tests/server/test_llm_assert_consistency.py` | LLM 产品集合校验回归 | T1 |
| `tests/server/test_fallback_priorities.py` | fallback 建议证据化和差异化 | T2 |
| `tests/test_report_common.py` / `tests/server/test_attachment_html_issues.py` | issue cards / HTML 诊断卡 | T3 |
| `tests/server/test_heatmap_optimization.py` | heatmap 数据和模板 | T5 |
| `tests/server/test_competitor_insights_v12.py` / `tests/server/test_excel_sheets.py` | 竞品中文和 Excel | T6 |
| `tests/test_v3_html.py` | 全景近 30 天筛选 | T7 |
| `tests/test_report_common.py` / `tests/server/test_email_full_template.py` | 风险/关注口径 | T8 |
| `tests/server/test_workflow_ops_alert_wiring.py` / `tests/server/test_internal_ops_alert.py` | delivery deadletter | T9 |

---

## Chunk 1: LLM 与行动建议契约止血

### Task 1: 修复 LLM `affected_products` 校验边界

**Files:**
- Modify: `qbu_crawler/server/report_llm.py`
- Test: `tests/server/test_llm_assert_consistency.py`
- Optional test: `tests/server/test_llm_prompt_v3.py`

- [ ] **Step 1.1: 写失败测试：问题簇产品不在 `risk_products` 也应通过**

在 `tests/server/test_llm_assert_consistency.py` 增加测试：

```python
def test_assert_consistency_allows_products_from_label_allowed_products():
    copy = {
        "hero_headline": "健康指数 96.2",
        "executive_summary": "摘要",
        "executive_bullets": [],
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "优化进料结构",
            "full_action": "针对结构设计问题，结合用户反馈逐项复核关键尺寸、适配方式和使用路径，优先验证最常被提到的卡点并形成改良清单。",
            "evidence_count": 1,
            "evidence_review_ids": [101],
            "affected_products": ["Walton's #22 Meat Grinder"],
        }],
    }
    kpis = {"health_index": 96.2}
    risk_products = [{"product_name": ".75 HP Grinder (#12)"}]
    reviews = [{"id": 101}]
    allowed_products_by_label = {
        "structure_design": {"Walton's #22 Meat Grinder"}
    }

    assert_consistency(
        copy,
        kpis,
        risk_products=risk_products,
        reviews=reviews,
        allowed_products_by_label=allowed_products_by_label,
    )
```

- [ ] **Step 1.2: 写失败测试：完全未知产品仍应失败**

同文件增加测试，`affected_products=["Unknown"]`，`allowed_products_by_label` 和 snapshot/risk 集合都不包含时应抛 `AssertionError`。

- [ ] **Step 1.3: 运行 LLM consistency 测试，确认失败**

Run:

```bash
uv run pytest tests/server/test_llm_assert_consistency.py -v
```

Expected: 新测试因 `assert_consistency()` 不接受 `allowed_products_by_label` 或仍按 `risk_products` 校验而失败。

- [ ] **Step 1.4: 修改 `assert_consistency()` 签名**

在 `qbu_crawler/server/report_llm.py` 中保留兼容参数，新增 keyword-only 参数：

```python
def assert_consistency(
    copy: dict,
    kpis: dict,
    *,
    risk_products=_SENTINEL,
    reviews=_SENTINEL,
    allowed_products_by_label: dict | None = None,
    all_product_names: set[str] | None = None,
) -> None:
```

规则：
- 若 priority 有 `label_code` 且 `allowed_products_by_label[label_code]` 非空，使用该集合校验。
- 否则使用 `all_product_names`。
- 再否则保持旧行为：使用 `risk_products`。

- [ ] **Step 1.5: 在 LLM 调用处传入 allowed products**

在 `generate_report_insights_with_validation()` 中从 analytics 生成：

```python
allowed_products_by_label = _allowed_products_by_label(analytics)
all_product_names = _all_product_names(analytics, snapshot)
```

最小 helper 可放在 `report_llm.py` 内，不新增复杂抽象。

- [ ] **Step 1.6: 更新 prompt 约束**

在 v3 prompt 中补一句：`affected_products 必须来自对应 label_code 的问题簇涉及产品；不要只限于高风险产品。`

- [ ] **Step 1.7: 运行测试**

Run:

```bash
uv run pytest tests/server/test_llm_assert_consistency.py tests/server/test_llm_prompt_v3.py -v
```

Expected: PASS。

---

### Task 2: fallback priorities 差异化并绑定证据

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_fallback_priorities.py`
- Test: `tests/server/test_excel_sheets.py`

- [ ] **Step 2.1: 写失败测试：fallback 不允许 `full_action` 全重复**

在 `tests/server/test_fallback_priorities.py` 增加测试，构造 3 个不同 `label_code` 的 clusters，断言：

```python
actions = [item["full_action"] for item in out]
assert len(set(actions)) == len(actions)
```

- [ ] **Step 2.2: 写失败测试：fallback 输出证据字段**

同文件断言每条输出包含：

```python
assert item["top_complaint"]
assert item["evidence_count"] >= 1
assert item["evidence_review_ids"]
assert item["affected_products"]
assert item["source"] == "rule_fallback"
```

对于没有证据的 cluster，断言：

```python
assert item["source"] == "evidence_insufficient"
assert "证据不足" in item["full_action"]
```

- [ ] **Step 2.3: 运行 fallback 测试，确认失败**

Run:

```bash
uv run pytest tests/server/test_fallback_priorities.py -v
```

Expected: 新测试失败，因为当前 fallback 使用同一个 `fallback_full_action`。

- [ ] **Step 2.4: 重写 `build_fallback_priorities()` 的生成规则**

在 `qbu_crawler/server/report_analytics.py` 中：
- 按 `label_code` 选择行动模板。
- 优先从 cluster 取 `example_reviews`、`deep_analysis.actionable_summary`、`affected_products`。
- 从 example review 取 `id/review_id` 作为 `evidence_review_ids`。
- `top_complaint` 优先中文 `headline_cn/body_cn`，再回退英文。

建议最小模板键：
- `structure_design`
- `quality_stability`
- `service_fulfillment`
- `material_finish`
- `assembly_installation`
- default

- [ ] **Step 2.5: 同步 `report_user_contract.action_priorities`**

在 `report_common.py` 新增或扩展归一化逻辑，保证 normalized analytics 中存在：

```python
normalized["report_user_contract"]["action_priorities"] = priorities
```

短期保持：

```python
normalized["report_copy"]["improvement_priorities"] = priorities
```

- [ ] **Step 2.6: Excel 优先消费 contract**

在 `qbu_crawler/server/report.py` 的“现在该做什么”sheet：

```python
priorities = (
    ((analytics.get("report_user_contract") or {}).get("action_priorities"))
    or (analytics.get("report_copy") or {}).get("improvement_priorities")
    or []
)
```

- [ ] **Step 2.7: 运行相关测试**

Run:

```bash
uv run pytest tests/server/test_fallback_priorities.py tests/server/test_excel_sheets.py -v
```

Expected: PASS。

---

## Chunk 2: 诊断卡证据展示

### Task 3: issue cards 透传图片、AI 建议和 deep analysis

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/test_report_common.py`
- Test: `tests/server/test_attachment_html_issues.py`

- [ ] **Step 3.1: 写失败测试：`issue_cards.recommendation` 使用 `full_action`**

在 `tests/test_report_common.py` 中构造 `report_copy.improvement_priorities` 只有 `full_action` 没有 `action` 的数据，断言：

```python
card = result["issue_cards"][0]
assert card["recommendation"] == "..."
```

- [ ] **Step 3.2: 写失败测试：issue card 包含 deep analysis 字段**

构造 cluster 带：

```python
"deep_analysis": {
    "actionable_summary": "...",
    "failure_modes": [{"name": "xxx"}],
    "root_causes": [{"name": "yyy"}],
    "user_workarounds": ["zzz"],
}
```

断言 card 包含：

```python
assert card["ai_recommendation"]
assert card["failure_modes"]
assert card["root_causes"]
assert card["user_workarounds"]
```

- [ ] **Step 3.3: 写失败测试：HTML 渲染图片证据和 AI 建议**

在 `tests/server/test_attachment_html_issues.py` 增加或扩展 HTML 渲染测试，断言：

```python
assert "issue-image-evidence" in html
assert "ai-box-suggest" in html
assert "根因" in html or "失效模式" in html
```

- [ ] **Step 3.4: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/test_report_common.py tests/server/test_attachment_html_issues.py -v
```

Expected: 新测试失败。

- [ ] **Step 3.5: 修改 issue card 构造逻辑**

在 `report_common.py`：
- `priority_by_label` 取值从 `p.get("action")` 改为 `p.get("full_action") or p.get("action")`。
- card 新增：
  - `ai_recommendation`
  - `failure_modes`
  - `root_causes`
  - `user_workarounds`
- `recommendation` 保持兼容，指向 `ai_recommendation`。

- [ ] **Step 3.6: 确保 deep analysis 合并后刷新 contract**

在 `report_snapshot.py` 中，LLM/fallback 和 `deep_analysis` 合并后，重新 normalize 或调用轻量 contract builder，避免落盘 analytics 有 deep analysis 但 issue cards 没同步。

- [ ] **Step 3.7: 修改 HTML 模板**

在 `daily_report_v3.html.j2` 的 issue card body 中：
- 在 quote blocks 后展示 `card.image_evidence` 缩略图。
- 展示 `card.ai_recommendation`。
- 如有 `failure_modes/root_causes/user_workarounds`，展示简短列表。

CSS 若已有通用图片样式则复用；需要新增时只加最小 class。

- [ ] **Step 3.8: 运行测试**

Run:

```bash
uv run pytest tests/test_report_common.py tests/server/test_attachment_html_issues.py -v
```

Expected: PASS。

---

## Chunk 3: 热力图与全景筛选

### Task 4: heatmap cell 输出分数组成和解释性 tooltip

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_heatmap_optimization.py`

- [ ] **Step 4.1: 写失败测试：mixed 以 0.5 权重计入体验健康度**

在 `tests/server/test_heatmap_optimization.py` 增加测试：

```python
cell = _build_heatmap_cell([
    {"sentiment": "positive", "rating": 5, "body_cn": "好"},
    {"sentiment": "mixed", "rating": 5, "body_cn": "有小问题但还行"},
    {"sentiment": "negative", "rating": 1, "body_cn": "差"},
])
assert cell["positive_count"] == 1
assert cell["mixed_count"] == 1
assert cell["negative_count"] == 1
assert cell["score"] == pytest.approx(0.5)
assert "混合 1" in cell["tooltip"]
```

- [ ] **Step 4.2: 写失败测试：红/黄/绿代表评论按解释目标选择**

构造红色 cell，断言 `top_review_excerpt` 来自负向评论；构造黄色 cell，优先 mixed。

- [ ] **Step 4.3: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/server/test_heatmap_optimization.py -v
```

Expected: 新测试失败。

- [ ] **Step 4.4: 修改 `_build_heatmap_cell()`**

在 `report_analytics.py`：
- 统计 `positive_count/mixed_count/negative_count/neutral_count`。
- 分数改为 `(positive + 0.5 * mixed) / sample_size`。
- `tooltip` 输出分数组成。
- 代表评论按颜色选择。

- [ ] **Step 4.5: 运行测试**

Run:

```bash
uv run pytest tests/server/test_heatmap_optimization.py -v
```

Expected: PASS。

---

### Task 5: heatmap 点击使用完整产品名下钻

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`
- Test: `tests/server/test_heatmap_optimization.py`

- [ ] **Step 5.1: 写失败测试：HTML cell 的 `data-product` 是完整产品名**

在 `tests/server/test_heatmap_optimization.py` 的渲染测试中构造产品：

```python
product_name = "Walton's Quick Patty Maker"
display_label = "Walton's Quick Patty"
```

断言：

```python
assert 'data-product="Walton&#39;s Quick Patty Maker"' in html or ...
assert "Walton's Quick Patty" in html
```

- [ ] **Step 5.2: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/server/test_heatmap_optimization.py -v
```

Expected: 当前模板使用 `y_label`，新测试失败。

- [ ] **Step 5.3: 增强 heatmap 数据结构**

在 `_build_heatmap_data()` 产物中增加：

```python
"y_items": [
    {"product_name": full_name, "display_label": short_label}
]
```

保留 `y_labels` 兼容旧测试。

- [ ] **Step 5.4: 修改模板**

在 `daily_report_v3.html.j2`：
- 循环 y 轴时使用 `y_item.display_label` 展示。
- `data-product` 使用 `y_item.product_name`。
- `title` 使用 cell `tooltip`。

- [ ] **Step 5.5: JS 保持完整值筛选**

在 `daily_report_v3.js`：
- 保持 `productSelect.value = product`。
- 若 value 不存在，不要静默误筛；可退回只筛 label，但应清空 product select。

- [ ] **Step 5.6: 运行测试**

Run:

```bash
uv run pytest tests/server/test_heatmap_optimization.py -v
```

Expected: PASS。

---

### Task 6: 全景近 30 天筛选使用 `date_published_parsed`

**Files:**
- Modify: `qbu_crawler/server/report_html.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 6.1: 写失败测试：parsed 日期命中近 30 天**

在 `tests/test_v3_html.py` 增加 `_annotate_reviews()` 测试：

```python
reviews = [{
    "date_published": "2 weeks ago",
    "date_published_parsed": "2026-04-20",
    "analysis_labels": "[]",
}]
_annotate_reviews(reviews, "2026-04-28")
assert reviews[0]["is_recent"] is True
```

- [ ] **Step 6.2: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/test_v3_html.py -v
```

Expected: 新测试失败。

- [ ] **Step 6.3: 修改 `_annotate_reviews()`**

在 `report_html.py`：

```python
raw_date = r.get("date_published_parsed") or r.get("date_published")
```

只对 ISO 日期尝试 `date.fromisoformat()`；无法解析则 `is_recent=False`。

- [ ] **Step 6.4: 运行测试**

Run:

```bash
uv run pytest tests/test_v3_html.py -v
```

Expected: PASS。

---

## Chunk 4: Excel、KPI 与 delivery 状态

### Task 7: 竞品短板保留中文字段并让 Excel 优先中文

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_competitor_insights_v12.py`
- Test: `tests/server/test_excel_sheets.py`

- [ ] **Step 7.1: 写失败测试：`negative_opportunities` 保留中文字段**

在 `tests/server/test_competitor_insights_v12.py` 增加测试，构造 competitor review：

```python
review = {
    "ownership": "competitor",
    "headline": "Bad delivery",
    "body": "Package was late",
    "headline_cn": "配送差",
    "body_cn": "包裹延迟",
}
```

断言输出 item 有 `headline_cn/body_cn`。

- [ ] **Step 7.2: 写失败测试：Excel 竞品启示短板用中文**

在 `tests/server/test_excel_sheets.py` 构造 analytics，生成 workbook 后断言“竞品启示”行包含中文，不包含英文正文。

- [ ] **Step 7.3: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/server/test_competitor_insights_v12.py tests/server/test_excel_sheets.py -v
```

Expected: 新测试失败。

- [ ] **Step 7.4: 修改 `_negative_opportunities()`**

在 `report_analytics.py` 输出中增加：

```python
"headline_cn": review.get("headline_cn"),
"body_cn": review.get("body_cn"),
```

- [ ] **Step 7.5: 确认 Excel 已优先中文**

`report.py::_theme_example()` 已优先 `body_cn/headline_cn`，如测试仍失败，检查 plan 中构造的 analytics 字段是否进入 Excel。

- [ ] **Step 7.6: 运行测试**

Run:

```bash
uv run pytest tests/server/test_competitor_insights_v12.py tests/server/test_excel_sheets.py -v
```

Expected: PASS。

---

### Task 8: 统一高风险产品和需关注产品口径

**Files:**
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`
- Optional modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/test_report_common.py`
- Test: `tests/server/test_email_full_template.py`

- [ ] **Step 8.1: 写失败测试：normalized kpis 输出 `attention_product_count`**

在 `tests/test_report_common.py` 构造 risk products：

```python
"risk_products": [
    {"status_lamp": "red", "risk_score": 40},
    {"status_lamp": "yellow", "risk_score": 30},
    {"status_lamp": "green", "risk_score": 0},
]
```

断言：

```python
assert result["kpis"]["high_risk_count"] == 1
assert result["kpis"]["attention_product_count"] == 2
```

- [ ] **Step 8.2: 写失败测试：邮件使用 `attention_product_count`**

在 `tests/server/test_email_full_template.py` 渲染邮件，断言“需关注产品 2 个”来自 kpis，不由模板独立遍历算出不同值。

- [ ] **Step 8.3: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/test_report_common.py tests/server/test_email_full_template.py -v
```

Expected: 新测试失败。

- [ ] **Step 8.4: 修改 normalize kpis**

在 `report_common.py`：

```python
normalized["kpis"]["attention_product_count"] = sum(
    1 for p in normalized.get("self", {}).get("risk_products", [])
    if p.get("status_lamp") in ("yellow", "red")
)
```

同时在 `report_user_contract.kpi_semantics` 写入阈值说明。

- [ ] **Step 8.5: 修改邮件模板**

在 `email_full.html.j2` 中优先：

```jinja2
{% set _attention_count = _kpis.get("attention_product_count", 0) %}
```

不要在模板中重新遍历产品算不同口径。

- [ ] **Step 8.6: 运行测试**

Run:

```bash
uv run pytest tests/test_report_common.py tests/server/test_email_full_template.py -v
```

Expected: PASS。

---

### Task 9: completed run 也能被 deadletter 降级

**Files:**
- Modify: `qbu_crawler/server/notifier.py`
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/server/test_internal_ops_alert.py`
- Test: `tests/server/test_workflow_ops_alert_wiring.py`

- [ ] **Step 9.1: 写失败测试：completed/full_sent run 有 deadletter 时可降级**

在 `tests/server/test_workflow_ops_alert_wiring.py` 增加测试：
- 构造 `workflow_runs.status='completed'`、`report_phase='full_sent'`。
- 构造对应 `notification_outbox.status='deadletter'`。
- 调用 `WorkflowWorker.process_once()`。
- 断言 run `report_phase='full_sent_local'`。

- [ ] **Step 9.2: 运行测试，确认失败**

Run:

```bash
uv run pytest tests/server/test_workflow_ops_alert_wiring.py tests/server/test_internal_ops_alert.py -v
```

Expected: 新测试失败，因为当前 worker 只扫描 active statuses。

- [ ] **Step 9.3: 新增 delivery reconcile helper**

在 `notifier.py` 或 `workflows.py` 中实现最小 helper：

```python
def reconcile_full_sent_deadletters(conn, *, limit: int = 50) -> int:
    ...
```

逻辑：
- 找 `workflow_runs.report_phase='full_sent'` 的最近 run。
- 调用 `downgrade_report_phase_on_deadletter(conn, run_id)`。
- 返回降级数量。

- [ ] **Step 9.4: 在 `WorkflowWorker.process_once()` 调用**

在处理 active runs 前或后调用 reconcile helper。注意：
- 失败只记录 exception，不阻断 workflow。
- 限制扫描数量。

- [ ] **Step 9.5: 运行测试**

Run:

```bash
uv run pytest tests/server/test_workflow_ops_alert_wiring.py tests/server/test_internal_ops_alert.py -v
```

Expected: PASS。

---

## Chunk 5: 集成回归

### Task 10: P0 集成测试集合

**Files:**
- No production file unless failures require scoped fixes.
- Test: all files touched above.

- [ ] **Step 10.1: 运行 P0 定向测试集**

Run:

```bash
uv run pytest ^
  tests/server/test_llm_assert_consistency.py ^
  tests/server/test_fallback_priorities.py ^
  tests/test_report_common.py ^
  tests/server/test_attachment_html_issues.py ^
  tests/server/test_heatmap_optimization.py ^
  tests/test_v3_html.py ^
  tests/server/test_competitor_insights_v12.py ^
  tests/server/test_excel_sheets.py ^
  tests/server/test_email_full_template.py ^
  tests/server/test_workflow_ops_alert_wiring.py ^
  tests/server/test_internal_ops_alert.py ^
  -v
```

Expected: PASS。

- [ ] **Step 10.2: 运行核心报告回归**

Run:

```bash
uv run pytest tests/test_v3_excel.py tests/test_v3_html.py tests/test_report_snapshot.py tests/test_report_common.py -v
```

Expected: PASS。

- [ ] **Step 10.3: 检查模板中旧字段风险**

Run:

```bash
rg -n "get\\(\"action\"\\)|\\.action\\b|data-product=\"\\{\\{ y_label|date_published\\)" qbu_crawler/server/report_templates qbu_crawler/server/report_common.py qbu_crawler/server/report_html.py
```

Expected:
- 不应再用 `action` 作为唯一 AI 建议字段。
- heatmap 不应再用截断 `y_label` 做 `data-product`。
- `_annotate_reviews()` 不应只读原始 `date_published`。

- [ ] **Step 10.4: 手动打开测试7 HTML 复核**

如果已有本地产物可重放，打开：

```text
C:\Users\leo\Desktop\生产测试\报告\测试7\reports\workflow-run-1-full-report.html
```

注意：这一步只能验证旧产物现状。修复后需要用同一份 snapshot/analytics 重新渲染 HTML 才能验证新行为。

- [ ] **Step 10.5: 记录开发日志**

新增 devlog：

```text
docs/devlogs/D021-test7-report-p0-contract-remediation.md
```

内容包括：
- P0 修复范围。
- LLM 校验契约变化。
- fallback 证据化策略。
- heatmap mixed 计分变化。
- delivery deadletter reconcile 策略。

---

## Execution Notes

- 当前工作树已有大量未提交修改；执行前必须先确认哪些改动属于用户已有工作，不要回滚。
- 每个 task 独立提交更安全，但只有在用户要求 commit 时再提交。
- 如果某个测试文件已有相似测试，优先扩展现有测试，不新增重复测试文件。
- 如果实现 `report_user_contract` 时发现需要大范围改模板，先停在兼容字段同步，不要把 P0 扩成 P1。
- 如果 heatmap mixed 权重导致大量旧测试失败，应更新测试说明为“体验健康度”而非“正向率”，不要简单退回旧规则。

---

## Ready Criteria

执行前确认：

- [ ] 用户确认本计划只执行 P0。
- [ ] 用户确认可以修改上述生产文件和测试文件。
- [ ] 执行者已阅读设计文档和审计文档。
- [ ] 执行者准备按 TDD 顺序推进，不先改实现。

执行完成后必须提供：

- 变更摘要。
- 运行过的测试命令和结果。
- 未解决的 P1/P2 后续项。
