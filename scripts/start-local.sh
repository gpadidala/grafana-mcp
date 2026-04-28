#!/usr/bin/env bash
# Bring up the local stack. By default: only the MCP server.
# Pass `--full` to also start Grafana + Inspector.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "warning: .env missing — copying .env.example. Edit it before running queries." >&2
  cp .env.example .env
fi

PROFILES=()
if [[ "${1:-}" == "--full" ]]; then
  PROFILES+=(--profile local-grafana --profile inspector)
fi

docker compose -f compose/docker-compose.yml "${PROFILES[@]}" up -d
docker compose -f compose/docker-compose.yml ps
echo
echo "MCP server:    http://localhost:${MCP_HOST_PORT:-8000}/healthz"
echo "MCP endpoint:  http://localhost:${MCP_HOST_PORT:-8000}/mcp"
if [[ "${1:-}" == "--full" ]]; then
  echo "Grafana:       http://localhost:${GRAFANA_HOST_PORT:-3000}  (admin/admin)"
  echo "Inspector:     http://localhost:${INSPECTOR_HOST_PORT:-6274}"
fi
