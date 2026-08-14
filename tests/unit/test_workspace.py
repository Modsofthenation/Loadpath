from __future__ import annotations

from pathlib import Path

from loadpath.review.diff import git_diff
from loadpath.workspace import git_dirty_paths, git_merge_base, resolve_review_range
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
