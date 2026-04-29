#!/usr/bin/env bash
# Bring up an MCP server pointed at a real (non-local) Grafana.
#
# Usage:
#   scripts/connect-remote.sh --env <name> {up|down|status|logs}
#
# Reads .env.<name> and uses --project-name grafana-mcp-<name> so multiple
# environments can run side-by-side on different host ports.
#
# Examples:
#   scripts/connect-remote.sh --env dev  up
#   scripts/connect-remote.sh --env prod up
#   scripts/connect-remote.sh --env dev  status
#   scripts/connect-remote.sh --env dev  down
#
# Prerequisite: a `.env.<name>` file at the repo root with at minimum
# GRAFANA_URL and GRAFANA_SERVICE_ACCOUNT_TOKEN set. See docs/multi-env.md.

set -euo pipefail

ENV_NAME=""
ACTION=""

while [ $# -gt 0 ]; do
  case "$1" in
    --env)
      ENV_NAME="$2"
      shift 2
      ;;
    up|down|status|logs|restart)
      ACTION="$1"
      shift
      ;;
    -h|--help)
      sed -n '1,/^set -euo pipefail$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$ENV_NAME" ] || [ -z "$ACTION" ]; then
  echo "usage: $0 --env <name> {up|down|status|logs|restart}" >&2
  exit 2
fi

cd "$(dirname "$0")/.."

ENV_FILE=".env.${ENV_NAME}"
PROJECT="grafana-mcp-${ENV_NAME}"
COMPOSE_FILE="compose/docker-compose.yml"

if [ ! -f "$ENV_FILE" ] && [ "$ACTION" = "up" ]; then
  cat <<EOF >&2
error: $ENV_FILE not found.

Create it from the template:
  cp .env.example $ENV_FILE

Then set at least:
  GRAFANA_URL=https://grafana.${ENV_NAME}.example.com
  GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_...
  MCP_HOST_PORT=<unique port>          # e.g. 8001 / 8002 / 8003

See docs/multi-env.md for the full reference.
EOF
  exit 1
fi

compose_cmd() {
  if [ -f "$ENV_FILE" ]; then
    docker compose --env-file "$ENV_FILE" --project-name "$PROJECT" \
      -f "$COMPOSE_FILE" "$@"
  else
    docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE" "$@"
  fi
}

case "$ACTION" in
  up)
    echo "→ bringing up MCP for env=${ENV_NAME} (project=${PROJECT})"
    compose_cmd up -d grafana-mcp
    PORT=$(grep -E '^MCP_HOST_PORT=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
    PORT="${PORT:-8000}"
    echo
    echo "→ verifying /healthz on host port ${PORT}"
    for i in $(seq 1 30); do
      if curl -fsS "http://localhost:${PORT}/healthz" 2>/dev/null | grep -q ok; then
        echo "  healthy after ${i}s"
        break
      fi
      sleep 1
      if [ "$i" = 30 ]; then
        echo "  /healthz never responded — check 'scripts/connect-remote.sh --env ${ENV_NAME} logs'"
        exit 1
      fi
    done
    echo
    echo "→ MCP for ${ENV_NAME} is up:"
    echo "    health:  http://localhost:${PORT}/healthz"
    echo "    metrics: http://localhost:${PORT}/metrics"
    echo "    MCP:     http://localhost:${PORT}/mcp"
    GRAFANA_URL=$(grep -E '^GRAFANA_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
    [ -n "${GRAFANA_URL:-}" ] && echo "    talking to: ${GRAFANA_URL}"
    ;;

  down)
    echo "→ tearing down MCP for env=${ENV_NAME} (project=${PROJECT})"
    compose_cmd down --remove-orphans
    ;;

  restart)
    echo "→ restarting MCP for env=${ENV_NAME}"
    compose_cmd up -d --force-recreate grafana-mcp
    ;;

  status)
    compose_cmd ps
    ;;

  logs)
    compose_cmd logs -f grafana-mcp
    ;;
esac
