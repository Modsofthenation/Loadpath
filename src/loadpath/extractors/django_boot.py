"""Optional django.setup() overlay. AST is the default; boot enriches model _meta when settings import."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.types import Edge, EdgeType, ExtractedGraph, Node, NodeType, node_id


def try_boot_models(repo_root: Path, config: LoadpathConfig) -> ExtractedGraph:
    graph = ExtractedGraph()
    settings_mod = _discover_settings_module(repo_root)
    if not settings_mod:
        return graph
    try:
        import django
        from django.apps import apps
    except ImportError:
        graph.residuals.append("django.setup() skipped: Django is not installed (AST graph still used)")
        return graph

    prev = os.environ.get("DJANGO_SETTINGS_MODULE")
    added: list[str] = []
    try:
        root = str(repo_root)
        backend = str(repo_root / config.django_root)
        for p in (root, backend):
            if p not in sys.path:
                sys.path.insert(0, p)
                added.append(p)
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_mod
        django.setup()
        for model in apps.get_models():
            app = model._meta.app_label
            qname = f"{app}.{model.__name__}"
            context = config.context_for_django_app(app)
            graph.nodes.append(
                Node(
                    id=node_id(NodeType.MODEL, qname),
                    type=NodeType.MODEL,
                    name=model.__name__,
                    qualified_name=qname,
                    context=context,
                    extra={
                        "app": app,
                        "db_table": model._meta.db_table,
                        "booted": True,
                    },
                )
            )
            for field in model._meta.get_fields():
                fname = getattr(field, "name", None)
                if not fname:
                    continue
                extra = {
                    "app": app,
                    "field_type": field.__class__.__name__,
                    "booted": True,
                }
                if getattr(field, "is_relation", False):
                    remote = getattr(field, "related_model", None)
                    on_delete = getattr(getattr(field, "remote_field", None), "on_delete", None)
                    extra["on_delete"] = getattr(on_delete, "__name__", None) if on_delete else None
                    extra["related_name"] = getattr(field, "related_name", None)
                    if remote is not None:
                        target = f"{remote._meta.app_label}.{remote.__name__}"
                        extra["to"] = target
                        graph.edges.append(
                            Edge(
                                src=node_id(NodeType.FIELD, f"{qname}.{fname}"),
                                dst=node_id(NodeType.MODEL, target),
                                type=EdgeType.RELATES_TO,
                                extra={"on_delete": extra["on_delete"], "booted": True},
                            )
                        )
                graph.nodes.append(
                    Node(
                        id=node_id(NodeType.FIELD, f"{qname}.{fname}"),
                        type=NodeType.FIELD,
                        name=fname,
                        qualified_name=f"{qname}.{fname}",
                        context=context,
                        extra=extra,
                    )
                )
                graph.edges.append(
                    Edge(
                        src=node_id(NodeType.MODEL, qname),
                        dst=node_id(NodeType.FIELD, f"{qname}.{fname}"),
                        type=EdgeType.HAS_FIELD,
                    )
                )
        graph.residuals.append(f"django.setup() overlay applied via {settings_mod}")
    except Exception as exc:  # noqa: BLE001
        graph.residuals.append(f"django.setup() skipped: {exc}")
    finally:
        if prev is None:
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        else:
            os.environ["DJANGO_SETTINGS_MODULE"] = prev
        for p in added:
            if p in sys.path:
                sys.path.remove(p)
    return graph


def _discover_settings_module(repo_root: Path) -> str | None:
    env = os.environ.get("DJANGO_SETTINGS_MODULE")
    if env:
        return env
    for settings in repo_root.rglob("settings.py"):
        rel = settings.relative_to(repo_root).with_suffix("")
        if any(part.startswith(".") for part in rel.parts):
            continue
        if "site-packages" in rel.parts:
            continue
        return ".".join(rel.parts)
    return None
