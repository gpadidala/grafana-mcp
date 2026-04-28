"""Pytest fixtures shared across functional and api suites.

Why a context-manager helper instead of an async-generator fixture:
  ``streamable_http_client`` opens an anyio cancel scope. When wrapped in a
  pytest-asyncio yield-fixture the entry and exit can land in different
  tasks, raising ``RuntimeError: Attempted to exit cancel scope in a
  different task``. Per-test ``async with`` keeps the scope on one task.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8000")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000")
GRAFANA_TOKEN = os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")
WRITE_DISABLED = os.environ.get("MCP_DISABLE_WRITE", "false").lower() == "true"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.write tests when MCP_DISABLE_WRITE=true."""
    if not WRITE_DISABLED:
        return
    skip = pytest.mark.skip(reason="MCP_DISABLE_WRITE=true — write tests skipped")
    for item in items:
        if "write" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "write: mutates Grafana state")
    config.addinivalue_line("markers", "needs_loki: requires a Loki datasource seeded")


@asynccontextmanager
async def mcp_session():
    """Open an initialised MCP client session over streamable-http."""
    async with streamable_http_client(f"{MCP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.fixture
def grafana() -> httpx.Client:
    """Raw Grafana REST client, used as ground truth."""
    headers = {"Accept": "application/json"}
    if GRAFANA_TOKEN:
        headers["Authorization"] = f"Bearer {GRAFANA_TOKEN}"
    with httpx.Client(base_url=GRAFANA_URL, headers=headers, timeout=10.0) as client:
        yield client


@pytest.fixture(scope="session")
def mcp_http() -> httpx.Client:
    """Plain HTTP client at the MCP base URL — for /healthz, /metrics."""
    with httpx.Client(base_url=MCP_BASE_URL, timeout=5.0) as client:
        yield client


def tool_payload(call_result: Any) -> Any:
    """Extract the structured payload from an MCP CallToolResult.

    The upstream server returns either structured content or a single text
    block whose text is JSON. Hand back whatever the test can introspect.
    """
    if getattr(call_result, "structuredContent", None):
        return call_result.structuredContent
    for block in getattr(call_result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text
    return None
