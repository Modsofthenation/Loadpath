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

## Releases

Keep these versions in lockstep:

- `pyproject.toml`
- `src/loadpath/__init__.py`
- `desktop/package.json`
- `ui/package.json`
- `editors/vscode/package.json`

Bump them, merge to `main`, wait for CI, then tag the merge commit:

```bash
git checkout main
git pull
git tag v0.1.0
git push origin v0.1.0
```

Pushing `vX.Y.Z` runs **Release**: desktop installers, a Python wheel/sdist, and a GitHub Release. A pre-release version (`0.1.0rc1`, `0.1.0-rc.1`) is marked as such. The workflow does not create tags.

For a draft, Actions → **Release** → **Run workflow** with an existing tag (draft is the default). Tag from a green `main`; the tagged commit must already include `.github/workflows/release.yml`.
