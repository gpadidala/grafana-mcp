"""Walk every safely-callable tool with a sensible default payload, capture
per-tool latency + success/failure, and emit a coverage matrix.

Run with ``-s`` to see the live table:
    pytest tests/e2e/test_tool_coverage.py -s

Tools that mutate state are skipped here — they belong in the @write-marked
suites where the lifecycle is explicit. Tools we can't call without
caller-specific state (incident ids, alert rule ids, dashboard panel ids)
are also skipped with a reason. Tools that need a datasource type the
local LGTM stack doesn't ship (clickhouse, cloudwatch, elasticsearch,
graphite, influxdb) are recorded as ``not-applicable`` so the matrix
reflects what's *callable* in this environment.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.conftest import mcp_session

pytestmark = pytest.mark.asyncio

DS = {
    "prometheus": "prometheus",
    "loki": "loki",
    "tempo": "tempo",
    "pyroscope": "pyroscope",
}

# Datasource types we don't ship in the local stack. Tools whose error
# messages match these substrings are reclassified as not-applicable.
MISSING_DS_MARKERS = (
    "ClickHouse client",
    "CloudWatch client",
    "Elasticsearch client",
    "graphite client",
    "InfluxDB",
    "OnCall",
    "Sift",
    "getting investigations",     # Sift on OSS Grafana → 404
    "Asserts",
    "access-control",             # Grafana OSS doesn't expose enterprise RBAC API
    "[GET /access-control",
)

PAYLOADS: dict[str, dict | str | None] = {
    # search / navigation
    "search_dashboards": {"query": ""},
    "search_folders": {},
    "list_datasources": {},
    "get_datasource": {"uid": "prometheus"},
    "generate_deeplink": {
        "resourceType": "dashboard", "dashboardUid": "grafana-mcp-test",
    },

    # dashboards
    "get_dashboard_by_uid": {"uid": "grafana-mcp-test"},
    "get_dashboard_summary": {"uid": "grafana-mcp-test"},
    "get_dashboard_property": {"uid": "grafana-mcp-test", "jsonPath": "$.title"},
    "get_dashboard_panel_queries": {"uid": "grafana-mcp-test"},

    # prometheus — endTime is required even for instant queries
    "query_prometheus": {
        "datasourceUid": DS["prometheus"], "expr": "up",
        "queryType": "instant", "endTime": "now",
    },
    "list_prometheus_metric_names": {"datasourceUid": DS["prometheus"]},
    "list_prometheus_metric_metadata": {"datasourceUid": DS["prometheus"]},
    "list_prometheus_label_names": {"datasourceUid": DS["prometheus"]},
    "list_prometheus_label_values": {
        "datasourceUid": DS["prometheus"], "labelName": "__name__",
    },
    "query_prometheus_histogram": None,    # needs a real histogram metric

    # loki
    "query_loki_logs": {
        "datasourceUid": DS["loki"], "logql": '{job="grafana-mcp-e2e"}', "limit": 5,
    },
    "query_loki_patterns": {
        "datasourceUid": DS["loki"], "logql": '{job="grafana-mcp-e2e"}',
    },
    "query_loki_stats": {
        "datasourceUid": DS["loki"], "logql": '{job="grafana-mcp-e2e"}',
    },
    "list_loki_label_names": {"datasourceUid": DS["loki"]},
    "list_loki_label_values": {"datasourceUid": DS["loki"], "labelName": "job"},

    # alerting (read-only listings — names vary across versions)
    "list_alert_groups": {},
    "list_alert_rules": {},

    # annotations
    "get_annotations": {"limit": 5},
    "get_annotation_tags": {},

    # oncall / incidents — error if backing service absent; coverage matrix
    # records that as not-applicable.
    "list_oncall_schedules": {},
    "list_oncall_teams": {},
    "list_oncall_users": {},
    "get_current_oncall_users": None,
    "list_incidents": {},
    "list_sift_investigations": {},

    # pyroscope — note snake_case data_source_uid in upstream 0.12.x
    "list_pyroscope_profile_types": {"data_source_uid": DS["pyroscope"]},
    "list_pyroscope_label_names": {"data_source_uid": DS["pyroscope"]},
    "list_pyroscope_label_values": {
        "data_source_uid": DS["pyroscope"], "name": "service_name",
    },

    # asserts
    "get_assertions": None,

    # admin (Admin SA token in this env)
    "list_users": {},
    "list_users_by_org": {},
    "list_teams": {},

    # query_examples + clickhouse describer want a datasource type — pass
    # one we have so the call exercises the routing layer.
    "get_query_examples": {"datasourceType": "prometheus"},

    # write tools — explicitly skipped here
    "create_annotation": "skip:write",
    "update_annotation": "skip:write",
    "create_folder": "skip:write",
    "update_dashboard": "skip:write",
    "create_incident": "skip:write",
    "add_activity_to_incident": "skip:write",
    "alerting_manage_rules": "skip:write",
    "alerting_manage_routing": "skip:write",

    # Need caller-specific state — explicitly skipped.
    "find_error_pattern_logs": None,
    "find_slow_requests": None,
    "get_alert_group": None,
    "get_dashboard_panel_image": None,
    "get_panel_image": None,
    "get_incident": None,
    "get_oncall_shift": None,
    "get_sift_analysis": None,
    "get_sift_investigation": None,
    "describe_alerting_routing": None,
    "describe_alerting_rules": None,
    "describe_clickhouse_table": None,
    "run_panel_query": None,
    "search_logs": None,
    "query_pyroscope": None,
    "list_clickhouse_tables": None,
    "query_clickhouse": None,
    "list_cloudwatch_dimensions": None,
    "list_cloudwatch_metrics": None,
    "list_cloudwatch_namespaces": None,
    "query_cloudwatch": None,
    "query_elasticsearch": None,
    "list_graphite_metrics": None,
    "list_graphite_tags": None,
    "query_graphite": None,
    "query_graphite_density": None,
    "query_influxdb": None,

    # Grafana enterprise RBAC tools — return 404 on OSS Grafana.
    "list_all_roles": None,
    "list_team_roles": None,
    "list_user_roles": None,
    "get_resource_description": None,
    "get_resource_permissions": None,
    "get_role_assignments": None,
    "get_role_details": None,
}

REPORT_PATH = Path("reports/e2e_tool_coverage.md")


async def test_walk_every_tool_capture_latency() -> None:
    rows: list[dict] = []
    async with mcp_session() as session:
        tools = (await session.list_tools()).tools
        for tool in tools:
            entry = {"tool": tool.name, "status": "", "ms": 0, "note": ""}
            mapping = PAYLOADS.get(tool.name, {})

            if mapping == "skip:write":
                entry["status"] = "skipped-write"
                rows.append(entry)
                continue
            if mapping is None:
                entry["status"] = "skipped-needs-state"
                rows.append(entry)
                continue

            t0 = time.perf_counter()
            try:
                r = await session.call_tool(tool.name, mapping)
                ms = (time.perf_counter() - t0) * 1000
                if getattr(r, "isError", False):
                    text = ""
                    for c in getattr(r, "content", []) or []:
                        text += getattr(c, "text", "") or ""
                    if any(m in text for m in MISSING_DS_MARKERS):
                        entry["status"] = "not-applicable"
                    else:
                        entry["status"] = "errored"
                    entry["note"] = text[:80].replace("\n", " ")
                else:
                    entry["status"] = "ok"
                entry["ms"] = round(ms, 1)
            except Exception as e:
                entry["status"] = "exception"
                entry["note"] = f"{type(e).__name__}: {e}"[:80]
            rows.append(entry)

    rows.sort(key=lambda r: r["tool"])

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w") as f:
        f.write("# e2e tool-coverage report\n\n")
        f.write(f"Total tools surfaced: **{len(rows)}**\n\n")
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        for status, n in sorted(counts.items()):
            f.write(f"- {status}: **{n}**\n")
        f.write("\n| tool | status | ms | note |\n|---|---|---:|---|\n")
        for r in rows:
            note = (r["note"] or "").replace("|", "\\|")
            f.write(f"| `{r['tool']}` | {r['status']} | {r['ms']} | {note} |\n")

    ok = sum(1 for r in rows if r["status"] == "ok")
    err = sum(1 for r in rows if r["status"] in ("errored", "exception"))
    skipped = sum(1 for r in rows if r["status"].startswith("skipped"))
    not_app = sum(1 for r in rows if r["status"] == "not-applicable")
    print(
        f"\n[coverage] {len(rows)} tools — ok={ok} errored={err} "
        f"not-applicable={not_app} skipped={skipped}"
    )
    print(f"  report → {REPORT_PATH}")

    # The threshold is over actually-callable tools in *this* environment
    # (i.e. excluding categories whose datasources we don't ship).
    callable_total = ok + err
    assert callable_total > 0
    assert ok / callable_total >= 0.85, (
        f"only {ok}/{callable_total} callable tools succeeded — below 85% "
        f"threshold. See {REPORT_PATH}."
    )
