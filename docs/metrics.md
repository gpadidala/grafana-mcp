# Metrics reference

The wrapper enables `--metrics` by default. Metrics are served at
`/metrics` on the same listener as the MCP endpoint (or on
`MCP_METRICS_ADDRESS` if set). The Prometheus `ServiceMonitor` shipped
under [`k8s/base/servicemonitor.yaml`](../k8s/base/servicemonitor.yaml)
points kube-prometheus-stack at this endpoint.

> Captured live from `grafana/mcp-grafana:0.12.1` after one MCP
> initialization + one `tools/list` + one `tools/call`. Names are
> upstream — they may shift across versions; re-run
> `curl /metrics | awk '/^# HELP/'` after every bump.

## MCP-specific

These are the metrics the wrapper's monitoring is built around. Names are
stable across upstream patch releases.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `mcp_server_operation_duration_seconds` | histogram | `mcp_method_name`, `network_transport`, `otel_scope_*` | End-to-end MCP request time, server-side: from receive to ack/result. Use `_bucket` with `histogram_quantile` for p50/p95/p99, and `_count` for call rate. |
| `mcp_server_session_duration_seconds` | histogram | `network_transport`, `otel_scope_*` | Session lifetime, recorded when the streamable-http session is reaped (idle timeout, see `MCP_SESSION_IDLE_TIMEOUT_MINUTES`). |
| `mcp_sessions_active` | gauge | `otel_scope_*` | Currently-open MCP sessions. Production capacity sizing pivot. |
| `mcp_client_cache_lookups_total` | counter | `otel_scope_*` | Total Grafana-client cache lookups. |
| `mcp_client_cache_hits_total` | counter | `otel_scope_*` | Cache hits — existing client reused. |
| `mcp_client_cache_misses_total` | counter | `otel_scope_*` | Cache misses — new client minted. High miss rate ⇒ short-lived sessions or per-call header overrides. |
| `mcp_client_cache_size` | gauge | `otel_scope_*` | Current cached-client count. |

### Useful PromQL

```promql
# p95 operation latency by method, last 5m
histogram_quantile(0.95,
  sum by (le, mcp_method_name) (
    rate(mcp_server_operation_duration_seconds_bucket{namespace="grafana-mcp"}[5m])
  )
)

# Top 10 slowest methods (p99)
topk(10,
  histogram_quantile(0.99,
    sum by (le, mcp_method_name) (
      rate(mcp_server_operation_duration_seconds_bucket{namespace="grafana-mcp"}[5m])
    )
  )
)

# Total RPS to MCP
sum(rate(mcp_server_operation_duration_seconds_count{namespace="grafana-mcp"}[1m]))

# Active sessions
sum(mcp_sessions_active{namespace="grafana-mcp"})

# Cache hit ratio
sum(rate(mcp_client_cache_hits_total[5m]))
/
sum(rate(mcp_client_cache_lookups_total[5m]))
```

## HTTP server / client

OpenTelemetry-instrumented (`go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp`).
Use these for **error-rate** (the MCP-specific operation metric does not
carry a `status` label).

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_server_request_duration_seconds` | histogram | `http_request_method`, `http_response_status_code`, `network_protocol_*`, `server_address`, `server_port`, `url_scheme` | Inbound HTTP duration. Filter `http_response_status_code=~"5..\|4.."` for errors. |
| `http_server_request_body_size_bytes` | histogram | as above | Inbound body size — useful for spotting abnormally large MCP payloads. |
| `http_server_response_body_size_bytes` | histogram | as above | Response payload size. |
| `http_client_request_duration_seconds` | histogram | (same OTel set) | Outbound HTTP from MCP → Grafana — when Grafana is slow, this rises before MCP-level latency does. |
| `http_client_request_body_size_bytes` | histogram | (same OTel set) | Outbound body size. |

### Useful PromQL

```promql
# Error rate (5xx) percent
100 *
sum(rate(http_server_request_duration_seconds_count{
  namespace="grafana-mcp",
  http_response_status_code=~"5.."
}[5m]))
/
sum(rate(http_server_request_duration_seconds_count{namespace="grafana-mcp"}[5m]))

# Upstream Grafana p95 (MCP → Grafana)
histogram_quantile(0.95,
  sum by (le) (
    rate(http_client_request_duration_seconds_bucket{namespace="grafana-mcp"}[5m])
  )
)
```

## Go runtime

Standard `client_golang` runtime metrics — useful for capacity tuning.

| Metric | Type | Meaning |
|---|---|---|
| `go_goroutines` | gauge | Live goroutines. Sustained growth ⇒ leaked goroutines. |
| `go_threads` | gauge | OS threads. |
| `go_gc_duration_seconds` | summary | GC pause distribution. |
| `go_gc_gogc_percent` | gauge | GOGC trigger. |
| `go_gc_gomemlimit_bytes` | gauge | Soft memory cap. |
| `go_memstats_alloc_bytes` | gauge | Heap allocated and currently in use. |
| `go_memstats_alloc_bytes_total` | counter | Total heap bytes allocated since start. |
| `go_memstats_heap_*` | gauge | Heap detail (alloc / idle / inuse / released / sys / objects / next_gc). |
| `go_memstats_stack_*` | gauge | Stack memory. |
| `go_memstats_frees_total` | counter | Total heap-object frees. |
| `go_memstats_mallocs_total` | counter | Total heap-object mallocs. |
| `go_memstats_last_gc_time_seconds` | gauge | Unix time of last GC. |
| `go_sched_gomaxprocs_threads` | gauge | GOMAXPROCS. |
| `go_info` | gauge | Build info (version, etc.). |

## Process

`process_collector` defaults.

| Metric | Type | Meaning |
|---|---|---|
| `process_cpu_seconds_total` | counter | Total user + system CPU. |
| `process_resident_memory_bytes` | gauge | RSS. |
| `process_virtual_memory_bytes` | gauge | VSZ. |
| `process_virtual_memory_max_bytes` | gauge | VSZ cap. |
| `process_open_fds` | gauge | Open file descriptors. |
| `process_max_fds` | gauge | FD limit. |
| `process_start_time_seconds` | gauge | Boot timestamp. |
| `process_network_receive_bytes_total` | counter | Bytes received over the network. |
| `process_network_transmit_bytes_total` | counter | Bytes sent over the network. |

## OTel target metadata

| Metric | Meaning |
|---|---|
| `target_info` | Constant 1; carries `service.name`, `service.version`, `host.*`, `os.*`, etc. as labels. Use for joining metrics across pods. |

## Coverage

Total metric families exposed at startup: **39**. After first MCP
session: **+8** (`mcp_*`, `http_*`).

## Suggested SLO definitions

| SLO | Threshold | PromQL |
|---|---|---|
| Availability — `/healthz` reachable | 99.9% over 30d | `avg_over_time(up{job=~".*grafana-mcp.*"}[30d])` |
| Latency — operation p95 | < 5s over 5m | `histogram_quantile(0.95, sum by (le) (rate(mcp_server_operation_duration_seconds_bucket[5m])))` |
| Error rate — HTTP 5xx | < 1% over 5m | see PromQL above |
| Concurrency headroom | active sessions < 80% of `MCP_SESSION_IDLE_TIMEOUT_MINUTES`-implied capacity | `sum(mcp_sessions_active) / <capacity>` |
