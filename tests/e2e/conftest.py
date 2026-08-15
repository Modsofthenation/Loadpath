from __future__ import annotations

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


@pytest.fixture
def browser_page():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium not available: {exc}")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = context.new_page()
    try:
        yield page
    finally:
        browser.close()
        pw.stop()
