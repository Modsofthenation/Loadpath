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
