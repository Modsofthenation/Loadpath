from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from loadpath import __version__
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
from loadpath.providers.scm import provider_for
from loadpath.review.engine import run_review
from loadpath.review.render import render_html, render_markdown
from loadpath.settings import AppSettings, public_settings, register_workspace, settings_path, _should_update_secret


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
    bitbucket_token: str | None = None
    bitbucket_username: str | None = None
    bitbucket_workspace: str | None = None
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


def require_repo_path(path: str | None) -> Path:
    if not (path or "").strip():
        raise HTTPException(400, "repo_path is required")
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(404, f"Repo not found: {root}")
    return root


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
        if _should_update_secret(body.bitbucket_token, current.bitbucket_token):
            current.bitbucket_token = body.bitbucket_token or ""
        if body.bitbucket_username is not None:
            current.bitbucket_username = body.bitbucket_username
        if body.bitbucket_workspace is not None:
            current.bitbucket_workspace = body.bitbucket_workspace
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
        if not token:
            token = settings.github_token if body.provider == "github" else settings.bitbucket_token
        if not token:
            raise HTTPException(400, f"No {body.provider} token configured")
        try:
            scm = provider_for(body.provider, token, username=username)
            prs = scm.list_pull_requests(body.repo, state=body.state)
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
        if not token:
            token = settings.github_token if body.provider == "github" else settings.bitbucket_token
        if not token:
            raise HTTPException(400, f"No {body.provider} token configured")
        if not body.markdown.strip():
            raise HTTPException(400, "markdown is empty")
        try:
            scm = provider_for(body.provider, token, username=username)
            posted = scm.upsert_pull_request_comment(body.repo, body.number, body.markdown)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
        return posted

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

    static_dir = Path(__file__).resolve().parent.parent / "static"
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
