"""Verify that --disable-write actually blocks write tools at runtime.

Run this against an MCP server explicitly started with MCP_DISABLE_WRITE=true.
If write tools are still callable, the prod overlay's safety net is broken.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    os.environ.get("MCP_DISABLE_WRITE", "").lower() != "true",
    reason="only meaningful when MCP_DISABLE_WRITE=true",
)
async def test_create_annotation_refused() -> None:
    async with mcp_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        if "create_annotation" not in names:
            # Ideal: write tools are filtered out of tools/list entirely.
            return
        result = await session.call_tool(
            "create_annotation",
            {"text": "this should be refused", "tags": ["disable-write-test"]},
        )
    # Either the call returns isError=True with a refusal, or upstream
    # filters the tool. Both are acceptable safety behaviours.
    assert getattr(result, "isError", False), \
        f"write succeeded under --disable-write: {tool_payload(result)}"
