#!/usr/bin/env bash
# Seed a local Grafana with a service account, a Prometheus datasource, and
# a sample dashboard. Writes the minted token into ../.env so the MCP
# container picks it up on the next restart.
#
# Idempotent: re-running deletes the prior service account and dashboard.
# Requires only `curl` and `python3` (no `jq`), so it runs anywhere.

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL_HOST:-http://localhost:13000}"
ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
ADMIN_PASS="${GRAFANA_ADMIN_PASS:-admin}"
SA_NAME="${SEED_SA_NAME:-grafana-mcp-tests}"
DS_NAME="${SEED_PROM_NAME:-prometheus-self}"
PROM_URL_INTERNAL="${PROM_URL_INTERNAL:-http://prometheus:9090}"
ENV_FILE="${ENV_FILE:-$(cd "$(dirname "$0")/../.." && pwd)/.env}"

curl_admin() { curl -fsS -u "${ADMIN_USER}:${ADMIN_PASS}" "$@"; }

# Tiny JSON helper — `python3 -c "import sys,json;print(json.load(sys.stdin)$1)"`.
jget() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

echo "→ waiting for Grafana at ${GRAFANA_URL}"
for _ in $(seq 1 30); do
  if curl -fsS "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "→ removing any prior test service account"
EXISTING=$(curl_admin "${GRAFANA_URL}/api/serviceaccounts/search?query=${SA_NAME}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(str(s['id']) for s in d.get('serviceAccounts',[]) if s.get('name')=='${SA_NAME}'))" || true)
for id in $EXISTING; do
  curl_admin -X DELETE "${GRAFANA_URL}/api/serviceaccounts/${id}" >/dev/null || true
done

echo "→ creating service account"
SA_ID=$(curl_admin -H 'Content-Type: application/json' \
  -d "{\"name\":\"${SA_NAME}\",\"role\":\"Admin\"}" \
  "${GRAFANA_URL}/api/serviceaccounts" | jget '["id"]')

echo "→ minting token"
TOKEN=$(curl_admin -H 'Content-Type: application/json' \
  -d "{\"name\":\"${SA_NAME}-token\"}" \
  "${GRAFANA_URL}/api/serviceaccounts/${SA_ID}/tokens" | jget '["key"]')

echo "→ creating Prometheus datasource (idempotent)"
curl_admin -X DELETE "${GRAFANA_URL}/api/datasources/name/${DS_NAME}" >/dev/null || true
curl_admin -H 'Content-Type: application/json' -d "{
  \"name\":\"${DS_NAME}\",
  \"type\":\"prometheus\",
  \"url\":\"${PROM_URL_INTERNAL}\",
  \"access\":\"proxy\",
  \"isDefault\":true
}" "${GRAFANA_URL}/api/datasources" >/dev/null || true

echo "→ creating sample dashboard"
DASH_PAYLOAD=$(python3 -c '
import json
print(json.dumps({
  "dashboard": {
    "uid": "grafana-mcp-test",
    "title": "grafana-mcp test dashboard",
    "panels": [{"id":1,"type":"timeseries","title":"up",
                "targets":[{"expr":"up","refId":"A"}]}],
    "schemaVersion": 38,
    "version": 0,
  },
  "overwrite": True,
}))')
curl_admin -H 'Content-Type: application/json' -d "${DASH_PAYLOAD}" "${GRAFANA_URL}/api/dashboards/db" >/dev/null

echo "→ writing token to ${ENV_FILE}"
[ -f "${ENV_FILE}" ] || cp "$(dirname "${ENV_FILE}")/.env.example" "${ENV_FILE}"
if grep -q '^GRAFANA_SERVICE_ACCOUNT_TOKEN=' "${ENV_FILE}"; then
  sed -i.bak "s|^GRAFANA_SERVICE_ACCOUNT_TOKEN=.*|GRAFANA_SERVICE_ACCOUNT_TOKEN=${TOKEN}|" "${ENV_FILE}"
else
  printf '\nGRAFANA_SERVICE_ACCOUNT_TOKEN=%s\n' "${TOKEN}" >> "${ENV_FILE}"
fi
rm -f "${ENV_FILE}.bak"

# Ensure the MCP container reaches the in-network Grafana.
if grep -q '^GRAFANA_URL=' "${ENV_FILE}"; then
  sed -i.bak "s|^GRAFANA_URL=.*|GRAFANA_URL=http://grafana:3000|" "${ENV_FILE}"
  rm -f "${ENV_FILE}.bak"
fi

echo "→ bouncing MCP so it picks up the new token"
docker compose -f "$(cd "$(dirname "$0")/../.." && pwd)/compose/docker-compose.yml" \
  up -d --force-recreate grafana-mcp >/dev/null

echo "✓ seed complete (token written, dashboard uid=grafana-mcp-test)"
