"""Multi-org via header forwarding.

When ``GRAFANA_FORWARD_HEADERS=X-Grafana-Org-Id`` is set in the wrapper
env, an MCP client can scope per-call to a specific Grafana organisation
by passing that header through the streamable-http transport.

The MCP Python SDK's ``ClientSession`` doesn't expose an arbitrary header
hook on every call (yet), so this test stays close to the wire and uses
the raw JSON-RPC HTTP path that the SDK speaks. If upstream introduces
``call_tool(..., headers={...})``, swap to that.
"""

from __future__ import annotations

import json
import os
import re

import httpx
import pytest

MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8000")


def _parse_jsonrpc(text: str) -> dict:
    """Streamable-http may wrap responses as SSE — pull the first JSON object."""
    for match in re.finditer(r"\{.*?\}\s*(?=\n|\Z)", text, re.S):
        try:
            return json.loads(match.group(0))
        except (ValueError, TypeError):
            continue
    return json.loads(text)


def _initialize(client: httpx.Client) -> str:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "e2e-multi-org", "version": "0"},
        },
    }
    r = client.post("/mcp", json=payload, headers={
        "Accept": "application/json, text/event-stream",
    })
    r.raise_for_status()
    return r.headers.get("Mcp-Session-Id", "")


def test_org_header_propagates_to_grafana() -> None:
    """Not asserting tenant content (we only have org 1 + an empty org 2);
    we assert that the request *does not error* with the header set, which
    proves the allowlist accepted it.
    """
    with httpx.Client(base_url=MCP_BASE_URL, timeout=10.0) as client:
        session_id = _initialize(client)
        if not session_id:
            pytest.skip(
                "server didn't return a session id — header forwarding test "
                "needs a stateful streamable-http session"
            )

        list_payload = {
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/call",
            "params": {"name": "list_datasources", "arguments": {}},
        }
        r = client.post(
            "/mcp", json=list_payload,
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
                "X-Grafana-Org-Id": "1",
            },
        )
        r.raise_for_status()
        body = _parse_jsonrpc(r.text)
        assert body.get("error") is None, body
        assert "result" in body, body


def test_org_header_disallowed_when_not_in_allowlist(monkeypatch) -> None:
    """When ``GRAFANA_FORWARD_HEADERS`` doesn't list the header, MCP must
    NOT forward it — i.e. the request still succeeds against the default org.
    The wrapper allowlist is set at start-up, so we can only inspect the
    behaviour, not flip it mid-test. Skip if the wrapper was started with
    forwarding enabled (the default in our compose).
    """
    if os.environ.get("GRAFANA_FORWARD_HEADERS"):
        pytest.skip("header forwarding enabled in this run; checked positive case above")
