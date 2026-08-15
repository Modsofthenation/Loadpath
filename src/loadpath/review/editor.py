"""Open a repo file in the local editor (Cursor / VS Code / system)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_TIMEOUT = 8
_EDITORS = {
    "cursor": ["cursor", "cursor.cmd"],
    "vscode": ["code", "code.cmd"],
    "system": [],
}


def _safe_file(repo_root: Path, rel_or_abs: str) -> Path:
    root = repo_root.resolve()
    raw = Path(rel_or_abs).expanduser()
    full = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        full.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path is outside the repository: {rel_or_abs}") from exc
    if not full.exists():
        raise FileNotFoundError(f"File not found: {full}")
    return full


def editor_urls(full: Path, line: int | None) -> dict[str, str]:
    path = str(full)
    suffix = f":{line}" if line and line > 0 else ""
    # vscode/cursor URI: vscode://file/<absPath>:<line>
    encoded = path.replace("\\", "/")
    if not encoded.startswith("/"):
        encoded = "/" + encoded
    loc = f"{encoded}{suffix}"
    return {
        "cursor": f"cursor://file{loc}",
        "vscode": f"vscode://file{loc}",
        "vscode-insiders": f"vscode-insiders://file{loc}",
        "file": full.as_uri() + (f"#L{line}" if line and line > 0 else ""),
    }


def open_in_editor(
    repo_root: Path,
    path: str,
    line: int | None = None,
    editor: str | None = None,
) -> dict[str, Any]:
    full = _safe_file(repo_root, path)
    urls = editor_urls(full, line)
    wanted = (editor or os.environ.get("LOADPATH_EDITOR") or "auto").strip().lower()
    commands: list[list[str]] = []
    if wanted in {"cursor", "auto"}:
        binary = next((b for b in _EDITORS["cursor"] if shutil.which(b)), None)
        if binary:
            goto = f"{full}:{line}" if line and line > 0 else str(full)
            commands.append([binary, "--goto", goto])
    if wanted in {"vscode", "code", "auto"}:
        binary = next((b for b in _EDITORS["vscode"] if shutil.which(b)), None)
        if binary:
            args = [binary, "-g", f"{full}:{line}"] if line and line > 0 else [binary, str(full)]
            commands.append(args)
    if wanted in {"system", "auto"}:
        if os.name == "nt":
            commands.append(["cmd", "/c", "start", "", str(full)])
        elif sys.platform == "darwin":
            commands.append(["open", str(full)])
        else:
            commands.append(["xdg-open", str(full)])

    last_error = ""
    for cmd in commands:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {
                "ok": True,
                "path": str(full.relative_to(repo_root.resolve())),
                "abs_path": str(full),
                "line": line,
                "opened_with": cmd[0],
                "urls": urls,
            }
        except OSError as exc:
            last_error = str(exc)
    return {
        "ok": False,
        "path": str(full.relative_to(repo_root.resolve())),
        "abs_path": str(full),
        "line": line,
        "opened_with": None,
        "urls": urls,
        "error": last_error or "No editor binary found. Use the cursor:// or vscode:// link.",
    }
