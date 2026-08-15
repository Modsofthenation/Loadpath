from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

from loadpath.server.app import create_app
from tests.conftest import prepare_review_repo


def test_api_health_index_review_graph_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    client = TestClient(create_app())

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    indexed = client.post("/api/index", json={"repo_path": str(repo), "incremental": False})
    assert indexed.status_code == 200, indexed.text
    summary = indexed.json()
    assert summary["counts"]["nodes"] > 20
    assert "billing" in summary["contexts"]
    assert summary["indexed_at"]
    assert "django.task" in summary["type_counts"]

    status = client.get("/api/index", params={"repo_path": str(repo)})
    assert status.json()["indexed"] is True
    assert "nodes" not in status.json() or status.json().get("nodes") is None

    repos = client.get("/api/repos")
    assert any(r["path"] == str(repo.resolve()) for r in repos.json()["repos"])

    arch = client.get("/api/architecture", params={"repo_path": str(repo)})
    assert arch.status_code == 200
    body_arch = arch.json()
    assert body_arch["indexed"] is True
    assert "django_boot" in body_arch
    assert any(n["name"] == "InvoicePage" for n in body_arch["nodes"])
    assert "celery_tasks_must_be_idempotent_on_model_pk" in body_arch["rules"]

    review = client.post(
        "/api/review",
        json={"repo_path": str(repo), "base": "HEAD~1", "head": "HEAD", "reindex": False},
    )
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["confidence"]["level"] in {"high", "medium", "low"}
    names = {n["name"] for n in body["nodes"]}
    assert "InvoicePage" in names
    assert "send_invoice_email" in names
    assert "rebuild_ledger" in names
    assert "markdown" in body
    assert "Celery" in body["headline"] or "celery" in body["headline"].lower()
    assert "Dramatiq" in body["headline"] or "dramatiq" in body["headline"].lower()
    assert body["index"]["counts"]["nodes"] > 20
    assert body["index"]["reindexed"] is False
    assert "workspace" in body
    assert body["index"]["django_boot"] == "off"
    assert body["checklist"]
    assert body["seed_ids"]
    assert body["marks"]
    assert "node_roles" in body

    listed = client.get("/api/reviews", params={"repo_path": str(repo)})
    assert listed.status_code == 200
    assert listed.json()["reviews"]
    review_id = listed.json()["reviews"][0]["id"]
    stored = client.get(f"/api/reviews/{review_id}", params={"repo_path": str(repo)})
    assert stored.status_code == 200
    assert stored.json()["markdown"]
    marks = client.get("/api/marks", params={"repo_path": str(repo)})
    assert marks.json()["files"]
    health = client.get("/api/architecture/health", params={"repo_path": str(repo)})
    assert health.json()["points"]
    status = client.get("/api/workspace/status", params={"repo_path": str(repo)})
    assert status.json()["fingerprint"]
    html = client.get(f"/api/reviews/{review_id}/html", params={"repo_path": str(repo)})
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]

    cfg = client.get("/api/config", params={"repo_path": str(repo)})
    assert "billing" in cfg.json()["contexts"]
    assert "waivers" in cfg.json()
    waived = client.post(
        "/api/config/waiver",
        json={"repo_path": str(repo), "rule": "leaked_seam", "reason": "e2e"},
    )
    assert waived.status_code == 200
    assert any(w["rule"] == "leaked_seam" for w in waived.json()["waivers"])

    init = client.post("/api/init", json={"repo_path": str(repo)})
    assert init.status_code == 200
    assert init.json()["wrote"] is False
    assert init.json()["django_root"] == "backend"

    graph = client.get("/api/graph", params={"repo_path": str(repo), "scope": "architecture"})
    assert graph.status_code == 200
    assert graph.json()["scope"] == "architecture"
    assert graph.json()["counts"]["edges"] > 0

    cfg = client.get("/api/config", params={"repo_path": str(repo)})
    assert "billing" in cfg.json()["contexts"]

    saved = client.put(
        "/api/settings",
        json={"github_token": "ghp_e2e_token_value", "ai_provider": "grok"},
    )
    assert saved.json()["github_token_set"] is True
    assert "e2e_token" not in json.dumps(saved.json())
    assert saved.json()["ai"]["provider"] == "grok"

    home = client.get("/")
    assert home.status_code == 200
    assert b"Loadpath" in home.content


def test_review_without_index_is_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    db = repo / ".loadpath" / "graph.sqlite3"
    if db.exists():
        db.unlink()
    client = TestClient(create_app())
    review = client.post(
        "/api/review",
        json={"repo_path": str(repo), "base": "HEAD~1", "head": "HEAD", "reindex": False},
    )
    assert review.status_code == 409


@respx.mock
def test_api_lists_github_and_bitbucket_prs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    client = TestClient(create_app())
    client.put("/api/settings", json={"github_token": "ghp_test", "bitbucket_token": "bb_test"})

    respx.get("https://api.github.com/repos/acme/demo/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 42,
                    "title": "Invoice total field",
                    "html_url": "https://github.com/acme/demo/pull/42",
                    "user": {"login": "ada"},
                    "head": {"ref": "feat/total"},
                    "base": {"ref": "main"},
                    "state": "open",
                    "updated_at": "2026-08-14T00:00:00Z",
                    "draft": False,
                }
            ],
        )
    )
    gh = client.post("/api/prs", json={"provider": "github", "repo": "acme/demo"})
    assert gh.status_code == 200, gh.text
    assert gh.json()["pull_requests"][0]["number"] == 42

    respx.get("https://api.github.com/repos/acme/demo/issues/42/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.post("https://api.github.com/repos/acme/demo/issues/42/comments").mock(
        return_value=httpx.Response(
            201,
            json={"id": 88, "html_url": "https://github.com/acme/demo/pull/42#issuecomment-88"},
        )
    )
    posted = client.post(
        "/api/prs/comment",
        json={"provider": "github", "repo": "acme/demo", "number": 42, "markdown": "## Loadpath: MEDIUM"},
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["updated"] is False
    assert posted.json()["id"] == "88"

    respx.get("https://api.bitbucket.org/2.0/repositories/acme/demo/pullrequests").mock(
        return_value=httpx.Response(
            200,
            json={
                "values": [
                    {
                        "id": 7,
                        "title": "ledger",
                        "links": {"html": {"href": "https://bitbucket.org/acme/demo/pull-requests/7"}},
                        "author": {"display_name": "bob"},
                        "source": {"branch": {"name": "feat"}},
                        "destination": {"branch": {"name": "main"}},
                        "state": "OPEN",
                        "updated_on": "2026-08-14T00:00:00Z",
                    }
                ]
            },
        )
    )
    bb = client.post("/api/prs", json={"provider": "bitbucket", "repo": "acme/demo"})
    assert bb.status_code == 200, bb.text
    assert bb.json()["pull_requests"][0]["provider"] == "bitbucket"


def test_api_whatif_and_gitlab_mrs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    client = TestClient(create_app())
    indexed = client.post("/api/index", json={"repo_path": str(repo), "incremental": False})
    assert indexed.status_code == 200, indexed.text
    walked = client.post(
        "/api/whatif",
        json={"repo_path": str(repo), "node_id": "django.field:billing.Invoice.total"},
    )
    assert walked.status_code == 200, walked.text
    body = walked.json()
    assert body["what_if"] is True
    assert body["nodes"]
    assert body["sinks"]
    dirty = client.post(
        "/api/review",
        json={"repo_path": str(repo), "base": "HEAD~1", "head": "HEAD", "reindex": False, "dirty": True},
    )
    assert dirty.status_code == 200, dirty.text
    assert dirty.json()["workspace"]["dirty_included"] is True
    assert dirty.json()["contract_break"]["kind"] in {"breaking", "additive", "drift", "none"}


@respx.mock
def test_api_lists_gitlab_merge_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    client = TestClient(create_app())
    client.put("/api/settings", json={"gitlab_token": "glpat_test", "gitlab_host": "gitlab.com"})
    respx.get("https://gitlab.com/api/v4/projects/acme%2Fdemo/merge_requests").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 9,
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
                }
            ],
        )
    )
    gl = client.post("/api/prs", json={"provider": "gitlab", "repo": "acme/demo"})
    assert gl.status_code == 200, gl.text
    assert gl.json()["pull_requests"][0]["number"] == 4
    assert gl.json()["pull_requests"][0]["provider"] == "gitlab"


def test_blank_and_missing_repo_path_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    client = TestClient(create_app())
    for method, url, payload in (
        ("POST", "/api/index", {"repo_path": ""}),
        ("POST", "/api/index", {"repo_path": "   "}),
        ("POST", "/api/review", {"repo_path": "", "base": "HEAD"}),
        ("POST", "/api/init", {"repo_path": ""}),
    ):
        r = client.request(method, url, json=payload)
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "repo_path is required"

    for url in ("/api/architecture", "/api/graph", "/api/config", "/api/detect", "/api/index"):
        r = client.get(url, params={"repo_path": ""})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "repo_path is required"

    missing = client.post("/api/index", json={"repo_path": "/no/such/loadpath-repo"})
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"].lower()


def test_api_browse_fs_and_git_refs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    client = TestClient(create_app())

    home = client.get("/api/fs")
    assert home.status_code == 200
    assert home.json()["path"] == str((tmp_path / "home").resolve())

    listing = client.get("/api/fs", params={"path": str(repo.parent)})
    assert listing.status_code == 200
    names = {item["name"]: item for item in listing.json()["entries"]}
    assert names[repo.name]["is_git"] is True

    here = client.get("/api/fs", params={"path": str(repo)})
    assert here.json()["is_git"] is True

    refs = client.get("/api/git/refs", params={"repo_path": str(repo), "limit": 50})
    assert refs.status_code == 200, refs.text
    body = refs.json()
    assert body["git"] is True
    assert body["presets"] == ["HEAD", "HEAD~1"]
    subjects = [c["subject"] for c in body["commits"]]
    assert "tighten Invoice.total contract" in subjects
    assert any(b["name"] == "main" for b in body["branches"])
    assert len(body["commits"]) <= 50

    missing = client.get("/api/git/refs", params={"repo_path": "/no/such/loadpath-repo"})
    assert missing.status_code == 404

    plain = tmp_path / "plain"
    plain.mkdir()
    not_git = client.get("/api/git/refs", params={"repo_path": str(plain)})
    assert not_git.status_code == 200
    assert not_git.json()["git"] is False


def test_settings_empty_model_does_not_wipe(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    client = TestClient(create_app())
    saved = client.put(
        "/api/settings",
        json={"ai_provider": "grok", "ai_model": "grok-keep", "ai_base_url": "https://example.invalid"},
    )
    assert saved.json()["ai"]["model"] == "grok-keep"
    kept = client.put(
        "/api/settings",
        json={"ai_provider": "grok", "ai_model": "", "ai_base_url": "", "github_token": ""},
    )
    body = kept.json()
    assert body["ai"]["provider"] == "grok"
    assert body["ai"]["model"] == "grok-keep"
    assert body["ai"]["base_url"] == "https://example.invalid"


def test_settings_empty_workspaces_do_not_wipe(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    client = TestClient(create_app())
    workspace = {"path": str(tmp_path / "acme-billing"), "name": "acme-billing"}
    seeded = client.put("/api/settings", json={"workspaces": [workspace]})
    expected = seeded.json()["workspaces"]
    assert len(expected) == 1
    assert expected[0]["path"] == workspace["path"]
    assert expected[0]["name"] == workspace["name"]
    omitted = client.put("/api/settings", json={"ai_provider": "grok"})
    assert omitted.json()["workspaces"] == expected
    emptied = client.put("/api/settings", json={"ai_provider": "none", "workspaces": []})
    assert emptied.json()["workspaces"] == expected

