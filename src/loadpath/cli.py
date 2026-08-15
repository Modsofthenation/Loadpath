from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown

from loadpath import __version__
from loadpath.architecture.snapshot import architecture_report
from loadpath.detect import write_draft_config
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
def init(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing loadpath.yml"),
) -> None:
    """Detect Django/React roots and draft loadpath.yml (does not overwrite by default)."""
    layout = write_draft_config(repo, overwrite=overwrite)
    console.print(layout["message"])
    console.print(f"Django root: {layout['django_root']}")
    console.print(f"React root: {layout['react_root']}")
    names = ", ".join((layout.get("contexts") or {}).keys()) or "none"
    console.print(f"Contexts: {names}")


@app.command()
def index(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    full: bool = typer.Option(False, "--full", help="Re-extract every file"),
) -> None:
    """Index a Django + React monorepo into a SQLite graph."""
    from loadpath.architecture.snapshot import summarize_index
    from loadpath.config import load_config
    from loadpath.settings import register_workspace

    store = index_repo(repo, incremental=not full, draft_config=True)
    register_workspace(repo)
    summary = summarize_index(store, load_config(repo))
    counts = summary["counts"]
    extracted = summary.get("files_extracted") or 0
    skipped = summary.get("reindex_skipped")
    if skipped:
        console.print(f"Index already current ({counts['nodes']} nodes / {counts['edges']} edges) → {default_db_path(repo)}")
    else:
        console.print(
            f"Indexed {counts['nodes']} nodes / {counts['edges']} edges"
            f" (extracted {extracted} files) → {default_db_path(repo)}"
        )
    contexts = ", ".join(summary["contexts"]) or "none"
    console.print(f"Contexts: {contexts}")
    boot = summary.get("django_boot") or "off"
    if boot != "off":
        console.print(f"Django boot: {boot}")
        if summary.get("django_boot_detail"):
            console.print(str(summary["django_boot_detail"]))
    if summary.get("stale"):
        console.print("Index still looks stale after extract.")
    findings = [f for f in summary["findings"] if not f.get("waived")]
    if findings:
        console.print(f"Architecture findings: {len(findings)}")
    store.close()


@app.command()
def review(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    base: str = typer.Option("HEAD~1", "--base", "-b"),
    head: Optional[str] = typer.Option("HEAD", "--head"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown|json|html"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
    reindex: bool = typer.Option(True, "--reindex/--no-reindex", help="Refresh the index before walking the diff"),
    full: bool = typer.Option(False, "--full", help="Full reindex instead of incremental"),
    three_dot: bool = typer.Option(True, "--three-dot/--two-dot", help="PR-shaped range (merge-base...head)"),
    dirty: bool = typer.Option(False, "--dirty", help="Include uncommitted files in the review"),
    fail_on: str = typer.Option(
        "never",
        "--fail-on",
        help="CI gate: never | blocker | low | medium",
    ),
    comment: bool = typer.Option(False, "--comment", help="Upsert the Loadpath brief on --pr"),
    provider: Optional[str] = typer.Option(None, "--provider", help="github | gitlab | bitbucket"),
    pr: Optional[int] = typer.Option(None, "--pr", help="Pull/merge request number to comment on or fetch"),
    scm_repo: Optional[str] = typer.Option(None, "--repo", help="owner/name for --comment / --pr fetch"),
    fetch_pr: bool = typer.Option(False, "--fetch-pr", help="Fetch --pr refs into this clone before reviewing"),
    github_output: Optional[Path] = typer.Option(None, "--github-output", help="Append gate fields for GitHub Actions"),
) -> None:
    """Review a git range as clustered load paths + confidence brief."""
    import os

    from loadpath.review.gate import FAIL_ON_CHOICES, gate_result, write_github_output
    from loadpath.review.render import render_html, render_markdown

    repo_path = repo
    if fetch_pr and pr and provider and scm_repo:
        from loadpath.providers.pr_fetch import prepare_pull_request

        prepared = prepare_pull_request(provider, scm_repo, pr, repo_path=str(repo))
        repo_path = Path(prepared["repo_path"])
        base = prepared["base"]
        head = prepared["head"]
        console.print(f"Fetched {provider} #{pr} → {head} (base {base})")

    payload = run_review(
        repo_path,
        base=base,
        head=head,
        reindex=reindex,
        incremental=not full,
        three_dot=three_dot,
        dirty=dirty,
    )
    if format == "json":
        import json

        text = json.dumps(payload, indent=2, default=str)
    elif format == "html":
        text = render_html(payload)
    else:
        text = render_markdown(payload)
        console.print(Markdown(text))
        if out is None and not comment and fail_on == "never" and github_output is None and not os.environ.get("GITHUB_OUTPUT"):
            gate = gate_result(payload, fail_on)
            raise typer.Exit(code=gate["exit_code"])
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"Wrote {out}")
    elif format != "markdown":
        console.print(text)

    if comment:
        from loadpath.providers.scm import provider_for
        from loadpath.settings import AppSettings

        settings = AppSettings.load()
        name = provider or "github"
        number = pr
        slug = scm_repo
        if not number or not slug:
            console.print("--comment needs --pr and --repo owner/name")
            raise typer.Exit(code=1)
        token = ""
        username = ""
        host = ""
        if name == "github":
            token = settings.github_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("LOADPATH_GITHUB_TOKEN") or ""
            host = settings.github_host
        elif name == "gitlab":
            token = settings.gitlab_token or os.environ.get("GITLAB_TOKEN") or os.environ.get("LOADPATH_GITLAB_TOKEN") or ""
            host = settings.gitlab_host
        else:
            token = settings.bitbucket_token
            username = settings.bitbucket_username
        if not token:
            console.print(f"No {name} token in settings or environment")
            raise typer.Exit(code=1)
        posted = provider_for(name, token, username=username, host=host).upsert_pull_request_comment(
            slug, number, render_markdown(payload)
        )
        action = "Updated" if posted.get("updated") else "Posted"
        console.print(f"{action} Loadpath comment on {slug}#{number}")

    output_path = github_output or (Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None)
    gate = gate_result(payload, fail_on if fail_on in FAIL_ON_CHOICES else "never")
    if output_path:
        write_github_output(str(output_path), gate, payload)
    if fail_on != "never" or gate["exit_code"]:
        if not gate["passed"]:
            console.print(gate["annotation"])
        raise typer.Exit(code=gate["exit_code"])


@app.command("whatif")
def whatif_cmd(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    node: str = typer.Argument(..., help="Node id from the index (e.g. django.field:billing.Invoice.total)"),
) -> None:
    """Walk sinks from one indexed node — no git range required."""
    from loadpath.review.whatif import simulate_node

    try:
        payload = simulate_node(repo, node)
    except (FileNotFoundError, KeyError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"{payload['title']}")
    console.print(f"Confidence: {payload['confidence']['level']}")
    sinks = payload.get("sinks") or []
    if sinks:
        console.print("Sinks: " + ", ".join(s.get("name") or "" for s in sinks[:8]))
    for sketch in (payload.get("suggested_tests") or [])[:3]:
        console.print(f"Test: {sketch['title']}")


@app.command()
def architecture(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
) -> None:
    """Show the indexed architecture (contexts, rules, type counts). Index first if empty."""
    report = architecture_report(repo)
    if not report["indexed"]:
        console.print("No index yet. Run `loadpath index` first.")
        raise typer.Exit(code=1)
    counts = report["counts"]
    console.print(f"{counts['nodes']} nodes / {counts['edges']} edges")
    boot = report.get("django_boot") or "off"
    if boot != "off":
        console.print(f"Django boot: {boot}")
    if report.get("stale"):
        console.print("Index is stale — re-run `loadpath index`.")
    console.print("Contexts: " + (", ".join(report["contexts"]) or "none"))
    for name, ctx in (report.get("contexts") or {}).items():
        owners = ", ".join(ctx.get("owners") or []) or "—"
        console.print(f"  {name}  apps={','.join(ctx.get('django_apps') or [])}  owners={owners}")
    active = [f for f in report.get("findings") or [] if not f.get("waived")]
    console.print(f"Rules: {len(report.get('rules') or [])} enabled · {len(active)} findings")
    for finding in active[:12]:
        console.print(f"  [{finding['severity']}] {finding['rule']}: {finding['message']}")
    deepening = [c for c in (report.get("deepening") or [])]
    if deepening:
        top = next((c for c in deepening if c.get("top")), deepening[0])
        console.print(f"Depth: {len(deepening)} deepening opportunities · top {top['strength']} — {top['title']}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(7345, "--port"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
    public_url: Optional[str] = typer.Option(
        None,
        "--public-url",
        help="Public base URL for MCP OAuth (https://… when tunneling). Default is http://<host>:<port>.",
    ),
    oauth_pin: Optional[str] = typer.Option(
        None,
        "--oauth-pin",
        help="Optional PIN on the OAuth consent screen (recommended when --public-url is set).",
    ),
) -> None:
    """Start the Loadpath app (API + UI + MCP /mcp with OAuth)."""
    from loadpath.server.app import serve as run_server

    run_server(host=host, port=port, open_browser=open_browser, public_url=public_url, oauth_pin=oauth_pin)


@app.command("mcp")
def mcp_stdio() -> None:
    """Run Loadpath as a local stdio MCP server (Cursor / Claude Desktop). No OAuth."""
    import asyncio

    from loadpath.mcp.server import run_stdio

    asyncio.run(run_stdio())


if __name__ == "__main__":
    app()
