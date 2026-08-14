from __future__ import annotations

from pathlib import Path

from loadpath.graph.store import GraphStore
from loadpath.review.confidence import score_confidence
from loadpath.review.engine import _serious_evolution_notes
from loadpath.types import Edge, EdgeType, Node, NodeType, node_id


def _store(tmp_path: Path) -> GraphStore:
    return GraphStore(tmp_path / "g.sqlite3")


def _node(ntype: NodeType, name: str, **extra) -> Node:
    return Node(
        id=node_id(ntype, name),
        type=ntype,
        name=name,
        qualified_name=name,
        extra=extra,
    )


def test_off_path_tested_by_does_not_cover_sink(tmp_path: Path):
    store = _store(tmp_path)
    sink = _node(NodeType.ROUTE, "/api/invoices/{id}")
    other = _node(NodeType.SERVICE, "unrelated")
    test = _node(NodeType.TEST, "test_unrelated")
    store.upsert_node(sink)
    store.upsert_node(other)
    store.upsert_node(test)
    store.upsert_edge(Edge(src=other.id, dst=test.id, type=EdgeType.TESTED_BY))
    store.upsert_edge(Edge(src=sink.id, dst=test.id, type=EdgeType.TESTED_BY))
    store.conn.commit()

    impact_nodes = [sink.to_row()]
    confidence = score_confidence(store, impact_nodes, impact_edges=[], findings=[], residuals=[])
    assert confidence["covered_sinks"] == 0
    assert sink.id in {s["id"] for s in confidence["untested_sinks"]}
    store.close()


def test_on_path_tested_by_covers_sink(tmp_path: Path):
    store = _store(tmp_path)
    sink = _node(NodeType.ROUTE, "/api/invoices/{id}")
    test = _node(NodeType.TEST, "test_invoice_route")
    edge = Edge(src=sink.id, dst=test.id, type=EdgeType.TESTED_BY, confidence=1.0)
    store.upsert_node(sink)
    store.upsert_node(test)
    store.upsert_edge(edge)
    store.conn.commit()

    impact_nodes = [sink.to_row(), test.to_row()]
    impact_edges = [edge.to_row()]
    confidence = score_confidence(store, impact_nodes, impact_edges, findings=[], residuals=[])
    assert confidence["covered_sinks"] == 1
    assert confidence["untested_sinks"] == []
    store.close()


def test_two_hop_tested_producer_on_path_covers_sink(tmp_path: Path):
    store = _store(tmp_path)
    sink = _node(NodeType.PAGE, "InvoicePage")
    hook = _node(NodeType.HOOK, "useInvoice")
    test = _node(NodeType.REACT_TEST, "InvoicePage.test")
    calls = Edge(src=sink.id, dst=hook.id, type=EdgeType.CALLS, confidence=1.0)
    tested = Edge(src=hook.id, dst=test.id, type=EdgeType.TESTED_BY, confidence=1.0)
    for node in (sink, hook, test):
        store.upsert_node(node)
    store.upsert_edge(calls)
    store.upsert_edge(tested)
    store.conn.commit()

    impact_nodes = [sink.to_row(), hook.to_row(), test.to_row()]
    impact_edges = [calls.to_row(), tested.to_row()]
    confidence = score_confidence(store, impact_nodes, impact_edges, findings=[], residuals=[])
    assert confidence["covered_sinks"] == 1
    store.close()


def test_weak_evolution_notes_are_not_serious():
    weak = [
        "serializers.py changed with cyclomatic complexity 4 in a historically active file",
        "billing/views.py::create changed with cyclomatic complexity 3",
    ]
    assert _serious_evolution_notes(weak) == []
    serious = [
        "billing/views.py is a hotspot (12 commits, knowledge silo: ada)",
        "Temporal coupling a.py ↔ b.py (5 co-changes, degree 0.5) crosses a bounded context",
    ]
    assert _serious_evolution_notes(serious) == serious
