"""Playwright functional test for every shipped Grafana dashboard.

Imports each dashboard via Grafana's API, navigates to it in a real
browser, waits for panels to render, captures a full-page screenshot,
and reports per-panel data presence.

Pre-conditions:
  - LGTM stack up (compose `local-grafana` profile)
  - tests/fixtures/seed_grafana.sh has run
  - tests/fixtures/generate_test_data.sh has run
  - tests/fixtures/drive_load.py has been run for ≥ 60 s so Prometheus
    has at least 4–5 scrapes' worth of mcp_* metrics

Outputs:
  - reports/dashboards/<uid>.png       full-page screenshot per dashboard
  - reports/dashboards/index.html      gallery view
  - reports/dashboards/summary.md      per-panel data-presence matrix
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:23000")
GRAFANA_USER = os.environ.get("GRAFANA_ADMIN_USER", "admin")
GRAFANA_PASS = os.environ.get("GRAFANA_ADMIN_PASS", "admin")
DASHBOARD_DIR = Path("docs/dashboards")
REPORT_DIR = Path("reports/dashboards")

# Panels that legitimately show "No data" in the local LGTM stack —
# they depend on K8s metrics (kube-state-metrics, cAdvisor) that aren't
# scraped here. Tracked so the assertion isn't noisy in local runs.
EXPECTED_NO_DATA_LOCAL = {
    "grafana-mcp-overview": {"Memory: working set / limit"},
    "grafana-mcp-errors": {
        "Pod restarts (15m increase)",
        "Restarts (1h)",
        # Top error endpoints uses topk(...) which is empty when no rows
        # match — Grafana renders this as "No data" rather than 0.
        "Top error endpoints",
        # 5xx panels are correctly empty in a healthy local stack — the
        # MCP server doesn't 5xx under any of the synthetic loads we
        # apply, so these panels show "No data". In production they
        # would only light up during real incidents.
        "5xx rate %",
        "5xx in range",
        "5xx rate over time",
    },
    # Sessions histograms only emit on session close; if no sessions
    # closed in the load window, the duration heatmap is empty.
    "grafana-mcp-sessions": {"Session-duration heatmap", "p95 session duration"},
}


def _import_dashboard(client: httpx.Client, dashboard_json: dict) -> str:
    payload = {"dashboard": dashboard_json, "overwrite": True, "folderId": 0}
    r = client.post("/api/dashboards/db", json=payload)
    r.raise_for_status()
    return r.json()["url"]


def _get_session_cookie() -> str:
    """Authenticate via Grafana's login endpoint and return the session cookie."""
    with httpx.Client(base_url=GRAFANA_URL, timeout=10) as c:
        r = c.post(
            "/login",
            json={"user": GRAFANA_USER, "password": GRAFANA_PASS},
            follow_redirects=False,
        )
        for k, v in r.cookies.items():
            if k == "grafana_session":
                return v
    raise RuntimeError("could not obtain grafana_session cookie")


@pytest.fixture(scope="session")
def grafana_client() -> httpx.Client:
    with httpx.Client(
        base_url=GRAFANA_URL,
        auth=(GRAFANA_USER, GRAFANA_PASS),
        headers={"Content-Type": "application/json"},
        timeout=30.0,
    ) as c:
        yield c


@pytest.fixture(scope="session")
def imported_dashboards(grafana_client) -> list[dict]:
    results = []
    for path in sorted(DASHBOARD_DIR.glob("*.json")):
        dashboard = json.loads(path.read_text())
        url_slug = _import_dashboard(grafana_client, dashboard)
        results.append({
            "uid": dashboard["uid"],
            "title": dashboard["title"],
            "panels": [p["title"] for p in dashboard["panels"]],
            "url": GRAFANA_URL.rstrip("/") + url_slug,
            "json_path": str(path),
        })
    return results


@pytest.fixture(scope="session")
def chromium_context():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cookie = _get_session_cookie()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1600, "height": 1400},
            ignore_https_errors=True,
        )
        context.add_cookies([{
            "name": "grafana_session",
            "value": cookie,
            "url": GRAFANA_URL,
        }])
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _wait_for_panels_loaded(page, timeout_ms: int = 45_000) -> None:
    """Wait until at least one panel header is visible, then give Grafana
    time to settle queries."""
    page.wait_for_selector(
        '[data-testid^="data-testid Panel header "]',
        timeout=timeout_ms,
    )
    # Grafana 11 streams query results — give them time to settle.
    page.wait_for_timeout(5000)


def _classify_panels(page) -> dict[str, list[str]]:
    """Inspect every rendered panel; classify by data presence.

    Grafana 11 test-ids:
      - `data-testid Panel header <Title>` — header per panel
      - `data-testid panel content`        — body of every panel
    """
    classification: dict[str, list[str]] = {"data": [], "no_data": [], "errored": []}

    headers = page.query_selector_all('[data-testid^="data-testid Panel header "]')
    for header in headers:
        testid = header.get_attribute("data-testid") or ""
        title = testid.replace("data-testid Panel header ", "").strip() or "<unknown>"

        # The panel container holds the header AND the body — climb to it.
        container = header.evaluate_handle(
            "el => el.closest('[data-viz-panel-key], section, article, .react-grid-item') || el.parentElement"
        ).as_element()
        if not container:
            classification["no_data"].append(title)
            continue

        # No data in Grafana 11 renders as a "No data" message.
        no_data = container.query_selector("text=/^No data$/i")
        # Errors render as a red status icon in the header.
        error = container.query_selector('[data-testid="data-testid Panel status error"]') \
                or container.query_selector('[data-testid*="Panel status error"]')

        if error:
            classification["errored"].append(title)
        elif no_data:
            classification["no_data"].append(title)
        else:
            classification["data"].append(title)

    return classification


def test_dashboard_uids_unique(imported_dashboards) -> None:
    uids = [d["uid"] for d in imported_dashboards]
    assert len(uids) == len(set(uids)), f"duplicate UIDs: {uids}"


@pytest.mark.parametrize("dashboard_idx", range(5))
def test_each_dashboard_renders_with_data(
    chromium_context, imported_dashboards, dashboard_idx: int
) -> None:
    if dashboard_idx >= len(imported_dashboards):
        pytest.skip("dashboard not present yet")
    d = imported_dashboards[dashboard_idx]
    page = chromium_context

    page.goto(
        f"{d['url']}?orgId=1&from=now-30m&to=now&kiosk=tv",
        wait_until="domcontentloaded", timeout=60_000,
    )
    _wait_for_panels_loaded(page)

    classification = _classify_panels(page)
    screenshot = REPORT_DIR / f"{d['uid']}.png"
    page.screenshot(path=str(screenshot), full_page=True)

    expected_no_data = EXPECTED_NO_DATA_LOCAL.get(d["uid"], set())
    unexpected_no_data = set(classification["no_data"]) - expected_no_data
    errored = set(classification["errored"])

    summary = REPORT_DIR / "summary.md"
    if dashboard_idx == 0:
        summary.write_text(
            f"# Dashboard render report\n\n"
            f"Stack: local LGTM compose. Grafana: {GRAFANA_URL}\n\n"
            f"| dashboard | data | no-data (expected) | no-data (unexpected) | errored | screenshot |\n"
            f"|---|---:|---|---|---|---|\n"
        )
    with summary.open("a") as f:
        nd_expected_str = ", ".join(sorted(set(classification["no_data"]) & expected_no_data)) or "—"
        nd_unexpected_str = ", ".join(sorted(unexpected_no_data)) or "—"
        err = ", ".join(sorted(errored)) or "—"
        f.write(
            f"| `{d['uid']}` | {len(classification['data'])} | {nd_expected_str} | "
            f"{nd_unexpected_str} | {err} | [{screenshot.name}]({screenshot.name}) |\n"
        )

    if dashboard_idx == len(imported_dashboards) - 1:
        index = REPORT_DIR / "index.html"
        with index.open("w") as f:
            f.write("<html><body><h1>grafana-mcp dashboard renders</h1>\n")
            for entry in imported_dashboards:
                f.write(
                    f"<h2>{entry['title']}</h2>\n"
                    f"<a href='{entry['uid']}.png'>"
                    f"<img src='{entry['uid']}.png' width='1000'/></a>\n"
                )
            f.write("</body></html>\n")

    print(
        f"\n[dashboards] {d['uid']} — "
        f"data={len(classification['data'])} "
        f"no_data={len(classification['no_data'])} "
        f"errored={len(errored)}"
    )
    if unexpected_no_data:
        print(f"  ⚠ unexpected no-data panels: {sorted(unexpected_no_data)}")
    if errored:
        print(f"  ⚠ errored panels: {sorted(errored)}")

    assert not errored, f"{d['uid']}: errored panels {errored}. See {screenshot}."
    assert len(unexpected_no_data) <= 2, (
        f"{d['uid']}: too many unexpectedly empty panels {sorted(unexpected_no_data)}. "
        f"See {screenshot}."
    )
