# tests/

Two suites:

- `functional/` — black-box checks of the MCP wrapper itself: tool
  discovery, transport modes, Inspector smoke. These pass against any
  running MCP server, even one pointed at an empty Grafana.
- `api/` — exercise individual tool categories and cross-check the MCP
  response against Grafana's REST API. These require a Grafana with
  seeded data (`tests/fixtures/seed_grafana.sh`).

## Prerequisites

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt
```

Then bring up the stack and seed it:

```bash
cp .env.example .env       # leave token blank for local-grafana profile
docker compose -f compose/docker-compose.yml --profile local-grafana up -d
./tests/fixtures/seed_grafana.sh
```

The seed script provisions a service account, writes its token into
`.env` as `GRAFANA_SERVICE_ACCOUNT_TOKEN`, then bounces the MCP container
so it picks the token up.

## Running

```bash
make test                 # functional + api
make test-functional      # quick smoke
make test-api             # tool exercises
```

Tests that mutate Grafana state are gated behind
`MCP_DISABLE_WRITE=false`. They skip with a reason when writes are off.

## Environment variables

| Var | Purpose |
|-----|---------|
| `MCP_BASE_URL` | http base for streamable-http (default `http://localhost:8000`) |
| `GRAFANA_URL` | Grafana base url for ground-truth checks |
| `GRAFANA_SERVICE_ACCOUNT_TOKEN` | token for both MCP and direct Grafana calls |
| `MCP_DISABLE_WRITE` | when `true`, write tests skip |
| `LOKI_DATASOURCE_UID` | optional — skip Loki tests if absent |
