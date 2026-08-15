"""Review experience: roles, checklist, marks, history, path isolate, health."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from loadpath.review.codeowners import review_codeowners
from loadpath.types import CONTRACT_TYPES, SINK_TYPES, EdgeType, NodeType

SINK_TYPE_VALUES = {t.value for t in SINK_TYPES}
CONTRACT_TYPE_VALUES = {t.value for t in CONTRACT_TYPES}
TEST_TYPES = {NodeType.TEST.value, NodeType.REACT_TEST.value}


def tested_src_ids(edges: list[dict[str, Any]]) -> set[str]:
    return {e["src"] for e in edges if e.get("type") == EdgeType.TESTED_BY.value}


def node_roles(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    seed_ids: set[str] | None = None,
) -> dict[str, list[str]]:
    seeds = set(seed_ids or [])
    tested = tested_src_ids(edges)
    roles: dict[str, list[str]] = {}
    for n in nodes:
        nid = n.get("id") or ""
        tags: list[str] = []
        ntype = n.get("type") or ""
        extra = n.get("extra") or {}
        if nid in seeds:
            tags.append("seed")
        elif seeds:
            tags.append("downstream")
        if ntype in SINK_TYPE_VALUES:
            tags.append("sink")
        if ntype in CONTRACT_TYPE_VALUES:
            tags.append("contract")
        if ntype in TEST_TYPES:
            tags.append("test")
        if nid in tested:
            tags.append("tested")
        elif ntype in SINK_TYPE_VALUES:
            tags.append("untested")
        if extra.get("inferred"):
            tags.append("inferred")
        roles[nid] = tags
    for e in edges:
        if (e.get("extra") or {}).get("overlap") or (e.get("confidence") or 1) < 0.8:
            for key in (e.get("src"), e.get("dst")):
                if key and key in roles and "inferred" not in roles[key]:
                    roles[key].append("inferred")
    return roles


def contract_sides(nodes: list[dict[str, Any]], fields: list[str] | None = None) -> dict[str, Any]:
    serializer: set[str] = set()
    zod: set[str] = set()
    openapi: set[str] = set()
    graphql: set[str] = set()
    for n in nodes:
        extra = n.get("extra") or {}
        ntype = n.get("type") or ""
        if ntype in {NodeType.SERIALIZER_FIELD.value, NodeType.FIELD.value}:
            if n.get("name"):
                serializer.add(str(n["name"]))
        if ntype == NodeType.SERIALIZER.value:
            serializer.update(str(x) for x in (extra.get("fields") or []) if x)
        if ntype == NodeType.FORM_SCHEMA.value:
            zod.update(str(x) for x in (extra.get("fields") or extra.get("form_fields") or []) if x)
        if ntype in {NodeType.COMPONENT.value, NodeType.PAGE.value}:
            zod.update(str(x) for x in (extra.get("form_fields") or []) if x)
        if ntype == NodeType.OPENAPI_PATH.value:
            openapi.update(str(x) for x in (extra.get("fields") or []) if x)
            if n.get("name"):
                openapi.add(str(n["name"]))
        if ntype in {NodeType.GRAPHQL_FIELD.value, NodeType.GRAPHQL_TYPE.value}:
            if n.get("name"):
                graphql.add(str(n["name"]))
            graphql.update(str(x) for x in (extra.get("fields") or []) if x)

    hinted = [f for f in (fields or []) if f and f not in {"id", "pk", "extra_kwargs", "required"}]
    names = sorted((serializer | zod | graphql | set(hinted)) - {"id", "pk"})
    rows: list[dict[str, Any]] = []
    for name in names[:40]:
        in_ser = name in serializer
        in_zod = name in zod
        in_gql = name in graphql
        if in_ser and (in_zod or in_gql or not (zod or graphql)):
            status = "aligned" if (in_zod or in_gql or not (zod or graphql)) else "missing_client"
        elif in_ser and not in_zod and zod:
            status = "missing_client"
        elif (in_zod or in_gql) and not in_ser and serializer:
            status = "missing_server"
        elif name in hinted:
            status = "changed"
        else:
            status = "partial"
        if in_ser and in_zod:
            status = "aligned"
        rows.append(
            {
                "field": name,
                "serializer": in_ser,
                "zod": in_zod,
                "openapi": name in openapi,
                "graphql": in_gql,
                "status": status,
            }
        )
    return {
        "serializer": sorted(serializer - {"id", "pk"})[:40],
        "zod": sorted(zod)[:40],
        "openapi": sorted(openapi)[:20],
        "graphql": sorted(graphql)[:40],
        "rows": rows,
    }


def checklist(review: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    conf = review.get("confidence") or {}
    findings = [f for f in (review.get("findings") or []) if not f.get("waived")]
    waived = [f for f in (review.get("findings") or []) if f.get("waived")]
    sketches = {s.get("sink"): s for s in (review.get("suggested_tests") or [])}

    blockers = [f for f in findings if f.get("severity") == "blocker"]
    warnings = [f for f in findings if f.get("severity") != "blocker"]
    for f in blockers:
        items.append(
            {
                "id": f"finding:{f.get('rule')}:{f.get('node_id') or f.get('message')}",
                "kind": "finding",
                "status": "todo",
                "title": f"Fix blocker · {f.get('rule')}",
                "detail": f.get("message") or "",
                "node_id": f.get("node_id"),
                "file_path": f.get("file_path"),
                "rule": f.get("rule"),
                "action": "fix",
            }
        )
    for f in warnings:
        items.append(
            {
                "id": f"finding:{f.get('rule')}:{f.get('node_id') or f.get('message')}",
                "kind": "finding",
                "status": "todo",
                "title": f"Resolve · {f.get('rule')}",
                "detail": f.get("message") or "",
                "node_id": f.get("node_id"),
                "file_path": f.get("file_path"),
                "rule": f.get("rule"),
                "action": "fix",
            }
        )

    contract = review.get("contract_break") or {}
    if contract.get("kind") and contract["kind"] != "none":
        items.append(
            {
                "id": f"contract:{contract['kind']}",
                "kind": "contract",
                "status": "todo" if contract["kind"] in {"breaking", "drift"} else "info",
                "title": f"Contract {contract['kind']}",
                "detail": "; ".join(contract.get("reasons") or []) or "Public contract changed",
                "action": "review-contract",
            }
        )

    auth = review.get("auth") or {}
    for missing in auth.get("missing_permissions") or []:
        items.append(
            {
                "id": f"auth:{missing.get('id')}",
                "kind": "auth",
                "status": "todo",
                "title": f"Gate {missing.get('name')}",
                "detail": auth.get("note") or "Missing permission_classes",
                "node_id": missing.get("id"),
                "action": "fix",
            }
        )

    for sink in conf.get("untested_sinks") or []:
        sketch = sketches.get(sink.get("name")) or sketches.get(sink.get("id"))
        items.append(
            {
                "id": f"test:{sink.get('id')}",
                "kind": "test",
                "status": "todo",
                "title": f"Test {sink.get('name')}",
                "detail": (sketch or {}).get("title") or "Sink on the path has no test that still reaches the change",
                "node_id": sink.get("id"),
                "body": (sketch or {}).get("body"),
                "action": "write-test",
            }
        )

    for residual in (review.get("residuals") or [])[:8]:
        items.append(
            {
                "id": f"residual:{residual[:80]}",
                "kind": "residual",
                "status": "info",
                "title": "Residual the graph could not close",
                "detail": residual,
                "action": "ask-ai",
            }
        )

    for f in waived:
        items.append(
            {
                "id": f"waived:{f.get('rule')}:{f.get('node_id')}",
                "kind": "waiver",
                "status": "done",
                "title": f"Waived · {f.get('rule')}",
                "detail": f.get("message") or "",
                "node_id": f.get("node_id"),
                "file_path": f.get("file_path"),
                "rule": f.get("rule"),
                "action": "none",
            }
        )

    todo = [i for i in items if i["status"] == "todo"]
    if not todo and (conf.get("level") == "high" or review.get("low_risk")):
        items.insert(
            0,
            {
                "id": "ready",
                "kind": "ready",
                "status": "done",
                "title": "Ready to merge",
                "detail": "No blockers, untested sinks, or breaking contract on this walk.",
                "action": "none",
            },
        )
    elif not todo and conf.get("level") == "medium":
        items.insert(
            0,
            {
                "id": "glance",
                "kind": "ready",
                "status": "info",
                "title": "Glance review",
                "detail": "Medium confidence — read the residual list and contract panel.",
                "action": "none",
            },
        )
    return items


def file_marks(review: dict[str, Any]) -> list[dict[str, Any]]:
    roles = review.get("node_roles") or node_roles(
        review.get("nodes") or [],
        review.get("edges") or [],
        set(review.get("seed_ids") or []),
    )
    by_path: dict[str, dict[str, Any]] = {}
    for n in review.get("nodes") or []:
        path = n.get("file_path")
        if not path:
            continue
        tags = roles.get(n.get("id") or "", [])
        current = by_path.setdefault(
            path,
            {
                "path": path,
                "line": n.get("start_line"),
                "roles": [],
                "node_id": n.get("id"),
                "badge": "",
                "tooltip": "",
            },
        )
        for tag in tags:
            if tag not in current["roles"]:
                current["roles"].append(tag)
        if n.get("start_line") and (current.get("line") is None or n["start_line"] < current["line"]):
            current["line"] = n["start_line"]
            current["node_id"] = n.get("id")
        if "seed" in tags:
            current["node_id"] = n.get("id")
            current["line"] = n.get("start_line") or current.get("line")

    order = ["seed", "untested", "contract", "sink", "tested", "downstream"]
    badge_for = {
        "seed": "S",
        "untested": "!",
        "contract": "C",
        "sink": "↓",
        "tested": "✓",
        "downstream": "→",
    }
    out: list[dict[str, Any]] = []
    for path, item in sorted(by_path.items()):
        lead = next((r for r in order if r in item["roles"]), item["roles"][0] if item["roles"] else "path")
        item["badge"] = badge_for.get(lead, "·")
        item["tooltip"] = f"{path} — " + ", ".join(item["roles"] or ["on load path"])
        out.append(item)
    return out


def isolate_paths(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    source_id: str,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Keep nodes/edges on directed paths from source to target (or any sink)."""
    ids = {n["id"] for n in nodes if n.get("id")}
    if source_id not in ids:
        return {"node_ids": [], "edge_ids": [], "targets": []}
    succ: dict[str, list[tuple[str, str]]] = defaultdict(list)
    pred: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in edges:
        src, dst, eid = e.get("src"), e.get("dst"), e.get("id")
        if src not in ids or dst not in ids or not eid:
            continue
        succ[src].append((dst, eid))
        pred[dst].append((src, eid))

    sinks = {n["id"] for n in nodes if n.get("type") in SINK_TYPE_VALUES}
    targets = {target_id} if target_id and target_id in ids else (sinks or ids)
    if source_id in targets and target_id is None:
        targets = (sinks - {source_id}) or targets

    reachable: set[str] = set()
    stack = [source_id]
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt, _ in succ.get(cur, []):
            if nxt not in reachable:
                stack.append(nxt)

    can_reach_target: set[str] = set()
    stack = [t for t in targets if t in reachable]
    seen_t = set(stack)
    while stack:
        cur = stack.pop()
        can_reach_target.add(cur)
        for prev, _ in pred.get(cur, []):
            if prev in reachable and prev not in seen_t:
                seen_t.add(prev)
                stack.append(prev)

    keep = can_reach_target | {source_id}
    if target_id:
        keep.add(target_id)
    edge_ids = [
        e["id"]
        for e in edges
        if e.get("src") in keep and e.get("dst") in keep and e.get("id")
    ]
    hit_targets = sorted(t for t in targets if t in keep and t != source_id)
    return {"node_ids": sorted(keep), "edge_ids": edge_ids, "targets": hit_targets}


def summarize_stored_review(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") or {}
    conf = payload.get("confidence") or {}
    contract = payload.get("contract_break") or {}
    findings = [f for f in (payload.get("findings") or []) if not f.get("waived")]
    return {
        "id": item.get("id") or payload.get("id"),
        "created_at": item.get("created_at") or payload.get("created_at"),
        "base_ref": item.get("base_ref") or payload.get("base"),
        "head_ref": item.get("head_ref") or payload.get("head"),
        "title": payload.get("title"),
        "level": conf.get("level"),
        "sinks": conf.get("sinks"),
        "covered_sinks": conf.get("covered_sinks"),
        "contract_break": contract.get("kind"),
        "findings": len(findings),
        "low_risk": payload.get("low_risk"),
        "labels": payload.get("labels") or [],
        "what_if": bool(payload.get("what_if")),
        "contexts": sorted(
            {n.get("context") for n in (payload.get("nodes") or []) if n.get("context")}
        ),
    }


def diff_reviews(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    def sink_names(review: dict[str, Any]) -> set[str]:
        return {s.get("name") or s.get("id") for s in (review.get("sinks") or []) if s}

    def finding_keys(review: dict[str, Any]) -> set[str]:
        return {
            f"{f.get('rule')}:{f.get('node_id') or f.get('message')}"
            for f in (review.get("findings") or [])
            if not f.get("waived")
        }

    now, then = sink_names(current), sink_names(previous)
    now_f, then_f = finding_keys(current), finding_keys(previous)
    now_level = (current.get("confidence") or {}).get("level")
    then_level = (previous.get("confidence") or {}).get("level")
    now_kind = (current.get("contract_break") or {}).get("kind") or "none"
    then_kind = (previous.get("contract_break") or {}).get("kind") or "none"
    rank = {"high": 2, "medium": 1, "low": 0}
    direction = "same"
    if rank.get(now_level, -1) > rank.get(then_level, -1):
        direction = "rose"
    elif rank.get(now_level, -1) < rank.get(then_level, -1):
        direction = "dropped"
    added, removed = sorted(now - then), sorted(then - now)
    note_bits = []
    if direction != "same":
        note_bits.append(f"Confidence {direction} ({then_level} → {now_level})")
    if added:
        note_bits.append("New sinks: " + ", ".join(added[:4]))
    if removed:
        note_bits.append("Gone: " + ", ".join(removed[:4]))
    if now_kind != then_kind:
        note_bits.append(f"Contract {then_kind} → {now_kind}")
    return {
        "direction": direction,
        "added_sinks": added,
        "removed_sinks": removed,
        "added_findings": len(now_f - then_f),
        "removed_findings": len(then_f - now_f),
        "from_level": then_level,
        "to_level": now_level,
        "from_contract": then_kind,
        "to_contract": now_kind,
        "note": "; ".join(note_bits) or "Same sinks and confidence as the compared walk.",
    }


def architecture_health(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Pulse from stored reviews: confidence, findings, inferred-edge ratio, per-context hits."""
    points: list[dict[str, Any]] = []
    context_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in reviews:
        payload = item.get("payload") or item
        conf = payload.get("confidence") or {}
        edges = payload.get("edges") or []
        inferred = sum(1 for e in edges if (e.get("confidence") or 1) < 0.8)
        ratio = (inferred / len(edges)) if edges else 0.0
        findings = [f for f in (payload.get("findings") or []) if not f.get("waived")]
        by_ctx: dict[str, int] = defaultdict(int)
        nodes = {n.get("id"): n for n in (payload.get("nodes") or [])}
        for f in findings:
            ctx = (nodes.get(f.get("node_id") or "") or {}).get("context") or "unscoped"
            by_ctx[ctx] += 1
        point = {
            "id": item.get("id") or payload.get("id"),
            "created_at": item.get("created_at") or payload.get("created_at"),
            "level": conf.get("level"),
            "sinks": conf.get("sinks") or 0,
            "covered_sinks": conf.get("covered_sinks") or 0,
            "findings": len(findings),
            "inferred_ratio": round(ratio, 3),
            "contexts": dict(by_ctx),
            "title": payload.get("title"),
        }
        points.append(point)
        for ctx, count in by_ctx.items():
            context_series[ctx].append(
                {"created_at": point["created_at"], "findings": count, "level": point["level"]}
            )
    points.sort(key=lambda p: p.get("created_at") or "")
    return {
        "points": points[-24:],
        "contexts": {k: v[-24:] for k, v in sorted(context_series.items())},
    }


def match_reviews_to_prs(
    summaries: list[dict[str, Any]],
    pull_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pr in pull_requests:
        item = dict(pr)
        source = str(pr.get("source_branch") or "")
        target = str(pr.get("target_branch") or "")
        head_sha = str(pr.get("head_sha") or "")
        base_sha = str(pr.get("base_sha") or "")
        hit = None
        for summary in summaries:
            head = str(summary.get("head_ref") or "")
            base = str(summary.get("base_ref") or "")
            if head_sha and head.startswith(head_sha[:7]):
                hit = summary
                break
            if source and (head == source or head.endswith("/" + source)):
                if not target or base == target or target in base:
                    hit = summary
                    break
            if base_sha and base.startswith(base_sha[:7]) and head_sha and head.startswith(head_sha[:7]):
                hit = summary
                break
        if hit:
            item["loadpath"] = hit
        out.append(item)
    return out


def attach_experience(
    review: dict[str, Any],
    *,
    seed_ids: set[str] | None = None,
    repo_root: Any | None = None,
) -> dict[str, Any]:
    """Fill roles, checklist, marks, contract sides, CODEOWNERS. Safe on old stored reviews."""
    nodes = review.get("nodes") or []
    edges = review.get("edges") or []
    seeds = set(seed_ids or review.get("seed_ids") or [])
    if not seeds:
        seeds = {
            n["id"]
            for n in nodes
            if n.get("id") and (n.get("file_path") in {r.get("path") for r in (review.get("read_order") or [])})
        }
    review["seed_ids"] = sorted(seeds)
    review["node_roles"] = node_roles(nodes, edges, seeds)
    contract = dict(review.get("contract_break") or {})
    if "sides" not in contract:
        contract["sides"] = contract_sides(nodes, contract.get("fields") or [])
        review["contract_break"] = contract
    review["checklist"] = checklist(review)
    review["marks"] = file_marks(review)
    if repo_root is not None and "codeowners" not in review:
        paths = [r.get("path") for r in (review.get("read_order") or []) if r.get("path")]
        paths.extend(n.get("file_path") for n in nodes if n.get("file_path"))
        review["codeowners"] = review_codeowners(repo_root, [p for p in paths if p])
        yml = list(review.get("suggested_reviewers") or [])
        extra = [o for o in (review["codeowners"].get("owners") or []) if o not in yml]
        review["codeowners_reviewers"] = extra
        review["suggested_reviewers"] = yml + extra
    return review
