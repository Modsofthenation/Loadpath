"""In-memory index progress for the local API/UI (and tests)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

_lock = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}


def progress_key(repo_root: Path | str) -> str:
    return str(Path(repo_root).expanduser().resolve())


def record_progress(repo_root: Path | str, event: dict[str, Any]) -> None:
    key = progress_key(repo_root)
    payload = {**event, "repo_path": key, "updated_at": time.time()}
    with _lock:
        _STATE[key] = payload


def read_progress(repo_root: Path | str) -> dict[str, Any]:
    key = progress_key(repo_root)
    with _lock:
        current = _STATE.get(key)
        if current is None:
            return {
                "phase": "idle",
                "done": 0,
                "total": 0,
                "message": "No index in progress",
                "repo_path": key,
            }
        return dict(current)


def progress_callback(repo_root: Path | str) -> Callable[[dict[str, Any]], None]:
    def _cb(event: dict[str, Any]) -> None:
        record_progress(repo_root, event)

    return _cb
