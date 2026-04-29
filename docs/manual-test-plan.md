# Manual test plan — grafana-mcp

Hand-off document for QA. Every test case is self-contained: pre-conditions,
steps, expected result, pass/fail. No prior `grafana-mcp` knowledge assumed.

> Companion to the automated suite under `tests/`. Manual cases focus on
> things automation can't easily prove: visual UX, real Grafana data,
> recovery scenarios, and security posture.

## Test environment

| Component | Required version | How to bring up |
|---|---|---|
| Docker / Docker Compose v2 | 24+ | already installed on the QA box |
| Python | 3.12+ | needed only for fixture scripts |
| `curl` | any | shipped on macOS / most Linux |
| MCP Inspector | bundled (Compose `--profile inspector`) | `docker compose ... --profile inspector up -d` |

```bash
# Bring up the full LGTM stack — Grafana 11.6.4 + Prometheus + Loki + Tempo + Pyroscope
git clone git@github.com:gpadidala/grafana-mcp.git
cd grafana-mcp
cp .env.example .env

# Edit .env if your host has port 3000/8000 already taken:
#   GRAFANA_HOST_PORT=23000
#   MCP_HOST_PORT=8000

docker compose --env-file .env -f compose/docker-compose.yml --profile local-grafana up -d
GRAFANA_URL_HOST=http://localhost:23000 ./tests/fixtures/seed_grafana.sh
./tests/fixtures/generate_test_data.sh
```

After all three commands, you should have:

- Grafana at `http://localhost:23000` (admin/admin)
- MCP at `http://localhost:8000`
- 4 datasources auto-provisioned: prometheus, loki, tempo, pyroscope
- 1 service-account token written to `.env` as `GRAFANA_SERVICE_ACCOUNT_TOKEN`
- 4 dashboards (1 from seed + 3 from data-generator)
- 50 log lines in Loki, 30 traces in Tempo

## Test case template

Every TC below uses this shape:

```
TC-<area>-<n>: <one-line title>
Area:           one of: smoke / discovery / datasource / auth / safety /
                multi-org / observability / inspector / k8s / docs
Severity:       blocker / major / minor
Pre-conditions: …
Steps:          …
Expected:       …
Result:         PASS / FAIL / BLOCKED  (filled in by tester)
Notes:          (filled in if FAIL or BLOCKED)
```

---

# 1. Smoke

## TC-smoke-1 — container starts and answers `/healthz`

- **Severity:** blocker
- **Pre-conditions:** clean machine, no `grafana-mcp-*` containers running.
- **Steps:**
  1. `docker compose --env-file .env -f compose/docker-compose.yml up -d grafana-mcp`
  2. Wait 10 s.
  3. `curl -fsS http://localhost:8000/healthz`
- **Expected:** Step 3 prints `ok` and exits 0.

## TC-smoke-2 — `/metrics` exposes Prometheus output

- **Severity:** major
- **Pre-conditions:** TC-smoke-1 passed.
- **Steps:** `curl -fsS http://localhost:8000/metrics | head`
- **Expected:** Output starts with `# HELP go_gc_duration_seconds …`. Contains lines starting with `mcp_` after at least one tools/list call.

## TC-smoke-3 — invalid env var causes startup failure with a clear log

- **Severity:** minor
- **Pre-conditions:** Stack is down.
- **Steps:**
  1. Set `GRAFANA_URL=` (empty) in `.env`.
  2. `docker compose --env-file .env -f compose/docker-compose.yml up grafana-mcp`
  3. Read the container logs.
- **Expected:** Container exits with a non-zero code. Logs say `GRAFANA_URL` is required (or equivalent). No reference to a stack trace pointing at our wrapper code — the error must come from upstream cleanly.

## TC-smoke-4 — `make smoke` runs end-to-end without manual intervention

- **Severity:** major
- **Steps:** Fresh checkout → `cp .env.example .env` → `make smoke`
- **Expected:** Exits 0 and prints `✓ smoke passed`.

---

# 2. Tool discovery

## TC-discovery-1 — full tool surface present

- **Severity:** major
- **Pre-conditions:** Stack up with default `MCP_ENABLED_TOOLS` (full surface).
- **Steps:**
  ```bash
  curl -fsS -X POST http://localhost:8000/mcp \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
  ```
- **Expected:** Response contains ≥ 70 entries. The list includes at least: `search_dashboards`, `list_datasources`, `query_prometheus`, `query_loki_logs`, `list_users`, `query_clickhouse`.

## TC-discovery-2 — narrowed surface honours allowlist

- **Severity:** major
- **Pre-conditions:** Stack down.
- **Steps:**
  1. Set `MCP_ENABLED_TOOLS=search,datasource,prometheus` in `.env`.
  2. Bring stack up.
  3. List tools as in TC-discovery-1.
- **Expected:** Only tools whose names start with `search_`, `list_datasources`, `get_datasource`, `query_prometheus`, `list_prometheus_*` are returned. **No** `query_loki_logs`, `list_users`, etc.

## TC-discovery-3 — every tool ships a JSON Schema

- **Severity:** minor
- **Steps:** From the response of TC-discovery-1, eyeball ten random entries.
- **Expected:** Each has a non-empty `description` and an `inputSchema` with `"type": "object"` and a `properties` map. No tool returns `null` schema.

---

# 3. Datasources

## TC-ds-1 — list_datasources returns all four provisioned

- **Severity:** major
- **Steps:** Call `tools/call` with `name=list_datasources`, no arguments.
- **Expected:** Response includes `prometheus`, `loki`, `tempo`, `pyroscope`. No errors.

## TC-ds-2 — query Prometheus `up` returns at least one series

- **Severity:** major
- **Steps:**
  ```json
  { "name": "query_prometheus",
    "arguments": { "datasourceUid": "prometheus", "expr": "up",
                   "queryType": "instant", "endTime": "now" } }
  ```
- **Expected:** Result contains at least one `metric` with `__name__: "up"`. No `isError`.

## TC-ds-3 — query Loki finds seeded log lines

- **Severity:** major
- **Pre-conditions:** `generate_test_data.sh` has run within the last hour.
- **Steps:**
  ```json
  { "name": "query_loki_logs",
    "arguments": { "datasourceUid": "loki",
                   "logql": "{job=\"grafana-mcp-e2e\"}", "limit": 5 } }
  ```
- **Expected:** Response contains lines such as `card_declined`, `rate limit threshold`, `payment authorised`.

## TC-ds-4 — Tempo search returns ingested traces (visual)

- **Severity:** major
- **Pre-conditions:** Test data pushed; ≥ 35 s elapsed (Tempo flush window).
- **Steps:**
  1. Open `http://localhost:23000` in a browser.
  2. Explore → datasource: `tempo` → query type "Search" → run.
- **Expected:** ≥ 1 trace listed under services `checkout`, `payments`, `catalog`. Click a trace, see ≥ 2 spans (the parent and the `db.query` child).

## TC-ds-5 — Pyroscope datasource healthy

- **Severity:** minor
- **Steps:**
  ```json
  { "name": "list_pyroscope_profile_types",
    "arguments": { "data_source_uid": "pyroscope" } }
  ```
- **Expected:** Returns a list (may be empty if no profiles ingested yet). No 500/`isError`.

## TC-ds-6 — get_datasource by uid AND by name

- **Severity:** minor
- **Steps:**
  - `get_datasource` with `{ "uid": "prometheus" }`
  - `get_datasource` with `{ "name": "prometheus" }`
- **Expected:** Both return the same datasource object.

---

# 4. Dashboards

## TC-dash-1 — search_dashboards finds seeded dashboards

- **Severity:** major
- **Steps:** Call `search_dashboards` with `query: "e2e"`.
- **Expected:** Returns ≥ 3 entries titled `e2e dashboard 1/2/3`.

## TC-dash-2 — get_dashboard_property with JSONPath

- **Severity:** minor
- **Steps:**
  ```json
  { "name": "get_dashboard_property",
    "arguments": { "uid": "grafana-mcp-test", "jsonPath": "$.title" } }
  ```
- **Expected:** Returns the string `grafana-mcp test dashboard`.

## TC-dash-3 — write tools refused under `--disable-write`

- **Severity:** **blocker**
- **Pre-conditions:** Set `MCP_DISABLE_WRITE=true` in `.env`. Bounce MCP.
- **Steps:**
  1. Verify `mcp_method_name` `create_annotation` is **absent** from `tools/list` (per TC-discovery rules).
  2. Force a call:
     ```json
     { "name": "create_annotation",
       "arguments": { "text": "test", "tags": ["x"] } }
     ```
- **Expected:** Response either:
  - has `isError: true`, or
  - returns `tool not found` (because the tool was filtered).
  Either is acceptable. **The annotation must NOT be created.** Verify by listing annotations afterwards.

---

# 5. Alerting

## TC-alert-1 — list_alert_groups callable, no error when alerting empty

- **Severity:** minor
- **Steps:** Call `list_alert_groups`, no arguments.
- **Expected:** Returns a list (may be empty). No `isError`.

## TC-alert-2 — list_contact_points / alerting_manage_routing returns something

- **Severity:** minor
- **Steps:** If `list_contact_points` exists, call it. Else call `alerting_manage_routing` with `{"action": "list"}`.
- **Expected:** Returns at minimum the default `email` contact point seeded by Grafana.

---

# 6. Auth & token rotation

## TC-auth-1 — wrong token surfaces clear 401 path

- **Severity:** major
- **Pre-conditions:** Stack up.
- **Steps:**
  1. Set `GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_garbage` in `.env`.
  2. Bounce MCP: `docker compose --env-file .env … up -d --force-recreate grafana-mcp`.
  3. Call `list_datasources` via Inspector or curl.
- **Expected:** Response is a tool error (`isError: true`) with text mentioning 401/Unauthorized. The container does **not** crash.

## TC-auth-2 — token rotation without restart (Compose)

- **Severity:** major
- **Steps:**
  1. Note the current token.
  2. In Grafana UI, mint a fresh token under the same service account.
  3. Update `.env`, bounce MCP.
  4. Run `query_prometheus(up)` — must succeed.
  5. Revoke the old token in Grafana UI.
  6. Run `query_prometheus(up)` again — must still succeed (proving the new token took effect).
- **Expected:** Steps 4 and 6 both return data.

## TC-auth-3 — service-account scope: read-only token cannot write

- **Severity:** major
- **Steps:**
  1. Mint a Viewer-role service account + token.
  2. Replace the token in `.env`, bounce MCP, leave `MCP_DISABLE_WRITE=false` so writes are *attempted*.
  3. Try `create_annotation`.
- **Expected:** Returns 403 / Forbidden surfaced as `isError: true`. Container does not crash. No annotation created (verify via Grafana UI).

---

# 7. Multi-org / header forwarding

## TC-multi-1 — header forwarding allowlist accepts X-Grafana-Org-Id

- **Severity:** major
- **Pre-conditions:** `GRAFANA_FORWARD_HEADERS=X-Grafana-Org-Id` (default in compose). A second org exists (created by `generate_test_data.sh`).
- **Steps:**
  ```bash
  curl -fsS -X POST http://localhost:8000/mcp \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'X-Grafana-Org-Id: 1' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
         "params":{"name":"list_datasources","arguments":{}}}'
  ```
- **Expected:** 200 OK, datasource list returned, no error.

## TC-multi-2 — header forwarding refuses unlisted headers

- **Severity:** minor
- **Pre-conditions:** Set `GRAFANA_FORWARD_HEADERS=` (empty) in `.env`, bounce MCP.
- **Steps:** Repeat TC-multi-1 with the same `X-Grafana-Org-Id` header.
- **Expected:** Call still succeeds, but the response is from org 1 (the default). MCP did **not** forward the header. Verify by checking Grafana audit logs / by adding a query that only returns data in org 2.

---

# 8. Observability

## TC-obs-1 — `/metrics` exposes mcp_*** metrics after first call

- **Severity:** major
- **Steps:**
  1. Restart MCP.
  2. `curl /metrics | grep '^mcp_'` — should return nothing (or only the gauge `mcp_sessions_active 0`).
  3. Run any tool call.
  4. Re-run `curl /metrics | grep '^mcp_'`.
- **Expected:** After step 3, output includes `mcp_server_operation_duration_seconds_*`, `mcp_server_session_duration_seconds_*`, `mcp_client_cache_*`.

## TC-obs-2 — import all 5 dashboards

- **Severity:** minor
- **Pre-conditions:** Local Grafana up; Prometheus configured to scrape the local MCP at `grafana-mcp:8000`.
- **Steps:**
  1. Open Grafana → Dashboards → Import → upload each JSON from `docs/dashboards/`.
  2. After 1–2 minutes of activity (run a few MCP tools), check each dashboard.
- **Expected:** Every dashboard renders without "No data" on the headline panels (Pods up, Active sessions, RPS, p95). Variable dropdowns (`namespace`, `method`) populate.

## TC-obs-3 — alerts fire under simulated latency

- **Severity:** minor (informational)
- **Pre-conditions:** Run in a real K8s cluster with kube-prometheus-stack.
- **Steps:**
  1. Apply `k8s/base/prometheusrule.yaml`.
  2. Use `kubectl exec` + `tc qdisc` (or comparable) to add 6 s latency to outbound MCP→Grafana traffic.
  3. Wait 10 minutes.
- **Expected:** `GrafanaMcpUpstreamGrafanaSlow` and `GrafanaMcpHighOperationLatencyP95` both fire. Alertmanager receives them with the runbook URL.

## TC-obs-4 — OpenTelemetry traces reach an OTLP collector

- **Severity:** minor
- **Steps:**
  1. Start a local OTLP collector (e.g. `otel/opentelemetry-collector` debug exporter).
  2. Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` in `.env`.
  3. Run a few MCP tool calls.
- **Expected:** Collector logs show spans with `service.name=mcp-grafana`.

---

# 9. MCP Inspector (visual)

## TC-insp-1 — Inspector connects via streamable-http

- **Severity:** major
- **Steps:**
  1. `docker compose --env-file .env -f compose/docker-compose.yml --profile inspector up -d`
  2. Open `http://localhost:6274` in a browser.
- **Expected:** Inspector UI loads. The "Connection" indicator is green. The "Tools" tab lists ≥ 70 entries.

## TC-insp-2 — Inspector calls a tool successfully

- **Severity:** major
- **Steps:** In the Inspector → Tools → `list_datasources` → Run.
- **Expected:** Right pane shows a JSON array containing all four datasources. No red error banner.

## TC-insp-3 — Inspector schema browser

- **Severity:** minor
- **Steps:** Click `query_prometheus` in the tools list.
- **Expected:** The argument form shows fields for `datasourceUid`, `expr`, `queryType`, `endTime`, `startTime`, `stepSeconds`. Required fields are visually marked.

---

# 10. Failure recovery

## TC-recover-1 — MCP survives Grafana restart

- **Severity:** major
- **Steps:**
  1. With everything healthy, stop Grafana: `docker compose stop grafana`.
  2. Run `query_prometheus(up)` against MCP — expect a tool error.
  3. Start Grafana again: `docker compose start grafana`.
  4. Wait 30 s.
  5. Run `query_prometheus(up)` again.
- **Expected:** Step 2 returns `isError: true` with a connection-refused / DNS-related message. Step 5 returns data. MCP container is **never** restarted.

## TC-recover-2 — MCP survives idle session reaping

- **Severity:** minor
- **Pre-conditions:** `MCP_SESSION_IDLE_TIMEOUT_MINUTES=1` for the test.
- **Steps:**
  1. Open an MCP session via Inspector.
  2. Wait ~ 90 s without making any calls.
  3. Try a tool call from the same session.
- **Expected:** Session is reaped after ~ 60 s; the new call either re-initializes seamlessly or returns a clean "session expired" error. No 500.

---

# 11. Resource sanity

## TC-res-1 — container respects 512Mi limit

- **Severity:** minor
- **Steps:**
  1. Run a 30-min sustained load: 10 sessions in parallel, each calling `query_prometheus(up)` every second.
  2. Observe `docker stats grafana-mcp` and `/metrics` `process_resident_memory_bytes`.
- **Expected:** RSS stays below 400 MiB. No OOMKill events.

## TC-res-2 — clean shutdown

- **Severity:** minor
- **Steps:** `docker compose stop grafana-mcp` while a session is open.
- **Expected:** Container exits within 10 s. Logs include a graceful shutdown message. No active connections leaked (verify with `lsof -iTCP:8000` afterwards).

---

# 12. Documentation sanity

## TC-doc-1 — README quickstart works on a clean machine

- **Severity:** major
- **Steps:** Follow `README.md` "Quick start (5 minutes)" verbatim on a machine with only Docker installed.
- **Expected:** All commands succeed in order. `/healthz` returns `ok` at the end.

## TC-doc-2 — runbook entries are reachable from alerts

- **Severity:** minor
- **Steps:** Open `k8s/base/prometheusrule.yaml`, follow each `runbook_url`.
- **Expected:** Every URL resolves to a real anchor in `docs/runbook.md`.

## TC-doc-3 — no broken internal links

- **Severity:** minor
- **Steps:** Run any markdown link checker on the repo (or eyeball every `*.md` link).
- **Expected:** Zero broken links.

---

# Sign-off matrix

Tester completes:

| Section | Passed | Failed | Blocked |
|---|---:|---:|---:|
| Smoke | / 4 | | |
| Tool discovery | / 3 | | |
| Datasources | / 6 | | |
| Dashboards | / 3 | | |
| Alerting | / 2 | | |
| Auth & token rotation | / 3 | | |
| Multi-org | / 2 | | |
| Observability | / 4 | | |
| Inspector | / 3 | | |
| Recovery | / 2 | | |
| Resource | / 2 | | |
| Documentation | / 3 | | |
| **Total** | **/ 37** | | |

**Release decision rules:**
- Any **blocker** failed → release blocked.
- Two or more **major** failed → triage required before release.
- Any number of **minor** failures → release allowed with documented exceptions.
