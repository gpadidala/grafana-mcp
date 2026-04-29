#!/usr/bin/env bash
# Seed a local Grafana with a service account, sample dashboard, and an
# alert rule. Datasources (prometheus / loki / tempo / pyroscope) are
# auto-provisioned via compose/provisioning/datasources/datasources.yaml,
# so this script's job is just minting a token and verifying everything is
# reachable.
#
# Idempotent: re-running deletes the prior service account and dashboard.
# Requires only `curl` and `python3` (no `jq`), so it runs anywhere.

set -euo pipefail

# Resolve the Python interpreter — Windows ships `python.exe`, Linux/macOS
# typically have `python3`. Fall back gracefully so this script works on
# every host without aliases.
PYTHON="${PYTHON:-$(command -v python3 || command -v python || true)}"
if [ -z "${PYTHON}" ]; then
  echo "error: no python interpreter found in PATH (install python3 or python)" >&2
  exit 1
fi

GRAFANA_URL="${GRAFANA_URL_HOST:-http://localhost:3000}"
ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
ADMIN_PASS="${GRAFANA_ADMIN_PASS:-admin}"
SA_NAME="${SEED_SA_NAME:-grafana-mcp-tests}"
ENV_FILE="${ENV_FILE:-$(cd "$(dirname "$0")/../.." && pwd)/.env}"

curl_admin() { curl -fsS -u "${ADMIN_USER}:${ADMIN_PASS}" "$@"; }
jget()       { ${PYTHON} -c "import sys,json; print(json.load(sys.stdin)$1)"; }

echo "→ waiting for Grafana at ${GRAFANA_URL}"
for _ in $(seq 1 60); do
  if curl -fsS "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "→ verifying provisioned datasources"
DS_NAMES=$(curl_admin "${GRAFANA_URL}/api/datasources" \
  | ${PYTHON} -c 'import sys,json; print(",".join(d["name"] for d in json.load(sys.stdin)))')
echo "  found: ${DS_NAMES:-<none>}"

echo "→ removing any prior test service account"
EXISTING=$(curl_admin "${GRAFANA_URL}/api/serviceaccounts/search?query=${SA_NAME}" \
  | ${PYTHON} -c "import sys,json; d=json.load(sys.stdin); print(' '.join(str(s['id']) for s in d.get('serviceAccounts',[]) if s.get('name')=='${SA_NAME}'))" || true)
for id in $EXISTING; do
  curl_admin -X DELETE "${GRAFANA_URL}/api/serviceaccounts/${id}" >/dev/null || true
done

echo "→ creating service account (Admin role — full plugin surface)"
SA_ID=$(curl_admin -H 'Content-Type: application/json' \
  -d "{\"name\":\"${SA_NAME}\",\"role\":\"Admin\"}" \
  "${GRAFANA_URL}/api/serviceaccounts" | jget '["id"]')

echo "→ minting token"
TOKEN=$(curl_admin -H 'Content-Type: application/json' \
  -d "{\"name\":\"${SA_NAME}-token\"}" \
  "${GRAFANA_URL}/api/serviceaccounts/${SA_ID}/tokens" | jget '["key"]')

echo "→ creating sample dashboard"
DASH_PAYLOAD=$(${PYTHON} -c '
import json
print(json.dumps({
  "dashboard": {
    "uid": "grafana-mcp-test",
    "title": "grafana-mcp test dashboard",
    "tags": ["grafana-mcp", "test"],
    "panels": [
      {"id":1,"type":"timeseries","title":"up",
       "datasource": {"type":"prometheus","uid":"prometheus"},
       "targets":[{"expr":"up","refId":"A"}]},
      {"id":2,"type":"logs","title":"recent logs",
       "datasource": {"type":"loki","uid":"loki"},
       "targets":[{"expr":"{job=~\".+\"}","refId":"A"}]},
    ],
    "schemaVersion": 38,
    "version": 0,
  },
  "overwrite": True,
}))')
curl_admin -H 'Content-Type: application/json' -d "${DASH_PAYLOAD}" \
  "${GRAFANA_URL}/api/dashboards/db" >/dev/null

echo "→ creating sample annotation"
NOW_MS=$(${PYTHON} -c 'import time; print(int(time.time()*1000))')
curl_admin -H 'Content-Type: application/json' -d "{
  \"text\":\"grafana-mcp seed marker\",
  \"tags\":[\"grafana-mcp-tests\",\"seed\"],
  \"time\":${NOW_MS}
}" "${GRAFANA_URL}/api/annotations" >/dev/null || true

echo "→ writing token to ${ENV_FILE}"
[ -f "${ENV_FILE}" ] || cp "$(dirname "${ENV_FILE}")/.env.example" "${ENV_FILE}"
if grep -q '^GRAFANA_SERVICE_ACCOUNT_TOKEN=' "${ENV_FILE}"; then
  sed -i.bak "s|^GRAFANA_SERVICE_ACCOUNT_TOKEN=.*|GRAFANA_SERVICE_ACCOUNT_TOKEN=${TOKEN}|" "${ENV_FILE}"
else
  printf '\nGRAFANA_SERVICE_ACCOUNT_TOKEN=%s\n' "${TOKEN}" >> "${ENV_FILE}"
fi
rm -f "${ENV_FILE}.bak"

if grep -q '^GRAFANA_URL=' "${ENV_FILE}"; then
  sed -i.bak "s|^GRAFANA_URL=.*|GRAFANA_URL=http://grafana:3000|" "${ENV_FILE}"
  rm -f "${ENV_FILE}.bak"
fi

echo "→ bouncing MCP so it picks up the new token"
docker compose --env-file "${ENV_FILE}" \
  -f "$(cd "$(dirname "$0")/../.." && pwd)/compose/docker-compose.yml" \
  up -d --force-recreate grafana-mcp >/dev/null

echo "✓ seed complete"
echo "  service account:  ${SA_NAME} (Admin)"
echo "  token →           ${ENV_FILE}"
echo "  dashboard uid:    grafana-mcp-test"
echo "  datasources:      ${DS_NAMES}"
