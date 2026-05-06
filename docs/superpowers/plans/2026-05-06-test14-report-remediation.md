# Test14 Report Remediation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:test-driven-development and superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复测试14暴露的日报口径、采集质量、趋势漏数、quiet 风险跳变和 artifact 审计问题。

**Architecture:** 保持现有 report_snapshot/report_common/report_html/report.py 分层，只在现有入口收口语义。用户可见展示区分本期与累计；采集质量使用 task product_summaries 的 extracted/text_total；quiet/change 与 full 共用标签同步与 artifact 登记。

**Tech Stack:** Python 3.10、pytest、SQLite、Jinja2、openpyxl。

---

## Chunk 1: 回归测试

### Task 1: 锁定测试14关键行为

**Files:**
- Create: `tests/server/test_test14_report_regressions.py`

- [ ] **Step 1: Write failing tests**

覆盖：
- 邮件副标题不能把累计评论写成“本期”。
- V3 总览里本期入库评论不能标成“基线样本评论”。
- `_parse_date_published()` 支持 minute/hour 相对时间。
- `summarize_scrape_quality()` 以 extracted/text_total 计算完整率，不用 saved 当完整率。
- `save_product()` 在本次未提供有效 `ratings_only_count` 时保留历史值。
- quiet 路径构建 analytics 时同步 LLM `analysis_labels`。
- quiet/change 生成的 analytics/html artifact 会登记。

- [ ] **Step 2: Run tests to verify failures**

Run: `uv run pytest tests/server/test_test14_report_regressions.py -q`
Expected: FAIL on current implementation.

## Chunk 2: 最小实现

### Task 2: 修复展示与日期

**Files:**
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/models.py`
- Modify: `qbu_crawler/server/report.py`

- [ ] **Step 1:** 邮件副标题改为“累计 ... / 本期新增 ...”。
- [ ] **Step 2:** V3 总览卡改为“本期入库评论”。
- [ ] **Step 3:** 日期解析支持 minute/hour，并在趋势查询里对不可解析相对时间 fallback 到 `date_published_parsed` 入库结果。

### Task 3: 修复采集质量和 ratings-only

**Files:**
- Modify: `qbu_crawler/server/scrape_quality.py`
- Modify: `qbu_crawler/models.py`

- [ ] **Step 1:** 从 task `product_summaries` 读取 `extracted_review_count` 作为采集完整率分子。
- [ ] **Step 2:** `saved_review_count` 只作为新增入库统计，不驱动低覆盖告警。
- [ ] **Step 3:** `save_product()` 对既有产品只在本次显式提供非空 `ratings_only_count` 时覆盖。

### Task 4: 修复 quiet/change 路径

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`

- [ ] **Step 1:** quiet/change 的累计 analytics 构建前同步 cumulative reviews 标签并传入 `synced_labels`。
- [ ] **Step 2:** quiet/change 写出的 analytics/html 调用 `_record_artifact_safe()`。

## Chunk 3: 验证

### Task 5: Targeted verification

Run:
- `uv run pytest tests/server/test_test14_report_regressions.py -q`
- `uv run pytest tests/server/test_historical_report_paths.py tests/server/test_historical_trend_queries.py tests/server/test_email_full_template.py tests/server/test_scrape_quality_zero_scrape.py -q`

Expected: all selected tests pass.
