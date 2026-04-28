"""Inspector-equivalent smoke check: connect, list tools, call list_datasources."""

from __future__ import annotations

import pytest

from tests.conftest import mcp_session

pytestmark = pytest.mark.asyncio


async def test_initialize_and_list_tools() -> None:
    async with mcp_session() as session:
        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        assert names, "tools/list returned empty"
        for tool in tools.tools:
            assert tool.description, f"tool {tool.name} has no description"
            assert tool.inputSchema, f"tool {tool.name} has no input schema"
            assert tool.inputSchema.get("type") == "object"


async def test_list_datasources_callable() -> None:
    async with mcp_session() as session:
        result = await session.call_tool("list_datasources", {})
        assert not getattr(result, "isError", False), result
