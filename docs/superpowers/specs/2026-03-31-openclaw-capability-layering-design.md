# OpenClaw Capability Layering Design

Date: 2026-03-31
Status: Draft for review
Scope: `openclaw-hybrid-automation` worktree

## 1. Problem Statement

The current Qbu OpenClaw experience has three conflicting needs:

1. Process requests must be deterministic and reliable.
2. Data analysis must remain intelligent, professional, and general-purpose.
3. Output must be clear, friendly, and consistent.

Today, the system is strong on basic querying and workflow execution, but weak at generalized "produce an artifact" requests. When the user asks for a deliverable such as exporting images or sending a filtered email report, the assistant can loop across MCP tools without a terminating path because the request exceeds the current tool surface.

At the same time, high-frequency data queries can still degrade into mixed output if the model combines summaries with raw tool fragments.

This design introduces a capability layering model that improves reliability without reducing analysis flexibility.

## 2. Goals

- Keep existing daily workflow, report delivery, and basic MCP querying intact.
- Add a consistent abstraction that can support generalized user requests such as:
  - inspect products/reviews by ownership, site, SKU, product name, date window, price range, rating range
  - analyze trends, anomalies, comparisons, and root causes across the same filter model
  - produce deliverables such as filtered email reports and exported review-image lists
- Prevent "tool thrash" when a request cannot currently be satisfied.
- Improve prompt and skill stability without pushing too much logic into prompts.

## 3. Non-Goals

- Replacing all existing MCP tools with a new tool family.
- Converting analysis into dozens of rigid scenario-specific tools.
- Rewriting the daily workflow architecture.
- Adding product hero-image export in this phase. The current database does not persist product hero-image fields.

## 4. Design Principles

### 4.1 Deterministic where actions happen

Any request that creates an artifact or external side effect must go through a dedicated server-side tool path. The assistant must not improvise these actions from primitive query tools.

### 4.2 Flexible where analysis happens

Analysis should keep a broad base of primitive tools plus a stronger analysis playbook. The system should not overfit to a small set of report templates.

### 4.3 Strong output contracts

The assistant should never expose raw tool fragments in the final answer. All multi-tool answers must be merged into a single polished response.

### 4.4 Additive rollout

The new model must layer on top of existing capabilities. Existing queries, daily runs, and legacy reports must continue to work.

## 5. Capability Model

All user requests are classified into three operation types.

### 5.1 Inspect

Purpose: read data, inspect status, preview scope, sample records.

Examples:
- "库里有哪些产品"
- "看看最近抓了什么"
- "看某个产品详情"
- "看某个 workflow 状态"

Characteristics:
- read-only
- small, fast, bounded outputs
- allowed to use existing primitive tools directly

### 5.2 Analyze

Purpose: interpret data, compare groups, explain trends or anomalies, produce business conclusions.

Examples:
- "竞品和自有谁评分更稳"
- "最近差评集中在哪些问题"
- "某价格区间的产品表现如何"
- "为什么今天评论数异常"

Characteristics:
- built on inspect data
- requires evidence-backed reasoning
- should route through `qbu-product-data` playbook when the question exceeds a single tool answer

### 5.3 Produce

Purpose: create an artifact or perform an external delivery action.

Examples:
- "把这些产品的差评报告发邮件"
- "导出某个产品的评论图片"
- "生成指定日期范围的筛选报告"

Characteristics:
- must use dedicated tool paths
- must fail fast if no supported tool exists
- must not attempt to synthesize unsupported output through repeated primitive queries

## 6. Unified Request Model

To maximize generalization, filtering and aggregation should be standardized.
This model is a **server-owned internal normalization contract**, not a second prompt-layer DSL. The backend must own:

- parameter normalization
- default filling
- range interpretation
- filter validation
- aggregation safety

The prompt layer may reason with these concepts, but it should not be expected to assemble a full nested request object ad hoc before every call.

### 6.1 Scope

`scope` defines what data the request targets.

Suggested shape:

```json
{
  "products": {
    "ids": [],
    "skus": [],
    "names": [],
    "sites": [],
    "ownership": [],
    "price": { "min": null, "max": null },
    "rating": { "min": null, "max": null },
    "review_count": { "min": null, "max": null }
  },
  "reviews": {
    "sentiment": "all",
    "rating": { "min": null, "max": null },
    "keyword": "",
    "has_images": null
  },
  "window": {
    "since": null,
    "until": null
  }
}
```

This shape supports the user's common natural constraints without creating a separate tool parameter design for every new feature.
The backend may expose this as typed tool input, but the assistant must not be forced to translate natural language twice.

### 6.2 View

`view` defines aggregation or presentation intent.

Suggested shape:

```json
{
  "group_by": [],
  "metrics": [],
  "sort": [],
  "limit": 20
}
```

Typical `group_by` values:
- `site`
- `ownership`
- `product`
- `day`
- `week`
- `price_bucket`
- `rating_bucket`

Typical `metrics`:
- `product_count`
- `review_count`
- `avg_price`
- `avg_rating`
- `negative_rate`
- `positive_rate`
- `image_review_count`

### 6.3 Delivery

`delivery` defines how the result should be returned.

Suggested shape:

```json
{
  "format": "chat|excel|email|links",
  "template": "overview|comparison|issue|custom",
  "recipients": [],
  "include_attachments": true
}
```

## 7. Tooling Strategy

### 7.1 Keep primitive tools

Existing primitive MCP tools remain the general-purpose base:

- `list_products`
- `get_product_detail`
- `query_reviews`
- `get_price_history`
- `get_stats`
- `execute_sql`

These remain essential for generalized inspection and analysis.

### 7.2 Add a small number of generalized action tools

The design introduces a limited set of higher-level tools for `produce` requests.

#### `preview_scope`

Purpose:
- estimate how many products and reviews match a requested scope
- tell the assistant whether the request is feasible
- provide a safe first step for large or ambiguous requests

Why first:
- prevents blind tool loops
- provides a consistent front door for complex requests

Control rules:
- `preview_scope` is optional for narrow scopes that already identify one product or a very small set of products.
- `preview_scope` is required before `produce` actions when any of the following is true:
  - no explicit product identifier is present
  - the request spans multiple sites or ownership groups
  - the date window exceeds 7 days
  - the likely match size may exceed 20 products or 200 reviews
- `preview_scope` must return a `next_action_hint`:
  - `safe_to_continue`
  - `requires_confirmation`
  - `unsupported`
- The agent must not re-run `preview_scope` in a loop. One preview per user ask is the default unless the user changes scope.

#### `send_filtered_report`

Purpose:
- generate a filtered report for a `scope`
- optionally deliver it through email

Supports:
- specific product names or SKUs
- ownership filters
- site filters
- date windows
- rating or sentiment slices

Contract lock:
- `send_filtered_report` must reuse the current report generation pipeline rather than introduce a second email/report contract.
- Title, body style, attachment behavior, and recipient handling must remain compatible with the current legacy report expectations unless the user explicitly asks for a different template.
- This is a rollout-critical guard because report-template regressions have already occurred in the current branch history.

#### `export_review_images`

Purpose:
- export review-image links for a filtered scope

Scope of first version:
- review images only
- not product hero images
- links or manifest output only in the first version
- no zip or archive packaging in the first version

### 7.3 Do not add `analyze_scope` yet

Analysis should remain skill-led in the first generalized rollout. The existing primitive tools plus a stronger `qbu-product-data` playbook are sufficient for this phase.

If `analyze_scope` is later added, it should remain narrow and should not replace the playbook-driven analysis model prematurely.

## 8. Prompt and Skill Design

Routing ownership must stay canonical:

- `AGENTS.md` owns request classification and tool/skill routing
- `TOOLS.md` owns output contract and capability-facing templates
- `qbu-product-data/SKILL.md` owns analysis methodology after routing is already decided

The same routing table must not be duplicated across multiple files.

### 8.1 AGENTS.md

Responsibility:
- intent classification
- hard routing rules
- fail-fast boundaries
- "one final answer" rule

Changes:
- explicitly classify requests into `inspect / analyze / produce`
- require fail-fast for unsupported `produce` requests
- require `preview_scope` before large or ambiguous `produce` requests
- forbid continued primitive-tool exploration when the system lacks a supported action path
- contain the canonical routing table for:
  - when to use primitive tools
  - when to enter the analysis skill
  - when to require dedicated produce tools

### 8.2 TOOLS.md

Responsibility:
- output contract
- response templates
- display budgets
- supported-vs-unsupported capability boundaries

Changes:
- add a capability boundary section
- add templates for:
  - product lists
  - scope previews
  - filtered report previews
  - report delivery confirmation
  - unsupported action responses
- do not duplicate routing ownership from `AGENTS.md`

### 8.3 qbu-product-data/SKILL.md

Responsibility:
- analysis playbook

Changes:
- formalize analysis types:
  - overview
  - comparison
  - trend
  - anomaly
  - root cause
- require conclusions to be evidence-backed
- require explicit uncertainty language when evidence is insufficient
- encourage minimal-query evidence gathering before deeper SQL

### 8.4 daily-scrape-report/SKILL.md

Responsibility:
- workflow-status and report-result explanation only

Changes:
- keep narrow
- reuse the same output discipline
- do not turn this into a second analysis engine

### 8.5 csv-management/SKILL.md

Responsibility:
- deterministic CSV management

Changes:
- no smartening beyond SOP clarity
- keep it strict and procedural

## 9. Data Model and Backend Implications

### 9.1 Models

`models.py` should gain reusable filter-building helpers so the new generalized tools do not duplicate filtering rules.

Needed capabilities:
- normalized product filter builder
- normalized review filter builder
- reusable scope preview count queries
- reusable filtered review-image lookup

### 9.2 Report generation

`report.py` should be extended so filtered report generation reuses the existing Excel and email pipeline rather than introducing a parallel reporting stack.

Desired structure:
- query filtered data
- generate Excel with existing formatting
- reuse stable email template conventions where appropriate
- report success/failure in a structured result

### 9.3 Current data limitations

The current database already supports:
- product-level filtering
- ownership filtering
- site filtering
- price/rating/review-count filtering
- review-level rating/date/keyword/has-images filtering
- review-image export

The current database does not yet support:
- exporting product hero images as a first-class artifact

That requires scraper and storage changes and is explicitly deferred.

## 10. Failure Handling

### 10.1 Unsupported action requests

When the user requests a `produce` action with no supported backend path:
- answer immediately that the action is not currently supported
- offer the nearest supported substitute
- do not continue tool exploration

### 10.2 Large or risky scopes

When the scope is large, ambiguous, or likely expensive:
- run `preview_scope` first
- summarize counts and likely output shape
- rely on the returned `next_action_hint`
- continue automatically only when `next_action_hint = safe_to_continue`
- ask for confirmation only when `next_action_hint = requires_confirmation`
- stop immediately when `next_action_hint = unsupported`

### 10.3 Partial deliverability

Action results must distinguish:
- data scope match
- artifact generation result
- delivery result

Do not collapse these into a single “success”.

## 11. Report Types Enabled by This Design

Using the unified model, the system can support a broad report family:

- overview reports
- comparison reports
- trend reports
- issue / negative-review reports
- product-watch reports
- custom filtered reports

All of these reuse:
- the same `scope`
- the same delivery patterns
- the same report pipeline

This is the core generalization benefit of the design.

## 12. Rollout Plan

### Phase 1

- add fail-fast prompt boundaries
- add `preview_scope`
- strengthen output contracts for complex requests

Expected value:
- immediately stops infinite MCP loops on unsupported produce requests

### Phase 2

- add `send_filtered_report`
- extend report pipeline for filtered generation and email delivery

Expected value:
- unlocks the most common generalized artifact request

### Phase 3

- add `export_review_images`
- improve report templates and delivery summaries

Expected value:
- expands artifact support without changing the architecture

### Phase 4

- consider product hero-image support if still needed
- only after scraper/storage model changes are scoped separately

## 13. Testing Strategy

### Backend tests

- scope normalization and filter-building tests
- preview count correctness tests
- filtered report generation tests
- report delivery result-shape tests
- export review-image result tests

### Plugin / prompt behavior tests

- verify supported `produce` requests choose the correct tool path
- verify unsupported `produce` requests fail fast
- verify multi-tool responses remain single-answer and do not leak raw fragments

### Prompt regression harness

Add a small acceptance set for the high-frequency asks that currently drift.

Minimum seed cases:
- "看下库里有哪些产品"
- "看最近抓了什么"
- "帮我分析最近差评"
- "给我导出某个产品的评论图片"
- "把指定 SKU 在某时间范围内的差评报告发邮件"

Acceptance expectations:
- correct `inspect / analyze / produce` classification
- no raw JSON or row-fragment leakage
- no unbounded tool loops
- fail-fast when a requested artifact path is not yet supported

### Regression focus

Protect current behavior for:
- daily workflows
- workflow notifications
- legacy report generation
- high-frequency product/review queries

## 14. Recommendation

Proceed with the layered hybrid design.

The first implementation slice should be:

1. fail-fast support boundaries in OpenClaw prompt/skill layer
2. explicit routing ownership
3. `preview_scope`

Defer `send_filtered_report` until the implementation plan explicitly preserves the current legacy email/report contract unchanged.

This sequence yields the largest reliability improvement while preserving current generalized query and analysis behavior.
