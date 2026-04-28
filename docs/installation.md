# Installation

Five paths, in increasing operational rigour.

## 1. Docker (single command)

```bash
docker run --rm -p 8000:8000 \
  -e GRAFANA_URL=https://grafana.example \
  -e GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_xxx \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_ADDRESS=0.0.0.0:8000 \
  grafana/mcp-grafana:0.12.1 \
  -t streamable-http --address :8000 --metrics
```

The wrapper's value over a raw `docker run` is the env-var translation in
`docker/entrypoint.sh` — useful when you have many flags to set.

## 2. Compose

Repo-local — gives you the wrapper image, the env file, and the optional
`local-grafana` / `inspector` profiles.

```bash
cp .env.example .env
docker compose --env-file .env -f compose/docker-compose.yml up -d
```

Profiles:

```bash
# bundled Grafana for laptop demos
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile local-grafana up -d

# MCP Inspector pointed at the running server
docker compose --env-file .env -f compose/docker-compose.yml \
  --profile inspector up -d
```

> **Why `--env-file .env` is required.** Compose reads `.env` from the
> compose-file's directory by default. Our `.env` lives at the repo root,
> so the explicit `--env-file` keeps variable substitution consistent.

## 3. Podman

Two paths, depending on Podman version:

- **Podman 4.4+** — points at the same Compose v2 file:
  ```bash
  podman compose --env-file .env -f compose/docker-compose.yml up -d
  ```
- **Older standalone `podman-compose`** (Python tool) — uses the v1 dialect
  in `compose/podman-compose.yml`:
  ```bash
  podman-compose -f compose/podman-compose.yml up -d
  ```

Differences from Docker:

- Rootless by default — bind ports >= 1024 only, or grant
  `net.ipv4.ip_unprivileged_port_start=80` in `sysctl`.
- `host.docker.internal` is `host.containers.internal` on Podman.
- `deploy.resources` is silently ignored by `podman-compose`; the
  `podman-compose.yml` variant uses `mem_limit` / `cpus` instead.

## 4. Raw binary

If you want to skip containers entirely:

```bash
go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@v0.12.1
GRAFANA_URL=https://grafana.example \
GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_xxx \
mcp-grafana -t streamable-http --address :8000 --metrics
```

This path doesn't use anything in this repo — it's documented here for
completeness. The wrapper, Compose stack, and K8s manifests are the value
add.

## 5. Kubernetes (Kustomize)

```bash
# render and inspect
make k8s-render ENV=dev | less

# apply (dev / staging require kubectl context)
make k8s-apply-dev
make k8s-apply-staging

# prod requires explicit confirmation
make k8s-apply-prod CONFIRM=yes
```

The `dev` overlay enables `--debug`, runs a single replica, and reads the
service-account token from a plain `Secret`. The `prod` overlay flips
`--disable-write` on, scales to 3 replicas, and switches to a Key
Vault-backed `SecretProviderClass` mount.

See `k8s/overlays/<env>/kustomization.yaml` for what each overlay patches.

## Prerequisite: a Grafana service account

```bash
# in Grafana → Administration → Service accounts → New service account
#   Name: grafana-mcp
#   Role: Editor (or less, see docs/api-reference.md)
# Create token, copy `glsa_...` into .env or your Secret.
```

For prod we recommend:

- Role: **Editor** *only* if you need write tools enabled. Otherwise **Viewer**
  + the specific RBAC permissions per tool listed in
  `docs/api-reference.md`.
- Token name including the environment (e.g. `grafana-mcp-prod-2026q2`) so
  rotations are auditable.
- Quarterly rotation calendar reminder.
