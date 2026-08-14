from __future__ import annotations

import os
import shutil
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from loadpath.server.app import create_app
from tests.conftest import prepare_review_repo


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def live_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    original_home = Path.home()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(original_home / ".cache" / "ms-playwright"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    pretty = tmp_path / "acme-billing"
    shutil.copytree(repo, pretty)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        thread.join(0.05)
    if not server.started:
        pytest.skip("uvicorn failed to start")
    try:
        yield f"http://127.0.0.1:{port}", pretty
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _playwright_page():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium not available: {exc}")
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    return pw, browser, page


@pytest.mark.playwright
def test_ui_review_graph_prs_settings(live_app, tmp_path: Path):
    base_url, repo = live_app
    pw, browser, page = _playwright_page()
    try:
        page.route(
            "**/api/prs",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"pull_requests":[{"provider":"github","id":"1","number":42,"title":"Invoice.total field change","url":"https://github.com/acme/demo/pull/42","author":"ada","source_branch":"feat/total","target_branch":"main","repo":"acme/demo","state":"open","updated_at":"2026-08-14T00:00:00Z","draft":false}]}',
            ),
        )
        page.goto(base_url, wait_until="networkidle")
        try:
            page.wait_for_function("document.fonts ? document.fonts.status === 'loaded' : true", timeout=5_000)
        except Exception:
            pass
        assert page.get_by_test_id("rail").is_visible()
        page.get_by_test_id("repo-path").fill(str(repo))
        page.get_by_test_id("base-ref").fill("HEAD~1")
        page.get_by_test_id("head-ref").fill("HEAD")

        dest = Path(os.environ.get("LOADPATH_SCREENSHOT_DIR", str(tmp_path / "shots")))
        dest.mkdir(parents=True, exist_ok=True)

        with page.expect_response(
            lambda r: "/api/index" in r.url and r.request.method == "POST",
            timeout=60_000,
        ) as pending_index:
            page.get_by_test_id("btn-index").click()
        if not pending_index.value.ok:
            pytest.fail(f"index API {pending_index.value.status}: {pending_index.value.text()}")
        page.get_by_test_id("architecture-brief").wait_for(timeout=15_000)
        page.get_by_test_id("architecture-brief").locator(".level").wait_for(timeout=15_000)
        page.locator(".react-flow__node").first.wait_for(timeout=15_000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(dest / "architecture.png"), full_page=False)

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
        page.locator(".react-flow__node").first.wait_for(timeout=15_000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(dest / "review.png"), full_page=False)

        page.get_by_test_id("tab-graph").click()
        page.get_by_test_id("graph-full").wait_for()
        page.locator(".react-flow__node").first.wait_for(timeout=15_000)
        page.wait_for_timeout(600)
        page.screenshot(path=str(dest / "graph.png"), full_page=False)

        page.get_by_test_id("tab-prs").click()
        page.get_by_test_id("pr-repo").fill("acme/demo")
        page.get_by_test_id("btn-list-prs").click()
        page.get_by_text("#42").wait_for(timeout=10_000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(dest / "pull-requests.png"), full_page=False)

        page.get_by_test_id("tab-settings").click()
        page.get_by_test_id("settings-form").wait_for()
        page.locator('select[name="ai_provider"]').select_option("grok")
        page.get_by_test_id("theme-grid").wait_for()
        page.get_by_test_id("theme-paper").click()
        page.wait_for_function("document.documentElement.dataset.theme === 'paper'")
        page.wait_for_timeout(200)
        page.screenshot(path=str(dest / "settings.png"), full_page=False)

        page.get_by_test_id("theme-select").select_option("nord")
        page.wait_for_function("document.documentElement.dataset.theme === 'nord'")

        for name in ("architecture.png", "review.png", "graph.png", "pull-requests.png", "settings.png"):
            assert (dest / name).stat().st_size > 1000
    finally:
        browser.close()
        pw.stop()
