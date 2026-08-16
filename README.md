# Loadpath

[![CI](https://github.com/Modsofthenation/PR-Reviewer/actions/workflows/ci.yml/badge.svg)](https://github.com/Modsofthenation/PR-Reviewer/actions/workflows/ci.yml)

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

![Review screen with impact graph](docs/screenshots/review.png)

It is a local CLI, a desktop UI, and an MCP server you can point Cursor at. Not a SaaS. Tokens stay on the machine in `~/.loadpath/settings.json`.

## App

`loadpath serve --port 7345` opens a local desktop-style UI: icon rail, labeled toolbar, merge-box confidence, and an inspectable impact graph. The same process hosts MCP at `/mcp` (OAuth). AI is used **only** for residual uncertainty the graph cannot close. Twenty-four themes live in Settings and `localStorage`. Last repo, git range, SCM slug, and the last review id are remembered the same way. Copy the markdown brief, save HTML, or post **one** PR comment (updated in place) from the Review tab. Keyboard: `1`–`5` switches tabs. `⌘`/`Ctrl`+`K` opens the command palette. `j`/`k` walks read-order. Outside Settings and Pull requests, `⌘`/`Ctrl`+`Enter` runs a review. Click a finding, sink, or inspector neighbor to select it on the graph; Open in editor uses Cursor / VS Code. Watch the working tree to re-walk on save. Architecture edits `loadpath.yml` in place.

### Empty review

Until a repo is indexed and a range is walked, Review is an onboarding card — not a blank graph.

![Empty review onboarding](docs/screenshots/review-empty.png)

### Review

Confidence brief, read-order, clusters, architecture findings on the impact path, residual list, and the subgraph for the git range. Review walks the **indexed** graph (incremental refresh by default).

![Review with brief and impact graph](docs/screenshots/review.png)

### Node inspector

Click a node. The inspector answers *what is this, what feeds it, what does it call, what would break* — not a dump of the indexer row.

![Inspector on InvoiceSerializer](docs/screenshots/review-inspector.png)

### Architecture

Index a repo first. The architecture tab is the full typed graph plus `loadpath.yml` contexts and rules — not a PR diff. Findings here are repo-wide; review then scopes them to the change.

![Architecture graph and findings](docs/screenshots/architecture.png)

### Impact graph

Toggle **This review** (impact subgraph) vs **Indexed architecture** (the repo map). Dashed edges are inferred (URL/Zod overlap); solid edges are extracted or generated-client stitches. 2D is the default. 3D uses the same layout algorithms, puts bounded context on the depth axis, and is available when WebGL is.

![Impact graph, this review](docs/screenshots/graph.png)

![Indexed architecture in the graph tab](docs/screenshots/graph-architecture.png)

### Pull requests

GitHub, GitLab, and Bitbucket via **Sign in** (OAuth) or a token in Settings. GitHub Enterprise and self-hosted GitLab take a host in Settings. After connecting, **My repos** lists every repository the account can access. Pick one and **Review this PR** — Loadpath fetches the PR refs into a local clone if this machine does not already have one. Review still runs against that clone. The screenshot uses a fixture PR so the tab is not empty.

![Pull requests list](docs/screenshots/pull-requests.png)

### Repo explorer

Browse the filesystem, pick a project root. Loadpath remembers recent workspaces.

![Repo explorer](docs/screenshots/explorer.png)

### Settings

Appearance (all 24 themes), GitHub / GitLab / Bitbucket **OAuth sign-in** (or a classic PAT / app password), GitHub Enterprise host, and AI providers (Anthropic, OpenAI, Grok/xAI, DeepSeek, Cursor-compatible, Ollama). Residual analysis only — Loadpath does not comment every hunk.

GitHub uses device flow (`repo read:user read:org`). Create an OAuth App, enable Device Flow, then set `LOADPATH_GITHUB_CLIENT_ID` or paste the client ID in Settings. For GitHub Enterprise, set the host (API is `{host}/api/v3`).

GitLab uses authorization code. Create an OAuth application whose callback is `http://127.0.0.1:7345/api/oauth/gitlab/callback`, then set `LOADPATH_GITLAB_CLIENT_ID` / `LOADPATH_GITLAB_CLIENT_SECRET` (or paste them in Settings). Self-managed GitLab takes a host.

Bitbucket uses authorization code. Create an OAuth consumer whose callback is `http://127.0.0.1:7345/api/oauth/bitbucket/callback`, then set `LOADPATH_BITBUCKET_CLIENT_ID` / `LOADPATH_BITBUCKET_CLIENT_SECRET` or paste the key and secret in Settings. Access tokens are refreshed automatically. SCM sign-in and repo listing are local-only (loopback) so a tunneled MCP server does not expose private repos.

![Settings with theme grid](docs/screenshots/settings.png)

### MCP consent

When Cursor (or another client) connects over HTTP MCP, Loadpath does not silently grant access. You get a local consent page: client name, Loadpath issuer URL, optional PIN. Approve or deny. Tokens stay in `~/.loadpath/oauth.json`.

![MCP consent](docs/screenshots/mcp-consent.png)

## Themes

Default is **Obsidian**. Settings lists every palette; the shots below are the same Review screen under nine of them.

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

Also shipping: Solarized Dark/Light, Forest, Rose Pine, Midnight Amber, Volcano, Lavender, Aurora, Biolume, Carbon, Seafoam, Peach Fuzz, Cotton Candy, Clear Sky, Coral Reef. High contrast is a first-class theme, not an afterthought.

## Install

Python 3.12+ and Node 22+ (UI).

```bash
pip install -e ".[dev]"
python -m playwright install chromium   # optional, for UI screenshot tests
cd ui && npm install && npm run build && cd ..
loadpath --help
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests, screenshot regeneration, and the Electron app.

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
loadpath review /path/to/repo --dirty          # include the working tree
loadpath review /path/to/repo --fail-on blocker  # CI merge gate (never|blocker|low|medium)

# Walk sinks from one indexed node — no git range
loadpath whatif /path/to/repo django.field:billing.Invoice.total

# Cross-platform app (API + visual graph + PR list + MCP /mcp with OAuth)
loadpath serve --port 7345

# Local stdio MCP for Cursor / Claude Desktop (no OAuth)
loadpath mcp
```

**Flow:** `index` builds the architecture graph → `architecture` shows contexts and rule hits on the whole repo → `review` walks that same graph for a git range. The app mirrors this: Index registers a workspace, Architecture inspects it, Review traces a change through it.

The bundled demo checkout is [`fixtures/demo_monorepo`](fixtures/demo_monorepo) (Django billing API + React invoice UI). Copy it and make **two** commits so `HEAD~1` is a real range — the fixture itself is not a git repo, and a single commit leaves the default range empty.

```bash
cp -R fixtures/demo_monorepo /tmp/acme-billing
cd /tmp/acme-billing
git init -b main
git add -A && git commit -m "baseline"
# Same contract tweak the screenshots use:
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
loadpath serve --open
```

Then point the UI at `/tmp/acme-billing`, or pick it from the repo explorer. `loadpath serve` always boots the app; it does not take a repo path. Default range is `HEAD~1`…`HEAD`. Toggle **Include uncommitted** to walk the working tree. Click a node → **What if this changes** to walk sinks as if that node changed — no git range, and **Back to git range** restores the last real review. Isolate path to sinks only filters the current map. The read-order list is a guided tour (prev/next highlights the file on the graph).

## GitHub Action merge gate

Use this repo as a composite action. It indexes the checkout, reviews `origin/$GITHUB_BASE_REF...HEAD`, optionally upserts the single Loadpath brief, and fails the job on architecture blockers (or on low/medium confidence if you ask).

```yaml
- uses: Modsofthenation/PR-Reviewer@main
  with:
    fail-on: blocker   # never | blocker | low | medium
    comment: true
```

Outputs: `level`, `passed`, `title`, `contract_break` (`none` | `additive` | `breaking` | `drift`).

CLI equivalent: `loadpath review . --fail-on blocker --comment --provider github --pr $N --repo $SLUG`. `--github-output` (or `GITHUB_OUTPUT`) writes the same fields for Actions.

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

**Cursor / Claude / ChatGPT / Gemini (HTTP + OAuth)** — add that MCP URL in the host’s connectors. The first connect opens a consent page on the Loadpath machine.

Tools: `list_workspaces`, `init_repo`, `index_repo`, `architecture`, `review`, `detect_repo`, `list_pull_requests`, `list_remote_repositories`, `post_review_comment`, `what_if`, `review_pull_request`, `load_path_marks`, `list_reviews`, `save_config`. `review` returns the load-path brief (confidence, sinks, reviewers, contract-break, auth, suggested tests, trend, checklist) — not hunk comments. `load_path_marks` is the gutter feed for the Cursor/VS Code extension in [`editors/vscode`](editors/vscode). `review_pull_request` fetches GitHub / GitLab / Bitbucket refs into a local clone first.

Put `loadpath.yml` at the repo root (see [`loadpath.yml.example`](loadpath.yml.example) and [`fixtures/demo_monorepo/loadpath.yml`](fixtures/demo_monorepo/loadpath.yml)). The tool is opinionated about *your* architecture, not a generic module graph.

## Django support

AST is the default extractor. It is a **framework overlay**, not an import graph.

| Surface | What Loadpath extracts |
| --- | --- |
| Models | Fields, FK / M2M / O2O, `on_delete`, string refs (`ForeignKey("accounts.User")`) as residuals |
| Serializers | `Meta.fields` / `exclude`, declared fields, nested serializers, `SerializerMethodField`, parsed `to_representation` keys, `serializes` edges, queryset-in-serializer flag |
| Views | DRF ViewSets / APIViews, `serializer_class`, `get_serializer_class` (resolved returns; residual only when unresolved), `permission_classes`, `get_queryset`, `filterset_class`, `authentication_classes`, `pagination_class` |
| Function views | `@api_view`, `@login_required`, `@csrf_exempt`, … |
| Django Ninja | `@router.get/post/…` routes and views, `Schema` / `ModelSchema` fields (including nested), response annotation → schema |
| FastAPI (same repo) | `@app.get/post/…` and Pydantic `BaseModel` (nested annotations) — only when the file imports FastAPI, so Ninja is not stolen |
| GraphQL | Strawberry `@strawberry.type` / `@strawberry.field` and Graphene `ObjectType` / `Mutation`; client `gql` documents stitch by operation/selection name |
| Channels | `WebsocketConsumer` subclasses and `path(..., Consumer.as_asgi())` websocket routes |
| Templates + HTMX | `.html` files, `{% url %}` / include / extends, `hx-get/post/…` stitched to Django routes |
| Cache / flags / on_commit | `cache.get/set/delete`, waffle-style `flag_is_active`, `transaction.on_commit` as sinks |
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
- `transaction.on_commit(lambda: task.apply_async(...))` — `SIDE_EFFECT` sink + residual; nested enqueue walked
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

**React:** react-router tables, Next.js App Router (`app/**/page.tsx`) and Pages Router, Server Actions, composition, TanStack Query `queryKey` + fetch/axios URL templates, RTK Query `createApi` endpoints, openapi-fetch `client.GET/POST`, tRPC procedures, ts-rest `path:` contracts, Zod schemas, GraphQL codegen types, feature-folder imports, RTL `render(<Page/>)` and Playwright/Cypress `page.goto` / `cy.visit` as `tested_by`.

**Stitch (the moat):** OpenAPI from Spectacular/schema files first; generated clients (`generated/`, orval, openapi-typescript) and typed clients (RTK Query, openapi-fetch, ts-rest, tRPC) as high-confidence `consumed_by_client`; FastAPI routes, Ninja/Pydantic schemas, and GraphQL operations (including codegen types) stitch the same way; HTMX URLs and Playwright/Cypress visits match Django/React routes; fallback URL-template matching and serializer/Zod field overlap marked **inferred**.

Frontend roots prefer `frontend/src`, `frontend`, `web/src`, `client/src`, `ui/src`, `src-ui/src` — not a Python package `src/` and not `docs` / docs-site trees. `app/` is a Django root candidate.

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

`high` / `medium` / `low` plus three reasons. Isolated leaf UI with green tests and no rule hits is labeled `loadpath:low-risk`. The same PR/range stores a **confidence trend** so a second review on that range can say whether confidence rose, dropped, or the sink count moved.

Auth is a first-class load path: permission_classes, get_queryset object scope, and websocket routes without a gate. Untested seams get **suggested tests** (pytest / RTL / GraphQL / Channels / HTMX). Contract diffs are labeled `additive`, `breaking`, or `drift`.

## Tests

```bash
pytest
cd ui && npm test
node --test desktop/*.test.mjs
```

| Suite | What it covers |
| --- | --- |
| `tests/unit/` | Django/React extractors, architecture rules, depth/seam survey, stitch, overlays (GraphQL/Channels/HTMX/FastAPI), SCM/AI providers |
| `tests/integration/test_review_vertical_slice.py` | Serializer field change reaches InvoicePage/Zod, not MePage; reviewers `billing-team` |
| `tests/e2e/test_cli_review.py` | `loadpath index` / `architecture` / `review` markdown, JSON, HTML |
| `tests/e2e/test_api_flow.py` | health, index, architecture, review-from-index, graph, settings, GitHub + Bitbucket PR list |
| `tests/e2e/test_mcp_oauth.py` | OAuth metadata/DCR/PKCE, consent, CIMD, MCP `review` stays on the billing load path |
| `tests/e2e/test_index_architecture_flow.py` | index snapshot, review without index, review walking an existing graph |
| `tests/e2e/test_brokers_and_django.py` | Celery + Dramatiq sinks, actor-only PR, non-idempotent Dramatiq warning, destructive migration, cross-context blocker, boot overlay, management commands, beat/canvas |
| `tests/e2e/test_ui_screenshots.py` | Playwright screenshots (tmpdir by default; set `LOADPATH_SCREENSHOT_DIR=docs/screenshots` to regenerate README assets) |
| `desktop/*.test.mjs` | Electron sidecar command, health-wait, and external-URL allowlist |

To regenerate the README screenshots:

```bash
LOADPATH_SCREENSHOT_DIR=docs/screenshots python -m pytest tests/e2e/test_ui_screenshots.py
```

## Demo fixture

[`fixtures/demo_monorepo`](fixtures/demo_monorepo) is a billing/identity split: DRF ViewSet, FBV, Ninja ledger route, FastAPI sidecar gateway, Strawberry + Graphene schema, Channels consumer, Django template + HTMX board, cache keys / feature flags / `on_commit`, Celery tasks + beat + canvas, Dramatiq actor + GenericActor, management command, signal, FK string ref, React InvoicePage/Zod + a `gql` document.

## What this is not

Not CodeRabbit (comments without a closed impact set). Not a CodeScene clone (we do not replace its hotspot maps; we only score churn/coupling on the load path). Not django-orm-lens (we do not boot an ER explorer; we reuse its N+1 / cascade / blast-radius heuristics inside the typed graph). Not a generic SCIP call graph. The product is review as load-path inspection.

## License

MIT. See [LICENSE](LICENSE). Vulnerability reports: [SECURITY.md](SECURITY.md).
