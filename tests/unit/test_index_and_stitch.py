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


def test_contexts_assigned(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    invoice = next(n for n in store.nodes([NodeType.MODEL]) if n["name"] == "Invoice")
    assert invoice["context"] == "billing"
    store.close()
