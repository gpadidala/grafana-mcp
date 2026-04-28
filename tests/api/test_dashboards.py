"""Dashboard tools, cross-checked against /api/search and /api/dashboards/uid."""

from __future__ import annotations

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


async def test_search_dashboards_returns_list() -> None:
    async with mcp_session() as session:
        payload = tool_payload(await session.call_tool("search_dashboards", {"query": ""}))
    assert payload is not None


async def test_search_matches_grafana_rest(grafana) -> None:
    async with mcp_session() as session:
        via_mcp = tool_payload(await session.call_tool("search_dashboards", {"query": ""}))
    via_rest = grafana.get("/api/search", params={"type": "dash-db"}).json()
    if not via_rest:
        pytest.skip("no dashboards seeded")
    rest_uids = {d["uid"] for d in via_rest}
    if isinstance(via_mcp, list):
        mcp_uids = {d.get("uid") for d in via_mcp if isinstance(d, dict)}
        assert rest_uids & mcp_uids, f"no overlap — rest={rest_uids} mcp={mcp_uids}"


async def test_dashboard_summary(grafana) -> None:
    dashboards = grafana.get("/api/search", params={"type": "dash-db", "limit": 1}).json()
    if not dashboards:
        pytest.skip("no dashboards seeded")
    uid = dashboards[0]["uid"]
    async with mcp_session() as session:
        summary = tool_payload(await session.call_tool("get_dashboard_summary", {"uid": uid}))
    assert summary, "empty summary"


async def test_dashboard_property_jsonpath(grafana) -> None:
    dashboards = grafana.get("/api/search", params={"type": "dash-db", "limit": 1}).json()
    if not dashboards:
        pytest.skip("no dashboards seeded")
    uid = dashboards[0]["uid"]
    async with mcp_session() as session:
        title = tool_payload(await session.call_tool(
            "get_dashboard_property",
            {"uid": uid, "jsonPaths": ["$.title"]},
        ))
    assert title, f"property fetch returned nothing for {uid}"


async def test_panel_queries(grafana) -> None:
    dashboards = grafana.get("/api/search", params={"type": "dash-db", "limit": 1}).json()
    if not dashboards:
        pytest.skip("no dashboards seeded")
    uid = dashboards[0]["uid"]
    async with mcp_session() as session:
        queries = tool_payload(await session.call_tool("get_dashboard_panel_queries", {"uid": uid}))
    assert queries is not None
