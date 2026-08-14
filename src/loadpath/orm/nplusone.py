"""Static N+1 detector (django-orm-lens shape) for Django source.

Flags `for x in qs:` bodies that traverse related objects without a matching
`select_related` / `prefetch_related` on that queryset. Structural only: no
Django boot. Prefers misses over invented findings.

Findings live on the enclosing view/service node (`extra.nplusone`). They are
not stored as index residuals, so a serializer-field review does not inherit
an unrelated loop in `services.py`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from loadpath.types import ExtractedGraph, NodeType

PREFERRED_OWNERS = {
    NodeType.VIEW,
    NodeType.SERVICE,
    NodeType.MANAGEMENT_COMMAND,
    NodeType.TASK,
}


@dataclass
class NPlusOne:
    line: int
    loop_var: str
    queryset: str
    accessed: list[str]
    kind: str
    suggested_fix: str
    confidence: str
    owner: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "loop_var": self.loop_var,
            "queryset": self.queryset,
            "accessed": self.accessed,
            "kind": self.kind,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "owner": self.owner,
        }


def apply_nplusone(graph: ExtractedGraph, tree: ast.AST) -> list[NPlusOne]:
    findings = scan_nplusone(tree)
    if not findings:
        return []
    for item in findings:
        owner = _owner_node(graph, item.owner)
        if owner is None:
            continue
        bucket = list(owner.extra.get("nplusone") or [])
        bucket.append(item.to_dict())
        owner.extra["nplusone"] = bucket
    return findings


def _owner_node(graph: ExtractedGraph, name: str | None):
    if not name:
        return None
    candidates = [n for n in graph.nodes if n.name == name]
    return next((n for n in candidates if n.type in PREFERRED_OWNERS), None) or (
        candidates[0] if candidates else None
    )


def scan_nplusone(tree: ast.AST) -> list[NPlusOne]:
    findings: list[NPlusOne] = []
    returns = _return_map(tree)

    def visit_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, owner: str) -> None:
        bindings: dict[str, ast.AST] = {}

        def walk_stmts(stmts: list[ast.stmt]) -> None:
            for stmt in stmts:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_function(stmt, stmt.name)
                    continue
                if isinstance(stmt, ast.ClassDef):
                    continue
                if isinstance(stmt, ast.For):
                    _scan_for(stmt, bindings, owner, findings, returns)
                    walk_stmts(stmt.body)
                    walk_stmts(stmt.orelse)
                    continue
                if isinstance(stmt, ast.If):
                    walk_stmts(stmt.body)
                    walk_stmts(stmt.orelse)
                    continue
                if isinstance(stmt, ast.While):
                    walk_stmts(stmt.body)
                    walk_stmts(stmt.orelse)
                    continue
                if isinstance(stmt, ast.With):
                    walk_stmts(stmt.body)
                    continue
                if isinstance(stmt, ast.Try):
                    walk_stmts(stmt.body)
                    for handler in stmt.handlers:
                        walk_stmts(handler.body)
                    walk_stmts(stmt.orelse)
                    walk_stmts(stmt.finalbody)
                    continue
                _bind(stmt, bindings)

        walk_stmts(list(fn.body))

    if not isinstance(tree, ast.Module):
        return findings
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_function(stmt, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_function(node, node.name)
    return findings


def _bind(stmt: ast.AST, bindings: dict[str, ast.AST]) -> None:
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = stmt.value
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
        bindings[stmt.target.id] = stmt.value


def _return_map(tree: ast.AST) -> dict[str, ast.AST]:
    """One-hop helper returns (module + class methods)."""
    out: dict[str, ast.AST] = {}

    def take(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for stmt in reversed(fn.body):
            if isinstance(stmt, ast.Return) and stmt.value is not None:
                out[fn.name] = stmt.value
                return

    if not isinstance(tree, ast.Module):
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            take(node)
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    take(stmt)
    return out


def _resolve_iter(source: ast.AST, bindings: dict[str, ast.AST], returns: dict[str, ast.AST]) -> ast.AST:
    if isinstance(source, ast.Name) and source.id in bindings:
        source = bindings[source.id]
    if isinstance(source, ast.Call):
        name = _call_name(source)
        if name in returns:
            source = returns[name]
    return source


def _scan_for(
    node: ast.For,
    bindings: dict[str, ast.AST],
    owner: str,
    findings: list[NPlusOne],
    returns: dict[str, ast.AST] | None = None,
) -> None:
    if not isinstance(node.target, ast.Name):
        return
    loop_var = node.target.id
    source = _resolve_iter(node.iter, bindings, returns or {})
    qs_text, selects, prefetches, is_qs = _queryset_shape(source)
    if not is_qs:
        return
    select_hits: list[str] = []
    prefetch_hits: list[str] = []
    for child in ast.walk(node):
        kind, field = _related_access(child, loop_var)
        if not kind or not field:
            continue
        if kind == "select_related" and field not in select_hits:
            select_hits.append(field)
        elif kind == "prefetch_related" and field not in prefetch_hits:
            prefetch_hits.append(field)
    if "*" in selects:
        select_hits = []
    else:
        select_hits = [f for f in select_hits if f.split("__")[0] not in selects]
    if "*" in prefetches:
        prefetch_hits = []
    else:
        prefetch_hits = [f for f in prefetch_hits if f.split("__")[0] not in prefetches]
    if not select_hits and not prefetch_hits:
        return
    accessed = select_hits + prefetch_hits
    if prefetch_hits and select_hits:
        kind = "select_related+prefetch_related"
    elif prefetch_hits:
        kind = "prefetch_related"
    else:
        kind = "select_related"
    bits: list[str] = []
    if select_hits:
        bits.append(".select_related(" + ", ".join(repr(f) for f in select_hits) + ")")
    if prefetch_hits:
        bits.append(".prefetch_related(" + ", ".join(repr(f) for f in prefetch_hits) + ")")
    confidence = "high" if prefetch_hits else "medium"
    findings.append(
        NPlusOne(
            line=node.lineno,
            loop_var=loop_var,
            queryset=qs_text,
            accessed=accessed,
            kind=kind,
            suggested_fix="".join(bits),
            confidence=confidence,
            owner=owner,
        )
    )


def _queryset_shape(node: ast.AST) -> tuple[str, set[str], set[str], bool]:
    text = _unparse(node)
    blob = text.replace(" ", "")
    looks = (
        ".objects." in blob
        or "get_queryset(" in blob
        or ".select_related(" in blob
        or ".prefetch_related(" in blob
        or ".all()" in blob
        or ".filter(" in blob
        or ".exclude(" in blob
        or ".annotate(" in blob
    )
    selects: set[str] = set()
    prefetches: set[str] = set()
    for call in reversed(_call_chain(node)):
        short = _call_name(call)
        args = [a for a in (_const_str(a) for a in call.args) if a]
        cleared = bool(call.args) and isinstance(call.args[0], ast.Constant) and call.args[0].value is None
        if short == "select_related":
            if cleared:
                selects.clear()
            elif args:
                selects.update(a.split("__")[0] for a in args)
            else:
                selects.add("*")
        elif short == "prefetch_related":
            if cleared:
                prefetches.clear()
            else:
                string_args = [a for a in (_const_str(a) for a in call.args) if a]
                prefetch_objs = [
                    _const_str(arg.args[0])
                    for arg in call.args
                    if isinstance(arg, ast.Call) and _call_name(arg) == "Prefetch" and arg.args
                ]
                if string_args:
                    prefetches.update(a.split("__")[0] for a in string_args)
                for inner in prefetch_objs:
                    if inner:
                        prefetches.add(inner.split("__")[0])
                if not string_args and not prefetch_objs and not any(
                    isinstance(arg, ast.Call) and _call_name(arg) == "Prefetch" for arg in call.args
                ):
                    if not call.args:
                        prefetches.add("*")
            for kw in call.keywords:
                val = kw.value
                if isinstance(val, ast.Call) and val.args:
                    inner = _const_str(val.args[0])
                    if inner:
                        prefetches.add(inner.split("__")[0])
                elif _const_str(val):
                    prefetches.add((_const_str(val) or "").split("__")[0])
    return text, selects, prefetches, looks


def _related_access(node: ast.AST, loop_var: str) -> tuple[str | None, str]:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        short = node.func.attr
        root, fields = _attr_root(node.func.value)
        if root == loop_var and fields and short in {"all", "filter", "exclude", "count", "exists"}:
            if not fields[0].startswith("_"):
                return "prefetch_related", fields[0]
    if isinstance(node, ast.Attribute):
        if node.attr in {"all", "filter", "exclude", "count", "exists", "first", "last"}:
            return None, ""
        root, fields = _attr_root(node)
        if root != loop_var or not fields:
            return None, ""
        first = fields[0]
        if first.startswith("_"):
            return None, ""
        if first.endswith("_set"):
            return "prefetch_related", first
        if len(fields) >= 2:
            return "select_related", first
    return None, ""


def _attr_root(node: ast.AST) -> tuple[str | None, list[str]]:
    fields: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        fields.append(cur.attr)
        cur = cur.value
    fields.reverse()
    if isinstance(cur, ast.Name):
        return cur.id, fields
    return None, fields


def _call_chain(node: ast.AST) -> list[ast.Call]:
    out: list[ast.Call] = []
    cur: ast.AST | None = node
    while cur is not None:
        if isinstance(cur, ast.Call):
            out.append(cur)
            nxt = cur.func
            cur = nxt.value if isinstance(nxt, ast.Attribute) else None
        elif isinstance(cur, ast.Attribute):
            cur = cur.value
        else:
            break
    return out


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__
