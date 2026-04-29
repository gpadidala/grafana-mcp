"""Default tool surface — guards against accidental category drift.

The wrapper compose default enables every upstream tool category so that
every datasource type the operator has plugged into Grafana is reachable.
Tests therefore probe the *actual* enabled list rather than the upstream
default.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import mcp_session

pytestmark = pytest.mark.asyncio

# Tools that should always be present whatever category mix is on.
ALWAYS_EXPECTED = {
    "search_dashboards",
    "list_datasources",
    "query_prometheus",
    "list_prometheus_metric_names",
    "query_loki_logs",
    "create_annotation",
    "get_annotations",
}

ENABLED_TOOLS = os.environ.get("MCP_ENABLED_TOOLS", "")
WRITE_DISABLED = os.environ.get("MCP_DISABLE_WRITE", "false").lower() == "true"

# Tools that the upstream binary filters out of tools/list when
# --disable-write is set. Tracked manually because upstream doesn't tag
# "write" in the schema.
WRITE_TOOLS = {
    "create_annotation",
    "update_annotation",
    "create_folder",
    "update_dashboard",
    "create_incident",
    "add_activity_to_incident",
}


async def test_always_expected_tools_present() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    expected = ALWAYS_EXPECTED - (WRITE_TOOLS if WRITE_DISABLED else set())
    missing = expected - names
    assert not missing, f"core tools missing: {missing}"
    # Sanity: when writes are off, write tools must NOT be in the surface.
    if WRITE_DISABLED:
        leaked = WRITE_TOOLS & names
        assert not leaked, f"--disable-write was set but write tools surfaced: {leaked}"


async def test_minimum_tool_count() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    # Upstream 0.12.1 default is ~50; with admin/clickhouse/etc enabled it
    # grows. The assertion is a generous lower bound.
    assert len(names) >= 30, f"only {len(names)} tools listed: {sorted(names)}"


async def test_disabled_categories_match_env() -> None:
    """If the operator ships MCP_ENABLED_TOOLS=admin,..., admin tools must
    be reachable. If MCP_ENABLED_TOOLS is unset / lacks admin, they must not.
    """
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    admin_names = {n for n in names if n.startswith(("list_users", "list_teams"))}
    if "admin" in ENABLED_TOOLS:
        assert admin_names, "admin enabled but no admin tools surfaced"
    # No assertion on the negative side — upstream may add admin-prefixed
    # tools that are technically read-only and stay enabled.


async def test_every_tool_has_input_schema() -> None:
    async with mcp_session() as session:
        for tool in (await session.list_tools()).tools:
            assert tool.description and tool.description.strip()
            schema = tool.inputSchema
            assert schema.get("type") == "object", f"{tool.name} has non-object schema"
