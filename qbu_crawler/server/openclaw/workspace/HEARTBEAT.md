# Heartbeat Checklist

Heartbeat is inspection-only. Do not submit daily jobs. Do not send must-deliver notifications.

Run these checks in order:

1. `list_workflow_runs(status="needs_attention", limit=10)`
   If any runs need attention, summarize the top blockers.
2. `list_pending_notifications(status="failed", limit=10)`
   If any failed notifications exist, summarize counts and oldest items.
3. `list_pending_notifications(status="deadletter", limit=10)`
   If any deadletters exist, escalate clearly.
4. `get_translate_status()`
   If translation backlog is growing abnormally, mention it.
5. If the user previously asked for proactive monitoring, optionally inspect recent workflow runs and summarize drift or anomalies.

If nothing actionable is found, reply with `HEARTBEAT_OK`.
