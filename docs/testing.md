# Testing

Two layers, one harness.

## Layout

| Directory | Purpose |
|---|---|
| `tests/functional/` | Black-box checks of the MCP wrapper itself. Pass against any running server, even one pointed at an empty Grafana. |
| `tests/api/` | Per-tool checks that cross-reference Grafana's REST API for ground truth. Need a seeded Grafana. |
| `tests/fixtures/` | Idempotent seed scripts. |

## Set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt

cp .env.example .env

# bring up MCP + Grafana on ports configured in .env
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile local-grafana up -d

# seed Grafana with a service account, datasource, and a sample dashboard,
# write the token back into .env, and bounce MCP so it picks it up
GRAFANA_URL_HOST=http://localhost:23000 ./tests/fixtures/seed_grafana.sh
```

## Running

```bash
make test                  # everything
make test-functional       # quick wrapper smoke
make test-api              # tool exercises
```

Pass-through pytest options:

```bash
PYTEST_ARGS="-k prometheus -v" make test-api
```

## Validating with MCP Inspector

The official Inspector is the canonical client for poking at an MCP server.

```bash
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile inspector up -d
open http://localhost:6274
```

The Inspector container is preconfigured to connect over streamable-http to
`grafana-mcp:8000/mcp`. Once connected:

1. **Tools** tab → confirm 50 tools listed (upstream 0.12.1 default).
2. **Tools → list_datasources → Run** → expect a non-empty array.
3. **Resources** tab → empty by design (this MCP exposes tools, not
   resources).

For the other transports:

```bash
./scripts/run-inspector.sh streamable-http   # default
./scripts/run-inspector.sh sse               # requires server in -t sse mode
./scripts/run-inspector.sh stdio             # proxies through docker exec
```

## End-to-end suite (`tests/e2e/`)

Adds depth on top of the functional + API suites by pushing **real
telemetry** into the LGTM stack and exercising every callable MCP tool
against it.

```bash
# Bring up the stack with all four datasources auto-provisioned.
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile local-grafana up -d

# Mint a service-account token + create the seed dashboard.
GRAFANA_URL_HOST=http://localhost:23000 ./tests/fixtures/seed_grafana.sh

# Push real logs to Loki, traces to Tempo, extra dashboards.
./tests/fixtures/generate_test_data.sh

# Run the e2e suite (use -s to see live coverage / latency tables).
make test-e2e
```

What it exercises:

| File | What it proves |
|---|---|
| `test_real_data.py` | Loki returns the seeded log lines, Tempo returns OTLP traces pushed during the test, Prometheus has `up` + Go-runtime metrics, Pyroscope answers, dashboard summary resolves seeded panels. |
| `test_concurrency.py` | 8 concurrent MCP sessions each running `list_tools` + `list_datasources` + 5×`query_prometheus` complete without cross-talk. Reports p50/p95/max. |
| `test_multi_org.py` | `X-Grafana-Org-Id` is forwarded when present in `GRAFANA_FORWARD_HEADERS`; the JSON-RPC call succeeds with the header set. |
| `test_tool_coverage.py` | Walks all 70 surfaced tools, calls each with a sensible payload, classifies as `ok` / `errored` / `not-applicable` (datasource/service absent in this env) / `skipped-write` / `skipped-needs-state`. Writes a coverage matrix to `reports/e2e_tool_coverage.md`. |

### Latest run summary

| Metric | Value |
|---|---|
| Total MCP tools surfaced | **70** (full upstream surface, all categories) |
| `ok` (succeeded with sensible defaults) | **27** |
| `errored` | **0** |
| `not-applicable` (datasource/service not provisioned locally) | **5** (Sift, OnCall ×4) |
| Skipped — write tool | **5** |
| Skipped — needs caller-specific state (id, panel, etc.) | **33** |
| Concurrency p50 / p95 / max | **0.29s / 0.32s / 0.32s** for 8 sessions × 7 calls |
| `--disable-write` enforcement | **verified live**: write tools both filtered from `tools/list` AND refused at call time |

A full per-tool table is regenerated to `reports/e2e_tool_coverage.md`
each run.

## What `make test` covers

| Area | File | Tests |
|---|---|---|
| Tool surface | `functional/test_tool_discovery.py` | default tools present, ≥30 tools, no leaked admin/clickhouse, every tool has a JSON Schema |
| Smoke / Inspector parity | `functional/test_inspector_smoke.py` | initialize, list_tools, call list_datasources |
| Health & metrics | `functional/test_transport_modes.py` + `api/test_health_metrics.py` | `/healthz`, `/metrics` exposure |
| Dashboards | `api/test_dashboards.py` | search, summary, JSONPath property, panel queries — cross-checked with `/api/search` |
| Datasources | `api/test_datasources.py` | list, get-by-uid, get-by-name (adapts to upstream rename `get_datasource`) |
| Prometheus | `api/test_prometheus.py` | instant + range, metric/label discovery |
| Loki | `api/test_loki.py` | label names + log query, skipped if no Loki seeded |
| Alerting | `api/test_alerting.py` | listing tools (adapts to `list_alert_groups` rename) |
| Annotations | `api/test_annotations.py` | full CRUD lifecycle, gated behind `@write` |

## Write-mode gating

```python
@pytest.mark.write
async def test_thing_that_mutates(): ...
```

`tests/conftest.py` reads `MCP_DISABLE_WRITE`; when `true`, every `@write`
test is skipped with a reason. The default in the dev `.env` is `false`;
the prod overlay enforces `true`.

## Reports

JUnit XML written to `reports/junit.xml`. The Makefile defaults wire that
up so CI systems (GitHub Actions, Buildkite, Jenkins) can ingest it.

## Adding tests

The fixture pattern is:

```python
from tests.conftest import mcp_session, tool_payload

async def test_thing():
    async with mcp_session() as session:
        result = tool_payload(await session.call_tool("name", {...}))
    assert ...
```

`mcp_session()` is a context manager (not a pytest fixture) by design —
the streamable-http client opens an anyio cancel scope that pytest-asyncio
yield-fixtures can entangle in different tasks. Per-test `async with`
keeps the scope on a single task.
