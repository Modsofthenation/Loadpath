from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from loadpath.architecture.rules import _related_accesses, evaluate
from loadpath.config import LoadpathConfig, load_config
from loadpath.graph.store import GraphStore
from loadpath.index import default_db_path, index_drift, index_repo
from loadpath.review.cluster import cluster_diff
from loadpath.review.confidence import score_confidence
from loadpath.review.diff import DiffSet, git_diff
from loadpath.review.evolution import analyze_evolution
from loadpath.workspace import git_dirty_paths, resolve_review_range
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


def _patch_names(diff: DiffSet | None) -> set[str]:
    if diff is None:
        return set()
    names: set[str] = set()
    for fd in diff.files:
        for raw in (fd.patch or "").splitlines():
            if raw.startswith("+") or raw.startswith("-"):
                if raw.startswith("+++") or raw.startswith("---"):
                    continue
                names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw[1:]))
    return names


def _test_field_residuals(impact_nodes: list[dict], diff: DiffSet | None) -> list[str]:
    names = _patch_names(diff)
    if not names:
        return []
    mentions: set[str] = set()
    for n in impact_nodes:
        if n["type"] not in {NodeType.TEST.value, NodeType.REACT_TEST.value}:
            continue
        mentions.update((n.get("extra") or {}).get("mentions") or [])
    out: list[str] = []
    seen: set[str] = set()
    for n in impact_nodes:
        if n["type"] not in {NodeType.FIELD.value, NodeType.SERIALIZER_FIELD.value}:
            continue
        fname = n.get("name") or ""
        if fname in {"id", "pk"} or fname not in names:
            continue
        if fname in mentions:
            continue
        key = f"{n['type']}:{fname}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            f"Test exists on the path but does not assert `{fname}` "
            f"({n.get('file_path') or n.get('qualified_name')})"
        )
    return out


def _react_path_residuals(impact_nodes: list[dict], diff: DiffSet | None) -> list[str]:
    changed = set(diff.paths) if diff else set()
    out: list[str] = []
    query_keys = [n for n in impact_nodes if n["type"] == NodeType.QUERY_KEY.value]
    invalidations = [
        n for n in query_keys if (n.get("extra") or {}).get("invalidation")
    ]
    mutations = [
        n
        for n in impact_nodes
        if n["type"] == NodeType.HOOK.value
        and ((n.get("extra") or {}).get("mutation") or "Mutation" in (n.get("name") or ""))
    ]
    if query_keys and mutations and not invalidations:
        out.append(
            "Mutation hook on the path does not invalidateQueries the queryKey this page reads"
        )
    for n in impact_nodes:
        extra = n.get("extra") or {}
        if n["type"] == NodeType.PAGE.value and n.get("file_path") in changed:
            if extra.get("has_error_boundary") is False:
                out.append(f"{n['name']} has no ErrorBoundary/Suspense around the page")
        if n["type"] in {NodeType.COMPONENT.value, NodeType.PAGE.value} and extra.get("form_fields"):
            pass
    field_names = {
        n["name"]
        for n in impact_nodes
        if n["type"] in {NodeType.SERIALIZER_FIELD.value, NodeType.FIELD.value}
    } & _patch_names(diff)
    form_fields: set[str] = set()
    for n in impact_nodes:
        extra = n.get("extra") or {}
        form_fields.update(extra.get("form_fields") or [])
        if n["type"] == NodeType.FORM_SCHEMA.value:
            form_fields.update(extra.get("fields") or [])
    missing_form = sorted(field_names - form_fields - {"id", "pk"})
    if missing_form and form_fields:
        out.append(
            "Changed fields "
            + ", ".join(f"`{f}`" for f in missing_form[:6])
            + " are not in the form defaultValues/Zod on this path"
        )
    return out


def collect_residuals(store: GraphStore, impact_nodes: list[dict], diff: DiffSet | None = None) -> list[str]:
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
    fields_by_name: dict[str, list[dict]] = {}
    for field in store.nodes([NodeType.FIELD]):
        fields_by_name.setdefault(field["name"], []).append(field)
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
        for hit in extra.get("nplusone") or []:
            accessed = list(hit.get("accessed") or [])
            related, _ = _related_accesses(accessed, fields_by_name, extra.get("app"))
            if not related:
                continue
            residuals.append(
                f"N+1 {', '.join(related)} in {n.get('file_path')}:{hit.get('line')} — {hit.get('suggested_fix')}"
            )
    residuals.extend(_test_field_residuals(impact_nodes, diff))
    residuals.extend(_react_path_residuals(impact_nodes, diff))
    ids = {n["id"] for n in impact_nodes}
    for e in store.edges():
        if e["src"] not in ids or e["dst"] not in ids:
            continue
        extra = e.get("extra") or {}
        if extra.get("overlap"):
            residuals.append(
                f"Inferred serializer/Zod overlap fields={extra['overlap']}"
            )
        if extra.get("superseded_by_generated"):
            residuals.append(
                f"String URL stitch {extra.get('react')} superseded by a generated OpenAPI client"
            )
    seen = set()
    out = []
    for r in residuals:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _serious_evolution_notes(notes: list[str]) -> list[str]:
    tokens = ("hotspot", "silo", "crosses a bounded", "cross-context", "temporal coupling")
    return [n for n in notes if any(tok in n.lower() for tok in tokens)]


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


def _knowledge_owners(evolution: dict) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for h in evolution.get("hotspots") or []:
        if (h.get("commits") or 0) < 3:
            continue
        for author in h.get("authors") or []:
            if author and author not in seen:
                seen.add(author)
                out.append(author)
    return out[:8]


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
    base: str = "HEAD~1",
    head: str | None = None,
    db_path: Path | None = None,
    config: LoadpathConfig | None = None,
    diff: DiffSet | None = None,
    reindex: bool = True,
    incremental: bool = True,
    *,
    three_dot: bool = True,
    draft_config: bool = False,
) -> dict:
    repo_root = repo_root.resolve()
    config = config or load_config(repo_root)
    graph_db = db_path or default_db_path(repo_root)
    if reindex:
        store = index_repo(
            repo_root,
            db_path=graph_db,
            config=config,
            incremental=incremental,
            draft_config=draft_config,
        )
    else:
        if not graph_db.is_file():
            raise FileNotFoundError(
                f"No index at {graph_db}. Run `loadpath index` or review with reindex enabled."
            )
        store = GraphStore(graph_db)

    range_info = resolve_review_range(repo_root, base, head, three_dot=three_dot)
    diff = diff or git_diff(repo_root, base, head, three_dot=three_dot)
    dirty = git_dirty_paths(repo_root)
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
    residuals = collect_residuals(store, impact_nodes, diff)
    evolution = analyze_evolution(repo_root, diff, impact_nodes, config)
    confidence = score_confidence(store, impact_nodes, impact_edges, scoped, residuals)
    serious = _serious_evolution_notes(evolution.get("notes") or [])
    if serious and confidence["level"] == "high":
        confidence["level"] = "medium"
        reasons = list(confidence.get("reasons") or [])
        reasons = [serious[0], *reasons][:3]
        confidence["reasons"] = reasons
    boot = store.get_meta("django_boot") or "off"
    if boot == "failed" and confidence["level"] == "high":
        confidence["level"] = "medium"
        reasons = list(confidence.get("reasons") or [])
        detail = store.get_meta("django_boot_detail") or "django.setup() failed"
        confidence["reasons"] = [detail, *reasons][:3]
    kinds = classify_change(impact_nodes, scoped, seeds=store.nodes_in_files(diff.paths))
    read, skip = read_order_files(diff, impact_nodes)
    reviewers = suggested_reviewers(config, impact_nodes)
    knowledge = _knowledge_owners(evolution)
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
    drift = index_drift(store, repo_root, config)
    dirty_set = set(dirty)
    overlap = [p for p in diff.paths if p in dirty_set]

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
        "knowledge_owners": knowledge,
        "sinks": sinks,
        "tests_note": tests_note,
        "architecture_note": arch_note,
        "evolution": evolution,
        "nodes": impact_nodes,
        "edges": impact_edges,
        "counts": store.counts(),
        "index": {
            "db": str(store.db_path),
            "counts": store.counts(),
            "type_counts": store.type_counts(),
            "indexed_at": store.get_meta("indexed_at"),
            "reindexed": reindex and store.get_meta("reindex_skipped") != "1",
            "incremental": incremental if reindex else store.get_meta("incremental") == "1",
            "reindex_skipped": store.get_meta("reindex_skipped") == "1",
            "files_extracted": int(store.get_meta("files_extracted") or 0),
            "stale": drift["stale"],
            "django_boot": boot,
            "django_boot_detail": store.get_meta("django_boot_detail") or "",
        },
        "workspace": {
            "dirty": dirty[:40],
            "dirty_count": len(dirty),
            "dirty_overlaps_review": bool(overlap),
            "dirty_overlap": overlap[:20],
            "merge_base": range_info.get("merge_base"),
            "three_dot": three_dot,
            "base_sha": range_info.get("base_sha"),
            "head_sha": range_info.get("head_sha"),
        },
        "headline": _headline(
            confidence, title, sinks, tests_note, arch_note, residuals, reviewers, evolution
        ),
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
            extra = n.get("extra") or {}
            name = extra.get("mounted_at") or extra.get("full_path") or n["name"]
            item = {
                "id": n["id"],
                "type": n["type"],
                "name": name,
                "file_path": n.get("file_path"),
                "context": n.get("context"),
            }
            if extra.get("broker"):
                item["broker"] = extra["broker"]
            out.append(item)
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


def _headline(confidence, title, sinks, tests_note, arch_note, residuals, reviewers, evolution=None) -> str:
    sink_bits = []
    routes = [s["name"] for s in sinks if s["type"] == NodeType.ROUTE.value]
    celery_tasks = [s["name"] for s in sinks if s["type"] == NodeType.TASK.value and s.get("broker") == "celery"]
    dramatiq_tasks = [s["name"] for s in sinks if s["type"] == NodeType.TASK.value and s.get("broker") == "dramatiq"]
    other_tasks = [
        s["name"]
        for s in sinks
        if s["type"] == NodeType.TASK.value and s.get("broker") not in {"celery", "dramatiq"}
    ]
    pages = [s["name"] for s in sinks if s["type"] in {NodeType.PAGE.value, NodeType.FORM_SCHEMA.value}]
    if routes:
        sink_bits.append(", ".join(routes[:4]))
    if celery_tasks:
        sink_bits.append("Celery " + ", ".join(celery_tasks[:3]))
    if dramatiq_tasks:
        sink_bits.append("Dramatiq " + ", ".join(dramatiq_tasks[:3]))
    if other_tasks:
        sink_bits.append("async " + ", ".join(other_tasks[:3]))
    if pages:
        sink_bits.append("React " + ", ".join(pages[:4]))
    residual = residuals[0] if residuals else "none"
    owners = ", ".join(reviewers) if reviewers else "context owners"
    pressure = (evolution or {}).get("notes") or []
    churn = pressure[0] if pressure else "none"
    return (
        f"Loadpath: {confidence['level'].upper()} — {title}\n"
        f"Sinks: {'; '.join(sink_bits) or 'none typed'}\n"
        f"Tests: {tests_note}\n"
        f"Architecture: {arch_note}\n"
        f"Residual: {residual}\n"
        f"Churn: {churn}\n"
        f"Suggested reviewers: {owners}"
    )
