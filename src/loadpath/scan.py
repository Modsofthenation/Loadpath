"""Pruned filesystem walks for index and detect.

`Path.rglob("*")` descends into `node_modules` / `.git` / `dist` before any
per-file filter runs. On an installed JS app that walk dominates both
`loadpath index` and every architecture load (mtime drift).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

# Directory names that never contain first-party Django/React we want to overlay.
SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".loadpath",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "docs",
    "documentation",
    "website",
    "docusaurus",
    "storybook",
    "starlight_help",
    "collected_static",
    "staticfiles",
    "locale",
    "site-packages",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    "coverage",
    "htmlcov",
    ".tox",
    ".nox",
    ".yarn",
    ".pnpm-store",
}

INDEX_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".htm", ".graphql", ".gql"}
SKIP_INDEX_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
MAX_SOURCE_BYTES = 1_048_576


def skip_dir_name(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.startswith(".")


def is_minified_name(name: str) -> bool:
    lowered = name.lower()
    return ".min." in lowered or lowered.endswith(".bundle.js") or lowered.endswith(".d.ts")


def walk_files(root: Path) -> Iterator[Path]:
    """Yield files under `root`, never descending into skip directories."""
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = [name for name in dirnames if not skip_dir_name(name)]
        base = Path(dirpath)
        for name in filenames:
            yield base / name


def iter_named_files(root: Path, names: Iterable[str]) -> Iterator[Path]:
    want = {n.lower() for n in names}
    for path in walk_files(root):
        if path.name.lower() in want:
            yield path


def iter_source_paths(root: Path, *, extensions: set[str] | None = None) -> Iterator[Path]:
    """First-party source files Loadpath will extract."""
    want = extensions if extensions is not None else INDEX_EXTENSIONS
    for path in walk_files(root):
        if path.suffix not in want:
            continue
        if path.name in SKIP_INDEX_NAMES or is_minified_name(path.name):
            continue
        yield path
