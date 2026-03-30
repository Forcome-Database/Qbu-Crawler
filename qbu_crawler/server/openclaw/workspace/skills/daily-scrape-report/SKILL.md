---
name: daily-scrape-report
description: AI digest sidecar for explaining completed daily runs. Never authoritative for report generation or email delivery.
---

# Daily AI Digest

Use this skill only after the deterministic workflow has already produced a fast report or full report.

Inputs:

- `get_workflow_status`
- `list_workflow_runs`
- optional product/review queries for deeper explanation

Goals:

- explain unusual review volume or negative-review spikes
- summarize ownership split and notable site changes
- highlight translation backlog or delivery anomalies

Rules:

1. Do not regenerate the report.
2. Do not clear state files.
3. Do not claim email or notification success unless workflow/outbox state shows it.
4. Treat this output as commentary layered on top of the deterministic pipeline.
