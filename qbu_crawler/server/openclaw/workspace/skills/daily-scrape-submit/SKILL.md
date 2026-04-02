---
name: daily-scrape-submit
description: Manual fallback only. Use when the operator explicitly asks to re-submit or backfill a daily run.
---

# Manual Daily Submit

This skill is not the primary scheduler. The normal production flow runs on:

`Crawler Host qbu-crawler serve -> embedded DailySchedulerWorker -> qbu-crawler workflow daily-submit`

Use this skill only when the operator explicitly asks for:

- manual re-submit
- backfill for a logical date
- disaster recovery when the crawler service scheduler failed

Procedure:

1. Confirm the logical date and whether this is a retry or a new backfill.
2. Inspect existing workflow state first with `get_workflow_status` or `list_workflow_runs`.
3. If a run already exists for that logical date, report that fact before doing anything else.
4. If the operator still wants fallback action, explain that this uses non-authoritative legacy state and may require crawler-host reconciliation afterward.

Do not pretend this skill replaces the crawler-host embedded scheduler or becomes the runtime source of truth.
