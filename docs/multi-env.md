# Connecting MCP to dev / perf / prod Grafanas

The bundled `local-grafana` Compose profile is for laptop demos. Real
work points the MCP server at your real Grafana — dev, perf, prod, or
any combination of them at the same time. This doc covers both.

## Mental model

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  grafana-mcp-dev        │ ──HTTPS──> grafana.dev.example.com │
│  (host port 8001)       │         └──────────────────────────┘
│  uses .env.dev          │
└─────────────────────────┘

┌─────────────────────────┐         ┌──────────────────────────┐
│  grafana-mcp-perf       │ ──HTTPS──> grafana.perf.example.com│
│  (host port 8002)       │         └──────────────────────────┘
│  uses .env.perf         │
└─────────────────────────┘

┌─────────────────────────┐         ┌──────────────────────────┐
│  grafana-mcp-prod       │ ──HTTPS──> grafana.prod.example.com│
│  (host port 8003)       │         └──────────────────────────┘
│  uses .env.prod         │
└─────────────────────────┘
```

Each environment is a separate Compose **project** (`--project-name`)
with its own `.env`, its own host port, its own service-account token.
They share the same source files in this repo; nothing about an
individual MCP server changes per environment except the configuration.

---

## 1. Mint a service-account token per environment

In **each** Grafana UI (dev, perf, prod):

```
Administration → Users and access → Service accounts → Add service account
  Display name:  grafana-mcp-<env>           # e.g. grafana-mcp-dev
  Role:          Viewer (read-only) or Editor (write tools too)
  → Add service account token
  Display name:  grafana-mcp-<env>-2026q2     # rotate quarterly
  → Copy the `glsa_...` token (shown once — store it before you leave the page)
```

**Role guidance:**

| Tool category you'll enable | Minimum role |
|---|---|
| Read-only observability (Prometheus, Loki, Tempo queries; dashboard search) | **Viewer** |
| Annotations CRUD, dashboard updates | **Editor** |
| `admin` tools (user/team management) | **Admin** *(rarely justified)* |

Run with `MCP_DISABLE_WRITE=true` in prod even if the SA is Editor —
that's the second-line defence against an LLM going rogue.

**Token hygiene:**

- Token name includes the environment + quarter (audit trail).
- Calendar reminder to rotate quarterly.
- Revoke the old token 24 h after rotation, after confirming the new
  one is live.

---

## 2. Create one `.env` per environment

```bash
cp .env.example .env.dev
cp .env.example .env.perf
cp .env.example .env.prod
```

The repo's `.gitignore` already excludes `.env.*`, so your tokens
never reach git.

### .env.dev

```env
GRAFANA_URL=https://grafana.dev.example.com
GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_dev_token_here
GRAFANA_ORG_ID=1                          # only if multi-org
MCP_DISABLE_WRITE=false                   # writes allowed in dev
MCP_LOG_LEVEL=debug                       # noisier in dev
MCP_HOST_PORT=8001                        # so dev/perf/prod don't collide

# Optional: header forwarding for ad-hoc multi-org via the MCP client
# GRAFANA_FORWARD_HEADERS=X-Grafana-Org-Id

# Optional: skip TLS verification if your dev Grafana uses a corporate
# self-signed cert. Insecure — never do this in prod.
# MCP_TLS_SKIP_VERIFY=true
```

### .env.perf

```env
GRAFANA_URL=https://grafana.perf.example.com
GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_perf_token_here
MCP_DISABLE_WRITE=false
MCP_HOST_PORT=8002
```

### .env.prod

```env
GRAFANA_URL=https://grafana.prod.example.com
GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_prod_token_here
GRAFANA_ORG_ID=1
MCP_DISABLE_WRITE=true                    # safety net
MCP_LOG_LEVEL=info
MCP_HOST_PORT=8003

# Lock down the tool surface in prod.
MCP_ENABLED_TOOLS=search,datasource,dashboard,prometheus,loki,alerting,annotations,oncall,incidents,sift,navigation,pyroscope,asserts
```

---

## 3. Bring up a single environment

```bash
docker compose --env-file .env.dev \
  -f compose/docker-compose.yml \
  --project-name grafana-mcp-dev \
  up -d grafana-mcp
```

Three important flags:

- `--env-file .env.dev` → which `.env` to load
- `--project-name grafana-mcp-dev` → isolates containers + network from
  other envs (`grafana-mcp-dev_grafana-mcp_1` etc.)
- `up -d grafana-mcp` → only the MCP service, **no `--profile
  local-grafana`** (we don't want a bundled Grafana — we're pointing at
  the real one)

Verify:

```bash
curl http://localhost:8001/healthz                            # → ok
docker logs grafana-mcp -p grafana-mcp-dev 2>&1 | head -3     # confirm GRAFANA_URL
```

Then point an MCP client at `http://localhost:8001/mcp`.

---

## 4. Run all three environments at once

```bash
docker compose --env-file .env.dev  -f compose/docker-compose.yml \
  --project-name grafana-mcp-dev  up -d grafana-mcp

docker compose --env-file .env.perf -f compose/docker-compose.yml \
  --project-name grafana-mcp-perf up -d grafana-mcp

docker compose --env-file .env.prod -f compose/docker-compose.yml \
  --project-name grafana-mcp-prod up -d grafana-mcp
```

What you have now:

```
$ docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
NAMES                              PORTS                              STATUS
grafana-mcp                        0.0.0.0:8001->8000/tcp             healthy   ← dev project
grafana-mcp                        0.0.0.0:8002->8000/tcp             healthy   ← perf project
grafana-mcp                        0.0.0.0:8003->8000/tcp             healthy   ← prod project
```

(Container names show `grafana-mcp` three times — Compose disambiguates
internally by project. You can confirm with
`docker compose --project-name grafana-mcp-prod ps`.)

Each MCP server is independent:

| Endpoint | Goes to |
|---|---|
| `http://localhost:8001/mcp` | dev Grafana |
| `http://localhost:8002/mcp` | perf Grafana |
| `http://localhost:8003/mcp` | prod Grafana |

Three separate Inspector connections, three separate dashboards, three
separate audit trails.

### Helper script

To avoid typing the long `docker compose ... --project-name ...`
incantation, use:

```bash
./scripts/connect-remote.sh --env dev up
./scripts/connect-remote.sh --env perf up
./scripts/connect-remote.sh --env prod up
```

The script reads `.env.<env>`, picks the right project name, and brings
up only the MCP service. See [`scripts/connect-remote.sh`](../scripts/connect-remote.sh).

---

## 5. TLS gotchas (very common on corporate networks)

Symptom in `docker logs`:

```
x509: certificate signed by unknown authority
```

Cause: your corporate firewall does TLS inspection — it re-signs
upstream certs with an internal CA that the MCP container doesn't
trust. Two fixes:

### Fix A — skip TLS verification (insecure but simplest)

```env
# in .env.<env>
MCP_TLS_SKIP_VERIFY=true
```

Acceptable for **internal** dev/perf where the network path is already
trusted. **Never set this in `.env.prod`.**

### Fix B — mount your corporate CA bundle (proper)

1. Get your corporate CA bundle from IT (typically `corp-root-ca.pem`).
   Put it under `certs/` in the repo:
   ```bash
   mkdir -p certs
   cp /path/to/corp-root-ca.pem certs/ca.pem
   ```
2. Create `compose/docker-compose.override.yml`:
   ```yaml
   services:
     grafana-mcp:
       volumes:
         - ../certs:/certs:ro
   ```
3. In `.env.<env>`:
   ```env
   MCP_TLS_CA_FILE=/certs/ca.pem
   ```

Compose merges `docker-compose.override.yml` automatically. The wrapper
entrypoint already translates `MCP_TLS_CA_FILE` → `--tls-ca-file`.

`certs/` is in the project `.gitignore` so the cert never ships to git.

---

## 6. MCP Inspector against a remote-pointing MCP

The Inspector still runs locally (or in the `inspector` Compose
profile). It just needs to know where to find the MCP server.

### Direct mode (recommended for remote-pointing MCP)

In the Inspector UI:

| Field | Value |
|---|---|
| Transport | Streamable HTTP |
| Mode | **Direct** |
| Server URL | `http://localhost:8001/mcp` (or `:8002`, `:8003`) |

Direct mode works because the MCP HTTP listener is exposed on a host
port, so your browser can reach it directly without going through the
Inspector's container proxy.

### Via Proxy mode

Only useful if you're running both Inspector AND MCP in the same
Compose project. For multi-env where each MCP is its own project, stick
with Direct mode.

---

## 7. Switching between environments

The cheapest way is to leave them all running on different host ports
(see §4). If you'd rather not, swap one for another:

```bash
./scripts/connect-remote.sh --env dev down
./scripts/connect-remote.sh --env prod up
```

Or hand-rolled:

```bash
docker compose --env-file .env.dev  --project-name grafana-mcp-dev  \
  -f compose/docker-compose.yml down
docker compose --env-file .env.prod --project-name grafana-mcp-prod \
  -f compose/docker-compose.yml up -d grafana-mcp
```

`down` only tears down the matching project's containers. Other envs
keep running.

---

## 8. Tear down everything

```bash
for env in dev perf prod; do
  ./scripts/connect-remote.sh --env $env down
done
```

Or:

```bash
docker compose --project-name grafana-mcp-dev  down
docker compose --project-name grafana-mcp-perf down
docker compose --project-name grafana-mcp-prod down
```

---

## 9. Troubleshooting checklist

| Symptom | Likely cause | Fix |
|---|---|---|
| `/healthz` returns ok but tool calls return `401` | Token revoked or wrong `GRAFANA_URL` | Re-mint token, verify URL points at the right Grafana |
| Tool calls return `403` on a specific category | Service account lacks the RBAC perm for that tool family | Read [`docs/api-reference.md`](api-reference.md) for the perm matrix; bump SA role |
| `x509: certificate signed by unknown authority` | Corporate TLS inspection | §5 above |
| `dial tcp: lookup ...: no such host` | DNS — corporate VPN required to reach the Grafana? | Connect VPN; in Docker Desktop check Settings → Network |
| Container starts then exits with `GRAFANA_URL is required` | Empty / wrong env file path | Re-check `--env-file` and that the var has a value |
| All three MCPs land on the same host port | Forgot `MCP_HOST_PORT` in one of the `.env.*` | Set it explicitly per env |
| `localhost:8001/healthz` ok from your laptop, but a colleague can't reach it | They need their own clone — MCP isn't a shared service unless you put it on a shared host | Put MCP in K8s (see [`k8s/`](../k8s/)) |

---

## 10. Production deployment is K8s, not Compose

This doc is for **operator laptops** pointing at remote Grafanas — useful
for ad-hoc analysis, on-call investigation, or testing the MCP surface
against a real environment.

For a **shared, multi-user MCP server** (your team's "MCP for prod
Grafana"), use the Kubernetes manifests under [`k8s/`](../k8s/) — the
prod overlay enforces `--disable-write`, mounts the token from Azure
Key Vault via the CSI driver, and is fronted by an Ingress with TLS.
See [`docs/production-checklist.md`](production-checklist.md).
