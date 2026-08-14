from __future__ import annotations

from pathlib import Path

from loadpath.config import load_config
from loadpath.index import index_repo
from loadpath.types import NodeType

from tests.conftest import FIXTURE_ROOT as FIXTURE


def test_index_stitches_django_route_to_react_client(tmp_path: Path):
    db = tmp_path / "graph.sqlite3"
    store = index_repo(FIXTURE, db_path=db, incremental=False)
    edges = store.edges()
    consumed = [e for e in edges if e["type"] == "consumed_by_client"]
    assert consumed, "expected URL stitch between Django routes and React fetch"
    inferred = [e for e in consumed if e["confidence"] < 0.9]
    assert inferred, "string-matched fetch must be marked inferred (lower confidence)"
    schema_edges = [e for e in edges if e["type"] == "matches_schema"]
    assert schema_edges, "serializer fields should overlap invoiceSchema"
    store.close()


def test_index_is_incremental(tmp_path: Path):
    db = tmp_path / "graph.sqlite3"
    store = index_repo(FIXTURE, db_path=db, incremental=False)
    first = store.counts()
    store.close()
    store = index_repo(FIXTURE, db_path=db, incremental=True)
    second = store.counts()
    store.close()
    assert first["nodes"] == second["nodes"]


def test_contexts_assigned(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    invoice = next(n for n in store.nodes([NodeType.MODEL]) if n["name"] == "Invoice")
    assert invoice["context"] == "billing"
    store.close()
