"""/healthz and /metrics — wrapper-level contract."""

from __future__ import annotations


def test_healthz_ok(mcp_http) -> None:
    r = mcp_http.get("/healthz")
    assert r.status_code == 200
    assert r.text.strip() == "ok"


def test_metrics_session_and_operation_timers(mcp_http) -> None:
    r = mcp_http.get("/metrics")
    assert r.status_code == 200
    body = r.text
    # These come from the upstream Prometheus instrumentation — names are
    # the stable contract the production observability docs depend on.
    expected_any = (
        "mcp_server_session_duration_seconds",
        "mcp_server_operation_duration_seconds",
        "mcp_grafana_session",
        "mcp_grafana_operation",
    )
    assert any(name in body for name in expected_any), \
        f"none of {expected_any} found in /metrics; got first 200 chars:\n{body[:200]}"
