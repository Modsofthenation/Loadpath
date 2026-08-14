from __future__ import annotations

from typer.testing import CliRunner

from loadpath.cli import app
from tests.conftest import prepare_review_repo

runner = CliRunner()


def test_cli_index_review_json_and_html(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    result = runner.invoke(app, ["index", str(repo)])
    assert result.exit_code == 0, result.output
    assert "nodes" in result.output
    assert "billing" in result.output

    arch = runner.invoke(app, ["architecture", str(repo)])
    assert arch.exit_code == 0, arch.output
    assert "billing" in arch.output
    assert "identity" in arch.output

    md = runner.invoke(
        app,
        ["review", str(repo), "--base", "HEAD~1", "--head", "HEAD", "--no-reindex"],
    )
    assert md.exit_code == 0, md.output
    assert "Loadpath" in md.output
    assert "MEDIUM" in md.output or "LOW" in md.output or "HIGH" in md.output

    json_out = tmp_path / "review.json"
    js = runner.invoke(
        app,
        ["review", str(repo), "--base", "HEAD~1", "--head", "HEAD", "--format", "json", "--out", str(json_out)],
    )
    assert js.exit_code == 0, js.output
    payload = json_out.read_text()
    assert "InvoiceSerializer" in payload
    assert "rebuild_ledger" in payload
    assert "send_invoice_email" in payload
    assert "Dramatiq" in payload or "dramatiq" in payload
    assert "Celery" in payload or "celery" in payload

    html_out = tmp_path / "review.html"
    html = runner.invoke(
        app,
        ["review", str(repo), "--base", "HEAD~1", "--head", "HEAD", "--format", "html", "--out", str(html_out)],
    )
    assert html.exit_code == 0, html.output
    text = html_out.read_text()
    assert "vis-network" in text
    assert "Loadpath" in text


def test_cli_init_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = prepare_review_repo(tmp_path)
    original = (repo / "loadpath.yml").read_text()
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output
    assert "unchanged" in result.output.lower() or "already" in result.output.lower()
    assert (repo / "loadpath.yml").read_text() == original


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Loadpath" in result.output
    assert "architecture" in result.output
    assert "init" in result.output


def test_cli_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "port" in result.output.lower()
