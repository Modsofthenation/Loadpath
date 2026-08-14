from __future__ import annotations

from loadpath.architecture.rules import Finding, RuleSeverity
from loadpath.graph.store import GraphStore
from loadpath.types import (
    CONTRACT_TYPES,
    ConfidenceLevel,
    EdgeType,
    NodeType,
    SINK_TYPES,
)

SINK_TYPE_VALUES = {t.value for t in SINK_TYPES}
CONTRACT_TYPE_VALUES = {t.value for t in CONTRACT_TYPES}
TEST_TYPES = {NodeType.TEST.value, NodeType.REACT_TEST.value}


def score_confidence(
    store: GraphStore,
    impact_nodes: list[dict],
    impact_edges: list[dict],
    findings: list[Finding],
    residuals: list[str],
) -> dict:
    sinks = [n for n in impact_nodes if n["type"] in SINK_TYPE_VALUES]
    if not sinks:
        # pages / forms / routes still count
        sinks = [
            n
            for n in impact_nodes
            if n["type"]
            in {
                NodeType.PAGE.value,
                NodeType.ROUTE.value,
                NodeType.TASK.value,
                NodeType.FORM_SCHEMA.value,
                NodeType.OPENAPI_PATH.value,
            }
        ]

    tested_ids: set[str] = set()
    impact_ids = {n["id"] for n in impact_nodes}
    for e in impact_edges:
        if e["type"] != EdgeType.TESTED_BY.value:
            continue
        if e["src"] in impact_ids and e["dst"] in impact_ids:
            tested_ids.add(e["src"])

    # A sink is covered if it, or a producer within two hops on THIS path, is tested.
    inbound: dict[str, list[str]] = {}
    for e in impact_edges:
        if e["src"] not in impact_ids or e["dst"] not in impact_ids:
            continue
        inbound.setdefault(e["dst"], []).append(e["src"])
        inbound.setdefault(e["src"], []).append(e["dst"])

    def reachable_tested(nid: str, depth: int = 2) -> bool:
        if nid in tested_ids:
            return True
        seen = {nid}
        frontier = [nid]
        for _ in range(depth):
            nxt = []
            for cur in frontier:
                for other in inbound.get(cur, []):
                    if other in seen:
                        continue
                    seen.add(other)
                    if other in tested_ids:
                        return True
                    nxt.append(other)
            frontier = nxt
        return False

    covered = [s for s in sinks if reachable_tested(s["id"])]
    sink_ratio = (len(covered) / len(sinks)) if sinks else 1.0

    blockers = [f for f in findings if f.severity == RuleSeverity.BLOCKER and not f.waived]
    warnings = [f for f in findings if f.severity == RuleSeverity.WARNING and not f.waived]

    inferred = [e for e in impact_edges if e.get("confidence", 1) < 0.8]
    unresolved_ratio = (len(inferred) / len(impact_edges)) if impact_edges else 0.0

    contract_nodes = [n for n in impact_nodes if n["type"] in CONTRACT_TYPE_VALUES]
    contract_ok = True
    for f in blockers:
        if f.rule == "serializers_are_the_only_published_contract":
            contract_ok = False

    reasons: list[str] = []
    level = ConfidenceLevel.HIGH

    if blockers:
        level = ConfidenceLevel.LOW
        reasons.append(f"{len(blockers)} architecture blocker(s)")
    elif sinks and sink_ratio < 0.2:
        level = ConfidenceLevel.LOW
        reasons.append(f"only {len(covered)}/{len(sinks)} sinks have tests that hit the changed radius")
    elif sink_ratio < 0.85 or warnings or unresolved_ratio > 0.35:
        level = ConfidenceLevel.MEDIUM
        if sink_ratio < 0.85:
            reasons.append(f"tests cover {len(covered)}/{len(sinks)} sinks")
        if warnings:
            reasons.append(f"{len(warnings)} architecture warning(s)")
        if unresolved_ratio > 0.35:
            reasons.append(f"{len(inferred)} inferred/unresolved edges on the path")
    else:
        reasons.append(f"tests cover {len(covered)}/{len(sinks) or 0} sinks")
        reasons.append("no architecture blockers")
        reasons.append("edges resolved")

    if not contract_ok and level == ConfidenceLevel.HIGH:
        level = ConfidenceLevel.MEDIUM
        reasons.append("contract drift between serializer and client/form")

    if residuals and level == ConfidenceLevel.HIGH:
        level = ConfidenceLevel.MEDIUM
        reasons.append(f"{len(residuals)} residual dynamic/inferred item(s)")

    while len(reasons) < 3:
        if unresolved_ratio > 0:
            reasons.append(f"{len(inferred)} inferred edges remain")
        elif contract_nodes:
            reasons.append(f"{len(contract_nodes)} contract node(s) in radius")
        else:
            reasons.append("impact radius is small")
        if len(reasons) >= 3:
            break

    return {
        "level": level.value,
        "score": round(sink_ratio - 0.15 * len(blockers) - 0.05 * unresolved_ratio, 3),
        "reasons": reasons[:3],
        "sinks": len(sinks),
        "covered_sinks": len(covered),
        "sink_ratio": round(sink_ratio, 3),
        "blockers": len(blockers),
        "warnings": len(warnings),
        "inferred_edges": len(inferred),
        "unresolved_ratio": round(unresolved_ratio, 3),
        "contract_ok": contract_ok,
        "tested_ids": sorted(tested_ids),
        "sink_ids": [s["id"] for s in sinks],
        "untested_sinks": [
            {"id": s["id"], "name": s["name"], "type": s["type"], "file_path": s.get("file_path")}
            for s in sinks
            if not reachable_tested(s["id"])
        ],
    }
