from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loadpath.index import index_repo
from loadpath.server.app import create_app
from tests.conftest import FIXTURE_ROOT as FIXTURE, prepare_review_repo


def test_index_emits_granular_progress(tmp_path: Path):
    events: list[dict] = []
    store = index_repo(
        FIXTURE,
        db_path=tmp_path / "g.sqlite3",
        incremental=False,
        workers=1,
        progress=events.append,
    )
    phases = [e["phase"] for e in events]
    assert phases[0] == "scan"
    assert "extract" in phases
    assert "stitch" in phases
    assert phases[-1] == "done"
    extracts = [e for e in events if e["phase"] == "extract" and e.get("current")]
    assert extracts, "expected per-file extract events"
    last_extract = [e for e in events if e["phase"] == "extract"][-1]
    assert last_extract["total"] >= last_extract["done"] > 0
    assert any("/" in (e.get("current") or "") for e in extracts)
    assert store.get_meta("index_workers") == "1"
    assert int(store.get_meta("index_elapsed_ms") or "0") >= 0
    store.close()


def test_parallel_extract_matches_sequential_graph(tmp_path: Path):
    one = index_repo(FIXTURE, db_path=tmp_path / "one.sqlite3", incremental=False, workers=1)
    two = index_repo(FIXTURE, db_path=tmp_path / "two.sqlite3", incremental=False, workers=2)
    assert two.get_meta("index_workers") == "2"
    assert {n["id"] for n in one.nodes()} == {n["id"] for n in two.nodes()}
    assert {e["id"] for e in one.edges()} == {e["id"] for e in two.edges()}
    one.close()
    two.close()


def test_incremental_skip_emits_skipped_progress(tmp_path: Path):
    db = tmp_path / "g.sqlite3"
    first = index_repo(FIXTURE, db_path=db, incremental=False, workers=1)
    first.close()
    events: list[dict] = []
    store = index_repo(FIXTURE, db_path=db, incremental=True, workers=1, progress=events.append)
    assert store.get_meta("reindex_skipped") == "1"
    assert store.get_meta("files_extracted") == "0"
    assert events[-1]["phase"] == "skipped"
    store.close()


def test_extract_error_becomes_residual(tmp_path: Path, monkeypatch):
    from loadpath import index as index_mod

    def boom(rel, source, config):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(index_mod, "extract_django_file", boom)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "backend").mkdir()
    (root / "backend" / "views.py").write_text("def hello():\n    return 1\n")
    store = index_repo(root, db_path=tmp_path / "g.sqlite3", incremental=False, workers=1)
    residuals = store.get_meta("residuals") or ""
    assert "Failed to extract" in residuals
    assert "extractor exploded" in residuals
    store.close()


def test_api_index_progress_idle_then_done(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    client = TestClient(create_app())
    idle = client.get("/api/index/progress", params={"repo_path": str(repo)})
    assert idle.status_code == 200
    assert idle.json()["phase"] == "idle"
    indexed = client.post("/api/index", json={"repo_path": str(repo), "incremental": False, "jobs": 1})
    assert indexed.status_code == 200, indexed.text
    done = client.get("/api/index/progress", params={"repo_path": str(repo)})
    assert done.status_code == 200
    body = done.json()
    assert body["phase"] == "done"
    assert body["message"]
    assert "elapsed_ms" in body
