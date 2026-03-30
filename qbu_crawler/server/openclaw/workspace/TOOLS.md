# Tool Guide

## Task Submission

- `start_scrape(urls, ownership, reply_to)`
- `start_collect(category_url, ownership, max_pages=0, reply_to="")`

Rules:

- `ownership` must be `own` or `competitor`.
- For ad-hoc chat tasks, always pass `reply_to`.

## Workflow Inspection

- `get_workflow_status(run_id | trigger_key)`
  returns run state, `report_phase`, snapshot metadata, and attached tasks
- `list_workflow_runs(status="", limit=20)`
  use for daily pipeline inspection
- `list_pending_notifications(status="", limit=20)`
  use for outbox backlog, failed delivery, and deadletter checks

Important states:

- workflow `status`:
  `submitted`, `running`, `reporting`, `completed`, `failed`, `needs_attention`
- workflow `report_phase`:
  `none`, `fast_pending`, `fast_sent`, `full_pending`, `full_sent`
- notification `status`:
  `pending`, `claimed`, `failed`, `sent`, `deadletter`

## Data and Reporting

- `generate_report(since, send_email="true")` is the legacy service-side report pipeline.
- In the new workflow path, fast/full report state should be read from workflow tools first.
- `trigger_translate()` and `get_translate_status()` are operational helpers, not daily scheduler controls.

## Old Compatibility Tools

- `check_pending_completions`
- `mark_notified`

These exist only for `legacy` and `shadow` rollout modes. They are not the authoritative path once `NOTIFICATION_MODE=outbox`.
