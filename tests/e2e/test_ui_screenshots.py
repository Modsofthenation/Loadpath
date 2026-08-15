from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.e2e.conftest import wait_visible_graph

THEME_SHOTS = (
    "obsidian",
    "nord",
    "neon-noir",
    "synthwave",
    "phosphor",
    "paper",
    "sakura",
    "citrus",
    "high-contrast",
)

EXPECTED = (
    "review-empty.png",
    "review.png",
    "review-inspector.png",
    "architecture.png",
    "graph.png",
    "graph-architecture.png",
    "pull-requests.png",
    "settings.png",
    "explorer.png",
    "mcp-consent.png",
    *(f"theme-{theme}.png" for theme in THEME_SHOTS),
)


def _wait_fonts(page) -> None:
    page.wait_for_function("document.fonts ? document.fonts.status === 'loaded' : true", timeout=5_000)


def _shot(page, dest: Path, name: str) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(dest / name), full_page=False)


def _wait_graph(page) -> None:
    wait_visible_graph(page)


@pytest.mark.playwright
def test_ui_review_graph_prs_settings(live_app, tmp_path: Path, browser_page):
    base_url, repo = live_app
    page = browser_page
    page.route(
        "**/api/prs",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"pull_requests":[{"provider":"github","id":"1","number":42,"title":"Invoice.total field change","url":"https://github.com/acme/demo/pull/42","author":"ada","source_branch":"feat/total","target_branch":"main","repo":"acme/demo","state":"open","updated_at":"2026-08-14T00:00:00Z","draft":false}]}',
        ),
    )
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)
    assert page.get_by_test_id("rail").is_visible()
    page.get_by_test_id("review-empty").wait_for()

    dest = Path(os.environ.get("LOADPATH_SCREENSHOT_DIR", str(tmp_path / "shots")))
    dest.mkdir(parents=True, exist_ok=True)

    # Pretty path only when regenerating README assets. CI must not rmtree a
    # shared /tmp directory that the demo instructions also use.
    if os.environ.get("LOADPATH_SCREENSHOT_DIR"):
        pretty = Path("/tmp/acme-billing")
        if pretty.exists():
            shutil.rmtree(pretty)
        shutil.copytree(repo, pretty)
        repo = pretty

    _shot(page, dest, "review-empty.png")
    page.get_by_test_id("repo-path").fill(str(repo))
    page.get_by_test_id("base-ref").fill("HEAD~1")
    page.get_by_test_id("head-ref").fill("HEAD")

    page.get_by_test_id("btn-browse-repo").click()
    page.get_by_test_id("repo-explorer").wait_for()
    page.get_by_test_id("explorer-entry").first.wait_for(timeout=10_000)
    _shot(page, dest, "explorer.png")
    page.get_by_test_id("explorer-cancel").click()
    page.get_by_test_id("repo-explorer").wait_for(state="hidden")

    with page.expect_response(
        lambda r: "/api/index" in r.url and r.request.method == "POST",
        timeout=60_000,
    ) as pending_index:
        page.get_by_test_id("btn-index").click()
    if not pending_index.value.ok:
        pytest.fail(f"index API {pending_index.value.status}: {pending_index.value.text()}")
    page.get_by_test_id("architecture-brief").wait_for(timeout=15_000)
    page.get_by_test_id("architecture-brief").locator(".level").wait_for(timeout=15_000)
    _wait_graph(page)
    page.wait_for_timeout(800)
    _shot(page, dest, "architecture.png")

    with page.expect_response(
        lambda r: "/api/review" in r.url and r.request.method == "POST",
        timeout=60_000,
    ) as pending:
        page.get_by_test_id("btn-review").click()
    response = pending.value
    if not response.ok:
        pytest.fail(f"review API {response.status}: {response.text()}")
    error = page.locator(".error")
    if error.count() and error.inner_text().strip():
        pytest.fail(error.inner_text())
    page.locator(".level").wait_for(timeout=15_000)
    brief = page.get_by_test_id("brief").inner_text()
    assert "MEDIUM" in brief or "LOW" in brief or "HIGH" in brief
    _wait_graph(page)
    page.wait_for_timeout(800)
    _shot(page, dest, "review.png")

    page.locator(".react-flow__node").filter(has_text="InvoiceSerializer").first.click()
    inspector = page.get_by_test_id("graph-inspector")
    inspector.wait_for(timeout=5_000)
    assert page.get_by_test_id("graph-inspector-purpose").inner_text().strip()
    assert "in ·" in page.get_by_test_id("graph-inspector-degree").inner_text()
    assert page.get_by_test_id("graph-inspector-path").inner_text().strip()
    _shot(page, dest, "review-inspector.png")
    page.get_by_test_id("graph-inspector-close").click()
    inspector.wait_for(state="hidden")

    page.get_by_test_id("tab-graph").click()
    page.get_by_test_id("graph-full").wait_for()
    _wait_graph(page)
    page.locator(".react-flow__minimap-node").first.wait_for(timeout=10_000)
    assert page.locator(".react-flow__minimap-node").count() > 3
    assert page.locator(".react-flow__edge").count() > 0
    page.wait_for_timeout(600)
    _shot(page, dest, "graph.png")

    page.get_by_test_id("graph-mode-architecture").click()
    _wait_graph(page)
    page.wait_for_timeout(600)
    _shot(page, dest, "graph-architecture.png")
    page.get_by_test_id("graph-mode-review").click()
    _wait_graph(page)

    page.get_by_test_id("graph-view-3d").click()
    assert page.get_by_test_id("graph-view-3d").get_attribute("aria-pressed") == "true"
    page.get_by_test_id("graph-3d").wait_for(timeout=15_000)
    page.locator("[data-testid='graph-3d-canvas'], [data-testid='graph-3d-fallback']").first.wait_for(timeout=20_000)
    page.get_by_test_id("graph-view-2d").click()
    _wait_graph(page)

    page.get_by_test_id("tab-prs").click()
    page.get_by_test_id("pr-repo").fill("acme/demo")
    page.get_by_test_id("btn-list-prs").click()
    page.get_by_text("#42").wait_for(timeout=10_000)
    _shot(page, dest, "pull-requests.png")

    page.get_by_test_id("tab-settings").click()
    page.get_by_test_id("settings-form").wait_for()
    page.locator('select[name="ai_provider"]').select_option("grok")
    page.get_by_test_id("theme-grid").wait_for()
    _shot(page, dest, "settings.png")

    page.get_by_test_id("tab-review").click()
    page.get_by_test_id("brief").wait_for()
    _wait_graph(page)
    for theme in THEME_SHOTS:
        page.get_by_test_id("theme-select").select_option(theme)
        page.wait_for_function(
            "id => document.documentElement.dataset.theme === id",
            arg=theme,
        )
        page.wait_for_timeout(250)
        _shot(page, dest, f"theme-{theme}.png")

    from loadpath.mcp.oauth import LoadpathOAuthProvider

    oauth = LoadpathOAuthProvider(
        issuer="http://127.0.0.1:7345",
        resource="http://127.0.0.1:7345/mcp",
        pin="123456",
    )
    consent = page.context.new_page()
    consent.set_content(oauth._consent_html("demo", "Cursor"))
    consent.set_viewport_size({"width": 1440, "height": 900})
    consent.wait_for_timeout(200)
    consent.screenshot(path=str(dest / "mcp-consent.png"), full_page=False)
    consent.close()

    for name in EXPECTED:
        path = dest / name
        assert path.is_file(), name
        assert path.stat().st_size > 1000, name
