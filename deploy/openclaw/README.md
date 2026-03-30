# OpenClaw Host Deployment

This directory holds versioned OpenClaw host assets:

- `openclaw.json5.template`
- workspace files
- MCP bridge service
- sync script

## Required Environment Variables

For `sync_openclaw_assets.sh`:

- `QBU_OPENCLAW_MCP_ENDPOINT`
- `QBU_OPENCLAW_HOOK_TOKEN`
- `QBU_OPENCLAW_MODEL_PRIMARY`
- `QBU_OPENCLAW_MODEL_FALLBACKS_JSON`

For the notify bridge service:

- `QBU_OPENCLAW_BRIDGE_TOKEN`
- `QBU_OPENCLAW_BRIDGE_ALLOWED_SOURCES`
- `QBU_OPENCLAW_BRIDGE_ALLOWED_TARGETS`
- `QBU_OPENCLAW_BRIDGE_HOST`
- `QBU_OPENCLAW_BRIDGE_PORT`
- `OPENCLAW_MESSAGE_COMMAND`

## Deploy

1. Clone or update this repo on the OpenClaw host.
2. Export the required environment variables.
3. Run `deploy/openclaw/sync_openclaw_assets.sh`.
4. Install `deploy/openclaw/systemd/qbu-openclaw-notify-bridge.service`.
5. Restart and verify:
   `openclaw status`
   `openclaw doctor`
   `systemctl status qbu-openclaw-notify-bridge`

## Drift Check

- `~/.openclaw/openclaw.json` should match the rendered template.
- `~/.openclaw/qbu-openclaw-assets.sha256` should be refreshed by each sync.
- `heartbeat.target` must remain `none`.
- `hooks.allowedAgentIds` must remain limited to `ops`.

## Rollback

1. Set feature flags back to `legacy`.
2. Restore the previous `openclaw.json`.
3. Restart the OpenClaw gateway.
4. Disable the bridge service if it was introduced only for the new path.
