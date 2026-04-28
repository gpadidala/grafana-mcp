"""Annotation CRUD — gated behind @write."""

from __future__ import annotations

import time

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = [pytest.mark.asyncio, pytest.mark.write]


async def test_annotation_full_lifecycle() -> None:
    text = f"grafana-mcp-test-{int(time.time())}"
    async with mcp_session() as session:
        created = tool_payload(await session.call_tool(
            "create_annotation",
            {"text": text, "tags": ["grafana-mcp-tests"]},
        ))
        assert created, "create_annotation returned empty"
        annotation_id = created.get("id") if isinstance(created, dict) else None

        listed = tool_payload(await session.call_tool(
            "get_annotations",
            {"tags": ["grafana-mcp-tests"]},
        ))
        assert listed, "get_annotations returned empty after create"

        if annotation_id:
            tool_names = {t.name for t in (await session.list_tools()).tools}
            update_tool = (
                "update_annotation"
                if "update_annotation" in tool_names
                else "patch_annotation"
            )
            await session.call_tool(
                update_tool,
                {"id": annotation_id, "text": text + " [patched]"},
            )

        tags_payload = tool_payload(await session.call_tool("get_annotation_tags", {}))
    assert tags_payload is not None
