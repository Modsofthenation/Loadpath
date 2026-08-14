from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from loadpath import __version__
from loadpath.ai.providers import client_for, residual_prompt
from loadpath.config import load_config
from loadpath.graph.store import GraphStore
from loadpath.index import default_db_path, index_repo
from loadpath.providers.scm import provider_for
from loadpath.review.engine import run_review
from loadpath.review.render import render_html, render_markdown
from loadpath.settings import AppSettings, public_settings, settings_path


class IndexRequest(BaseModel):
    repo_path: str
    incremental: bool = True


class ReviewRequest(BaseModel):
    repo_path: str
    base: str = "origin/main"
    head: str | None = None
    reindex: bool = True


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


def create_app() -> FastAPI:
    app = FastAPI(title="Loadpath", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return public_settings(AppSettings.load())

    @app.put("/api/settings")
    def put_settings(body: SettingsUpdate) -> dict[str, Any]:
        current = AppSettings.load()
        if body.github_token is not None and body.github_token not in {"", current.github_token} and "…" not in body.github_token:
            current.github_token = body.github_token
        if body.bitbucket_token is not None and "…" not in (body.bitbucket_token or ""):
            current.bitbucket_token = body.bitbucket_token
        if body.bitbucket_username is not None:
            current.bitbucket_username = body.bitbucket_username
        if body.bitbucket_workspace is not None:
            current.bitbucket_workspace = body.bitbucket_workspace
        if body.ai_provider is not None:
            current.ai.provider = body.ai_provider
        if body.ai_api_key is not None and "…" not in body.ai_api_key:
            current.ai.api_key = body.ai_api_key
        if body.ai_model is not None:
            current.ai.model = body.ai_model
        if body.ai_base_url is not None:
            current.ai.base_url = body.ai_base_url
        if body.workspaces is not None:
            from loadpath.settings import Workspace

            current.workspaces = [Workspace.model_validate(w) for w in body.workspaces]
        current.save()
        return public_settings(current)

    @app.post("/api/index")
    def api_index(body: IndexRequest) -> dict[str, Any]:
        root = Path(body.repo_path).expanduser().resolve()
        if not root.is_dir():
            raise HTTPException(404, f"Repo not found: {root}")
        store = index_repo(root, incremental=body.incremental)
        counts = store.counts()
        store.close()
        return {"ok": True, "counts": counts, "db": str(default_db_path(root))}

    @app.post("/api/review")
    def api_review(body: ReviewRequest) -> dict[str, Any]:
        root = Path(body.repo_path).expanduser().resolve()
        if not root.is_dir():
            raise HTTPException(404, f"Repo not found: {root}")
        try:
            review = run_review(root, base=body.base, head=body.head, reindex=body.reindex)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc
        review["markdown"] = render_markdown(review)
        return review

    @app.get("/api/reviews")
    def api_reviews(repo_path: str) -> dict[str, Any]:
        root = Path(repo_path).expanduser().resolve()
        db = default_db_path(root)
        if not db.is_file():
            return {"reviews": []}
        store = GraphStore(db)
        items = store.list_reviews()
        store.close()
        return {"reviews": items}

    @app.get("/api/reviews/{review_id}")
    def api_review_get(review_id: str, repo_path: str) -> dict[str, Any]:
        root = Path(repo_path).expanduser().resolve()
        store = GraphStore(default_db_path(root))
        item = store.get_review(review_id)
        store.close()
        if not item:
            raise HTTPException(404, "Review not found")
        return item

    @app.get("/api/graph")
    def api_graph(repo_path: str) -> dict[str, Any]:
        root = Path(repo_path).expanduser().resolve()
        db = default_db_path(root)
        if not db.is_file():
            raise HTTPException(404, "Index the repo first")
        store = GraphStore(db)
        payload = {"nodes": store.nodes(), "edges": store.edges(), "counts": store.counts()}
        store.close()
        return payload

    @app.get("/api/config")
    def api_config(repo_path: str) -> dict[str, Any]:
        root = Path(repo_path).expanduser().resolve()
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
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
        return {"pull_requests": [p.to_dict() for p in prs]}

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

    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 7345, open_browser: bool = True) -> None:
    import uvicorn

    settings_path().parent.mkdir(parents=True, exist_ok=True)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run("loadpath.server.app:app", host=host, port=port, reload=False)
