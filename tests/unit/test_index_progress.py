from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loadpath.progress import begin_progress, overall_percent, progress_callback, progress_key, read_progress
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
    assert body["percent"] == 100


def test_overall_percent_never_goes_backwards_across_phases():
    floor = 0
    percents = []
    events = [
        {"phase": "scan", "done": 0, "total": 0},
        {"phase": "scan", "done": 50, "total": 100},
        {"phase": "scan", "done": 100, "total": 100},
        {"phase": "extract", "done": 0, "total": 80},
        {"phase": "extract", "done": 40, "total": 80},
        {"phase": "extract", "done": 80, "total": 80},
        {"phase": "boot", "done": 0, "total": 1},
        {"phase": "stitch", "done": 0, "total": 1},
        {"phase": "done", "done": 5, "total": 100},
    ]
    for event in events:
        floor = overall_percent(event, floor=floor)
        percents.append(floor)
    assert percents == sorted(percents)
    assert percents[0] == 0
    assert percents[2] == percents[3] == 20
    assert percents[-1] == 100
    naive_extract_start = 0
    assert percents[3] > naive_extract_start


def test_recorded_index_percent_is_monotonic(tmp_path):
    repo = prepare_review_repo(tmp_path)
    begin_progress(repo)
    percents: list[int] = []

    inner = progress_callback(repo)

    def _cb(event):
        inner(event)
        percents.append(int(read_progress(repo)["percent"]))

    store = index_repo(repo, incremental=False, workers=1, progress=_cb)
    store.close()
    assert percents
    assert percents == sorted(percents)
    assert percents[-1] == 100
    assert percents[0] < 50
    leftover = read_progress(repo)
    begin_progress(repo)
    reset = read_progress(repo)
    assert leftover["percent"] == 100
    assert reset["percent"] == 0
    assert reset["phase"] == "scan"
    assert progress_key(repo) == reset["repo_path"]


def test_default_workers_stays_sequential_on_small_trees(monkeypatch):
    from loadpath.index import default_workers

    monkeypatch.delenv("LOADPATH_INDEX_JOBS", raising=False)
    assert default_workers(42) == 1
    monkeypatch.setenv("LOADPATH_INDEX_JOBS", "3")
    assert default_workers(42) == 3
