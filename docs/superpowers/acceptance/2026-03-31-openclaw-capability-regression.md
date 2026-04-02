# OpenClaw Capability Regression Acceptance Set

Date: 2026-03-31
Scope: `openclaw-hybrid-automation`

This file records the high-frequency asks whose routing and output shape must remain stable while capability layering evolves.

It is not the full semantic-truth harness.

`inspect / analyze / produce` in this file are shorthand labels only.
The authoritative routing model remains the decision-axis model defined in the spec and consumed by `AGENTS.md`.

This file primarily protects:

- reliable fixed-path behavior for high-frequency asks
- clear and stable output shape

For metric semantics, time-axis semantics, provenance, and prompt-organization drift checks, also see:

- `docs/superpowers/acceptance/2026-04-02-openclaw-semantic-regression.md`

## Case 1: “库里有多少产品”

- **Primary axes:** `data_read`
- **Shorthand:** `inspect`
- **Expected path:** `get_stats` only
- **Expected answer shape:**
  - one merged final answer
  - direct count answer
  - no sample list unless the user explicitly asks for examples
- **Forbidden behavior:**
  - auto-calling `list_products`
  - mixing in recent products or workflow status
  - inventing SQL when `execute_sql` was not called

## Case 2: “看下库里有哪些产品”

- **Primary axes:** `data_read`
- **Shorthand:** `inspect`
- **Expected path:** `get_stats` + `list_products(limit=5, sort_by="scraped_at", order="desc")`
- **Expected answer shape:**
  - one merged final answer
  - data overview first
  - sample products second
- **Forbidden behavior:**
  - raw JSON
  - raw row fragments
  - full dump unless explicitly requested

## Case 3: “看最近抓了什么”

- **Primary axes:** `data_read`
- **Shorthand:** `inspect`
- **Expected path:** `get_stats` + `list_products(sort_by="scraped_at", order="desc", limit=5)`
- **Expected answer shape:**
  - highlight recency
  - show only a sample by default
- **Forbidden behavior:**
  - mixing workflow status into product list
  - unbounded row output

## Case 4: “帮我分析最近差评”

- **Primary axes:** `data_read + judgment`
- **Shorthand:** `analyze`
- **Expected path:**
  - start from `query_reviews(max_rating=2, ...)`
  - escalate to `qbu-product-data` if causes, patterns, or priorities are requested
- **Expected answer shape:**
  - conclusion
  - evidence
  - business interpretation
  - action suggestions
- **Forbidden behavior:**
  - only listing comments with no synthesis
  - exposing SQL

## Case 5: “给我导出某个产品的评论图片”

- **Primary axes:** `data_read + system_action + artifact`
- **Shorthand:** `produce`
- **Expected path:**
  - `preview_scope(artifact_type="review_images")` when scope is broad or ambiguous
  - `export_review_images`
- **Expected answer shape:**
  - clearly state that the export is for review images only
  - summarize counts and provide links/manifest result
- **Forbidden behavior:**
  - pretending product hero-image export is supported
  - looping across primitive query tools

## Case 6: “把指定 SKU 在某时间范围内的差评报告发邮件”

- **Primary axes:** `data_read + artifact + confirmation`
- **Shorthand:** `produce`
- **Expected path:**
  - `preview_scope`
  - `send_filtered_report`
- **Expected answer shape:**
  - state the filtered scope
  - summarize matched products/reviews
  - state artifact and email delivery result separately
- **Forbidden behavior:**
  - using `generate_report` as if it were a scoped report tool
  - claiming email delivery from primitive queries

## Maintenance Rule

Whenever `AGENTS.md`, `TOOLS.md`, the plugin summarization layer, or `qbu-product-data` is changed, re-check these cases before deployment.

This file protects high-frequency routing and output shape.
The semantic regression file protects:

- canonical metric meaning
- canonical time-axis meaning
- composite-ask decomposition
- methodology/provenance grounding
- prompt-organization drift

If the two files ever appear to conflict:

- this file wins only for stable high-frequency path and output-shape expectations
- the semantic regression file wins for meaning, ownership, time-axis, and provenance truth

Both files should stay green before rollout.
