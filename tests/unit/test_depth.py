from __future__ import annotations

from pathlib import Path

from loadpath.architecture.depth import deepening_candidates, evaluate_depth
from loadpath.architecture.rules import evaluate
from loadpath.config import load_config
from loadpath.index import index_repo
from loadpath.review.engine import run_review
from loadpath.review.render import render_markdown
from tests.conftest import FIXTURE_ROOT as FIXTURE
from tests.conftest import prepare_review_repo


def test_fixture_leaks_queryset_past_query_module(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate_depth(store, load_config(FIXTURE))
    hits = [f for f in findings if f.rule == "leaked_seam"]
    assert hits, [f.message for f in findings]
    assert any("InvoiceViewSet" in f.message and "seam" in f.message for f in hits)
    assert any(f.extra.get("strength") == "strong" for f in hits)
    invoice_hits = [f for f in hits if "InvoiceViewSet" in f.message]
    modules = {f.extra.get("query_module") for f in invoice_hits}
    assert "services" in modules
    assert "recalculate_total" not in modules
    store.close()


def test_fixture_e2e_covers_published_invoice_seam(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate_depth(store, load_config(FIXTURE))
    hits = [f for f in findings if f.rule == "tests_bypass_interface"]
    blob = " ".join(f.message for f in hits)
    assert "/api/invoices/{id}" not in blob
    assert "/invoices/{id}" not in blob
    e2e = [
        e
        for e in store.edges()
        if e["type"] == "tested_by" and (e.get("extra") or {}).get("via") == "e2e"
    ]
    assert e2e
    store.close()


def test_tests_bypass_when_only_serializer_is_tested(tmp_path: Path):
    from loadpath.graph.store import GraphStore
    from loadpath.types import Edge, EdgeType, Node, NodeType, node_id

    store = GraphStore(tmp_path / "g.sqlite3")
    route = Node(id=node_id(NodeType.ROUTE, "billing:/secret"), type=NodeType.ROUTE, name="/secret", qualified_name="billing:/secret", extra={"route": "/secret"})
    view = Node(id=node_id(NodeType.VIEW, "billing.SecretView"), type=NodeType.VIEW, name="SecretView", qualified_name="billing.SecretView")
    ser = Node(id=node_id(NodeType.SERIALIZER, "billing.SecretSerializer"), type=NodeType.SERIALIZER, name="SecretSerializer", qualified_name="billing.SecretSerializer")
    test = Node(id=node_id(NodeType.TEST, "billing.test_secret"), type=NodeType.TEST, name="test_secret", qualified_name="billing.test_secret")
    for n in (route, view, ser, test):
        store.upsert_node(n)
    store.upsert_edge(Edge(src=route.id, dst=view.id, type=EdgeType.PUBLISHES_ROUTE))
    store.upsert_edge(Edge(src=view.id, dst=ser.id, type=EdgeType.USES_SERIALIZER))
    store.upsert_edge(Edge(src=ser.id, dst=test.id, type=EdgeType.TESTED_BY))
    store.conn.commit()
    hits = [f for f in evaluate_depth(store, load_config(FIXTURE)) if f.rule == "tests_bypass_interface"]
    assert hits
    assert any("SecretSerializer" in f.message and "/secret" in f.message for f in hits)
    store.close()


def test_architecture_survey_ranks_a_top_candidate(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(FIXTURE))
    cards = deepening_candidates(findings)
    assert cards
    assert cards[0]["top"] is True
    assert cards[0]["strength"] in {"strong", "worth_exploring", "speculative"}
    assert cards[0]["deletion_test"]
    store.close()


def test_review_scopes_depth_to_the_change(tmp_path: Path):
    repo = prepare_review_repo(tmp_path)
    review = run_review(repo, base="HEAD~1", head="HEAD")
    assert review["depth_note"]
    assert "Depth:" in review["headline"]
    rules = {f["rule"] for f in review["findings"] if not f.get("waived")}
    assert "leaked_seam" in rules or "tests_bypass_interface" in rules
    md = render_markdown(review)
    assert "### Depth" in md
    assert review["deepening"]
    assert review["deepening"][0]["top"] is True
