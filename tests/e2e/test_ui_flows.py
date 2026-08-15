from __future__ import annotations

import pytest


def _wait_fonts(page) -> None:
    try:
        page.wait_for_function("document.fonts ? document.fonts.status === 'loaded' : true", timeout=5_000)
    except Exception:
        pass


def _assert_readable_error(page) -> str:
    error = page.get_by_test_id("error")
    error.wait_for(timeout=10_000)
    text = error.inner_text().strip()
    assert text, "expected an error message"
    assert "{" not in text, text
    assert '"detail"' not in text, text
    return text


@pytest.mark.playwright
def test_ui_empty_path_keys_and_readable_errors(live_app, browser_page):
    base_url, _repo = live_app
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)

    page.get_by_test_id("review-empty").wait_for()
    page.get_by_test_id("btn-review").click()
    text = _assert_readable_error(page)
    assert "repository" in text.lower() or "repo_path" in text.lower()

    page.keyboard.press("Escape")
    page.get_by_test_id("error").wait_for(state="hidden")

    page.get_by_test_id("repo-path").fill("/no/such/loadpath-repo")
    page.get_by_test_id("btn-index").click()
    missing = _assert_readable_error(page)
    assert "not found" in missing.lower()
    page.locator(".brand").click()
    page.keyboard.press("Escape")
    page.get_by_test_id("error").wait_for(state="hidden")

    page.get_by_test_id("tab-prs").click()
    page.get_by_test_id("pr-empty").wait_for()
    page.get_by_test_id("btn-list-prs").click()
    token_err = _assert_readable_error(page)
    assert "token" in token_err.lower()

    page.get_by_test_id("tab-graph").click()
    page.get_by_test_id("graph-empty").wait_for()

    page.locator(".brand").click()
    page.keyboard.press("2")
    page.get_by_test_id("architecture-panel").wait_for()
    page.keyboard.press("3")
    page.get_by_test_id("graph-full").wait_for()
    page.keyboard.press("1")
    page.get_by_test_id("review-layout").wait_for()

    page.get_by_test_id("repo-path").click()
    page.keyboard.press("4")
    page.get_by_test_id("review-layout").wait_for()
    page.get_by_test_id("tab-prs").wait_for()


@pytest.mark.playwright
def test_ui_index_review_graph_copy_and_workspace(live_app, browser_page):
    base_url, repo = live_app
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)
    page.get_by_test_id("repo-path").fill(str(repo))
    page.get_by_test_id("base-ref").fill("HEAD~1")
    page.get_by_test_id("head-ref").fill("HEAD")

    with page.expect_response(
        lambda r: "/api/index" in r.url and r.request.method == "POST",
        timeout=60_000,
    ) as pending_index:
        page.get_by_test_id("btn-index").click()
        page.locator(".progress").wait_for(timeout=5_000)
    if not pending_index.value.ok:
        pytest.fail(f"index API {pending_index.value.status}: {pending_index.value.text()}")

    page.get_by_test_id("architecture-brief").locator(".level").wait_for(timeout=15_000)
    page.wait_for_function("() => !document.querySelector('[data-testid=\"btn-index\"]')?.disabled")
    page.get_by_test_id("workspace-select").wait_for()
    options = page.get_by_test_id("workspace-select").locator("option").all_inner_texts()
    assert any("acme-billing" in opt for opt in options), options

    page.locator(".brand").click()
    page.keyboard.press("Control+Enter")
    page.get_by_test_id("brief").locator(".level").wait_for(timeout=30_000)
    error = page.locator(".error")
    if error.count() and error.inner_text().strip():
        pytest.fail(error.inner_text())

    brief = page.get_by_test_id("brief").inner_text()
    assert "MEDIUM" in brief or "LOW" in brief or "HIGH" in brief
    assert "billing-team" in brief
    assert "MePage" not in brief
    page.locator(".react-flow__node").filter(has_text="InvoicePage").first.wait_for(timeout=15_000)
    page.locator(".react-flow__edge").first.wait_for(timeout=15_000)
    assert page.locator(".react-flow__node").filter(has_text="MePage").count() == 0

    page.get_by_test_id("tab-graph").click()
    page.get_by_test_id("graph-full").wait_for()
    page.locator(".react-flow__node").first.wait_for(timeout=15_000)
    page.locator(".react-flow__edge").first.wait_for(timeout=15_000)
    page.locator(".react-flow__minimap-node").first.wait_for(timeout=10_000)
    page.locator(".react-flow__node").first.click()
    inspector = page.get_by_test_id("graph-inspector")
    inspector.wait_for(timeout=10_000)
    assert inspector.inner_text().strip()
    overflow = inspector.evaluate(
        """el => {
            const pane = el.parentElement;
            const box = el.getBoundingClientRect();
            const paneBox = pane.getBoundingClientRect();
            return {
                content: el.scrollWidth <= el.clientWidth + 1,
                in_pane: box.right <= paneBox.right + 1 && box.left >= paneBox.left - 1,
            };
        }"""
    )
    assert overflow["content"], "selected-node inspector overflows horizontally"
    assert overflow["in_pane"], "selected-node inspector extends outside the graph pane"

    page.get_by_test_id("graph-mode-architecture").click()
    assert page.get_by_test_id("graph-mode-architecture").get_attribute("aria-pressed") == "true"
    page.locator(".react-flow__node").first.wait_for(timeout=15_000)
    page.locator(".react-flow__edge").first.wait_for(timeout=15_000)

    page.get_by_test_id("tab-review").click()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
    page.get_by_test_id("btn-copy-markdown").click()
    page.get_by_test_id("status-note").wait_for(timeout=10_000)
    assert "Copied markdown" in page.get_by_test_id("status-note").inner_text()
    clip = page.evaluate("navigator.clipboard.readText()")
    assert "Loadpath" in clip or "Invoice" in clip or clip.strip()

    page.get_by_test_id("btn-post-comment").click()
    post_err = _assert_readable_error(page)
    assert "pull request" in post_err.lower()


@pytest.mark.playwright
def test_ui_settings_preserve_model_and_theme(live_app, browser_page):
    base_url, _repo = live_app
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)

    page.get_by_test_id("tab-settings").click()
    page.get_by_test_id("settings-form").wait_for()
    page.locator('select[name="ai_provider"]').select_option("grok")
    page.get_by_test_id("ai-model").fill("grok-e2e-model")
    page.get_by_test_id("ai-base-url").fill("https://example.invalid/v1")
    page.get_by_test_id("theme-paper").click()
    page.wait_for_function("document.documentElement.dataset.theme === 'paper'")
    page.get_by_test_id("btn-save-settings").click()
    page.get_by_test_id("status-note").wait_for()

    saved = page.request.get(f"{base_url}/api/settings").json()
    assert saved["ai"]["provider"] == "grok"
    assert saved["ai"]["model"] == "grok-e2e-model"
    assert saved["ai"]["base_url"] == "https://example.invalid/v1"

    page.get_by_test_id("tab-review").click()
    page.get_by_test_id("tab-settings").click()
    page.get_by_test_id("settings-form").wait_for()
    assert page.get_by_test_id("ai-model").input_value() == "grok-e2e-model"
    assert page.get_by_test_id("ai-base-url").input_value() == "https://example.invalid/v1"
    page.get_by_test_id("btn-save-settings").click()
    page.get_by_test_id("status-note").wait_for()
    kept = page.request.get(f"{base_url}/api/settings").json()
    assert kept["ai"]["model"] == "grok-e2e-model"
    assert kept["ai"]["base_url"] == "https://example.invalid/v1"

    page.reload(wait_until="networkidle")
    page.wait_for_function("document.documentElement.dataset.theme === 'paper'")


@pytest.mark.playwright
def test_ui_pr_review_this_range_fills_refs(live_app, browser_page):
    base_url, _repo = live_app
    page = browser_page
    page.route(
        "**/api/prs",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"pull_requests":[{"provider":"github","id":"1","number":42,'
                '"title":"Invoice.total field change",'
                '"url":"https://github.com/acme/demo/pull/42","author":"ada",'
                '"source_branch":"feat/total","target_branch":"main","repo":"acme/demo",'
                '"state":"open","updated_at":"2026-08-14T00:00:00Z","draft":false,'
                '"base_sha":"abc111base","head_sha":"def222head"}]}'
            ),
        ),
    )
    page.goto(base_url, wait_until="networkidle")
    page.get_by_test_id("tab-prs").click()
    page.get_by_test_id("pr-empty").wait_for()
    page.get_by_test_id("pr-repo").fill("acme/demo")
    page.get_by_test_id("btn-list-prs").click()
    page.get_by_test_id("pr-42").wait_for(timeout=10_000)
    page.get_by_test_id("pr-review-42").click()
    page.get_by_test_id("review-layout").wait_for()
    assert page.get_by_test_id("base-ref").input_value() == "abc111base"
    assert page.get_by_test_id("head-ref").input_value() == "def222head"
