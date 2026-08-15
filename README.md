# Loadpath

Review as **load-path inspection** on a Django + React architecture graph. Not another hunk-comment bot.

A change is a force. Loadpath traces where that force travels until it hits a sink — HTTP response, UI, Celery/Dramatiq job, migration, permission — then scores whether you have enough evidence to merge.

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

## App

`loadpath serve --port 7345` opens a local desktop-style UI: icon rail, labeled toolbar, merge-box confidence, and an inspectable impact graph. The same process hosts MCP at `/mcp` (OAuth). Tokens stay on the machine in `~/.loadpath/settings.json`. AI is used **only** for residual uncertainty the graph cannot close. Two dozen themes (Obsidian, Nord, Neon Noir, Synthwave, Phosphor, Sakura, Citrus, Paper, high-contrast, …) live in Settings and `localStorage`. Last repo, git range, and SCM slug are remembered the same way. Copy the markdown brief, or post **one** PR comment (updated in place) from the Review tab. Keyboard: `1`–`5` switches tabs. Outside Settings and Pull requests, `⌘`/`Ctrl`+`Enter` runs a review.

### Review

Confidence brief, read-order, clusters, architecture findings on the impact path, residual list, and the subgraph for the git range. Review walks the **indexed** graph (incremental refresh by default).

![Review](docs/screenshots/review.png)

### Architecture

Index a repo first. The architecture tab is the full typed graph plus `loadpath.yml` contexts and rules — not a PR diff. Findings here are repo-wide; review then scopes them to the change.

![Architecture](docs/screenshots/architecture.png)

### Impact graph

Toggle **This review** (impact subgraph) vs **Indexed architecture** (the repo map). Dashed edges are inferred (URL/Zod overlap); solid edges are extracted or generated-client stitches.

![Impact graph](docs/screenshots/graph.png)

### Pull requests

GitHub and Bitbucket via API tokens from Settings. Pick a PR and jump to a branch-range review.

![Pull requests](docs/screenshots/pull-requests.png)

### Settings

GitHub / Bitbucket tokens; AI providers (Anthropic, OpenAI, Grok/xAI, DeepSeek, Cursor-compatible, Ollama). Residual analysis only — Loadpath does not comment every hunk.

![Settings](docs/screenshots/settings.png)

## Install

Python 3.12+ and Node 22+ (UI).

```bash
pip install -e ".[dev]"
python -m playwright install chromium   # optional, for UI screenshot tests
cd ui && npm install && npm run build && cd ..
loadpath --help
```

## Desktop app (Windows, macOS, Linux)

Electron wraps the same local app: it starts the Loadpath backend and opens it in a native window. Tokens still live in `~/.loadpath/settings.json`.

**From source**

```bash
pip install -e .
cd ui && npm install && npm run build && cd ..
cd desktop && npm install && npm start
```

Requires Python 3.12+ on `PATH` (`python` on Windows, `python3` elsewhere), or set `LOADPATH_PYTHON`.

**Installers**

GitHub → Actions → **Desktop builds** → **Run workflow**. That manual job builds:

| OS | Artifact |
| --- | --- |
| Linux | AppImage and `.deb` |
| Windows | NSIS `.exe` |
| macOS | `.dmg` and `.zip` (unsigned) |

macOS Gatekeeper will block the unsigned app until you open it from Finder with right-click → Open. The workflow smokes `/api/health` on the bundled Python sidecar before packaging.

## CLI

```bash
# Detect Django/React roots and draft loadpath.yml (never overwrites an existing file)
loadpath init /path/to/repo

# Index a monorepo (SQLite graph at .loadpath/graph.sqlite3; unchanged hashes skip extract)
loadpath index /path/to/repo

# Inspect bounded contexts, rules, and type counts from that index
loadpath architecture /path/to/repo

# Review a git range against the index (three-dot / merge-base by default)
loadpath review /path/to/repo --base HEAD~1 --head HEAD
loadpath review /path/to/repo --base origin/main --head HEAD --no-reindex

# Cross-platform app (API + visual graph + PR list + MCP /mcp with OAuth)
loadpath serve --port 7345

# Local stdio MCP for Cursor / Claude Desktop (no OAuth)
loadpath mcp
```

**Flow:** `index` builds the architecture graph → `architecture` shows contexts and rule hits on the whole repo → `review` walks that same graph for a git range. The app mirrors this: Index registers a workspace, Architecture inspects it, Review traces a change through it.

## MCP (Cursor, Claude, ChatGPT, Gemini)

`loadpath serve` exposes Streamable HTTP MCP at `/mcp`, protected with OAuth 2.1 (PKCE, dynamic client registration, Client ID Metadata Documents). Cloud hosts need HTTPS; set `--public-url` to the public origin when tunneling. `--oauth-pin` adds a PIN on the consent page.

```bash
loadpath serve --host 0.0.0.0 --port 7345 --public-url https://your-tunnel.example --oauth-pin 123456
```

MCP URL: `https://your-tunnel.example/mcp` (or `http://127.0.0.1:7345/mcp` on the same machine).

**Cursor (stdio, local)** — `~/.cursor/mcp.json` or project `.cursor/mcp.json`:

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

**Cursor / Claude / ChatGPT / Gemini (HTTP + OAuth)** — add that MCP URL in the host’s connectors. The first connect opens a consent page on the Loadpath machine. Tokens stay in `~/.loadpath/oauth.json`.

Tools: `list_workspaces`, `init_repo`, `index_repo`, `architecture`, `review`, `detect_repo`, `list_pull_requests`, `post_review_comment`. `review` returns the load-path brief (confidence, sinks, reviewers) — not hunk comments.

Put `loadpath.yml` at the repo root (see [`loadpath.yml.example`](loadpath.yml.example) and [`fixtures/demo_monorepo/loadpath.yml`](fixtures/demo_monorepo/loadpath.yml)). The tool is opinionated about *your* architecture, not a generic module graph.

## Django support

AST is the default extractor. It is a **framework overlay**, not an import graph.

| Surface | What Loadpath extracts |
| --- | --- |
| Models | Fields, FK / M2M / O2O, `on_delete`, string refs (`ForeignKey("accounts.User")`) as residuals |
| Serializers | `Meta.fields` / `exclude`, declared fields, `serializes` edges, queryset-in-serializer flag |
| Views | DRF ViewSets / APIViews, `serializer_class`, `get_serializer_class` (residual), `permission_classes`, `get_queryset`, `filterset_class`, `authentication_classes`, `pagination_class` |
| Function views | `@api_view`, `@login_required`, `@csrf_exempt`, … |
| Django Ninja | `@router.get/post/…` routes and views |
| URLs | `path` / `re_path`, DRF `router.register`, `include()` mount composition (`/api` + `invoices/<id>/` → `/api/invoices/{id}`) |
| Signals | `@receiver`, `signal.connect()` residual, `AppConfig.ready()` residual |
| Management commands | `BaseCommand` + `handle()`, including `.delay(` / `.send(` enqueue edges |
| Migrations | `CreateModel` / `AddField` / `RemoveField` / `DeleteModel` / `RunPython` as `destructive_migration` |
| Tests | `test_*` in `tests.py` / `tests/` as `tested_by` |

### Celery

- `@shared_task`, `@app.task`, `@periodic_task`
- `celery.Task` subclasses (`run(self, invoice_id)`)
- Enqueue: `.delay(`, `.apply_async(`
- Signatures / canvas: `.s(`, `.si(`, `chain` / `group` / `chord` (canvas is a residual; inner signatures are `enqueues` edges)
- `current_app.send_task("billing.tasks.send_invoice_email")` — residual + inferred enqueue
- `transaction.on_commit(lambda: task.apply_async(...))` — residual, nested enqueue walked
- `CELERY_BEAT_SCHEDULE` / `beat_schedule` in settings

### Dramatiq

- `@dramatiq.actor`
- `dramatiq.GenericActor` subclasses (`perform(self, invoice_id)`)
- Enqueue: `.send(`, `.send_with_options(` (heuristic: dramatiq import or `actors` / `tasks` module)

Call-site placeholders (`rebuild_ledger.send` in a view) do **not** overwrite the actor definition’s file. The graph keeps `actors.py` / `tasks.py` as the node home.

### Idempotency rule

`celery_tasks_must_be_idempotent_on_model_pk` (alias `async_tasks_must_be_idempotent_on_model_pk`) warns when a Celery **or** Dramatiq task takes a full object payload instead of `pk` / `*_id`. Message names the broker.

### Optional `django.setup()` overlay

AST is enough for review. If you need live `_meta` (db_table, resolved relations), set `boot_django: true` in `loadpath.yml`. Loadpath then imports Django, calls `django.setup()`, and merges model/field nodes. Failures become residuals; the AST graph still stands. Leave it `false` in CI unless the fixture is a bootable project.

## React + stitch

**React:** react-router tables, composition, TanStack Query `queryKey` + fetch/axios URL templates, Zod schemas, feature-folder imports, RTL `render(<Page/>)` as `tested_by`.

**Stitch (the moat):** OpenAPI from Spectacular/schema files first; generated clients (`generated/`, orval, openapi-typescript) as high-confidence `consumed_by_client`; fallback URL-template matching and serializer/Zod field overlap marked **inferred**.

## Architecture rules (`loadpath.yml`)

| Rule | Meaning |
| --- | --- |
| `views_cannot_import_other_context_models` | A billing view must not import `accounts.UserProfile` |
| `react_feature_may_only_call_own_or_shared_api` | Billing UI may not `fetch('/api/me')` |
| `serializers_are_the_only_published_contract` | Zod/form fields must not drift from the serializer |
| `no_queryset_in_serializer` | Serializers must not run querysets |
| `celery_tasks_must_be_idempotent_on_model_pk` | Celery and Dramatiq tasks take a model pk |
| `queryset_nplusone` | Loops over querysets that touch related objects need `select_related` / `prefetch_related` |
| `queryset_missing_index` | `.filter()` / `.order_by()` on a field that has no `db_index` / `unique` |
| `cascade_crosses_context` | `on_delete=CASCADE` must not blast into another bounded context |
| `migration_blast_radius` | `RemoveField` / `DeleteModel` still referenced by the typed graph |
| `leaked_seam` | A view queries a model past a query module that already exists in the same context |
| `tests_bypass_interface` | Tests hit serializer/view internals while the published route or page seam is untested |

Waivers live under `waivers:` in the same file. Reviewers are the `owners` of the bounded contexts in the impact subgraph.

Review also scores **depth** on the impact path — the same vocabulary as a deep-module design pass: **module**, **interface**, **seam**, **leverage**, **locality**. A module is deep when a lot of behaviour sits behind a small interface. The **deletion test** asks whether removing a module concentrates complexity or just moves it. The **interface is the test surface**. Architecture is the survey (deepening opportunities ranked Strong / Worth exploring / Speculative); review then scopes those candidates to the git range.

Impact walk skips permission/app/context hubs, does not climb `renders` into the App shell, and does not follow cross-context `relates_to` (an Invoice FK to UserProfile does not pull identity into a billing review).

Review also folds in a **churn & coupling** slice of git history (CodeScene-style hotspots, bus factor, temporal coupling, cyclomatic complexity on the changed functions) scoped to the same impact files — not a whole-repo hotspot map.

## How confidence is scored

Line coverage on changed files is the wrong metric. Loadpath scores the **impact subgraph**:

| Signal | High | Low |
| --- | --- | --- |
| Tests | Sinks in the radius are hit by tests that still reach the changed symbol | Serializer changed, tests only on the view happy path (past the published seam) |
| Contract | OpenAPI/client types track the serializer | React path/Zod field still old |
| Architecture | No new cross-context edges; published seams hold | `crosses_context` or a leaked queryset seam |
| Graph | Resolved edges | Many inferred/dynamic edges |

`high` / `medium` / `low` plus three reasons. Isolated leaf UI with green tests and no rule hits is labeled `loadpath:low-risk`.

## Tests

```bash
pytest
cd ui && npm test
node --test desktop/*.test.mjs
```

| Suite | What it covers |
| --- | --- |
| `tests/unit/` | Django/React extractors, architecture rules, depth/seam survey, stitch, SCM/AI providers |
| `tests/integration/test_review_vertical_slice.py` | Serializer field change reaches InvoicePage/Zod, not MePage; reviewers `billing-team` |
| `tests/e2e/test_cli_review.py` | `loadpath index` / `architecture` / `review` markdown, JSON, HTML |
| `tests/e2e/test_api_flow.py` | health, index, architecture, review-from-index, graph, settings, GitHub + Bitbucket PR list |
| `tests/e2e/test_mcp_oauth.py` | OAuth metadata/DCR/PKCE, consent, CIMD, MCP `review` stays on the billing load path |
| `tests/e2e/test_index_architecture_flow.py` | index snapshot, review without index, review walking an existing graph |
| `tests/e2e/test_brokers_and_django.py` | Celery + Dramatiq sinks, actor-only PR, non-idempotent Dramatiq warning, destructive migration, cross-context blocker, boot overlay, management commands, beat/canvas |
| `tests/e2e/test_ui_screenshots.py` | Playwright: Architecture, Review, Impact graph, Pull requests, Settings → `docs/screenshots/` |
| `desktop/*.test.mjs` | Electron sidecar command, health-wait, and external-URL allowlist |

CI installs Chromium and runs the full suite.

## Demo fixture

[`fixtures/demo_monorepo`](fixtures/demo_monorepo) is a billing/identity split: DRF ViewSet, FBV, Ninja ledger route, Celery tasks + beat + canvas, Dramatiq actor + GenericActor, management command, signal, FK string ref, React InvoicePage/Zod.

## What this is not

Not CodeRabbit (comments without a closed impact set). Not a CodeScene clone (we do not replace its hotspot maps; we only score churn/coupling on the load path). Not django-orm-lens (we do not boot an ER explorer; we reuse its N+1 / cascade / blast-radius heuristics inside the typed graph). Not a generic SCIP call graph. The product is review as load-path inspection.
