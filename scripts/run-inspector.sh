#!/usr/bin/env bash
# Launch MCP Inspector against the running server.
#
# Usage:
#   scripts/run-inspector.sh [streamable-http|sse|stdio]
#
# Defaults to streamable-http on http://localhost:8000/mcp.
# stdio mode proxies through `docker exec` into the running container.

set -euo pipefail

MODE="${1:-streamable-http}"
HOST_URL="${MCP_HOST_URL:-http://localhost:8000}"

case "$MODE" in
  streamable-http)
    npx -y @modelcontextprotocol/inspector@latest \
      --transport streamable-http \
      --server-url "${HOST_URL}/mcp"
    ;;
  sse)
    # SSE transport requires the server to be started with `-t sse`.
    npx -y @modelcontextprotocol/inspector@latest \
      --transport sse \
      --server-url "${HOST_URL}/sse"
    ;;
  stdio)
    # Proxy stdio through the running container's binary.
    npx -y @modelcontextprotocol/inspector@latest \
      docker exec -i grafana-mcp /app/mcp-grafana -t stdio
    ;;
  *)
    echo "unknown mode: $MODE  (expected: streamable-http | sse | stdio)" >&2
    exit 2
    ;;
esac
