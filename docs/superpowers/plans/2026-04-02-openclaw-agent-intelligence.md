# OpenClaw Agent Intelligence Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the OpenClaw agent (豆沙) intent understanding, execution reliability, prompt quality, and output quality without breaking existing functionality — by eliminating cross-layer drift and adding targeted workspace enhancements.

**Architecture:** Three-phase approach: Phase 0 fixes the foundation (contract.py ↔ index.js ↔ workspace alignment), Phase 1 adds high-impact workspace rules (~83 lines), Phase 2 adds moderate-impact refinements (~24 lines). All changes are additive or surgical replacements; no existing behavior is removed.

**Tech Stack:** Python (contract.py), JavaScript (index.js plugin), Markdown (workspace files). Existing test suite: pytest (Python), node test runner (JS plugin).

---

## File Map

### Phase 0 — Foundation (eliminate cross-layer drift)

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `qbu_crawler/server/mcp/contract.py:100-358` | Add 11 missing tool contracts with `does_not_support` |
| Modify | `qbu_crawler/server/openclaw/plugin/index.js:800` | Fix canonical wording in `summarizeProductDetail` |
| Modify | `qbu_crawler/server/openclaw/plugin/index.js:779` | Fix canonical wording in `summarizeProductList` |
| Modify | `qbu_crawler/server/openclaw/plugin/index.js:824` | Align review display budget from 5→3 |
| Modify | `qbu_crawler/server/openclaw/plugin/index.js:9-20` | Extend `CONTRACT_TOOL_ORDER` to all 20 tools |
| Modify | `qbu_crawler/server/openclaw/bridge/app.py:47` | Fix canonical wording in fast_report template |
| Regenerate | `qbu_crawler/server/openclaw/plugin/generated/tool_contract.json` | Re-export from contract.py |
| Modify | `tests/test_tool_contract.py` | Extend to cover all 20 tools |
| Modify | `qbu_crawler/server/openclaw/plugin/index.test.mjs` | Add summarizer wording assertions |

### Phase 1 — High-impact workspace changes

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md` (prepend before line 1) | Pre-Response Checklist |
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md:94` (after Decision Flow step 6) | Data Freshness Gate |
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md:245` (after SOP step 6) | Pre-flight Validation |
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md:246` (after Pre-flight) | Error Recovery |
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md:196` (after Unsupported-nearby) | Routing Examples: correction/amendment/conditional |
| Modify | `qbu_crawler/server/openclaw/workspace/TOOLS.md:109` (after Canonical Metric Wording) | User→Canonical metric mapping table |
| Modify | `qbu_crawler/server/openclaw/workspace/TOOLS.md:462` (after Unsupported template) | Empty Result guidance |
| Modify | `tests/test_tool_contract.py` | Assert workspace docs contain new sections |

### Phase 2 — Moderate-impact workspace changes

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md` (after Routing) | Time Expression Defaults table |
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md` (after Output Rules) | Proactive Signals with thresholds |
| Modify | `qbu_crawler/server/openclaw/workspace/AGENTS.md` (end of Output Rules) | Tone Calibration |

---

## Phase 0: Eliminate Cross-Layer Drift

### Task 1: Expand contract.py to cover all 20 live tools

**Files:**
- Modify: `qbu_crawler/server/mcp/contract.py:100-358`
- Test: `tests/test_tool_contract.py`

- [ ] **Step 1: Write the failing test — all 20 tools must exist in contract**

Add to `tests/test_tool_contract.py`:

```python
def test_all_live_tools_exist_in_contract():
    """Every tool registered in the MCP server must have a contract entry."""
    expected_tools = {
        # inspect
        "get_stats", "list_products", "get_product_detail", "query_reviews",
        "get_price_history", "get_task_status", "list_tasks",
        "get_workflow_status", "list_workflow_runs", "list_pending_notifications",
        "get_translate_status", "execute_sql",
        # produce
        "start_scrape", "start_collect", "cancel_task",
        "preview_scope", "send_filtered_report", "export_review_images",
        "generate_report", "trigger_translate",
    }
    assert expected_tools == set(TOOL_CONTRACTS.keys())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py::test_all_live_tools_exist_in_contract -v`
Expected: FAIL — 11 tools missing from TOOL_CONTRACTS

- [ ] **Step 3: Write the failing test — produce tools must have does_not_support**

```python
def test_produce_tools_have_does_not_support():
    """All produce-tier tools must declare what they cannot do."""
    produce_tiers = {"produce_action", "produce_preview"}
    for name, contract in TOOL_CONTRACTS.items():
        if contract["tier"] in produce_tiers:
            assert contract["does_not_support"], (
                f"{name} is produce-tier but has empty does_not_support"
            )
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py::test_produce_tools_have_does_not_support -v`
Expected: FAIL — existing `preview_scope` has no `does_not_support`, and 11 new produce tools don't exist yet

- [ ] **Step 5a: Add `does_not_support` to existing `preview_scope` contract**

In `contract.py`, find the `preview_scope` entry (line ~228-256) and add after the `supports` line:

```python
        does_not_support=["artifact generation", "email delivery", "data mutation"],
```

- [ ] **Step 5b: Add 11 missing tool contracts to contract.py**

Insert after the existing `"list_pending_notifications"` entry (before the closing `}` of `TOOL_CONTRACTS`). Each tool uses the `_tool()` helper that already exists. The exact contracts:

```python
    # --- Task lifecycle tools ---
    "start_scrape": _tool(
        name="start_scrape",
        tier="produce_action",
        description="Submit one or more product URLs for scraping.",
        input_schema={
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}},
                "ownership": {"type": "string"},
                "review_limit": {"type": "integer"},
                "reply_to": {"type": "string"},
            },
            "required": ["urls", "ownership"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string"},
                "total": {"type": "integer"},
            },
            "additionalProperties": True,
        },
        time_axes=["task_lifecycle_time"],
        supports=["product page scraping for supported sites"],
        does_not_support=["category page collection", "CSV maintenance", "unsupported site URLs"],
    ),
    "start_collect": _tool(
        name="start_collect",
        tier="produce_action",
        description="Collect product URLs from a category page, then scrape each product.",
        input_schema={
            "type": "object",
            "properties": {
                "category_url": {"type": "string"},
                "ownership": {"type": "string"},
                "max_pages": {"type": "integer"},
                "review_limit": {"type": "integer"},
                "reply_to": {"type": "string"},
            },
            "required": ["category_url", "ownership"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
        time_axes=["task_lifecycle_time"],
        supports=["category page product discovery and scraping"],
        does_not_support=["direct product URL scraping", "non-category URLs"],
    ),
    "get_task_status": _tool(
        name="get_task_status",
        tier="inspect_status",
        description="Query a crawler task's real-time status and progress.",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string"},
                "progress": {"type": "object"},
            },
            "additionalProperties": True,
        },
        time_axes=["task_lifecycle_time"],
        supports=["single task status inspection"],
    ),
    "list_tasks": _tool(
        name="list_tasks",
        tier="inspect_list",
        description="List crawler task records, optionally filtered by status.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "tasks": {"type": "array"},
                "total": {"type": "integer"},
            },
            "required": ["tasks", "total"],
            "additionalProperties": False,
        },
        time_axes=["task_lifecycle_time"],
        supports=["task list browsing and status filtering"],
    ),
    "cancel_task": _tool(
        name="cancel_task",
        tier="produce_action",
        description="Cancel a running or pending crawler task.",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
        time_axes=["task_lifecycle_time"],
        supports=["cancellation of running or pending tasks"],
        does_not_support=["cancellation of completed or failed tasks"],
    ),
    "get_price_history": _tool(
        name="get_price_history",
        tier="inspect_detail",
        description="Get price, stock, rating, and review-count history from snapshots.",
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "days": {"type": "integer"},
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "days": {"type": "integer"},
                "data_points": {"type": "integer"},
                "history": {"type": "array"},
            },
            "additionalProperties": True,
        },
        metrics=["avg_price_current", "avg_rating_current"],
        time_axes=["snapshot_time"],
        supports=["single-product price and stock trend inspection"],
        does_not_support=["multi-product comparison", "review content history"],
    ),
    "execute_sql": _tool(
        name="execute_sql",
        tier="inspect_exact",
        description="Execute a read-only SQL query against the collected database.",
        input_schema={
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "columns": {"type": "array"},
                "rows": {"type": "array"},
                "row_count": {"type": "integer"},
            },
            "additionalProperties": True,
        },
        supports=["read-only SELECT queries", "custom aggregation and cross-dimensional analysis"],
        does_not_support=["write operations", "DDL", "queries exceeding 500 rows or 5 seconds"],
    ),
    "generate_report": _tool(
        name="generate_report",
        tier="produce_action",
        description="Generate a legacy report for data added after a timestamp.",
        input_schema={
            "type": "object",
            "properties": {
                "since": {"type": "string"},
                "send_email": {"type": "string"},
            },
            "required": ["since"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "products_count": {"type": "integer"},
                "reviews_count": {"type": "integer"},
                "email_status": {"type": "string"},
            },
            "additionalProperties": True,
        },
        time_axes=["review_ingest_time"],
        supports=["legacy full-scope report generation"],
        does_not_support=["filtered scope reporting", "review-image export"],
    ),
    "trigger_translate": _tool(
        name="trigger_translate",
        tier="produce_action",
        description="Wake the translation worker immediately.",
        input_schema={
            "type": "object",
            "properties": {"reset_skipped": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "pending": {"type": "integer"},
                "failed": {"type": "integer"},
            },
            "additionalProperties": True,
        },
        supports=["immediate translation worker trigger"],
        does_not_support=["selective per-review translation", "translation model selection"],
    ),
    "get_translate_status": _tool(
        name="get_translate_status",
        tier="inspect_status",
        description="Query translation backlog and completion counts.",
        input_schema={
            "type": "object",
            "properties": {"since": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "translated": {"type": "integer"},
                "pending": {"type": "integer"},
                "failed": {"type": "integer"},
            },
            "additionalProperties": True,
        },
        time_axes=["review_ingest_time"],
        supports=["translation progress inspection"],
    ),
    "list_workflow_runs": _tool(
        name="list_workflow_runs",
        tier="inspect_list",
        description="List workflow runs, optionally filtered by status.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "total": {"type": "integer"},
            },
            "required": ["items", "total"],
            "additionalProperties": False,
        },
        time_axes=["task_lifecycle_time"],
        supports=["workflow run list browsing and status filtering"],
    ),
```

- [ ] **Step 6: Run tests to verify they pass (excluding artifact consistency)**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py -v -k "not test_export_tool_contract_artifact_matches_checked_in_json"`
Expected: ALL PASS. The artifact consistency test is expected to fail until Task 2 regenerates the JSON.

- [ ] **Step 7: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/mcp/contract.py tests/test_tool_contract.py
git commit -m "feat(contract): expand tool contracts to all 20 live MCP tools"
```

---

### Task 2: Regenerate tool_contract.json artifact

**Files:**
- Regenerate: `qbu_crawler/server/openclaw/plugin/generated/tool_contract.json`
- Test: `tests/test_tool_contract.py::test_export_tool_contract_artifact_matches_checked_in_json`

- [ ] **Step 1: Regenerate the JSON artifact from contract.py**

Run:
```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run python -c "
from qbu_crawler.server.mcp.contract import export_tool_contract_artifact
export_tool_contract_artifact('qbu_crawler/server/openclaw/plugin/generated/tool_contract.json')
print('done')
"
```
Expected: `done`

- [ ] **Step 2: Run the existing artifact-consistency test**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py::test_export_tool_contract_artifact_matches_checked_in_json -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/plugin/generated/tool_contract.json
git commit -m "chore: regenerate tool_contract.json with all 20 tool contracts"
```

---

### Task 3: Fix plugin summarizer canonical wording drift and update CONTRACT_TOOL_ORDER

**Files:**
- Modify: `qbu_crawler/server/openclaw/plugin/index.js:9-20,779,800,824`
- Test: `qbu_crawler/server/openclaw/plugin/index.test.mjs`

- [ ] **Step 1: Add failing tests for canonical wording**

The existing test file uses plain named functions (not `test()` from `node:test`), invoked directly at the bottom. `normalizeMcpToolResult` is already imported at line 12. Add new test functions before the invocation block, and add their calls to the invocation block at the bottom.

Add functions before the existing invocation block (before `testExtractSpeakerContextFromMessageEvent();`):

```javascript
function testSummarizeProductDetailUsesCanonicalLabel() {
  var result = normalizeMcpToolResult("get_product_detail", {
    structuredContent: {
      name: "Test Product", sku: "TP-001", site: "basspro",
      ownership: "own", price: 29.99, rating: 4.5, review_count: 42,
    },
  });
  var text = result.content[0].text;
  assert.ok(text.includes("站点展示评论总数"), "must use canonical label, got: " + text);
  assert.ok(!text.includes("**评论数**"), "must not use generic 评论数 label");
}

function testSummarizeReviewListRespectsDisplayBudgetOf3() {
  var items = [];
  for (var i = 0; i < 10; i++) {
    items.push({ product_name: "Product " + i, rating: 3, author: "Author " + i });
  }
  var result = normalizeMcpToolResult("query_reviews", {
    structuredContent: { items: items, total: 10 },
  });
  var text = result.content[0].text;
  var sampleMatches = text.match(/^\d+\.\s/gm) || [];
  assert.ok(sampleMatches.length <= 3, "review samples must be <= 3, got " + sampleMatches.length);
}
```

Add invocations at the bottom (before `console.log("plugin tests passed");`):

```javascript
testSummarizeProductDetailUsesCanonicalLabel();
testSummarizeReviewListRespectsDisplayBudgetOf3();
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/openclaw/plugin && node index.test.mjs`
Expected: AssertionError — "must use canonical label" and "review samples must be <= 3, got 5"

- [ ] **Step 3: Fix index.js — three summarizer edits**

Edit 1 — `summarizeProductDetail()` line 800:
```javascript
// old:  "- **评论数**：" + (data.review_count ?? 0),
// new:
    "- **站点展示评论总数**：" + (data.review_count ?? 0),
```

Edit 2 — `summarizeProductList()` line 779:
```javascript
// old:  " · 评论 " + (item.review_count ?? 0) + " 条"
// new:
      " · 站点评论 " + (item.review_count ?? 0) + " 条"
```

Edit 3 — `summarizeReviewList()` line 824:
```javascript
// old:  var shown = items.slice(0, 5);
// new:
  var shown = items.slice(0, 3);
```

- [ ] **Step 4: Update CONTRACT_TOOL_ORDER to include all 20 tools**

In `index.js` lines 9-20, replace the existing `CONTRACT_TOOL_ORDER` array with:

```javascript
var CONTRACT_TOOL_ORDER = [
  "get_stats",
  "list_products",
  "get_product_detail",
  "query_reviews",
  "get_price_history",
  "get_task_status",
  "list_tasks",
  "get_workflow_status",
  "list_workflow_runs",
  "list_pending_notifications",
  "get_translate_status",
  "execute_sql",
  "start_scrape",
  "start_collect",
  "cancel_task",
  "preview_scope",
  "send_filtered_report",
  "export_review_images",
  "generate_report",
  "trigger_translate",
];
```

This ensures `CONTRACT_TOOL_NAMES` (line 8, derived from `CONTRACT_TOOL_ORDER`) matches the 20 keys in the regenerated `tool_contract.json`, so the existing `testHighValueToolNamesComeFromSharedContractArtifact` test continues to pass.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/openclaw/plugin && node index.test.mjs`
Expected: `plugin tests passed`

- [ ] **Step 6: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/plugin/index.js qbu_crawler/server/openclaw/plugin/index.test.mjs
git commit -m "fix(plugin): align summarizer with canonical wording, display budget, and full contract order"
```

---

### Task 4: Fix bridge template canonical wording

**Files:**
- Modify: `qbu_crawler/server/openclaw/bridge/app.py:47`

- [ ] **Step 1: Fix the fast_report template**

In `bridge/app.py` line 47, the `workflow_fast_report` template uses generic `评论数`:

```python
# old:  "- **评论数**：{reviews_count}\n"
# new:
        "- **已入库评论数**：{reviews_count}\n"
```

- [ ] **Step 2: Verify no other generic 评论数 in bridge templates**

Search bridge/app.py for bare `评论数` (without prefix like `已入库` or `站点展示`). The `task_completed` template uses `新增评论` which is acceptable context-specific wording. Only line 47 needs fixing.

- [ ] **Step 3: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/bridge/app.py
git commit -m "fix(bridge): use canonical 已入库评论数 in fast_report template"
```

---

## Phase 1: High-Impact Workspace Changes

### Task 5: Add Pre-Response Checklist to AGENTS.md

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md` (prepend before line 1)

- [ ] **Step 1: Prepend checklist as the very first section**

Prepend to the top of AGENTS.md, before the existing line 1 (`# Qbu OpenClaw Workspace`):

```markdown
## Pre-Response Checklist

每轮回复前过一遍（不需对外展示）：

1. start_scrape / start_collect 场景是否已确认 ownership？
2. 回复中的"评论数"是 `ingested_review_rows` 还是 `site_reported_review_total_current`？
3. 是否把 pending / running 状态说成了"已完成"/"已发送"？
4. 最终回复是否追加了 JSON、SQL 或重复摘要？
5. 称呼是否跟随当前发言人？

---

```

- [ ] **Step 2: Verify AGENTS.md still passes existing integrity test**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py::test_runtime_workspace_docs_stay_repo_local_free_and_role_separated -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/workspace/AGENTS.md
git commit -m "feat(workspace): add pre-response checklist to AGENTS.md"
```

---

### Task 6: Add Data Freshness Gate to AGENTS.md

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md` (after Decision Flow step 6, before `### Ad-hoc Task Requests`)

- [ ] **Step 1: Insert after the Decision Flow numbered list**

After the line `6. 不要把复合 ask 压成单一步骤` and before `### Ad-hoc Task Requests`, insert:

```markdown

### Data Freshness Gate

任何涉及 `needs_judgment=yes` 的分析请求，在执行前先检查 `get_stats()` 返回的 `last_scrape_at`：

- 距今 < 24h：正常分析
- 距今 24h-72h：回复中加一句"注意：数据最后更新于 {time}，分析基于该时间点"
- 距今 > 72h：明确警告"数据已超过 3 天未更新，分析可能不准确。建议先触发抓取。"

仅对 `product_state_time` 和 `review_ingest_time` 相关分析触发。对 `review_publish_time` 的历史分析不触发。

```

- [ ] **Step 2: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/workspace/AGENTS.md
git commit -m "feat(workspace): add data freshness gate before analysis"
```

---

### Task 7: Add Pre-flight Validation and Error Recovery to AGENTS.md

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md` (after Ad-hoc Task SOP step 6, before the email follow-ups block)

- [ ] **Step 1: Insert Pre-flight and Error Recovery after SOP step 6**

After the line `6. 如果工具失败，只能说"提交失败"，不能说"处理中"` and before `For ad-hoc email follow-ups after scraping:`, insert:

```markdown

### Pre-flight Validation

调用 `start_scrape` 或 `start_collect` 前：

- URL 域名必须在支持列表中（`www.basspro.com`、`www.meatyourmaker.com`、`www.waltons.com`、`waltons.com`）
- 域名不匹配时立即告知不支持该站点，不要替用户猜测 URL

### Error Recovery

#### 查找类（not found）
- `get_product_detail` 未找到 → 尝试 `list_products(search=关键词)` 模糊匹配
- 模糊命中唯一产品 → 使用它；命中多个 → 列出让用户选
- 模糊也找不到 → 告知"未找到"并提示是否需要先抓取

#### 超时类（timeout / query failed）
- `execute_sql` 超时 → 简化查询或改用基础工具
- 不连续重试同一个 SQL

#### 提交类（submission error）
- 不静默吞掉错误
- 简化后告知用户，不暴露原始错误消息
- 建议检查 URL 是否属于支持站点

```

- [ ] **Step 2: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/workspace/AGENTS.md
git commit -m "feat(workspace): add pre-flight validation and error recovery to AGENTS.md"
```

---

### Task 8: Add Routing Examples for correction/amendment/conditional patterns

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md` (after `### Other common routes` section, before `## Ad-hoc Task SOP`)

- [ ] **Step 1: Insert new routing examples**

After the last "Other common routes" entry (the one about "看 daily 是否正常") and before `## Ad-hoc Task SOP`, insert:

```markdown

### Correction pattern

"不对，我要看的是竞品的"

- 修正上一轮 scope 参数（如 ownership → competitor）
- 其他条件继承上一轮
- 不重走完整路由流程

### Amendment pattern

"还有呢 / 继续"

- 上一轮有 truncated 结果时，用 offset 翻页
- 保持完全相同的筛选条件

### Conditional pattern

"如果差评超过 10 条就发邮件"

- decision vector: needs_data_read=yes, needs_confirmation=yes, needs_artifact=conditional
- 先查 total → 判断条件 → 满足则进入 preview_scope → 确认 → produce
- 不满足则直接告知数量，不进入 produce 流程

```

- [ ] **Step 2: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/workspace/AGENTS.md
git commit -m "feat(workspace): add correction/amendment/conditional routing examples"
```

---

### Task 9: Add Metric Mapping and Empty Result guidance to TOOLS.md

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md:109` (after Canonical Metric Wording)
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md:462` (after Unsupported Produce template)

- [ ] **Step 1: Insert User→Canonical mapping after Canonical Metric Wording**

After the line `- preview_scope.counts.products 只是兼容旧展示的别名...` (line ~109) and before `### Canonical Time Wording`, insert:

```markdown

### User Phrasing → Canonical Mapping

- "评论数 / 多少条评论 / 评论有多少" → `ingested_review_rows`（默认口径）
- "页面上写的评论数 / 站点显示的" → `site_reported_review_total_current`（需显式标注）
- "有多少产品 / 产品数" → `product_count`
- "带图的 / 有图评论" → `image_review_rows`
- "差评 / 低分 / 吐槽" → 不是单独 metric，是 `max_rating=2` 的筛选条件
- "好评率" → 需 `execute_sql` 计算，基础工具不直接提供
- 歧义时默认走 `ingested_review_rows`

```

- [ ] **Step 2: Insert Empty Result guidance after Unsupported Produce template**

After the Unsupported Produce Request template closing ` ``` ` (around line 462) and before `### Rating Distribution`, insert:

```markdown

### Empty Result

当查询返回 0 条结果时：

- 说明查询条件（"按 SKU=XXX 查询"）
- 给出可能原因（1-2 条，不超过 2 句）
- 给出建议（放宽条件 / 确认拼写 / 先抓取）
- 保持 2-3 句，不展开成完整模板填充

```

- [ ] **Step 3: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/workspace/TOOLS.md
git commit -m "feat(workspace): add metric mapping and empty result guidance to TOOLS.md"
```

---

### Task 10: Run full test suite to verify Phase 0+1 didn't break anything

**Files:**
- Test: `tests/test_tool_contract.py` (full)
- Test: `qbu_crawler/server/openclaw/plugin/index.test.mjs`

- [ ] **Step 1: Run Python test suite**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py tests/test_metric_semantics.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run plugin test suite**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/openclaw/plugin && node --test index.test.mjs`
Expected: ALL PASS

- [ ] **Step 3: Verify workspace doc integrity**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py::test_runtime_workspace_docs_stay_repo_local_free_and_role_separated -v`
Expected: PASS

---

## Phase 2: Moderate-Impact Workspace Changes

### Task 11: Add Time Expression Defaults, Proactive Signals, and Tone Calibration

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`

- [ ] **Step 1: Insert Time Expression Defaults after the Data Freshness Gate section**

After the Data Freshness Gate section (added in Task 6) and before `### Ad-hoc Task Requests`, insert:

```markdown

### Time Expression Defaults

- "最近抓的 / 最近入库的" → `review_ingest_time`，默认 7 天
- "最近的评论 / 最近的差评" → `review_publish_time`，默认 30 天
- "最近更新 / 数据新不新" → `product_state_time`，当前态
- 无法判断 → 追问，不默认

```

- [ ] **Step 2: Insert Proactive Signals after Output Rules section**

After the `## Output Rules` section (before `## Runtime Stability Guardrail`), insert:

```markdown

### Proactive Signals

完成用户主体问题后，以下条件命中时追加一句提醒（仅一句）：

- 产品评分 < 3.0 且已入库评论 > 10 条
- workflow 存在 `needs_attention` 状态
- 查询的产品全部缺货（stock_status=OutOfStock）

不触发：用户已在问相关问题时不重复；精确 inspect 不追加分析。

### Tone Calibration

- 日常查询：一句话解决，数字加粗
- 分析判断：先结论后证据，"集中在""主要是"而非"严重""紧急"
- 证据不足："样本量还不大，目前更像初步信号"
- 不该出现：大段重复用户原话、不必要的铺垫、情感渲染

```

- [ ] **Step 3: Run workspace integrity test**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_tool_contract.py::test_runtime_workspace_docs_stay_repo_local_free_and_role_separated -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd E:/Project/ForcomeAiTools/Qbu-Crawler
git add qbu_crawler/server/openclaw/workspace/AGENTS.md
git commit -m "feat(workspace): add time defaults, proactive signals, and tone calibration"
```

---

### Task 12: Final validation — full suite

- [ ] **Step 1: Run all Python tests**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/ -v --ignore=.venv`
Expected: ALL PASS

- [ ] **Step 2: Run plugin tests**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/openclaw/plugin && node --test index.test.mjs`
Expected: ALL PASS

- [ ] **Step 3: Verify workspace file sizes stayed reasonable**

Run: `wc -l qbu_crawler/server/openclaw/workspace/AGENTS.md qbu_crawler/server/openclaw/workspace/TOOLS.md`
Expected: AGENTS.md ~420 lines (was 308), TOOLS.md ~555 lines (was 532). Total growth ~135 lines (~520 tokens, <3% of prompt budget).

---

## Summary of Changes by File

| File | Phase | Net Change |
|------|-------|------------|
| `contract.py` | 0 | +~230 lines (11 tool contracts) |
| `plugin/generated/tool_contract.json` | 0 | Regenerated |
| `index.js` | 0 | 3 surgical line edits |
| `bridge/app.py` | 0 | 1 line edit |
| `AGENTS.md` | 1+2 | +~107 lines (checklist, freshness, pre-flight, error recovery, routing examples, time defaults, proactive signals, tone) |
| `TOOLS.md` | 1 | +~23 lines (metric mapping, empty result) |
| `test_tool_contract.py` | 0 | +~20 lines (2 new tests) |
| `index.test.mjs` | 0 | +~20 lines (2 new tests) |
