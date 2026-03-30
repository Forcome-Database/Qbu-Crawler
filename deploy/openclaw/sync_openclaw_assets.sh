#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$STATE_DIR/openclaw.json}"
TEMPLATE_PATH="$REPO_ROOT/deploy/openclaw/openclaw.json5.template"
WORKSPACE_SRC="$REPO_ROOT/qbu_crawler/server/openclaw/workspace"
PLUGIN_SRC="$REPO_ROOT/qbu_crawler/server/openclaw/plugin"
MAIN_WORKSPACE="$STATE_DIR/workspace"
OPS_WORKSPACE="$STATE_DIR/workspace-ops"

: "${QBU_OPENCLAW_MCP_ENDPOINT:?set QBU_OPENCLAW_MCP_ENDPOINT}"
: "${QBU_OPENCLAW_HOOK_TOKEN:?set QBU_OPENCLAW_HOOK_TOKEN}"
: "${QBU_OPENCLAW_MODEL_PRIMARY:?set QBU_OPENCLAW_MODEL_PRIMARY}"

MODEL_FALLBACKS_JSON="${QBU_OPENCLAW_MODEL_FALLBACKS_JSON:-[]}"

mkdir -p "$STATE_DIR" "$MAIN_WORKSPACE" "$OPS_WORKSPACE" "$STATE_DIR/extensions/mcp-products"

python - <<'PY' "$TEMPLATE_PATH" "$CONFIG_PATH" "$QBU_OPENCLAW_MCP_ENDPOINT" "$QBU_OPENCLAW_HOOK_TOKEN" "$QBU_OPENCLAW_MODEL_PRIMARY" "$MODEL_FALLBACKS_JSON"
import pathlib
import sys

template_path, config_path, endpoint, hook_token, model_primary, model_fallbacks = sys.argv[1:]
text = pathlib.Path(template_path).read_text(encoding="utf-8")
text = text.replace("__MCP_ENDPOINT__", endpoint)
text = text.replace("__HOOK_TOKEN__", hook_token)
text = text.replace("__MODEL_PRIMARY__", model_primary)
text = text.replace("__MODEL_FALLBACKS_JSON__", model_fallbacks)
pathlib.Path(config_path).write_text(text, encoding="utf-8")
PY

rsync -a --delete "$PLUGIN_SRC/" "$STATE_DIR/extensions/mcp-products/"
rsync -a --delete \
  --exclude "data/" \
  --exclude "state/" \
  --exclude "reports/" \
  "$WORKSPACE_SRC/" "$MAIN_WORKSPACE/"
rsync -a --delete \
  --exclude "data/" \
  --exclude "state/" \
  --exclude "reports/" \
  "$WORKSPACE_SRC/" "$OPS_WORKSPACE/"

mkdir -p "$MAIN_WORKSPACE/state" "$OPS_WORKSPACE/state"
mkdir -p "$MAIN_WORKSPACE/data" "$OPS_WORKSPACE/data" "$MAIN_WORKSPACE/reports" "$OPS_WORKSPACE/reports"
[[ -f "$MAIN_WORKSPACE/state/active-tasks.json" ]] || printf '{}\n' > "$MAIN_WORKSPACE/state/active-tasks.json"
[[ -f "$OPS_WORKSPACE/state/active-tasks.json" ]] || printf '{}\n' > "$OPS_WORKSPACE/state/active-tasks.json"

python - <<'PY' "$STATE_DIR" > "$STATE_DIR/qbu-openclaw-assets.sha256"
import hashlib
import pathlib
import sys

state_dir = pathlib.Path(sys.argv[1])
paths = []
for root in (state_dir / "workspace", state_dir / "workspace-ops", state_dir / "extensions" / "mcp-products", state_dir / "openclaw.json"):
    if root.is_file():
        paths.append(root)
    elif root.exists():
        paths.extend(sorted(p for p in root.rglob("*") if p.is_file()))

for path in paths:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"{digest}  {path}")
PY

openclaw gateway restart
openclaw status
openclaw doctor
