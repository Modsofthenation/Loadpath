"""Local workspace helpers: directory browsing, git refs, dirty tree, merge-base."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_GIT_TIMEOUT = 8
_MAX_DIR_ENTRIES = 400
DEFAULT_COMMIT_LIMIT = 50
_MAX_COMMIT_LIMIT = 100
_MAX_BRANCHES = 50
_MAX_TAGS = 20


def _git_output(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_root), *args],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=_GIT_TIMEOUT,
    )


def resolve_existing_dir(path: str | None) -> Path:
    """Walk up from path until a real directory is found, else home."""
    home = Path.home().resolve()
    if not (path or "").strip():
        return home
    current = Path(path).expanduser()
    try:
        current = current.resolve()
    except OSError:
        pass
    while True:
        try:
            if current.is_dir():
                return current
        except OSError:
            pass
        parent = current.parent
        if parent == current:
            return home
        current = parent


def list_directory(path: str | None = None) -> dict[str, Any]:
    """List child directories for the in-app repository picker."""
    home = Path.home().resolve()
    root = resolve_existing_dir(path)
    parent = str(root.parent) if root.parent != root else None
    entries: list[dict[str, Any]] = []
    try:
        children = list(root.iterdir())
    except OSError:
        children = []
    for child in children:
        name = child.name
        if name.startswith("."):
            continue
        try:
            if not child.is_dir():
                continue
            resolved = child.resolve()
        except OSError:
            continue
        entries.append(
            {
                "name": name,
                "path": str(resolved),
                "is_dir": True,
                "is_git": (resolved / ".git").exists(),
            }
        )
    entries.sort(key=lambda item: (not item["is_git"], item["name"].lower()))
    truncated = len(entries) > _MAX_DIR_ENTRIES
    if truncated:
        entries = entries[:_MAX_DIR_ENTRIES]
    return {
        "path": str(root),
        "name": root.name or str(root),
        "parent": parent,
        "home": str(home),
        "is_git": (root / ".git").exists(),
        "truncated": truncated,
        "entries": entries,
    }


def list_git_refs(repo_root: Path, *, commit_limit: int = DEFAULT_COMMIT_LIMIT) -> dict[str, Any]:
    """Branches, tags, and recent commits for base/head pickers."""
    repo_root = repo_root.resolve()
    limit = max(1, min(int(commit_limit), _MAX_COMMIT_LIMIT))
    payload: dict[str, Any] = {
        "git": False,
        "repo_path": str(repo_root),
        "head": None,
        "head_short": None,
        "branches": [],
        "tags": [],
        "commits": [],
        "presets": ["HEAD", "HEAD~1"],
    }
    if not repo_root.is_dir() or not (repo_root / ".git").exists():
        return payload
    payload["git"] = True
    head = git_rev_parse(repo_root, "HEAD")
    payload["head"] = head
    payload["head_short"] = head[:12] if head else None
    payload["commits"] = _list_commits(repo_root, limit)
    payload["branches"] = _list_refs(repo_root, ("refs/heads", "refs/remotes"), _MAX_BRANCHES)
    payload["tags"] = _list_refs(repo_root, ("refs/tags",), _MAX_TAGS, sort="-creatordate")
    return payload


def _list_commits(repo_root: Path, limit: int) -> list[dict[str, str]]:
    try:
        raw = _git_output(
            repo_root,
            "log",
            f"-n{limit}",
            "--format=%H%x09%h%x09%an%x09%cI%x09%s",
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []
    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        sha, short, author, date, subject = (line.split("\t", 4) + [""] * 5)[:5]
        if not sha:
            continue
        commits.append(
            {"sha": sha, "short": short, "subject": subject, "author": author, "date": date}
        )
    return commits


def _list_refs(
    repo_root: Path,
    patterns: tuple[str, ...],
    limit: int,
    *,
    sort: str = "-committerdate",
) -> list[dict[str, Any]]:
    try:
        raw = _git_output(
            repo_root,
            "for-each-ref",
            f"--sort={sort}",
            *patterns,
            "--format=%(refname:short)%09%(objectname)%09%(objectname:short)%09%(HEAD)%09%(contents:subject)",
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []
    refs: list[dict[str, Any]] = []
    for line in raw.splitlines():
        name, sha, short, head_mark, subject = (line.split("\t", 4) + [""] * 5)[:5]
        if not name or name == "HEAD" or name.endswith("/HEAD"):
            continue
        refs.append(
            {
                "name": name,
                "sha": sha,
                "short": short,
                "subject": subject,
                "current": head_mark.strip() == "*",
            }
        )
        if len(refs) >= limit:
            break
    return refs


def git_dirty_paths(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(repo_root), "status", "--porcelain", "-uall"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    paths: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.append(path)
    return paths


def git_merge_base(repo_root: Path, a: str, b: str) -> str | None:
    repo_root = repo_root.resolve()
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "merge-base", a, b],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_rev_parse(repo_root: Path, ref: str) -> str | None:
    repo_root = repo_root.resolve()
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", ref],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve_review_range(
    repo_root: Path,
    base: str,
    head: str | None,
    *,
    three_dot: bool = True,
) -> dict[str, str | None]:
    """Map branch names to a PR-shaped range (merge-base...head) when possible."""
    head_ref = head or "HEAD"
    merge_base = git_merge_base(repo_root, base, head_ref) if three_dot else None
    diff_base = merge_base or base
    return {
        "base": base,
        "head": head,
        "head_ref": head_ref,
        "merge_base": merge_base,
        "diff_base": diff_base,
        "three_dot": three_dot,
        "base_sha": git_rev_parse(repo_root, diff_base),
        "head_sha": git_rev_parse(repo_root, head_ref),
    }
