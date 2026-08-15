"""Simulate a change from a node without a git range."""

from __future__ import annotations

from pathlib import Path

from loadpath.architecture.rules import evaluate
from loadpath.config import load_config
from loadpath.graph.store import GraphStore, linked_edges
from loadpath.index import default_db_path
from loadpath.review.auth import auth_path
from loadpath.review.cluster import impact_walk
from loadpath.review.confidence import score_confidence
from loadpath.review.contract import classify_contract_break
from loadpath.review.suggested_tests import suggested_tests as sketches_for
from loadpath.review.engine import (
    READ_ORDER,
    _arch_note,
    _depth_note,
    _sink_summaries,
    _tests_note,
    classify_change,
    collect_residuals,
    suggested_reviewers,
)


def simulate_node(repo_root: Path, node_id: str, *, hops: int = 8) -> dict:
    repo_root = repo_root.resolve()
    config = load_config(repo_root)
    db = default_db_path(repo_root)
    if not db.is_file():
        raise FileNotFoundError(f"No index at {db}. Run `loadpath index` first.")
    store = GraphStore(db)
    seed = store.get_node(node_id)
    if not seed:
        store.close()
        raise KeyError(f"Unknown node: {node_id}")
    nodes, edges = impact_walk(store, {node_id}, hops=hops)
    edges = linked_edges(nodes, edges)
    findings = evaluate(store, config, changed_ids={node_id})
    impact_ids = {n["id"] for n in nodes}
    scoped = [
        f
        for f in findings
        if (f.node_id and f.node_id in impact_ids) or f.node_id == node_id or not impact_ids
    ]
    residuals = collect_residuals(store, nodes, None)
    confidence = score_confidence(store, nodes, edges, scoped, residuals)
    auth = auth_path(store, nodes, edges)
    sinks = _sink_summaries(nodes, store)
    sketches = sketches_for(confidence.get("untested_sinks") or [], nodes)
    kinds = classify_change(nodes, scoped, seeds=[seed])
    contract = classify_contract_break(nodes, None)
    read_order = _read_order(nodes)
    payload = {
        "ok": True,
        "what_if": True,
        "id": f"whatif:{node_id}",
        "node": seed,
        "title": f"What if {seed.get('name')} changes",
        "headline": f"What if {seed.get('name')} changes — {confidence.get('level')}",
        "confidence": confidence,
        "change_kinds": kinds,
        "labels": [],
        "low_risk": False,
        "clusters": [],
        "read_order": read_order,
        "skip": [],
        "sinks": sinks,
        "nodes": nodes,
        "edges": edges,
        "findings": [f.to_dict() for f in scoped],
        "residuals": residuals,
        "auth": auth,
        "contract_break": contract,
        "suggested_tests": sketches,
        "suggested_reviewers": suggested_reviewers(config, nodes),
        "tests_note": _tests_note(confidence, nodes),
        "architecture_note": _arch_note(scoped, kinds, nodes),
        "depth_note": _depth_note(scoped),
        "seed_type": seed.get("type"),
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }
    store.close()
    return payload


def _read_order(nodes: list[dict]) -> list[dict]:
    rank = {t.value: i for i, t in enumerate(READ_ORDER)}
    by_file: dict[str, list[dict]] = {}
    for n in nodes:
        path = n.get("file_path")
        if path:
            by_file.setdefault(path, []).append(n)
    out = []
    for path, group in by_file.items():
        why = ", ".join(sorted({n["type"].split(".")[-1] for n in group})[:4])
        file_rank = min(rank.get(n["type"], 40) for n in group)
        out.append({"path": path, "why": why, "status": "M", "rank": file_rank})
    out.sort(key=lambda r: (r["rank"], r["path"]))
    for item in out:
        item.pop("rank", None)
    return out
