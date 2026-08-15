from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import respx
from fastapi.testclient import TestClient

from loadpath.mcp.compact import compact_architecture, compact_review
from loadpath.mcp.oauth import LoadpathOAuthProvider
from loadpath.mcp.tools import architecture, review_range
from loadpath.server.app import create_app
from tests.conftest import prepare_review_repo


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _client(tmp_path, monkeypatch, **kwargs) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(oauth_auto_approve=True, **kwargs))


def test_oauth_metadata_and_mcp_requires_bearer(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        health = client.get("/api/health")
        assert health.json()["mcp"] == "/mcp"

        as_meta = client.get("/.well-known/oauth-authorization-server")
        assert as_meta.status_code == 200
        body = as_meta.json()
        assert body["registration_endpoint"].endswith("/register")
        assert "none" in body["token_endpoint_auth_methods_supported"]
        assert body["client_id_metadata_document_supported"] is True
        assert "S256" in body["code_challenge_methods_supported"]

        oidc = client.get("/.well-known/openid-configuration")
        assert oidc.json()["issuer"] == body["issuer"]

        prm = client.get("/.well-known/oauth-protected-resource")
        assert prm.json()["resource"].endswith("/mcp")
        assert prm.json()["authorization_servers"] == [body["issuer"]]

        denied = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert denied.status_code == 401
        assert "resource_metadata" in denied.headers.get("www-authenticate", "").lower()


def test_dcr_pkce_token_then_tools_list(tmp_path, monkeypatch):
    verifier, challenge = _pkce()
    redirect = "http://127.0.0.1:9/cb"
    with _client(tmp_path, monkeypatch) as client:
        issuer = client.get("/.well-known/oauth-authorization-server").json()["issuer"]
        resource = issuer + "/mcp"
        registered = client.post(
            "/register",
            json={
                "client_name": "Cursor",
                "redirect_uris": [redirect],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "loadpath",
            },
        )
        assert registered.status_code == 201, registered.text
        client_id = registered.json()["client_id"]
        assert registered.json()["token_endpoint_auth_method"] == "none"

        auth = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "loadpath",
                "state": "xyz",
                "resource": resource,
            },
            follow_redirects=False,
        )
        assert auth.status_code in {302, 307}
        location = urlparse(auth.headers["location"])
        code = parse_qs(location.query)["code"][0]
        assert parse_qs(location.query)["state"] == ["xyz"]

        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": resource,
            },
        )
        assert token.status_code == 200, token.text
        access = token.json()["access_token"]
        assert token.json()["token_type"] == "Bearer"

        listed = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert listed.status_code == 200, listed.text
        assert "Loadpath" in listed.text
        assert "serverInfo" in listed.text


def test_consent_page_when_not_auto_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    _, challenge = _pkce()
    redirect = "http://127.0.0.1:9/cb"
    with TestClient(create_app(oauth_auto_approve=False)) as client:
        registered = client.post(
            "/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [redirect],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "loadpath",
            },
        )
        client_id = registered.json()["client_id"]
        auth = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "loadpath",
            },
            follow_redirects=False,
        )
        assert auth.status_code in {302, 307}
        consent_url = auth.headers["location"]
        assert "/consent?txn=" in consent_url
        page = client.get(urlparse(consent_url).path + "?" + urlparse(consent_url).query)
        assert page.status_code == 200
        assert "Claude" in page.text
        txn = parse_qs(urlparse(consent_url).query)["txn"][0]
        allowed = client.post("/consent", data={"txn": txn, "decision": "allow"}, follow_redirects=False)
        assert allowed.status_code in {302, 307}
        assert "code=" in allowed.headers["location"]


def test_cimd_fetches_https_client_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    issuer = "http://127.0.0.1:7345"
    provider = LoadpathOAuthProvider(issuer, issuer + "/mcp", auto_approve=True)
    document = {
        "client_name": "ChatGPT",
        "redirect_uris": ["https://chatgpt.com/connector/oauth/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    with respx.mock:
        respx.get("https://chatgpt.com/.well-known/mcp/client.json").respond(200, json=document)
        info = asyncio.run(provider.get_client("https://chatgpt.com/.well-known/mcp/client.json"))
    assert info is not None
    assert info.client_name == "ChatGPT"
    assert info.token_endpoint_auth_method == "none"


def test_mcp_review_tool_stays_on_load_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    repo = prepare_review_repo(tmp_path)
    brief = review_range(str(repo), base="HEAD~1", head="HEAD", reindex=True)
    assert "error" not in brief
    assert "markdown" in brief
    assert "nodes" not in brief
    assert "InvoicePage" in brief["markdown"]
    assert "MePage" not in brief["markdown"]
    names = {s["name"] for s in brief["sinks"]}
    assert "send_invoice_email" in names or any("invoice" in n.lower() for n in names)
    assert brief["suggested_reviewers"] == ["billing-team"]
    arch = architecture(str(repo))
    assert arch["indexed"] is True
    assert "billing" in arch["contexts"]
    assert "nodes" not in arch


def test_compact_drops_graph():
    compact = compact_architecture({"indexed": True, "nodes": [1], "edges": [2], "findings": [], "counts": {"nodes": 1}})
    assert "nodes" not in compact
    review = compact_review(
        {
            "title": "t",
            "headline": "h",
            "confidence": {"level": "medium", "reasons": []},
            "markdown": "## Loadpath",
            "findings": [],
            "nodes": [{"name": "x"}],
        }
    )
    assert "nodes" not in review
    assert review["markdown"] == "## Loadpath"
