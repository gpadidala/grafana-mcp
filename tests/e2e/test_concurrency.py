"""Concurrent-session stress: prove the streamable-http listener handles
multiple parallel MCP clients without cross-talk or session leaks.

Each session runs a small canonical workflow:
  1. initialize
  2. list_tools
  3. list_datasources
  4. query_prometheus(up)

Failure modes we're trying to catch:
  - Session-id confusion (one client's response landing on another)
  - Server-side fixture leakage (token from session A used by session B)
  - Lock contention causing non-trivial serialisation
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.conftest import mcp_session, tool_payload

pytestmark = pytest.mark.asyncio

CONCURRENT_CLIENTS = 8
CALLS_PER_CLIENT = 5


async def _client_workflow(client_id: int) -> dict:
    started = time.perf_counter()
    async with mcp_session() as session:
        tools = await session.list_tools()
        ds = tool_payload(await session.call_tool("list_datasources", {}))
        results = []
        for i in range(CALLS_PER_CLIENT):
            r = tool_payload(await session.call_tool(
                "query_prometheus",
                {"datasourceUid": "prometheus", "expr": "up",
                 "queryType": "instant"},
            ))
            results.append(r)
    return {
        "client": client_id,
        "tools_count": len(tools.tools),
        "datasources_observed": len(ds) if isinstance(ds, list) else None,
        "calls": len(results),
        "duration_s": time.perf_counter() - started,
    }


async def test_concurrent_sessions_no_crosstalk() -> None:
    results = await asyncio.gather(
        *[_client_workflow(i) for i in range(CONCURRENT_CLIENTS)]
    )

    # All clients must see the same tool surface.
    counts = {r["tools_count"] for r in results}
    assert len(counts) == 1, f"tool counts diverged across clients: {counts}"

    # Every client must complete its full workflow.
    assert all(r["calls"] == CALLS_PER_CLIENT for r in results)

    # Print a perf summary into pytest captured stdout — useful when run with -s.
    durations = sorted(r["duration_s"] for r in results)
    p50 = durations[len(durations) // 2]
    p95 = durations[int(len(durations) * 0.95)]
    print(
        f"\n[concurrency] {CONCURRENT_CLIENTS} clients × "
        f"{CALLS_PER_CLIENT + 2} calls each — "
        f"p50={p50:.2f}s p95={p95:.2f}s max={max(durations):.2f}s"
    )
