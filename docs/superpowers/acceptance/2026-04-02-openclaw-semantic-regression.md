# OpenClaw Semantic Regression Harness

Date: 2026-04-02
Scope: `openclaw-hybrid-automation`

This file protects semantic truth, prompt organization, and methodology grounding.

It primarily protects:

- intelligent and generalizable analysis quality
- professional metric and time semantics
- grounded explanations that do not invent process

It complements:

- `docs/superpowers/acceptance/2026-03-31-openclaw-capability-regression.md`

The older file protects high-frequency routing and output shape.
This file protects meaning.

## 1. What This Harness Guards

This harness must catch:

- metric aliasing drift
- time-axis drift
- invented process/provenance
- composite-ask routing collapse
- prompt-layer ownership drift
- unsupported-nearby asks that are likely to cause tool thrash

## 2. Semantic Owners

The expected ownership model is:

- MCP server contract owns capability truth, schemas, metrics, time axes, and support boundaries
- plugin owns transport, speaker context, minimal rendering, and actual tool-call ledger
- `AGENTS.md` owns routing policy only
- `TOOLS.md` owns output contract only
- `qbu-product-data/SKILL.md` owns analysis method only

If any test case reveals that two or more layers are independently defining runtime truth, treat that as a regression.

## 3. Audit Checks

### Check A: Rule Ownership

- **Question:** Does each runtime rule have exactly one owner?
- **Failure signals:**
  - the same support boundary appears in both `AGENTS.md` and `TOOLS.md`
  - the same metric semantics appear in prompt files and plugin code with different wording
  - dated addenda define runtime truth that the main sections do not contain

### Check B: Metric Taxonomy

- **Question:** Does every user-visible metric map to one canonical metric?
- **Failure signals:**
  - generic "评论数" used where multiple underlying counts exist
  - `reviews` row counts mixed with `products.review_count`
  - matched review counts described like catalog-global counts

### Check C: Time-Axis Semantics

- **Question:** Does every time-filtered answer bind to one explicit time axis?
- **Failure signals:**
  - "最近" means scrape time in one path and publish time in another
  - a tool accepts `window` but the answer does not reveal the axis when ambiguity exists
  - trend analysis mixes current-state time and historical snapshot time

### Check D: Composite-Ask Routing

- **Question:** Are composite asks decomposed across decision axes rather than forced into one label?
- **Failure signals:**
  - "先看范围，再发报告" is routed as only `produce`
  - "分析并导出" is routed as only `analyze`
  - the answer thrashes tools because it has no intermediate confirmation state

### Check E: Evidence Threshold

- **Question:** Does analysis distinguish sample evidence from sufficient evidence?
- **Failure signals:**
  - root-cause claims built only from a few sample reviews
  - business-priority claims without grouped or comparative evidence
  - recommendations presented as firm conclusions when evidence is partial

### Check F: Provenance Grounding

- **Question:** When asked "你是怎么查的", does the answer only describe actual tool calls?
- **Failure signals:**
  - claims of SQL execution without `execute_sql`
  - claims of report generation without produce tools
  - claims of notification or delivery success without authoritative status evidence

### Check G: Patch Layering

- **Question:** Are new behaviors integrated into the main contract instead of only appended?
- **Failure signals:**
  - capability truth exists mainly in dated addenda
  - main sections remain stale while appendices continue to grow
  - acceptance covers only the latest incident-driven asks

## 4. Golden Semantic Cases

## Case 1: Exact catalog count

- **Ask:** `库里有多少产品`
- **Expected semantics:**
  - `product_count`
  - current-state catalog
- **Expected path:**
  - `get_stats` only
- **Forbidden:**
  - sample products
  - site-reported review totals
  - invented SQL/process narration

## Case 2: Exact ingested review count

- **Ask:** `库里现在已入库多少条评论`
- **Expected semantics:**
  - `ingested_review_rows`
- **Expected path:**
  - exact inspect path
- **Forbidden:**
  - using `products.review_count` sum
  - unlabeled "评论总数"

## Case 3: Site-reported review total

- **Ask:** `按站点页面显示，一共有多少评论`
- **Expected semantics:**
  - `site_reported_review_total_current`
- **Expected path:**
  - path may aggregate product current state
- **Required wording:**
  - must explicitly say `站点展示评论总数`
- **Forbidden:**
  - presenting the number as `已入库评论数`

## Case 4: Time-axis disambiguation

- **Ask:** `最近 7 天有哪些差评`
- **Expected semantics:**
  - answer must bind the window to either `review_ingest_time` or `review_publish_time`
- **Required wording:**
  - if defaulted, declare the chosen axis when ambiguity matters
- **Forbidden:**
  - silent use of a generic `window`

## Case 5: Composite ask with confirmation

- **Ask:** `先看这个范围会命中多少，再把差评报告发邮件`
- **Expected semantics:**
  - composite ask
  - requires preview before artifact
- **Expected path:**
  - `preview_scope`
  - confirmation or explicit `next_action_hint`
  - then `send_filtered_report`
- **Forbidden:**
  - forced single-label routing
  - immediate produce without preview when the scope is broad or ambiguous

## Case 6: Unsupported-nearby produce ask

- **Ask:** `把这些产品主图打包成 zip 发我`
- **Expected semantics:**
  - unsupported produce ask near a supported export capability
- **Expected path:**
  - fail fast
  - offer the nearest supported substitute
- **Forbidden:**
  - misusing `export_review_images`
  - pretending hero-image export exists

## Case 7: Methodology question

- **Ask:** `你是怎么查出来的`
- **Expected semantics:**
  - grounded tool provenance only
- **Required wording:**
  - mention only actual tool calls from the current turn
- **Forbidden:**
  - invented SQL
  - invented workflow/report steps
  - invented transport or notification status

## Case 8: Historical ownership caveat

- **Ask:** `过去 30 天自有和竞品谁表现更稳`
- **Expected semantics:**
  - if current ownership is used to look back, the answer must say so
- **Required wording:**
  - `按当前归属回看` or equivalent caveat
- **Forbidden:**
  - implying historical ownership truth without support

## Case 9: Prompt-organization ownership drift

- **Ask:** prompt or workspace refactor review
- **Expected semantics:**
  - runtime rule ownership stays separated
- **Expected path:**
  - review `AGENTS.md`, `TOOLS.md`, `qbu-product-data/SKILL.md`, plugin contract source
- **Owning layers:**
  - MCP contract: capability truth, metric semantics, time axes, support boundaries
  - plugin: transport, minimal rendering, actual tool-call ledger
  - `AGENTS.md`: routing policy
  - `TOOLS.md`: output contract
  - `qbu-product-data/SKILL.md`: analysis method
- **Forbidden:**
  - repo-local paths inside runtime workspace prompts
  - duplicated support matrices across `AGENTS.md` and `TOOLS.md`
  - dated addenda becoming the real runtime contract

## Case 10: Composite-ask decomposition failure

- **Ask:** `先看范围和风险，再判断值不值得做，最后把报告发邮件`
- **Expected semantics:**
  - this is a composite ask across multiple axes
- **Expected path:**
  - decompose into `data_read`, `judgment`, `confirmation`, `artifact`
  - preview or scope first
  - artifact only after explicit confirmation or a clear `next_action_hint`
- **Expected provenance rule:**
  - methodology explanations must reflect the staged path, not a fake single-step action
- **Forbidden:**
  - routing the whole ask as only `produce`
  - skipping the preview/confirmation layer when scope is broad
  - explaining the method as if a report was sent before the preview stage completed

## 5. Prompt-Organization Review Checklist

Before rollout, review these artifacts together:

- `workspace/AGENTS.md`
- `workspace/TOOLS.md`
- `workspace/skills/qbu-product-data/SKILL.md`
- `plugin/index.js`
- MCP server contract or tool schema source

Review questions:

1. Which file is the owner of this rule?
2. Is the same truth redefined elsewhere?
3. Is every visible metric canonically named?
4. Is every visible time window canonically bound?
5. Can a composite ask be decomposed without tool thrash?
6. Can the assistant explain its method without inventing steps?

If any answer is "not sure", treat it as a review failure.

## 6. Passing Criteria

The harness passes only if:

- exact inspect answers stay exact
- metric names stay canonical
- time axes stay explicit
- methodology answers stay grounded
- unsupported-nearby asks fail fast
- prompt files do not reintroduce duplicated runtime truth
