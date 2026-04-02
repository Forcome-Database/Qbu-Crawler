# OpenClaw Capability Layering Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a layered `inspect / analyze / produce` capability model that stops unbounded tool loops, preserves current daily/report behavior, and enables generalized scope-based preview and artifact actions.

**Architecture:** Keep existing primitive MCP tools as the generalized inspect base. Move capability boundaries and fail-fast rules into the OpenClaw workspace contract, add a server-owned scope normalization layer, and introduce a small set of dedicated produce tools starting with `preview_scope`, then `send_filtered_report`, then `export_review_images`. Reuse the current report pipeline and email contract instead of creating parallel delivery behavior.

**Tech Stack:** Python (FastMCP, SQLite, openpyxl), JavaScript plugin summarization, Markdown workspace rules, pytest, node-based plugin tests

---

## File Structure

**Create:**
- `qbu_crawler/server/scope.py` — server-owned scope normalization, threshold logic, and preview decision helpers
- `tests/test_scope.py` — scope normalization and preview threshold tests
- `tests/test_filtered_reports.py` — filtered report generation and contract-preservation tests
- `docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md` — prompt/regression acceptance set for high-frequency asks
- `docs/devlogs/D010-openclaw-capability-layering.md` — implementation log and rollout notes

**Modify:**
- `qbu_crawler/models.py` — reusable preview counts, filtered review-image lookup, scope-aware query helpers
- `qbu_crawler/server/mcp/tools.py` — add `preview_scope`, `send_filtered_report`, `export_review_images`
- `qbu_crawler/server/report.py` — add filtered report generation by scope while preserving legacy email contract
- `qbu_crawler/server/openclaw/plugin/index.js` — summarize new tool results cleanly
- `qbu_crawler/server/openclaw/plugin/index.test.mjs` — plugin summary regression cases for new tools
- `qbu_crawler/server/openclaw/workspace/AGENTS.md` — canonical routing ownership and fail-fast produce rules
- `qbu_crawler/server/openclaw/workspace/TOOLS.md` — capability boundaries and new response templates
- `qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md` — analysis playbook tightened around `inspect / analyze / produce`
- `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-report/SKILL.md` — keep narrow and aligned with new output contract
- `qbu_crawler/server/openclaw/workspace/skills/csv-management/SKILL.md` — keep deterministic, clarify non-goals
- `tests/test_mcp_tools.py` — MCP tool result-shape tests for new produce tools
- `tests/test_report.py` — preserve legacy report subject/body contract

**Do not modify in this plan:**
- daily workflow orchestration in `qbu_crawler/server/workflows.py`
- OpenClaw bridge behavior in `qbu_crawler/server/openclaw/bridge/app.py`
- current legacy report email template wording unless explicitly required by tests/spec

---

## Chunk 1: Routing, Capability Boundaries, and Fail-Fast

### Task 1: Make `AGENTS.md` the canonical routing owner

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Reference: `docs/superpowers/specs/2026-03-31-openclaw-capability-layering-design.md`

- [ ] **Step 1: Write the routing table to match the approved spec**

Add explicit rules for:
- `inspect` requests using primitive tools
- `analyze` requests routing into `skills/qbu-product-data/SKILL.md`
- `produce` requests requiring dedicated action tools

- [ ] **Step 2: Add fail-fast behavior for unsupported `produce` asks**

Required behavior:
- if no dedicated produce path exists, say so immediately
- offer the nearest supported substitute
- forbid repeated primitive-tool exploration after the capability boundary is known

- [ ] **Step 3: Add `preview_scope` routing rules**

Document exactly when `preview_scope` is:
- optional for narrow scope
- required for broad or ambiguous scope
- not to be re-run repeatedly

- [ ] **Step 4: Manual review against the spec**

Check:
- no duplicated routing logic that belongs in `TOOLS.md`
- `AGENTS.md` owns classification and routing only

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/workspace/AGENTS.md
git commit -m "docs: define capability routing ownership"
```

### Task 2: Make `TOOLS.md` the output-contract owner

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md`

- [ ] **Step 1: Add capability boundary section**

Must distinguish:
- what is currently supported
- what is not yet supported
- how unsupported `produce` requests should be phrased

- [ ] **Step 2: Add templates for new generalized responses**

Required templates:
- scope preview
- filtered report preview
- report delivery confirmation
- unsupported artifact request

- [ ] **Step 3: Keep routing content out of `TOOLS.md`**

Remove or avoid any logic that duplicates `AGENTS.md` routing ownership.

- [ ] **Step 4: Manual check against current messy-output regressions**

Verify that the templates explicitly forbid:
- raw JSON
- row fragments
- post-answer tool leakage

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/workspace/TOOLS.md
git commit -m "docs: add capability boundary and produce templates"
```

### Task 3: Tighten analysis playbook without reducing generality

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/daily-scrape-report/SKILL.md`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/csv-management/SKILL.md`

- [ ] **Step 1: Update `qbu-product-data` to assume routing is already decided**

Strengthen:
- overview
- comparison
- trend
- anomaly
- root-cause

Do not add many scenario-specific branches.

- [ ] **Step 2: Keep `daily-scrape-report` narrow**

Document that it explains workflow/report outcomes, not arbitrary product analysis.

- [ ] **Step 3: Keep `csv-management` deterministic**

Clarify that it manages CSV input rules only and is not an analysis path.

- [ ] **Step 4: Manual acceptance check**

Use these asks conceptually:
- "看下库里有哪些产品"
- "帮我分析最近差评"
- "给我导出某个产品图片"

Expected:
- only the second goes to analysis skill
- the third is blocked unless a supported produce path exists

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md qbu_crawler/server/openclaw/workspace/skills/daily-scrape-report/SKILL.md qbu_crawler/server/openclaw/workspace/skills/csv-management/SKILL.md
git commit -m "docs: harden analysis and produce skill boundaries"
```

### Task 4: Add a concrete prompt regression harness

**Files:**
- Create: `docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md`
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md`

- [ ] **Step 1: Create the acceptance file with seed asks**

Seed cases must include:
- "看下库里有哪些产品"
- "看最近抓了什么"
- "帮我分析最近差评"
- "给我导出某个产品的评论图片"
- "把指定 SKU 在某时间范围内的差评报告发邮件"

- [ ] **Step 2: Define expected behavior for each ask**

Each case must record:
- expected intent classification
- expected tool path
- forbidden behavior
- expected final answer shape

- [ ] **Step 3: Reference this harness from workspace docs**

Add one short reference in `AGENTS.md` or `TOOLS.md` so future edits know this acceptance set exists and must remain valid.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md qbu_crawler/server/openclaw/workspace/AGENTS.md qbu_crawler/server/openclaw/workspace/TOOLS.md
git commit -m "docs: add openclaw capability regression harness"
```

---

## Chunk 2: Server-Owned Scope Normalization and `preview_scope`

### Task 4: Add a focused scope module

**Files:**
- Create: `qbu_crawler/server/scope.py`
- Test: `tests/test_scope.py`

- [ ] **Step 1: Write the failing tests for scope normalization**

```python
def test_normalize_scope_maps_simple_filters():
    scope = normalize_scope(
        products={"skus": ["SKU-1"], "ownership": ["own"]},
        reviews={"sentiment": "negative"},
        window={"since": "2026-03-01", "until": "2026-03-31"},
    )
    assert scope.products.skus == ["SKU-1"]
    assert scope.products.ownership == ["own"]
    assert scope.reviews.max_rating == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_scope.py::test_normalize_scope_maps_simple_filters -v
```

Expected: fail because `scope.py` and normalization helpers do not exist yet.

- [ ] **Step 3: Implement minimal normalization and preview-threshold helpers**

Implement:
- `normalize_scope(...)`
- `needs_preview(...)`
- `preview_hint(...)`

Required outputs:
- normalized filter object
- hard thresholds from the spec
- `safe_to_continue | requires_confirmation | unsupported`

- [ ] **Step 4: Add boundary tests**

Cover:
- explicit single-product scope does not require preview
- multi-site or long-window produce scope requires preview
- unsupported artifact type returns `unsupported`

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/test_scope.py -v
```

Expected: all scope tests pass.

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/scope.py tests/test_scope.py
git commit -m "feat: add server-owned scope normalization"
```

### Task 5: Add reusable preview queries in the data layer

**Files:**
- Modify: `qbu_crawler/models.py`
- Test: `tests/test_scope.py`

- [ ] **Step 1: Write failing tests for preview counts**

Add tests for:
- matched product count
- matched review count
- matched image-review count

- [ ] **Step 2: Implement reusable preview helpers**

Implement minimal helpers in `models.py`, for example:
- `preview_scope_counts(scope)`
- `list_review_images_for_scope(scope, limit)`

These helpers must reuse existing database semantics and not fork filtering logic per tool.

- [ ] **Step 3: Run tests**

Run:

```bash
uv run pytest tests/test_scope.py -k preview -v
```

Expected: preview-count tests pass.

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/models.py tests/test_scope.py
git commit -m "feat: add preview and image lookup helpers"
```

### Task 6: Expose `preview_scope` through MCP and plugin summaries

**Files:**
- Modify: `qbu_crawler/server/mcp/tools.py`
- Modify: `qbu_crawler/server/openclaw/plugin/index.js`
- Modify: `qbu_crawler/server/openclaw/plugin/index.test.mjs`
- Modify: `tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing MCP tool test**

```python
def test_preview_scope_returns_counts_and_next_action_hint():
    result = preview_scope(
        products={"ownership": ["competitor"]},
        window={"since": "2026-03-01", "until": "2026-03-31"},
    )
    assert result["counts"]["products"] >= 0
    assert result["next_action_hint"] in {"safe_to_continue", "requires_confirmation", "unsupported"}
```

- [ ] **Step 2: Run the failing MCP test**

Run:

```bash
uv run pytest tests/test_mcp_tools.py -k preview_scope -v
```

Expected: fail because the tool does not exist yet.

- [ ] **Step 3: Implement `preview_scope` in `tools.py`**

Requirements:
- accept normalized scope-like inputs
- return structured content
- include counts and `next_action_hint`
- not send email or generate files

- [ ] **Step 4: Add plugin summary support**

Update `index.js` to summarize `preview_scope` into:
- matched product count
- matched review count
- image-review count if relevant
- whether continuation is safe, needs confirmation, or unsupported

- [ ] **Step 5: Run Python and plugin tests**

Run:

```bash
uv run pytest tests/test_mcp_tools.py -k preview_scope -v
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add qbu_crawler/server/mcp/tools.py qbu_crawler/server/openclaw/plugin/index.js qbu_crawler/server/openclaw/plugin/index.test.mjs tests/test_mcp_tools.py
git commit -m "feat: add preview_scope produce gate"
```

---

## Chunk 3: Generalized Produce Actions

### Task 7: Add filtered report generation without changing the current email contract

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/test_report.py`
- Test: `tests/test_filtered_reports.py`

- [ ] **Step 1: Write failing contract-preservation tests**

Required tests:
- filtered report reuses current report subject/body style unless explicitly overridden
- attachment generation still follows the current Excel path expectations

Example:

```python
def test_send_filtered_report_reuses_legacy_email_contract():
    result = send_filtered_report(
        scope={"products": {"skus": ["SKU-1"]}},
        delivery={"format": "email", "recipients": ["a@example.com"]},
    )
    assert result["email"]["subject"].startswith("【网评监控】")
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/test_report.py tests/test_filtered_reports.py -k filtered -v
```

Expected: fail because the filtered-report path does not exist yet.

- [ ] **Step 3: Implement filtered-query report path in `report.py`**

Requirements:
- query products/reviews by normalized scope
- reuse existing Excel generation
- preserve legacy subject/body style by default
- return a structured result with separate:
  - data match counts
  - artifact generation status
  - email delivery status

- [ ] **Step 4: Run report tests**

Run:

```bash
uv run pytest tests/test_report.py tests/test_filtered_reports.py -v
```

Expected: filtered and legacy report tests both pass.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report.py tests/test_report.py tests/test_filtered_reports.py
git commit -m "feat: add filtered report generation with legacy contract"
```

### Task 8: Expose `send_filtered_report` through MCP and fail-fast routing

**Files:**
- Modify: `qbu_crawler/server/mcp/tools.py`
- Modify: `qbu_crawler/server/openclaw/plugin/index.js`
- Modify: `tests/test_mcp_tools.py`
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md`

- [ ] **Step 1: Write failing MCP tests**

Test expectations:
- successful structured result for supported filtered report requests
- explicit unsupported result for unsupported artifact requests

- [ ] **Step 2: Implement `send_filtered_report` MCP tool**

Requirements:
- call the new filtered report path
- preserve structured return shape
- never claim success when email delivery fails

- [ ] **Step 3: Update plugin summaries and prompt contracts**

`AGENTS.md` and `TOOLS.md` must now:
- prefer `preview_scope` first for broad produce requests
- use `send_filtered_report` only for supported report requests
- fail fast for unsupported artifact asks

- [ ] **Step 4: Run MCP tests**

Run:

```bash
uv run pytest tests/test_mcp_tools.py -k filtered_report -v
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

Expected: tool and plugin tests pass.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/mcp/tools.py qbu_crawler/server/openclaw/plugin/index.js tests/test_mcp_tools.py qbu_crawler/server/openclaw/workspace/AGENTS.md qbu_crawler/server/openclaw/workspace/TOOLS.md
git commit -m "feat: expose filtered report produce action"
```

### Task 9: Add review-image export as a links-only produce path

**Files:**
- Modify: `qbu_crawler/server/mcp/tools.py`
- Modify: `qbu_crawler/server/openclaw/plugin/index.js`
- Modify: `tests/test_mcp_tools.py`
- Modify: `tests/test_scope.py`

- [ ] **Step 1: Write failing tests for review-image export**

Cover:
- image-link listing for a narrow scope
- unsupported result if no review images exist

- [ ] **Step 2: Implement `export_review_images`**

Requirements for first version:
- review images only
- return links or manifest structure only
- no product hero-image path
- no zip packaging

- [ ] **Step 3: Add plugin summary**

Summarize:
- matched products
- matched image reviews
- first few image links or manifest count

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/test_scope.py tests/test_mcp_tools.py -k image -v
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

Expected: image-export tests pass.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/mcp/tools.py qbu_crawler/server/openclaw/plugin/index.js tests/test_scope.py tests/test_mcp_tools.py
git commit -m "feat: add review image export action"
```

---

## Manual Verification Checklist

- [ ] "看下库里有哪些产品" still uses inspect path and returns one polished answer
- [ ] "帮我分析最近差评" routes into analysis playbook and still feels generalized
- [ ] "给我导出某个产品的评论图片" no longer loops indefinitely
- [ ] unsupported artifact requests fail fast instead of thrashing tools
- [ ] `preview_scope` is used for broad produce asks and not re-run repeatedly
- [ ] `send_filtered_report` preserves the current legacy email subject/body contract by default
- [ ] existing daily workflow, notification flow, and legacy report generation are unaffected

## Final Test Commands

Run:

```bash
uv run pytest tests/test_scope.py tests/test_filtered_reports.py tests/test_mcp_tools.py tests/test_report.py tests/test_workflows.py tests/test_notifier.py tests/test_runtime.py -v
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

Expected:
- all Python tests pass
- plugin summary tests pass
- no regression in legacy report contract

## Rollout Order

1. Land Chunk 1 only and sync `workspace/`
2. Land Chunk 2 and deploy Windows package + OpenClaw plugin
3. Land Chunk 3 `send_filtered_report` only after contract-preservation tests are green
4. Land `export_review_images` last

## Notes for Execution

- Keep all changes in the `openclaw-hybrid-automation` worktree
- Do not change the current legacy email wording unless a test explicitly requires it
- Do not turn `scope` into a prompt-only abstraction; keep normalization server-owned
- Prefer additive changes over replacing existing primitives

Plan complete and saved to `docs/superpowers/plans/2026-03-31-openclaw-capability-layering.md`. Ready to execute?
