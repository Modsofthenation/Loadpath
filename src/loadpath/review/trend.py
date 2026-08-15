"""Confidence history for the same repo / PR range."""

from __future__ import annotations

from loadpath.graph.store import GraphStore

_LEVEL_RANK = {"high": 2, "medium": 1, "low": 0}


def confidence_trend(
    store: GraphStore,
    *,
    base: str | None = None,
    head: str | None = None,
    current: dict | None = None,
    limit: int = 12,
) -> dict:
    rows = store.list_reviews(include_payload=True, limit=40)
    points: list[dict] = []
    for row in rows:
        payload = row.get("payload") or {}
        conf = payload.get("confidence") or {}
        points.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "base": row.get("base_ref"),
                "head": row.get("head_ref"),
                "level": conf.get("level"),
                "sinks": conf.get("sinks"),
                "covered_sinks": conf.get("covered_sinks"),
                "title": payload.get("title"),
                "contract_break": (payload.get("contract_break") or {}).get("kind"),
            }
        )
    same_range = [p for p in points if (not base or p["base"] == base) and (not head or p["head"] == head)]
    series = same_range or points
    series = series[:limit]
    if current:
        current_point = {
            "id": current.get("id"),
            "created_at": current.get("created_at"),
            "base": current.get("base"),
            "head": current.get("head"),
            "level": (current.get("confidence") or {}).get("level"),
            "sinks": (current.get("confidence") or {}).get("sinks"),
            "covered_sinks": (current.get("confidence") or {}).get("covered_sinks"),
            "title": current.get("title"),
            "contract_break": (current.get("contract_break") or {}).get("kind"),
            "current": True,
        }
        if not series or series[0].get("id") != current_point.get("id"):
            series = [current_point, *series]
    note = _note(series)
    return {"points": series[:limit], "note": note}


def _note(series: list[dict]) -> str:
    levels = [p.get("level") for p in series if p.get("level")]
    if len(levels) < 2:
        return "First review stored for this range"
    newest, previous = levels[0], levels[1]
    if _LEVEL_RANK.get(newest, 1) < _LEVEL_RANK.get(previous, 1):
        return f"Confidence dropped {previous} → {newest}"
    if _LEVEL_RANK.get(newest, 1) > _LEVEL_RANK.get(previous, 1):
        return f"Confidence rose {previous} → {newest}"
    sinks_now = series[0].get("sinks")
    sinks_prev = series[1].get("sinks")
    if isinstance(sinks_now, int) and isinstance(sinks_prev, int) and sinks_now != sinks_prev:
        delta = sinks_now - sinks_prev
        sign = "+" if delta > 0 else ""
        return f"Confidence stayed {newest}; sinks {sign}{delta}"
    return f"Confidence unchanged at {newest}"
