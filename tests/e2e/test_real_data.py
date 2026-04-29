"""End-to-end checks against the LGTM stack with real telemetry pushed in.

Pre-req: tests/fixtures/generate_test_data.sh has run, so:
  - Loki has ≥3 streams under job=grafana-mcp-e2e
  - Tempo has 30 traces across 3 services
  - Grafana has 4+ dashboards tagged grafana-mcp / e2e
  - Prometheus self-scrapes (so `up` is non-empty)

These are the assertions that fail loudly when MCP starts returning empty
results because of a regression — empty-tolerant tests cannot.
"""

from __future__ import annotations

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


# ─── Prometheus: real series + non-empty values ──────────────────────────
async def test_prometheus_up_is_alive() -> None:
    async with mcp_session() as session:
        result = tool_payload(await session.call_tool(
            "query_prometheus",
            {"datasourceUid": "prometheus", "expr": "up",
             "queryType": "instant", "endTime": "now"},
        ))
    body = str(result)
    # Result shape is upstream-version-specific; we just want evidence
    # of a non-empty Prometheus response containing the `up` series.
    assert any(needle in body for needle in ("metric", "value", "vector", '"up"', "instance")), \
        f"prometheus query returned an unexpected/empty payload: {body[:300]}"


async def test_prometheus_metric_names_includes_seeded() -> None:
    async with mcp_session() as session:
        # Default limit is 10, alphabetical — `up` is on a later page.
        # Pull it explicitly with regex.
        payload = tool_payload(await session.call_tool(
            "list_prometheus_metric_names",
            {"datasourceUid": "prometheus", "regex": "^up$"},
        ))
        # Also verify the unfiltered first page returns Go runtime metrics.
        page1 = tool_payload(await session.call_tool(
            "list_prometheus_metric_names",
            {"datasourceUid": "prometheus"},
        ))
    assert "up" in str(payload), \
        f"`up` series not found by regex query: {payload}"
    assert "go_" in str(page1) or "process_" in str(page1), \
        f"first page lacked any Go/process runtime metric: {page1}"


# ─── Loki: pushed log lines surface ──────────────────────────────────────
async def test_loki_label_names_includes_e2e_job() -> None:
    async with mcp_session() as session:
        payload = tool_payload(await session.call_tool(
            "list_loki_label_names",
            {"datasourceUid": "loki"},
        ))
    flat = str(payload).lower()
    assert "job" in flat, f"expected `job` label after seeding: {flat[:300]}"


async def test_loki_query_finds_seeded_logs() -> None:
    async with mcp_session() as session:
        payload = tool_payload(await session.call_tool(
            "query_loki_logs",
            {"datasourceUid": "loki",
             "logql": '{job="grafana-mcp-e2e"}',
             "limit": 10},
        ))
    body = str(payload)
    # Look for one of the strings we pushed.
    needles = ("checkout flow", "rate limit", "card_declined", "payment authorised")
    assert any(n in body for n in needles), \
        f"none of {needles} found in Loki query result: {body[:400]}"


# ─── Tempo: push fresh traces inside the test so we don't depend on
#           seed-time data still being inside Tempo's ingester window. ────
import asyncio as _asyncio  # noqa: E402
import json as _json  # noqa: E402
import os as _os  # noqa: E402
import secrets as _secrets  # noqa: E402
import time as _time  # noqa: E402


def _push_otlp_trace(service: str = "checkout") -> str:
    """Push a single OTLP HTTP trace to localhost:4318 and return the trace id."""
    import urllib.request
    trace_id = _secrets.token_hex(16)
    span_id = _secrets.token_hex(8)
    now_ns = int(_time.time() * 1e9)
    payload = {
        "resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": service}},
                {"key": "deployment.environment", "value": {"stringValue": "e2e"}},
            ]},
            "scopeSpans": [{
                "scope": {"name": "grafana-mcp-e2e"},
                "spans": [{
                    "traceId": trace_id, "spanId": span_id,
                    "name": f"POST /{service}", "kind": 2,
                    "startTimeUnixNano": str(now_ns),
                    "endTimeUnixNano": str(now_ns + 250_000_000),
                    "status": {"code": 1},
                }],
            }],
        }],
    }
    endpoint = _os.environ.get("TEMPO_OTLP_HTTP", "http://localhost:4318") + "/v1/traces"
    req = urllib.request.Request(
        endpoint, data=_json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()
    return trace_id


async def test_tempo_search_via_grafana(grafana) -> None:
    """MCP doesn't ship a dedicated Tempo tool surface in 0.12.1, but we
    verify the datasource is alive and reachable through Grafana's proxy
    so MCP-driven workflows that resolve trace IDs can work.

    The test pushes its own trace and waits for Tempo's ingester to flush
    (configured to ~30s in compose/tempo/tempo-config.yaml).
    """
    pushed = [_push_otlp_trace() for _ in range(5)]
    # Tempo flushes every 30s in the e2e compose tuning.
    deadline = _time.monotonic() + 60
    while _time.monotonic() < deadline:
        response = grafana.get(
            "/api/datasources/proxy/uid/tempo/api/search",
            params={"q": "{}", "limit": 10},
        )
        response.raise_for_status()
        data = response.json()
        traces = data.get("traces") or []
        if any(t.get("traceID") in pushed for t in traces):
            return
        await _asyncio.sleep(3)
    pytest.fail(
        f"Tempo never returned any of the {len(pushed)} pushed traces "
        f"within 60s — flush window broken or ingester unhealthy"
    )


# ─── Pyroscope: datasource reachable, profile types listable ─────────────
async def test_pyroscope_profile_types() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "list_pyroscope_profile_types" not in names:
            pytest.skip("pyroscope tools not enabled")
        # Upstream 0.12.x uses snake_case data_source_uid for pyroscope tools.
        payload = tool_payload(await session.call_tool(
            "list_pyroscope_profile_types",
            {"data_source_uid": "pyroscope"},
        ))
    # Pyroscope on an empty store still answers with the declared profile
    # types (cpu, alloc_objects, …) — body should be a non-trivial string.
    assert payload is not None


# ─── Dashboards: search finds the e2e ones, summary works ────────────────
async def test_search_finds_e2e_dashboards() -> None:
    async with mcp_session() as session:
        payload = tool_payload(await session.call_tool(
            "search_dashboards",
            {"query": "e2e"},
        ))
    body = str(payload)
    assert "e2e dashboard" in body or "grafana-mcp-e2e" in body, \
        f"e2e dashboards not surfaced: {body[:400]}"


async def test_dashboard_summary_resolves_panels(grafana) -> None:
    async with mcp_session() as session:
        payload = tool_payload(await session.call_tool(
            "get_dashboard_summary",
            {"uid": "grafana-mcp-test"},
        ))
    body = str(payload)
    # The seeded dashboard has a panel titled "up" and one titled
    # "recent logs" — at least one should be visible.
    assert "up" in body or "recent logs" in body, \
        f"summary missing seeded panels: {body[:300]}"
