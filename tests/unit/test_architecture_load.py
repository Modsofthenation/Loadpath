from __future__ import annotations

import os
import time
from pathlib import Path

from loadpath.architecture.snapshot import architecture_graph, architecture_report, workspace_index_card
from loadpath.index import default_db_path, file_hash, index_drift, index_repo
from loadpath.config import load_config
from tests.conftest import FIXTURE_ROOT, prepare_review_repo


def test_architecture_graph_skips_field_leaves(tmp_path: Path):
    store = index_repo(FIXTURE_ROOT, db_path=tmp_path / "g.sqlite3", incremental=False)
    nodes, edges = architecture_graph(store)
    types = {n["type"] for n in nodes}
    assert "django.serializer_field" not in types
    assert "django.field" not in types
    assert "django.test" not in types
    assert "InvoicePage" in {n["name"] for n in nodes}
    assert "InvoiceViewSet" in {n["name"] for n in nodes}
    ids = {n["id"] for n in nodes}
    assert all(e["src"] in ids and e["dst"] in ids for e in edges)
    assert len(nodes) < len(store.nodes())
    store.close()


def test_architecture_summary_skips_source_file_hashes(tmp_path, monkeypatch):
    repo = prepare_review_repo(tmp_path)
    index_repo(repo, db_path=default_db_path(repo), incremental=False)
    calls: list[str] = []
    real = file_hash

    def wrapped(path: Path) -> str:
        calls.append(Path(path).name)
        return real(path)

    monkeypatch.setattr("loadpath.index.file_hash", wrapped)
    report = architecture_report(repo, include_graph=False)
    assert report["indexed"] is True
    assert report["graph_pending"] is True
    assert report["nodes"] == []
    assert "InvoiceViewSet" not in {n.get("name") for n in report["nodes"]}
    assert calls
    assert all(name.endswith((".yml", ".yaml", ".json")) or name == "loadpath.yml" for name in calls)


def test_workspace_card_does_not_build_the_graph(tmp_path):
    repo = prepare_review_repo(tmp_path)
    index_repo(repo, db_path=default_db_path(repo), incremental=False)
    card = workspace_index_card(repo)
    assert card["indexed"] is True
    assert card["counts"]["nodes"] > 20
    assert "billing" in card["contexts"]
    assert "nodes" not in card


def test_mtime_drift_sees_a_touched_file(tmp_path):
    repo = prepare_review_repo(tmp_path)
    db = default_db_path(repo)
    store = index_repo(repo, db_path=db, incremental=False)
    config = load_config(repo)
    fresh = index_drift(store, repo, config, hash_contents=False)
    assert fresh["stale"] is False
    target = repo / "backend/billing/serializers.py"
    later = time.time() + 5
    os.utime(target, (later, later))
    drifted = index_drift(store, repo, config, hash_contents=False)
    assert drifted["stale"] is True
    assert any(p.endswith("serializers.py") for p in drifted["changed"])
    store.close()


def test_store_type_filter_and_edge_cache(tmp_path: Path):
    store = index_repo(FIXTURE_ROOT, db_path=tmp_path / "g.sqlite3", incremental=False)
    first = store.edges()
    second = store.edges()
    assert first is second
    views = store.nodes(["django.view"])
    assert views
    assert all(n["type"] == "django.view" for n in views)
    store.close()
