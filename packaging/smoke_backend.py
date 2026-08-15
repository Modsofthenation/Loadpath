#!/usr/bin/env python3
"""Start the bundled sidecar and wait until /api/health and the UI succeed."""

from __future__ import annotations

import socket
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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=2) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.status, body


port = _free_port()
proc = subprocess.Popen(
    [str(exe), "serve", "--host", "127.0.0.1", "--port", str(port), "--no-open"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
health_url = f"http://127.0.0.1:{port}/api/health"
ui_url = f"http://127.0.0.1:{port}/"
try:
    last = "no response"
    for _ in range(60):
        if proc.poll() is not None:
            print(f"sidecar exited before it became ready (code {proc.returncode})", file=sys.stderr)
            sys.exit(1)
        try:
            status, body = _get(health_url)
            if status == 200 and "ok" in body and proc.poll() is None:
                ui_status, html = _get(ui_url)
                if ui_status != 200 or 'id="root"' not in html:
                    print(f"UI missing from sidecar: HTTP {ui_status}", file=sys.stderr)
                    sys.exit(1)
                print(body)
                sys.exit(0)
            last = f"HTTP {status}: {body}"
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
