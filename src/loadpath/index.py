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
# Bump when extractor/stitch node identity changes so incremental indexes rebuild.
INDEX_REVISION = "10"


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
        "docs",
        "documentation",
        "website",
        "docusaurus",
        "storybook",
        "starlight_help",
        "collected_static",
        "staticfiles",
        "locale",
    }
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix not in INDEX_EXTENSIONS:
            continue
        rel_path = path.relative_to(repo_root)
        rel = rel_path.as_posix()
        if any(part in skip_dirs for part in rel_path.parts):
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


def _config_digest(repo_root: Path) -> str:
    path = repo_root / "loadpath.yml"
    if not path.is_file():
        return ""
    return file_hash(path)


def _sidecar_digest(repo_root: Path, config: LoadpathConfig) -> str:
    digest = hashlib.sha256()
    names = list(config.openapi_paths)
    for rel in ("openapi.yaml", "openapi.yml", "openapi.json", "schema.yml", "schema.yaml", "schema.json"):
        names.append(rel)
        names.append(f"{config.django_root.rstrip('/')}/{rel}")
    for rel in sorted(set(names)):
        path = repo_root / rel
        if path.is_file():
            digest.update(rel.encode())
            digest.update(path.read_bytes())
    digest.update(_config_digest(repo_root).encode())
    digest.update(INDEX_REVISION.encode())
    return digest.hexdigest()


def index_drift(store: GraphStore, repo_root: Path, config: LoadpathConfig) -> dict:
    files = iter_source_files(repo_root, config)
    present = {path.relative_to(repo_root).as_posix() for path in files}
    indexed = set(store.indexed_paths())
    changed: list[str] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        if store.file_hash(rel) != file_hash(path):
            changed.append(rel)
    added = sorted(present - indexed)
    deleted = sorted(indexed - present)
    config_changed = _sidecar_digest(repo_root, config) != (store.get_meta("sidecar_hash") or "")
    return {
        "stale": bool(changed or added or deleted or config_changed) or store.file_count() == 0,
        "config_changed": config_changed,
        "changed": changed[:40],
        "changed_count": len(changed),
        "added": added[:40],
        "added_count": len(added),
        "deleted": deleted[:40],
        "deleted_count": len(deleted),
        "file_count": len(present),
        "indexed_count": len(indexed),
    }


def _boot_status(residuals: list[str], enabled: bool) -> tuple[str, str]:
    if not enabled:
        return "off", "boot_django is false; AST graph only"
    for line in residuals:
        if "django.setup() skipped:" in line:
            return "failed", line
        if "django.setup() overlay applied" in line:
            return "ok", line
    return "skipped", "django.setup() did not run"


def index_repo(
    repo_root: Path,
    db_path: Path | None = None,
    config: LoadpathConfig | None = None,
    incremental: bool = True,
    *,
    draft_config: bool = False,
) -> GraphStore:
    repo_root = repo_root.resolve()
    if draft_config:
        from loadpath.detect import write_draft_config

        if not (repo_root / "loadpath.yml").is_file():
            write_draft_config(repo_root)
    config = config or load_config(repo_root)
    db_path = db_path or default_db_path(repo_root)
    store = GraphStore(db_path)
    store.set_meta("repo_root", str(repo_root))

    drift = index_drift(store, repo_root, config)
    revision_changed = (store.get_meta("index_revision") or "") != INDEX_REVISION
    if incremental and store.file_count() > 0 and not drift["stale"] and not revision_changed:
        store.set_meta("reindex_skipped", "1")
        store.set_meta("files_extracted", "0")
        store.set_meta("files_skipped", str(drift["indexed_count"]))
        store.conn.commit()
        return store

    residuals: list[str] = []
    skipped: set[str] = set()
    files = iter_source_files(repo_root, config)
    present = {path.relative_to(repo_root).as_posix() for path in files}
    extracted = 0
    for stale in store.indexed_paths():
        if stale not in present:
            store.delete_file_nodes(stale)
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        digest = file_hash(path)
        if incremental and not revision_changed and store.file_hash(rel) == digest:
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
        extracted += 1

    boot = ExtractedGraph()
    if config.boot_django:
        boot = try_boot_models(repo_root, config)
        store.upsert_graph(boot)
        residuals.extend(boot.residuals)
    boot_state, boot_detail = _boot_status(boot.residuals, config.boot_django)

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
    store.set_meta("reindex_skipped", "0")
    store.set_meta("files_extracted", str(extracted))
    store.set_meta("files_skipped", str(len(skipped)))
    store.set_meta("django_boot", boot_state)
    store.set_meta("django_boot_detail", boot_detail)
    store.set_meta("config_hash", _config_digest(repo_root))
    store.set_meta("sidecar_hash", _sidecar_digest(repo_root, config))
    store.set_meta("index_revision", INDEX_REVISION)
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
