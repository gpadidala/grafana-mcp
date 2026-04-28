"""Alerting tools.

Upstream split alerting tools across versions:
  - older: ``list_alert_rules`` / ``list_contact_points``
  - 0.12.x: ``list_alert_groups`` + ``alerting_manage_rules`` / ``alerting_manage_routing``

Tests probe the surface and exercise whatever read-only entrypoint is present.
Mutating CRUD is gated behind ``@write``.
"""

from __future__ import annotations

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


async def test_alert_listing_smoke() -> None:
    """Exercise whichever read-only listing tool the upstream version ships."""
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "list_alert_rules" in names:
            payload = tool_payload(await session.call_tool("list_alert_rules", {}))
        elif "list_alert_groups" in names:
            payload = tool_payload(await session.call_tool("list_alert_groups", {}))
        else:
            pytest.skip("no alerting list-tool present (alerting category disabled?)")
    assert payload is not None


async def test_routing_or_contact_points_listable() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "list_contact_points" in names:
            payload = tool_payload(await session.call_tool("list_contact_points", {}))
        elif "alerting_manage_routing" in names:
            payload = tool_payload(await session.call_tool(
                "alerting_manage_routing", {"action": "list"},
            ))
        else:
            pytest.skip("no contact-points / routing tool present")
    assert payload is not None


@pytest.mark.write
async def test_alert_rule_round_trip() -> None:
    pytest.skip("write CRUD covered manually — fixture seeding alert rules is non-trivial")
