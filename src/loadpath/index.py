from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from loadpath.config import LoadpathConfig, load_config
from loadpath.extractors.django import extract_django_file
from loadpath.extractors.react import extract_react_file
from loadpath.extractors.django_boot import try_boot_models
from loadpath.graph.store import GraphStore
from loadpath.stitch.openapi import stitch
from loadpath.types import GENERATED_PATH_MARKERS, ExtractedGraph, Node, NodeType, node_id

PY_SKIP = {"migrations"}  # still extract migrations, just not skip
INDEX_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def default_db_path(repo_root: Path) -> Path:
    return repo_root / ".loadpath" / "graph.sqlite3"


def iter_source_files(repo_root: Path, config: LoadpathConfig) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {
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
    }
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix not in INDEX_EXTENSIONS:
            continue
        rel = path.relative_to(repo_root).as_posix()
        if any(part in skip_dirs for part in path.parts):
            continue
        if any(m in rel for m in GENERATED_PATH_MARKERS if m.endswith("/") and m not in {"generated/"}):
            # still index generated clients
            pass
        if path.name in {"package-lock.json"}:
            continue
        files.append(path)
    return files


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def language_for(path: Path) -> str:
    if path.suffix == ".py":
        return "python"
    if path.suffix in {".ts", ".tsx"}:
        return "typescript"
    return "javascript"


def index_repo(
    repo_root: Path,
    db_path: Path | None = None,
    config: LoadpathConfig | None = None,
    incremental: bool = True,
) -> GraphStore:
    repo_root = repo_root.resolve()
    config = config or load_config(repo_root)
    db_path = db_path or default_db_path(repo_root)
    store = GraphStore(db_path)
    store.set_meta("repo_root", str(repo_root))

    residuals: list[str] = []
    skipped: set[str] = set()
    files = iter_source_files(repo_root, config)
    present = {path.relative_to(repo_root).as_posix() for path in files}
    for stale in store.indexed_paths():
        if stale not in present:
            store.delete_file_nodes(stale)
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        digest = file_hash(path)
        if incremental and store.file_hash(rel) == digest:
            skipped.add(rel)
            continue
        store.delete_file_nodes(rel, drop_incoming=False)
        source = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".py":
            graph = extract_django_file(rel, source, config)
        else:
            graph = extract_react_file(rel, source, config)
        _assign_contexts(graph, config, rel)
        store.upsert_file(rel, digest, language_for(path))
        store.upsert_graph(graph)
        residuals.extend(graph.residuals)

    boot = ExtractedGraph()
    if config.boot_django:
        boot = try_boot_models(repo_root, config)
        store.upsert_graph(boot)
        residuals.extend(boot.residuals)

    _ensure_context_nodes(store, config)
    stitch_residuals = stitch(store, config, repo_root)
    store.prune_dangling_edges()
    if incremental:
        old = [line for line in (store.get_meta("residuals") or "").splitlines() if line]
        changed = present - skipped
        preserved = [
            line
            for line in old
            if any(rel in line for rel in skipped) and not any(rel in line for rel in changed)
        ]
        residuals = preserved + residuals + stitch_residuals
        seen: set[str] = set()
        deduped: list[str] = []
        for line in residuals:
            if line not in seen:
                seen.add(line)
                deduped.append(line)
        residuals = deduped
    else:
        residuals.extend(stitch_residuals)
    store.set_meta("residuals", "\n".join(residuals))
    store.set_meta("indexed_at", datetime.now(timezone.utc).isoformat())
    store.set_meta("incremental", "1" if incremental else "0")
    store.conn.commit()
    return store


def _assign_contexts(graph: ExtractedGraph, config: LoadpathConfig, rel: str) -> None:
    for node in graph.nodes:
        if node.context:
            continue
        if node.type.value.startswith("django.") or node.type.value.startswith("react."):
            if rel.endswith(".py"):
                app = (node.extra or {}).get("app")
                if app:
                    node.context = config.context_for_django_app(app)
            else:
                node.context = config.context_for_react_path(rel)


def _ensure_context_nodes(store: GraphStore, config: LoadpathConfig) -> None:
    for name, ctx in config.contexts.items():
        store.upsert_node(
            Node(
                id=node_id(NodeType.BOUNDED_CONTEXT, name),
                type=NodeType.BOUNDED_CONTEXT,
                name=name,
                qualified_name=name,
                extra={"django_apps": ctx.django_apps, "react": ctx.react, "public_api": ctx.public_api},
            )
        )
        for app in ctx.django_apps:
            store.upsert_node(
                Node(
                    id=node_id(NodeType.APP, app),
                    type=NodeType.APP,
                    name=app,
                    qualified_name=app,
                    context=name,
                )
            )
            store.conn.execute(
                """
                INSERT OR IGNORE INTO edges(id, src, dst, type, weight, confidence, extra)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    f"{node_id(NodeType.APP, app)}|belongs_to|{node_id(NodeType.BOUNDED_CONTEXT, name)}",
                    node_id(NodeType.APP, app),
                    node_id(NodeType.BOUNDED_CONTEXT, name),
                    "belongs_to",
                    "cheap",
                    1.0,
                    "{}",
                ),
            )
