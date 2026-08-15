from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TypeVar

import httpx

from loadpath.architecture.snapshot import architecture_report, summarize_index
from loadpath.config import load_config
from loadpath.detect import detect_layout, write_draft_config
from loadpath.index import index_repo
from loadpath.mcp.compact import compact_architecture, compact_review
from loadpath.providers.scm import attach_local_paths, provider_for
from loadpath.review.engine import run_review
from loadpath.review.render import render_markdown
from loadpath.settings import AppSettings, register_workspace

_T = TypeVar("_T")


def _with_scm(provider: str, fn: Callable[[Any], _T]) -> _T | dict[str, str]:
    settings = AppSettings.load()
    token = ""
    username = ""
    host = ""
    if provider == "github":
        token = settings.github_token
        host = settings.github_host
    elif provider == "gitlab":
        token = settings.gitlab_token
        host = settings.gitlab_host
    else:
        token = settings.bitbucket_token
        username = settings.bitbucket_username
    if not token:
        return {"error": f"No {provider} token configured in Loadpath settings"}
    try:
        return fn(provider_for(provider, token, username=username, host=host))
    except httpx.HTTPStatusError as exc:
        if (
            provider == "bitbucket"
            and exc.response is not None
            and exc.response.status_code == 401
            and settings.bitbucket_refresh_token
        ):
            from loadpath.providers.oauth import refresh_bitbucket_access_token

            try:
                settings = refresh_bitbucket_access_token(settings)
            except Exception as refresh_exc:  # noqa: BLE001
                return {"error": str(refresh_exc)}
            token = settings.bitbucket_token
            username = settings.bitbucket_username
            return fn(provider_for(provider, token, username=username))
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _repo(path: str) -> Path | dict[str, str]:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"Repo not found: {root}"}
    return root


def list_workspaces() -> dict[str, Any]:
    """Registered Loadpath workspaces and whether they are indexed."""
    settings = AppSettings.load()
    repos: list[dict[str, Any]] = []
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
    return {"workspaces": repos}


def init_repo(repo_path: str, overwrite: bool = False) -> dict[str, Any]:
    """Detect Django/React roots and draft loadpath.yml (does not overwrite by default)."""
    root = _repo(repo_path)
    if isinstance(root, dict):
        return root
    layout = write_draft_config(root, overwrite=overwrite)
    register_workspace(root)
    return layout


def index_workspace(repo_path: str, incremental: bool = True) -> dict[str, Any]:
    """Build or refresh the architecture graph for a Django + React repo."""
    root = _repo(repo_path)
    if isinstance(root, dict):
        return root
    store = index_repo(root, incremental=incremental, draft_config=True)
    register_workspace(root)
    summary = summarize_index(store, load_config(root))
    store.close()
    summary.pop("residuals", None)
    return compact_architecture({**summary, "findings": summary.get("findings") or []})


def architecture(repo_path: str) -> dict[str, Any]:
    """Indexed architecture: contexts, rules, findings. Index first if empty."""
    root = _repo(repo_path)
    if isinstance(root, dict):
        return root
    return compact_architecture(architecture_report(root))


def review_range(
    repo_path: str,
    base: str = "HEAD~1",
    head: str | None = "HEAD",
    reindex: bool = True,
    incremental: bool = True,
    three_dot: bool = True,
    dirty: bool = False,
) -> dict[str, Any]:
    """Review a git range as a load path: sinks, confidence, reviewers. Not hunk comments."""
    root = _repo(repo_path)
    if isinstance(root, dict):
        return root
    try:
        review = run_review(
            root,
            base=base,
            head=head,
            reindex=reindex,
            incremental=incremental,
            three_dot=three_dot,
            dirty=dirty,
        )
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    review["markdown"] = render_markdown(review)
    register_workspace(root)
    return compact_review(review)


def detect_repo(repo_path: str) -> dict[str, Any]:
    """Detect Django/React layout without writing loadpath.yml."""
    root = _repo(repo_path)
    if isinstance(root, dict):
        return root
    return detect_layout(root)


def list_pull_requests(
    provider: str,
    repo: str,
    state: str = "open",
) -> dict[str, Any]:
    """List pull requests from GitHub, GitLab, or Bitbucket using tokens in ~/.loadpath/settings.json."""
    result = _with_scm(provider, lambda scm: scm.list_pull_requests(repo, state=state))
    if isinstance(result, dict) and result.get("error"):
        return result
    return {"pull_requests": [p.to_dict() for p in result]}


def list_remote_repositories(provider: str) -> dict[str, Any]:
    """List GitHub, GitLab, or Bitbucket repositories the saved token can access."""
    settings = AppSettings.load()
    result = _with_scm(provider, lambda scm: (scm.list_repositories(), scm.current_user()))
    if isinstance(result, dict) and result.get("error"):
        return result
    repos, profile = result
    attach_local_paths(repos, [w.path for w in settings.workspaces])
    return {"provider": provider, "user": profile, "repos": [r.to_dict() for r in repos]}


def post_review_comment(
    provider: str,
    repo: str,
    number: int,
    markdown: str,
) -> dict[str, Any]:
    """Upsert the single Loadpath brief comment on a pull request."""
    if not markdown.strip():
        return {"error": "markdown is empty"}
    result = _with_scm(
        provider,
        lambda scm: scm.upsert_pull_request_comment(repo, number, markdown),
    )
    return result


def what_if(repo_path: str, node_id: str) -> dict[str, Any]:
    """Walk sinks from one indexed node without a git range."""
    root = _repo(repo_path)
    if isinstance(root, dict):
        return root
    from loadpath.review.whatif import simulate_node

    try:
        payload = simulate_node(root, node_id)
    except (FileNotFoundError, KeyError) as exc:
        return {"error": str(exc)}
    payload.pop("nodes", None)
    payload.pop("edges", None)
    return payload


def review_pull_request(
    provider: str,
    repo: str,
    number: int,
    repo_path: str | None = None,
) -> dict[str, Any]:
    """Fetch a PR/MR into a local clone and review the three-dot range."""
    from loadpath.providers.pr_fetch import prepare_pull_request

    try:
        prepared = prepare_pull_request(provider, repo, number, repo_path=repo_path)
        review = run_review(
            Path(prepared["repo_path"]),
            base=prepared["base"],
            head=prepared["head"],
            reindex=True,
            incremental=True,
            three_dot=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    review["markdown"] = render_markdown(review)
    register_workspace(Path(prepared["repo_path"]))
    compact = compact_review(review)
    compact["pull_request"] = prepared
    return compact
