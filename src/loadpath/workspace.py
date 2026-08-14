"""Git workspace facts used by review: dirty tree, merge-base, three-dot range."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
