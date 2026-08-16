"""In-memory index progress for the local API/UI (and tests)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

_lock = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}

# Overall bar spans. Keep in sync with ui/src/indexProgress.ts PHASE_SPANS.
PHASE_SPANS: dict[str, tuple[int, int]] = {
    "scan": (0, 20),
    "extract": (20, 88),
    "boot": (88, 94),
    "stitch": (94, 99),
    "skipped": (100, 100),
    "done": (100, 100),
}

LIVE_PHASES = {"scan", "extract", "boot", "stitch"}


def progress_key(repo_root: Path | str) -> str:
    return str(Path(repo_root).expanduser().resolve())


def overall_percent(event: dict[str, Any], *, floor: int = 0) -> int:
    """Map a per-phase done/total event onto a monotonic 0–100 bar."""
    phase = str(event.get("phase") or "idle")
    if phase in {"idle", ""}:
        return max(0, min(100, floor))
    span = PHASE_SPANS.get(phase)
    if span is None:
        return max(0, min(100, floor))
    start, end = span
    if start == end:
        pct = end
    else:
        total = int(event.get("total") or 0)
        done = int(event.get("done") or 0)
        if total <= 0:
            pct = start
        else:
            ratio = min(1.0, max(0.0, done / total))
            pct = int(round(start + (end - start) * ratio))
    return max(0, min(100, max(floor, pct)))


def record_progress(repo_root: Path | str, event: dict[str, Any]) -> None:
    key = progress_key(repo_root)
    payload = {**event, "repo_path": key, "updated_at": time.time()}
    with _lock:
        prev = _STATE.get(key) or {}
        floor = int(prev.get("percent") or 0)
        if payload.get("phase") == "scan" and int(payload.get("done") or 0) == 0:
            floor = 0
        payload["percent"] = overall_percent(payload, floor=floor)
        _STATE[key] = payload


def begin_progress(repo_root: Path | str, message: str = "Indexing…") -> None:
    record_progress(
        repo_root,
        {
            "phase": "scan",
            "done": 0,
            "total": 0,
            "message": message,
        },
    )


def read_progress(repo_root: Path | str) -> dict[str, Any]:
    key = progress_key(repo_root)
    with _lock:
        current = _STATE.get(key)
        if current is None:
            return {
                "phase": "idle",
                "done": 0,
                "total": 0,
                "percent": 0,
                "message": "No index in progress",
                "repo_path": key,
            }
        return dict(current)


def progress_callback(repo_root: Path | str) -> Callable[[dict[str, Any]], None]:
    def _cb(event: dict[str, Any]) -> None:
        record_progress(repo_root, event)

    return _cb
