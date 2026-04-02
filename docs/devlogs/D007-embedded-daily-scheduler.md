# D007 - Embedded Daily Scheduler

## Background

The original hybrid automation plan moved daily submit onto an external crawler-host scheduler.
In the actual deployment, the operator preferred a single long-running `uvx qbu-crawler serve`
process without an additional OS-level timer to maintain.

## Change

Daily submit is now able to run inside the crawler service itself.

- Added `DailySchedulerWorker` to the crawler runtime.
- The worker starts only when `DAILY_SUBMIT_MODE=embedded`.
- Trigger time is configured through `.env` with `DAILY_SCHEDULER_TIME=HH:MM`.
- The worker reuses `submit_daily_run()` so workflow idempotency remains enforced by
  `trigger_key=daily:<logical_date>`.
- The embedded scheduler uses an in-process submitter instead of loopback HTTP to avoid
  startup races during `serve`.

## Config

New settings:

- `DAILY_SUBMIT_MODE=embedded`
- `DAILY_SCHEDULER_TIME=08:00`
- `DAILY_SCHEDULER_INTERVAL=30`
- `DAILY_SCHEDULER_RETRY_SECONDS=300`

## Operational Notes

- OpenClaw cron can remain enabled during migration because daily workflow creation is idempotent.
- Once embedded scheduling proves stable, the old OpenClaw `daily-scrape` cron should be disabled.
- CSV inputs still need to exist on the crawler host filesystem before `serve` starts.

## Verification

Targeted tests passed:

- `tests/test_runtime.py::test_server_runtime_starts_and_stops_components`
- `tests/test_workflows.py::test_config_embedded_daily_scheduler_settings`
- `tests/test_workflows.py::test_config_rejects_invalid_daily_scheduler_time`
- `tests/test_workflows.py::TestDailyScheduler::test_scheduler_waits_until_schedule_time`
- `tests/test_workflows.py::TestDailyScheduler::test_scheduler_submits_once_after_schedule`
