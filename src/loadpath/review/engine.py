from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from loadpath.architecture.rules import evaluate
from loadpath.config import LoadpathConfig, load_config
from loadpath.graph.store import GraphStore
from loadpath.index import default_db_path, index_repo
from loadpath.review.cluster import cluster_diff
from loadpath.review.confidence import score_confidence
from loadpath.review.diff import DiffSet, git_diff
from loadpath.types import (
    ChangeKind,
    GENERATED_PATH_MARKERS,
    NodeType,
)

READ_ORDER = [
    NodeType.SERIALIZER,
    NodeType.SERIALIZER_FIELD,
    NodeType.ROUTE,
    NodeType.OPENAPI_PATH,
    NodeType.FORM_SCHEMA,
    NodeType.PERMISSION,
    NodeType.VIEW,
    NodeType.VIEWSET_ACTION,
    NodeType.SERVICE,
    NodeType.MODEL,
    NodeType.FIELD,
    NodeType.MIGRATION_OP,
    NodeType.RECEIVER,
    NodeType.SIGNAL,
    NodeType.TASK,
    NodeType.PAGE,
    NodeType.HOOK,
    NodeType.API_CLIENT,
    NodeType.QUERY_KEY,
    NodeType.COMPONENT,
    NodeType.TEST,
    NodeType.REACT_TEST,
]


def classify_change(impact_nodes: list[dict], findings: list, seeds: list[dict] | None = None) -> list[str]:
    kinds: set[str] = set()
    types = {n["type"] for n in impact_nodes}
    seed_types = {n["type"] for n in (seeds or [])} or types
    if (
        NodeType.SERIALIZER.value in seed_types
        or NodeType.SERIALIZER_FIELD.value in seed_types
        or NodeType.OPENAPI_PATH.value in seed_types
        or NodeType.FORM_SCHEMA.value in seed_types
        or NodeType.ROUTE.value in seed_types
    ):
        kinds.add(ChangeKind.PUBLIC_CONTRACT.value)
    if (
        NodeType.MIGRATION_OP.value in seed_types
        or NodeType.MODEL.value in seed_types
        or NodeType.FIELD.value in seed_types
    ):
        kinds.add(ChangeKind.SCHEMA_MIGRATION.value)
    if NodeType.PERMISSION.value in seed_types:
        kinds.add(ChangeKind.AUTH.value)
    if any(getattr(f, "rule", "") in {
        "views_cannot_import_other_context_models",
        "react_feature_may_only_call_own_or_shared_api",
    } and not getattr(f, "waived", False) for f in findings):
        kinds.add(ChangeKind.CROSS_CONTEXT.value)
    if NodeType.SERVICE.value in types and ChangeKind.PUBLIC_CONTRACT.value not in kinds:
        kinds.add(ChangeKind.INTERNAL_SERVICE.value)
    ui_only = types <= {
        NodeType.COMPONENT.value,
        NodeType.PAGE.value,
        NodeType.REACT_ROUTE.value,
        NodeType.REACT_TEST.value,
        NodeType.FEATURE_MODULE.value,
    }
    if ui_only and NodeType.API_CLIENT.value not in types:
        kinds.add(ChangeKind.LEAF_UI.value)
    if NodeType.COMPONENT.value in types or NodeType.PAGE.value in types:
        if ChangeKind.PUBLIC_CONTRACT.value in kinds or NodeType.HOOK.value in types:
            pass
        elif ChangeKind.LEAF_UI.value not in kinds and len(kinds) == 0:
            kinds.add(ChangeKind.LEAF_UI.value)
    if not kinds:
        kinds.add(ChangeKind.INTERNAL_SERVICE.value)
    if len(kinds) > 1 and ChangeKind.LEAF_UI.value in kinds:
        kinds.discard(ChangeKind.LEAF_UI.value)
    return sorted(kinds)


def read_order_files(diff: DiffSet, impact_nodes: list[dict]) -> tuple[list[dict], list[str]]:
    nodes_by_file: dict[str, list[dict]] = {}
    for n in impact_nodes:
        if n.get("file_path"):
            nodes_by_file.setdefault(n["file_path"], []).append(n)
    rank = {t: i for i, t in enumerate(READ_ORDER)}

    def file_rank(path: str) -> int:
        nodes = nodes_by_file.get(path, [])
        if not nodes:
            return 50
        return min(rank.get(NodeType(n["type"]), 40) if n["type"] in {t.value for t in NodeType} else 40 for n in nodes)

    read: list[dict] = []
    skip: list[str] = []
    for f in diff.files:
        if f.skip or any(m in f.path for m in GENERATED_PATH_MARKERS if m != "generated/"):
            skip.append(f.path)
            continue
        nodes = nodes_by_file.get(f.path, [])
        if not nodes and f.path.endswith((".md", ".txt", ".lock")):
            skip.append(f.path)
            continue
        read.append(
            {
                "path": f.path,
                "status": f.status,
                "added": f.added,
                "deleted": f.deleted,
                "rank": file_rank(f.path),
                "why": _why(nodes),
            }
        )
    read.sort(key=lambda r: (r["rank"], r["path"]))
    return read, skip


def _why(nodes: list[dict]) -> str:
    if not nodes:
        return "changed file outside typed graph"
    types = [n["type"].split(".")[-1] for n in nodes]
    return ", ".join(sorted(set(types))[:4])


def collect_residuals(store: GraphStore, impact_nodes: list[dict]) -> list[str]:
    residuals = []
    tested = {
        e["src"]
        for e in store.edges()
        if e["type"] == "tested_by"
    }
    for n in impact_nodes:
        if n["type"] == NodeType.RECEIVER.value and n["id"] not in tested:
            loc = f"{n.get('file_path')}:{n.get('start_line')}" if n.get("file_path") else n["qualified_name"]
            residuals.append(f"{n['name']} ({loc}) — no test")
    stored = store.get_meta("residuals") or ""
    impact_files = {n.get("file_path") for n in impact_nodes if n.get("file_path")}
    impact_names = {n.get("name") for n in impact_nodes}
    for line in stored.splitlines():
        if any(f and f in line for f in impact_files) or any(n and str(n) in line for n in impact_names):
            residuals.append(line)
    for n in impact_nodes:
        extra = n.get("extra") or {}
        if extra.get("get_serializer_class"):
            residuals.append(f"Dynamic get_serializer_class on {n['qualified_name']}")
        if extra.get("string_ref"):
            residuals.append(f"String model ref {n['qualified_name']}")
        if extra.get("inferred"):
            residuals.append(f"Inferred client {n.get('name')} in {n.get('file_path')}")
        if extra.get("queryset_in_serializer"):
            residuals.append(f"Queryset inside serializer {n['qualified_name']}")
    seen = set()
    out = []
    for r in residuals:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def suggested_reviewers(config: LoadpathConfig, impact_nodes: list[dict]) -> list[str]:
    owners: list[str] = []
    for n in impact_nodes:
        owners.extend(config.owners_for_context(n.get("context")))
    # unique preserve order
    seen = set()
    out = []
    for o in owners:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out


def is_low_risk(kinds: list[str], confidence: dict, findings: list) -> bool:
    if any(not f.waived and f.severity.value == "blocker" for f in findings):
        return False
    if confidence["level"] == "low":
        return False
    if ChangeKind.CROSS_CONTEXT.value in kinds or ChangeKind.PUBLIC_CONTRACT.value in kinds:
        return False
    if ChangeKind.SCHEMA_MIGRATION.value in kinds or ChangeKind.AUTH.value in kinds:
        return False
    return confidence["level"] == "high" or ChangeKind.LEAF_UI.value in kinds


def run_review(
    repo_root: Path,
    base: str = "origin/main",
    head: str | None = None,
    db_path: Path | None = None,
    config: LoadpathConfig | None = None,
    diff: DiffSet | None = None,
    reindex: bool = True,
) -> dict:
    repo_root = repo_root.resolve()
    config = config or load_config(repo_root)
    if reindex:
        store = index_repo(repo_root, db_path=db_path, config=config)
    else:
        store = GraphStore(db_path or default_db_path(repo_root))

    diff = diff or git_diff(repo_root, base, head)
    clusters, impact_nodes, impact_edges = cluster_diff(store, diff)
    seed_ids = {n["id"] for n in store.nodes_in_files(diff.paths)}
    findings = evaluate(store, config, changed_ids=seed_ids)
    # keep findings that touch the impact subgraph or changed files
    impact_ids = {n["id"] for n in impact_nodes}
    impact_files = set(diff.paths)
    scoped = [
        f
        for f in findings
        if (f.node_id and f.node_id in impact_ids)
        or (f.file_path and f.file_path in impact_files)
        or not impact_ids
    ]
    residuals = collect_residuals(store, impact_nodes)
    confidence = score_confidence(store, impact_nodes, impact_edges, scoped, residuals)
    kinds = classify_change(impact_nodes, scoped, seeds=store.nodes_in_files(diff.paths))
    read, skip = read_order_files(diff, impact_nodes)
    reviewers = suggested_reviewers(config, impact_nodes)
    low_risk = is_low_risk(kinds, confidence, scoped)
    labels = ["loadpath:" + confidence["level"]]
    if low_risk:
        labels.append("loadpath:low-risk")
    if ChangeKind.CROSS_CONTEXT.value in kinds:
        labels.append("loadpath:cross-context")
    if ChangeKind.PUBLIC_CONTRACT.value in kinds:
        labels.append("loadpath:contract")

    title = _title(clusters, kinds)
    sinks = _sink_summaries(impact_nodes, store)
    tests_note = _tests_note(confidence, impact_nodes)
    arch_note = _arch_note(scoped, kinds, impact_nodes)

    payload = {
        "id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "base": diff.base,
        "head": diff.head,
        "title": title,
        "change_kinds": kinds,
        "confidence": confidence,
        "labels": labels,
        "low_risk": low_risk,
        "clusters": clusters,
        "read_order": read,
        "skip": skip,
        "findings": [f.to_dict() for f in scoped],
        "residuals": residuals,
        "suggested_reviewers": reviewers,
        "sinks": sinks,
        "tests_note": tests_note,
        "architecture_note": arch_note,
        "nodes": impact_nodes,
        "edges": impact_edges,
        "counts": store.counts(),
        "headline": _headline(confidence, title, sinks, tests_note, arch_note, residuals, reviewers),
    }
    store.save_review(payload["id"], payload["created_at"], str(repo_root), diff.base, diff.head, payload)
    store.close()
    return payload


def _title(clusters: list[dict], kinds: list[str]) -> str:
    if clusters:
        return clusters[0]["title"]
    if kinds:
        return kinds[0].replace("_", " ")
    return "change"


def _sink_summaries(nodes: list[dict], store: GraphStore) -> list[dict]:
    interesting = {
        NodeType.ROUTE.value,
        NodeType.OPENAPI_PATH.value,
        NodeType.TASK.value,
        NodeType.PAGE.value,
        NodeType.FORM_SCHEMA.value,
        NodeType.PERMISSION.value,
        NodeType.MIGRATION_OP.value,
        NodeType.RECEIVER.value,
    }
    out = []
    for n in nodes:
        if n["type"] in interesting:
            out.append(
                {
                    "id": n["id"],
                    "type": n["type"],
                    "name": n["name"],
                    "file_path": n.get("file_path"),
                    "context": n.get("context"),
                }
            )
    return out


def _tests_note(confidence: dict, nodes: list[dict]) -> str:
    untested = confidence.get("untested_sinks") or []
    covered = confidence.get("covered_sinks", 0)
    sinks = confidence.get("sinks", 0)
    if not untested:
        return f"pytest/RTL hits {covered}/{sinks} sinks in the radius"
    names = ", ".join(u["name"] for u in untested[:4])
    return f"{covered}/{sinks} sinks tested; missing tests on {names}"


def _arch_note(findings: list, kinds: list[str], impact_nodes: list[dict] | None = None) -> str:
    blockers = [f for f in findings if not f.waived and f.severity.value == "blocker"]
    if blockers:
        return blockers[0].message
    if ChangeKind.CROSS_CONTEXT.value in kinds:
        return "cross-context edges present"
    ctxs = sorted({n.get("context") for n in (impact_nodes or []) if n.get("context")})
    if ctxs:
        return "stays inside " + " / ".join(ctxs)
    return "no cross-context rule hits"


def _headline(confidence, title, sinks, tests_note, arch_note, residuals, reviewers) -> str:
    sink_bits = []
    routes = [s["name"] for s in sinks if s["type"] == NodeType.ROUTE.value]
    tasks = [s["name"] for s in sinks if s["type"] == NodeType.TASK.value]
    pages = [s["name"] for s in sinks if s["type"] in {NodeType.PAGE.value, NodeType.FORM_SCHEMA.value}]
    if routes:
        sink_bits.append(", ".join(routes[:4]))
    if tasks:
        sink_bits.append("Celery " + ", ".join(tasks[:3]))
    if pages:
        sink_bits.append("React " + ", ".join(pages[:4]))
    residual = residuals[0] if residuals else "none"
    owners = ", ".join(reviewers) if reviewers else "context owners"
    return (
        f"Loadpath: {confidence['level'].upper()} — {title}\n"
        f"Sinks: {'; '.join(sink_bits) or 'none typed'}\n"
        f"Tests: {tests_note}\n"
        f"Architecture: {arch_note}\n"
        f"Residual: {residual}\n"
        f"Suggested reviewers: {owners}"
    )
