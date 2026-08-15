"""First-run layout detection. Drafts loadpath.yml; never overwrites one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from loadpath.config import DEFAULT_RULES, LoadpathConfig, find_config

SKIP_DIRS = {
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
    "site-packages",
    "docs",
    "documentation",
    "website",
    "docusaurus",
    "storybook",
    "starlight_help",
}

TESTISH_PARTS = {"test", "tests", "testing"}


def _skip(path: Path) -> bool:
    return any(part in SKIP_DIRS or part.startswith(".") for part in path.parts)


def detect_layout(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    django_root = _detect_django_root(repo_root)
    react_root = _detect_react_root(repo_root)
    apps = _django_apps(repo_root, django_root)
    features = _react_features(repo_root, react_root)
    contexts = _guess_contexts(apps, features, react_root)
    return {
        "repo_root": str(repo_root),
        "django_root": django_root,
        "react_root": react_root,
        "django_apps": apps,
        "react_features": features,
        "contexts": contexts,
        "has_config": find_config(repo_root) is not None,
        "manage_py": _first(repo_root, "manage.py"),
        "package_json": _first(repo_root, "package.json"),
    }


def draft_config_text(layout: dict[str, Any]) -> str:
    contexts: dict[str, Any] = {}
    for name, ctx in (layout.get("contexts") or {}).items():
        contexts[name] = {
            "django_apps": list(ctx.get("django_apps") or []),
            "react": list(ctx.get("react") or []),
            "public_api": list(ctx.get("public_api") or []),
            "owners": list(ctx.get("owners") or [f"{name}-team"]),
        }
    payload = {
        "contexts": contexts,
        "layers": {
            "django": ["route", "view", "service", "model"],
            "react": ["route", "page", "feature", "shared"],
        },
        "rules": list(DEFAULT_RULES),
        "django_root": layout.get("django_root") or "backend",
        "react_root": layout.get("react_root") or "frontend/src",
        "openapi_paths": [],
        "boot_django": False,
    }
    header = (
        "# Drafted by `loadpath init`. Edit contexts, public_api, and owners — "
        "this is the architecture Loadpath will enforce.\n"
    )
    return header + yaml.safe_dump(payload, sort_keys=False)


def write_draft_config(repo_root: Path, *, overwrite: bool = False) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    layout = detect_layout(repo_root)
    path = repo_root / "loadpath.yml"
    wrote = False
    if path.is_file() and not overwrite:
        layout["config_path"] = str(path)
        layout["wrote"] = False
        layout["message"] = "loadpath.yml already exists; left it unchanged"
        return layout
    path.write_text(draft_config_text(layout), encoding="utf-8")
    wrote = True
    layout["config_path"] = str(path)
    layout["wrote"] = wrote
    layout["has_config"] = True
    layout["message"] = f"Wrote {path}"
    return layout


def ensure_config(repo_root: Path) -> LoadpathConfig:
    """Load config, drafting a manifest first when the repo has none."""
    from loadpath.config import load_config

    if find_config(repo_root) is None:
        write_draft_config(repo_root)
    return load_config(repo_root)


def _first(repo_root: Path, name: str) -> str | None:
    for path in repo_root.rglob(name):
        if _skip(path):
            continue
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
    return None


def _is_testish(rel: Path) -> bool:
    return any(part in TESTISH_PARTS for part in rel.parts)


def _detect_django_root(repo_root: Path) -> str:
    """Prefer the package that holds real apps, not a nested test project's manage.py."""
    parents: list[tuple[str, ...]] = []
    for marker in repo_root.rglob("apps.py"):
        if _skip(marker):
            continue
        app_dir = marker.parent
        if app_dir.name in {"migrations", "tests", "management"}:
            continue
        rel = app_dir.relative_to(repo_root)
        if _is_testish(rel):
            continue
        parents.append(rel.parent.parts)
    if parents:
        common: list[str] = []
        for items in zip(*parents):
            if len(set(items)) == 1:
                common.append(items[0])
            else:
                break
        return "/".join(common) if common else "."

    manages = [p for p in repo_root.rglob("manage.py") if not _skip(p)]
    manages.sort(key=lambda p: (_is_testish(p.relative_to(repo_root)), len(p.relative_to(repo_root).parts)))
    if manages:
        rel = manages[0].parent.relative_to(repo_root)
        return rel.as_posix() if rel.parts else "."
    for candidate in ("backend", "server", "api", "app"):
        if (repo_root / candidate).is_dir():
            return candidate
    return "backend"


PREFERRED_REACT_ROOTS = (
    "frontend/src",
    "frontend",
    "src-ui/src",
    "web/src",
    "client/src",
    "ui/src",
)

SKIP_REACT_PARTS = {
    "docs",
    "documentation",
    "website",
    "docusaurus",
    "storybook",
    "starlight_help",
    "e2e",
    "cypress",
}


def _package_has_react(pkg: Path) -> bool:
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    return "react" in deps or "react-dom" in deps


def _detect_react_root(repo_root: Path) -> str:
    for candidate in PREFERRED_REACT_ROOTS:
        path = repo_root / candidate
        if path.is_dir():
            return candidate

    scored: list[tuple[int, str]] = []
    for pkg in repo_root.rglob("package.json"):
        if _skip(pkg):
            continue
        if any(part in SKIP_REACT_PARTS for part in pkg.parts):
            continue
        if not _package_has_react(pkg):
            continue
        src = pkg.parent / "src"
        root = src if src.is_dir() else pkg.parent
        rel = root.relative_to(repo_root).as_posix()
        score = 0
        if any(token in rel.split("/") for token in {"frontend", "web", "ui", "client", "src-ui"}):
            score += 10
        if src.is_dir():
            score += 5
        scored.append((score, rel))
    if scored:
        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        return scored[0][1]
    return "frontend/src"


def _django_apps(repo_root: Path, django_root: str) -> list[str]:
    root = repo_root / django_root
    if not root.is_dir():
        root = repo_root
    apps: list[str] = []
    for marker in root.rglob("apps.py"):
        if _skip(marker):
            continue
        rel = marker.relative_to(repo_root)
        if _is_testish(rel) or marker.parent.name in {"migrations", "tests", "management"}:
            continue
        name = marker.parent.name
        if name not in apps and name not in {"config", "project", "settings"}:
            apps.append(name)
    if not apps:
        for marker in root.rglob("models.py"):
            if _skip(marker) or _is_testish(marker.relative_to(repo_root)):
                continue
            name = marker.parent.name
            if name not in apps and name not in {"migrations", "config"}:
                apps.append(name)
    return sorted(apps)


def _react_features(repo_root: Path, react_root: str) -> list[str]:
    features_dir = repo_root / react_root / "features"
    if not features_dir.is_dir():
        return []
    return sorted(p.name for p in features_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def _guess_contexts(apps: list[str], features: list[str], react_root: str) -> dict[str, Any]:
    aliases = {"auth": "identity", "accounts": "identity", "users": "identity"}
    names = sorted({aliases.get(n, n) for n in apps} | {aliases.get(n, n) for n in features})
    if not names:
        names = ["app"]
    contexts: dict[str, Any] = {}
    for name in names:
        django_apps = [a for a in apps if aliases.get(a, a) == name]
        react = [
            f"{react_root}/features/{feat}"
            for feat in features
            if aliases.get(feat, feat) == name
        ]
        contexts[name] = {
            "django_apps": django_apps,
            "react": react,
            "public_api": [],
            "owners": [f"{name}-team"],
        }
    return contexts
