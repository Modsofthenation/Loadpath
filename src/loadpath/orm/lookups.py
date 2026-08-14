"""Path-local missing-index hints from .filter() / .order_by() vs field extras."""

from __future__ import annotations

import ast

from loadpath.types import ExtractedGraph, NodeType

PREFERRED_OWNERS = {
    NodeType.VIEW,
    NodeType.SERVICE,
    NodeType.MANAGEMENT_COMMAND,
    NodeType.TASK,
}

SKIP_LOOKUPS = {"pk", "id", "pk__in", "id__in"}


def apply_lookups(graph: ExtractedGraph, tree: ast.AST) -> None:
    hits = scan_lookups(tree)
    if not hits:
        return
    by_owner: dict[str, list[dict]] = {}
    for item in hits:
        by_owner.setdefault(item["owner"], []).append(item)
    for owner_name, items in by_owner.items():
        owner = _owner_node(graph, owner_name)
        if owner is None:
            continue
        bucket = list(owner.extra.get("lookups") or [])
        bucket.extend(items)
        owner.extra["lookups"] = bucket


def _owner_node(graph: ExtractedGraph, name: str | None):
    if not name:
        return None
    candidates = [n for n in graph.nodes if n.name == name]
    return next((n for n in candidates if n.type in PREFERRED_OWNERS), None) or (
        candidates[0] if candidates else None
    )


def scan_lookups(tree: ast.AST) -> list[dict]:
    out: list[dict] = []

    def visit_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, owner: str) -> None:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            short = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if short not in {"filter", "exclude", "order_by", "get"}:
                continue
            fields: list[str] = []
            if short == "order_by":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        fields.append(arg.value.lstrip("-").split("__")[0])
            else:
                for kw in node.keywords:
                    if kw.arg:
                        fields.append(kw.arg.split("__")[0])
            fields = [f for f in fields if f and f not in SKIP_LOOKUPS and not f.startswith("_")]
            if not fields:
                continue
            out.append(
                {
                    "owner": owner,
                    "kind": short,
                    "fields": fields,
                    "line": getattr(node, "lineno", 0),
                }
            )
        for stmt in fn.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_function(stmt, stmt.name)

    if not isinstance(tree, ast.Module):
        return out
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_function(stmt, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_function(node, node.name)
    return out
