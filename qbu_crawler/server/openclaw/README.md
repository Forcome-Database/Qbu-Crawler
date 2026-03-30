# OpenClaw Integration

This directory now supports the hybrid architecture:

- Crawler Host owns deterministic execution.
- OpenClaw owns natural-language entry, read-only inspection, and optional AI digest.
- Must-deliver notifications go through `notification_outbox -> notify bridge -> openclaw message send`.

## Authoritative Paths

- Daily submit:
  `Crawler Host systemd -> qbu-crawler workflow daily-submit`
- Temporary task completion:
  `TaskManager -> notification_outbox -> OpenClaw bridge`
- Daily report:
  `WorkflowWorker -> snapshot -> fast report -> full report`
- AI digest:
  optional sidecar after full report, never authoritative

OpenClaw `cron`, `heartbeat`, and `/hooks/agent` are no longer the hard-SLA path.

## Deployment Boundaries

- `daily-submit` must run on the Crawler Host.
- The notify bridge must listen only on loopback or a private network.
- `/api` and `/mcp` are internal control-plane surfaces.
- `openclaw.json` must be deployed from versioned templates, not edited by hand.

## Feature Flags

- `NOTIFICATION_MODE=legacy|shadow|outbox`
- `DAILY_SUBMIT_MODE=openclaw|crawler_systemd`
- `REPORT_MODE=legacy|snapshot_fast_full`
- `AI_DIGEST_MODE=off|async`

Recommended rollout order:

1. `NOTIFICATION_MODE=shadow`
2. `NOTIFICATION_MODE=outbox`
3. `DAILY_SUBMIT_MODE=crawler_systemd`
4. `REPORT_MODE=snapshot_fast_full`
5. `AI_DIGEST_MODE=async`

## What OpenClaw Still Does

- Accept ad-hoc scrape/collect requests from chat.
- Query task, workflow, snapshot, and outbox state through MCP.
- Explain anomalies, summarize negative reviews, and produce AI digest text.
- Run heartbeat checks for stale workflows, failed notifications, translation backlog, and unusual review patterns.

## What OpenClaw No Longer Owns

- Daily scheduler of record
- Temporary task completion truth
- Report generation truth
- Email delivery truth

## Workspace Notes

- `workspace/AGENTS.md`: route requests and enforce safety boundaries.
- `workspace/HEARTBEAT.md`: inspection-only heartbeat checklist.
- `workspace/TOOLS.md`: tool semantics for workflow/outbox/snapshot inspection.
- `skills/daily-scrape-submit/SKILL.md`: manual fallback only.
- `skills/daily-scrape-report/SKILL.md`: AI digest only.

`workspace/state/active-tasks.json` remains only for manual fallback and migration debugging. It is not authoritative state.

## CSV Inputs

The default CSV source paths still point at the OpenClaw workspace:

- `workspace/data/sku-list-source.csv`
- `workspace/data/sku-product-details.csv`

When `DAILY_SUBMIT_MODE=crawler_systemd`, these files must be synchronized to the Crawler Host before the timer runs. That sync is part of the OpenClaw asset deployment step.
