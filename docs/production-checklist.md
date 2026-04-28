# Production checklist

A flat, scannable list. Use it before promoting from staging to prod, and at
each quarterly review.

## Identity & access

- [ ] **Dedicated service account** in Grafana, **least privilege** for the
      enabled tool categories. Don't reuse a human's account.
- [ ] Token name includes the environment (e.g. `grafana-mcp-prod-2026q2`)
      so audit logs show provenance.
- [ ] Quarterly rotation calendar reminder set.
- [ ] `--disable-write` is **on** in the prod overlay. Disabling it requires
      a ticketed exception with a rollback plan.
- [ ] Off-by-default categories (`admin`, `clickhouse`, `cloudwatch`,
      `elasticsearch`, `examples`, `graphite`, `influxdb`, `runpanelquery`,
      `searchlogs`) stay off unless explicitly justified.
- [ ] Token stored in **Azure Key Vault** and mounted via **Secrets Store
      CSI Driver** (`SecretProviderClass`). Plain `Secret` only in dev.
- [ ] Pod identity uses **Azure Workload Identity**; the SA annotation is
      set in the prod overlay.

## Network

- [ ] `NetworkPolicy` restricts ingress to namespaces or pods labelled
      `mcp-client=true`.
- [ ] Egress restricted to the Grafana endpoint(s) and DNS only.
- [ ] Ingress (if external) terminates TLS via cert-manager + Let's Encrypt
      or AKS-managed certs. AGIC or NGINX is fine — pick one.
- [ ] mTLS to Grafana documented for hardened environments
      (`MCP_TLS_CERT_FILE`, `MCP_TLS_KEY_FILE`, `MCP_TLS_CA_FILE`).
- [ ] WAF / rate limit on the public ingress if exposed beyond the cluster.

## Reliability

- [ ] **3 replicas minimum** in prod, spread across zones via
      `topologySpreadConstraints`.
- [ ] PDB `minAvailable: 1`.
- [ ] HPA configured (CPU 70%, memory 80%, min 2 / max 10) and tested by
      forcing load.
- [ ] Readiness probe gates traffic correctly (`/healthz`).
- [ ] Liveness probe is **not** more aggressive than readiness — false
      restarts hurt more than they help.
- [ ] Container resource requests/limits sized from actual prod metrics,
      not the defaults in `k8s/base/deployment.yaml`.

## Observability

- [ ] `--metrics` enabled, scraped by Prometheus Operator via
      `ServiceMonitor`.
- [ ] OTel tracing shipped to Tempo (or equivalent). Sampling tuned.
- [ ] Sample Grafana dashboard JSON imported (TODO: ship one in
      `docs/dashboards/`).
- [ ] Alert rules in place:
  - request error rate
  - p95 / p99 latency
  - pod restart count > N in 10 min
  - OOMKilled count > 0
  - upstream `/healthz` failures
- [ ] Logs centralised (Loki / Azure Monitor / equivalent).

## Supply chain

- [ ] Image pinned by **digest** in prod overlay, not floating tag. Update
      script regenerates the digest on each version bump.
- [ ] SBOM generated with `syft`; vuln scan with `trivy` in CI; CI fails on
      critical vulns.
- [ ] Image signed with `cosign` (optional but recommended).
- [ ] Base image is `grafana/mcp-grafana:<exact-tag>` — do not rebase onto
      something custom without a clear reason.

## Operability

- [ ] Runbook in `docs/` for: token expired, Grafana unreachable, sudden
      tool-call spike, OOMKill, pod stuck `CrashLoopBackOff`.
- [ ] Upgrade procedure documented and tested in staging *first*.
- [ ] Rollback procedure documented (`kubectl rollout undo`, kustomize
      revert + apply).
- [ ] Capacity review at each minor upstream bump — the tool surface and
      session memory footprint can shift.
- [ ] On-call rotation knows where the dashboards and runbooks live.

## Verification before sign-off

```bash
# Render and lint the prod overlay.
make k8s-render ENV=prod | kubectl apply --dry-run=server -f -

# Optional, recommended:
kubectl kustomize k8s/overlays/prod | kubeconform -strict -summary
kubectl kustomize k8s/overlays/prod | kube-score score --output-format ci

# Ship.
make k8s-apply-prod CONFIRM=yes
```
