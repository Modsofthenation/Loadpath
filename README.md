# Loadpath

Review as **load-path inspection** on a Django + React architecture graph. Not another hunk-comment bot.

A change is a force. Loadpath traces where that force travels until it hits a sink (HTTP response, UI, job, migration, permission) — then scores whether you have enough evidence to merge.

## What you get on every PR

1. **Clustered diff** — one cluster is one load path, not one file
2. **Impact graph** — real Django/React node types, typed weighted edges
3. **Confidence brief** — sink tests, contract coverage, architecture rules, residual unknowns

```
Loadpath: MEDIUM — Invoice.total field change
Sinks: GET/POST /api/invoices, Celery send_invoice_email, React InvoicePage + InvoiceForm
Tests: pytest hits serializer and view; no RTL test on InvoiceForm
Architecture: stays inside billing
Residual: total also formatted in a Signal update_ledger — no test
Suggested reviewers: billing-team
```

## Install

Python 3.12+ and Node 22+ (UI).

```bash
pip install -e ".[dev]"
cd ui && npm install && npm run build && cd ..
loadpath --help
```

## CLI

```bash
# Index a monorepo (SQLite graph, incremental on file hashes)
loadpath index /path/to/repo

# Review a git range → markdown brief (also --format html|json)
loadpath review /path/to/repo --base origin/main --head HEAD

# Cross-platform app (API + visual graph + PR list)
loadpath serve --port 7345
```

Put `loadpath.yml` at the repo root (see `loadpath.yml.example` and `fixtures/demo_monorepo/loadpath.yml`). The tool is opinionated about *your* architecture, not a generic module graph.

## App

`loadpath serve` opens a local desktop-style UI:

- **Review** — confidence, read-order, clusters, architecture blockers, residual list
- **Impact graph** — layered load path (Django → OpenAPI stitch → React)
- **Pull requests** — GitHub and Bitbucket via API tokens in Settings
- **Settings** — GitHub/Bitbucket tokens; AI providers (Anthropic, OpenAI, Grok/xAI, DeepSeek, Cursor-compatible, Ollama)

Tokens live in `~/.loadpath/settings.json` on the machine running the app. AI is used **only** for residual uncertainty the graph cannot close (`getattr`, raw SQL, `get_serializer_class`, `AppConfig.ready()` signals, string model refs, inferred URL stitches). It does not comment every hunk.

## How confidence is scored

Line coverage on changed files is the wrong metric. Loadpath scores the **impact subgraph**:

| Signal | High | Low |
| --- | --- | --- |
| Tests | Sinks in the radius are hit by tests that still reach the changed symbol | Serializer changed, tests only on the view happy path |
| Contract | OpenAPI/client types track the serializer | React path/Zod field still old |
| Architecture | No new cross-context edges | `crosses_context` with no waiver |
| Graph | Resolved edges | Many inferred/dynamic edges |

`high` / `medium` / `low` plus three reasons. Isolated leaf UI with green tests and no rule hits is labeled `loadpath:low-risk`.

## Extractors

**Django (framework overlay, not just imports):** `urls.py` / DRF router, `serializer_class` / `get_serializer_class`, `Meta.fields`, permissions, model `_meta`-shaped AST (FK/`on_delete`), `@receiver`, `@shared_task` / `.delay(`, `apps.get_model("app.Model")`, migration ops, pytest node ids as `tested_by`.

**React:** react-router tables, composition, TanStack Query `queryKey` + fetch/axios URL templates, Zod schemas, feature-folder imports, RTL `render(<Page/>)` as `tested_by`.

**Stitch (the moat):** OpenAPI from Spectacular/schema files first; generated clients (`generated/`, orval, openapi-typescript) as high-confidence `consumed_by_client`; fallback URL-template matching and serializer/Zod field overlap marked **inferred**.

## Tests

```bash
pytest
cd ui && npm test
```

The vertical slice in `tests/integration/test_review_vertical_slice.py` indexes `fixtures/demo_monorepo`, changes one serializer field, and asserts the path reaches the React form with a medium/low confidence reason.

## What this is not

Not CodeRabbit (comments without a closed impact set). Not CodeScene (historical coupling). Not django-orm-lens (models only). Not a generic SCIP call graph. The product is review as load-path inspection.
