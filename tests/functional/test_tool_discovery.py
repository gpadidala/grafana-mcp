"""Default tool surface — guards against accidental category drift."""

from __future__ import annotations

import os

import pytest

from tests.conftest import mcp_session

pytestmark = pytest.mark.asyncio

# Tools that should always be present in the upstream default profile.
# Names cross-checked against grafana/mcp-grafana@v0.12.1 README.
EXPECTED_DEFAULTS = {
    "search_dashboards",
    "list_datasources",
    "query_prometheus",
    "list_prometheus_metric_names",
    "query_loki_logs",
    "create_annotation",
    "get_annotations",
}

# Disabled-by-default upstream categories — leak detection by name prefix.
DISABLED_PREFIXES = (
    "list_users",
    "list_teams",
    "query_clickhouse",
    "search_logs",
    "example_",
)

ENABLED_TOOLS = os.environ.get("MCP_ENABLED_TOOLS", "")


async def test_default_tools_present() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    missing = EXPECTED_DEFAULTS - names
    assert not missing, f"expected default tools missing: {missing}"


async def test_minimum_tool_count() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    assert len(names) >= 30, f"only {len(names)} tools listed: {sorted(names)}"


async def test_disabled_categories_absent_unless_opted_in() -> None:
    if any(p in ENABLED_TOOLS for p in ("admin", "clickhouse", "searchlogs", "examples")):
        pytest.skip(f"opted in via MCP_ENABLED_TOOLS={ENABLED_TOOLS}")
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    leaked = [n for n in names if n.startswith(DISABLED_PREFIXES)]
    assert not leaked, f"disabled-by-default tools unexpectedly present: {leaked}"


async def test_every_tool_has_input_schema() -> None:
    async with mcp_session() as session:
        for tool in (await session.list_tools()).tools:
            assert tool.description and tool.description.strip()
            schema = tool.inputSchema
            assert schema.get("type") == "object", f"{tool.name} has non-object schema"
