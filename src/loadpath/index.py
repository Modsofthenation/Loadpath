from __future__ import annotations

import hashlib
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loadpath.config import LoadpathConfig, load_config
from loadpath.extractors.django import extract_django_file
from loadpath.extractors.react import extract_react_file
from loadpath.extractors.templates import extract_template_file
from loadpath.extractors.django_boot import try_boot_models
from loadpath.graph.store import GraphStore
from loadpath.stitch.openapi import stitch
from loadpath.types import GENERATED_PATH_MARKERS, ExtractedGraph, Node, NodeType, node_id

PY_SKIP = {"migrations"}  # still extract migrations, just not skip
INDEX_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".htm"}
# Bump when extractor/stitch node identity changes so incremental indexes rebuild.
INDEX_REVISION = "10"
_UPSERT_BATCH = 25

ProgressCallback = Callable[[dict[str, Any]], None]


class SourceFile:
    __slots__ = ("path", "rel", "digest")

    def __init__(self, path: Path, rel: str, digest: str) -> None:
        self.path = path
        self.rel = rel
        self.digest = digest


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


def _hash_job(path: str) -> str:
    return file_hash(Path(path))


def language_for(path: Path) -> str:
    if path.suffix == ".py":
        return "python"
    if path.suffix in {".html", ".htm"}:
        return "html"
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


def _emit(progress: ProgressCallback | None, event: dict[str, Any]) -> None:
    if progress is None:
        return
    progress(event)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def default_workers(n_files: int) -> int:
    env = os.environ.get("LOADPATH_INDEX_JOBS", "").strip()
    if env.isdigit():
        return max(1, int(env))
    if getattr(sys, "frozen", False):
        return 1
    if n_files < 6:
        return 1
    cpu = os.cpu_count() or 2
    return max(1, min(8, cpu, n_files))


def list_source_files(
    repo_root: Path,
    config: LoadpathConfig,
    *,
    hash_workers: int | None = None,
    progress: ProgressCallback | None = None,
    started: float | None = None,
) -> list[SourceFile]:
    """Scan once and hash each source file. Hashing is I/O-bound, so threads help."""
    started = time.monotonic() if started is None else started
    paths = iter_source_files(repo_root, config)
    _emit(
        progress,
        {
            "phase": "scan",
            "done": 0,
            "total": len(paths),
            "elapsed_ms": _elapsed_ms(started),
            "message": f"Scanning {len(paths)} source files",
        },
    )
    if not paths:
        return []
    workers = hash_workers if hash_workers is not None else (1 if len(paths) < 8 else min(8, len(paths)))
    out: list[SourceFile] = []
    if workers <= 1:
        for i, path in enumerate(paths, start=1):
            rel = path.relative_to(repo_root).as_posix()
            out.append(SourceFile(path, rel, file_hash(path)))
            if i == 1 or i == len(paths) or i % 25 == 0:
                _emit(
                    progress,
                    {
                        "phase": "scan",
                        "done": i,
                        "total": len(paths),
                        "current": rel,
                        "elapsed_ms": _elapsed_ms(started),
                        "message": f"Hashed {i}/{len(paths)} files",
                    },
                )
        return out
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_hash_job, str(path)): path for path in paths}
        done = 0
        for fut in as_completed(futs):
            path = futs[fut]
            rel = path.relative_to(repo_root).as_posix()
            out.append(SourceFile(path, rel, fut.result()))
            done += 1
            if done == 1 or done == len(paths) or done % 25 == 0:
                _emit(
                    progress,
                    {
                        "phase": "scan",
                        "done": done,
                        "total": len(paths),
                        "current": rel,
                        "elapsed_ms": _elapsed_ms(started),
                        "message": f"Hashed {done}/{len(paths)} files",
                    },
                )
    by_path = {src.path: src for src in out}
    return [by_path[path] for path in paths]


def index_drift(
    store: GraphStore,
    repo_root: Path,
    config: LoadpathConfig,
    files: list[SourceFile] | None = None,
) -> dict:
    files = files if files is not None else list_source_files(repo_root, config)
    present = {src.rel for src in files}
    indexed = set(store.indexed_paths())
    changed: list[str] = []
    for src in files:
        if store.file_hash(src.rel) != src.digest:
            changed.append(src.rel)
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


def _extract_one(rel: str, path: Path, config: LoadpathConfig) -> ExtractedGraph:
    source = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix in {".html", ".htm"}:
        graph = extract_template_file(rel, source, config)
    elif path.suffix == ".py":
        graph = extract_django_file(rel, source, config)
    else:
        graph = extract_react_file(rel, source, config)
    _assign_contexts(graph, config, rel)
    return graph


def _extract_job(payload: tuple[str, str, LoadpathConfig]) -> tuple[str, ExtractedGraph | None, str | None]:
    """Picklable worker: extract one file. Must stay at module level for spawn."""
    rel, path, config = payload
    try:
        return rel, _extract_one(rel, Path(path), config), None
    except Exception as exc:  # pragma: no cover - surfaced as residual
        return rel, None, f"{type(exc).__name__}: {exc}"


def _extract_sequential(
    files: list[SourceFile],
    config: LoadpathConfig,
    *,
    started: float,
    progress: ProgressCallback | None,
    workers: int = 1,
) -> list[tuple[SourceFile, ExtractedGraph | None, str | None]]:
    results: list[tuple[SourceFile, ExtractedGraph | None, str | None]] = []
    total = len(files)
    for i, src in enumerate(files, start=1):
        _emit(
            progress,
            {
                "phase": "extract",
                "done": i - 1,
                "total": total,
                "current": src.rel,
                "workers": workers,
                "elapsed_ms": _elapsed_ms(started),
                "message": f"Extracting {src.rel} ({i}/{total})",
            },
        )
        try:
            results.append((src, _extract_one(src.rel, src.path, config), None))
        except Exception as exc:
            results.append((src, None, f"{type(exc).__name__}: {exc}"))
        _emit(
            progress,
            {
                "phase": "extract",
                "done": i,
                "total": total,
                "current": src.rel,
                "workers": workers,
                "elapsed_ms": _elapsed_ms(started),
                "message": f"Extracted {src.rel} ({i}/{total})",
            },
        )
    return results


def _extract_parallel(
    files: list[SourceFile],
    config: LoadpathConfig,
    *,
    workers: int,
    started: float,
    progress: ProgressCallback | None,
) -> list[tuple[SourceFile, ExtractedGraph | None, str | None]]:
    by_rel = {src.rel: src for src in files}
    total = len(files)
    found: dict[str, tuple[ExtractedGraph | None, str | None]] = {}
    ctx = multiprocessing.get_context("spawn")
    _emit(
        progress,
        {
            "phase": "extract",
            "done": 0,
            "total": total,
            "workers": workers,
            "elapsed_ms": _elapsed_ms(started),
            "message": f"Extracting {total} files with {workers} workers",
        },
    )
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        futs = {
            pool.submit(_extract_job, (src.rel, str(src.path), config)): src.rel for src in files
        }
        done = 0
        for fut in as_completed(futs):
            rel = futs[fut]
            try:
                _, graph, err = fut.result()
            except Exception as exc:
                graph, err = None, f"{type(exc).__name__}: {exc}"
            found[rel] = (graph, err)
            done += 1
            _emit(
                progress,
                {
                    "phase": "extract",
                    "done": done,
                    "total": total,
                    "current": rel,
                    "workers": workers,
                    "elapsed_ms": _elapsed_ms(started),
                    "message": f"Extracted {rel} ({done}/{total})",
                },
            )
    return [(src, found[src.rel][0], found[src.rel][1]) for src in files]


def index_repo(
    repo_root: Path,
    db_path: Path | None = None,
    config: LoadpathConfig | None = None,
    incremental: bool = True,
    *,
    draft_config: bool = False,
    progress: ProgressCallback | None = None,
    workers: int | None = None,
) -> GraphStore:
    repo_root = repo_root.resolve()
    started = time.monotonic()
    if draft_config:
        from loadpath.detect import write_draft_config

        if not (repo_root / "loadpath.yml").is_file():
            write_draft_config(repo_root)
    config = config or load_config(repo_root)
    db_path = db_path or default_db_path(repo_root)
    store = GraphStore(db_path)
    store.set_meta("repo_root", str(repo_root))

    _emit(
        progress,
        {
            "phase": "scan",
            "done": 0,
            "total": 0,
            "elapsed_ms": 0,
            "message": "Scanning source files",
        },
    )
    files = list_source_files(repo_root, config, progress=progress, started=started)
    n_cpu = workers if workers is not None else default_workers(len(files))
    drift = index_drift(store, repo_root, config, files=files)
    revision_changed = (store.get_meta("index_revision") or "") != INDEX_REVISION
    if incremental and store.file_count() > 0 and not drift["stale"] and not revision_changed:
        store.set_meta("reindex_skipped", "1")
        store.set_meta("files_extracted", "0")
        store.set_meta("files_skipped", str(drift["indexed_count"]))
        store.set_meta("index_workers", "0")
        store.set_meta("index_elapsed_ms", str(_elapsed_ms(started)))
        store.conn.commit()
        _emit(
            progress,
            {
                "phase": "skipped",
                "done": drift["indexed_count"],
                "total": drift["indexed_count"],
                "skipped": drift["indexed_count"],
                "workers": 0,
                "elapsed_ms": _elapsed_ms(started),
                "message": f"Index already current ({drift['indexed_count']} files unchanged)",
            },
        )
        return store

    residuals: list[str] = []
    skipped: set[str] = set()
    present = {src.rel for src in files}
    extracted = 0
    used_workers = 1
    for stale in store.indexed_paths():
        if stale not in present:
            store.delete_file_nodes(stale)

    to_extract: list[SourceFile] = []
    for src in files:
        if incremental and not revision_changed and store.file_hash(src.rel) == src.digest:
            skipped.add(src.rel)
            continue
        to_extract.append(src)

    _emit(
        progress,
        {
            "phase": "extract",
            "done": 0,
            "total": len(to_extract),
            "workers": n_cpu,
            "skipped": len(skipped),
            "elapsed_ms": _elapsed_ms(started),
            "message": (
                f"Extracting {len(to_extract)} of {len(files)} files"
                if to_extract
                else f"Nothing to extract ({len(skipped)} unchanged)"
            ),
        },
    )

    results: list[tuple[SourceFile, ExtractedGraph | None, str | None]] = []
    if to_extract:
        if n_cpu > 1 and len(to_extract) > 1:
            try:
                results = _extract_parallel(
                    to_extract,
                    config,
                    workers=n_cpu,
                    started=started,
                    progress=progress,
                )
                used_workers = n_cpu
            except (BrokenProcessPool, OSError, PermissionError):
                results = _extract_sequential(
                    to_extract, config, started=started, progress=progress, workers=1
                )
                used_workers = 1
        else:
            results = _extract_sequential(
                to_extract, config, started=started, progress=progress, workers=1
            )
            used_workers = 1

    pending = 0
    for src, graph, err in results:
        if err or graph is None:
            residuals.append(f"Failed to extract {src.rel}: {err or 'unknown error'}")
            continue
        store.delete_file_nodes(src.rel, drop_incoming=False)
        store.upsert_file(src.rel, src.digest, language_for(src.path))
        store.upsert_graph(graph, commit=False)
        residuals.extend(graph.residuals)
        extracted += 1
        pending += 1
        if pending >= _UPSERT_BATCH:
            store.conn.commit()
            pending = 0
    if pending:
        store.conn.commit()

    _emit(
        progress,
        {
            "phase": "boot",
            "done": 0,
            "total": 1,
            "elapsed_ms": _elapsed_ms(started),
            "message": "Booting Django models (optional)",
        },
    )
    boot = ExtractedGraph()
    if config.boot_django:
        boot = try_boot_models(repo_root, config)
        store.upsert_graph(boot)
        residuals.extend(boot.residuals)
    boot_state, boot_detail = _boot_status(boot.residuals, config.boot_django)

    _emit(
        progress,
        {
            "phase": "stitch",
            "done": 0,
            "total": 1,
            "elapsed_ms": _elapsed_ms(started),
            "message": "Stitching contracts (OpenAPI, GraphQL, HTMX)",
        },
    )
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
    elapsed = _elapsed_ms(started)
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
    store.set_meta("index_workers", str(used_workers))
    store.set_meta("index_elapsed_ms", str(elapsed))
    store.conn.commit()
    _emit(
        progress,
        {
            "phase": "done",
            "done": extracted,
            "total": len(files),
            "skipped": len(skipped),
            "workers": used_workers,
            "elapsed_ms": elapsed,
            "errors": sum(1 for line in residuals if line.startswith("Failed to extract ")),
            "message": (
                f"Indexed {extracted} files ({len(skipped)} unchanged) in {elapsed}ms"
                if extracted
                else f"Indexed 0 files ({len(skipped)} unchanged) in {elapsed}ms"
            ),
        },
    )
    return store


def _assign_contexts(graph: ExtractedGraph, config: LoadpathConfig, rel: str) -> None:
    for node in graph.nodes:
        if node.context:
            continue
        if node.type.value.startswith(("django.", "react.", "fastapi.", "graphql.")):
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
