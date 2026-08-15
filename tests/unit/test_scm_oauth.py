from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from loadpath.providers.oauth import GITHUB_DEVICE_CODE_URL, GITHUB_TOKEN_URL
from loadpath.providers.scm import attach_local_paths, parse_remote_url
from loadpath.server.app import create_app
from loadpath.settings import AppSettings


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("LOADPATH_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("LOADPATH_BITBUCKET_CLIENT_ID", raising=False)
    monkeypatch.delenv("LOADPATH_BITBUCKET_CLIENT_SECRET", raising=False)
    return TestClient(create_app())


def test_attach_local_paths_from_git_remote(tmp_path):
    repo = tmp_path / "demo"
    repo.mkdir()
    import subprocess

    subprocess.check_call(["git", "init"], cwd=repo, stdout=subprocess.DEVNULL)
    subprocess.check_call(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/demo.git"],
        stdout=subprocess.DEVNULL,
    )
    from loadpath.providers.scm import RemoteRepo

    repos = [
        RemoteRepo(provider="github", slug="acme/demo", name="demo", owner="acme", url="https://github.com/acme/demo"),
        RemoteRepo(provider="github", slug="other/app", name="app", owner="other", url="https://github.com/other/app"),
    ]
    attach_local_paths(repos, [str(repo)])
    assert repos[0].local_path == str(repo.resolve())
    assert repos[1].local_path is None
    assert parse_remote_url("git@github.com:acme/demo.git") == ("github", "acme/demo")


def test_oauth_status_and_client_id_settings(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    status = client.get("/api/oauth/status").json()
    assert status["github"]["oauth_ready"] is False
    assert status["github"]["connected"] is False
    saved = client.put(
        "/api/settings",
        json={
            "github_oauth_client_id": "Ov23test",
            "bitbucket_oauth_client_id": "bbkey",
            "bitbucket_oauth_client_secret": "bbsecret",
        },
    )
    body = saved.json()
    assert body["github_oauth_ready"] is True
    assert body["bitbucket_oauth_ready"] is True
    assert "bbsecret" not in body["bitbucket_oauth_client_secret"]
    kept = client.put("/api/settings", json={"bitbucket_oauth_client_secret": ""})
    assert kept.json()["bitbucket_oauth_ready"] is True


@respx.mock
def test_github_device_flow_saves_token_and_lists_repos(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put("/api/settings", json={"github_oauth_client_id": "Ov23test"})
    respx.post(GITHUB_DEVICE_CODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dev-1",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "verification_uri_complete": "https://github.com/login/device?user_code=ABCD-1234",
                "expires_in": 900,
                "interval": 5,
            },
        )
    )
    started = client.post("/api/oauth/github/start")
    assert started.status_code == 200, started.text
    flow = started.json()
    assert flow["user_code"] == "ABCD-1234"
    assert flow["flow_id"]

    token_replies = iter(
        [
            httpx.Response(200, json={"error": "authorization_pending"}),
            httpx.Response(200, json={"access_token": "gho_oauth_token", "token_type": "bearer"}),
        ]
    )
    respx.post(GITHUB_TOKEN_URL).mock(side_effect=lambda _request: next(token_replies))
    pending = client.post("/api/oauth/github/poll", json={"flow_id": flow["flow_id"]})
    assert pending.json()["status"] == "pending"
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"login": "ada", "html_url": "https://github.com/ada"})
    )
    done = client.post("/api/oauth/github/poll", json={"flow_id": flow["flow_id"]})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "complete"
    assert done.json()["user"] == "ada"
    settings = AppSettings.load()
    assert settings.github_token == "gho_oauth_token"
    assert settings.github_user == "ada"

    respx.get("https://api.github.com/user/repos").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "full_name": "acme/demo",
                    "html_url": "https://github.com/acme/demo",
                    "private": True,
                    "default_branch": "main",
                    "updated_at": "2026-08-14T00:00:00Z",
                    "description": "",
                }
            ],
        )
    )
    listed = client.get("/api/scm/repos", params={"provider": "github"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["repos"][0]["slug"] == "acme/demo"
    assert listed.json()["user"]["login"] == "ada"

    disconnected = client.post("/api/oauth/disconnect", json={"provider": "github"})
    assert disconnected.json()["github_token_set"] is False


@respx.mock
def test_bitbucket_oauth_callback_lists_all_repos(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put(
        "/api/settings",
        json={"bitbucket_oauth_client_id": "bbkey", "bitbucket_oauth_client_secret": "bbsecret"},
    )
    started = client.get("/api/oauth/bitbucket/start")
    assert started.status_code == 200, started.text
    flow = started.json()
    assert "client_id=bbkey" in flow["authorize_url"]
    assert flow["flow_id"]

    respx.post("https://bitbucket.org/site/oauth2/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "bb_oauth", "refresh_token": "bb_refresh", "token_type": "bearer"},
        )
    )
    respx.get("https://api.bitbucket.org/2.0/user").mock(
        return_value=httpx.Response(200, json={"username": "bob", "display_name": "Bob"})
    )
    callback = client.get(
        "/api/oauth/bitbucket/callback",
        params={"code": "auth-code", "state": flow["flow_id"]},
    )
    assert callback.status_code == 200, callback.text
    assert "Connected to Bitbucket" in callback.text
    settings = AppSettings.load()
    assert settings.bitbucket_token == "bb_oauth"
    assert settings.bitbucket_refresh_token == "bb_refresh"
    assert settings.bitbucket_user == "bob"
    assert settings.bitbucket_username == ""

    respx.get("https://api.bitbucket.org/2.0/repositories").mock(
        return_value=httpx.Response(
            200,
            json={
                "values": [
                    {
                        "full_name": "acme/demo",
                        "links": {"html": {"href": "https://bitbucket.org/acme/demo"}},
                        "is_private": True,
                        "mainbranch": {"name": "main"},
                        "updated_on": "2026-08-14T00:00:00Z",
                    }
                ]
            },
        )
    )
    listed = client.get("/api/scm/repos", params={"provider": "bitbucket"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["repos"][0]["slug"] == "acme/demo"


@respx.mock
def test_bitbucket_refreshes_expired_oauth_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    seeded = AppSettings(
        bitbucket_token="expired",
        bitbucket_refresh_token="bb_refresh",
        bitbucket_oauth_client_id="bbkey",
        bitbucket_oauth_client_secret="bbsecret",
    )
    seeded.save()
    calls = {"repos": 0}

    def repos_handler(request: httpx.Request) -> httpx.Response:
        calls["repos"] += 1
        auth = request.headers.get("authorization") or ""
        if auth.endswith("fresh_token"):
            return httpx.Response(
                200,
                json={
                    "values": [
                        {
                            "full_name": "acme/demo",
                            "links": {"html": {"href": "https://bitbucket.org/acme/demo"}},
                            "is_private": False,
                            "mainbranch": {"name": "main"},
                            "updated_on": "2026-08-14T00:00:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(401, json={"error": "unauthorized"})

    respx.get("https://api.bitbucket.org/2.0/repositories").mock(side_effect=repos_handler)
    respx.get("https://api.bitbucket.org/2.0/user").mock(
        return_value=httpx.Response(200, json={"username": "bob", "display_name": "Bob"})
    )
    respx.post("https://bitbucket.org/site/oauth2/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "fresh_token", "refresh_token": "bb_refresh2"})
    )
    listed = client.get("/api/scm/repos", params={"provider": "bitbucket"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["repos"][0]["slug"] == "acme/demo"
    assert AppSettings.load().bitbucket_token == "fresh_token"


def test_github_oauth_start_requires_client_id(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    res = client.post("/api/oauth/github/start")
    assert res.status_code == 400
    assert "client ID" in res.json()["detail"]
