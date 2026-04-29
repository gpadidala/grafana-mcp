# Dashboards

Production-grade Grafana dashboards for the MCP server. Import any of the
JSON files into your Grafana — they all assume a Prometheus datasource
that scrapes the [`ServiceMonitor`](../../k8s/base/servicemonitor.yaml)
shipped with this repo (or any Prometheus reachable on `/metrics`).

## What's here

| File | Title | UID | Panels |
|---|---|---|---:|
| [`grafana-mcp-overview.json`](grafana-mcp-overview.json) | Overview / SLO | `grafana-mcp-overview` | 12 |
| [`grafana-mcp-tools.json`](grafana-mcp-tools.json) | Tools / Operations | `grafana-mcp-tools` | 8 |
| [`grafana-mcp-sessions.json`](grafana-mcp-sessions.json) | Sessions | `grafana-mcp-sessions` | 9 |
| [`grafana-mcp-errors.json`](grafana-mcp-errors.json) | Errors | `grafana-mcp-errors` | 9 |
| [`grafana-mcp-runtime.json`](grafana-mcp-runtime.json) | Runtime / Resources | `grafana-mcp-runtime` | 10 |

## Importing

```bash
GRAFANA=http://grafana.example
TOKEN=glsa_...

for f in docs/dashboards/*.json; do
  curl -fsS -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -X POST "$GRAFANA/api/dashboards/db" \
       -d "$(jq -n --slurpfile dash "$f" \
              '{dashboard: $dash[0], overwrite: true, folderId: 0}')"
  echo
done
```

Or via UI: **Dashboards → Import → Upload JSON file**.

## Required metrics

All dashboards filter by `namespace="$namespace"`. In a Kubernetes
deployment, kube-prometheus-stack populates this label automatically.
For the local Compose stack, the same effect is achieved by static
labels in [`compose/prometheus/prometheus.yml`](../../compose/prometheus/prometheus.yml).

The metric catalogue is at [`docs/metrics.md`](../metrics.md).

## Live previews

These screenshots are captured by
[`tests/e2e/test_dashboards_playwright.py`](../../tests/e2e/test_dashboards_playwright.py)
against the local LGTM stack with 90 s of sustained MCP load
(see [`tests/fixtures/drive_load.py`](../../tests/fixtures/drive_load.py)).
Re-run with `make test-dashboards`.

### Overview / SLO

Top-level health: pods up, RPS, p95/p99 latency, 5xx %, top-N tools.

![Overview](screenshots/grafana-mcp-overview.png)

### Tools / Operations

Per-method drill-down: calls/sec by method, latency heatmap, p95 by
method, full p50/p95/p99 + RPS table.

![Tools](screenshots/grafana-mcp-tools.png)

### Sessions

Active sessions, churn rate, session-duration heatmap, Grafana-client
cache hit ratio.

![Sessions](screenshots/grafana-mcp-sessions.png)

### Errors

5xx/4xx rates, status-code stack, pod restarts, upstream Grafana
latency, top-N error endpoints. (5xx panels are correctly empty in a
healthy local run — they only light up during real incidents.)

![Errors](screenshots/grafana-mcp-errors.png)

### Runtime / Resources

Goroutines, GC pauses, heap detail, CPU, network bytes, file
descriptors.

![Runtime](screenshots/grafana-mcp-runtime.png)

## Why some panels say "No data" locally

| Panel | Reason | Where it lights up |
|---|---|---|
| `Memory: working set / limit` | Uses `container_memory_working_set_bytes` from cAdvisor | Real K8s cluster |
| `Pod restarts (15m increase)` / `Restarts (1h)` | Uses `kube_pod_container_status_restarts_total` from kube-state-metrics | Real K8s cluster |
| `5xx rate %` / `5xx in range` / `5xx rate over time` | Healthy local stack → 0 5xx responses | Production (during incidents) |
| `Top error endpoints` | `topk()` over an empty set renders as no-data | Production with errors |
| `GC pause p95` | `go_gc_duration_seconds{quantile="0.95"}` only emits after the first GC cycle | After ~30 s of sustained allocation |
