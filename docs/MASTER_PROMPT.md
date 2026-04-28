# Master Prompt — Grafana MCP Server Deployment Platform

> Paste this entire document into Claude Code as the initial instruction. It is written as a phased, end-to-end build specification with explicit acceptance criteria so Claude Code can execute autonomously, then hand the deployable artifacts back for validation. Codex (or any second pair of eyes) can step in after each phase to audit.

---

## 0. Role, Mission, and Guardrails

You are acting as a senior platform engineer building a **production-grade deployment platform for the Grafana MCP server** (`github.com/grafana/mcp-grafana`, Docker image `mcp/grafana` / `grafana/mcp-grafana`).

You are **not rewriting the Grafana MCP server itself**. You are wrapping the upstream image and binary in a deployable, testable, observable platform that I (a Grafana administrator) can run on my laptop today and roll out to an AKS cluster tomorrow.

**Authoritative upstream references — use these, do not invent behaviour:**
- Source repo: <https://github.com/grafana/mcp-grafana>
- Docker Hub: <https://hub.docker.com/r/mcp/grafana> and <https://hub.docker.com/r/grafana/mcp-grafana>
- MCP spec: <https://modelcontextprotocol.io/>
- MCP Inspector docs: <https://modelcontextprotocol.io/docs/tools/inspector>
- MCP Inspector source: <https://github.com/modelcontextprotocol/inspector>
- Grafana service accounts: <https://grafana.com/docs/grafana/latest/administration/service-accounts/>
- Grafana RBAC: <https://grafana.com/docs/grafana/latest/administration/roles-and-permissions/access-control/>

**Hard rules:**
1. **Configuration via env vars only.** `GRAFANA_URL` and `GRAFANA_SERVICE_ACCOUNT_TOKEN` are mandatory; never hardcode them, never commit them, never log the token.
2. **Both Docker Compose and Podman must work** with the same source files. Where syntax differs, provide a `podman-compose.yml` (or document `podman compose -f docker-compose.yml`) and verify it.
3. **No secret leakage.** `.env` is gitignored, sample is `.env.example`. Kubernetes manifests reference `Secret` objects only — never inline tokens.
4. **Version pinning.** Pin the Grafana MCP image to a specific tag (latest stable as of build time, default to `v0.10.0` unless a newer tag exists on Docker Hub at execution time — verify before pinning). Pin Helm/Inspector/test framework versions too.
5. **Idempotent and reversible.** Every `make` / `docker compose` / `kubectl apply` action has a documented teardown.
6. **Verify before claiming done.** Each phase has acceptance criteria — run them, capture output, only then move on.

If any required information cannot be resolved (e.g. an upstream flag changed), **stop and ask**, do not guess.

---

## 1. Project Layout

Create the following structure at the repo root. Do not create empty placeholder files; only create files you actually populate in this build.

```
grafana-mcp-platform/
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── LICENSE                      # Apache-2.0 (matches upstream)
├── .gitignore
├── .dockerignore
├── .env.example
├── Makefile
├── docker/
│   ├── Dockerfile               # thin wrapper / re-tag of upstream
│   └── entrypoint.sh            # optional, only if it adds value
├── compose/
│   ├── docker-compose.yml       # Docker Compose v2 schema
│   ├── docker-compose.override.yml.example
│   └── podman-compose.yml       # Podman-friendly variant
├── config/
│   └── tools.env.example        # tool category enable/disable presets
├── k8s/
│   ├── base/
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml
│   │   ├── secret.example.yaml
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── serviceaccount.yaml
│   │   ├── networkpolicy.yaml
│   │   ├── poddisruptionbudget.yaml
│   │   ├── hpa.yaml
│   │   └── servicemonitor.yaml  # Prometheus Operator
│   └── overlays/
│       ├── dev/
│       │   └── kustomization.yaml
│       ├── staging/
│       │   └── kustomization.yaml
│       └── prod/
│           ├── kustomization.yaml
│           ├── ingress.yaml
│           └── replica-patch.yaml
├── tests/
│   ├── README.md
│   ├── requirements.txt
│   ├── conftest.py
│   ├── functional/
│   │   ├── test_inspector_smoke.py
│   │   ├── test_tool_discovery.py
│   │   └── test_transport_modes.py
│   ├── api/
│   │   ├── test_dashboards.py
│   │   ├── test_datasources.py
│   │   ├── test_prometheus.py
│   │   ├── test_loki.py
│   │   ├── test_alerting.py
│   │   ├── test_annotations.py
│   │   └── test_health_metrics.py
│   └── fixtures/
│       └── seed_grafana.sh      # seeds a local Grafana with test data
├── scripts/
│   ├── start-local.sh
│   ├── stop-local.sh
│   ├── run-inspector.sh
│   ├── smoke-test.sh
│   └── render-manifests.sh
└── docs/
    ├── installation.md
    ├── usecases.md
    ├── api-reference.md
    ├── testing.md
    ├── production-checklist.md
    └── images/                  # architecture diagrams as PNG/SVG
```

---

## 2. Phased Execution Plan

Work through these phases **in order**. After each phase, print a short status block (what was created, what was verified, what's next) and stop for review if `INTERACTIVE=1` is set.

### Phase 1 — Bootstrap & local Docker run

**Deliverables**
- `.gitignore` (exclude `.env`, `*.local.yaml`, `__pycache__/`, `.venv/`, `node_modules/`, `kubeconfig*`, `*.kubeconfig`, `secrets/`).
- `.dockerignore`.
- `.env.example` containing every supported env var with safe defaults and comments:
  - `GRAFANA_URL`
  - `GRAFANA_SERVICE_ACCOUNT_TOKEN`
  - `GRAFANA_USERNAME`, `GRAFANA_PASSWORD` (alternative auth)
  - `GRAFANA_ORG_ID`
  - `GRAFANA_EXTRA_HEADERS`
  - `MCP_TRANSPORT` (`stdio` | `sse` | `streamable-http`, default `streamable-http`)
  - `MCP_ADDRESS` (default `0.0.0.0:8000`)
  - `MCP_LOG_LEVEL` (default `info`)
  - `MCP_DEBUG` (default `false`)
  - `MCP_DISABLE_WRITE` (default `true` for prod overlay, `false` locally)
  - `MCP_ENABLED_TOOLS` (comma-separated; document `admin`, `examples`, `clickhouse`, `searchlogs` are off by default)
  - `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_EXPORTER_OTLP_INSECURE`
  - TLS client: `MCP_TLS_CERT_FILE`, `MCP_TLS_KEY_FILE`, `MCP_TLS_CA_FILE`, `MCP_TLS_SKIP_VERIFY`
  - TLS server: `MCP_SERVER_TLS_CERT_FILE`, `MCP_SERVER_TLS_KEY_FILE`
- `docker/Dockerfile` — a thin wrapper over `grafana/mcp-grafana:<pinned-tag>`. Default to `streamable-http` on `:8000` so it's container-friendly. Set a non-root `USER`, declare `EXPOSE 8000`, add a `HEALTHCHECK` that hits `/healthz`.
- `docker/entrypoint.sh` — only if you genuinely need to translate env vars into CLI flags (e.g. `MCP_ENABLED_TOOLS` → `--enabled-tools=...`). Keep it minimal and POSIX-sh.
- `Makefile` targets: `build`, `run`, `stop`, `logs`, `shell`, `inspector`, `test`, `test-functional`, `test-api`, `lint`, `clean`, `k8s-render`, `k8s-apply-dev`, `k8s-diff`.

**Acceptance criteria**
- `docker build -t grafana-mcp-platform:dev -f docker/Dockerfile .` succeeds.
- `docker run --rm --env-file .env grafana-mcp-platform:dev` starts and `curl -fsS http://localhost:8000/healthz` returns `ok`.
- `.env.example` covers every env var the upstream binary actually accepts; cross-check against the upstream README's CLI Flags Reference.

---

### Phase 2 — Docker Compose (Compose v2) + Podman

**Deliverables**
- `compose/docker-compose.yml`:
  - Service `grafana-mcp` using the locally built image (with `image:` + `build:` so users can swap).
  - Maps `8000:8000`.
  - Loads `../.env` via `env_file`.
  - Healthcheck pointing at `/healthz`.
  - Restart policy `unless-stopped`.
  - Resource limits via `deploy.resources` (compatible with `docker compose` standalone too).
  - Optional companion service `grafana` (image `grafana/grafana-oss:11-latest` or current LTS) gated behind a Compose profile (`--profile local-grafana`) so I can spin up a full stack with one command for testing. Pre-provision a service account token via a tiny init container or a documented one-time `curl` step in `tests/fixtures/seed_grafana.sh`.
  - Optional MCP Inspector service behind profile `inspector` (image `node:20-alpine` running `npx @modelcontextprotocol/inspector` against the MCP server URL).
- `compose/docker-compose.override.yml.example` — documents how to mount local certs, change ports, etc.
- `compose/podman-compose.yml` — Podman-rootless-friendly: avoid features `podman-compose` doesn't support (e.g. `deploy:` is silently ignored — use `mem_limit`/`cpus` instead). Document running with either `podman compose -f docker-compose.yml up` (Podman 4.4+) **or** the standalone `podman-compose -f compose/podman-compose.yml up`.

**Acceptance criteria**
- `docker compose -f compose/docker-compose.yml up -d` brings the server up healthy.
- `docker compose --profile local-grafana up -d` brings up Grafana + MCP + (optional) seed.
- `docker compose --profile inspector up -d` exposes the Inspector UI; document the URL and how to point it at the MCP server.
- Same flow works with `podman compose -f compose/docker-compose.yml up -d` and `podman-compose -f compose/podman-compose.yml up -d`. Document any divergence in `docs/installation.md`.

---

### Phase 3 — Validate with MCP Inspector

**Deliverables**
- `scripts/run-inspector.sh` — launches Inspector via `npx -y @modelcontextprotocol/inspector` (or the dockerized version) against the running MCP server in **all three transport modes**: stdio (proxy via `docker exec`), SSE (`http://localhost:8000/sse`), and streamable-http (`http://localhost:8000/`).
- `docs/testing.md` section "Validating with MCP Inspector" with screenshots/log captures showing:
  - Successful connection
  - Tool list populated (count and a sample of tool names like `search_dashboards`, `list_datasources`, `query_prometheus`)
  - One sample tool invocation (e.g. `list_datasources`) returning a non-empty response
- `tests/functional/test_inspector_smoke.py` — programmatic smoke check that uses the official `mcp` Python SDK (or `mcp-client`) to:
  - Connect to streamable-http
  - List tools
  - Call `list_datasources`
  - Assert the response shape

**Acceptance criteria**
- All three transports successfully list ≥ 30 tools (the exact count depends on which categories are enabled — assert lower bound).
- Inspector smoke test exits 0.

---

### Phase 4 — Test suite (functional + API)

**Deliverables**
- `tests/requirements.txt` — pin `pytest`, `pytest-asyncio`, `httpx`, `mcp` (the official Python SDK), `pyyaml`.
- `tests/conftest.py` — fixtures for: MCP client session (streamable-http), raw Grafana HTTP client (using the same service account token, for ground-truth comparisons), test data setup/teardown.
- `tests/fixtures/seed_grafana.sh` — idempotent seed: creates a folder, a Prometheus datasource pointing at a stub or real Prometheus, a sample dashboard, an annotation, and an alert rule.

**Functional test cases** (`tests/functional/`) — verify *end-user behaviour through MCP*:
1. `test_inspector_smoke.py` — see Phase 3.
2. `test_tool_discovery.py`
   - Tool list contains the expected default categories.
   - Disabled-by-default tools (`admin`, `clickhouse`, `searchlogs`, `examples`) are absent unless explicitly enabled.
   - Each tool exposes a non-empty `description` and a valid JSON Schema for inputs.
3. `test_transport_modes.py`
   - Same canonical request (`list_datasources`) against stdio, SSE, and streamable-http returns equivalent payloads.
   - SSE/HTTP transports honour the `X-Grafana-Org-Id` header override.
   - Health endpoint `/healthz` responds 200 only on SSE/HTTP transports.

**API-based test cases** (`tests/api/`) — exercise each major tool category and cross-check against Grafana's REST API:
4. `test_dashboards.py` — `search_dashboards`, `get_dashboard_summary`, `get_dashboard_by_uid`, `get_dashboard_property` (JSONPath like `$.title`, `$.panels[*].title`), `get_dashboard_panel_queries`. For each, also call the Grafana REST endpoint directly and assert the MCP response is a faithful subset/transform.
5. `test_datasources.py` — `list_datasources`, `get_datasource_by_uid`, `get_datasource_by_name`. Assert known seeded datasource appears.
6. `test_prometheus.py` — `query_prometheus` instant + range, `list_prometheus_metric_names`, `list_prometheus_label_names`, `list_prometheus_label_values`, `query_prometheus_histogram`. Use a metric guaranteed to exist (`up`).
7. `test_loki.py` — `query_loki_logs` (log + metric query), `list_loki_label_names`, `list_loki_label_values`, `query_loki_stats`. Skip gracefully if no Loki datasource is seeded.
8. `test_alerting.py` — `list_alert_rules`, `get_alert_rule_by_uid`, `list_contact_points`. Write tests (`create_alert_rule`, `update_alert_rule`, `delete_alert_rule`) gated behind `MCP_DISABLE_WRITE=false`.
9. `test_annotations.py` — full CRUD: `create_annotation`, `get_annotations`, `patch_annotation`, `update_annotation`, plus `get_annotation_tags`. Cleanup in teardown.
10. `test_health_metrics.py` — `/healthz` returns 200 `ok`; `/metrics` (when `--metrics` enabled) exposes `mcp_server_operation_duration_seconds` and `mcp_server_session_duration_seconds`.

**Acceptance criteria**
- `make test` runs the full suite with `pytest -ra` and exits 0 against the local Compose stack.
- Tests requiring write are skipped (with reason) when `MCP_DISABLE_WRITE=true`, executed when false.
- Coverage of tool categories: dashboards, datasources, prometheus, loki, alerting, annotations, health/metrics — minimum.

---

### Phase 5 — Architecture & documentation

**Deliverables**
- `ARCHITECTURE.md` describing:
  - Component view (MCP client ↔ MCP server ↔ Grafana / Prometheus / Loki / OnCall / Incident / Sift)
  - Transport modes and when to use each
  - Auth flow with service account token
  - Multi-org behaviour
  - Observability path (metrics scraped by Prometheus, traces shipped via OTLP to Tempo)
  - Production deployment topology on AKS
- Mermaid diagrams embedded in `ARCHITECTURE.md` for: high-level architecture, request flow, AKS topology. Also export each as PNG/SVG into `docs/images/` so the README renders on platforms that don't render Mermaid.
- `README.md` — modelled on a top-tier OSS README. Sections, in order:
  1. **Title + badges** (build status placeholder, license, MCP version supported, Grafana version supported)
  2. **What is this?** (one paragraph, plain English)
  3. **Why does it exist?** (the gap it fills vs. running the upstream image directly)
  4. **Architecture** (link to `ARCHITECTURE.md` + embedded high-level diagram)
  5. **Prerequisites**
  6. **Quick start (5 minutes)** — Docker Compose path
  7. **Quick start with Podman**
  8. **Configuration reference** (table of every env var, default, description, where it maps to upstream flag)
  9. **Use cases** (link to `docs/usecases.md`, with 6–10 concrete scenarios — see §3 below)
  10. **Validating with MCP Inspector** (commands + screenshot)
  11. **Testing** (`make test`, what's covered, how to extend)
  12. **API reference** (link to `docs/api-reference.md` — table of MCP tools with required RBAC, mirroring upstream)
  13. **Production deployment on AKS** (link to `docs/production-checklist.md`)
  14. **Observability** (Prometheus metrics, OTel tracing, sample Grafana dashboard JSON in `docs/`)
  15. **Security model** (service account scoping, read-only mode, network policy, secret management)
  16. **Troubleshooting**
  17. **Upgrading**
  18. **Contributing**
  19. **License & upstream attribution**
- `docs/installation.md` — every install path: Docker, Compose, Podman, Helm, raw binary, Kustomize.
- `docs/usecases.md` — see §3.
- `docs/api-reference.md` — table of MCP tools (built from upstream README), grouped by category, with RBAC permission, scope, and a curl/MCP example for each. Note disabled-by-default tools.
- `docs/production-checklist.md` — see §4.

**Acceptance criteria**
- `markdownlint` (or equivalent) passes.
- Every internal link resolves.
- README has zero TODOs.

---

### Phase 6 — AKS / Kubernetes manifests

**Deliverables under `k8s/base/`** (Kustomize base):
- `namespace.yaml` — namespace `grafana-mcp` with the `pod-security.kubernetes.io/enforce: restricted` label.
- `serviceaccount.yaml` — dedicated SA. If using Azure Workload Identity, annotate with `azure.workload.identity/client-id` placeholder; document this.
- `secret.example.yaml` — **example only**, with comments pointing at AKS-native options:
  - Plain `Secret` for dev
  - **Recommended** for prod: Azure Key Vault via the Secrets Store CSI Driver with `SecretProviderClass`. Provide the `SecretProviderClass` manifest commented out as a recommended alternative.
- `configmap.yaml` — non-secret env (URL host, transport, log level, enabled tools, OTEL endpoint).
- `deployment.yaml` — production-grade:
  - `replicas: 2` (overridden in prod overlay to 3+)
  - `strategy: RollingUpdate` with `maxSurge: 1`, `maxUnavailable: 0`
  - Container port 8000, plus 9090 if metrics on separate address
  - `livenessProbe` and `readinessProbe` hitting `/healthz`
  - `startupProbe` for slow Grafana endpoints
  - Resources: requests `100m / 128Mi`, limits `500m / 512Mi` (document tuning)
  - `securityContext`: `runAsNonRoot: true`, `runAsUser: 65532`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile.type: RuntimeDefault`
  - `topologySpreadConstraints` across zones
  - Env from ConfigMap + Secret
  - Args: `["-t", "streamable-http", "--address", ":8000", "--metrics", "--log-level", "$(MCP_LOG_LEVEL)"]` plus `--disable-write` in prod overlay
- `service.yaml` — `ClusterIP`, ports 8000 (http) and 9090 (metrics).
- `networkpolicy.yaml`:
  - Ingress: only from namespaces/pods labelled `mcp-client=true` (and the cluster's ingress controller namespace if exposed)
  - Egress: only to the Grafana service FQDN/IP and DNS
- `poddisruptionbudget.yaml` — `minAvailable: 1`.
- `hpa.yaml` — HPA on CPU 70% + memory 80%, min 2 / max 10. Add a custom-metrics example (commented) for `mcp_server_operation_duration_seconds` p95.
- `servicemonitor.yaml` — Prometheus Operator `ServiceMonitor` scraping `/metrics`.
- `kustomization.yaml` — wires all of the above.

**Overlays:**
- `k8s/overlays/dev/` — single replica, `--debug` enabled, write enabled.
- `k8s/overlays/staging/` — 2 replicas, write enabled, sandbox Grafana URL via patch.
- `k8s/overlays/prod/`:
  - `replica-patch.yaml` → 3 replicas
  - `ingress.yaml` → AGIC (Application Gateway Ingress Controller) **or** NGINX ingress with TLS, annotated for cert-manager. Provide both as commented variants and document choosing.
  - Patches to enforce `--disable-write`, add Azure Workload Identity annotations on the SA, and switch the Secret to a `SecretProviderClass`-backed CSI volume.

**Scripts:**
- `scripts/render-manifests.sh` — `kubectl kustomize k8s/overlays/<env>` for diffing.
- `Makefile` targets: `k8s-render ENV=prod`, `k8s-diff ENV=prod`, `k8s-apply-dev`, `k8s-apply-staging`, `k8s-apply-prod` (the last requires `CONFIRM=yes`).

**Acceptance criteria**
- `kubectl kustomize k8s/overlays/prod` produces a valid manifest set; pipe through `kubeval` or `kubeconform` and assert clean.
- `kustomize build k8s/overlays/prod | kubectl apply --dry-run=server -f -` against an AKS cluster succeeds (document the prerequisite kubeconfig step).
- The manifest set passes `kube-score` with no critical findings (warnings allowed but documented).

---

## 3. Use cases to document (`docs/usecases.md`)

Write each as: scenario → MCP prompt → underlying tool calls → expected outcome → caveats.

1. **Triage a firing alert** — "What's firing right now and what dashboard panels show the affected service?" (`list_alert_rules`, `search_dashboards`, `get_dashboard_panel_queries`)
2. **Ad-hoc PromQL** — "What's the p95 request latency for service `checkout` over the last 30 minutes?" (`list_datasources`, `query_prometheus`, `query_prometheus_histogram`)
3. **Log triage** — "Show me the error patterns in the `payments` service in the last hour." (`query_loki_logs`, `query_loki_patterns`, `find_error_pattern_logs` if Sift is enabled)
4. **Dashboard hygiene** — "List dashboards that haven't been updated in 6 months and summarise their panel queries." (`search_dashboards`, `get_dashboard_summary`, `get_dashboard_panel_queries`)
5. **Targeted dashboard edit** — "Change the title of the third panel on dashboard `xyz` to 'Latency p95'." (`get_dashboard_property`, `patch_dashboard` — write mode only)
6. **Annotation workflow** — "Annotate dashboard X at the time of the deploy to record the rollout." (`create_annotation`)
7. **On-call lookup** — "Who is on call for the platform team right now and when does the shift end?" (`list_oncall_schedules`, `get_current_oncall_users`, `get_oncall_shift`)
8. **Audit / governance** — "List all service accounts that have Editor on the `prod-alerts` folder." (admin tools, requires `--enabled-tools=admin`)
9. **Read-only AI assistant for prod** — same MCP server, deployed with `--disable-write`, gives a copilot-style assistant safe access without the ability to mutate.
10. **Multi-org tenancy** — same MCP server, calls scoped via `X-Grafana-Org-Id` header per session.

For each, include the exact tool name(s) and a one-line note on RBAC requirements.

---

## 4. Production checklist (`docs/production-checklist.md`)

A flat, scannable list, grouped:

**Identity & access**
- Dedicated Grafana service account, least privilege, token rotated quarterly.
- `--disable-write` on by default in prod; require ticketed exception to disable.
- Admin/ClickHouse/SearchLogs/Examples categories disabled unless explicitly justified.
- Token stored in Azure Key Vault, mounted via CSI driver; never in plain `Secret` outside dev.

**Network**
- NetworkPolicy restricts ingress to authorised namespaces.
- Egress restricted to Grafana endpoint(s).
- Ingress (if external) terminates TLS via cert-manager + Let's Encrypt or AKS-managed certs.
- mTLS to Grafana documented for hardened environments (`--tls-cert-file`, `--tls-key-file`, `--tls-ca-file`).

**Reliability**
- ≥ 3 replicas in prod, spread across zones.
- PDB `minAvailable: 1`.
- HPA configured and tested.
- Readiness probe gates traffic correctly.

**Observability**
- `--metrics` enabled, scraped by Prometheus Operator.
- OTel tracing shipped to Tempo (or equivalent).
- Sample Grafana dashboard JSON included for self-monitoring.
- Alert rules: error rate, p95 latency, pod restarts, OOMKills.

**Supply chain**
- Image pinned by digest in prod overlay, not floating tag.
- SBOM generated with `syft`; vuln scan with `trivy` in CI.
- Image signed with cosign (optional).

**Operability**
- Runbook in `docs/` for common incidents (token expired, Grafana unreachable, spike in tool calls).
- Upgrade procedure documented and tested in staging first.
- Rollback procedure documented (kustomize rollback or `kubectl rollout undo`).

---

## 5. Test execution & quality gates

**`make test` must run, in order:**
1. Lint: `markdownlint`, `yamllint`, `shellcheck`, `kustomize build` validation, `kubeconform`.
2. Build: `docker build`.
3. Bring up Compose stack with `local-grafana` profile.
4. Seed Grafana via `tests/fixtures/seed_grafana.sh`.
5. Run `pytest tests/functional tests/api -ra --junitxml=reports/junit.xml`.
6. Tear down Compose stack.
7. Print a summary table.

**A separate `make test-aks-dryrun ENV=prod`** target runs `kubectl --dry-run=server` against the configured cluster and a `kube-score` pass.

---

## 6. Output & reporting

After completing all phases, produce a final report containing:
- Tree of created files (top 3 levels).
- Pinned versions: upstream MCP image tag, MCP Inspector version, Helm chart version (if used), Python SDK version.
- Test results summary (pass/fail/skipped counts).
- Any TODOs or open questions, explicitly labelled.

Then stop. Do not push, do not tag, do not deploy to any cluster. Hand back to me for review and Codex follow-up.

---

## 7. Style notes

- Comments in YAML/Dockerfiles explain *why*, not *what*.
- Shell scripts: `set -euo pipefail`, no `bash`-isms unless shebang says `bash`.
- Python: type hints, `pytest` parametrisation where it reduces duplication, no bare `except`.
- README tone: direct, operator-focused, no marketing language.
- Diagrams: prefer Mermaid for source-of-truth, export PNG/SVG for rendering compatibility.

---

**Begin with Phase 1. Confirm the upstream image tag you're pinning to before you start writing the Dockerfile.**
