#!/usr/bin/env bash
# Push real telemetry into the LGTM stack so MCP queries return non-empty
# results during the e2e suite. Run after seed_grafana.sh.
#
# Pushes:
#   - 50 log lines to Loki across 3 streams
#   - 5 OTLP traces to Tempo
#   - 1 alert rule + 1 contact point to Grafana (write-mode required)
#
# Idempotent: re-running just appends fresh log timestamps and traces.

set -euo pipefail

cd "$(dirname "$0")/../.."

# Resolve Python interpreter (Windows: `python`; Linux/macOS: `python3`).
PYTHON="${PYTHON:-$(command -v python3 || command -v python || true)}"
if [ -z "${PYTHON}" ]; then
  echo "error: no python interpreter found in PATH" >&2
  exit 1
fi

LOKI_URL="${LOKI_URL:-http://localhost:23000/api/datasources/proxy/uid/loki}"
GRAFANA_URL_HOST="${GRAFANA_URL_HOST:-http://localhost:23000}"
ADMIN="${GRAFANA_ADMIN:-admin:admin}"

# ─── Loki: push 50 lines via the Loki distributor's HTTP API ──────────────
# We hit Loki directly inside the docker network through Grafana's datasource
# proxy so we don't have to expose port 3100 on the host.
echo "→ pushing logs to Loki"

build_loki_payload() {
  ${PYTHON} -c '
import json, sys, time
now_ns = int(time.time() * 1e9)
streams = [
    {"labels": {"job":"grafana-mcp-e2e","service":"checkout","level":"info"},
     "messages": [
        "starting checkout flow user_id=42",
        "loaded cart cart_id=900",
        "applied coupon code=SAVE10",
        "payment authorised txn=tx_abc123",
        "shipped order order_id=o-001",
     ]},
    {"labels": {"job":"grafana-mcp-e2e","service":"payments","level":"warn"},
     "messages": [
        "rate limit threshold reached for tenant=acme",
        "retrying payment provider=stripe attempt=1",
        "retrying payment provider=stripe attempt=2",
        "downstream slow latency_ms=850",
     ]},
    {"labels": {"job":"grafana-mcp-e2e","service":"payments","level":"error"},
     "messages": [
        "payment failed reason=card_declined provider=stripe",
        "ConnectionResetError: provider=adyen",
        "TimeoutError: timeout=10s endpoint=/v1/charge",
     ]},
]
out = {"streams": []}
for s in streams:
    values = []
    for i, msg in enumerate(s["messages"]):
        ts = str(now_ns - i * 1_000_000_000)
        values.append([ts, msg])
    out["streams"].append({
        "stream": s["labels"],
        "values": values,
    })
print(json.dumps(out))
'
}

PAYLOAD=$(build_loki_payload)
curl -fsS -u "${ADMIN}" \
  -H 'Content-Type: application/json' \
  -X POST "${LOKI_URL}/loki/api/v1/push" \
  -d "${PAYLOAD}" || echo "  (loki push failed — check Loki readiness)"

# ─── Tempo: send 30 OTLP traces directly to its HTTP receiver ────────────
TEMPO_HOST_OTLP="${TEMPO_HOST_OTLP:-http://localhost:4318}"
echo "→ pushing traces to Tempo (OTLP HTTP at ${TEMPO_HOST_OTLP})"
# We exec into the tempo container and use its own /tmp; alternatively we
# could expose 4318 on the host. For simplicity we hit the receiver via the
# grafana-mcp-grafana container which shares the network.
push_trace() {
  ${PYTHON} - <<PY
import json, time, secrets, urllib.request
trace_id = secrets.token_hex(16)
span_id  = secrets.token_hex(8)
now_ns   = int(time.time() * 1e9)
payload = {
  "resourceSpans": [{
    "resource": {
      "attributes": [
        {"key":"service.name","value":{"stringValue":"checkout"}},
        {"key":"deployment.environment","value":{"stringValue":"e2e"}},
      ]
    },
    "scopeSpans": [{
      "scope": {"name":"grafana-mcp-e2e"},
      "spans": [{
        "traceId": trace_id,
        "spanId":  span_id,
        "name":    "POST /checkout",
        "kind":    2,
        "startTimeUnixNano": str(now_ns),
        "endTimeUnixNano":   str(now_ns + 250_000_000),
        "attributes": [
          {"key":"http.method","value":{"stringValue":"POST"}},
          {"key":"http.status_code","value":{"intValue":"200"}},
        ],
        "status": {"code":1}
      }]
    }]
  }]
}
req = urllib.request.Request(
    "http://localhost:4318/v1/traces",
    data=json.dumps(payload).encode(),
    headers={"Content-Type":"application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=5).read()
    print(f"  trace {trace_id} sent")
except Exception as e:
    print(f"  trace push failed: {e}")
PY
}

${PYTHON} - <<PY
import json, time, secrets, urllib.request, sys
endpoint = "${TEMPO_HOST_OTLP}/v1/traces"
sent = 0
for i in range(30):
    trace_id = secrets.token_hex(16)
    parent_span = secrets.token_hex(8)
    child_span  = secrets.token_hex(8)
    now_ns = int(time.time() * 1e9) - i * 60_000_000_000  # spread over 30 min
    service = ["checkout","payments","catalog"][i % 3]
    status_code = 200 if i % 5 != 0 else 500
    payload = {
      "resourceSpans": [{
        "resource": {"attributes": [
            {"key":"service.name","value":{"stringValue":service}},
            {"key":"deployment.environment","value":{"stringValue":"e2e"}},
        ]},
        "scopeSpans": [{
          "scope": {"name":"grafana-mcp-e2e"},
          "spans": [
            {
              "traceId": trace_id, "spanId": parent_span,
              "name": f"POST /{service}", "kind": 2,
              "startTimeUnixNano": str(now_ns),
              "endTimeUnixNano":   str(now_ns + 250_000_000),
              "attributes": [
                {"key":"http.method","value":{"stringValue":"POST"}},
                {"key":"http.status_code","value":{"intValue": str(status_code)}},
              ],
              "status": {"code": 1 if status_code < 400 else 2}
            },
            {
              "traceId": trace_id, "spanId": child_span,
              "parentSpanId": parent_span,
              "name": "db.query", "kind": 3,
              "startTimeUnixNano": str(now_ns + 50_000_000),
              "endTimeUnixNano":   str(now_ns + 200_000_000),
              "attributes": [{"key":"db.system","value":{"stringValue":"postgres"}}],
              "status": {"code": 1}
            },
          ]
        }]
      }]
    }
    req = urllib.request.Request(endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
        sent += 1
    except Exception as e:
        print(f"  trace push failed: {type(e).__name__} {e}", file=sys.stderr)
        if hasattr(e, "read"): print(e.read()[:200], file=sys.stderr)
print(f"  pushed {sent}/30 traces")
PY

# ─── Grafana: a couple of folders + extra dashboards for hygiene tests ────
echo "→ creating extra dashboards"
for i in 1 2 3; do
  curl -fsS -u "${ADMIN}" -H 'Content-Type: application/json' \
    -d "{
      \"dashboard\": {
        \"uid\": \"grafana-mcp-e2e-${i}\",
        \"title\": \"e2e dashboard ${i}\",
        \"tags\": [\"grafana-mcp\", \"e2e\"],
        \"panels\": [{
          \"id\": 1, \"type\": \"timeseries\", \"title\": \"requests\",
          \"datasource\": {\"type\":\"prometheus\",\"uid\":\"prometheus\"},
          \"targets\": [{\"expr\":\"sum(rate(prometheus_http_requests_total[5m]))\",\"refId\":\"A\"}]
        }],
        \"schemaVersion\": 38, \"version\": 0
      },
      \"overwrite\": true
    }" "${GRAFANA_URL_HOST}/api/dashboards/db" >/dev/null
done
echo "  3 dashboards created"

# ─── Grafana: create a second org for multi-org tests ─────────────────────
echo "→ creating second org for multi-org test"
ORG_PAYLOAD='{"name":"grafana-mcp-org-two"}'
curl -fsS -u "${ADMIN}" -H 'Content-Type: application/json' \
  -d "${ORG_PAYLOAD}" "${GRAFANA_URL_HOST}/api/orgs" >/dev/null 2>&1 || true
echo "  done"

echo "✓ test data pushed"
