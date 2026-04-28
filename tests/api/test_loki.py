"""Loki tool category. Skipped unless a Loki datasource is seeded."""

from __future__ import annotations

import os

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = [pytest.mark.asyncio, pytest.mark.needs_loki]


def _loki_uid(grafana) -> str | None:
    explicit = os.environ.get("LOKI_DATASOURCE_UID")
    if explicit:
        return explicit
    for ds in grafana.get("/api/datasources").json():
        if ds.get("type") == "loki":
            return ds["uid"]
    return None


async def test_loki_label_names(grafana) -> None:
    uid = _loki_uid(grafana)
    if not uid:
        pytest.skip("no Loki datasource available")
    async with mcp_session() as session:
        names = tool_payload(await session.call_tool(
            "list_loki_label_names",
            {"datasourceUid": uid},
        ))
    assert names is not None


async def test_loki_log_query(grafana) -> None:
    uid = _loki_uid(grafana)
    if not uid:
        pytest.skip("no Loki datasource available")
    async with mcp_session() as session:
        result = tool_payload(await session.call_tool(
            "query_loki_logs",
            {"datasourceUid": uid, "logql": '{job=~".+"}', "limit": 5},
        ))
    assert result is not None
