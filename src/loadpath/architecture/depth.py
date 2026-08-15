"""Graph survey for deep-module friction.

Vocabulary (use these terms in messages): module, interface, depth, seam,
adapter, leverage, locality. Depth is leverage at the interface, not a line-count
ratio. The deletion test asks whether removing a module concentrates complexity
or just moves it. The interface is the test surface.
"""

from __future__ import annotations

from loadpath.architecture.rules import Finding
from loadpath.config import LoadpathConfig
from loadpath.graph.store import GraphStore
from loadpath.types import EdgeType, NodeType, RuleSeverity

DEPTH_RULES = ("leaked_seam", "tests_bypass_interface")
STRENGTH_ORDER = {"strong": 0, "worth_exploring": 1, "speculative": 2}

RULE_DOCS = {
    "leaked_seam": (
        "A view queries a model past a query module that already exists in the same context. "
        "Put the queryset behind that module's interface."
    ),
    "tests_bypass_interface": (
        "Tests exercise internals (serializer/view) while the published route or page seam is untested. "
        "The interface is the test surface."
    ),
}


def evaluate_depth(store: GraphStore, config: LoadpathConfig) -> list[Finding]:
    out: list[Finding] = []
    enabled = set(config.rules)
    if "leaked_seam" in enabled:
        out.extend(_leaked_seams(store))
    if "tests_bypass_interface" in enabled:
        out.extend(_tests_bypass_interface(store))
    return out


def deepening_candidates(findings: list[Finding] | list[dict], *, limit: int = 8) -> list[dict]:
    cards: list[dict] = []
    seen: set[str] = set()
    for raw in findings:
        finding = raw if isinstance(raw, Finding) else _finding_from_dict(raw)
        if finding.waived:
            continue
        card = _card_for(finding)
        if not card:
            continue
        key = f"{card['rule']}:{card.get('node_id')}:{card['title']}"
        if key in seen:
            continue
        seen.add(key)
        cards.append(card)
    cards.sort(key=lambda c: (STRENGTH_ORDER.get(c["strength"], 9), c["title"]))
    if cards:
        cards[0] = {**cards[0], "top": True}
    return cards[:limit]


def _finding_from_dict(raw: dict) -> Finding:
    return Finding(
        rule=str(raw.get("rule") or ""),
        severity=RuleSeverity(raw.get("severity") or "warning"),
        message=str(raw.get("message") or ""),
        node_id=raw.get("node_id"),
        file_path=raw.get("file_path"),
        waived=bool(raw.get("waived")),
        extra=dict(raw.get("extra") or {}),
    )


def _card_for(finding: Finding) -> dict | None:
    extra = finding.extra or {}
    if finding.rule == "leaked_seam":
        strength = extra.get("strength") or "strong"
        module = extra.get("module") or finding.message
        service = extra.get("query_module") or "the query module"
        return {
            "rule": finding.rule,
            "strength": strength,
            "title": f"Deepen {module} behind {service}",
            "message": finding.message,
            "file_path": finding.file_path,
            "node_id": finding.node_id,
            "deletion_test": extra.get("deletion_test") or "",
            "leverage": extra.get("leverage") or "",
            "locality": extra.get("locality") or "",
            "before": extra.get("before") or "",
            "after": extra.get("after") or "",
        }
    if finding.rule == "tests_bypass_interface":
        seam = extra.get("seam") or "the published seam"
        return {
            "rule": finding.rule,
            "strength": extra.get("strength") or "worth_exploring",
            "title": f"Test {seam} as the interface",
            "message": finding.message,
            "file_path": finding.file_path,
            "node_id": finding.node_id,
            "deletion_test": extra.get("deletion_test") or "",
            "leverage": extra.get("leverage") or "",
            "locality": extra.get("locality") or "",
            "before": extra.get("before") or "",
            "after": extra.get("after") or "",
        }
    if finding.rule == "queryset_nplusone":
        name = finding.message.split(" loops", 1)[0]
        return {
            "rule": finding.rule,
            "strength": extra.get("strength") or "worth_exploring",
            "title": f"Keep {name} relation walks inside the query module",
            "message": finding.message,
            "file_path": finding.file_path,
            "node_id": finding.node_id,
            "deletion_test": (
                "Deleting the loop does not remove the relation walk — every caller would reimplement it."
            ),
            "leverage": "One select_related/prefetch at the module interface pays back at every call site.",
            "locality": "The N+1 is a locality failure: knowledge of related objects leaked into the loop.",
            "before": f"{name} iterates a queryset and touches related objects in the loop body.",
            "after": "The query module returns already-joined rows; callers do not walk relations.",
        }
    return None


def _leaked_seams(store: GraphStore) -> list[Finding]:
    views = {n["id"]: n for n in store.nodes([NodeType.VIEW])}
    models = {n["id"]: n for n in store.nodes([NodeType.MODEL])}
    services = [n for n in store.nodes([NodeType.SERVICE]) if not (n.get("extra") or {}).get("referenced")]
    services_by_ctx: dict[str, list[dict]] = {}
    for svc in services:
        ctx = svc.get("context") or ""
        services_by_ctx.setdefault(ctx, []).append(svc)
    called_by_view: dict[str, set[str]] = {v: set() for v in views}
    for edge in store.edges():
        if edge["type"] != EdgeType.CALLS.value:
            continue
        if edge["src"] in called_by_view:
            called_by_view[edge["src"]].add(edge["dst"])
    out: list[Finding] = []
    for edge in store.edges():
        if edge["type"] != EdgeType.QUERIES_MODEL.value:
            continue
        view = views.get(edge["src"])
        model = models.get(edge["dst"])
        if not view or not model:
            continue
        if (edge.get("extra") or {}).get("imported"):
            continue
        ctx = view.get("context") or ""
        peers = [
            s
            for s in services_by_ctx.get(ctx, [])
            if s["id"] not in called_by_view.get(view["id"], set())
            and s.get("file_path") != view.get("file_path")
        ]
        if not peers:
            continue
        peer = peers[0]
        out.append(
            Finding(
                rule="leaked_seam",
                severity=RuleSeverity.WARNING,
                message=(
                    f"{view['name']} queries {model.get('qualified_name')} past the "
                    f"{peer['name']} module's seam. Callers of the view learn the queryset; "
                    f"depth (leverage at the interface) is lost."
                ),
                node_id=view["id"],
                file_path=view.get("file_path"),
                extra={
                    "strength": "strong",
                    "module": view["name"],
                    "query_module": peer["name"],
                    "model": model.get("qualified_name"),
                    "deletion_test": (
                        f"Deleting {peer['name']} would not concentrate complexity — the view already "
                        f"owns the queryset. Deleting the view's queryset would reappear on every action."
                    ),
                    "leverage": (
                        f"One query module interface would pay back across {view['name']} actions and tests."
                    ),
                    "locality": "Queryset shape, select_related, and auth scoping should live in one module.",
                    "before": f"{view['name']} → {model.get('name')} (queryset in the view)",
                    "after": f"{view['name']} → {peer['name']} → {model.get('name')}",
                },
            )
        )
    return out


def _tests_bypass_interface(store: GraphStore) -> list[Finding]:
    routes = {n["id"]: n for n in store.nodes([NodeType.ROUTE, NodeType.REACT_ROUTE])}
    pages = {n["id"]: n for n in store.nodes([NodeType.PAGE])}
    views = {n["id"]: n for n in store.nodes([NodeType.VIEW])}
    serializers = {n["id"]: n for n in store.nodes([NodeType.SERIALIZER])}
    tested_src: set[str] = set()
    for edge in store.edges():
        if edge["type"] == EdgeType.TESTED_BY.value:
            tested_src.add(edge["src"])
    view_of_route: dict[str, str] = {}
    ser_of_view: dict[str, str] = {}
    page_of_route: dict[str, str] = {}
    for edge in store.edges():
        if edge["type"] == EdgeType.PUBLISHES_ROUTE.value and edge["src"] in routes:
            if edge["dst"] in views:
                view_of_route[edge["src"]] = edge["dst"]
            if edge["dst"] in pages:
                page_of_route[edge["src"]] = edge["dst"]
        if edge["type"] == EdgeType.USES_SERIALIZER.value and edge["src"] in views and edge["dst"] in serializers:
            ser_of_view[edge["src"]] = edge["dst"]
    out: list[Finding] = []
    for route_id, route in routes.items():
        if route_id in tested_src:
            continue
        view_id = view_of_route.get(route_id)
        page_id = page_of_route.get(route_id)
        behind = [nid for nid in (view_id, ser_of_view.get(view_id) if view_id else None, page_id) if nid]
        tested_behind = [nid for nid in behind if nid in tested_src]
        if not tested_behind:
            continue
        seam_name = route.get("extra", {}).get("mounted_at") or route["name"]
        internals = []
        for nid in tested_behind:
            node = views.get(nid) or serializers.get(nid) or pages.get(nid) or store.get_node(nid)
            if node:
                internals.append(node["name"])
        out.append(
            Finding(
                rule="tests_bypass_interface",
                severity=RuleSeverity.WARNING,
                message=(
                    f"Tests hit {', '.join(internals)} but not the published seam {seam_name}. "
                    f"The interface is the test surface — callers and tests should cross the same seam."
                ),
                node_id=route_id,
                file_path=route.get("file_path"),
                extra={
                    "strength": "worth_exploring",
                    "seam": seam_name,
                    "tested": internals,
                    "deletion_test": (
                        "If those internal tests were deleted after a test at the route/page existed, "
                        "behaviour coverage would remain. Today they pin the implementation."
                    ),
                    "leverage": "One test through the published seam covers serializer, view, and auth together.",
                    "locality": "Verification is scattered across internals instead of concentrating at the seam.",
                    "before": f"tests → {', '.join(internals)}; {seam_name} untested",
                    "after": f"tests → {seam_name} (serializer/view stay behind the interface)",
                },
            )
        )
    return out
