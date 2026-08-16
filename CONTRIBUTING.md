# Contributing

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security reports go to [SECURITY.md](SECURITY.md), not the public issue tracker.

## Setup

Python 3.12+ and Node 22+.

```bash
git clone https://github.com/Modsofthenation/PR-Reviewer.git
cd PR-Reviewer
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m playwright install chromium   # optional; needed for UI screenshot tests
cd ui && npm install && npm run build && cd ..
loadpath --help
```

Do not commit `~/.loadpath/`, `.env`, tokens, or private clones. Settings already live outside the repo.

## Tests

```bash
pytest
cd ui && npm test
node --test desktop/*.test.mjs
```

CI installs Chromium and runs the full suite. The demo fixture is `fixtures/demo_monorepo`.

## Screenshots

README images live in `docs/screenshots/` and are produced by Playwright:

```bash
LOADPATH_SCREENSHOT_DIR=docs/screenshots python -m pytest tests/e2e/test_ui_screenshots.py
```

Do not commit a 3D screenshot from headless Chromium unless `[data-testid=graph-3d-canvas]` is present. This environment often falls back to “WebGL is unavailable.”

## UI

The React app in `ui/` is built into `src/loadpath/static/` and served by `loadpath serve`.

```bash
cd ui
npm run build     # writes into src/loadpath/static/
npm run dev       # Vite, proxies /api to the Django-shaped FastAPI server
```

If you change `ui/` and only run `loadpath serve`, you are looking at a stale bundle until you `npm run build`.

## Editor gutter

`editors/vscode` is a local Cursor/VS Code extension that polls `/api/marks` and badges files on the current load path (`S` seed, `!` untested sink, `C` contract). Install from that folder; `loadpath serve` must be running.

## Desktop

```bash
pip install -e .
cd ui && npm install && npm run build && cd ..
cd desktop && npm install && npm start
```

Requires Python 3.12+ on `PATH` (`python` on Windows, `python3` elsewhere), or set `LOADPATH_PYTHON`.
