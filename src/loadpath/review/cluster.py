from __future__ import annotations

from collections import defaultdict

from loadpath.graph.store import GraphStore
from loadpath.review.diff import DiffSet
from loadpath.types import NodeType, SINK_TYPES

CLUSTER_SEED_PRIORITY = [
    NodeType.SERIALIZER,
    NodeType.SERIALIZER_FIELD,
    NodeType.MODEL,
    NodeType.FIELD,
    NodeType.ROUTE,
    NodeType.VIEW,
    NodeType.TASK,
    NodeType.RECEIVER,
    NodeType.PAGE,
    NodeType.FORM_SCHEMA,
    NodeType.HOOK,
    NodeType.COMPONENT,
]

# Shared hubs that connect unrelated contexts if traversed.
BRIDGE_TYPES = {
    NodeType.PERMISSION.value,
    NodeType.THROTTLE.value,
    NodeType.APP.value,
    NodeType.BOUNDED_CONTEXT.value,
    NodeType.URL_NAME.value,
}

FORWARD_TYPES = {
    "has_field",
    "serializes",
    "uses_serializer",
    "publishes_route",
    "consumed_by_client",
    "matches_schema",
    "enqueues",
    "emits_signal",
    "receives",
    "calls",
    "renders",
    "queries_model",
    "uses_query_key",
    "serves",
    "relates_to",
    "tested_by",
    "has_permission",
    "belongs_to",
}

BACKWARD_TYPES = {
    "uses_serializer",
    "publishes_route",
    "consumed_by_client",
    "has_field",
    "serializes",
    "calls",
    "matches_schema",
    "enqueues",
    "tested_by",
    "queries_model",
    "emits_signal",
    "receives",
    "uses_query_key",
    "belongs_to",
}


def impact_walk(store: GraphStore, seed_ids: set[str], hops: int = 8) -> tuple[list[dict], list[dict]]:
    if not seed_ids:
        return [], []
    by_id = {n["id"]: n for n in store.nodes()}
    outgoing: dict[str, list[dict]] = defaultdict(list)
    incoming: dict[str, list[dict]] = defaultdict(list)
    for e in store.edges():
        outgoing[e["src"]].append(e)
        incoming[e["dst"]].append(e)

    seen = set(seed_ids)
    kept_edges: dict[str, dict] = {}
    frontier = set(seed_ids)

    def include(nid: str, expand: bool) -> None:
        if nid not in by_id:
            return
        if nid not in seen:
            seen.add(nid)
            if expand:
                frontier.add(nid)

    for _ in range(hops):
        nxt: set[str] = set()
        working = set(frontier)
        frontier.clear()
        for nid in working:
            node = by_id.get(nid) or {}
            if node.get("type") in BRIDGE_TYPES:
                continue
            for e in outgoing.get(nid, []):
                if e["type"] not in FORWARD_TYPES:
                    continue
                other = e["dst"]
                other_node = by_id.get(other) or {}
                expand = other_node.get("type") not in BRIDGE_TYPES
                include(other, expand)
                kept_edges[e["id"]] = e
                if expand and other not in working:
                    nxt.add(other)
            for e in incoming.get(nid, []):
                if e["type"] not in BACKWARD_TYPES:
                    continue
                if e["type"] == "renders":
                    continue
                if e["type"] == "belongs_to" and node.get("type") != NodeType.FEATURE_MODULE.value:
                    continue
                other = e["src"]
                other_node = by_id.get(other) or {}
                if other_node.get("type") in BRIDGE_TYPES:
                    kept_edges[e["id"]] = e
                    include(other, False)
                    continue
                include(other, True)
                kept_edges[e["id"]] = e
                if other not in working:
                    nxt.add(other)
        frontier = {i for i in nxt if i not in working}

    nodes = [by_id[i] for i in seen if i in by_id]
    return nodes, list(kept_edges.values())


def cluster_diff(
    store: GraphStore,
    diff: DiffSet,
    hops: int = 8,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (clusters, impact_nodes, impact_edges)."""
    changed_paths = [f.path for f in diff.files if not f.skip]
    seeds = store.nodes_in_files(changed_paths)
    seed_ids = {n["id"] for n in seeds}
    nodes, edges = impact_walk(store, seed_ids, hops=hops) if seed_ids else ([], [])

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for n in seeds:
        find(n["id"])
    for e in edges:
        if e["src"] in seed_ids:
            union(e["src"], e["dst"])
        if e["dst"] in seed_ids:
            union(e["dst"], e["src"])

    seed_groups: dict[str, list[dict]] = defaultdict(list)
    for n in seeds:
        seed_groups[find(n["id"])].append(n)

    clusters = []
    for cid, members in seed_groups.items():
        files = sorted({m["file_path"] for m in members if m.get("file_path")})
        title = _cluster_title(members)
        related = _related_nodes(members, nodes)
        clusters.append(
            {
                "id": cid,
                "title": title,
                "files": files,
                "seed_ids": [m["id"] for m in members],
                "node_ids": [n["id"] for n in related],
                "kinds": sorted({m["type"] for m in members}),
                "contexts": sorted({m["context"] for m in members if m.get("context")}),
            }
        )
    clusters.sort(key=lambda c: (-len(c["files"]), c["title"]))
    return clusters, nodes, edges


def _cluster_title(members: list[dict]) -> str:
    by_type = {m["type"]: m for m in members}
    for ntype in CLUSTER_SEED_PRIORITY:
        if ntype.value in by_type:
            m = by_type[ntype.value]
            return f"{m['name']} ({ntype.value.split('.')[-1]})"
    if members:
        ctx = members[0].get("context") or "change"
        return f"{ctx} cluster"
    return "Unclustered"


def _related_nodes(members: list[dict], all_nodes: list[dict]) -> list[dict]:
    ids = {m["id"] for m in members}
    prefixes = {m["qualified_name"].split(".")[0] for m in members}
    related = []
    for n in all_nodes:
        if n["id"] in ids:
            related.append(n)
            continue
        q = n.get("qualified_name") or ""
        if q.split(".")[0] in prefixes and n.get("type") in {t.value for t in SINK_TYPES}:
            related.append(n)
    return related
