from __future__ import annotations

from pathlib import Path

from loadpath.architecture.snapshot import architecture_report
from loadpath.graph.store import GraphStore, linked_edges
from loadpath.review.cluster import impact_walk
from loadpath.review.engine import run_review
from loadpath.review.render import render_html
from loadpath.types import Edge, EdgeType, Node, NodeType, node_id

from tests.conftest import prepare_review_repo


def _node(ntype: NodeType, name: str, file_path: str | None = "a.py") -> Node:
    return Node(
        id=node_id(ntype, name),
        type=ntype,
        name=name,
        qualified_name=name,
        file_path=file_path,
    )


def _assert_linked(nodes: list[dict], edges: list[dict]) -> None:
    ids = {n["id"] for n in nodes}
    assert edges, "expected a non-empty linked graph"
    for edge in edges:
        assert edge["src"] in ids, f"dangling src {edge['src']} on {edge['type']}"
        assert edge["dst"] in ids, f"dangling dst {edge['dst']} on {edge['type']}"


def test_linked_edges_drops_missing_endpoints():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [
        {"id": "ok", "src": "a", "dst": "b"},
        {"id": "ghost", "src": "a", "dst": "missing"},
        {"id": "orphan", "src": "gone", "dst": "b"},
    ]
    kept = linked_edges(nodes, edges)
    assert [e["id"] for e in kept] == ["ok"]


def test_impact_walk_and_subgraph_drop_dangling_edges(tmp_path: Path):
    store = GraphStore(tmp_path / "g.sqlite3")
    view = _node(NodeType.VIEW, "InvoiceView")
    serializer = _node(NodeType.SERIALIZER, "InvoiceSerializer")
    store.upsert_node(view)
    store.upsert_node(serializer)
    store.upsert_edge(Edge(src=view.id, dst=serializer.id, type=EdgeType.USES_SERIALIZER))
    store.upsert_edge(Edge(src=view.id, dst="django.model:ghost", type=EdgeType.CALLS))
    store.conn.commit()

    nodes, edges = impact_walk(store, {view.id})
    _assert_linked(nodes, edges)
    assert serializer.id in {n["id"] for n in nodes}
    assert not any(e["dst"] == "django.model:ghost" for e in edges)

    sub_nodes, sub_edges = store.subgraph([view.id])
    _assert_linked(sub_nodes, sub_edges)
    assert not any(e["dst"] == "django.model:ghost" for e in sub_edges)
    store.close()


def test_demo_review_and_architecture_graphs_are_linked(tmp_path: Path):
    repo = prepare_review_repo(tmp_path)
    review = run_review(repo, base="HEAD~1", head="HEAD")
    _assert_linked(review["nodes"], review["edges"])
    assert review["headline"].startswith("Loadpath:")
    assert review["confidence"]["level"] in {"high", "medium", "low"}
    assert review["read_order"]
    md_html = render_html(review)
    assert "vis-network" in md_html
    assert "nodeIds.has(e.src)" in md_html

    report = architecture_report(repo)
    _assert_linked(report["nodes"], report["edges"])
