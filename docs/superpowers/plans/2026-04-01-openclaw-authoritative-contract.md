# OpenClaw Authoritative Contract Migration Plan

> **For agentic workers:** REQUIRED: use `superpowers:subagent-driven-development` or `superpowers:executing-plans` when implementing this plan. Track progress with checkbox syntax.

**Goal:** Make the MCP server the single source of truth for capability semantics, metric names, and time axes; thin the plugin; separate runtime rule ownership cleanly across server/plugin/workspace layers; upgrade routing from single-label intent handling to multi-axis decisions; and add semantic regression plus prompt-audit protection.

**Architecture:** Introduce a server-owned contract module and generated shared artifact, enforce a one-rule-one-owner matrix, formalize metric and time taxonomies, reduce plugin business logic, propagate canonical semantics into workspace rules and skills without duplicating runtime truth, then add semantic regression fixtures and prompt-organization audit gates.

**Tech Stack:** Python, FastMCP, SQLite, JavaScript OpenClaw plugin, Markdown workspace docs, pytest, node-based plugin tests

---

## File Structure

**Create:**
- `qbu_crawler/server/mcp/contract.py` — authoritative tool contract, metric catalog, time-axis catalog, export helpers
- `qbu_crawler/server/openclaw/plugin/generated/tool_contract.json` — generated shared artifact consumed by plugin
- `tests/test_tool_contract.py` — contract export and semantic-alignment tests
- `tests/test_metric_semantics.py` — metric taxonomy and time-axis behavior tests
- `docs/devlogs/D011-openclaw-authoritative-contract.md` — migration log and rollout notes
- `docs/superpowers/acceptance/2026-04-02-openclaw-semantic-regression.md` — semantic regression and prompt-audit matrix

**Modify:**
- `qbu_crawler/server/mcp/tools.py` — attach contract metadata and canonical semantics to high-value tools
- `qbu_crawler/models.py` — expose canonical metric helpers and explicit time-axis query helpers
- `qbu_crawler/server/openclaw/plugin/index.js` — consume generated contract, shrink local tool truth, add provenance handling
- `qbu_crawler/server/openclaw/plugin/index.test.mjs` — plugin alignment and provenance tests
- `qbu_crawler/server/openclaw/workspace/AGENTS.md` — multi-axis routing rules and provenance constraints
- `qbu_crawler/server/openclaw/workspace/TOOLS.md` — output contracts that use canonical metric/time names
- `qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md` — analysis playbook aligned to canonical semantics
- `docs/superpowers/specs/2026-04-01-openclaw-authoritative-contract-design.md` — update if implementation exposes clarified tradeoffs
- `docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md` — keep scope explicit versus semantic harness
- `tests/test_mcp_tools.py` — align tool tests to canonical payloads

**Do not modify in this plan:**
- daily workflow orchestration in `qbu_crawler/server/workflows.py`
- OpenClaw bridge transport in `qbu_crawler/server/openclaw/bridge/app.py`
- SMTP/report email wording unless contract tests require a wording change

---

## Chunk 0: Ownership Matrix and Audit Gates

### Task 0: Freeze rule ownership before implementation

**Files:**
- Modify: `docs/superpowers/specs/2026-04-01-openclaw-authoritative-contract-design.md`
- Modify: `docs/superpowers/acceptance/2026-04-02-openclaw-semantic-regression.md`
- Modify: `docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md`

- [ ] **Step 1: Reconfirm one-rule-one-owner boundaries**

Check that the spec explicitly states:
- MCP server contract owns capability truth, metric semantics, time axes, support boundaries, provenance schema
- plugin owns transport, speaker context, minimal rendering, and actual tool-call ledger
- `AGENTS.md` owns routing policy only
- `TOOLS.md` owns output contract only
- `qbu-product-data/SKILL.md` owns analysis method only

- [ ] **Step 2: Encode audit gates into the semantic harness**

The semantic harness must explicitly guard:
- rule ownership drift
- metric taxonomy drift
- time-axis drift
- composite-ask routing collapse
- evidence-threshold collapse
- provenance drift
- patch layering via dated addenda

- [ ] **Step 3: Keep the older capability harness scoped**

Ensure the older acceptance file is explicitly limited to:
- high-frequency routing
- output shape

And that it points readers to the semantic harness for meaning-level checks.

- [ ] **Step 4: Manual review**

Confirm no implementation task starts before the ownership model and audit gates are documented clearly enough to review code changes against them.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-04-01-openclaw-authoritative-contract-design.md docs/superpowers/acceptance/2026-04-02-openclaw-semantic-regression.md docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md
git commit -m "docs: define ownership and semantic audit gates"
```

---

## Chunk 1: Authoritative Contract and Shared Artifact

### Task 1: Create the server-owned contract module

**Files:**
- Create: `qbu_crawler/server/mcp/contract.py`
- Test: `tests/test_tool_contract.py`

- [ ] **Step 1: Write failing tests for exported contract shape**

Cover:
- contract contains tool name, tier, input schema, output schema
- contract includes canonical metric names
- contract includes canonical time-axis names for time-sensitive tools

- [ ] **Step 2: Implement minimal contract catalog**

Start with high-value tools:
- `get_stats`
- `list_products`
- `get_product_detail`
- `query_reviews`
- `preview_scope`
- `send_filtered_report`
- `export_review_images`
- `get_workflow_status`
- `list_pending_notifications`

- [ ] **Step 3: Add generated JSON export**

Export a deterministic artifact to:
- `qbu_crawler/server/openclaw/plugin/generated/tool_contract.json`

The export must be reproducible in tests.

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/test_tool_contract.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/mcp/contract.py qbu_crawler/server/openclaw/plugin/generated/tool_contract.json tests/test_tool_contract.py
git commit -m "feat: add authoritative mcp contract catalog"
```

### Task 2: Consume the shared artifact in the plugin

**Files:**
- Modify: `qbu_crawler/server/openclaw/plugin/index.js`
- Modify: `qbu_crawler/server/openclaw/plugin/index.test.mjs`

- [ ] **Step 1: Replace hand-maintained tool truth where possible**

The plugin should consume generated contract metadata instead of maintaining a drifting duplicate inventory.

- [ ] **Step 2: Reduce plugin summary logic to thin rendering**

Required:
- no alternate field-name fallbacks for canonical fields
- no invented business semantics
- rendering should only use contract-declared metrics
- plugin must not remain an independent capability registry

- [ ] **Step 3: Add plugin tests for contract alignment**

Assert:
- plugin fails clearly when a required canonical field is missing
- plugin summary matches canonical field names
- plugin does not introduce capabilities or support boundaries absent from the generated contract

- [ ] **Step 4: Run tests**

Run:

```bash
node --check qbu_crawler/server/openclaw/plugin/index.js
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/plugin/index.js qbu_crawler/server/openclaw/plugin/index.test.mjs
git commit -m "refactor: make plugin consume shared tool contract"
```

---

## Chunk 2: Metric Taxonomy and Time Semantics

### Task 3: Add canonical metric helpers in the data layer

**Files:**
- Modify: `qbu_crawler/models.py`
- Test: `tests/test_metric_semantics.py`

- [ ] **Step 1: Write failing tests for metric taxonomy**

Required cases:
- `get_stats` exposes `product_count` and `ingested_review_rows` semantics distinctly
- site-reported totals are not mislabeled as ingested rows
- matched review counts differ correctly from global counts

- [ ] **Step 2: Implement canonical metric helpers**

Add reusable helpers for:
- `product_count`
- `ingested_review_rows`
- `site_reported_review_total_current`
- `matched_review_product_count`
- `image_review_rows`

- [ ] **Step 3: Add explicit time-axis helpers**

Expose helpers or documented internal functions for:
- `product_state_time`
- `snapshot_time`
- `review_ingest_time`
- `review_publish_time`

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/test_metric_semantics.py tests/test_mcp_tools.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/models.py tests/test_metric_semantics.py tests/test_mcp_tools.py
git commit -m "feat: formalize metric and time semantics"
```

### Task 4: Propagate canonical semantics into workspace and skill contracts

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md`

- [ ] **Step 1: Remove ambiguous metric language**

Examples:
- replace generic "评论数" with canonical labels when needed
- distinguish stored rows from site-reported totals
- remove runtime truth duplication where a rule now belongs to the server contract

- [ ] **Step 2: Add time-axis wording rules**

The docs must state:
- when "最近" means scrape time
- when published time should be used
- when a reply must declare the axis explicitly

- [ ] **Step 3: Add historical-ownership caveat**

Analysis docs must avoid implying historical ownership truth unless supported.

- [ ] **Step 4: Reassert document ownership**

Ensure:
- `AGENTS.md` contains routing policy but not backend capability truth
- `TOOLS.md` contains output contract but not routing policy
- `SKILL.md` contains analysis method but not produce inventory

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/workspace/AGENTS.md qbu_crawler/server/openclaw/workspace/TOOLS.md qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md
git commit -m "docs: align workspace semantics to canonical metrics"
```

---

## Chunk 3: Provenance and Thin-Plugin Exactness

### Task 5: Add actual tool-call provenance handling

**Files:**
- Modify: `qbu_crawler/server/openclaw/plugin/index.js`
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Test: `qbu_crawler/server/openclaw/plugin/index.test.mjs`

- [ ] **Step 1: Track actual tool usage within a turn**

Capture enough structured provenance for:
- tool names
- whether `execute_sql` was actually called
- whether the answer came from a single exact tool or a multi-tool path

- [ ] **Step 2: Add answer constraints for "你是怎么查的"**

Rules:
- mention only actual tools used
- never claim SQL execution if no SQL tool was used
- when provenance is incomplete, say so instead of inventing steps

- [ ] **Step 3: Add plugin tests**

Cases:
- `get_stats` only path
- `get_stats + list_products` path
- no-SQL path asked for methodology
- answer must not overclaim transport, delivery, or report-generation steps absent from the actual call ledger

- [ ] **Step 4: Run tests**

Run:

```bash
node --check qbu_crawler/server/openclaw/plugin/index.js
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/plugin/index.js qbu_crawler/server/openclaw/workspace/AGENTS.md qbu_crawler/server/openclaw/plugin/index.test.mjs
git commit -m "feat: add grounded tool provenance for inspect answers"
```

---

## Chunk 4: Multi-Axis Routing

### Task 6: Replace single-label routing guidance with a decision vector

**Files:**
- Modify: `qbu_crawler/server/openclaw/workspace/AGENTS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/TOOLS.md`
- Modify: `qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md`

- [ ] **Step 1: Define routing axes**

Document:
- `needs_data_read`
- `needs_judgment`
- `needs_system_action`
- `needs_artifact`
- `needs_confirmation`
- `needs_clarification`

- [ ] **Step 2: Remove forced single-label assumptions from workspace docs**

Keep `inspect / analyze / produce` as shorthand categories only.
Runtime-facing routing guidance must decompose composite asks across multiple axes.

- [ ] **Step 3: Rewrite high-frequency routing examples**

Required examples:
- exact inspect ask
- analysis ask
- composite ask that previews then produces
- unsupported-nearby produce ask

- [ ] **Step 4: Keep simple asks simple**

Explicitly protect:
- "库里有多少产品"
- "库里有多少评论"
- "最近更新的是谁"

These should stay short-path exact asks.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/openclaw/workspace/AGENTS.md qbu_crawler/server/openclaw/workspace/TOOLS.md qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md
git commit -m "docs: adopt multi-axis routing model"
```

---

## Chunk 5: Semantic Regression Harness

### Task 7: Build semantic regression coverage

**Files:**
- Modify: `docs/superpowers/acceptance/2026-04-02-openclaw-semantic-regression.md`
- Modify: `docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md`
- Modify: `tests/test_mcp_tools.py`
- Modify: `tests/test_tool_contract.py`
- Modify: `qbu_crawler/server/openclaw/plugin/index.test.mjs`

- [ ] **Step 1: Add golden semantic cases**

Include:
- exact catalog count
- ingested-review-row count
- site-reported review total
- time-window ambiguity
- historical ownership caveat
- unsupported artifact near supported artifact
- "你是怎么查的"
- prompt-organization ownership drift
- composite-ask decomposition failure

- [ ] **Step 2: Encode expected semantics, not just formatting**

Each case must record:
- expected tool path
- expected metric name
- expected time axis
- expected provenance claim or prohibition
- forbidden drift patterns
- owning layer for each relevant runtime rule when applicable

- [ ] **Step 3: Run combined verification**

Run:

```bash
uv run pytest tests/test_tool_contract.py tests/test_metric_semantics.py tests/test_mcp_tools.py -v
node --check qbu_crawler/server/openclaw/plugin/index.js
node qbu_crawler/server/openclaw/plugin/index.test.mjs
```

- [ ] **Step 4: Write devlog**

Document:
- what drift classes are now prevented
- what remains intentionally unresolved
- rollout and deployment notes
- what still depends on human prompt review versus automated enforcement

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/acceptance/2026-04-02-openclaw-semantic-regression.md docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md docs/devlogs/D011-openclaw-authoritative-contract.md tests/test_tool_contract.py tests/test_metric_semantics.py tests/test_mcp_tools.py qbu_crawler/server/openclaw/plugin/index.test.mjs
git commit -m "test: add semantic regression harness for openclaw data paths"
```

---

## Verification Strategy

Before any rollout claim:

- review rule ownership against the spec matrix
- run all new contract, metric, and MCP tests
- run plugin tests
- manually inspect one exact ask against a known SQLite fixture
- manually inspect one composite ask that uses `preview_scope`
- manually inspect one methodology question to confirm no invented SQL/process claims
- manually inspect one prompt-organization review against the semantic harness

---

## Rollout Notes

This plan intentionally preserves:

- current daily workflow behavior
- current report delivery path
- current produce tools added in the capability-layering work

The migration prioritizes correctness of inspect semantics first, then reduces drift, then upgrades routing sophistication. Exactness is the first milestone, not the last.
