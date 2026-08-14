from __future__ import annotations

from typer.testing import CliRunner

from loadpath.cli import app
from tests.conftest import copy_fixture, git_commit_all, git_init_with_main

runner = CliRunner()


def test_cli_index_and_review(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    ser = repo / "backend/billing/serializers.py"
    ser.write_text(ser.read_text() + "\n# touch\n")
    git_commit_all(repo, "touch serializer")
    result = runner.invoke(app, ["index", str(repo)])
    assert result.exit_code == 0, result.output
    assert "nodes" in result.output
    result = runner.invoke(app, ["review", str(repo), "--base", "HEAD~1", "--head", "HEAD"])
    assert result.exit_code == 0, result.output
    assert "Loadpath" in result.output
