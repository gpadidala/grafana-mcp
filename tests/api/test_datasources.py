"""Datasource tools.

Upstream v0.12.x exposes a single ``get_datasource`` tool that accepts either
``uid`` or ``name``. Earlier versions split this into two; tests probe the
discovered tool surface and adapt rather than hard-coding either shape.
"""

from __future__ import annotations

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


async def test_list_datasources(grafana) -> None:
    via_rest = grafana.get("/api/datasources").json()
    if not via_rest:
        pytest.skip("no datasources seeded")
    async with mcp_session() as session:
        via_mcp = tool_payload(await session.call_tool("list_datasources", {}))
    rest_uids = {ds["uid"] for ds in via_rest}
    if isinstance(via_mcp, list):
        mcp_uids = {ds.get("uid") for ds in via_mcp if isinstance(ds, dict)}
        assert rest_uids & mcp_uids, "no overlap between MCP and REST datasource lists"


async def test_get_datasource_by_uid(grafana) -> None:
    datasources = grafana.get("/api/datasources").json()
    if not datasources:
        pytest.skip("no datasources seeded")
    uid = datasources[0]["uid"]
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        # Both naming variants are accepted to keep the test version-portable.
        if "get_datasource" in names:
            payload = tool_payload(await session.call_tool("get_datasource", {"uid": uid}))
        elif "get_datasource_by_uid" in names:
            payload = tool_payload(await session.call_tool("get_datasource_by_uid", {"uid": uid}))
        else:
            pytest.skip("no get_datasource* tool exposed")
    assert payload, "datasource fetch returned empty"


async def test_get_datasource_by_name(grafana) -> None:
    datasources = grafana.get("/api/datasources").json()
    if not datasources:
        pytest.skip("no datasources seeded")
    name = datasources[0]["name"]
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "get_datasource" in names:
            payload = tool_payload(await session.call_tool("get_datasource", {"name": name}))
        elif "get_datasource_by_name" in names:
            payload = tool_payload(await session.call_tool("get_datasource_by_name", {"name": name}))
        else:
            pytest.skip("no get_datasource* tool exposed")
    assert payload, "datasource fetch returned empty"
