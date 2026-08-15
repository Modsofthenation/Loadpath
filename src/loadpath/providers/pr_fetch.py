"""Fetch a PR/MR into a local clone so review can walk it without a pre-synced checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loadpath.providers.scm import PullRequest, provider_for
from loadpath.settings import AppSettings, register_workspace

_GIT_TIMEOUT = 120
FETCH_SPEC = {
    "github": "pull/{n}/head",
    "gitlab": "merge-requests/{n}/head",
    "bitbucket": "pull-requests/{n}/from",
}


def redact_secrets(text: str, *secrets: str) -> str:
    out = text
    for secret in secrets:
        if not secret:
            continue
        out = out.replace(secret, "***")
        out = out.replace(quote(secret, safe=""), "***")
    return out


def clones_root() -> Path:
    return Path.home() / ".loadpath" / "clones"


def fetch_spec(provider: str, number: int) -> str:
    template = FETCH_SPEC.get(provider)
    if not template:
        raise ValueError(f"Cannot fetch pull requests from {provider}")
    return template.format(n=int(number))


def local_pr_ref(number: int) -> str:
    return f"refs/loadpath/pr-{int(number)}"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.PIPE,
        timeout=_GIT_TIMEOUT,
        env=env,
    )


def _token_for(settings: AppSettings, provider: str) -> tuple[str, str]:
    if provider == "github":
        token = settings.github_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("LOADPATH_GITHUB_TOKEN") or ""
        return token, settings.github_host or ""
    if provider == "gitlab":
        token = settings.gitlab_token or os.environ.get("GITLAB_TOKEN") or os.environ.get("LOADPATH_GITLAB_TOKEN") or ""
        return token, settings.gitlab_host or ""
    if provider == "bitbucket":
        return settings.bitbucket_token, ""
    return "", ""


def clone_url(provider: str, slug: str, token: str, host: str = "") -> str:
    if provider == "github":
        web = host.strip() or "github.com"
        if web in {"github.com", "www.github.com", "api.github.com"}:
            web = "github.com"
        if token:
            return f"https://x-access-token:{quote(token, safe='')}@{web}/{slug}.git"
        return f"https://{web}/{slug}.git"
    if provider == "gitlab":
        web = host.strip() or "gitlab.com"
        if token:
            return f"https://oauth2:{quote(token, safe='')}@{web}/{slug}.git"
        return f"https://{web}/{slug}.git"
    if provider == "bitbucket":
        if token:
            return f"https://x-token-auth:{quote(token, safe='')}@bitbucket.org/{slug}.git"
        return f"https://bitbucket.org/{slug}.git"
    raise ValueError(f"Unknown provider {provider}")


def ensure_clone(provider: str, slug: str, *, token: str = "", host: str = "") -> Path:
    dest = clones_root() / provider / slug.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    if dest.is_dir() and (dest / ".git").exists():
        try:
            _git(dest, "fetch", "--all", "--prune", env=env)
        except subprocess.CalledProcessError:
            pass
        return dest
    url = clone_url(provider, slug, token, host)
    try:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", url, str(dest)],
            env=env,
            timeout=_GIT_TIMEOUT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = redact_secrets((exc.stderr or "").strip() or "git clone failed", token)
        raise RuntimeError(detail) from None
    return dest


def fetch_pull_ref(repo_root: Path, provider: str, number: int) -> str:
    repo_root = repo_root.resolve()
    spec = fetch_spec(provider, number)
    local = local_pr_ref(number)
    try:
        _git(repo_root, "fetch", "origin", f"{spec}:{local}", "--force")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Could not fetch {provider} #{number} ({spec}). "
            "Need a remote named origin that advertises pull/merge-request refs."
        ) from exc
    return local


def checkout_review_tree(repo_root: Path, local_ref: str, number: int) -> Path:
    """Detached worktree at the fetched PR ref so index reads the PR, not the user's branch."""
    repo_root = repo_root.resolve()
    dest = clones_root() / "worktrees" / f"{repo_root.name}-pr-{int(number)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(repo_root, "worktree", "remove", "--force", str(dest))
    except subprocess.CalledProcessError:
        pass
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
        try:
            _git(repo_root, "worktree", "prune")
        except subprocess.CalledProcessError:
            pass
    _git(repo_root, "worktree", "add", "--detach", str(dest), local_ref)
    return dest


def prepare_pull_request(
    provider: str,
    repo: str,
    number: int,
    *,
    repo_path: str | None = None,
) -> dict[str, Any]:
    """Return local path + git refs for reviewing a remote PR/MR."""
    settings = AppSettings.load()
    token, host = _token_for(settings, provider)
    scm = provider_for(provider, token, username=settings.bitbucket_username, host=host) if token else None
    pr: PullRequest | None = None
    if scm:
        pr = scm.get_pull_request(repo, number)
    root: Path | None = None
    if repo_path:
        candidate = Path(repo_path).expanduser().resolve()
        if candidate.is_dir():
            root = candidate
    if root is None:
        from loadpath.providers.scm import attach_local_paths, RemoteRepo

        listed = [
            RemoteRepo(provider=provider, slug=repo, name=repo.split("/")[-1], owner=repo.split("/")[0], url="")
        ]
        attach_local_paths(listed, [w.path for w in settings.workspaces])
        if listed[0].local_path:
            root = Path(listed[0].local_path)
    cloned = False
    if root is None:
        if not token:
            raise RuntimeError(
                f"No local clone for {repo} and no {provider} token to clone it. "
                "Sign in under Settings or pass a local repo path."
            )
        root = ensure_clone(provider, repo, token=token, host=host)
        cloned = True
        register_workspace(root, name=repo.split("/")[-1])
    local_ref = fetch_pull_ref(root, provider, number)
    review_root = checkout_review_tree(root, local_ref, number)
    base_ref = (pr.target_branch if pr else None) or "origin/HEAD"
    if pr and pr.target_branch:
        try:
            _git(root, "fetch", "origin", pr.target_branch)
            base_ref = f"origin/{pr.target_branch}"
        except subprocess.CalledProcessError:
            base_ref = pr.target_branch
    return {
        "repo_path": str(review_root),
        "provider": provider,
        "repo": repo,
        "number": number,
        "base": base_ref,
        "head": local_ref,
        "cloned": cloned,
        "title": pr.title if pr else f"{provider} #{number}",
        "source_branch": pr.source_branch if pr else "",
        "target_branch": pr.target_branch if pr else "",
        "url": pr.url if pr else "",
    }