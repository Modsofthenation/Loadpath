from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from loadpath.types import GENERATED_PATH_MARKERS


@dataclass
class FileDiff:
    path: str
    status: str  # A, M, D
    added: int = 0
    deleted: int = 0
    patch: str = ""
    skip: bool = False


@dataclass
class DiffSet:
    files: list[FileDiff] = field(default_factory=list)
    base: str = "HEAD"
    head: str = "WORKTREE"

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self.files if not f.skip]


def is_skippable(path: str) -> bool:
    n = path.replace("\\", "/")
    if n.endswith(("lock", ".min.js", ".map", ".svg", ".png", ".jpg", ".woff", ".woff2")):
        return True
    return any(m in n for m in GENERATED_PATH_MARKERS if m != "generated/")


def _range_args(base: str, head: str | None, three_dot: bool) -> list[str]:
    if head and three_dot:
        return [f"{base}...{head}"]
    if head:
        return [base, head]
    return [base]


def git_diff(
    repo_root: Path,
    base: str,
    head: str | None = None,
    *,
    three_dot: bool = True,
) -> DiffSet:
    repo_root = repo_root.resolve()
    specs: list[list[str]] = []
    if head and three_dot:
        specs.append(_range_args(base, head, True))
    if head:
        two = _range_args(base, head, False)
        if two not in specs:
            specs.append(two)
    if not specs:
        specs.append(_range_args(base, head, three_dot))

    last_error: subprocess.CalledProcessError | None = None
    numstat = namestat = patch = ""
    used = specs[0]
    for spec in specs:
        try:
            numstat = subprocess.check_output(
                ["git", "-C", str(repo_root), "diff", "--numstat", "-M", *spec],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            namestat = subprocess.check_output(
                ["git", "-C", str(repo_root), "diff", "--name-status", "-M", *spec],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            patch = subprocess.check_output(
                ["git", "-C", str(repo_root), "diff", "-U3", *spec],
                text=True,
                stderr=subprocess.DEVNULL,
                errors="replace",
            )
            used = spec
            last_error = None
            break
        except subprocess.CalledProcessError as exc:
            last_error = exc
            continue
    if last_error is not None:
        return DiffSet(files=[], base=base, head=head or "WORKTREE")
    patches = _split_patches(patch)

    added_map: dict[str, tuple[int, int]] = {}
    for line in numstat.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, path = parts[0], parts[1], parts[2]
        added_map[path] = (int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0)

    files: list[FileDiff] = []
    for line in namestat.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]
        path = parts[-1]
        a, d = added_map.get(path, (0, 0))
        files.append(
            FileDiff(
                path=path,
                status=status,
                added=a,
                deleted=d,
                patch=patches.get(path, ""),
                skip=is_skippable(path),
            )
        )
    return DiffSet(files=files, base=base, head=head or "WORKTREE")


def _split_patches(patch: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current: list[str] = []
    path = None
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if path and current:
                out[path] = "".join(current)
            current = [line]
            # diff --git a/foo b/foo
            bits = line.strip().split(" ")
            path = bits[-1][2:] if bits[-1].startswith("b/") else bits[-1]
        else:
            current.append(line)
    if path and current:
        out[path] = "".join(current)
    return out
