from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loadpath.providers.scm import BitbucketProvider, GitHubProvider, GitLabProvider
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
    kept = c.put("/api/settings", json={"github_token": "", "bitbucket_token": "", "ai_api_key": ""})
    assert kept.json()["github_token_set"] is True


def test_github_upserts_single_loadpath_comment():
    import httpx

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"id": 9, "body": "<!-- loadpath-review -->\nold"}],
            )
        return httpx.Response(200, json={"id": 9, "html_url": "https://github.com/acme/demo/issues/1#issuecomment-9"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gh = GitHubProvider("tok", client=client)
    posted = gh.upsert_pull_request_comment("acme/demo", 12, "## Loadpath: MEDIUM")
    assert posted["updated"] is True
    assert any(c.method == "PATCH" for c in calls)
    assert not any(c.method == "POST" and "/issues/12/comments" in str(c.url) for c in calls)


def test_github_rejects_unsafe_repo_slug():
    import pytest

    from loadpath.providers.scm import parse_remote_url, require_repo_slug

    gh = GitHubProvider("tok")
    with pytest.raises(ValueError):
        gh.list_pull_requests("../etc/passwd")
    with pytest.raises(ValueError):
        require_repo_slug("acme/../passwd")
    with pytest.raises(ValueError):
        require_repo_slug("acme/./demo")
    assert require_repo_slug("acme/billing/demo") == "acme/billing/demo"
    assert parse_remote_url("https://github.com/../etc/passwd") is None


def test_parse_remote_url_github_and_bitbucket():
    from loadpath.providers.scm import parse_remote_url

    assert parse_remote_url("git@github.com:Acme/Demo.git") == ("github", "Acme/Demo")
    assert parse_remote_url("https://github.com/Acme/Demo") == ("github", "Acme/Demo")
    assert parse_remote_url("https://x-access-token:tok@github.com/acme/demo.git") == ("github", "acme/demo")
    assert parse_remote_url("https://bitbucket.org/acme/demo.git") == ("bitbucket", "acme/demo")
    assert parse_remote_url("git@bitbucket.org:acme/demo.git") == ("bitbucket", "acme/demo")
    assert parse_remote_url("https://gitlab.com/acme/demo.git") == ("gitlab", "acme/demo")
    assert parse_remote_url("git@gitlab.com:acme/demo.git") == ("gitlab", "acme/demo")
    assert parse_remote_url("https://gitlab.example.com/acme/demo.git") == ("gitlab", "acme/demo")
    assert parse_remote_url("https://gitlab.com/acme/billing/demo.git") == ("gitlab", "acme/billing/demo")
    assert parse_remote_url("git@gitlab.com:acme/billing/demo.git") == ("gitlab", "acme/billing/demo")


def test_github_lists_repositories_across_pages():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "ada", "html_url": "https://github.com/ada"})
        page = int(request.url.params.get("page") or "1")
        if page == 1:
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "acme/demo",
                        "html_url": "https://github.com/acme/demo",
                        "private": True,
                        "default_branch": "main",
                        "updated_at": "2026-08-14T00:00:00Z",
                        "description": "billing",
                    }
                ]
                + [
                    {
                        "full_name": f"acme/r{i}",
                        "html_url": f"https://github.com/acme/r{i}",
                        "private": False,
                        "default_branch": "main",
                        "updated_at": "2026-08-14T00:00:00Z",
                        "description": "",
                    }
                    for i in range(99)
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "full_name": "acme/extra",
                    "html_url": "https://github.com/acme/extra",
                    "private": False,
                    "default_branch": "main",
                    "updated_at": "2026-08-14T00:00:00Z",
                    "description": "",
                }
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gh = GitHubProvider("tok", client=client)
    assert gh.current_user()["login"] == "ada"
    repos = gh.list_repositories(limit=120)
    slugs = {r.slug for r in repos}
    assert "acme/demo" in slugs
    assert "acme/extra" in slugs
    assert len(repos) == 101


def test_bitbucket_lists_repositories_via_next():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2.0/user":
            return httpx.Response(200, json={"username": "bob", "display_name": "Bob"})
        if "after=" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "values": [
                        {
                            "full_name": "acme/ledger",
                            "links": {"html": {"href": "https://bitbucket.org/acme/ledger"}},
                            "is_private": True,
                            "mainbranch": {"name": "main"},
                            "updated_on": "2026-08-14T00:00:00Z",
                            "description": "",
                        }
                    ]
                },
            )
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
                        "description": "app",
                    }
                ],
                "next": "https://api.bitbucket.org/2.0/repositories?role=member&pagelen=50&after=token",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bb = BitbucketProvider("tok", client=client)
    assert bb.current_user()["login"] == "bob"
    repos = bb.list_repositories()
    assert [r.slug for r in repos] == ["acme/demo", "acme/ledger"]


def test_github_enterprise_uses_api_v3():
    gh = GitHubProvider("tok", host="github.example.com")
    assert gh.base == "https://github.example.com/api/v3"
    cloud = GitHubProvider("tok", host="github.com")
    assert cloud.base == "https://api.github.com"


def test_gitlab_lists_merge_requests():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user"):
            return httpx.Response(200, json={"username": "ada", "name": "Ada", "web_url": "https://gitlab.com/ada"})
        return httpx.Response(
            200,
            json=[
                {
                    "id": 90,
                    "iid": 4,
                    "title": "Invoice total",
                    "web_url": "https://gitlab.com/acme/demo/-/merge_requests/4",
                    "author": {"username": "ada"},
                    "source_branch": "feat/total",
                    "target_branch": "main",
                    "state": "opened",
                    "updated_at": "2026-08-14T00:00:00Z",
                    "draft": False,
                    "sha": "abc",
                    "diff_refs": {"base_sha": "def", "head_sha": "abc"},
                }
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gl = GitLabProvider("tok", client=client)
    assert gl.current_user()["login"] == "ada"
    mrs = gl.list_pull_requests("acme/demo")
    assert mrs[0].number == 4
    assert mrs[0].provider == "gitlab"
    assert mrs[0].source_branch == "feat/total"


def test_clone_url_and_fetch_spec():
    from loadpath.providers.pr_fetch import clone_url, fetch_spec, local_pr_ref

    gh = clone_url("github", "acme/demo", "tok")
    assert "x-access-token:tok@" in gh
    assert gh.endswith("github.com/acme/demo.git")
    gl = clone_url("gitlab", "acme/demo", "glpat", "gitlab.example.com")
    assert "oauth2:glpat@" in gl
    assert "gitlab.example.com/acme/demo.git" in gl
    assert fetch_spec("github", 12) == "pull/12/head"
    assert fetch_spec("gitlab", 4) == "merge-requests/4/head"
    assert fetch_spec("bitbucket", 3) == "pull-requests/3/from"
    assert local_pr_ref(12) == "refs/loadpath/pr-12"


def test_redact_secrets_strips_tokens():
    from loadpath.providers.pr_fetch import redact_secrets

    leaked = "fatal: https://oauth2:glpat-secret@gitlab.com/acme/demo.git"
    assert "glpat-secret" not in redact_secrets(leaked, "glpat-secret")
    assert "***" in redact_secrets(leaked, "glpat-secret")


def test_checkout_review_tree_indexes_pr_head(tmp_path, monkeypatch):
    from loadpath.providers import pr_fetch

    monkeypatch.setattr(pr_fetch, "clones_root", lambda: tmp_path / "clones")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess = __import__("subprocess")
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo, stdout=subprocess.DEVNULL)
    subprocess.check_call(["git", "config", "user.email", "lp@test"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "lp"], cwd=repo)
    (repo / "on-main.txt").write_text("main\n")
    subprocess.check_call(["git", "add", "on-main.txt"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "main"], cwd=repo, stdout=subprocess.DEVNULL)
    subprocess.check_call(["git", "checkout", "-b", "pr"], cwd=repo, stdout=subprocess.DEVNULL)
    (repo / "on-pr.txt").write_text("pr\n")
    subprocess.check_call(["git", "add", "on-pr.txt"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "pr"], cwd=repo, stdout=subprocess.DEVNULL)
    pr_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.check_call(["git", "update-ref", "refs/loadpath/pr-9", pr_sha], cwd=repo)
    subprocess.check_call(["git", "checkout", "main"], cwd=repo, stdout=subprocess.DEVNULL)
    tree = pr_fetch.checkout_review_tree(repo, "refs/loadpath/pr-9", 9)
    assert (tree / "on-pr.txt").is_file()
    assert not (repo / "on-pr.txt").exists()
