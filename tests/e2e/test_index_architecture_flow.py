from __future__ import annotations

from loadpath.architecture.snapshot import architecture_report
from loadpath.index import default_db_path, index_repo
from tests.conftest import FIXTURE_ROOT, copy_fixture, git_init_with_main, prepare_review_repo


def test_index_summary_includes_contexts_and_timestamp(tmp_path):
    store = index_repo(FIXTURE_ROOT, db_path=tmp_path / "g.sqlite3", incremental=False)
    assert store.get_meta("indexed_at")
    assert store.type_counts()["django.task"] >= 2
    store.close()
    report = architecture_report(FIXTURE_ROOT, db_path=tmp_path / "g.sqlite3")
    assert report["indexed"] is True
    assert "billing" in report["contexts"]
    assert "identity" in report["contexts"]
    assert report["counts"]["nodes"] > 20
    names = {n["name"] for n in report["nodes"]}
    assert "InvoiceViewSet" in names
    assert "InvoicePage" in names
    assert any(n["type"] == "arch.context" for n in report["nodes"])
    assert report.get("deepening") is not None


def test_review_without_index_raises(tmp_path):
    from loadpath.review.engine import run_review

    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    try:
        run_review(repo, base="HEAD", head="HEAD", reindex=False)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "index" in str(exc).lower()


def test_review_walks_existing_index(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from loadpath.review.engine import run_review

    repo = prepare_review_repo(tmp_path)
    store = index_repo(repo, incremental=False)
    store.close()
    review = run_review(repo, base="HEAD~1", head="HEAD", reindex=False)
    assert review["index"]["reindexed"] is False
    assert review["index"]["counts"]["nodes"] > 20
    names = {n["name"] for n in review["nodes"]}
    assert "InvoicePage" in names
    assert default_db_path(repo).is_file()
