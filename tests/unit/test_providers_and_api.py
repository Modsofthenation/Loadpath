from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loadpath.providers.scm import BitbucketProvider, GitHubProvider
from loadpath.server.app import create_app
from loadpath.settings import AppSettings


def test_github_lists_pull_requests():
    import httpx

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200,
        json=[
            {
                "id": 9,
                "number": 12,
                "title": "Invoice total",
                "html_url": "https://github.com/acme/demo/pull/12",
                "user": {"login": "ada"},
                "head": {"ref": "feat/total"},
                "base": {"ref": "main"},
                "state": "open",
                "updated_at": "2026-08-14T00:00:00Z",
                "draft": False,
            }
        ],
    )))
    gh = GitHubProvider("tok", client=client)
    prs = gh.list_pull_requests("acme/demo")
    assert prs[0].number == 12
    assert prs[0].source_branch == "feat/total"


def test_bitbucket_lists_pull_requests():
    import httpx

    payload = {
        "values": [
            {
                "id": 3,
                "title": "auth",
                "links": {"html": {"href": "https://bitbucket.org/acme/demo/pull-requests/3"}},
                "author": {"display_name": "bob"},
                "source": {"branch": {"name": "feat"}},
                "destination": {"branch": {"name": "main"}},
                "state": "OPEN",
                "updated_on": "2026-08-14T00:00:00Z",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bb = BitbucketProvider("tok", username="bob", client=client)
    prs = bb.list_pull_requests("acme/demo")
    assert prs[0].number == 3
    assert prs[0].provider == "bitbucket"


def test_health_and_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    app = create_app()
    c = TestClient(app)
    assert c.get("/api/health").json()["status"] == "ok"
    r = c.put("/api/settings", json={"github_token": "ghp_secret_token", "ai_provider": "anthropic"})
    body = r.json()
    assert body["github_token_set"] is True
    assert "secret" not in body["github_token"]
    assert body["ai"]["provider"] == "anthropic"
