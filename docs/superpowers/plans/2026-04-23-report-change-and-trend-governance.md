# 报表“今日变化”与“变化趋势”治理 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不新增周报/月报产物的前提下，统一日报报表语义，落地 `今日变化` 与 `变化趋势`，并修复已确认的数据口径问题。

**Architecture:** 以现有报表主链路为骨架，先在 `report_snapshot.py` / `report_analytics.py` / `report_common.py` 建立 `report_semantics`、`change_digest`、`trend_digest`、artifact resolver 与顶层 `kpis` 单一展示源，再让 HTML、邮件、Excel 与 LLM 全部改为只消费这些归一化字段。Phase 1 先完成语义治理、路径可迁移和状态分层，交付“功能不砍”的统一契约和基础趋势页；Phase 2 再在不改变契约的前提下深化 `变化趋势` 的图表、表格和阅读层级。

**Tech Stack:** Python 3.10+, pytest, SQLite, Jinja2, Chart.js, openpyxl

**Spec:** `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md`

**Path Baseline:** 真实生产报告目录以 `C:\Users\User\Desktop\QBU\reports` 为准；`C:\Users\leo\Desktop\pachong` 仅作为本地拷贝参考。实现必须保证 previous context 在绝对路径、相对路径和生产拷贝路径下都可解析。

---

## File Map

| File | Responsibility | Tasks |
|------|---------------|-------|
| `qbu_crawler/server/report.py` | report 查询层、Excel 导出、趋势数据 sheet | T1, T7, T10 |
| `qbu_crawler/server/report_snapshot.py` | full report 主链路、`change_digest`、previous context 挂接、artifact resolver | T3, T7 |
| `qbu_crawler/server/report_analytics.py` | 统一语义字段、`trend_digest`、趋势聚合、状态分层 | T2, T3, T5, T9 |
| `qbu_crawler/server/report_common.py` | normalize、顶层 `kpis` 透传、mode-safe 文案 | T2, T4, T6 |
| `qbu_crawler/server/report_html.py` | HTML 渲染入参与模板上下文对齐 | T6, T10 |
| `qbu_crawler/server/report_charts.py` | Chart.js 配置生成，承接趋势图表 | T5, T6, T9, T10 |
| `qbu_crawler/server/report_llm.py` | 报表 LLM prompt、语义安全、fallback | T4 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | HTML tab 结构、KPI 卡与趋势页模块渲染 | T6, T10 |
| `qbu_crawler/server/report_templates/daily_report_v3.js` | 顶层 tab 与趋势页二级切换交互 | T6, T10 |
| `qbu_crawler/server/report_templates/daily_report_v3.css` | 新增 tab、趋势 KPI、图表与表格布局 | T6, T10 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | 邮件摘要统一消费 `change_digest` 与顶层 `kpis` | T7 |
| `tests/test_report.py` | report 查询层与 Excel 导出回归 | T1, T7, T10 |
| `tests/test_report_snapshot.py` | `change_digest` 与 run mode 行为回归 | T3, T7 |
| `tests/test_report_analytics.py` | 语义字段、KPI、趋势聚合回归 | T2, T3, T5, T9 |
| `tests/test_report_common.py` | normalize、mode-safe 文案、KPI 透传回归 | T2, T4, T6 |
| `tests/test_report_llm.py` | LLM prompt、bootstrap fallback、安全词回归 | T4 |
| `tests/test_v3_llm.py` | 报表 V3 LLM 集成语义回归 | T4 |
| `tests/test_v3_html.py` | HTML 顶层 tab、趋势切换、KPI 展示回归 | T6, T10 |
| `tests/test_v3_excel.py` | Excel `今日变化` / `趋势数据` / “本次新增”列回归 | T7, T10 |
| `tests/test_report_integration.py` | 跨载体 KPI 一致性、warning / 空态、digest 集成回归 | T2, T5, T6, T7, T9, T10 |
| `tests/test_metric_semantics.py` | `window.reviews_count`、`fresh_review_count` 等语义回归 | T8, T11 |
| `tests/test_v3_modes.py` | bootstrap / incremental 展示模式回归 | T8, T11 |
| `docs/devlogs/` | 实施记录与语义治理沉淀 | T8, T11 |
| `AGENTS.md` | 报表语义、时间口径、统一 digest 规则同步 | T8, T11 |

---

## Delivery Phases

### Phase 1：语义治理与止血

交付目标：

- 顶层统一语义字段落地
- 顶层 `kpis` 成为唯一展示 KPI 源
- `今日变化` 正式可用，且 `bootstrap` 下展示监控起点态
- `变化趋势` 基础入口可用，且按 `ready | accumulating | degraded` 分层
- artifact resolver 可用，生产拷贝场景下 previous context 不失效
- 邮件 / HTML / Excel / LLM 的当前口径问题被修复

暂停点：

- 如果 Phase 1 完成后暂停，系统已经可以稳定输出不漂移的单报表
- Phase 2 的所有增强都必须建立在 Phase 1 的统一契约之上

### Phase 2：趋势深化与阅读增强

交付目标：

- `trend_digest` 扩展图表、辅图和表格
- 四个趋势维度的数据层级更完整
- HTML / Excel 趋势页阅读体验增强

---

## Chunk 1: Phase 1 语义治理与止血

### Task 1: 补齐 report 查询层 review 字段，给 digest 和趋势计算提供稳定原始数据

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: 写失败测试，锁定 review 查询字段**

在 `tests/test_report.py` 新增针对 `query_report_data()` / `query_cumulative_data()` 的断言，要求 review 结果至少包含：

```python
required = {
    "id", "product_name", "product_sku", "product_url",
    "author", "headline", "body", "rating",
    "date_published", "date_published_parsed", "images",
    "ownership", "headline_cn", "body_cn", "translate_status",
    "scraped_at", "site",
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report.py -v -k "query_report_data or query_cumulative_data"`
Expected: FAIL，提示缺少 `scraped_at`、`site` 或 `product_url`

- [ ] **Step 3: 修改 report 查询 SQL，补齐字段**

在 `qbu_crawler/server/report.py` 中统一窗口查询和累计查询的 review SELECT，确保至少补齐：

```sql
SELECT
  r.id AS id,
  p.name AS product_name,
  p.sku AS product_sku,
  p.url AS product_url,
  p.site AS site,
  r.scraped_at AS scraped_at,
  ...
```

- [ ] **Step 4: 回归 JSON / images 兼容**

确认新增字段不会破坏现有 `images` 的解析逻辑，也不会影响旧测试依赖的 review 结构。

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_report.py -v -k "query_report_data or query_cumulative_data"`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/report.py tests/test_report.py
git commit -m "修复 报表查询补齐 review 原始字段"
```

---

### Task 2: 固化顶层语义字段，并把顶层 `kpis` 设为唯一展示 KPI 源

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_report_common.py`
- Test: `tests/test_report_integration.py`

- [ ] **Step 1: 写失败测试，锁定顶层语义字段**

在 `tests/test_report_analytics.py` / `tests/test_report_common.py` 新增断言：

```python
assert normalized["report_semantics"] in {"bootstrap", "incremental"}
assert normalized["is_bootstrap"] is (normalized["report_semantics"] == "bootstrap")
assert "change_digest" in normalized
assert "trend_digest" in normalized
assert "kpis" in normalized
```

- [ ] **Step 2: 写失败测试，锁定 KPI 单一展示源**

在 `tests/test_report_integration.py` 构造冲突数据：

```python
analytics = {
    "kpis": {"ingested_review_rows": 12},
    "cumulative_kpis": {"ingested_review_rows": 999},
}
```

断言 HTML / 邮件 / Excel 摘要最终只能展示 `12`，不能展示 `999`。

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_common.py tests/test_report_integration.py -v -k "report_semantics or trend_digest or kpi"`
Expected: FAIL，字段不存在或展示层仍读取错误来源

- [ ] **Step 4: 在 analytics 层引入 `report_semantics` / `is_bootstrap`**

在 `qbu_crawler/server/report_analytics.py` 中基于现有 mode 映射：

```python
report_semantics = "bootstrap" if mode_info["mode"] == "baseline" else "incremental"
is_bootstrap = report_semantics == "bootstrap"
```

并保留现有 mode 兼容字段。

- [ ] **Step 5: 在 normalize 层固化 `kpis` 与语义字段**

在 `qbu_crawler/server/report_common.py` 保证：

- 顶层透传 `report_semantics`
- 顶层透传 `is_bootstrap`
- 顶层透传 `change_digest`
- 顶层透传 `trend_digest`
- 顶层透传 `kpis`
- 不把 `cumulative_kpis` 当成展示字段暴露给模板

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_common.py tests/test_report_integration.py -v -k "report_semantics or trend_digest or kpi"`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_report_analytics.py tests/test_report_common.py tests/test_report_integration.py
git commit -m "新增 报表统一语义字段与 KPI 单一展示源"
```

---

### Task 3: 组装 `change_digest`，统一承接“今日变化”

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_report_snapshot.py`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_metric_semantics.py`

- [ ] **Step 1: 写失败测试，锁定 `change_digest.summary` 口径**

在 `tests/test_report_snapshot.py` 增加最小场景：

```python
assert digest["enabled"] is True
assert digest["summary"]["ingested_review_count"] == 6
assert digest["summary"]["fresh_review_count"] == 2
assert digest["summary"]["historical_backfill_count"] == 4
assert digest["summary"]["fresh_own_negative_count"] == 1
```

并增加 baseline 场景：

```python
assert digest["enabled"] is True
assert digest["view_state"] == "bootstrap"
assert digest["summary"]["ingested_review_count"] == 6
```

- [ ] **Step 2: 写失败测试，锁定语义边界**

在 `tests/test_metric_semantics.py` / `tests/test_report_snapshot.py` 断言：

- `window.reviews_count` 只表示本次入库数
- 展示文案只能从 `change_digest.summary.ingested_review_count` 取值
- `backfill_dominant` 阈值为 `>= 0.7`
- `incremental + 无显著变化` 时必须生成 `change_digest.empty_state`
- `warnings` 至少稳定保留 `translation_incomplete`、`estimated_dates`、`backfill_dominant`
- previous context 在旧绝对路径失效时，仍可从当前 `REPORT_DIR`、数据库同级 `reports/` 或同目录回退搜索中恢复
- 新写入的 artifact 路径不再继续固化为当前机器绝对路径

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_report_snapshot.py tests/test_report_analytics.py tests/test_metric_semantics.py -v -k "change_digest or fresh_review_count or backfill_dominant or previous_context"`
Expected: FAIL，`change_digest` 不存在、baseline 行为错误或 previous context 回退缺失

- [ ] **Step 4: 在 `report_snapshot.py` 中新增 digest builder**

在 `qbu_crawler/server/report_snapshot.py` 中新增 artifact resolver 与局部 digest builder，统一收口：

- `workflow_runs` 原始路径
- 当前 `REPORT_DIR`
- 数据库同级 `reports/`
- `workflow-run-{id}-*.json` 同目录兜底搜索
- 新产物写回 `workflow_runs` 时优先持久化为相对产物路径

- `window.new_reviews`
- `detect_snapshot_changes(...)`
- `compute_cluster_changes(...)`

必须计算的字段：

```python
fresh_review_count
historical_backfill_count
fresh_own_negative_count
issue_new_count
issue_escalated_count
issue_improving_count
state_change_count
```

- [ ] **Step 5: 统一 `issue_changes` / `product_changes` / `review_signals` / `warnings` / `empty_state` 结构**

在 digest 层归一化：

- `issue_changes` item 统一字段
- `product_changes` 至少保留 `sku/name/old/new`
- `review_signals` 只保留新近可行动评论，不暴露全量 review 列表
- `warnings` 显式保留三类键，不让展示层猜字段是否存在
- `empty_state` 用于“本期无显著变化”，不能和 `bootstrap` 复用
- `view_state` 仅允许 `bootstrap | active | empty`

- [ ] **Step 6: 把 `change_digest` 挂到 raw analytics 再透传到 normalized**

确保磁盘 JSON、HTML、邮件、Excel 都能消费同一份 `change_digest`。

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_report_snapshot.py tests/test_report_analytics.py tests/test_metric_semantics.py -v -k "change_digest or fresh_review_count or backfill_dominant or previous_context"`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py tests/test_report_snapshot.py tests/test_report_analytics.py tests/test_metric_semantics.py
git commit -m "新增 今日变化统一 digest 契约"
```

---

### Task 4: 加入 LLM 语义安全，避免 `bootstrap` 被写成“今日新增”

**Files:**
- Modify: `qbu_crawler/server/report_llm.py`
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/test_report_llm.py`
- Test: `tests/test_v3_llm.py`

- [ ] **Step 1: 写失败测试，锁定 prompt 必须感知 `report_semantics`**

在 `tests/test_report_llm.py` 新增断言：

```python
analytics = {"report_semantics": "bootstrap", "kpis": {}, "window": {"reviews_count": 20}}
prompt = _build_insights_prompt(analytics)
assert "bootstrap" in prompt or "基线" in prompt
assert "今日新增评论" not in prompt
```

再为 `incremental` 场景加对称断言：

```python
analytics = {"report_semantics": "incremental", "window": {"reviews_count": 20}}
prompt = _build_insights_prompt(analytics)
assert "今日变化" in prompt or "今日新增评论" in prompt
```

- [ ] **Step 2: 写失败测试，锁定 `bootstrap` fallback**

在 `tests/test_report_llm.py` / `tests/test_v3_llm.py` 模拟 LLM 返回：

```json
{"hero_headline": "今日新增 20 条评论", "executive_bullets": ["今日暴增"], ...}
```

断言 `generate_report_insights()` 在 `report_semantics = "bootstrap"` 下不会原样透出，而会回退到确定性基线话术。

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_report_llm.py tests/test_v3_llm.py -v -k "bootstrap or fallback or report_semantics"`
Expected: FAIL，prompt 未区分语义或 fallback 未触发

- [ ] **Step 4: 修改 `_build_insights_prompt()`，显式注入语义**

在 `qbu_crawler/server/report_llm.py` 中：

- 显式读取 `analytics["report_semantics"]`
- `bootstrap` 下写明“这是建档/基线期”
- `bootstrap` 下不要注入“今日新增评论”片段
- `incremental` 下才允许提示模型关注本期变化

- [ ] **Step 5: 加入 deterministic fallback / sanitize 规则**

在 `generate_report_insights()` 或独立校验函数中增加：

- `bootstrap` 下检测禁用措辞
- 命中时改用 deterministic fallback
- fallback 输出也必须走同一套基线话术

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_llm.py tests/test_v3_llm.py -v -k "bootstrap or fallback or report_semantics"`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_llm.py qbu_crawler/server/report_common.py tests/test_report_llm.py tests/test_v3_llm.py
git commit -m "修复 报表 LLM 的 bootstrap 语义与安全回退"
```

---

### Task 5: 构建 Phase 1 基础版 `trend_digest`，禁止把趋势计算塞进模板

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_common.py`
- Modify: `qbu_crawler/server/report_charts.py`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_report_common.py`
- Test: `tests/test_report_integration.py`

- [ ] **Step 1: 写失败测试，锁定基础版 `trend_digest` 结构**

在 `tests/test_report_analytics.py` 增加断言：

```python
trend = normalized["trend_digest"]
assert set(trend["views"]) == {"week", "month", "year"}
assert set(trend["dimensions"]) == {"sentiment", "issues", "products", "competition"}
assert trend["default_view"] == "month"
assert trend["default_dimension"] == "sentiment"
```

并断言每个维度在每个视角下至少包含：

- `kpis`
- `primary_chart`
- `table`
- `status`
- `status_message`

- [ ] **Step 2: 写失败测试，锁定时间口径**

在 `tests/test_report_integration.py` 构造评论发布时间与抓取时间冲突场景，断言：

- 舆情 / 问题趋势按 `date_published_parsed`
- 产品状态趋势按 `scraped_at`
- 无法形成状态趋势的组件返回 `accumulating` 或 `degraded`，而不是混用时间轴硬算
- 首日监控场景下：
  - `sentiment / issues` 维度可 `ready`
  - `products` 维度至少部分组件 `accumulating`
  - `competition` 维度允许混合状态
- `hours ago` 这类相对时间能被解析或被显式标记为 `estimated_dates`，不得静默污染 freshness / 趋势

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_common.py tests/test_report_integration.py -v -k "trend_digest or date_published_parsed or scraped_at or hours ago"`
Expected: FAIL，`trend_digest` 不存在或时间口径混用

- [ ] **Step 4: 在 analytics 层生成基础版趋势聚合**

在 `qbu_crawler/server/report_analytics.py` 中为 Phase 1 落地：

- `week / month / year`
- `sentiment / issues / products / competition`
- 每个维度最少一组稳定 KPI、主图数据和基础表数据
- 每个组件显式输出 `status = ready | accumulating | degraded`
- 样本不足时输出状态说明，而不是伪造空趋势

在 `qbu_crawler/server/report_common.py` 中补齐：

- `hours ago` 等小时级相对时间解析
- 解析失败时的显式降级标记，供 `estimated_dates` warning 消费

- [ ] **Step 5: 在 `report_charts.py` 生成基础趋势图配置**

为 `trend_digest` 生成基础 Chart.js 配置，避免 HTML 模板手拼主图数据。

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_common.py tests/test_report_integration.py -v -k "trend_digest or date_published_parsed or scraped_at or hours ago"`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_common.py qbu_crawler/server/report_charts.py tests/test_report_analytics.py tests/test_report_common.py tests/test_report_integration.py
git commit -m "新增 Phase 1 基础趋势 digest"
```

---

## Chunk 2: Phase 1 展示层与导出对齐

### Task 6: HTML 落地 `今日变化` 与基础版 `变化趋势`，并清理 KPI 错误消费

**Files:**
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report_charts.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`
- Test: `tests/test_v3_html.py`
- Test: `tests/test_report_common.py`
- Test: `tests/test_report_integration.py`

- [ ] **Step 1: 写失败测试，锁定顶层 tab 与 mode 行为**

在 `tests/test_v3_html.py` 增加：

```python
assert "今日变化" in html_for_baseline
assert "今日变化" in html_for_incremental
assert "变化趋势" in html_for_baseline
assert "变化趋势" in html_for_incremental
```

并断言：

- 顶层 tab 名称与顺序固定为 `总览 / 今日变化 / 变化趋势 / 问题诊断 / 产品排行 / 竞品对标 / 全景数据`
- `bootstrap` 下 `今日变化` 展示“监控起点”态而不是被隐藏
- `今日变化` 不再是 placeholder 空壳
- `变化趋势` 初始默认选中 `月 + 舆情趋势`

- [ ] **Step 2: 写失败测试，锁定 HTML 只能读顶层 `kpis`**

在 `tests/test_report_integration.py` 构造 `kpis` 与 `cumulative_kpis` 冲突值，断言 HTML KPI 卡读取的是顶层 `kpis`。

- [ ] **Step 3: 写失败测试，锁定 warning / 空态 / 文案卫生**

在 `tests/test_v3_html.py` / `tests/test_report_integration.py` 断言：

- `translation_incomplete`、`estimated_dates`、`backfill_dominant` 触发时能看到提示
- `incremental + 无显著变化` 时渲染显式空态，而不是空表格或空卡片
- `bootstrap` 下不出现“今日新增/较昨日/较上期”
- HTML 中不得出现 `None`、`null`、`[]`、`{}`
- `今日变化` 内不得混入“持续关注产品”“全量风险排行”“全量问题摘要”等全量模块
- 首日场景下 `变化趋势` 能同时看到 `ready` 与 `accumulating` 组件，不会被整体降成单一状态
- [ ] **Step 4: 运行测试确认失败**

Run: `uv run pytest tests/test_v3_html.py tests/test_report_common.py tests/test_report_integration.py -v -k "今日变化 or 变化趋势 or kpi"`
Expected: FAIL，tab 缺失、placeholder 未替换或 KPI 来源错误

- [ ] **Step 5: 渲染 `今日变化` 正式内容**

在 `daily_report_v3.html.j2` 中把 `今日变化` 固化为四段：

- 变化摘要
- 问题变化
- 产品状态变化
- 新近评论信号

模板只允许读取：

```jinja2
analytics.change_digest
analytics.kpis
```

并补齐：

- warning 提示区
- `bootstrap` 监控起点态渲染
- `empty_state` 渲染
- 空值保护，禁止把内部 `None` 类字符串直接打到页面

- [ ] **Step 6: 落基础版 `变化趋势`**

在 HTML / JS / charts 中新增：

- 一级切换：`周 | 月 | 年`
- 二级切换：`舆情趋势 | 问题趋势 | 产品趋势 | 竞品趋势`
- 每个维度最少渲染 1 组 KPI、1 张主图、1 张基础表
- 每个组件按 `ready | accumulating | degraded` 渲染
- 样本不足时展示说明，不伪造图表
- 初始默认视图固定为 `month + sentiment`

- [ ] **Step 7: 统一 CSS 与 print 展现**

确保新增结构不会压垮现有布局，print 模式下趋势内容全部展开，不丢失主图或表格。

- [ ] **Step 8: 跑测试确认通过**

Run: `uv run pytest tests/test_v3_html.py tests/test_report_common.py tests/test_report_integration.py -v -k "今日变化 or 变化趋势 or kpi"`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add qbu_crawler/server/report_html.py qbu_crawler/server/report_charts.py qbu_crawler/server/report_templates/daily_report_v3.html.j2 qbu_crawler/server/report_templates/daily_report_v3.js qbu_crawler/server/report_templates/daily_report_v3.css tests/test_v3_html.py tests/test_report_common.py tests/test_report_integration.py
git commit -m "新增 HTML 今日变化与基础趋势页"
```

---

### Task 7: 对齐邮件与 Excel，统一消费 `change_digest` 与顶层 `kpis`

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`
- Test: `tests/test_v3_excel.py`
- Test: `tests/test_report.py`
- Test: `tests/test_report_snapshot.py`
- Test: `tests/test_report_integration.py`

- [ ] **Step 1: 写失败测试，锁定邮件摘要来源**

在 `tests/test_report_integration.py` 断言邮件模板：

- 摘要区只读 `analytics.kpis`
- 变化摘要只读 `change_digest.summary`
- 问题变化只读 `change_digest.issue_changes`
- 产品变化只读 `change_digest.product_changes`
- warning 提示不直出 `None` / 空占位串

- [ ] **Step 2: 写失败测试，锁定 Excel 口径**

在 `tests/test_v3_excel.py` 增加断言：

- Excel `产品概览` 的“采集评论数”来自真实 review 聚合
- Excel 新增 `今日变化` sheet
- Excel `今日变化` sheet 在 `bootstrap` 下显示“监控起点”说明
- Excel “本次新增”列在 `bootstrap` 下显示 `新近 / 补采`
- Excel “本次新增”列在 `incremental` 下显示 `新增 / 空`
- Excel 中不得出现 `None` / `null`
- `impact_category_display` 在 `impact_category` 为空时能回退到 `failure_mode` 或标签摘要
- `headline_display` 在 `headline_cn` 为空时能回退到 `headline` 或正文摘要

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_v3_excel.py tests/test_report.py tests/test_report_snapshot.py tests/test_report_integration.py -v -k "今日变化 or 采集评论数 or 本次新增 or kpi"`
Expected: FAIL，邮件仍混读旧字段或 Excel 列语义不完整

- [ ] **Step 4: 改邮件模板**

在 `email_full.html.j2` 中清理 `_win`、`_changes` 等旧拼装路径，统一改为消费：

- `analytics.kpis`
- `analytics.change_digest.summary`
- `analytics.change_digest.issue_changes`
- `analytics.change_digest.product_changes`

- [ ] **Step 5: 改 Excel 导出逻辑**

在 `qbu_crawler/server/report.py` 中：

- 修正 `产品概览` “采集评论数”的来源
- 新增 `今日变化` sheet
- 保留 `趋势数据` sheet
- `今日变化` sheet 在 `bootstrap` 下输出监控起点摘要而不是空表
- 明确 `bootstrap / incremental` 两种 “本次新增” 列文案
- `今日变化` sheet 支持 warning / 空态说明，禁止输出空表占位串
- 统一输出 `impact_category_display` / `headline_display`，不把原始空值直接落到 Excel

- [ ] **Step 6: 回归 `window_review_ids` 与累计视图兼容**

确保累计评论视图仍能标记“本次入库”评论，不破坏既有明细导出行为。

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_v3_excel.py tests/test_report.py tests/test_report_snapshot.py tests/test_report_integration.py -v -k "今日变化 or 采集评论数 or 本次新增 or window_review_ids or kpi"`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add qbu_crawler/server/report.py qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_templates/email_full.html.j2 tests/test_v3_excel.py tests/test_report.py tests/test_report_snapshot.py tests/test_report_integration.py
git commit -m "对齐 邮件与 Excel 的变化摘要和 KPI 口径"
```

---

### Task 8: Phase 1 收尾回归与文档同步

**Files:**
- Modify: `tests/test_metric_semantics.py`
- Modify: `tests/test_v3_modes.py`
- Modify: `docs/devlogs/` 下新日志
- Modify: `AGENTS.md`

- [ ] **Step 1: 增加 mode 与语义回归测试**

在 `tests/test_metric_semantics.py` / `tests/test_v3_modes.py` 断言：

- `bootstrap` 下不出现“今日新增”
- `bootstrap` 下 `今日变化` 入口存在且为监控起点态
- `incremental` 下 `今日变化` 正常显示
- `backfill_dominant` 时提示正确
- `window.reviews_count` 不被展示层解释成业务新增
- `incremental + 无显著变化` 时走 `empty_state`
- 任一载体不出现 `None` / `null` / 内部空占位串
- 新写入的 artifact 路径策略与读取回退策略互相兼容，不会让后续 run 再次固化旧问题

- [ ] **Step 2: 跑 Phase 1 关键回归**

Run:

```bash
uv run pytest tests/test_report.py tests/test_report_snapshot.py tests/test_report_analytics.py tests/test_report_common.py tests/test_report_llm.py tests/test_v3_llm.py tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_integration.py tests/test_metric_semantics.py tests/test_v3_modes.py -v
```

Expected: PASS

- [ ] **Step 3: 同步开发日志**

新增 `docs/devlogs/` 文档，记录：

- Phase 1 为什么先做语义治理
- `report_semantics` / `change_digest` / `trend_digest` 边界
- 顶层 `kpis` 单一展示源规则
- `30 天 fresh` 与 `70% backfill_dominant` 阈值

- [ ] **Step 4: 同步 `AGENTS.md`**

把下面约束写入项目规范：

- `window.reviews_count` 只表示本次入库评论数
- 展示层 KPI 只允许读顶层 `kpis`
- 评论类趋势按 `date_published_parsed`
- 产品状态趋势按 `scraped_at`
- HTML / 邮件 / Excel 必须消费统一 digest

- [ ] **Step 5: 提交**

```bash
git add tests/test_metric_semantics.py tests/test_v3_modes.py docs/devlogs AGENTS.md
git commit -m "完善 Phase 1 报表语义治理回归与文档"
```

---

## Chunk 3: Phase 2 趋势深化与阅读增强

### Task 9: 深化 `trend_digest` 数据层，补齐四个维度的派生趋势

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/server/report_charts.py`
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_report_integration.py`

- [ ] **Step 1: 写失败测试，锁定扩展版 `trend_digest` 结构**

在 `tests/test_report_analytics.py` 增加断言：

- `views == {"week", "month", "year"}`
- `dimensions == {"sentiment", "issues", "products", "competition"}`
- 每个维度在每个视角下至少包含：
  - `kpis`
  - `primary_chart`
  - `secondary_charts`
  - `table`

- [ ] **Step 2: 写失败测试，锁定时间口径**

在 `tests/test_report_integration.py` 构造评论发布时间与抓取时间冲突场景，断言：

- 舆情 / 问题趋势按 `date_published_parsed`
- 产品状态趋势按 `scraped_at`

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_integration.py -v -k "trend_digest or date_published_parsed or scraped_at"`
Expected: FAIL，结构不完整或时间口径混用

- [ ] **Step 4: 扩展 `trend_digest` 聚合**

在 `qbu_crawler/server/report_analytics.py` 增强：

- `sentiment`：评论量、自有差评、自有差评率、健康指数
- `issues`：Top 问题簇热度、受影响 SKU、新增/升级/缓解问题
- `products`：重点 SKU 评分、价格、评论总数、库存状态
- `competition`：自有 vs 竞品评分、差评率/好评率、差距指数

- [ ] **Step 5: 扩展图表配置**

在 `qbu_crawler/server/report_charts.py` 中为上述结构生成主图和辅图配置，避免模板手拼复杂图表对象。

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py tests/test_report_integration.py -v -k "trend_digest or date_published_parsed or scraped_at"`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_charts.py tests/test_report_analytics.py tests/test_report_integration.py
git commit -m "增强 Phase 2 趋势 digest 与时间口径回归"
```

---

### Task 10: 增强 HTML / Excel 的 `变化趋势` 阅读体验

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report_charts.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.js`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.css`
- Test: `tests/test_v3_html.py`
- Test: `tests/test_v3_excel.py`
- Test: `tests/test_report_integration.py`

- [ ] **Step 1: 写失败测试，锁定趋势页扩展结构**

在 `tests/test_v3_html.py` / `tests/test_v3_excel.py` 断言：

- 每个维度都能看到扩展 KPI 区
- 趋势页存在主图 + 至少两张辅图
- Excel `趋势数据` sheet 输出对应扩展表格

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_integration.py -v -k "变化趋势 or secondary or 趋势数据"`
Expected: FAIL，扩展图表或表格不存在

- [ ] **Step 3: 扩展 HTML 模板与交互**

在 `daily_report_v3.html.j2` / `daily_report_v3.js` / `daily_report_v3.css` 中：

- 扩展趋势 KPI 区
- 渲染主图、辅图和表格
- 保持 `周 | 月 | 年` 与四个维度的切换逻辑不变

- [ ] **Step 4: 扩展 Excel 趋势数据导出**

在 `qbu_crawler/server/report.py` 中增强 `趋势数据` sheet，使其能导出 Phase 2 扩展表格与关键指标。

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_integration.py -v -k "变化趋势 or secondary or 趋势数据"`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/report.py qbu_crawler/server/report_html.py qbu_crawler/server/report_charts.py qbu_crawler/server/report_templates/daily_report_v3.html.j2 qbu_crawler/server/report_templates/daily_report_v3.js qbu_crawler/server/report_templates/daily_report_v3.css tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_integration.py
git commit -m "增强 Phase 2 趋势页图表与导出"
```

---

### Task 11: Phase 2 收尾回归与文档同步

**Files:**
- Modify: `tests/test_metric_semantics.py`
- Modify: `tests/test_v3_modes.py`
- Modify: `docs/devlogs/` 下新日志
- Modify: `AGENTS.md`

- [ ] **Step 1: 增加 Phase 2 趋势回归**

在 `tests/test_metric_semantics.py` / `tests/test_v3_modes.py` 增加断言：

- Phase 2 没有引入新的 KPI 来源
- 趋势增强后仍沿用同一 `trend_digest`
- 年视角样本不足时仍给说明而不是伪造数据
- `ready | accumulating | degraded` 状态分层在 Phase 2 后仍保持一致

- [ ] **Step 2: 跑 Phase 2 全量回归**

Run:

```bash
uv run pytest tests/test_report.py tests/test_report_snapshot.py tests/test_report_analytics.py tests/test_report_common.py tests/test_report_llm.py tests/test_v3_llm.py tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_integration.py tests/test_metric_semantics.py tests/test_v3_modes.py -v
```

Expected: PASS

- [ ] **Step 3: 同步开发日志与 `AGENTS.md`**

补充 Phase 2 内容：

- 趋势维度扩展范围
- 环比 / 同比 / 期初期末表达规则
- Phase 2 不得绕开统一契约的约束

- [ ] **Step 4: 提交**

```bash
git add tests/test_metric_semantics.py tests/test_v3_modes.py docs/devlogs AGENTS.md
git commit -m "完善 Phase 2 趋势增强回归与文档"
```

---

## 实施顺序

严格按下面顺序执行：

1. Phase 1
2. T1 查询字段补齐
3. T2 顶层语义字段与 KPI 单一展示源
4. T3 `change_digest` + artifact resolver
5. T4 LLM 语义安全
6. T5 基础 `trend_digest`
7. T6 HTML `今日变化` 与基础趋势页
8. T7 邮件与 Excel 对齐
9. T8 Phase 1 回归与文档
10. Phase 2
11. T9 扩展 `trend_digest`
12. T10 增强 HTML / Excel 趋势阅读体验
13. T11 Phase 2 回归与文档

---

## 风险提示

- 最大风险不是页面结构，而是旧字段继续被展示层直接消费
- `kpis` 单一展示源如果不落测试，很容易在邮件或 Excel 再次漂移
- `bootstrap` 的 LLM 安全如果只改 prompt、不加 deterministic fallback，仍然会被模型措辞击穿
- `变化趋势` 的最大风险不是图表样式，而是把 `date_published_parsed` 和 `scraped_at` 混用
- production 拷贝场景下如果没有 artifact resolver，`previous context` 会直接失效
- “功能不砍”最大的实现风险不是页面太多，而是用隐藏 tab 规避数据未就绪问题
- 如果只做读取侧 resolver、不治理写入侧路径，新 run 会继续把绝对路径问题写回数据库
- 如果不把 `impact_category` / `headline_cn` 的回退链写成测试，真实生产空值仍会在导出时漏出来
- 如果不锁 `hours ago` 和首日混合就绪态，趋势实现很容易在首轮上线时被时间轴混用击穿
- Phase 2 的最大风险是为追求丰富度重新在模板里重算趋势，破坏 Phase 1 已建立的契约

---

## 完成定义

以下条件全部满足，才算本计划完成：

- Phase 1 完成后，系统已具备可上线的统一报表语义，不再出现已确认的当前口径问题
- 顶层 `kpis` 成为邮件 / HTML / Excel 唯一展示 KPI 源
- `bootstrap` 下不再出现“今日新增”类措辞，且 LLM 有 deterministic fallback
- HTML 新增 `今日变化` 与 `变化趋势`，并符合“入口常驻、状态分层”的边界
- `今日变化` 的 warning / empty_state 边界闭合，且不混入全量模块
- `bootstrap` 下 `今日变化` 为监控起点态，不隐藏 tab，不伪造增量
- Excel 修复 `产品概览` “采集评论数”及 “本次新增” 双态列语义
- previous context 在真实生产路径、相对路径和本地拷贝路径下都能恢复
- 新 run 写入的 artifact 路径不再继续固化单机绝对路径
- 任一载体不再出现 `None` / `null` / 内部空占位串
- `impact_category_display` / `headline_display` 回退链对真实空值样本有效
- `hours ago` 与相对时间解析失败场景都有明确回归和降级说明
- 首日监控场景下，趋势页允许并正确展示混合就绪态
- Phase 2 完成后，趋势页在不改变契约的前提下完成深化
- 对应测试全部通过，文档同步完成

---

Plan complete and saved to `docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md`. Ready to execute?
