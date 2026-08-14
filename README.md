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

`loadpath serve --port 7345` opens a local desktop-style UI. Tokens stay on the machine in `~/.loadpath/settings.json`. AI is used **only** for residual uncertainty the graph cannot close.

### Review

Confidence brief, read-order, clusters, architecture findings, residual list, and the impact subgraph for the git range.

![Review](docs/screenshots/review.png)

### Impact graph

Full-canvas layered graph: Django models and serializers on the left, views/tasks in the middle, OpenAPI stitch, React hooks and pages on the right. Dashed edges are inferred (URL/Zod overlap); solid edges are extracted or generated-client stitches.

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

## CLI

```bash
# Index a monorepo (SQLite graph at .loadpath/graph.sqlite3, incremental on file hashes)
loadpath index /path/to/repo

# Review a git range → markdown (also --format html|json)
loadpath review /path/to/repo --base origin/main --head HEAD

# Cross-platform app (API + visual graph + PR list)
loadpath serve --port 7345
```

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

Waivers live under `waivers:` in the same file. Reviewers are the `owners` of the bounded contexts in the impact subgraph.

Impact walk skips permission/app/context hubs, does not climb `renders` into the App shell, and does not follow cross-context `relates_to` (an Invoice FK to UserProfile does not pull identity into a billing review).

## How confidence is scored

Line coverage on changed files is the wrong metric. Loadpath scores the **impact subgraph**:

| Signal | High | Low |
| --- | --- | --- |
| Tests | Sinks in the radius are hit by tests that still reach the changed symbol | Serializer changed, tests only on the view happy path |
| Contract | OpenAPI/client types track the serializer | React path/Zod field still old |
| Architecture | No new cross-context edges | `crosses_context` with no waiver |
| Graph | Resolved edges | Many inferred/dynamic edges |

`high` / `medium` / `low` plus three reasons. Isolated leaf UI with green tests and no rule hits is labeled `loadpath:low-risk`.

## Tests

```bash
pytest
cd ui && npm test
```

| Suite | What it covers |
| --- | --- |
| `tests/unit/` | Django/React extractors, architecture rules, stitch, SCM/AI providers |
| `tests/integration/test_review_vertical_slice.py` | Serializer field change reaches InvoicePage/Zod, not MePage; reviewers `billing-team` |
| `tests/e2e/test_cli_review.py` | `loadpath index` / `review` markdown, JSON, HTML |
| `tests/e2e/test_api_flow.py` | health, index, review, graph, settings, GitHub + Bitbucket PR list |
| `tests/e2e/test_brokers_and_django.py` | Celery + Dramatiq sinks, actor-only PR, non-idempotent Dramatiq warning, destructive migration, cross-context blocker, boot overlay, management commands, beat/canvas |
| `tests/e2e/test_ui_screenshots.py` | Playwright: Review, Impact graph, Pull requests, Settings → `docs/screenshots/` |

CI installs Chromium and runs the full suite.

## Demo fixture

[`fixtures/demo_monorepo`](fixtures/demo_monorepo) is a billing/identity split: DRF ViewSet, FBV, Ninja ledger route, Celery tasks + beat + canvas, Dramatiq actor + GenericActor, management command, signal, FK string ref, React InvoicePage/Zod.

## What this is not

Not CodeRabbit (comments without a closed impact set). Not CodeScene (historical coupling). Not django-orm-lens (models only). Not a generic SCIP call graph. The product is review as load-path inspection.
