from __future__ import annotations

from typing import Any

from loadpath.review.render import render_markdown


def compact_architecture(report: dict[str, Any]) -> dict[str, Any]:
    """Architecture snapshot without the full node/edge dump (too large for MCP)."""
    findings = [f for f in (report.get("findings") or []) if not f.get("waived")]
    return {
        "indexed": report.get("indexed"),
        "stale": report.get("stale"),
        "repo_root": report.get("repo_root"),
        "indexed_at": report.get("indexed_at"),
        "django_boot": report.get("django_boot") or "off",
        "counts": report.get("counts") or {"nodes": 0, "edges": 0},
        "type_counts": report.get("type_counts") or {},
        "contexts": report.get("contexts") or {},
        "rules": report.get("rules") or [],
        "findings": findings[:24],
        "deepening": (report.get("deepening") or [])[:8],
        "residuals": (report.get("residuals") or [])[:20],
        "has_config": report.get("has_config"),
    }


def compact_review(review: dict[str, Any]) -> dict[str, Any]:
    """Load-path brief: confidence, sinks, reviewers. Not the full impact graph."""
    findings = [f for f in (review.get("findings") or []) if not f.get("waived")]
    return {
        "markdown": review.get("markdown") or render_markdown(review),
        "title": review.get("title"),
        "headline": review.get("headline"),
        "confidence": review.get("confidence"),
        "change_kinds": review.get("change_kinds") or [],
        "sinks": review.get("sinks") or [],
        "suggested_reviewers": review.get("suggested_reviewers") or [],
        "read_order": review.get("read_order") or [],
        "findings": findings,
        "deepening": (review.get("deepening") or [])[:8],
        "depth_note": review.get("depth_note"),
        "residuals": (review.get("residuals") or [])[:12],
        "low_risk": review.get("low_risk"),
        "index": review.get("index"),
        "workspace": review.get("workspace"),
    }
