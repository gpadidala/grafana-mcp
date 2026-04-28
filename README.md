# grafana-mcp

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![upstream: grafana/mcp-grafana](https://img.shields.io/badge/upstream-mcp--grafana%200.12.1-orange)](https://github.com/grafana/mcp-grafana)
[![grafana: 11.x](https://img.shields.io/badge/grafana-11.x-success)](https://grafana.com/)
[![mcp spec](https://img.shields.io/badge/MCP-2025--03--26-purple)](https://modelcontextprotocol.io/)

A standalone, opinionated deployment platform for the **Grafana MCP server**
([upstream](https://github.com/grafana/mcp-grafana)).

---

## What is this?

`grafana-mcp` wraps the upstream `grafana/mcp-grafana` Docker image with the
plumbing you need to actually run it: pinned versions, hardened container,
Compose stacks, Kubernetes manifests for AKS, a regression test suite, and
operator-focused docs. The MCP server itself is unchanged — bug fixes and new
tools come from upstream. This repo is what makes shipping it painless.

## Why does it exist?

Running `docker run grafana/mcp-grafana` on a laptop is a one-liner. Running
it as a multi-replica, secret-managed, observable, network-policy-fenced
service in AKS is a project. This repo is that project, packaged so the next
operator who wants the same thing doesn't have to rediscover it.

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full picture. Short version:

```
MCP client  ──streamable-http──▶  grafana-mcp wrapper  ──REST+token──▶  Grafana
                                       │
                                       ├─ /healthz   (liveness)
                                       ├─ /metrics   (Prometheus)
                                       └─ OTLP       (Tempo)
```

## Prerequisites

- Docker 24+ **or** Podman 4.4+
- `make`
- Python 3.12+ (for the test suite)
- A Grafana instance and a service-account token — or use the bundled
  `local-grafana` Compose profile to spin one up.

## Quick start (5 minutes)

```bash
git clone git@github.com:gpadidala/grafana-mcp.git
cd grafana-mcp

cp .env.example .env
# edit GRAFANA_URL and GRAFANA_SERVICE_ACCOUNT_TOKEN

make build
docker compose --env-file .env -f compose/docker-compose.yml up -d

curl -fsS http://localhost:8000/healthz   # → ok
```

To bring up Grafana + Inspector alongside (laptop demo):

```bash
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile local-grafana --profile inspector up -d
./tests/fixtures/seed_grafana.sh
```

## Quick start with Podman

```bash
podman compose --env-file .env -f compose/docker-compose.yml up -d
# or, on older standalones:
podman-compose -f compose/podman-compose.yml up -d
```

See `docs/installation.md` for the differences (rootless, deploy-key
omissions, host networking).

## Configuration reference

Every supported env var is documented in [`.env.example`](.env.example). The
wrapper translates env vars → CLI flags in [`docker/entrypoint.sh`](docker/entrypoint.sh).
A short subset:

| Env var | Default | Maps to |
|---|---|---|
| `GRAFANA_URL` | — | upstream env |
| `GRAFANA_SERVICE_ACCOUNT_TOKEN` | — | upstream env |
| `GRAFANA_ORG_ID` | — | upstream env |
| `MCP_TRANSPORT` | `streamable-http` | `-t` |
| `MCP_ADDRESS` | `0.0.0.0:8000` | `--address` |
| `MCP_LOG_LEVEL` | `info` | `--log-level` |
| `MCP_DEBUG` | `false` | `--debug` |
| `MCP_DISABLE_WRITE` | `false` | `--disable-write` |
| `MCP_ENABLED_TOOLS` | upstream default | `--enabled-tools` |
| `MCP_METRICS` | `true` | `--metrics` |
| `MCP_SESSION_IDLE_TIMEOUT_MINUTES` | `30` | `--session-idle-timeout-minutes` |
| `MCP_TLS_CERT_FILE` … | — | `--tls-cert-file` … |

## Use cases

See [`docs/usecases.md`](docs/usecases.md) for ten worked scenarios — alert
triage, ad-hoc PromQL, log-pattern analysis, dashboard hygiene, on-call
lookup, audit, multi-org, and read-only AI assistants.

## Validating with MCP Inspector

```bash
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile inspector up -d
open http://localhost:6274
```

The Inspector container is preconfigured to point at the running MCP server.
See [`docs/testing.md`](docs/testing.md) for screenshots and the equivalent
CLI commands for stdio / SSE / streamable-http.

## Testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt

make test                  # functional + api
```

The suite cross-checks MCP responses against Grafana's REST API. Tests that
mutate Grafana state are gated behind `MCP_DISABLE_WRITE=false`.

## API reference

[`docs/api-reference.md`](docs/api-reference.md) lists every MCP tool exposed
by upstream `0.12.1` — name, category, required Grafana RBAC, and a sample
invocation.

## Production deployment on AKS

Render and apply the `prod` overlay:

```bash
make k8s-render ENV=prod | less
make k8s-apply-prod CONFIRM=yes
```

Pre-flight checks live in [`docs/production-checklist.md`](docs/production-checklist.md).
The prod overlay enforces `--disable-write`, runs as non-root, mounts the
service-account token from a `SecretProviderClass`-backed CSI volume, and
pins images by digest.

## Observability

- **Metrics**: `/metrics` is enabled by default and scraped by the included
  `ServiceMonitor`.
- **Tracing**: set `OTEL_EXPORTER_OTLP_ENDPOINT` and traces flow to Tempo or
  any OTLP collector.
- **Self-monitoring dashboard**: JSON exported under `docs/` (TODO).

## Security model

- One service account per environment, token rotated quarterly.
- Off-by-default tool categories (`admin`, `clickhouse`, `searchlogs`,
  `examples`) stay off in prod unless explicitly justified.
- `runAsNonRoot`, `readOnlyRootFilesystem`, `seccomp=RuntimeDefault`,
  `cap_drop=ALL` enforced via Pod Security Admission `restricted`.
- NetworkPolicy: ingress only from `mcp-client=true` pods, egress only to
  the Grafana endpoint.
- Optional mTLS to Grafana via `MCP_TLS_*`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `/healthz` returns nothing | Transport is `stdio` (no HTTP listener). |
| `tools/list` returns < 30 entries | `MCP_ENABLED_TOOLS` is too restrictive, or `--disable-*` flags are set. |
| `lookup grafana on 127.0.0.11:53: no such host` | MCP container not on the same network as Grafana — check Compose profile. |
| Token-related 401s | Service account lacks the role required by the called tool category. |

## Upgrading

1. Bump `MCP_GRAFANA_VERSION` in [`Makefile`](Makefile) and
   [`docker/Dockerfile`](docker/Dockerfile).
2. Re-run the test suite — it pins names that may shift between minor versions.
3. Review the upstream changelog for new tool categories that require a
   conscious enable/disable decision.
4. Update [`CHANGELOG.md`](CHANGELOG.md).
5. Apply to `dev`, then `staging`, then `prod`.

## Contributing

Issues and PRs welcome. Run `make test` and `make k8s-render ENV=prod`
before submitting.

## License & upstream attribution

Apache-2.0 — same as the upstream
[grafana/mcp-grafana](https://github.com/grafana/mcp-grafana). All MCP tool
behaviour is implemented upstream; this repository contains only deployment
glue, tests, and documentation.
