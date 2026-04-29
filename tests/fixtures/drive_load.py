"""Drive sustained MCP load so dashboards have something to render.

Runs N concurrent sessions for a fixed duration. Each session loops over
a mix of read-only tool calls, deliberately spread across categories so
the per-method panels in the Tools dashboard light up.

Usage:
    python tests/fixtures/drive_load.py --duration 90 --sessions 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8000")

# A mix of tools that are quick + meaningful in our LGTM stack. Keep it
# read-only so we can run with disable-write either way.
WORKLOAD = [
    ("list_datasources", {}),
    ("search_dashboards", {"query": ""}),
    ("get_datasource", {"uid": "prometheus"}),
    ("get_dashboard_by_uid", {"uid": "grafana-mcp-test"}),
    ("get_dashboard_summary", {"uid": "grafana-mcp-test"}),
    ("query_prometheus",
     {"datasourceUid": "prometheus", "expr": "up",
      "queryType": "instant", "endTime": "now"}),
    ("list_prometheus_metric_names",
     {"datasourceUid": "prometheus"}),
    ("list_prometheus_label_names",
     {"datasourceUid": "prometheus"}),
    ("list_loki_label_names", {"datasourceUid": "loki"}),
    ("query_loki_logs",
     {"datasourceUid": "loki",
      "logql": '{job="grafana-mcp-e2e"}', "limit": 5}),
    ("list_pyroscope_profile_types",
     {"data_source_uid": "pyroscope"}),
    ("get_annotations", {"limit": 5}),
    ("list_alert_groups", {}),
    ("list_teams", {}),
]


async def session_loop(session_id: int, deadline: float, stats: dict) -> None:
    while time.monotonic() < deadline:
        try:
            async with streamable_http_client(f"{MCP_BASE_URL}/mcp") as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    # Each open session makes ~10 calls before closing,
                    # so the session-duration histogram gets meaningful
                    # samples.
                    for _ in range(10):
                        if time.monotonic() >= deadline:
                            break
                        name, args = random.choice(WORKLOAD)
                        try:
                            await s.call_tool(name, args)
                            stats["ok"] += 1
                        except Exception:
                            stats["err"] += 1
                        await asyncio.sleep(random.uniform(0.05, 0.25))
        except Exception:
            stats["session_err"] += 1
            await asyncio.sleep(1)


async def _http_error_jitter(deadline: float) -> None:
    """Send a small fraction of intentionally broken HTTP requests so the
    Errors dashboard's 4xx/5xx panels have something to plot. Real
    deployments naturally see this; in a quiet local lab we have to
    synthesise it.

    Note: must hit the instrumented handler (`POST /mcp`) for
    `http_server_request_duration_seconds` to record the status code —
    fall-through 404s on un-routed paths bypass the middleware.
    """
    import urllib.error
    import urllib.request
    while time.monotonic() < deadline:
        # Malformed JSON → 400, recorded by otelhttp.
        req = urllib.request.Request(
            f"{MCP_BASE_URL}/mcp",
            data=b"not json",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError:
            pass
        except Exception:
            pass
        await asyncio.sleep(1.5)


async def main(duration: int, sessions: int) -> None:
    stats: dict = {"ok": 0, "err": 0, "session_err": 0}
    deadline = time.monotonic() + duration
    started = time.monotonic()
    print(f"[drive_load] {sessions} sessions for {duration}s against {MCP_BASE_URL}",
          flush=True)
    await asyncio.gather(
        *[session_loop(i, deadline, stats) for i in range(sessions)],
        _http_error_jitter(deadline),
    )
    elapsed = time.monotonic() - started
    rps = stats["ok"] / elapsed if elapsed else 0
    print(json.dumps({"elapsed_s": round(elapsed, 1),
                      "rps": round(rps, 1), **stats}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=90)
    ap.add_argument("--sessions", type=int, default=6)
    args = ap.parse_args()
    asyncio.run(main(args.duration, args.sessions))
