#!/usr/bin/env python3
"""Start the bundled sidecar and wait until /api/health succeeds."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
exe = ROOT / "desktop" / "backend-dist" / "loadpath" / ("loadpath.exe" if sys.platform == "win32" else "loadpath")
if not exe.is_file():
    print(f"missing sidecar: {exe}", file=sys.stderr)
    sys.exit(1)

port = "7345"
proc = subprocess.Popen(
    [str(exe), "serve", "--host", "127.0.0.1", "--port", port, "--no-open"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
url = f"http://127.0.0.1:{port}/api/health"
try:
    last = "no response"
    for _ in range(60):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                body = response.read().decode("utf-8", errors="replace")
                if response.status == 200 and "ok" in body:
                    print(body)
                    sys.exit(0)
                last = f"HTTP {response.status}: {body}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = str(exc)
        time.sleep(1)
    print(f"sidecar did not become ready: {last}", file=sys.stderr)
    sys.exit(1)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
