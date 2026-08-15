from __future__ import annotations

import shutil
import time

import pytest

from tests.e2e.conftest import wait_visible_graph


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
    page.locator(".react-flow__edge").filter(visible=True).first.wait_for(timeout=15_000)
    assert page.locator(".react-flow__node").filter(has_text="MePage").count() == 0

    page.get_by_test_id("tab-graph").click()
    page.get_by_test_id("graph-full").wait_for()
    wait_visible_graph(page)
    page.locator(".react-flow__minimap-node").first.wait_for(timeout=10_000)
    page.locator(".react-flow__node").first.click()
    inspector = page.get_by_test_id("graph-inspector")
    inspector.wait_for(timeout=10_000)
    assert inspector.inner_text().strip()
    assert page.get_by_test_id("graph-inspector-purpose").inner_text().strip()
    assert page.get_by_test_id("graph-inspector-inputs").is_visible()
    assert page.get_by_test_id("graph-inspector-outputs").is_visible()
    degree = page.get_by_test_id("graph-inspector-degree").inner_text()
    assert "in ·" in degree and "out" in degree
    path = page.get_by_test_id("graph-inspector-path")
    if path.count():
        assert path.inner_text().strip()
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

    page.get_by_test_id("graph-view-3d").click()
    assert page.get_by_test_id("graph-view-3d").get_attribute("aria-pressed") == "true"
    page.get_by_test_id("graph-3d").wait_for(timeout=15_000)
    page.locator("[data-testid='graph-3d-canvas'], [data-testid='graph-3d-fallback']").first.wait_for(timeout=20_000)
    page.get_by_test_id("graph-view-2d").click()
    page.locator(".react-flow__node").first.wait_for(timeout=15_000)

    page.get_by_test_id("graph-mode-architecture").click()
    assert page.get_by_test_id("graph-mode-architecture").get_attribute("aria-pressed") == "true"
    wait_visible_graph(page)

    page.get_by_test_id("tab-review").click()
    page.get_by_test_id("merge-box").wait_for()
    page.get_by_test_id("merge-checklist").wait_for()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
    page.get_by_test_id("btn-copy-markdown").click()
    page.get_by_test_id("status-note").wait_for(timeout=10_000)
    assert "Copied markdown" in page.get_by_test_id("status-note").inner_text()
    clip = page.evaluate("navigator.clipboard.readText()")
    assert "Loadpath" in clip or "Invoice" in clip or clip.strip()

    page.locator(".brand").click()
    page.keyboard.press("Control+K")
    page.get_by_test_id("command-palette").wait_for()
    page.get_by_test_id("command-palette-input").fill("Impact graph")
    page.keyboard.press("Enter")
    page.get_by_test_id("graph-full").wait_for()
    page.get_by_test_id("graph-search").fill("Invoice")
    page.get_by_test_id("graph-search-hits").wait_for()
    page.get_by_test_id("graph-neighborhood").wait_for()
    page.get_by_test_id("graph-test-overlay").click()
    assert page.get_by_test_id("graph-test-overlay").get_attribute("aria-pressed") == "true"

    page.get_by_test_id("tab-review").click()
    page.get_by_test_id("btn-export-html").click()
    page.get_by_test_id("status-note").wait_for(timeout=10_000)

    page.get_by_test_id("btn-post-comment").click()
    post_err = _assert_readable_error(page)
    assert "pull request" in post_err.lower()


@pytest.mark.playwright
def test_ui_index_polls_progress_endpoint(live_app, browser_page):
    import time

    base_url, repo = live_app
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)
    page.get_by_test_id("repo-path").fill(str(repo))

    progress_hits: list[str] = []

    def on_route(route):
        req = route.request
        url = req.url
        if "/api/index/progress" in url:
            progress_hits.append(url)
            route.continue_()
            return
        if req.method == "POST" and url.rstrip("/").endswith("/api/index"):
            time.sleep(1.2)
            route.continue_()
            return
        route.continue_()

    page.route("**/api/**", on_route)
    with page.expect_response(
        lambda r: r.url.rstrip("/").endswith("/api/index") and r.request.method == "POST",
        timeout=60_000,
    ):
        page.get_by_test_id("btn-index").click()
        page.locator(".progress").wait_for(timeout=5_000)
        page.wait_for_function(
            """() => {
              const t = document.querySelector('.rail-foot .muted')?.textContent || '';
              return /Extract|Scan|Stitch|Indexed|Boot|Hashed/.test(t);
            }""",
            timeout=10_000,
        )
        page.screenshot(path="/opt/cursor/artifacts/index_progress_bar.png")
    page.get_by_test_id("architecture-brief").locator(".level").wait_for(timeout=15_000)
    assert progress_hits, "UI should poll GET /api/index/progress while indexing"
    page.screenshot(path="/opt/cursor/artifacts/index_complete_architecture.png")


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


@pytest.mark.playwright
def test_ui_browse_repo_and_pick_git_refs(live_app, browser_page):
    base_url, repo = live_app
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)

    page.get_by_test_id("repo-path").fill(str(repo))
    page.get_by_test_id("btn-browse-repo").click()
    explorer = page.get_by_test_id("repo-explorer")
    explorer.wait_for()
    page.get_by_test_id("explorer-path").wait_for()
    page.wait_for_function(
        "path => document.querySelector('[data-testid=\"explorer-path\"]')?.value.includes(path)",
        arg=repo.name,
    )
    page.get_by_test_id("explorer-use").click()
    explorer.wait_for(state="hidden")
    first = page.get_by_test_id("repo-path").input_value()
    assert repo.name in first

    page.get_by_test_id("btn-browse-repo").click()
    explorer.wait_for()
    page.get_by_test_id("explorer-path").fill(str(repo.parent))
    page.get_by_role("button", name="Go").click()
    page.get_by_test_id("explorer-entry").filter(has_text=repo.name).wait_for()
    page.get_by_test_id("explorer-entry").filter(has_text=repo.name).click()
    page.get_by_test_id("explorer-use").click()
    explorer.wait_for(state="hidden")
    chosen = page.get_by_test_id("repo-path").input_value()
    assert repo.name in chosen

    page.get_by_test_id("base-ref").fill("custom-base")
    assert page.get_by_test_id("base-ref").input_value() == "custom-base"

    with page.expect_response(lambda r: "/api/git/refs" in r.url, timeout=15_000):
        page.get_by_test_id("base-ref-toggle").click()
    menu = page.get_by_test_id("base-ref-menu")
    menu.wait_for()
    menu.get_by_text("HEAD~1", exact=True).wait_for()
    menu.get_by_test_id("ref-option-commit").filter(has_text="tighten Invoice.total contract").wait_for()
    menu.get_by_test_id("ref-option-commit").filter(has_text="baseline").click()
    selected = page.get_by_test_id("base-ref").input_value()
    assert selected != "custom-base"
    assert len(selected) >= 7

    page.get_by_test_id("head-ref-toggle").click()
    heads = page.get_by_test_id("head-ref-menu")
    heads.wait_for()
    heads.get_by_test_id("ref-option-branch").filter(has_text="main").click()
    assert page.get_by_test_id("head-ref").input_value() == "main"


@pytest.mark.playwright
def test_ui_oauth_login_and_remote_repo_list(live_app, browser_page):
    base_url, _repo = live_app
    page = browser_page
    page.request.put(
        f"{base_url}/api/settings",
        headers={"Content-Type": "application/json"},
        data='{"github_oauth_client_id":"Ov23ui","github_token":"ghp_ui_token"}',
    )
    page.route(
        "**/api/scm/repos**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"provider":"github","user":{"login":"ada","name":"Ada","url":"https://github.com/ada"},'
                '"repos":[{"provider":"github","slug":"acme/demo","name":"demo","owner":"acme",'
                '"url":"https://github.com/acme/demo","private":true,"default_branch":"main",'
                '"updated_at":"","description":"","local_path":null},'
                '{"provider":"github","slug":"acme/ledger","name":"ledger","owner":"acme",'
                '"url":"https://github.com/acme/ledger","private":false,"default_branch":"main",'
                '"updated_at":"","description":"","local_path":null}]}'
            ),
        ),
    )
    page.route(
        "**/api/oauth/github/start",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"flow_id":"flow1","user_code":"WXYZ-9876",'
                '"verification_uri":"https://github.com/login/device",'
                '"verification_uri_complete":"https://github.com/login/device?user_code=WXYZ-9876",'
                '"interval":5,"expires_in":900}'
            ),
        ),
    )
    page.add_init_script("window.open = () => null;")
    page.goto(base_url, wait_until="networkidle")

    page.get_by_test_id("tab-prs").click()
    page.get_by_test_id("scm-repo-count").wait_for(timeout=10_000)
    assert "2 github repositories" in page.get_by_test_id("scm-repo-count").inner_text()
    page.get_by_test_id("pr-repo").fill("acme/demo")

    page.get_by_test_id("tab-settings").click()
    page.get_by_test_id("settings-form").wait_for()
    assert "ada" in page.get_by_test_id("scm-github").inner_text().lower() or "token saved" in page.get_by_test_id("scm-github").inner_text().lower()
    page.get_by_test_id("btn-github-disconnect").click()
    page.get_by_test_id("btn-github-login").wait_for()
    page.get_by_test_id("btn-github-login").click()
    page.get_by_test_id("github-user-code").wait_for()
    assert "WXYZ-9876" in page.get_by_test_id("github-user-code").inner_text()


def _index_repo(page, repo) -> None:
    page.get_by_test_id("repo-path").fill(str(repo))
    with page.expect_response(
        lambda r: "/api/index" in r.url and r.request.method == "POST",
        timeout=60_000,
    ) as pending:
        page.get_by_test_id("btn-index").click()
        page.locator(".progress").wait_for(timeout=5_000)
    if not pending.value.ok:
        pytest.fail(f"index API {pending.value.status}: {pending.value.text()}")
    page.wait_for_function("() => !document.querySelector('[data-testid=\"btn-index\"]')?.disabled")


@pytest.mark.playwright
def test_ui_workspace_switch_shows_loading(live_app, browser_page):
    base_url, repo = live_app
    other = repo.parent / "other-billing"
    shutil.copytree(repo, other)
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)

    _index_repo(page, repo)
    _index_repo(page, other)
    page.get_by_test_id("workspace-select").wait_for()
    assert page.get_by_test_id("workspace-select").input_value() == str(other)
    page.get_by_test_id("tab-review").click()
    page.get_by_test_id("review-empty").wait_for()

    page.evaluate(
        """() => {
          const orig = window.fetch;
          window.fetch = async (input, init) => {
            const url = String(typeof input === "string" ? input : input.url);
            if (url.includes("/api/architecture")) {
              await new Promise((resolve) => setTimeout(resolve, 800));
            }
            return orig.call(window, input, init);
          };
        }"""
    )

    page.get_by_test_id("workspace-select").select_option(value=str(repo))
    loading = page.get_by_test_id("workspace-loading")
    loading.wait_for(timeout=5_000)
    assert "loading" in loading.inner_text().lower()
    page.get_by_test_id("progress").wait_for()
    loading.wait_for(state="hidden", timeout=15_000)
    assert page.get_by_test_id("workspace-select").input_value() == str(repo)
    page.get_by_test_id("review-empty").wait_for()


@pytest.mark.playwright
def test_ui_architecture_brief_paints_before_graph(live_app, browser_page):
    base_url, repo = live_app
    page = browser_page
    page.goto(base_url, wait_until="networkidle")
    _wait_fonts(page)

    def on_route(route):
        if "/api/architecture/graph" in route.request.url:
            time.sleep(1.2)
        route.continue_()

    page.route("**/api/**", on_route)
    page.get_by_test_id("repo-path").fill(str(repo))
    _index_repo(page, repo)
    page.get_by_test_id("architecture-brief").locator(".level").wait_for(timeout=20_000)
    page.get_by_test_id("graph-loading").wait_for()
    assert "drawing" in page.get_by_test_id("graph-loading").inner_text().lower()
    page.get_by_test_id("graph-loading").wait_for(state="hidden", timeout=20_000)
    wait_visible_graph(page)

