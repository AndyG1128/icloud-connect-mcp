#!/bin/sh
set -eu
unset CONTROL_PLANE_API_KEY OPENAI_API_KEY
connector_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$connector_root"
export ICLOUD_MCP_CONFIG="${ICLOUD_MCP_CONFIG:-$connector_root/.config/config.toml}"
exec "$connector_root/.venv/bin/icloud-mcp"
