"""Auth as a first-class load path: who can hit the sinks after this change."""

from __future__ import annotations

from loadpath.graph.store import GraphStore
from loadpath.types import EdgeType, NodeType

ANONYMOUS_OK = {"AllowAny", "IsAuthenticatedOrReadOnly"}
AUTHED = {"IsAuthenticated", "IsAdminUser", "IsOwner", "DjangoModelPermissions", "TokenHasReadWriteScope"}


def auth_path(store: GraphStore, impact_nodes: list[dict], impact_edges: list[dict]) -> dict:
    views = [n for n in impact_nodes if n["type"] in {NodeType.VIEW.value, NodeType.VIEWSET_ACTION.value}]
    routes = [
        n
        for n in impact_nodes
        if n["type"]
        in {
            NodeType.ROUTE.value,
            NodeType.FASTAPI_ROUTE.value,
            NodeType.WEBSOCKET_ROUTE.value,
            NodeType.GRAPHQL_OPERATION.value,
        }
    ]
    perms_by_view: dict[str, list[str]] = {}
    for n in views:
        extra = n.get("extra") or {}
        perms_by_view[n["id"]] = list(extra.get("permissions") or extra.get("authentication") or [])

    for e in impact_edges:
        if e["type"] != EdgeType.HAS_PERMISSION.value:
            continue
        dst = next((n for n in impact_nodes if n["id"] == e["dst"]), None)
        if dst and dst["type"] == NodeType.PERMISSION.value:
            perms_by_view.setdefault(e["src"], [])
            if dst["name"] not in perms_by_view[e["src"]]:
                perms_by_view[e["src"]].append(dst["name"])

    sinks: list[dict] = []
    missing: list[dict] = []
    object_scope: list[dict] = []
    for view in views:
        extra = view.get("extra") or {}
        perms = perms_by_view.get(view["id"]) or []
        item = {
            "id": view["id"],
            "name": view["name"],
            "file_path": view.get("file_path"),
            "permissions": perms,
            "authentication": extra.get("authentication") or [],
            "get_queryset": bool(extra.get("get_queryset")),
        }
        sinks.append(item)
        if not perms and not extra.get("fastapi") and not extra.get("ninja"):
            missing.append(item)
        if extra.get("get_queryset"):
            object_scope.append(item)

    for route in routes:
        extra = route.get("extra") or {}
        if extra.get("websocket") and not extra.get("permissions"):
            missing.append(
                {
                    "id": route["id"],
                    "name": route["name"],
                    "file_path": route.get("file_path"),
                    "permissions": [],
                    "authentication": [],
                    "get_queryset": False,
                }
            )

    note = _note(sinks, missing, object_scope)
    return {
        "sinks": sinks[:24],
        "missing_permissions": missing[:12],
        "object_scope": object_scope[:12],
        "note": note,
    }


def _note(sinks: list[dict], missing: list[dict], object_scope: list[dict]) -> str:
    if not sinks:
        return "No view/route auth surface on this path"
    if missing:
        names = ", ".join(m["name"] for m in missing[:3])
        return f"No permission_classes on {names}"
    declared = sorted({p for s in sinks for p in s.get("permissions") or []})
    bit = ", ".join(declared[:4]) if declared else "undeclared"
    extra = ""
    if object_scope:
        extra = f"; {len(object_scope)} view(s) use get_queryset for object scope"
    return f"Sinks gated by {bit}{extra}"
