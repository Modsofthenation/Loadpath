from __future__ import annotations

from dataclasses import dataclass, field

from loadpath.config import LoadpathConfig
from loadpath.extractors.react import normalize_url_template
from loadpath.graph.store import GraphStore
from loadpath.stitch.openapi import django_route_to_template, parse_public_api
from loadpath.types import Edge, EdgeType, Node, NodeType, RuleSeverity, node_id

RULE_DOCS = {
    "views_cannot_import_other_context_models": "Views must not import models from another bounded context.",
    "react_feature_may_only_call_own_or_shared_api": "A React feature may only call its own public API or shared clients.",
    "serializers_are_the_only_published_contract": "Serializers (and OpenAPI) are the only published contract; React must not drift.",
    "no_queryset_in_serializer": "Serializers must not run querysets.",
    "celery_tasks_must_be_idempotent_on_model_pk": "Celery and Dramatiq tasks must take a model pk/id, not a full object payload.",
    "async_tasks_must_be_idempotent_on_model_pk": "Celery and Dramatiq tasks must take a model pk/id, not a full object payload.",
    "queryset_nplusone": "Querysets iterated in a loop must select_related/prefetch_related related objects they touch.",
    "cascade_crosses_context": "on_delete=CASCADE must not blast into another bounded context.",
    "migration_blast_radius": "Destructive migrations must not drop fields/models still referenced on the load path.",
}


@dataclass
class Finding:
    rule: str
    severity: RuleSeverity
    message: str
    node_id: str | None = None
    file_path: str | None = None
    waived: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "node_id": self.node_id,
            "file_path": self.file_path,
            "waived": self.waived,
            "extra": self.extra,
        }


def _waived(config: LoadpathConfig, rule: str, node: str | None) -> bool:
    for w in config.waivers:
        if w.rule != rule:
            continue
        if w.node is None or w.node == node:
            return True
    return False


def evaluate(store: GraphStore, config: LoadpathConfig, changed_ids: set[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    enabled = set(config.rules)

    if "views_cannot_import_other_context_models" in enabled:
        findings.extend(_views_foreign_models(store, config))
    if "react_feature_may_only_call_own_or_shared_api" in enabled:
        findings.extend(_react_own_api(store, config))
    if "serializers_are_the_only_published_contract" in enabled:
        findings.extend(_contract_drift(store, config))
    if "no_queryset_in_serializer" in enabled:
        findings.extend(_queryset_in_serializer(store))
    if "celery_tasks_must_be_idempotent_on_model_pk" in enabled or "async_tasks_must_be_idempotent_on_model_pk" in enabled:
        findings.extend(_task_idempotency(store, changed_ids))
    if "queryset_nplusone" in enabled:
        findings.extend(_nplusone(store))
    if "cascade_crosses_context" in enabled:
        findings.extend(_cascade_crosses_context(store, config))
    if "migration_blast_radius" in enabled:
        findings.extend(_migration_blast_radius(store))

    for f in findings:
        f.waived = _waived(config, f.rule, f.node_id)
        if f.waived:
            continue
        if f.node_id and f.extra.get("other_context"):
            store.upsert_edge(
                Edge(
                    src=f.node_id,
                    dst=node_id(NodeType.BOUNDED_CONTEXT, f.extra["other_context"]),
                    type=EdgeType.CROSSES_CONTEXT,
                    extra={"rule": f.rule, "message": f.message},
                )
            )
    store.conn.commit()
    return findings


def _views_foreign_models(store: GraphStore, config: LoadpathConfig) -> list[Finding]:
    out: list[Finding] = []
    views = {n["id"]: n for n in store.nodes([NodeType.VIEW, NodeType.SERVICE])}
    models = {n["id"]: n for n in store.nodes([NodeType.MODEL])}
    for edge in store.edges():
        if edge["type"] != EdgeType.QUERIES_MODEL.value:
            continue
        view = views.get(edge["src"])
        model = models.get(edge["dst"]) or store.get_node(edge["dst"])
        if not view or not model:
            continue
        vctx = view.get("context")
        mctx = model.get("context")
        if not mctx:
            qn = model.get("qualified_name") or ""
            app = qn.split(".")[0] if "." in qn else None
            mctx = config.context_for_django_app(app) if app else None
        if vctx and mctx and vctx != mctx:
            store.upsert_node(
                Node(
                    id=node_id(NodeType.BOUNDED_CONTEXT, mctx),
                    type=NodeType.BOUNDED_CONTEXT,
                    name=mctx,
                    qualified_name=mctx,
                )
            )
            out.append(
                Finding(
                    rule="views_cannot_import_other_context_models",
                    severity=RuleSeverity.BLOCKER,
                    message=(
                        f"{view['name']} ({vctx}) talks to {model.get('qualified_name')} "
                        f"({mctx}), skipping that context's service layer"
                    ),
                    node_id=view["id"],
                    file_path=view.get("file_path"),
                    extra={"other_context": mctx, "model": model.get("qualified_name")},
                )
            )
    return out


def _react_own_api(store: GraphStore, config: LoadpathConfig) -> list[Finding]:
    out: list[Finding] = []
    clients = {n["id"]: n for n in store.nodes([NodeType.API_CLIENT])}
    features = {n["id"]: n for n in store.nodes([NodeType.FEATURE_MODULE, NodeType.HOOK, NodeType.PAGE, NodeType.COMPONENT])}
    allowed_by_context: dict[str, set[str]] = {}
    for name, ctx in config.contexts.items():
        allowed_by_context[name] = set()
        for spec in ctx.public_api:
            _, path = parse_public_api(spec)
            allowed_by_context[name].add(path)
            allowed_by_context[name].add(normalize_url_template(path))

    for edge in store.edges():
        if edge["type"] not in {EdgeType.CALLS.value, EdgeType.CONSUMED_BY_CLIENT.value}:
            continue
        src = features.get(edge["src"])
        dst = clients.get(edge["dst"])
        if not src or not dst:
            continue
        ctx = src.get("context")
        if not ctx or config.is_shared_react(src.get("file_path") or ""):
            continue
        tmpl = normalize_url_template(dst.get("name") or "")
        allowed = allowed_by_context.get(ctx) or set()
        if not allowed:
            continue
        if any(_path_belongs(tmpl, a) for a in allowed):
            continue
        # calling another context's public API?
        other = None
        for oname, paths in allowed_by_context.items():
            if oname != ctx and any(_path_belongs(tmpl, a) for a in paths):
                other = oname
                break
        if other:
            out.append(
                Finding(
                    rule="react_feature_may_only_call_own_or_shared_api",
                    severity=RuleSeverity.BLOCKER,
                    message=(
                        f"React feature '{ctx}' called {tmpl} (owned by {other}) "
                        f"from {src.get('file_path')}"
                    ),
                    node_id=src["id"],
                    file_path=src.get("file_path"),
                    extra={"other_context": other, "url": tmpl},
                )
            )
    return out


def _path_belongs(url: str, allowed: str) -> bool:
    u = normalize_url_template(url)
    a = django_route_to_template(allowed)
    if u == a:
        return True
    u_base = u.rstrip("/").rsplit("/{id}", 1)[0]
    a_base = a.rstrip("/").rsplit("/{id}", 1)[0]
    return u_base == a_base or u.startswith(a_base + "/")


def _contract_drift(store: GraphStore, config: LoadpathConfig) -> list[Finding]:
    out: list[Finding] = []
    # If a serializer field has no matching zod field on a MATCHES_SCHEMA partner, warn
    schemas = {n["id"]: n for n in store.nodes([NodeType.FORM_SCHEMA])}
    fields = {n["id"]: n for n in store.nodes([NodeType.SERIALIZER_FIELD])}
    serializers = {n["id"]: n for n in store.nodes([NodeType.SERIALIZER])}
    matched_serializers: dict[str, list[dict]] = {}
    for edge in store.edges():
        if edge["type"] != EdgeType.MATCHES_SCHEMA.value:
            continue
        ser = serializers.get(edge["src"])
        schema = schemas.get(edge["dst"])
        if ser and schema:
            matched_serializers.setdefault(ser["id"], []).append(schema)
    for ser_id, schema_list in matched_serializers.items():
        ser = serializers[ser_id]
        ser_field_names = {
            f["name"]
            for f in fields.values()
            if f["qualified_name"].startswith(ser["qualified_name"] + ".")
        }
        for schema in schema_list:
            zod = set((schema.get("extra") or {}).get("fields") or [])
            extra_in_react = zod - ser_field_names
            missing_in_react = ser_field_names - zod
            if extra_in_react:
                out.append(
                    Finding(
                        rule="serializers_are_the_only_published_contract",
                        severity=RuleSeverity.BLOCKER,
                        message=(
                            f"Serializer field removed or missing; React form {schema['name']} "
                            f"still posts {sorted(extra_in_react)}"
                        ),
                        node_id=schema["id"],
                        file_path=schema.get("file_path"),
                        extra={"fields": sorted(extra_in_react), "serializer": ser["name"]},
                    )
                )
            if missing_in_react and extra_in_react:
                # already covered; extra missing is a warning unless changed
                pass
    return out


def _queryset_in_serializer(store: GraphStore) -> list[Finding]:
    out = []
    for ser in store.nodes([NodeType.SERIALIZER]):
        if (ser.get("extra") or {}).get("queryset_in_serializer"):
            out.append(
                Finding(
                    rule="no_queryset_in_serializer",
                    severity=RuleSeverity.BLOCKER,
                    message=f"Serializer {ser['name']} appears to run a queryset",
                    node_id=ser["id"],
                    file_path=ser.get("file_path"),
                )
            )
    return out


def _task_idempotency(store: GraphStore, changed_ids: set[str] | None) -> list[Finding]:
    out = []
    for task in store.nodes([NodeType.TASK]):
        extra = task.get("extra") or {}
        if extra.get("referenced") and extra.get("looks_idempotent_on_pk") is None:
            continue
        if extra.get("looks_idempotent_on_pk") is False or (
            extra.get("looks_idempotent_on_pk") is None and extra.get("args")
        ):
            if extra.get("looks_idempotent_on_pk"):
                continue
            args = extra.get("args") or []
            if not args:
                continue
            if extra.get("looks_idempotent_on_pk"):
                continue
            if changed_ids and task["id"] not in changed_ids:
                # still report if task is in radius — caller filters
                pass
            if extra.get("looks_idempotent_on_pk") is True:
                continue
            broker = extra.get("broker") or "task"
            label = {"celery": "Celery", "dramatiq": "Dramatiq"}.get(broker, "Async")
            out.append(
                Finding(
                    rule="celery_tasks_must_be_idempotent_on_model_pk",
                    severity=RuleSeverity.WARNING,
                    message=(
                        f"{label} task {task['name']} args {args} do not look like a model pk; "
                        "tasks must be idempotent on model pk"
                    ),
                    node_id=task["id"],
                    file_path=task.get("file_path"),
                    extra={"args": args, "broker": broker},
                )
            )
    return out


def _nplusone(store: GraphStore) -> list[Finding]:
    out: list[Finding] = []
    for node in store.nodes():
        hits = (node.get("extra") or {}).get("nplusone") or []
        for hit in hits:
            accessed = ", ".join(hit.get("accessed") or []) or "related fields"
            fix = hit.get("suggested_fix") or ".select_related()"
            out.append(
                Finding(
                    rule="queryset_nplusone",
                    severity=RuleSeverity.WARNING,
                    message=(
                        f"{node['name']} loops `{hit.get('loop_var')}` over a queryset and touches {accessed} "
                        f"without {fix} ({node.get('file_path')}:{hit.get('line')})"
                    ),
                    node_id=node["id"],
                    file_path=node.get("file_path"),
                    extra=hit,
                )
            )
    return out


def _cascade_crosses_context(store: GraphStore, config: LoadpathConfig) -> list[Finding]:
    out: list[Finding] = []
    fields = {n["id"]: n for n in store.nodes([NodeType.FIELD])}
    models = {n["id"]: n for n in store.nodes([NodeType.MODEL])}
    for edge in store.edges():
        if edge["type"] != EdgeType.RELATES_TO.value:
            continue
        if (edge.get("extra") or {}).get("on_delete") != "CASCADE":
            continue
        field = fields.get(edge["src"])
        target = models.get(edge["dst"]) or store.get_node(edge["dst"])
        if not field or not target:
            continue
        src_model = field["qualified_name"].rsplit(".", 1)[0]
        src_app = (field.get("extra") or {}).get("app") or src_model.split(".")[0]
        dst_app = (target.get("extra") or {}).get("app") or (target.get("qualified_name") or "").split(".")[0]
        sctx = field.get("context") or config.context_for_django_app(src_app)
        dctx = target.get("context") or config.context_for_django_app(dst_app)
        if sctx and dctx and sctx != dctx:
            out.append(
                Finding(
                    rule="cascade_crosses_context",
                    severity=RuleSeverity.WARNING,
                    message=(
                        f"Deleting {target.get('qualified_name')} ({dctx}) CASCADE-deletes "
                        f"{src_model} via {field['name']} ({sctx})"
                    ),
                    node_id=field["id"],
                    file_path=field.get("file_path"),
                    extra={"target_context": dctx, "on_delete": "CASCADE"},
                )
            )
    return out


def _migration_blast_radius(store: GraphStore) -> list[Finding]:
    out: list[Finding] = []
    for op in store.nodes([NodeType.MIGRATION_OP]):
        extra = op.get("extra") or {}
        kind = extra.get("op")
        if kind not in {"RemoveField", "DeleteModel"}:
            continue
        args = extra.get("args") or []
        app = extra.get("app") or ""
        still: list[dict] = []
        if kind == "RemoveField":
            model = extra.get("model_name") or (args[0] if args else None)
            field = extra.get("field_name") or (args[1] if len(args) > 1 else None)
            if not model or not field:
                continue
            still.extend(_remaining_field_refs(store, app, model, field))
        else:
            model = extra.get("model_name") or extra.get("name") or (args[0] if args else None)
            if not model:
                continue
            still.extend(_remaining_model_refs(store, app, model))
        seen: set[str] = set()
        uniq: list[dict] = []
        for node in still:
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            uniq.append(node)
        if not uniq:
            continue
        names = ", ".join(sorted({n["qualified_name"] for n in uniq})[:6])
        out.append(
            Finding(
                rule="migration_blast_radius",
                severity=RuleSeverity.WARNING,
                message=f"{op['name']} still referenced by {names}",
                node_id=op["id"],
                file_path=op.get("file_path"),
                extra={"op": kind, "still": [n["id"] for n in uniq[:8]]},
            )
        )
    return out


def _qnames(store: GraphStore, ntype: NodeType, qname: str) -> list[dict]:
    want = qname.lower()
    return [n for n in store.nodes([ntype]) if (n.get("qualified_name") or "").lower() == want]


def _ids_for(store: GraphStore, ntype: NodeType, qname: str) -> set[str]:
    ids = {node_id(ntype, qname)}
    ids.update(n["id"] for n in _qnames(store, ntype, qname))
    return ids


def _remaining_field_refs(store: GraphStore, app: str, model: str, field: str) -> list[dict]:
    still = list(_qnames(store, NodeType.FIELD, f"{app}.{model}.{field}"))
    model_ids = _ids_for(store, NodeType.MODEL, f"{app}.{model}")
    serializer_ids: set[str] = set()
    want_model = f"{app}.{model}".lower()
    for edge in store.edges():
        if edge["type"] != EdgeType.SERIALIZES.value:
            continue
        dst = (edge.get("dst") or "").lower()
        if edge["dst"] in model_ids or dst.endswith(":" + want_model):
            serializer_ids.add(edge["src"])
    for edge in store.edges():
        if edge["type"] != EdgeType.HAS_FIELD.value or edge["src"] not in serializer_ids:
            continue
        child = store.get_node(edge["dst"])
        if child and child.get("name") == field:
            still.append(child)
    return still


def _remaining_model_refs(store: GraphStore, app: str, model: str) -> list[dict]:
    still = list(_qnames(store, NodeType.MODEL, f"{app}.{model}"))
    model_ids = _ids_for(store, NodeType.MODEL, f"{app}.{model}")
    want = f"{app}.{model}".lower()
    for edge in store.edges():
        dst = (edge.get("dst") or "").lower()
        if edge["dst"] not in model_ids and not dst.endswith(":" + want):
            continue
        if edge["type"] in {
            EdgeType.SERIALIZES.value,
            EdgeType.QUERIES_MODEL.value,
            EdgeType.RELATES_TO.value,
        }:
            src = store.get_node(edge["src"])
            if src:
                still.append(src)
    return still
