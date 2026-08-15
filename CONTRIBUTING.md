# Contributing

## Setup

Python 3.12+ and Node 22+.

```bash
pip install -e ".[dev]"
python -m playwright install chromium   # optional; needed for UI screenshot tests
cd ui && npm install && npm run build && cd ..
loadpath --help
```

## Tests

```bash
pytest
cd ui && npm test
node --test desktop/*.test.mjs
```

CI installs Chromium and runs the full suite.

Parity tests clone public OSS repos at pinned SHAs. The first run needs network; after that the clone is reused.

## Screenshots

README images live in `docs/screenshots/` and are produced by Playwright:

```bash
LOADPATH_SCREENSHOT_DIR=docs/screenshots python -m pytest tests/e2e/test_ui_screenshots.py
```

Headless Chromium in this environment often cannot render WebGL, so `graph-3d.png` may be the fallback card. Do not treat that file as a 3D demo.

## UI

The React app in `ui/` is built into `src/loadpath/static/` and served by `loadpath serve`.

```bash
cd ui
npm run build     # writes into src/loadpath/static/
npm run dev       # Vite, proxies /api to the Django-shaped FastAPI server
```

If you change `ui/` and only run `loadpath serve`, you are looking at a stale bundle until you `npm run build`.

## Desktop

```bash
pip install -e .
cd ui && npm install && npm run build && cd ..
cd desktop && npm install && npm start
```

Requires Python 3.12+ on `PATH` (`python` on Windows, `python3` elsewhere), or set `LOADPATH_PYTHON`.
