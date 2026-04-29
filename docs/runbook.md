# grafana-mcp runbook

Operator playbook. Index page — drill into a section by symptom or alert
name.

| Alert | Section |
|---|---|
| `GrafanaMcpDown` | [#mcp-down](#mcp-down) |
| `GrafanaMcpRestartingRepeatedly` | [#crashloop](#crashloop) |
| `GrafanaMcpHighOperationLatencyP95` / `P99` | [#latency](#latency) |
| `GrafanaMcpHighErrorRate` | [#errors](#errors) |
| `GrafanaMcpMemoryPressure` | [#oom](#oom) |
| `GrafanaMcpHpaMaxedOut` | [#hpa-maxed](#hpa-maxed) |

---

## mcp-down

**What it means:** Prometheus can't scrape `grafana-mcp:9090/metrics`, the
pod is failing readiness, or both.

**Triage in order:**

```bash
NS=grafana-mcp
kubectl -n $NS get pods -l app.kubernetes.io/name=grafana-mcp
kubectl -n $NS describe pod -l app.kubernetes.io/name=grafana-mcp | tail -50
kubectl -n $NS logs -l app.kubernetes.io/name=grafana-mcp --tail=100
```

**Most common causes:**

1. **Image pull failure** — usually after a tag/digest bump in the prod
   overlay. Roll back: `kubectl -n $NS rollout undo deploy/grafana-mcp`.
2. **Probe failing** — check `/healthz` from inside the cluster:
   `kubectl -n $NS exec -it deploy/grafana-mcp -- curl -fsS http://127.0.0.1:8000/healthz`
3. **NetworkPolicy regression** — confirm the monitoring namespace has the
   `kubernetes.io/metadata.name=monitoring` label and Prometheus pods can
   reach port 9090.

**Rollback:**

```bash
kubectl -n $NS rollout undo deploy/grafana-mcp
kubectl -n $NS rollout status deploy/grafana-mcp
```

---

## crashloop

**What it means:** the container has been restarting more than three times
in 15 minutes.

```bash
NS=grafana-mcp
kubectl -n $NS logs -l app.kubernetes.io/name=grafana-mcp --previous --tail=200
```

**Common causes:**

| Log signal | Cause | Fix |
|---|---|---|
| `panic: ... GRAFANA_URL ...` | misconfigured ConfigMap | `kubectl -n $NS edit cm/grafana-mcp-config` |
| `401 Unauthorized` from Grafana | expired / revoked token | rotate token, see [#token-rotation](#token-rotation) |
| `dial tcp ... no such host` | Grafana DNS unresolvable | check egress NetworkPolicy + cluster DNS |
| `bind: address already in use` | duplicate listener (only on host networking) | not used in our manifests |
| OOMKilled in events | memory limit too low | bump `resources.limits.memory` then retest |

---

## latency

**What it means:** `mcp_server_operation_duration_seconds` p95 ≥ 5s for
10m, or p99 ≥ 15s.

```bash
# Top slow operations
kubectl -n $NS exec -it deploy/grafana-mcp -- \
  curl -fsS http://localhost:9090/metrics \
  | grep mcp_server_operation_duration_seconds_bucket \
  | awk '/le="\+Inf"/' | sort -k2 -n | tail -20
```

**Almost always Grafana-side**, not the MCP. Confirm by checking Grafana's
own latency dashboards. If MCP itself is the source:

- High concurrency from a chatty client → consider raising HPA max.
- Heavy `query_loki_logs` calls → tighten `MCP_MAX_LOKI_LOG_LIMIT` in
  the ConfigMap.
- Heavy admin enumerations → narrow `MCP_ENABLED_TOOLS` for that env.

---

## errors

**What it means:** > 5% errored operations in a 10m window.

**Triage:**

1. Identify the operation: `sum by (operation) (rate(mcp_server_operation_duration_seconds_count{status="error"}[5m]))`.
2. Match against recent changes — token rotation, datasource UID swap,
   plugin enable/disable.
3. Check Grafana audit log if available — many errors are upstream auth or
   permission issues.

**Specific patterns:**

- `403 Forbidden` on a specific tool family → service account lacks the
  RBAC permission for that category. See `docs/api-reference.md` for the
  permission per category and update the SA.
- `tool not found` errors visible to clients → likely after an upstream
  bump renamed a tool. Re-run `make test`; tests probe the surface and
  will tell you what shifted.

---

## oom

**What it means:** working set ≥ 85% of the limit for 10m.

**Quick fix:**

```bash
NS=grafana-mcp
# Bump the limit in dev overlay first
kubectl -n $NS patch deploy grafana-mcp \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"mcp","resources":{"limits":{"memory":"1Gi"}}}]}}}}'
```

Then update `k8s/base/deployment.yaml` to make the change durable.

**Root-cause:** memory grows roughly with concurrent streaming sessions.
Drop `MCP_SESSION_IDLE_TIMEOUT_MINUTES` to reap aggressively if clients
forget to close.

---

## hpa-maxed

**What it means:** HPA has been at `maxReplicas` for ≥ 15m.

**Decision tree:**

- Sustained legitimate load? → bump `maxReplicas` in `k8s/base/hpa.yaml`,
  PR + apply.
- Runaway client? → check upstream MCP client logs / audit for a single
  caller burning the listener.
- Spiky bot traffic? → consider a per-client rate limiter at the ingress.

---

## token-rotation

**Frequency:** quarterly minimum, immediately on suspected leak.

**Procedure (Key Vault path):**

```bash
# 1. Mint a new token in Grafana (Administration → Service accounts).
# 2. Update the secret in Key Vault:
az keyvault secret set \
  --vault-name "$KV" --name grafana-mcp-token --value "$NEW_TOKEN"
# 3. The CSI driver picks the new value up on its sync interval (default
#    2m). To force immediate uptake:
kubectl -n grafana-mcp rollout restart deploy/grafana-mcp
# 4. Validate:
kubectl -n grafana-mcp logs -l app.kubernetes.io/name=grafana-mcp --tail=20
# 5. Revoke the old token in Grafana once 24h has passed without errors.
```

**Procedure (plain Secret path — dev only):**

```bash
kubectl -n grafana-mcp create secret generic grafana-mcp \
  --from-literal=GRAFANA_SERVICE_ACCOUNT_TOKEN="$NEW_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n grafana-mcp rollout restart deploy/grafana-mcp
```

---

## upgrade

```bash
# 1. Bump version in three places.
sed -i '' 's/MCP_GRAFANA_VERSION=0\.12\.1/MCP_GRAFANA_VERSION=0.13.0/' Makefile
sed -i '' 's/MCP_GRAFANA_VERSION=0\.12\.1/MCP_GRAFANA_VERSION=0.13.0/' docker/Dockerfile
sed -i '' 's/0\.12\.1/0.13.0/' k8s/overlays/prod/kustomization.yaml

# 2. Test locally — tool-name renames will surface here.
make build && make test

# 3. Tag + let the release workflow build, scan, sign, push.
git tag v0.13.0 && git push origin v0.13.0

# 4. Apply to staging, observe 24h, then prod.
make k8s-apply-staging
make k8s-apply-prod CONFIRM=yes
```

---

## rollback

```bash
NS=grafana-mcp
kubectl -n $NS rollout undo deploy/grafana-mcp
kubectl -n $NS rollout status deploy/grafana-mcp
# Confirm the image
kubectl -n $NS get deploy/grafana-mcp -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

If the rollback is for a manifest change (not just an image bump),
`git revert` the offending commit and re-apply the overlay.
