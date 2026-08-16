# Loadpath

[![CI](https://github.com/Modsofthenation/PR-Reviewer/actions/workflows/ci.yml/badge.svg)](https://github.com/Modsofthenation/PR-Reviewer/actions/workflows/ci.yml)

Local **load-path inspection** for Django + React pull requests. A change is a force: Loadpath traces where that force travels until it hits a sink (HTTP, UI, Celery/Dramatiq, migration, permission), then scores whether you have enough evidence to merge.

It is a CLI, a local desktop UI, a GitHub Action merge gate, and an MCP server you can point Cursor at. Not a SaaS. Not a hunk-comment bot.

```
Loadpath: MEDIUM — Invoice.total field change
Sinks: GET/POST /api/invoices/{id}; Celery send_invoice_email, apply_credit; Dramatiq rebuild_ledger; React InvoicePage + InvoiceForm
Tests: pytest hits serializer and view; no RTL test on InvoiceForm
Architecture: stays inside billing
Residual: total also formatted in a Signal update_ledger — no test
Suggested reviewers: billing-team
```

On the demo monorepo that path is:

`Invoice.total → InvoiceSerializer → InvoiceViewSet → /api/invoices/{id} → OpenAPI → fetch → useInvoice → InvoicePage → InvoiceForm / Zod`

plus the jobs the view enqueues (`send_invoice_email.delay`, `rebuild_ledger.send`).

## What it does

- Indexes a Django + React repo into a typed architecture graph (AST overlay, not an import graph).
- Reviews a git range against that graph: sinks, tests, contract drift, auth, suggested reviewers.
- Shows the same walk in a local UI (2D map, optional 3D when WebGL is available).
- Optionally upserts **one** PR comment (updated in place) and fails CI on architecture blockers.
- Speaks MCP so an editor can ask for the brief without dumping the full graph.

## What it does not do

- **Not a general reviewer bot.** It does not comment every hunk, suggest nits, or replace human review.
- **Not a SaaS.** Nothing is uploaded. Tokens stay in `~/.loadpath/` on the machine that runs Loadpath.
- **Not a linter, SAST scanner, or test runner.** It does not execute your app or your test suite.
- **Not a generic call graph.** Other stacks (Rails, JVM, …) are out of scope. FastAPI / GraphQL / HTMX are overlays inside a Django+React repo, not standalone products.
- **Not a runtime tracer.** Edges come from extractors (AST, OpenAPI, generated clients). Dashed edges are inferred.
- **Not CodeScene / django-orm-lens / SCIP.** Churn and N+1 heuristics are scored on the load path only.

MIT. See [LICENSE](LICENSE). Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Vulnerabilities: [SECURITY.md](SECURITY.md).

## Requirements

- Python **3.12+**
- Node **22+** (to build the UI; the served app is static files)
- Git
- A Django + React repo (or the bundled demo)

## Install

Clone and install from source (there is no PyPI package yet):

```bash
git clone https://github.com/Modsofthenation/PR-Reviewer.git
cd PR-Reviewer
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cd ui && npm install && npm run build && cd ..
loadpath --help
```

`python -m playwright install chromium` is optional (UI screenshot tests only).

## Quick start (demo)

The fixture at [`fixtures/demo_monorepo`](fixtures/demo_monorepo) is not a git repo. Copy it and make **two** commits so `HEAD~1`…`HEAD` is a real range:

```bash
cp -R fixtures/demo_monorepo /tmp/acme-billing
cd /tmp/acme-billing
git init -b main
git add -A && git commit -m "baseline"
python3 - <<'PY'
from pathlib import Path
p = Path("backend/billing/serializers.py")
p.write_text(p.read_text().replace(
    'fields = ["id", "customer_id", "total", "status"]',
    'fields = ["id", "customer_id", "total", "status"]\n        extra_kwargs = {"total": {"required": True}}',
))
PY
git add -A && git commit -m "tighten Invoice.total contract"

loadpath index /tmp/acme-billing
loadpath review /tmp/acme-billing --base HEAD~1 --head HEAD
loadpath serve --open
```

Point the UI at `/tmp/acme-billing` (or pick it in the repo explorer). Default range is `HEAD~1`…`HEAD`.

**Flow:** `index` builds the graph → `architecture` surveys the repo → `review` walks a git range. The app mirrors this: Index, Architecture, Review.

## Run

### CLI

```bash
loadpath init /path/to/repo                 # draft loadpath.yml (never overwrites)
loadpath index /path/to/repo                # SQLite graph at .loadpath/graph.sqlite3
loadpath architecture /path/to/repo
loadpath review /path/to/repo --base HEAD~1 --head HEAD
loadpath review /path/to/repo --base origin/main --head HEAD --no-reindex
loadpath review /path/to/repo --dirty       # include the working tree
loadpath review /path/to/repo --fail-on blocker   # never | blocker | low | medium
loadpath whatif /path/to/repo django.field:billing.Invoice.total
loadpath serve --port 7345                  # UI + API + MCP /mcp
loadpath mcp                                # stdio MCP for Cursor (no OAuth)
```

Put `loadpath.yml` at the repo root (see [`loadpath.yml.example`](loadpath.yml.example)).

### Local UI

`loadpath serve` binds **127.0.0.1:7345** and opens the app. Icon rail, merge-box confidence, inspectable graph. Copy markdown, save HTML, or post **one** PR comment from Review.

Keyboard: `1`–`5` tabs. `⌘`/`Ctrl`+`K` command palette. `j`/`k` read-order. `⌘`/`Ctrl`+`Enter` runs a review (outside Settings / Pull requests).

### GitHub Action merge gate

```yaml
permissions:
  contents: read
  pull-requests: write   # only needed when comment: true
jobs:
  loadpath:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: Modsofthenation/PR-Reviewer@main
        with:
          fail-on: blocker   # never | blocker | low | medium
          comment: true
```

Indexes the checkout, reviews `origin/$GITHUB_BASE_REF...HEAD`, optionally upserts the brief, fails on architecture blockers (or on low/medium confidence if you ask).

Outputs: `level`, `passed`, `title`, `contract_break` (`none` | `additive` | `breaking` | `drift`).

CLI equivalent: `loadpath review . --fail-on blocker --comment --provider github --pr $N --repo $SLUG`.

### MCP (Cursor, Claude, ChatGPT, Gemini)

**Local stdio** — `~/.cursor/mcp.json` or project `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "loadpath": {
      "command": "loadpath",
      "args": ["mcp"]
    }
  }
}
```

**HTTP + OAuth** — `loadpath serve` exposes Streamable HTTP MCP at `/mcp`. Cloud hosts need HTTPS. Set `--public-url` when tunneling, and `--oauth-pin` so random clients cannot approve themselves:

```bash
loadpath serve --host 0.0.0.0 --port 7345 --public-url https://your-tunnel.example --oauth-pin 123456
```

The UI remains on `http://127.0.0.1:7345`. The tunnel is for MCP only. First connect opens a consent page on this machine.

Tools: `list_workspaces`, `init_repo`, `index_repo`, `architecture`, `review`, `detect_repo`, `list_pull_requests`, `list_remote_repositories`, `post_review_comment`, `what_if`, `review_pull_request`, `load_path_marks`, `list_reviews`, `save_config`. `review` returns the brief — not hunk comments. `load_path_marks` feeds the Cursor/VS Code gutter in [`editors/vscode`](editors/vscode).

### Desktop app (Windows, macOS, Linux)

Electron wraps the same local server. Tokens still live in `~/.loadpath/settings.json`.

```bash
pip install -e .
cd ui && npm install && npm run build && cd ..
cd desktop && npm install && npm start
```

Requires Python 3.12+ on `PATH` (`python` on Windows, `python3` elsewhere), or `LOADPATH_PYTHON`.

Installers: GitHub → Actions → **Desktop builds** → **Run workflow** (Linux AppImage/`.deb`, Windows NSIS, macOS unsigned `.dmg`/`.zip`). Gatekeeper needs right-click → Open on macOS.

## Security

- Default bind is loopback. `/api/*` except `/api/health` rejects non-local `Origin`/`Host` (settings, filesystem browse, review, PR comments, AI).
- SCM OAuth, tokens, and indexes stay in `~/.loadpath/` (`0700` / `0600`).
- Do not set `LOADPATH_OAUTH_AUTO_APPROVE=1` outside tests.
- Report vulnerabilities privately: [SECURITY.md](SECURITY.md).

## The app

Until a repo is indexed and a range is walked, Review is an onboarding card.

![Empty review onboarding](docs/screenshots/review-empty.png)

![Review with brief and impact graph](docs/screenshots/review.png)

**Node inspector** — click a node: what it is, what feeds it, what it calls.

![Inspector on InvoiceSerializer](docs/screenshots/review-inspector.png)

**Architecture** — full typed graph plus `loadpath.yml` contexts. Findings here are repo-wide; review scopes them to the change.

![Architecture graph and findings](docs/screenshots/architecture.png)

**Impact graph** — **This review** vs **Indexed architecture**. Dashed edges are inferred; solid edges are extracted. 2D is the default. 3D uses the same layouts with bounded context on the depth axis when WebGL is available.

![Impact graph, this review](docs/screenshots/graph.png)

![Indexed architecture in the graph tab](docs/screenshots/graph-architecture.png)

**Pull requests** — GitHub, GitLab, Bitbucket via **Sign in** (OAuth) or a token. GitHub Enterprise and self-hosted GitLab take a host in Settings. **Review this PR** fetches refs into a local clone. Sign-in and repo listing are loopback-only.

![Pull requests list](docs/screenshots/pull-requests.png)

**Repo explorer** — pick a project root. Loadpath remembers recent workspaces.

![Repo explorer](docs/screenshots/explorer.png)

**Settings** — 24 themes; GitHub device flow (`repo read:user read:org`); GitLab / Bitbucket authorization-code (callback `http://127.0.0.1:7345/api/oauth/<gitlab|bitbucket>/callback`); AI providers (Anthropic, OpenAI, Grok/xAI, DeepSeek, Cursor-compatible, Ollama) for **residual uncertainty only**.

Set `LOADPATH_GITHUB_CLIENT_ID` (enable Device Flow on the OAuth App) or paste the client ID in Settings. GitLab/Bitbucket: `LOADPATH_*_CLIENT_ID` / `LOADPATH_*_CLIENT_SECRET`.

![Settings with theme grid](docs/screenshots/settings.png)

**MCP consent** — HTTP MCP does not silently grant access. Tokens in `~/.loadpath/oauth.json`.

![MCP consent](docs/screenshots/mcp-consent.png)

Watch the working tree to re-walk on save. Click a node → **What if this changes** to walk sinks with no git range. Isolate path to sinks filters the current map.

### Themes

Default is **Obsidian**. Nine of the twenty-four palettes:

<table>
<tr>
<td align="center"><strong>Obsidian</strong><br/><img src="docs/screenshots/theme-obsidian.png" alt="Obsidian theme" /></td>
<td align="center"><strong>Nord</strong><br/><img src="docs/screenshots/theme-nord.png" alt="Nord theme" /></td>
<td align="center"><strong>Neon noir</strong><br/><img src="docs/screenshots/theme-neon-noir.png" alt="Neon noir theme" /></td>
</tr>
<tr>
<td align="center"><strong>Synthwave</strong><br/><img src="docs/screenshots/theme-synthwave.png" alt="Synthwave theme" /></td>
<td align="center"><strong>Phosphor</strong><br/><img src="docs/screenshots/theme-phosphor.png" alt="Phosphor theme" /></td>
<td align="center"><strong>Paper</strong><br/><img src="docs/screenshots/theme-paper.png" alt="Paper theme" /></td>
</tr>
<tr>
<td align="center"><strong>Sakura</strong><br/><img src="docs/screenshots/theme-sakura.png" alt="Sakura theme" /></td>
<td align="center"><strong>Citrus</strong><br/><img src="docs/screenshots/theme-citrus.png" alt="Citrus theme" /></td>
<td align="center"><strong>High contrast</strong><br/><img src="docs/screenshots/theme-high-contrast.png" alt="High contrast theme" /></td>
</tr>
</table>

Also shipping: Solarized Dark/Light, Forest, Rose Pine, Midnight Amber, Volcano, Lavender, Aurora, Biolume, Carbon, Seafoam, Peach Fuzz, Cotton Candy, Clear Sky, Coral Reef.

## Django support

AST is the default extractor. It is a **framework overlay**, not an import graph.

| Surface | What Loadpath extracts |
| --- | --- |
| Models | Fields, FK / M2M / O2O, `on_delete`, string refs as residuals |
| Serializers | `Meta.fields` / `exclude`, nested serializers, `SerializerMethodField`, `serializes` edges |
| Views | DRF ViewSets / APIViews, `serializer_class`, `permission_classes`, `get_queryset`, … |
| Function views | `@api_view`, `@login_required`, `@csrf_exempt`, … |
| Django Ninja | `@router.get/post/…`, `Schema` / `ModelSchema` |
| FastAPI (same repo) | `@app.get/post/…` and Pydantic `BaseModel` — only when the file imports FastAPI |
| GraphQL | Strawberry / Graphene; client `gql` documents stitch by operation name |
| Channels | `WebsocketConsumer` and websocket routes |
| Templates + HTMX | `{% url %}`, `hx-get/post/…` stitched to Django routes |
| Cache / flags / on_commit | `cache.get/set`, waffle-style flags, `transaction.on_commit` as sinks |
| URLs | `path` / `re_path`, DRF routers, `include()` composition |
| Signals | `@receiver`, `signal.connect()` residual |
| Management commands | `BaseCommand` + enqueue edges |
| Migrations | `CreateModel` / `AddField` / `RemoveField` / `DeleteModel` / `RunPython` |
| Tests | `test_*` as `tested_by` |
| Celery | `@shared_task` / `@app.task`, `.delay(` / `.apply_async(`, canvas residual, beat schedule |
| Dramatiq | `@dramatiq.actor`, `.send(` / `.send_with_options(` |

Call-site placeholders do **not** overwrite the actor definition’s file.

`celery_tasks_must_be_idempotent_on_model_pk` (alias `async_tasks_must_be_idempotent_on_model_pk`) warns when a task takes a full object payload instead of `pk` / `*_id`.

Optional `boot_django: true` in `loadpath.yml` imports Django for live `_meta`. Leave it `false` in CI unless the fixture is bootable. Failures become residuals; the AST graph still stands.

## React + stitch

**React:** react-router, Next.js App/Pages Router, Server Actions, TanStack Query, RTK Query, openapi-fetch, tRPC, ts-rest, Zod, GraphQL codegen, RTL / Playwright / Cypress as `tested_by`.

**Stitch:** OpenAPI from Spectacular/schema files; generated clients as high-confidence `consumed_by_client`; HTMX and e2e visits match routes; URL-template / Zod overlap marked **inferred**.

Frontend roots prefer `frontend/src`, `frontend`, `web/src`, `client/src`, `ui/src` — not a Python package `src/`. `app/` is a Django root candidate.

## Architecture rules (`loadpath.yml`)

| Rule | Meaning |
| --- | --- |
| `views_cannot_import_other_context_models` | A billing view must not import `accounts.UserProfile` |
| `react_feature_may_only_call_own_or_shared_api` | Billing UI may not `fetch('/api/me')` |
| `serializers_are_the_only_published_contract` | Zod/form fields must not drift from the serializer |
| `no_queryset_in_serializer` | Serializers must not run querysets |
| `celery_tasks_must_be_idempotent_on_model_pk` | Celery and Dramatiq tasks take a model pk |
| `queryset_nplusone` | Loops over querysets that touch related objects need `select_related` / `prefetch_related` |
| `queryset_missing_index` | `.filter()` / `.order_by()` on a field with no `db_index` / `unique` |
| `cascade_crosses_context` | `on_delete=CASCADE` must not blast into another bounded context |
| `migration_blast_radius` | `RemoveField` / `DeleteModel` still referenced by the typed graph |
| `leaked_seam` | A view queries a model past a query module that already exists in the same context |
| `tests_bypass_interface` | Tests hit internals while the published route or page seam is untested |

Waivers live under `waivers:`. Reviewers are the `owners` of bounded contexts on the impact subgraph.

Review also scores **depth** on the impact path (module, interface, seam, leverage, locality) and a **churn & coupling** slice of git history scoped to impact files.

Impact walk skips permission/app/context hubs, does not climb `renders` into the App shell, and does not follow cross-context `relates_to`.

## How confidence is scored

Line coverage on changed files is the wrong metric. Loadpath scores the **impact subgraph**:

| Signal | High | Low |
| --- | --- | --- |
| Tests | Sinks in the radius are hit by tests that still reach the changed symbol | Serializer changed, tests only on the view happy path |
| Contract | OpenAPI/client types track the serializer | React path/Zod field still old |
| Architecture | No new cross-context edges; published seams hold | `crosses_context` or a leaked queryset seam |
| Graph | Resolved edges | Many inferred/dynamic edges |

`high` / `medium` / `low` plus three reasons. Isolated leaf UI with green tests and no rule hits is `loadpath:low-risk`. Auth is first-class (permission_classes, get_queryset, ungated websockets). Contract diffs are `additive`, `breaking`, or `drift`.

## Tests

```bash
pytest
cd ui && npm test
node --test desktop/*.test.mjs
```

| Suite | What it covers |
| --- | --- |
| `tests/unit/` | Extractors, rules, stitch, SCM/AI providers, loopback API |
| `tests/integration/test_review_vertical_slice.py` | Serializer field change reaches InvoicePage/Zod, not MePage |
| `tests/e2e/test_cli_review.py` | `index` / `architecture` / `review` markdown, JSON, HTML |
| `tests/e2e/test_api_flow.py` | health, index, architecture, review, graph, settings, PRs |
| `tests/e2e/test_mcp_oauth.py` | OAuth metadata/DCR/PKCE, consent, MCP `review` |
| `tests/e2e/test_ui_screenshots.py` | Playwright screenshots (`LOADPATH_SCREENSHOT_DIR=docs/screenshots` to regenerate) |
| `desktop/*.test.mjs` | Electron sidecar, health-wait, external-URL allowlist |

See [CONTRIBUTING.md](CONTRIBUTING.md) for screenshot regeneration, Vite, and the editor extension.

## Demo fixture

[`fixtures/demo_monorepo`](fixtures/demo_monorepo) is a billing/identity split: DRF ViewSet, FBV, Ninja, FastAPI sidecar, Strawberry + Graphene, Channels, HTMX, Celery + Dramatiq, React InvoicePage/Zod.

## License

MIT. See [LICENSE](LICENSE).
