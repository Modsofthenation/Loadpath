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
    generated = [
        e
        for e in consumed
        if (e.get("extra") or {}).get("generated_client") and e["confidence"] >= 0.9
    ]
    assert generated, "generated OpenAPI client should stitch at high confidence"
    assert any((e.get("extra") or {}).get("superseded_by_generated") for e in inferred)
    schema_edges = [e for e in edges if e["type"] == "matches_schema"]
    assert schema_edges, "serializer fields should overlap invoiceSchema"
    store.close()


def test_index_drafts_yml_in_repo_even_if_parent_has_one(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "app"
    child.mkdir(parents=True)
    (parent / "loadpath.yml").write_text("contexts: {}\n", encoding="utf-8")
    (child / "backend").mkdir()
    (child / "backend" / "manage.py").write_text("print(1)\n")
    store = index_repo(child, db_path=child / "g.sqlite3", incremental=False, draft_config=True)
    store.close()
    assert (child / "loadpath.yml").is_file()
    assert (parent / "loadpath.yml").read_text() == "contexts: {}\n"
    db = tmp_path / "graph.sqlite3"
    store = index_repo(FIXTURE, db_path=db, incremental=False)
    store.close()
    store = index_repo(FIXTURE, db_path=db, incremental=True)
    assert store.get_meta("reindex_skipped") == "1"
    assert store.get_meta("files_extracted") == "0"
    assert store.get_meta("django_boot") == "off"
    store.close()


def test_incremental_index_drops_deleted_files(tmp_path: Path):
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    db = tmp_path / "g.sqlite3"
    store = index_repo(root, db_path=db, incremental=False)
    assert any(n["name"] == "InvoicePage" for n in store.nodes())
    store.close()
    (root / "frontend/src/features/billing/InvoicePage.tsx").unlink()
    store = index_repo(root, db_path=db, incremental=True)
    assert not any(n["name"] == "InvoicePage" for n in store.nodes())
    store.close()


def test_incremental_reindex_keeps_enqueue_edges(tmp_path: Path):
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    db = tmp_path / "g.sqlite3"
    store = index_repo(root, db_path=db, incremental=False)
    before = [e for e in store.edges() if e["type"] == "enqueues"]
    assert before
    store.close()
    tasks = root / "backend/billing/tasks.py"
    tasks.write_text(tasks.read_text() + "\n# touch\n")
    store = index_repo(root, db_path=db, incremental=True)
    after = [e for e in store.edges() if e["type"] == "enqueues"]
    assert len(after) >= len(before)
    store.close()


def test_index_revision_change_reextracts_unchanged_files(tmp_path: Path, monkeypatch):
    import shutil

    from loadpath import index as index_mod

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    db = tmp_path / "g.sqlite3"
    store = index_repo(root, db_path=db, incremental=False)
    assert store.get_meta("index_revision") == index_mod.INDEX_REVISION
    store.close()
    monkeypatch.setattr(index_mod, "INDEX_REVISION", index_mod.INDEX_REVISION + "-next")
    store = index_repo(root, db_path=db, incremental=True)
    assert store.get_meta("reindex_skipped") != "1"
    assert int(store.get_meta("files_extracted") or "0") > 0
    assert store.get_meta("index_revision") == index_mod.INDEX_REVISION
    store.close()


def test_contexts_assigned(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    invoice = next(n for n in store.nodes([NodeType.MODEL]) if n["name"] == "Invoice")
    assert invoice["context"] == "billing"
    store.close()


def test_empty_include_prefix_does_not_pollute_child_paths(tmp_path: Path):
    from loadpath.graph.store import GraphStore
    from loadpath.stitch.openapi import apply_url_includes, django_route_to_template
    from loadpath.types import Node, NodeType, node_id

    store = GraphStore(tmp_path / "g.sqlite3")
    store.upsert_node(
        Node(
            id=node_id(NodeType.ROUTE, "zproject:include:tornado"),
            type=NodeType.ROUTE,
            name="include:zproject.tornado_urls",
            qualified_name="zproject:include:zproject.tornado_urls",
            extra={"app": "zproject", "route": "", "include": "zproject.urls"},
        )
    )
    child_id = node_id(NodeType.ROUTE, "zproject:coverage/{id}")
    store.upsert_node(
        Node(
            id=child_id,
            type=NodeType.ROUTE,
            name="coverage/{id}",
            qualified_name="zproject:coverage/{id}",
            extra={"app": "zproject", "route": "coverage/{id}"},
        )
    )
    store.conn.commit()
    apply_url_includes(store)
    child = store.get_node(child_id)
    assert child is not None
    assert "include:" not in child["name"]
    assert child["name"] == "/coverage/{id}"
    assert (child.get("extra") or {}).get("full_path") == "/coverage/{id}"
    store.close()
    assert django_route_to_template("include:zproject.tornado_urls") == "/"
    assert django_route_to_template("^base") == "/base"
    assert django_route_to_template("^$") == "/"


def test_regex_include_join_strips_anchors(tmp_path: Path):
    from loadpath.graph.store import GraphStore
    from loadpath.stitch.openapi import apply_url_includes
    from loadpath.types import Node, NodeType, node_id

    store = GraphStore(tmp_path / "g.sqlite3")
    store.upsert_node(
        Node(
            id=node_id(NodeType.ROUTE, "geonode:base"),
            type=NodeType.ROUTE,
            name="^base",
            qualified_name="geonode:^base",
            extra={"app": "geonode", "route": "^base/", "include": "geonode.base.urls"},
        )
    )
    child_id = node_id(NodeType.ROUTE, "base:index")
    store.upsert_node(
        Node(
            id=child_id,
            type=NodeType.ROUTE,
            name="^$",
            qualified_name="base:^$",
            extra={"app": "base", "route": "^$"},
        )
    )
    store.conn.commit()
    apply_url_includes(store)
    child = store.get_node(child_id)
    assert child is not None
    assert child["name"] == "/base"
    store.close()
