"""Index → architecture snapshot used by review, CLI, and the app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loadpath.architecture.depth import deepening_candidates
from loadpath.architecture.rules import evaluate
from loadpath.config import LoadpathConfig, load_config
from loadpath.graph.store import GraphStore
from loadpath.index import default_db_path, index_drift
from loadpath.types import NodeType

ARCHITECTURE_NODE_TYPES = {
    NodeType.BOUNDED_CONTEXT.value,
    NodeType.APP.value,
    NodeType.ROUTE.value,
    NodeType.VIEW.value,
    NodeType.SERIALIZER.value,
    NodeType.MODEL.value,
    NodeType.TASK.value,
    NodeType.MANAGEMENT_COMMAND.value,
    NodeType.SIGNAL.value,
    NodeType.RECEIVER.value,
    NodeType.OPENAPI_PATH.value,
    NodeType.PAGE.value,
    NodeType.FEATURE_MODULE.value,
    NodeType.HOOK.value,
    NodeType.API_CLIENT.value,
    NodeType.FORM_SCHEMA.value,
}


def summarize_index(store: GraphStore, config: LoadpathConfig) -> dict[str, Any]:
    raw_findings = evaluate(store, config)
    findings = [f.to_dict() for f in raw_findings]
    residuals = [line for line in (store.get_meta("residuals") or "").splitlines() if line]
    contexts = {
        name: {
            "name": name,
            "django_apps": ctx.django_apps,
            "react": ctx.react,
            "public_api": ctx.public_api,
            "owners": ctx.owners,
        }
        for name, ctx in config.contexts.items()
    }
    drift = index_drift(store, config.repo_root, config)
    boot_residuals = [line for line in residuals if "django.setup()" in line]
    return {
        "ok": True,
        "indexed": True,
        "repo_root": store.get_meta("repo_root") or str(config.repo_root),
        "db": str(store.db_path),
        "indexed_at": store.get_meta("indexed_at"),
        "incremental": store.get_meta("incremental") == "1",
        "reindex_skipped": store.get_meta("reindex_skipped") == "1",
        "files_extracted": int(store.get_meta("files_extracted") or 0),
        "files_skipped": int(store.get_meta("files_skipped") or 0),
        "django_boot": store.get_meta("django_boot") or "off",
        "django_boot_detail": store.get_meta("django_boot_detail") or "",
        "stale": drift["stale"],
        "drift": drift,
        "counts": store.counts(),
        "type_counts": store.type_counts(),
        "file_count": store.file_count(),
        "contexts": contexts,
        "rules": list(config.rules),
        "findings": findings,
        "deepening": deepening_candidates(raw_findings),
        "residuals": residuals[:40],
        "boot_residuals": boot_residuals,
        "has_config": (config.repo_root / "loadpath.yml").is_file(),
    }


def architecture_graph(store: GraphStore) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [n for n in store.nodes() if n["type"] in ARCHITECTURE_NODE_TYPES]
    ids = {n["id"] for n in nodes}
    edges = [e for e in store.edges() if e["src"] in ids and e["dst"] in ids]
    return nodes, edges


def architecture_report(repo_root: Path, db_path: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    db = db_path or default_db_path(repo_root)
    if not db.is_file():
        cfg = load_config(repo_root)
        return {
            "ok": False,
            "indexed": False,
            "stale": True,
            "django_boot": "off",
            "django_boot_detail": "",
            "repo_root": str(repo_root),
            "db": str(db),
            "has_config": (repo_root / "loadpath.yml").is_file(),
            "contexts": {
                name: {
                    "name": name,
                    "django_apps": ctx.django_apps,
                    "react": ctx.react,
                    "public_api": ctx.public_api,
                    "owners": ctx.owners,
                }
                for name, ctx in cfg.contexts.items()
            },
            "rules": list(cfg.rules),
            "counts": {"nodes": 0, "edges": 0},
            "type_counts": {},
            "findings": [],
            "deepening": [],
            "residuals": [],
            "nodes": [],
            "edges": [],
        }
    store = GraphStore(db)
    config = load_config(repo_root)
    summary = summarize_index(store, config)
    nodes, edges = architecture_graph(store)
    summary["nodes"] = nodes
    summary["edges"] = edges
    store.close()
    return summary
