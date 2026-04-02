# OpenClaw Integration

This directory now supports the hybrid architecture:

- Crawler Host owns deterministic execution.
- OpenClaw owns natural-language entry, read-only inspection, and optional AI digest.
- Must-deliver notifications go through `notification_outbox -> notify bridge -> openclaw message send`.

## Authoritative Paths

- Daily submit:
  `Crawler Host qbu-crawler serve -> embedded DailySchedulerWorker -> submit_daily_run`
- Temporary task completion:
  `TaskManager -> notification_outbox -> OpenClaw bridge`
- Daily report:
  `WorkflowWorker -> snapshot -> fast report -> full report`
- AI digest:
  optional sidecar after full report, never authoritative

OpenClaw `cron`, `heartbeat`, and `/hooks/agent` are no longer the hard-SLA path.

## Deployment Boundaries

- `daily-submit` must run on the Crawler Host.
- `daily-submit` is now started by the crawler service itself when `DAILY_SUBMIT_MODE=embedded`.
- The notify bridge must listen only on loopback or a private network.
- `/api` and `/mcp` are internal control-plane surfaces.
- `openclaw.json` must be deployed from versioned templates, not edited by hand.

## Feature Flags

- `NOTIFICATION_MODE=legacy|shadow|outbox`
- `DAILY_SUBMIT_MODE=openclaw|embedded`
- `DAILY_SCHEDULER_TIME=HH:MM`
- `REPORT_MODE=legacy|snapshot_fast_full`
- `AI_DIGEST_MODE=off|async`

Recommended rollout order:

1. `NOTIFICATION_MODE=shadow`
2. `NOTIFICATION_MODE=outbox`
3. `DAILY_SUBMIT_MODE=embedded`
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

The scheduler can read CSV inputs in two ways:

1. Local filesystem paths:
   - `DAILY_SOURCE_CSV_PATH`
   - `DAILY_PRODUCT_CSV_PATH`
2. Remote download URLs:
   - `DAILY_SOURCE_CSV_URL`
   - `DAILY_PRODUCT_CSV_URL`

If the `*_CSV_URL` variables are configured, the embedded scheduler downloads the latest CSV files at trigger time and the OpenClaw-managed workspace files remain the source of truth.

If the `*_CSV_URL` variables are empty, then the CSV files must already be present on the Crawler Host before `serve` starts.
