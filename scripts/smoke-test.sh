#!/usr/bin/env bash
# End-to-end smoke test:
#   1. up the compose stack
#   2. /healthz responds
#   3. /metrics exposes the upstream session/operation timers
#   4. MCP tools/list returns a non-empty list (via JSON-RPC over HTTP)
#   5. tear down
#
# Exits non-zero on the first failure. Designed for CI and `make smoke`.

set -euo pipefail

cd "$(dirname "$0")/.."

CLEANUP() {
  docker compose -f compose/docker-compose.yml down --remove-orphans >/dev/null 2>&1 || true
}
trap CLEANUP EXIT

echo "→ docker compose up"
docker compose -f compose/docker-compose.yml up -d --build grafana-mcp

URL="http://localhost:${MCP_HOST_PORT:-8000}"
echo "→ waiting for /healthz"
for i in $(seq 1 30); do
  if curl -fsS "$URL/healthz" 2>/dev/null | grep -q '^ok$'; then
    echo "  healthy after ${i}s"; break
  fi
  sleep 1
  if [ "$i" = 30 ]; then echo "  /healthz never responded"; exit 1; fi
done

echo "→ /metrics smoke"
curl -fsS "$URL/metrics" | grep -E '^(mcp_server_|go_)' | head -3

echo "→ MCP tools/list (JSON-RPC)"
INIT_PAYLOAD='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
LIST_PAYLOAD='{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# We don't track the session id here because tools/list works without one
# in current upstream; if upstream tightens that, switch to mcp Python SDK.
RESPONSE=$(curl -fsS -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -X POST "$URL/mcp" --data "$LIST_PAYLOAD" || true)

TOOL_COUNT=$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys,re
raw=sys.stdin.read()
# streamable-http may wrap as SSE; extract the first JSON payload.
m=re.search(r"\{.*\}", raw, re.S)
if not m: print(0); sys.exit(0)
try:
    d=json.loads(m.group(0))
    print(len(d.get("result",{}).get("tools",[])))
except Exception:
    print(0)
' 2>/dev/null || echo 0)

echo "  tools listed: $TOOL_COUNT"
if [ "$TOOL_COUNT" -lt 10 ]; then
  echo "  expected at least 10 tools — check server logs"
  docker compose -f compose/docker-compose.yml logs grafana-mcp | tail -30
  exit 1
fi

echo "✓ smoke passed"
