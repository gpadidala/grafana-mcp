"""Pyroscope tool category — exercises the profile datasource."""

from __future__ import annotations

import os

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


def _pyro_uid(grafana) -> str | None:
    explicit = os.environ.get("PYROSCOPE_DATASOURCE_UID")
    if explicit:
        return explicit
    for ds in grafana.get("/api/datasources").json():
        if ds.get("type") == "grafana-pyroscope-datasource":
            return ds["uid"]
    return None


async def test_pyroscope_profile_types(grafana) -> None:
    uid = _pyro_uid(grafana)
    if not uid:
        pytest.skip("no Pyroscope datasource available")
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "list_pyroscope_profile_types" not in names:
            pytest.skip("pyroscope tools not enabled")
        payload = tool_payload(await session.call_tool(
            "list_pyroscope_profile_types",
            {"datasourceUid": uid},
        ))
    assert payload is not None


async def test_pyroscope_label_names(grafana) -> None:
    uid = _pyro_uid(grafana)
    if not uid:
        pytest.skip("no Pyroscope datasource available")
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "list_pyroscope_label_names" not in names:
            pytest.skip("pyroscope tools not enabled")
        payload = tool_payload(await session.call_tool(
            "list_pyroscope_label_names",
            {"datasourceUid": uid},
        ))
    assert payload is not None
