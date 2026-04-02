---
name: daily-scrape-report
description: AI digest sidecar for explaining completed daily runs. Never authoritative for report generation or email delivery.
---

# Daily AI Digest

Use this skill only after the deterministic workflow has already produced a fast report or full report.

## Inputs

- `get_workflow_status`
- `list_workflow_runs`
- `list_pending_notifications` when delivery is relevant
- optional lightweight product or review queries for explanation

## Goals

- explain unusual review volume or negative-review spikes
- summarize ownership split and notable site changes
- highlight translation backlog or delivery anomalies
- add a concise business digest on top of the deterministic workflow

## What this skill is not

- not the source of truth for workflow status
- not the source of truth for email delivery
- not the main deep-analysis skill
- not a replacement for `qbu-product-data`
- not a produce path

If the user asks for deeper comparison, trend diagnosis, or root-cause analysis, hand off to `skills/qbu-product-data/SKILL.md`.

## Rules

1. Do not regenerate the report.
2. Do not clear state files.
3. Do not claim email or notification success unless workflow or outbox state shows it.
4. Treat this output as commentary layered on top of the deterministic pipeline.
5. Follow `TOOLS.md` for output structure.
6. Keep `task execution status`, `notification delivery status`, and `report generation status` separate.
7. Prefer workflow status, notification anomaly, and data overview templates.
8. If everything is normal, be concise; do not manufacture drama.

## Default workflow

1. Inspect `get_workflow_status`
2. If the question mentions delivery, add `list_pending_notifications`
3. Summarize only the parts relevant to:
   - execution
   - report phase
   - delivery anomalies
4. If the user asks “why” and the answer needs deeper evidence, move to `qbu-product-data`

## Output Preference

Default order:

1. workflow 是否完成
2. 报告是否完成
3. 通知是否送达
4. 是否有值得关注的异常

不要把 daily digest 写成大而全的长报告。
