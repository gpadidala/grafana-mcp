# API reference

Tools exposed by upstream `grafana/mcp-grafana` **0.12.1**, grouped by
category. Names are taken directly from a live `tools/list` against the
wrapper image.

> Cross-version note: tool names *do* change between upstream releases.
> Bumping the pinned version (`MCP_GRAFANA_VERSION`) requires re-running
> `make test` to catch renames before they reach prod.

## Search & navigation

| Tool | Purpose | RBAC |
|---|---|---|
| `search_dashboards` | full-text dashboard search | `dashboards:read` |
| `search_folders` | folder lookup | `folders:read` |
| `generate_deeplink` | build a URL into Grafana for a query/dashboard | none |

## Datasources

| Tool | Purpose | RBAC |
|---|---|---|
| `list_datasources` | enumerate datasources | `datasources:read` |
| `get_datasource` | by uid or name | `datasources:read` |

## Dashboards

| Tool | Purpose | RBAC |
|---|---|---|
| `get_dashboard_by_uid` | full dashboard JSON | `dashboards:read` |
| `get_dashboard_summary` | title + panels + folder | `dashboards:read` |
| `get_dashboard_property` | JSONPath query into the dashboard | `dashboards:read` |
| `get_dashboard_panel_queries` | datasource queries per panel | `dashboards:read` |
| `update_dashboard` | **write** | `dashboards:write` |
| `get_panel_image` | render panel as PNG | `dashboards:read` + rendering plugin |
| `create_folder` | **write** | `folders:write` |

## Prometheus

| Tool | Purpose |
|---|---|
| `query_prometheus` | instant or range query |
| `query_prometheus_histogram` | histogram quantile helper |
| `list_prometheus_metric_names` | metadata browse |
| `list_prometheus_metric_metadata` | metadata browse |
| `list_prometheus_label_names` | label discovery |
| `list_prometheus_label_values` | label discovery |

## Loki

| Tool | Purpose |
|---|---|
| `query_loki_logs` | LogQL log query |
| `query_loki_patterns` | log pattern detection |
| `query_loki_stats` | volume / rate stats |
| `list_loki_label_names` | label discovery |
| `list_loki_label_values` | label discovery |

## Pyroscope

| Tool | Purpose |
|---|---|
| `query_pyroscope` | profile query |
| `list_pyroscope_label_names` | label discovery |
| `list_pyroscope_label_values` | label discovery |
| `list_pyroscope_profile_types` | available profile types |

## Alerting

Upstream 0.12.x consolidated alert rule and routing CRUD into two unified
tools. They take an `action` field (`list`, `get`, `create`, `update`,
`delete`) — the Inspector schema browser is the source of truth for the
exact arguments.

| Tool | Purpose |
|---|---|
| `list_alert_groups` | grouped firing rules |
| `get_alert_group` | single group lookup |
| `alerting_manage_rules` | rule CRUD (**write**) |
| `alerting_manage_routing` | contact points + routing CRUD (**write**) |
| `get_assertions` | grafana-asserts integration |

## Annotations

| Tool | Purpose | RBAC |
|---|---|---|
| `create_annotation` | **write** | `annotations:write` |
| `get_annotations` | search by tag/time | `annotations:read` |
| `update_annotation` | **write** | `annotations:write` |
| `get_annotation_tags` | enumerate tags | `annotations:read` |

## OnCall

Requires Grafana OnCall on the upstream instance.

| Tool | Purpose |
|---|---|
| `list_oncall_schedules` | schedules |
| `list_oncall_teams` | teams |
| `list_oncall_users` | users |
| `get_current_oncall_users` | who's on call now |
| `get_oncall_shift` | upcoming/active shift detail |

## Incidents

| Tool | Purpose |
|---|---|
| `list_incidents` | enumerate |
| `get_incident` | single incident |
| `create_incident` | **write** |
| `add_activity_to_incident` | **write** |

## Sift (Grafana Cloud / supported on-prem)

| Tool | Purpose |
|---|---|
| `list_sift_investigations` | enumerate investigations |
| `get_sift_investigation` | detail |
| `get_sift_analysis` | analysis output |
| `find_error_pattern_logs` | error-pattern triage |
| `find_slow_requests` | slow-request triage |

## Disabled by default

These categories require an explicit opt-in via
`MCP_ENABLED_TOOLS=admin,…`:

`admin`, `clickhouse`, `cloudwatch`, `elasticsearch`, `examples`,
`graphite`, `influxdb`, `runpanelquery`, `searchlogs`.

Enable only when you have a clear use case and the service account is
scoped accordingly.

## Sample invocation

JSON-RPC over HTTP to the streamable-http transport:

```bash
curl -fsS -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"tools/call",
    "params":{
      "name":"query_prometheus",
      "arguments":{
        "datasourceUid":"prometheus-self",
        "expr":"up",
        "queryType":"instant"
      }
    }
  }'
```
