from __future__ import annotations

from pathlib import Path

from loadpath.review.diff import git_diff
from loadpath.workspace import git_dirty_paths, git_merge_base, list_directory, list_git_refs, resolve_review_range
from tests.conftest import git_commit_all, git_init_with_main


def test_merge_base_and_three_dot_range(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    git_init_with_main(repo)
    (repo / "b.txt").write_text("two\n")
    git_commit_all(repo, "second")
    mb = git_merge_base(repo, "HEAD~1", "HEAD")
    assert mb
    info = resolve_review_range(repo, "HEAD~1", "HEAD", three_dot=True)
    assert info["merge_base"] == mb
    diff = git_diff(repo, "HEAD~1", "HEAD", three_dot=True)
    assert any(f.path == "b.txt" for f in diff.files)


def test_dirty_paths_include_uncommitted(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    git_init_with_main(repo)
    (repo / "dirty.txt").write_text("nope\n")
    assert "dirty.txt" in git_dirty_paths(repo)


def test_list_directory_marks_git_repos(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    nested = tmp_path / "workspace" / "acme"
    nested.mkdir(parents=True)
    (nested / "README.md").write_text("hi\n")
    git_init_with_main(nested)
    (tmp_path / "workspace" / "notes").mkdir()
    (tmp_path / "workspace" / "notes" / "todo.txt").write_text("x\n")
    listing = list_directory(str(tmp_path / "workspace"))
    names = {item["name"]: item for item in listing["entries"]}
    assert names["acme"]["is_git"] is True
    assert names["notes"]["is_git"] is False
    assert listing["is_git"] is False
    jumped = list_directory(str(nested / "missing-child"))
    assert jumped["path"] == str(nested.resolve())
    assert jumped["is_git"] is True


def test_list_git_refs_includes_commits_and_branches(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.txt").write_text("one\n")
    git_init_with_main(repo)
    (repo / "b.txt").write_text("two\n")
    git_commit_all(repo, "second commit")
    refs = list_git_refs(repo, commit_limit=50)
    assert refs["git"] is True
    assert refs["presets"] == ["HEAD", "HEAD~1"]
    subjects = [c["subject"] for c in refs["commits"]]
    assert "second commit" in subjects
    assert "baseline" in subjects
    assert len(refs["commits"]) == 2
    names = {b["name"] for b in refs["branches"]}
    assert "main" in names
    assert any(b["current"] for b in refs["branches"])
    empty = list_git_refs(tmp_path / "not-a-repo")
    assert empty["git"] is False
    assert empty["commits"] == []
    nested = repo / "backend"
    nested.mkdir()
    from_subdir = list_git_refs(nested)
    assert from_subdir["git"] is True
    assert from_subdir["commits"]
