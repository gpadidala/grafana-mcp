# Use cases

Ten scenarios, each laid out as: **prompt → tool calls → expected outcome →
caveats**. Tool names track upstream `grafana/mcp-grafana` 0.12.1.

---

## 1. Triage a firing alert

> *"What's firing right now and which dashboards show the affected service?"*

| Step | Tool | Why |
|---|---|---|
| 1 | `list_alert_groups` | grouped firing rules |
| 2 | `search_dashboards` *(query: service name)* | likely affected dashboards |
| 3 | `get_dashboard_panel_queries` | extract PromQL/LogQL for context |

**Expected:** alert group, dashboard list, and panel queries to feed back
into the chat.

**RBAC:** `alert.rules:read`, `folders:read`, `dashboards:read`.

---

## 2. Ad-hoc PromQL

> *"What's the p95 request latency for `checkout` over the last 30 minutes?"*

| Step | Tool |
|---|---|
| 1 | `list_datasources` |
| 2 | `query_prometheus_histogram` (range) |

**Caveat:** the histogram metric name and label cardinality matter — the LLM
should reuse `list_prometheus_label_values` to discover the right service
label rather than guessing.

**RBAC:** `datasources.proxy:perform`.

---

## 3. Log triage

> *"Show me the error patterns in `payments` in the last hour."*

| Step | Tool |
|---|---|
| 1 | `list_datasources` |
| 2 | `query_loki_patterns` |
| 3 | `find_error_pattern_logs` *(Sift)* |

**Caveat:** Sift requires a Grafana Cloud or supported on-prem deployment.
On vanilla OSS, fall back to `query_loki_logs` with a regex.

**RBAC:** `datasources.proxy:perform`, plus Sift access.

---

## 4. Dashboard hygiene

> *"List dashboards untouched in 6 months and summarise their panel queries."*

| Step | Tool |
|---|---|
| 1 | `search_dashboards` |
| 2 | `get_dashboard_summary` (loop) |
| 3 | `get_dashboard_panel_queries` (loop) |

**Caveat:** rate-limit the loop; large estates produce hundreds of calls.

**RBAC:** `dashboards:read`.

---

## 5. Targeted dashboard edit

> *"Change the title of the third panel on dashboard xyz to 'Latency p95'."*

| Step | Tool |
|---|---|
| 1 | `get_dashboard_property` *(jsonPaths: `$.panels[2]`)* |
| 2 | `update_dashboard` |

**Caveat:** write tool — refused unless `MCP_DISABLE_WRITE=false` and the
service account has `dashboards:write`. Always confirm with the user before
applying.

---

## 6. Annotation workflow

> *"Annotate dashboard X at the time of the deploy."*

| Step | Tool |
|---|---|
| 1 | `create_annotation` |

**RBAC:** `annotations:write`. Tag annotations with the deploy id so audit
joins are trivial.

---

## 7. On-call lookup

> *"Who is on call for platform right now?"*

| Step | Tool |
|---|---|
| 1 | `list_oncall_schedules` |
| 2 | `get_current_oncall_users` |
| 3 | `get_oncall_shift` |

**Caveat:** requires Grafana OnCall enabled on the source instance.

---

## 8. Audit / governance

> *"List service accounts with Editor on `prod-alerts`."*

| Step | Tool |
|---|---|
| 1 | admin tools (only when `--enabled-tools=admin`) |

**Caveat:** off by default. Enable explicitly only for the audit MCP server,
not the day-to-day developer one.

---

## 9. Read-only AI assistant for prod

Deploy two MCP servers behind separate ingress hosts:

- `mcp-prod-readonly.example.com` — `MCP_DISABLE_WRITE=true`, given to all
  developers.
- `mcp-prod-write.example.com` — write enabled, locked to a small group.

Both share the same Grafana, but the read-only one mints tokens with
**Viewer** scope and never carries `dashboards:write`.

---

## 10. Multi-org tenancy

One MCP server, many Grafana orgs:

```env
GRAFANA_FORWARD_HEADERS=X-Grafana-Org-Id
```

Per-session, the MCP client (or the proxy in front of it) sets the header.
The default org for sessions that don't provide one is `GRAFANA_ORG_ID`.

**Caveat:** auditing must persist the requesting client identity *and* the
chosen org-id together. Otherwise per-tenant attribution is impossible.
