"""Index → architecture snapshot used by review, CLI, and the app."""

from __future__ import annotations

import json
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
    NodeType.FORM.value,
    NodeType.MODEL.value,
    NodeType.SERVICE.value,
    NodeType.PERMISSION.value,
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
    NodeType.SERVER_ACTION.value,
    NodeType.GRAPHQL_TYPE.value,
    NodeType.GRAPHQL_OPERATION.value,
    NodeType.FASTAPI_ROUTE.value,
    NodeType.PYDANTIC_MODEL.value,
    NodeType.CONSUMER.value,
    NodeType.WEBSOCKET_ROUTE.value,
    NodeType.TEMPLATE.value,
    NodeType.CACHE_KEY.value,
    NodeType.FEATURE_FLAG.value,
    NodeType.SIDE_EFFECT.value,
}


def persist_findings(store: GraphStore, config: LoadpathConfig) -> list[dict[str, Any]]:
    """Run architecture rules once and store the result for cheap workspace loads."""
    raw = evaluate(store, config)
    findings = [f.to_dict() for f in raw]
    store.set_meta("findings_json", json.dumps(findings))
    return findings


def _load_cached_findings(store: GraphStore) -> list[dict[str, Any]] | None:
    raw = store.get_meta("findings_json")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    return payload


def summarize_index(store: GraphStore, config: LoadpathConfig, *, hash_drift: bool = False) -> dict[str, Any]:
    drift = index_drift(store, config.repo_root, config, hash_contents=hash_drift)
    findings = None if drift.get("config_changed") else _load_cached_findings(store)
    if findings is None:
        findings = persist_findings(store, config)
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
        "deepening": deepening_candidates(findings),
        "residuals": residuals[:40],
        "boot_residuals": boot_residuals,
        "has_config": (config.repo_root / "loadpath.yml").is_file(),
    }


def architecture_graph(store: GraphStore) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    types = sorted(ARCHITECTURE_NODE_TYPES)
    nodes = store.nodes(types)
    return nodes, store.edges_between_types(types)


def workspace_index_card(repo_root: Path, db_path: Path | None = None) -> dict[str, Any]:
    """Counts and contexts only — used by GET /api/repos so listing workspaces is cheap."""
    repo_root = repo_root.resolve()
    db = db_path or default_db_path(repo_root)
    has_config = (repo_root / "loadpath.yml").is_file()
    empty_contexts: dict[str, Any] = {}
    if not db.is_file():
        return {
            "indexed": False,
            "counts": {"nodes": 0, "edges": 0},
            "has_config": has_config,
            "contexts": empty_contexts,
        }
    store = GraphStore(db)
    config = load_config(repo_root)
    card = {
        "indexed": True,
        "counts": store.counts(),
        "indexed_at": store.get_meta("indexed_at"),
        "has_config": has_config,
        "contexts": {
            name: {
                "name": name,
                "django_apps": ctx.django_apps,
                "react": ctx.react,
                "public_api": ctx.public_api,
                "owners": ctx.owners,
            }
            for name, ctx in config.contexts.items()
        },
        "django_boot": store.get_meta("django_boot") or "off",
        "stale": False,
    }
    store.close()
    return card


def architecture_report(
    repo_root: Path,
    db_path: Path | None = None,
    *,
    include_graph: bool = True,
    hash_drift: bool = False,
) -> dict[str, Any]:
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
            "graph_pending": False,
        }
    store = GraphStore(db)
    config = load_config(repo_root)
    summary = summarize_index(store, config, hash_drift=hash_drift)
    if include_graph:
        nodes, edges = architecture_graph(store)
        summary["nodes"] = nodes
        summary["edges"] = edges
        summary["graph_pending"] = False
    else:
        summary["nodes"] = []
        summary["edges"] = []
        summary["graph_pending"] = True
    store.close()
    return summary
