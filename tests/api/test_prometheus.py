"""Prometheus tool category — uses the `up` series which always exists
when Prometheus scrapes anything (or itself)."""

from __future__ import annotations

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


def _prom_uid(grafana) -> str | None:
    for ds in grafana.get("/api/datasources").json():
        if ds.get("type") == "prometheus":
            return ds["uid"]
    return None


async def test_query_prometheus_instant(grafana) -> None:
    uid = _prom_uid(grafana)
    if not uid:
        pytest.skip("no prometheus datasource seeded")
    async with mcp_session() as session:
        result = tool_payload(await session.call_tool(
            "query_prometheus",
            {"datasourceUid": uid, "expr": "up", "queryType": "instant"},
        ))
    assert result is not None


async def test_query_prometheus_range(grafana) -> None:
    uid = _prom_uid(grafana)
    if not uid:
        pytest.skip("no prometheus datasource seeded")
    async with mcp_session() as session:
        result = tool_payload(await session.call_tool(
            "query_prometheus",
            {"datasourceUid": uid, "expr": "up", "queryType": "range",
             "startRfc3339": "now-5m", "endRfc3339": "now", "stepSeconds": 60},
        ))
    assert result is not None


async def test_metric_names(grafana) -> None:
    uid = _prom_uid(grafana)
    if not uid:
        pytest.skip("no prometheus datasource seeded")
    async with mcp_session() as session:
        payload = tool_payload(await session.call_tool(
            "list_prometheus_metric_names",
            {"datasourceUid": uid},
        ))
    assert payload is not None


async def test_label_names_and_values(grafana) -> None:
    """Two-step probe: skip if the upstream Prometheus has no labels yet.

    The skip check must live *outside* ``async with`` — pytest.skip raises
    ``Skipped``, which anyio's TaskGroup wraps in BaseExceptionGroup if it
    propagates through the context manager exit.
    """
    uid = _prom_uid(grafana)
    if not uid:
        pytest.skip("no prometheus datasource seeded")

    async with mcp_session() as session:
        names = tool_payload(await session.call_tool(
            "list_prometheus_label_names",
            {"datasourceUid": uid},
        ))
    if not isinstance(names, list) or not names:
        pytest.skip("no labels — empty Prometheus")
    first_label = next((n for n in names if isinstance(n, str)), None)
    if not first_label:
        pytest.skip("no string label names in response")

    async with mcp_session() as session:
        values = tool_payload(await session.call_tool(
            "list_prometheus_label_values",
            {"datasourceUid": uid, "labelName": first_label},
        ))
    assert values is not None
