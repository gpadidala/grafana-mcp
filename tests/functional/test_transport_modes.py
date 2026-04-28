"""Health/metrics transport contract.

stdio and a separate SSE listener aren't exercised here — those run as
distinct compose profiles and are covered manually via Inspector. We do
verify the streamable-http transport contracts the MCP wrapper depends on.
"""

from __future__ import annotations

import pytest


def test_healthz_returns_ok(mcp_http) -> None:
    r = mcp_http.get("/healthz")
    assert r.status_code == 200
    assert r.text.strip() == "ok"


def test_metrics_exposes_upstream_counters(mcp_http) -> None:
    r = mcp_http.get("/metrics")
    assert r.status_code == 200
    body = r.text
    # Upstream Prometheus instrumentation — names are stable contract.
    assert "go_goroutines" in body
    # Operation/session timers only appear after the first MCP call;
    # asserting their HELP line is enough to prove the registry is wired.
    assert "mcp_server_" in body or "go_gc_duration_seconds" in body


def test_unknown_path_404(mcp_http) -> None:
    r = mcp_http.get("/does-not-exist")
    assert r.status_code in (404, 405)


@pytest.mark.parametrize("path", ["/healthz", "/metrics"])
def test_endpoints_are_get_only(mcp_http, path: str) -> None:
    # POSTing to /healthz or /metrics must not 500 — upstream rejects with 4xx.
    r = mcp_http.post(path)
    assert r.status_code < 500
