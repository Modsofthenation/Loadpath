"""Cheap line lookups for extractors (avoid `source[:pos].count('\\n')` per match)."""

from __future__ import annotations

import bisect


def newline_starts(source: str) -> list[int]:
    starts = [0]
    idx = 0
    while True:
        found = source.find("\n", idx)
        if found < 0:
            break
        starts.append(found + 1)
        idx = found + 1
    return starts


def line_at(starts: list[int], pos: int) -> int:
    return bisect.bisect_right(starts, pos)
