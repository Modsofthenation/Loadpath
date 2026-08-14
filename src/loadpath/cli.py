from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown

from loadpath import __version__
from loadpath.index import default_db_path, index_repo
from loadpath.review.engine import run_review
from loadpath.review.render import render_html, render_markdown

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Loadpath — Django+React PR load-path reviewer.")
console = Console()


@app.callback()
def _version(version: bool = typer.Option(False, "--version", help="Show version")) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()


@app.command()
def index(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    full: bool = typer.Option(False, "--full", help="Re-extract every file"),
) -> None:
    """Index a Django + React monorepo into a SQLite graph."""
    store = index_repo(repo, incremental=not full)
    counts = store.counts()
    console.print(f"Indexed {counts['nodes']} nodes / {counts['edges']} edges → {default_db_path(repo)}")
    store.close()


@app.command()
def review(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    base: str = typer.Option("origin/main", "--base", "-b"),
    head: Optional[str] = typer.Option(None, "--head"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown|json|html"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
) -> None:
    """Review a git range as clustered load paths + confidence brief."""
    payload = run_review(repo, base=base, head=head)
    if format == "json":
        import json

        text = json.dumps(payload, indent=2, default=str)
    elif format == "html":
        text = render_html(payload)
    else:
        text = render_markdown(payload)
        console.print(Markdown(text))
        if out is None:
            return
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"Wrote {out}")
    elif format != "markdown":
        console.print(text)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(7345, "--port"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Start the Loadpath app (API + UI)."""
    from loadpath.server.app import serve as run_server

    run_server(host=host, port=port, open_browser=open_browser)


if __name__ == "__main__":
    app()
