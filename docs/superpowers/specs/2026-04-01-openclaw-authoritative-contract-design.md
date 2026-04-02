# OpenClaw Authoritative Contract Design

Date: 2026-04-01
Status: Draft for review
Scope: `openclaw-hybrid-automation` worktree

## 1. Problem Statement

The current OpenClaw data experience has improved capability breadth, but it has regressed on one critical property: exact answers are no longer reliably grounded in a single source of truth.

The system currently spreads truth across five layers:

1. MCP server tool implementations and returned payloads
2. OpenClaw plugin tool metadata and result summarizers
3. Workspace routing rules in `AGENTS.md`
4. Output contracts in `TOOLS.md`
5. Analysis behavior in `skills/qbu-product-data/SKILL.md`

As soon as any layer drifts, the assistant can answer with numbers or explanations that are plausible but wrong.

This is not a prompt-only problem. It is an architecture problem:

- exact inspect queries are routed through too many interpretive layers
- metrics such as "评论数" do not have a stable taxonomy
- time windows are not formalized
- plugin summarization acts like a second reasoning layer
- regression coverage mostly protects routing and formatting, not semantic truth

The system needs a new foundation that preserves flexible analysis and new produce capabilities without sacrificing accuracy.

## 2. Goals

- Re-establish a single authoritative contract for tool semantics and result shapes.
- Restore exact inspect queries to short, deterministic, truth-first behavior.
- Formalize metric names so chat answers and analysis use the same semantics.
- Formalize time axes so "最近", "时间范围", and "趋势" are not silently interpreted in different ways.
- Reduce plugin drift by turning it into a thin adapter instead of a second business-logic layer.
- Upgrade routing from a single coarse label to a multi-axis decision model that supports composite asks.
- Add semantic regression coverage for exactness, not only formatting.

## 3. Non-Goals

- Rewriting the daily workflow architecture.
- Removing current `preview_scope`, `send_filtered_report`, or `export_review_images` capabilities.
- Turning all analysis into rigid scenario-specific tools.
- Solving historical ownership reconstruction in full during the first migration chunk.
- Building product hero-image export in this phase.

## 4. Diagnosis

### 4.1 Truth is duplicated

The same concepts are redefined in multiple places:

- MCP tools define real capabilities and payloads
- plugin code re-describes those capabilities and reinterprets payloads
- workspace docs describe another copy of capability boundaries
- tests and acceptance files encode assumptions about older field names

This duplication makes drift inevitable.

### 4.2 The plugin is too smart

The plugin currently does more than transport and minimal normalization. It also:

- infers summaries
- maps fields
- chooses output semantics
- embeds another layer of business phrasing

That makes it a second reasoning layer in front of the model.

### 4.3 Metrics are underspecified

The system currently has multiple incompatible notions of "评论数":

- current product-page displayed review count from `products.review_count`
- historical snapshot review count from `product_snapshots.review_count`
- ingested review rows from `COUNT(reviews)`
- matched review rows after applying a review filter
- image-bearing review rows

Today these can all collapse into a single phrase in prompts or answers.

### 4.4 Time semantics are underspecified

The system already stores several time axes:

- `products.scraped_at`
- `product_snapshots.scraped_at`
- `reviews.scraped_at`
- `reviews.date_published`
- workflow/task timestamps such as `created_at`, `started_at`, `finished_at`

But the assistant contract still treats many of these as a generic `window`.

### 4.5 Routing is overfit to recent asks

The current `inspect / analyze / produce` framing is directionally useful, but real asks are often composite:

- "先看看范围，再给我发报告"
- "帮我分析这个时间窗的差评，并导出带图评论"
- "告诉我库里有多少产品，顺便说说最近更新的是谁"

Single-label routing is not sufficient for these asks.

### 4.6 Regression is too shallow

The current test and acceptance set focuses on:

- tool availability
- route choice
- output shape

It does not yet protect:

- metric semantics
- time-axis semantics
- explanation provenance
- composite-ask decomposition

## 5. Design Principles

### 5.1 Server truth first

The authoritative contract must be owned by the MCP server side. Every downstream consumer should derive from that contract rather than hand-maintaining its own interpretation.

### 5.2 Thin plugin

The plugin should normalize and render. It should not invent alternate field names or business semantics.

### 5.3 Semantic names over generic names

Generic names like `review_count` are not acceptable as user-facing semantics unless the underlying meaning is exact and unique.

### 5.4 Time axis must be explicit

Every result that depends on time must declare which time axis it uses.

### 5.5 Composite asks are first-class

Routing must model whether a request needs data read, judgment, side effects, confirmation, or artifact delivery. A single label is not enough.

### 5.6 Regression must protect meaning

The harness must detect semantic drift, not only formatting drift.

### 5.7 One rule, one owner

Every operational rule must have exactly one authoritative owner.

If the same rule is defined in multiple layers, the system will eventually drift.

## 6. Ownership Model

This design requires an explicit ownership matrix.

### 6.1 Runtime ownership matrix

| Layer | Owns | Must not own |
|---|---|---|
| MCP server contract | tool capability truth, input/output schema, metric taxonomy, time-axis taxonomy, support boundaries, provenance schema | chat phrasing, visual formatting, high-frequency example wording |
| OpenClaw plugin | transport, session hooks, speaker context, minimal rendering of server-declared fields, actual tool-call ledger | independent capability inventory, alternate field names, business conclusions, hidden metric remapping |
| `AGENTS.md` | routing policy, fail-fast behavior, decomposition rules for composite asks | backend support matrix, duplicated parameter truth, metric semantics, time semantics |
| `TOOLS.md` | output contract, user-facing wording, display templates, status wording | routing policy, capability truth, duplicated support inventory |
| `qbu-product-data/SKILL.md` | analysis method, evidence standards, escalation rules inside analysis | exact inspect routing, produce inventory, backend metric definitions |

### 6.2 Ownership constraints

- Capability truth must flow downward from the server contract.
- Output wording may depend on capability truth, but may not redefine it.
- Prompt files may consume metric and time semantics, but may not rename or reinterpret them.
- Addenda are allowed only for rollout notes, not as a second source of runtime truth.
## 7. Proposed Architecture

## 7.1 Authoritative contract

Introduce a server-owned contract layer that defines:

- tool capability tier
- input schema
- output schema
- supported semantics
- unsupported semantics
- metric names surfaced by each tool
- time axes surfaced by each tool

Recommended ownership:

- source of truth in Python under the MCP/server side
- generated shared artifact for plugin consumption
- tests that assert plugin and docs stay aligned to that generated artifact

The plugin and workspace docs must stop being the place where raw capability truth is invented.

### Contract shape

Each tool contract should declare at least:

```json
{
  "name": "get_stats",
  "tier": "inspect_exact",
  "input_schema": {},
  "output_schema": {},
  "metrics": ["product_count", "ingested_review_rows", "avg_price", "avg_rating"],
  "time_axes": ["product_state_time"],
  "supports": ["exact current-state catalog overview"],
  "does_not_support": ["historical trend", "site-reported review totals unless explicitly named"]
}
```

### Contract consumers

- MCP server tool registration
- OpenClaw plugin tool metadata
- plugin summarization rules
- workspace capability boundaries
- semantic regression fixtures

## 7.2 Metric taxonomy

Formalize a canonical metric vocabulary.

### Core catalog metrics

| Canonical metric | Meaning | Source |
|---|---|---|
| `product_count` | Number of products matching the current product scope | `products` |
| `ingested_review_rows` | Number of rows in `reviews` matching the current review scope | `reviews` |
| `site_reported_review_total_current` | Sum of current `products.review_count` for the current product scope | `products` |
| `snapshot_reported_review_total` | Sum of historical `product_snapshots.review_count` in a snapshot window | `product_snapshots` |
| `matched_review_product_count` | Distinct product count among matched review rows | `reviews` x `products` |
| `image_review_rows` | Matched review rows with non-empty images | `reviews` |
| `avg_price_current` | Average current price of scoped products | `products` |
| `avg_rating_current` | Average current rating of scoped products | `products` |

### Default language rules

- "产品数" defaults to `product_count`
- "已入库评论数" defaults to `ingested_review_rows`
- "站点显示评论数" must be used when the source is `products.review_count`
- "命中评论产品数" must be used when a review filter narrows the product set
- "带图评论数" maps to `image_review_rows`

No output contract should use an unlabeled generic "评论数" if there is any ambiguity.

## 7.3 Time-axis taxonomy

Formalize canonical time axes.

| Canonical time axis | Meaning | Backing field |
|---|---|---|
| `product_state_time` | Time when current product row was last refreshed | `products.scraped_at` |
| `snapshot_time` | Time when a historical product snapshot was captured | `product_snapshots.scraped_at` |
| `review_ingest_time` | Time when a review row was ingested by the crawler | `reviews.scraped_at` |
| `review_publish_time` | Time published on the source site | `reviews.date_published` |
| `task_lifecycle_time` | Task/workflow lifecycle timestamps | `tasks.*`, `workflow_runs.*`, `notification_outbox.*` |

### Time rules

- Every tool that accepts a window must declare which time axis that window binds to.
- Any answer that summarizes time-filtered data must label the axis when ambiguity is possible.
- "最近" defaults must be documented by tool family, not improvised by the model.

## 7.4 Historical dimension semantics

Some dimensions are current-state only unless otherwise modeled.

### Ownership

`products.ownership` is current-state metadata, not guaranteed historical truth.

Short-term rule:

- exact current-state inspect answers may use current ownership
- historical comparisons must label this as "按当前归属回看"
- the assistant must not imply that ownership was historically stable unless evidence exists

Future-compatible direction:

- persist ownership into historical snapshot or audit records when true historical-own-vs-competitor analysis becomes required

## 7.5 Multi-axis routing model

Replace the implicit single-label classifier with a decision vector.

Each ask should be evaluated on these axes:

- `needs_data_read`
- `needs_judgment`
- `needs_system_action`
- `needs_artifact`
- `needs_confirmation`
- `needs_clarification`

### Routing examples

| Ask | Decision vector | Expected path |
|---|---|---|
| "库里有多少产品" | read | `get_stats` only |
| "最近差评集中在哪些问题" | read + judgment | inspect tools + `qbu-product-data` |
| "给我导出这个产品的评论图片" | read + system_action + artifact | `preview_scope` optionally, then `export_review_images` |
| "先看这个范围命中多少，再发差评报告" | read + needs_confirmation + artifact | `preview_scope` then `send_filtered_report` |

This model prevents simple exact asks from being over-routed while still supporting composite requests.

### Routing guardrail

The decision vector replaces single-label intent classification as the authoritative routing model.

`inspect / analyze / produce` may still be used as shorthand in human discussion, but runtime-facing routing guidance must not depend on a forced single-choice label when the ask is composite.

## 7.6 Plugin role

The plugin should become a thin adapter.

Allowed plugin responsibilities:

- transport
- minimal normalization of structured content
- compact rendering of already-declared metrics
- actual-tool provenance logging for the current turn

Disallowed plugin responsibilities:

- inventing alternate field names
- inferring business conclusions not present in the tool contract
- silently changing metric semantics
- becoming the canonical inventory of tool capabilities

## 7.7 Provenance for "你是怎么查的"

The system should preserve an actual tool-call ledger for the current interaction.

Desired behavior:

- if the assistant used `get_stats`, it may say so
- if the assistant used `execute_sql`, it may name the SQL tool
- if no SQL tool was called, it must not claim that SQL was executed

This should be driven by real call provenance, not prompt-only discipline.

## 7.8 Semantic regression harness

Extend regression from format-only checks into semantic truth checks.

The harness should cover:

- exact inspect asks
- metric ambiguity cases
- time-axis ambiguity cases
- composite ask decomposition
- unsupported-nearby produce asks
- provenance questions such as "你是怎么查的"

The harness should assert:

- correct tool path
- correct metric semantics
- correct time-axis semantics
- no invented process claims
- no raw tool leakage in final answers

## 7.9 Prompt organization audit harness

The system also needs a document-level audit harness so prompt files stop drifting into overlapping mini-contracts.

### Required audit checks

1. `Rule ownership check`
   - Every operational rule must have one owner.
   - Failure signal: the same capability boundary, metric rule, or routing rule appears in multiple files as runtime truth.

2. `Composite-ask routing check`
   - Composite asks must be decomposed across decision axes.
   - Failure signal: a request like "先看范围，再发报告" is still forced into a single label.

3. `Metric taxonomy check`
   - Every user-visible metric must map to a canonical metric.
   - Failure signal: generic "评论数" remains unlabeled in ambiguous contexts.

4. `Time-axis check`
   - Every "最近 / 时间范围 / 趋势" interpretation must bind to an explicit time axis.
   - Failure signal: the same phrase can mean scrape time in one file and publish time in another.

5. `Inspect/analyze evidence-threshold check`
   - Analytical conclusions must require enough evidence.
   - Failure signal: sample rows alone are treated as sufficient for root-cause or business-priority claims.

6. `Provenance check`
   - Methodology explanations must be grounded in actual tool calls.
   - Failure signal: the assistant claims SQL execution without an actual SQL tool call.

7. `Patch-layering check`
   - New capabilities must update the main contract, not only dated addenda.
   - Failure signal: appendices grow while the main sections remain stale.

### Audit output

Every prompt-organization audit should report:

- duplicated truths
- contradictory rules
- hidden assumptions
- ambiguous metrics
- ambiguous time axes
- unsupported-nearby asks that are likely to trigger tool thrash

This audit harness complements semantic regression; it does not replace it.

## 8. Compatibility and Rollout

This design is additive.

The following remain intact:

- daily workflow execution
- legacy report email contract
- current produce tools introduced in the capability-layering phase
- primitive inspect tools

The migration should first improve semantic correctness, then reduce duplication, then improve routing sophistication.

## 9. Success Criteria

The design is successful when:

- exact inspect answers are grounded in canonical metrics and stop drifting
- plugin summaries can no longer disagree with real server payloads without failing tests
- the assistant explicitly distinguishes stored review rows from site-reported review totals
- time-filtered answers declare their time axis when needed
- composite asks stop degenerating into either over-routing or tool thrash
- regression fixtures catch semantic drift before rollout
- prompt audits can identify duplicated runtime truth before it reaches production

## 10. Recommended Migration Order

1. Establish the authoritative contract and shared artifact.
2. Introduce metric and time taxonomies into tool outputs and workspace language.
3. Thin the plugin and add provenance tracking.
4. Refactor routing to multi-axis decisions.
5. Upgrade semantic regression coverage.
6. Add prompt-organization audit checks to review and rollout discipline.

This order fixes exactness first and sophistication second.
