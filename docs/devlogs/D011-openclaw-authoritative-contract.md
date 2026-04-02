# D011 OpenClaw Authoritative Contract

Date: 2026-04-02
Branch: `openclaw-hybrid-automation`

## Summary

This round converted the semantic regression harness from a doc-only checklist into executable guardrails for:

- canonical metric naming
- time-axis wording
- unsupported-nearby produce boundaries
- prompt-organization drift
- grounded methodology / provenance answers

## Drift Classes Now Prevented

- `get_stats` style answers drifting between `ingested_review_rows` and `site_reported_review_total_current`
- `preview_scope` style answers collapsing `product_count` into `matched_review_product_count`
- plugin methodology prompts claiming SQL when `execute_sql` was not actually completed
- runtime workspace prompts referencing repo-local files or repo-only review artifacts
- semantic harness docs forgetting ownership-drift and composite-ask decomposition cases

## What Remains Intentionally Unresolved

- The OpenClaw runtime still relies on prompt-layer routing and output contracts; this harness does not replace human review of prompt quality.
- The plugin still renders human-readable summaries for structured tool results; the harness reduces drift but does not yet remove all rendering logic from the plugin.
- Historical ownership is still a current-state field applied retrospectively; the harness only enforces the caveat wording, not a true historical ownership model.

## Deployment Notes

- Changes in this chunk are docs/tests/plugin-test coverage only.
- No crawler-host Python deployment is required for this chunk by itself.
- If plugin tests are shipped together with runtime prompt changes, the OpenClaw server should receive the updated workspace docs and plugin test source alongside any plugin runtime changes.

## Human Review Still Required

The automated harness now checks:

- contract support boundaries
- semantic case coverage in acceptance docs
- repo-local path leakage in runtime workspace docs
- decision-vector and canonical-wording anchors
- grounded provenance prompt additions

Human review is still required for:

- whether a new prompt wording is genuinely clear to end users
- whether analysis outputs overstate evidence in nuanced business situations
- whether new composite asks are decomposed in a user-friendly order
