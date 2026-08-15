from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx

from loadpath import __version__
from loadpath.paths import package_dir
from loadpath.mcp.oauth import SCOPE
from loadpath.mcp.server import (
    add_mcp_auth_middleware,
    build_mcp_http,
    copy_mcp_routes,
    create_mcp_server,
    mcp_lifespan,
    public_base_url,
    resource_url,
)
from loadpath.ai.providers import client_for, residual_prompt
from loadpath.architecture.snapshot import architecture_graph, architecture_report, summarize_index
from loadpath.config import load_config
from loadpath.detect import detect_layout, write_draft_config
from loadpath.graph.store import GraphStore
from loadpath.index import default_db_path, index_repo
from loadpath.providers.oauth import (
    callback_html,
    disconnect_scm,
    finish_bitbucket_authorize,
    is_loopback_request,
    oauth_status,
    poll_github_device,
    start_bitbucket_authorize,
    start_github_device,
)
from loadpath.providers.scm import attach_local_paths, provider_for
from loadpath.review.engine import run_review
from loadpath.review.render import render_html, render_markdown
from loadpath.settings import AppSettings, public_settings, register_workspace, settings_path, _should_update_secret
from loadpath.workspace import DEFAULT_COMMIT_LIMIT, list_directory, list_git_refs


class IndexRequest(BaseModel):
    repo_path: str
    incremental: bool = True


class ReviewRequest(BaseModel):
    repo_path: str
    base: str = "HEAD~1"
    head: str | None = None
    reindex: bool = True
    incremental: bool = True
    three_dot: bool = True


class InitRequest(BaseModel):
    repo_path: str
    overwrite: bool = False


class PRCommentRequest(BaseModel):
    provider: str
    repo: str
    number: int
    markdown: str
    token: str | None = None
    username: str | None = None


class SettingsUpdate(BaseModel):
    github_token: str | None = None
    github_oauth_client_id: str | None = None
    bitbucket_token: str | None = None
    bitbucket_username: str | None = None
    bitbucket_workspace: str | None = None
    bitbucket_oauth_client_id: str | None = None
    bitbucket_oauth_client_secret: str | None = None
    ai_provider: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_base_url: str | None = None
    workspaces: list[dict[str, Any]] | None = None


class PRListRequest(BaseModel):
    provider: str
    repo: str
    state: str = "open"
    token: str | None = None
    username: str | None = None


class ResidualRequest(BaseModel):
    review: dict[str, Any] = Field(default_factory=dict)


class GitHubOAuthPoll(BaseModel):
    flow_id: str


class OAuthDisconnect(BaseModel):
    provider: str


def require_repo_path(path: str | None) -> Path:
    if not (path or "").strip():
        raise HTTPException(400, "repo_path is required")
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(404, f"Repo not found: {root}")
    return root


def _scm_credentials(settings: AppSettings, provider: str) -> tuple[str, str]:
    if provider == "github":
        return settings.github_token, ""
    if provider == "bitbucket":
        return settings.bitbucket_token, settings.bitbucket_username
    raise HTTPException(400, f"Unknown SCM provider: {provider}")


def _call_scm(provider: str, fn):
    from loadpath.providers.oauth import refresh_bitbucket_access_token

    settings = AppSettings.load()
    token, username = _scm_credentials(settings, provider)
    if not token:
        raise HTTPException(400, f"No {provider} token configured")
    try:
        return fn(provider_for(provider, token, username=username))
    except httpx.HTTPStatusError as exc:
        if (
            provider == "bitbucket"
            and exc.response is not None
            and exc.response.status_code == 401
            and settings.bitbucket_refresh_token
        ):
            try:
                settings = refresh_bitbucket_access_token(settings)
            except Exception as refresh_exc:  # noqa: BLE001
                raise HTTPException(502, str(refresh_exc)) from refresh_exc
            token, username = _scm_credentials(settings, provider)
            return fn(provider_for(provider, token, username=username))
        raise HTTPException(502, str(exc)) from exc


def require_loopback(request: Request) -> None:
    if not is_loopback_request(request.headers.get("host") or "", request.headers.get("origin") or ""):
        raise HTTPException(403, "SCM sign-in and repo listing are only available from the local Loadpath UI")


def create_app(
    public_url: str | None = None,
    oauth_pin: str | None = None,
    oauth_auto_approve: bool | None = None,
) -> FastAPI:
    base = public_base_url(public_url=public_url)
    mcp = create_mcp_server(
        http=True,
        public_url=base,
        oauth_pin=oauth_pin,
        auto_approve=oauth_auto_approve,
    )
    mcp_http = build_mcp_http(mcp)
    app = FastAPI(title="Loadpath", version=__version__, lifespan=mcp_lifespan(mcp))
    app.state.mcp = mcp
    app.state.mcp_http = mcp_http
    add_mcp_auth_middleware(app, mcp)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["WWW-Authenticate", "Mcp-Session-Id", "mcp-session-id"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "mcp": "/mcp"}

    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/openid-configuration")
    def oauth_authorization_server() -> dict[str, Any]:
        issuer = base.rstrip("/")
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "registration_endpoint": f"{issuer}/register",
            "revocation_endpoint": f"{issuer}/revoke",
            "scopes_supported": [SCOPE],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "code_challenge_methods_supported": ["S256"],
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
        }

    @app.get("/.well-known/oauth-protected-resource")
    def oauth_protected_resource_root() -> dict[str, Any]:
        issuer = base.rstrip("/")
        resource = resource_url(issuer)
        return {
            "resource": resource,
            "authorization_servers": [issuer],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "Loadpath",
        }

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return public_settings(AppSettings.load())

    @app.put("/api/settings")
    def put_settings(body: SettingsUpdate) -> dict[str, Any]:
        current = AppSettings.load()
        if _should_update_secret(body.github_token, current.github_token):
            current.github_token = body.github_token or ""
        if body.github_oauth_client_id is not None:
            current.github_oauth_client_id = body.github_oauth_client_id.strip()
        if _should_update_secret(body.bitbucket_token, current.bitbucket_token):
            current.bitbucket_token = body.bitbucket_token or ""
        if body.bitbucket_username is not None:
            current.bitbucket_username = body.bitbucket_username
        if body.bitbucket_workspace is not None:
            current.bitbucket_workspace = body.bitbucket_workspace
        if body.bitbucket_oauth_client_id is not None:
            current.bitbucket_oauth_client_id = body.bitbucket_oauth_client_id.strip()
        if _should_update_secret(body.bitbucket_oauth_client_secret, current.bitbucket_oauth_client_secret):
            current.bitbucket_oauth_client_secret = body.bitbucket_oauth_client_secret or ""
        if body.ai_provider is not None:
            current.ai.provider = body.ai_provider
        if _should_update_secret(body.ai_api_key, current.ai.api_key):
            current.ai.api_key = body.ai_api_key or ""
        if _should_update_secret(body.ai_model, current.ai.model):
            current.ai.model = body.ai_model or ""
        if _should_update_secret(body.ai_base_url, current.ai.base_url):
            current.ai.base_url = body.ai_base_url or ""
        if body.workspaces:
            from loadpath.settings import Workspace

            current.workspaces = [Workspace.model_validate(w) for w in body.workspaces]
        current.save()
        return public_settings(current)

    @app.post("/api/index")
    def api_index(body: IndexRequest) -> dict[str, Any]:
        root = require_repo_path(body.repo_path)
        store = index_repo(root, incremental=body.incremental, draft_config=True)
        register_workspace(root)
        summary = summarize_index(store, load_config(root))
        store.close()
        return summary

    @app.get("/api/index")
    def api_index_status(repo_path: str) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        report = architecture_report(root)
        report.pop("nodes", None)
        report.pop("edges", None)
        return report

    @app.get("/api/fs")
    def api_fs(path: str | None = None) -> dict[str, Any]:
        return list_directory(path)

    @app.get("/api/git/refs")
    def api_git_refs(repo_path: str, limit: int = DEFAULT_COMMIT_LIMIT) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        return list_git_refs(root, commit_limit=limit)

    @app.get("/api/repos")
    def api_repos() -> dict[str, Any]:
        settings = AppSettings.load()
        repos = []
        for workspace in settings.workspaces:
            path = Path(workspace.path)
            item: dict[str, Any] = {
                "path": workspace.path,
                "name": workspace.name or path.name,
                "exists": path.is_dir(),
                "indexed": False,
                "counts": {"nodes": 0, "edges": 0},
            }
            if path.is_dir():
                report = architecture_report(path)
                item.update(
                    {
                        "indexed": report["indexed"],
                        "counts": report.get("counts") or {"nodes": 0, "edges": 0},
                        "indexed_at": report.get("indexed_at"),
                        "contexts": list((report.get("contexts") or {}).keys()),
                        "has_config": report.get("has_config", False),
                    }
                )
            repos.append(item)
        return {"repos": repos}

    @app.post("/api/review")
    def api_review(body: ReviewRequest) -> dict[str, Any]:
        root = require_repo_path(body.repo_path)
        try:
            review = run_review(
                root,
                base=body.base,
                head=body.head,
                reindex=body.reindex,
                incremental=body.incremental,
                three_dot=body.three_dot,
            )
        except FileNotFoundError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc
        review["markdown"] = render_markdown(review)
        register_workspace(root)
        return review

    @app.get("/api/reviews")
    def api_reviews(repo_path: str) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        db = default_db_path(root)
        if not db.is_file():
            return {"reviews": []}
        store = GraphStore(db)
        items = store.list_reviews()
        store.close()
        return {"reviews": items}

    @app.get("/api/reviews/{review_id}")
    def api_review_get(review_id: str, repo_path: str) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        store = GraphStore(default_db_path(root))
        item = store.get_review(review_id)
        store.close()
        if not item:
            raise HTTPException(404, "Review not found")
        return item

    @app.get("/api/graph")
    def api_graph(repo_path: str, scope: str = "full") -> dict[str, Any]:
        root = require_repo_path(repo_path)
        db = default_db_path(root)
        if not db.is_file():
            raise HTTPException(409, "Index the repo first")
        store = GraphStore(db)
        if scope == "architecture":
            nodes, edges = architecture_graph(store)
        else:
            nodes, edges = store.nodes(), store.edges()
        payload = {"nodes": nodes, "edges": edges, "counts": store.counts(), "scope": scope}
        store.close()
        return payload

    @app.get("/api/architecture")
    def api_architecture(repo_path: str) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        return architecture_report(root)

    @app.get("/api/config")
    def api_config(repo_path: str) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        cfg = load_config(root)
        return {
            "contexts": {k: vars(v) for k, v in cfg.contexts.items()},
            "rules": cfg.rules,
            "django_root": cfg.django_root,
            "react_root": cfg.react_root,
        }

    @app.post("/api/prs")
    def api_prs(body: PRListRequest) -> dict[str, Any]:
        settings = AppSettings.load()
        token = body.token
        username = body.username or settings.bitbucket_username
        if token:
            try:
                scm = provider_for(body.provider, token, username=username)
                prs = scm.list_pull_requests(body.repo, state=body.state)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, str(exc)) from exc
            return {"pull_requests": [p.to_dict() for p in prs]}
        try:
            prs = _call_scm(body.provider, lambda scm: scm.list_pull_requests(body.repo, state=body.state))
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
        return {"pull_requests": [p.to_dict() for p in prs]}

    @app.post("/api/init")
    def api_init(body: InitRequest) -> dict[str, Any]:
        root = require_repo_path(body.repo_path)
        layout = write_draft_config(root, overwrite=body.overwrite)
        register_workspace(root)
        return layout

    @app.get("/api/detect")
    def api_detect(repo_path: str) -> dict[str, Any]:
        root = require_repo_path(repo_path)
        return detect_layout(root)

    @app.post("/api/prs/comment")
    def api_pr_comment(body: PRCommentRequest) -> dict[str, Any]:
        settings = AppSettings.load()
        token = body.token
        username = body.username or settings.bitbucket_username
        if not body.markdown.strip():
            raise HTTPException(400, "markdown is empty")
        if token:
            try:
                scm = provider_for(body.provider, token, username=username)
                return scm.upsert_pull_request_comment(body.repo, body.number, body.markdown)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, str(exc)) from exc
        try:
            return _call_scm(
                body.provider,
                lambda scm: scm.upsert_pull_request_comment(body.repo, body.number, body.markdown),
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/scm/repos")
    def api_scm_repos(request: Request, provider: str = Query("github")) -> dict[str, Any]:
        require_loopback(request)
        settings = AppSettings.load()

        def _load(scm):
            return scm.list_repositories(), scm.current_user()

        try:
            repos, profile = _call_scm(provider, _load)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
        attach_local_paths(repos, [w.path for w in settings.workspaces])
        login = profile.get("login") or ""
        if login:
            current = AppSettings.load()
            if provider == "github" and current.github_user != login:
                current.github_user = login
                current.save()
            elif provider == "bitbucket" and current.bitbucket_user != login:
                current.bitbucket_user = login
                current.save()
        return {
            "provider": provider,
            "user": profile,
            "repos": [r.to_dict() for r in repos],
        }

    @app.get("/api/oauth/status")
    def api_oauth_status(request: Request) -> dict[str, Any]:
        require_loopback(request)
        return oauth_status()

    @app.post("/api/oauth/github/start")
    def api_github_oauth_start(request: Request) -> dict[str, Any]:
        require_loopback(request)
        try:
            return start_github_device()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/oauth/github/poll")
    def api_github_oauth_poll(request: Request, body: GitHubOAuthPoll) -> dict[str, Any]:
        require_loopback(request)
        try:
            return poll_github_device(body.flow_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/oauth/bitbucket/start")
    def api_bitbucket_oauth_start(request: Request) -> dict[str, Any]:
        require_loopback(request)
        redirect_uri = f"{base.rstrip('/')}/api/oauth/bitbucket/callback"
        try:
            return start_bitbucket_authorize(redirect_uri)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/oauth/bitbucket/callback")
    def api_bitbucket_oauth_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
        if error:
            return HTMLResponse(
                callback_html(
                    ok=False,
                    title="Bitbucket sign-in cancelled",
                    body=error.replace("_", " "),
                ),
                status_code=400,
            )
        if not code or not state:
            return HTMLResponse(
                callback_html(ok=False, title="Bitbucket sign-in failed", body="Missing code or state."),
                status_code=400,
            )
        try:
            settings = finish_bitbucket_authorize(code, state)
        except ValueError as exc:
            return HTMLResponse(
                callback_html(ok=False, title="Bitbucket sign-in failed", body=str(exc)),
                status_code=400,
            )
        except httpx.HTTPError as exc:
            return HTMLResponse(
                callback_html(ok=False, title="Bitbucket sign-in failed", body=str(exc)),
                status_code=502,
            )
        user = settings.bitbucket_user or "your account"
        return HTMLResponse(
            callback_html(
                ok=True,
                title="Connected to Bitbucket",
                body=f"Signed in as {user}. Return to Loadpath — your repositories are available on the Pull requests tab.",
            )
        )

    @app.post("/api/oauth/disconnect")
    def api_oauth_disconnect(request: Request, body: OAuthDisconnect) -> dict[str, Any]:
        require_loopback(request)
        try:
            settings = disconnect_scm(body.provider)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return public_settings(settings)

    @app.post("/api/ai/residual")
    def api_residual(body: ResidualRequest) -> dict[str, Any]:
        settings = AppSettings.load()
        if settings.ai.provider in {"", "none"} or not settings.ai.api_key:
            raise HTTPException(400, "Configure an AI provider in settings first")
        try:
            client = client_for(
                settings.ai.provider,
                settings.ai.api_key,
                model=settings.ai.model,
                base_url=settings.ai.base_url,
            )
            text = client.complete(residual_prompt(body.review))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
        return {"note": text}

    copy_mcp_routes(app, mcp_http)

    static_dir = package_dir() / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()


def serve(
    host: str = "127.0.0.1",
    port: int = 7345,
    open_browser: bool = True,
    public_url: str | None = None,
    oauth_pin: str | None = None,
) -> None:
    import uvicorn

    settings_path().parent.mkdir(parents=True, exist_ok=True)
    display = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    base = public_base_url(host=host, port=port, public_url=public_url)
    application = create_app(public_url=base, oauth_pin=oauth_pin)
    if open_browser:
        webbrowser.open(f"http://{display}:{port}")
    uvicorn.run(application, host=host, port=port, reload=False)
