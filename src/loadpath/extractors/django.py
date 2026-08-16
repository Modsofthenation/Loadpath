from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

from loadpath.config import LoadpathConfig
from loadpath.types import Edge, EdgeType, ExtractedGraph, Node, NodeType, node_id

DJANGO_VIEW_BASES = {
    "View",
    "APIView",
    "GenericAPIView",
    "ViewSet",
    "GenericViewSet",
    "ModelViewSet",
    "ReadOnlyModelViewSet",
    "ListAPIView",
    "RetrieveAPIView",
    "CreateAPIView",
    "UpdateAPIView",
    "DestroyAPIView",
    "ListCreateAPIView",
    "RetrieveUpdateAPIView",
    "RetrieveUpdateDestroyAPIView",
    "TemplateView",
    "FormView",
    "RedirectView",
}

SERIALIZER_BASES = {"Serializer", "ModelSerializer", "HyperlinkedModelSerializer", "ListSerializer"}
FORM_BASES = {"Form", "ModelForm", "BaseForm", "BaseModelForm"}
FILTERSET_BASES = {"FilterSet"}
MODEL_BASES = {"Model"}
# Subpackages that are never the Django app name (billing/views/foo.py → billing).
APP_PACKAGE_DIRS = {
    "views",
    "viewsets",
    "serializers",
    "models",
    "forms",
    "filtersets",
    "filters",
    "tasks",
    "admin",
    "tests",
    "templatetags",
    "management",
    "commands",
    "migrations",
    "actors",
    "signals",
    "receivers",
    "services",
    "handlers",
    "api",
    "endpoints",
    "permissions",
    "throttles",
    "consumers",
    "schema",
    "routing",
    "gateway",
}
ADMIN_BASES = {"ModelAdmin", "StackedInline", "TabularInline"}
CELERY_DECORATORS = {"shared_task", "task", "periodic_task"}
DRAMATIQ_DECORATORS = {"actor"}
TASK_DECORATORS = CELERY_DECORATORS | DRAMATIQ_DECORATORS
CELERY_ENQUEUE = {"delay", "apply_async"}
CELERY_SIGNATURE = {"s", "si"}
CELERY_CANVAS = {"group", "chain", "chord", "signature"}
DRAMATIQ_ENQUEUE = {"send", "send_with_options"}
CELERY_TASK_BASES = {"Task"}
DRAMATIQ_TASK_BASES = {"GenericActor"}
NINJA_HTTP = {"get", "post", "put", "patch", "delete", "api_operation"}
NINJA_SCHEMA_BASES = {"Schema", "ModelSchema"}
FASTAPI_HTTP = {"get", "post", "put", "patch", "delete", "options", "head", "trace", "api_route", "websocket"}
CONSUMER_BASES = {
    "WebsocketConsumer",
    "AsyncWebsocketConsumer",
    "JsonWebsocketConsumer",
    "AsyncJsonWebsocketConsumer",
    "AsyncHttpConsumer",
}
GRAPHENE_BASES = {"ObjectType", "Mutation", "InputObjectType", "Interface", "ScalarType", "DjangoObjectType"}
STRAWBERRY_TYPE_DECS = {"type", "input", "interface", "enum"}
CACHE_METHODS = {"get", "set", "delete", "add", "get_or_set", "incr", "decr", "touch"}
FLAG_FUNCS = {
    "flag_is_active",
    "switch_is_active",
    "sample_is_active",
    "flag_enabled",
    "is_flag_enabled",
    "feature_enabled",
    "is_feature_enabled",
}
REL_FIELD_TYPES = {
    "ForeignKey",
    "OneToOneField",
    "ManyToManyField",
    "GenericForeignKey",
    "GenericRelation",
}
SIGNAL_NAMES = {
    "pre_save",
    "post_save",
    "pre_delete",
    "post_delete",
    "m2m_changed",
    "pre_init",
    "post_init",
    "class_prepared",
}
DESTRUCTIVE_MIGRATION_OPS = {"DeleteModel", "RemoveField", "AlterField", "RunPython", "RenameField"}
ON_DELETE_ATTRS = {"CASCADE", "PROTECT", "RESTRICT", "SET_NULL", "SET_DEFAULT", "DO_NOTHING", "SET"}


def _name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{}")
        return "".join(parts)
    return None


def _list_names(node: ast.AST | None) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        names = []
        for elt in node.elts:
            n = _name(elt)
            if n:
                names.append(n.split(".")[-1])
        return names
    n = _name(node)
    return [n.split(".")[-1]] if n else []


def _ann_class_names(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    if isinstance(node, ast.Name):
        return [node.id] if node.id[:1].isupper() else []
    if isinstance(node, ast.Attribute):
        n = _name(node)
        short = n.split(".")[-1] if n else ""
        return [short] if short[:1].isupper() else []
    if isinstance(node, ast.Subscript):
        return _ann_class_names(node.value) + _ann_class_names(node.slice)
    if isinstance(node, ast.Tuple):
        names: list[str] = []
        for elt in node.elts:
            names.extend(_ann_class_names(elt))
        return names
    if isinstance(node, ast.BinOp):
        return _ann_class_names(node.left) + _ann_class_names(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value[:1].isupper():
        return [node.value.split(".")[-1]]
    return []


def _looks_like_ninja_blob(imports: dict[str, str], from_imports: dict[str, str]) -> bool:
    blob = " ".join(imports.values()) + " " + " ".join(from_imports.values())
    return "ninja" in blob.lower()


def _bases(node: ast.ClassDef) -> list[str]:
    return [b for b in (_name(base) for base in node.bases) if b]


def _has_base(node: ast.ClassDef, names: set[str]) -> bool:
    return any((b.split(".")[-1] in names) for b in _bases(node))


def _decorator_names(node: ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef) -> list[str]:
    out = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            n = _name(dec.func)
        else:
            n = _name(dec)
        if n:
            out.append(n)
    return out


def _kw(call: ast.Call, key: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _truthy(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _bool_kw(call: ast.Call, key: str) -> bool | None:
    node = _kw(call, key)
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _int_kw(call: ast.Call, key: str) -> int | None:
    node = _kw(call, key)
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _doc_line(node: ast.AST) -> str | None:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    line = doc.strip().split("\n", 1)[0].strip()
    return line[:180] or None


def _with_doc(extra: dict, node: ast.AST) -> dict:
    doc = _doc_line(node)
    if doc:
        extra["doc"] = doc
    return extra


def _default_repr(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if node.value is None:
            return None
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, (int, float, bool)):
            return str(node.value)
        return None
    name = _name(node)
    return name.split(".")[-1] if name else None


def _field_constraints(call: ast.Call) -> dict:
    extra: dict = {}
    for key in ("null", "blank"):
        val = _bool_kw(call, key)
        if val is not None:
            extra[key] = val
    for key in ("primary_key", "auto_now", "auto_now_add"):
        if _bool_kw(call, key):
            extra[key] = True
    for key in ("max_length", "max_digits", "decimal_places"):
        val = _int_kw(call, key)
        if val is not None:
            extra[key] = val
    default = _default_repr(_kw(call, "default"))
    if default is not None:
        extra["default"] = default
    help_text = _const_str(_kw(call, "help_text"))
    if help_text:
        extra["help_text"] = help_text[:160]
    choices = _kw(call, "choices")
    if choices is not None:
        cname = _name(choices)
        if cname:
            extra["choices"] = cname.split(".")[-1]
    return extra


def strip_url_anchors(route: str) -> str:
    route = (route or "").strip()
    if route.startswith("include:"):
        return ""
    if route.startswith("^"):
        route = route[1:]
    if route.endswith("$") and not route.endswith("\\$"):
        route = route[:-1]
    return route


def _replace_named_groups(route: str) -> str:
    """Turn `(?P<slug>(?:[\\w-]+))` into `{slug}` without choking on nested groups."""
    out: list[str] = []
    i = 0
    n = len(route)
    while i < n:
        if route.startswith("(?P<", i):
            name_end = route.find(">", i + 4)
            if name_end != -1:
                name = route[i + 4 : name_end]
                k = name_end + 1
                depth = 1
                in_class = False
                while k < n and depth:
                    ch = route[k]
                    escaped = k > 0 and route[k - 1] == "\\"
                    if not escaped:
                        if in_class:
                            if ch == "]":
                                in_class = False
                        elif ch == "[":
                            in_class = True
                        elif ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                    k += 1
                if depth == 0:
                    out.append("{" + name + "}")
                    i = k
                    continue
        out.append(route[i])
        i += 1
    return "".join(out)


def pretty_url_pattern(route: str) -> str:
    """Turn `^$` / `(?P<slug>…)` into a graph-readable path fragment."""
    return strip_url_anchors(_replace_named_groups(route or ""))


def _app_from_path(rel: str) -> str | None:
    parts = list(Path(rel).parts)
    if parts and parts[-1].endswith(".py"):
        parts = parts[:-1]
    while len(parts) > 1 and parts[-1] in APP_PACKAGE_DIRS:
        parts.pop()
    return parts[-1] if parts else None


def _module_qual(rel: str) -> str:
    p = Path(rel)
    if p.suffix == ".py":
        p = p.with_suffix("")
    return ".".join(p.parts)


class DjangoExtractor(ast.NodeVisitor):
    def __init__(self, rel_path: str, source: str, config: LoadpathConfig) -> None:
        self.rel_path = rel_path.replace("\\", "/")
        self.source = source
        self.config = config
        self.app = _app_from_path(self.rel_path) or "unknown"
        self.context = config.context_for_django_app(self.app)
        self.graph = ExtractedGraph()
        self.imports: dict[str, str] = {}  # local name → module.qual
        self.from_imports: dict[str, str] = {}
        self.class_stack: list[str] = []

    def add_node(self, ntype: NodeType, name: str, qname: str, lineno: int, extra: dict | None = None) -> Node:
        node = Node(
            id=node_id(ntype, qname),
            type=ntype,
            name=name,
            qualified_name=qname,
            file_path=self.rel_path,
            start_line=lineno,
            context=self.context,
            extra=extra or {},
        )
        self.graph.nodes.append(node)
        return node

    def add_edge(self, src: str, dst: str, etype: EdgeType, confidence: float = 1.0, extra: dict | None = None) -> None:
        self.graph.edges.append(Edge(src=src, dst=dst, type=etype, confidence=confidence, extra=extra or {}))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name.split(".")[-1]] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            self.from_imports[local] = f"{mod}.{alias.name}" if mod else alias.name
        self.generic_visit(node)

    def _resolve(self, name: str) -> str:
        if name in self.from_imports:
            return self.from_imports[name]
        if name in self.imports:
            return self.imports[name]
        root = name.split(".")[0]
        if root in self.from_imports:
            return self.from_imports[root] + name[len(root) :]
        if root in self.imports:
            return self.imports[root] + name[len(root) :]
        return name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        if _has_base(node, MODEL_BASES):
            self._model(node)
        elif _has_base(node, SERIALIZER_BASES):
            self._serializer(node)
        elif _has_base(node, FORM_BASES) or (
            node.name.endswith("Form")
            and not node.name.startswith("Test")
            and not _has_base(node, {"TestCase", "SimpleTestCase", "TransactionTestCase", "LiveServerTestCase", "APITestCase"})
        ):
            self._serializer(node, ntype=NodeType.FORM)
        elif _has_base(node, FILTERSET_BASES) or node.name.endswith("FilterSet"):
            self._serializer(node, ntype=NodeType.FORM, filterset=True)
        elif _has_base(node, DJANGO_VIEW_BASES) or node.name.endswith(("View", "ViewSet")):
            self._view(node)
        elif any(b.split(".")[-1] in {"BaseCommand", "AppCommand", "LabelCommand"} for b in _bases(node)):
            self.add_node(
                NodeType.MANAGEMENT_COMMAND,
                node.name if node.name != "Command" else Path(self.rel_path).stem,
                f"{self.app}.{Path(self.rel_path).stem}",
                node.lineno,
                {"app": self.app},
            )
        elif self._task_class(node):
            pass
        elif _has_base(node, CONSUMER_BASES) or node.name.endswith("Consumer"):
            self._consumer(node)
        elif self._graphql_class(node):
            self._graphql_type(node)
        elif _has_base(node, {"BaseModel"}) and not _has_base(node, MODEL_BASES):
            self._pydantic_model(node)
        elif _has_base(node, NINJA_SCHEMA_BASES) and self._looks_like_ninja():
            self._pydantic_model(node, ninja=True)
        elif _has_base(node, ADMIN_BASES) or node.name.endswith("Admin"):
            self._admin(node)
        elif any(x.endswith("Config") for x in _bases(node)) or node.name.endswith("Config"):
            self._app_config(node)
        elif "Service" in node.name or "UseCase" in node.name:
            self._service_class(node)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._maybe_task(node)
        self._maybe_receiver(node)
        self._maybe_plain_signal_handler(node)
        self._maybe_command(node)
        self._maybe_test(node)
        self._maybe_service_fn(node)
        self._maybe_fbv(node)
        ninja = self._maybe_ninja(node)
        if not ninja:
            self._maybe_fastapi(node)
        self._maybe_graphql_operation(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        fname = _name(node.func) or ""
        short = fname.split(".")[-1]
        if short in {"path", "re_path", "url"}:
            self._url_path(node)
        elif short == "register" and "router" in fname.lower():
            self._router_register(node)
        elif short == "include":
            pass
        elif short == "get_model":
            self._get_model(node)
        elif short in CELERY_ENQUEUE:
            prefix = fname.rsplit(".", 1)[0] if "." in fname else ""
            if prefix and prefix.split(".")[-1] not in CELERY_CANVAS:
                self._enqueue(node, fname, broker="celery")
        elif short in CELERY_SIGNATURE and self._looks_like_celery(fname):
            self._enqueue(node, fname, broker="celery")
        elif short in CELERY_CANVAS and self._looks_like_celery(fname):
            self.graph.residuals.append(f"Celery canvas {fname}() at {self.rel_path}:{node.lineno}")
            self._enqueue_from_canvas(node)
        elif short == "send_task":
            self._send_task(node)
        elif short in DRAMATIQ_ENQUEUE and self._looks_like_dramatiq_send(fname):
            self._enqueue(node, fname, broker="dramatiq")
        elif short == "on_commit":
            self._side_effect_on_commit(node)
        elif short in CACHE_METHODS and self._looks_like_cache(fname):
            self._cache_call(node, fname, short)
        elif short in FLAG_FUNCS or self._looks_like_flag(fname):
            self._flag_call(node, fname)
        elif short in {"raw", "execute"} or (short == "extra" and _kw(node, "where")):
            self.graph.residuals.append(f"Raw SQL ({fname}) in {self.rel_path}:{node.lineno}")
        elif short in {"select_related", "prefetch_related"}:
            pass
        elif short == "connect":
            handler = node.args[0] if node.args else _kw(node, "receiver")
            stem = Path(self.rel_path).stem
            looks_signal = stem in {"apps", "signals", "signal_handlers", "handlers"} or any(
                token in fname.lower() for token in {n.lower() for n in SIGNAL_NAMES} | {"signal"}
            )
            if looks_signal and isinstance(handler, (ast.Name, ast.Attribute)):
                self._signal_connect(node, fname)
        elif short == "reverse":
            self._reverse(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"CELERY_BEAT_SCHEDULE", "beat_schedule"}:
                self._beat_schedule(node.value)
        self.generic_visit(node)

    def _model(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        model = self.add_node(
            NodeType.MODEL, node.name, qname, node.lineno, _with_doc({"app": self.app}, node)
        )
        app_node = self.add_node(NodeType.APP, self.app, self.app, 1)
        self.add_edge(model.id, app_node.id, EdgeType.BELONGS_TO)
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and stmt.targets and isinstance(stmt.targets[0], ast.Name):
                fname = stmt.targets[0].id
                if fname.startswith("_"):
                    continue
                field_q = f"{qname}.{fname}"
                extra: dict = {"app": self.app}
                rel_to = None
                on_delete = None
                if isinstance(stmt.value, ast.Call):
                    call_name = _name(stmt.value.func) or ""
                    extra["field_type"] = call_name.split(".")[-1]
                    extra["relation"] = extra["field_type"] in REL_FIELD_TYPES
                    to_arg = stmt.value.args[0] if stmt.value.args else _kw(stmt.value, "to")
                    rel_to = _const_str(to_arg) or _name(to_arg)
                    if isinstance(to_arg, ast.Constant) and isinstance(to_arg.value, str):
                        extra["string_ref"] = True
                        self.graph.residuals.append(
                            f'string model ref {to_arg.value} on {qname}.{fname} ({self.rel_path}:{stmt.lineno})'
                        )
                    od = _kw(stmt.value, "on_delete")
                    on_delete = _name(od)
                    extra["on_delete"] = on_delete.split(".")[-1] if on_delete else None
                    extra["related_name"] = _const_str(_kw(stmt.value, "related_name"))
                    extra["db_index"] = _truthy(_kw(stmt.value, "db_index"))
                    extra["unique"] = _truthy(_kw(stmt.value, "unique"))
                    extra.update(_field_constraints(stmt.value))
                field_node = self.add_node(NodeType.FIELD, fname, field_q, stmt.lineno, extra)
                self.add_edge(model.id, field_node.id, EdgeType.HAS_FIELD)
                if rel_to:
                    target = rel_to if "." in rel_to else f"{self.app}.{rel_to.split('.')[-1]}"
                    rel_id = node_id(NodeType.MODEL, target)
                    self.add_edge(
                        field_node.id,
                        rel_id,
                        EdgeType.RELATES_TO,
                        extra={"on_delete": extra.get("on_delete")},
                    )
                    if extra.get("on_delete") == "CASCADE":
                        self.add_edge(model.id, rel_id, EdgeType.RELATES_TO, extra={"cascade": True})

    def _serializer(
        self, node: ast.ClassDef, ntype: NodeType = NodeType.SERIALIZER, *, filterset: bool = False
    ) -> None:
        qname = f"{self.app}.{node.name}"
        extra: dict = {"app": self.app}
        if ntype is NodeType.FORM:
            extra["django_form"] = not filterset
            if filterset:
                extra["filterset"] = True
        ser = self.add_node(ntype, node.name, qname, node.lineno, _with_doc(extra, node))
        meta_model = None
        meta_fields: list[str] | None = None
        meta_exclude: list[str] | None = None
        declared: list[tuple[str, int]] = []
        queryset_in_serializer = False
        for stmt in node.body:
            if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                for m in stmt.body:
                    if isinstance(m, ast.Assign) and m.targets and isinstance(m.targets[0], ast.Name):
                        key = m.targets[0].id
                        if key == "model":
                            meta_model = _name(m.value)
                        elif key == "fields":
                            if isinstance(m.value, ast.Constant) and m.value.value == "__all__":
                                meta_fields = ["__all__"]
                            else:
                                meta_fields = [
                                    elt.value
                                    for elt in (m.value.elts if isinstance(m.value, (ast.List, ast.Tuple)) else [])
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                                ]
                        elif key == "exclude":
                            meta_exclude = [
                                elt.value
                                for elt in (m.value.elts if isinstance(m.value, (ast.List, ast.Tuple)) else [])
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]
            if isinstance(stmt, ast.Assign) and stmt.targets and isinstance(stmt.targets[0], ast.Name):
                fname = stmt.targets[0].id
                if not fname.startswith("_") and fname[0].islower():
                    declared.append((fname, stmt.lineno))
            if isinstance(stmt, ast.FunctionDef) and "queryset" in ast.dump(stmt):
                queryset_in_serializer = True
        nested_by_name = self._nested_serializer_fields(node)
        method_fields = self._method_field_names(node)
        to_repr_fields = self._to_representation_fields(node)
        body = self._slice(node)
        if queryset_in_serializer or ".objects." in body or "objects.filter" in body:
            ser.extra["queryset_in_serializer"] = True
        fields = declared[:]
        if meta_fields and meta_fields != ["__all__"]:
            existing = {n for n, _ in fields}
            for f in meta_fields:
                if f not in existing:
                    fields.append((f, node.lineno))
        existing_names = {n for n, _ in fields}
        for fname in to_repr_fields:
            if fname not in existing_names:
                fields.append((fname, node.lineno))
                existing_names.add(fname)
        for fname, lineno in fields:
            fq = f"{qname}.{fname}"
            field_extra: dict = {"app": self.app}
            nested = nested_by_name.get(fname)
            if nested:
                field_extra["nested_serializer"] = nested
            if fname in method_fields:
                field_extra["method_field"] = True
            if fname in to_repr_fields:
                field_extra["from_to_representation"] = True
            fn = self.add_node(NodeType.SERIALIZER_FIELD, fname, fq, lineno, field_extra)
            self.add_edge(ser.id, fn.id, EdgeType.HAS_FIELD)
            if nested:
                nested_q = nested if "." in nested else f"{self.app}.{nested.split('.')[-1]}"
                self.add_edge(fn.id, node_id(NodeType.SERIALIZER, nested_q), EdgeType.USES_SERIALIZER, extra={"nested": True})
                self.add_edge(ser.id, node_id(NodeType.SERIALIZER, nested_q), EdgeType.CALLS, extra={"nested": True})
            if meta_model:
                model_q = meta_model if "." in meta_model else f"{self.app}.{meta_model.split('.')[-1]}"
                self.add_edge(fn.id, node_id(NodeType.FIELD, f"{model_q}.{fname}"), EdgeType.SERIALIZES, confidence=0.85)
        if meta_model:
            model_q = meta_model if "." in meta_model else f"{self.app}.{meta_model.split('.')[-1]}"
            self.add_edge(ser.id, node_id(NodeType.MODEL, model_q), EdgeType.SERIALIZES)
        if meta_exclude:
            ser.extra["exclude"] = meta_exclude
        if nested_by_name:
            ser.extra["nested_serializers"] = sorted(set(nested_by_name.values()))
        if method_fields:
            ser.extra["method_fields"] = sorted(method_fields)
        if to_repr_fields:
            ser.extra["to_representation_fields"] = to_repr_fields
        elif any(isinstance(s, ast.FunctionDef) and s.name == "to_representation" for s in node.body):
            ser.extra["to_representation"] = True
            self.graph.residuals.append(
                f"to_representation on {qname} ({self.rel_path}:{node.lineno}) — published fields not parsed"
            )

    def _view(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        extra: dict = _with_doc({"app": self.app, "bases": _bases(node)}, node)
        serializer_class = None
        permissions: list[str] = []
        queryset_model = None
        dynamic_serializer = False
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and stmt.targets and isinstance(stmt.targets[0], ast.Name):
                key = stmt.targets[0].id
                if key == "serializer_class":
                    serializer_class = _name(stmt.value)
                elif key == "permission_classes":
                    permissions = _list_names(stmt.value)
                elif key == "throttle_classes":
                    extra["throttles"] = _list_names(stmt.value)
                elif key == "queryset":
                    dumped = ast.dump(stmt.value)
                    m = re.search(r"id='([A-Z][A-Za-z0-9_]+)'", dumped)
                    if m:
                        queryset_model = m.group(1)
                elif key == "filterset_class":
                    extra["filterset"] = _name(stmt.value)
                elif key == "authentication_classes":
                    extra["authentication"] = _list_names(stmt.value)
                elif key == "pagination_class":
                    extra["pagination"] = _name(stmt.value)
                elif key == "template_name":
                    extra["template"] = _const_str(stmt.value)
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "get_queryset":
                extra["get_queryset"] = True
                dumped = ast.dump(stmt)
                m = re.search(r"id='([A-Z][A-Za-z0-9_]+)'", dumped)
                if m and not queryset_model:
                    queryset_model = m.group(1)
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "get_serializer_class":
                dynamic_serializer = True
                extra["get_serializer_class"] = True
                resolved = self._serializer_names_in(stmt)
                extra["serializer_classes"] = resolved
                if resolved:
                    extra["get_serializer_class_resolved"] = True
                else:
                    self.graph.residuals.append(
                        f"Dynamic get_serializer_class on {qname} ({self.rel_path}:{stmt.lineno})"
                    )
            if isinstance(stmt, ast.FunctionDef) and stmt.name in {
                "list",
                "create",
                "retrieve",
                "update",
                "partial_update",
                "destroy",
            }:
                action_q = f"{qname}.{stmt.name}"
                action = self.add_node(
                    NodeType.VIEWSET_ACTION, stmt.name, action_q, stmt.lineno, {"app": self.app}
                )
                self.add_edge(node_id(NodeType.VIEW, qname), action.id, EdgeType.CALLS)
        extra["permissions"] = permissions
        view = self.add_node(NodeType.VIEW, node.name, qname, node.lineno, extra)
        if serializer_class:
            ser_q = (
                serializer_class
                if "." in serializer_class and not serializer_class.startswith("serializers")
                else f"{self.app}.{serializer_class.split('.')[-1]}"
            )
            self.add_edge(view.id, node_id(NodeType.SERIALIZER, ser_q), EdgeType.USES_SERIALIZER)
        for name in extra.get("serializer_classes") or []:
            ser_q = name if "." in name and not name.startswith("serializers") else f"{self.app}.{name.split('.')[-1]}"
            self.add_edge(
                view.id,
                node_id(NodeType.SERIALIZER, ser_q),
                EdgeType.USES_SERIALIZER,
                extra={"from": "get_serializer_class"},
            )
        if extra.get("filterset") and extra["filterset"] not in {True, False}:
            fs = str(extra["filterset"])
            fs_q = fs if "." in fs and not fs.startswith("filter") else f"{self.app}.{fs.split('.')[-1]}"
            self.add_edge(view.id, node_id(NodeType.FORM, fs_q), EdgeType.CALLS, confidence=0.9)
        for perm in permissions:
            pid = node_id(NodeType.PERMISSION, perm)
            self.graph.nodes.append(
                Node(id=pid, type=NodeType.PERMISSION, name=perm, qualified_name=perm, extra={"from_view": qname})
            )
            self.add_edge(view.id, pid, EdgeType.HAS_PERMISSION)
        for throttle in extra.get("throttles") or []:
            tid = node_id(NodeType.THROTTLE, throttle)
            self.graph.nodes.append(
                Node(
                    id=tid,
                    type=NodeType.THROTTLE,
                    name=throttle,
                    qualified_name=throttle,
                    extra={"from_view": qname},
                )
            )
            self.add_edge(view.id, tid, EdgeType.HAS_PERMISSION)
        if extra.get("pagination"):
            extra["pagination_sink"] = True
        if extra.get("template"):
            tmpl = extra["template"]
            tn = self.add_node(NodeType.TEMPLATE, Path(tmpl).name, tmpl, node.lineno, {"app": self.app})
            self.add_edge(view.id, tn.id, EdgeType.SERVES_TEMPLATE)
        if queryset_model:
            self.add_edge(
                view.id,
                node_id(NodeType.MODEL, f"{self.app}.{queryset_model}"),
                EdgeType.QUERIES_MODEL,
            )
        if dynamic_serializer:
            extra["dynamic"] = True
        # foreign model imports used in this view file
        self._note_cross_app_model_imports(view.id)

    def _note_cross_app_model_imports(self, view_id: str) -> None:
        for local, target in self.from_imports.items():
            # accounts.models.UserProfile
            parts = target.split(".")
            if "models" in parts:
                idx = parts.index("models")
                app = parts[idx - 1] if idx > 0 else None
                model = parts[idx + 1] if idx + 1 < len(parts) else local
                if app and app != self.app and model[:1].isupper():
                    self.add_edge(
                        view_id,
                        node_id(NodeType.MODEL, f"{app}.{model}"),
                        EdgeType.QUERIES_MODEL,
                        extra={"imported": True, "foreign_app": app},
                    )

    def _admin(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        self.add_node(NodeType.ADMIN, node.name, qname, node.lineno, _with_doc({"app": self.app}, node))

    def _service_class(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        self.add_node(NodeType.SERVICE, node.name, qname, node.lineno, _with_doc({"app": self.app}, node))

    def _maybe_service_fn(self, node: ast.FunctionDef) -> None:
        if Path(self.rel_path).name in {"services.py", "use_cases.py", "usecases.py"}:
            qname = f"{self.app}.{node.name}"
            self.add_node(NodeType.SERVICE, node.name, qname, node.lineno, _with_doc({"app": self.app}, node))

    def _app_config(self, node: ast.ClassDef) -> None:
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "ready":
                text = self._slice(stmt)
                if "import" in text or "connect" in text or "receiver" in text:
                    self.graph.residuals.append(
                        f"Signal/import registration in AppConfig.ready() {self.rel_path}:{stmt.lineno}"
                    )

    def _maybe_task(self, node: ast.FunctionDef) -> None:
        decs = _decorator_names(node)
        broker = None
        if any("dramatiq" in d or d.split(".")[-1] in DRAMATIQ_DECORATORS for d in decs):
            broker = "dramatiq"
        elif any("celery" in d or d.split(".")[-1] in CELERY_DECORATORS for d in decs):
            broker = "celery"
        elif "tasks.py" in self.rel_path or "actors.py" in self.rel_path:
            if node.name.endswith("task") or "task" in node.name or "actors.py" in self.rel_path:
                broker = "dramatiq" if "actors.py" in self.rel_path else "celery"
        if broker is None:
            return
        qname = f"{self.app}.{node.name}"
        args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
        extra = _with_doc(
            {
                "app": self.app,
                "args": args,
                "broker": broker,
                "decorators": decs,
            },
            node,
        )
        extra["looks_idempotent_on_pk"] = _looks_idempotent(args)
        self.add_node(NodeType.TASK, node.name, qname, node.lineno, extra)

    def _task_class(self, node: ast.ClassDef) -> bool:
        bases = _bases(node)
        shorts = {b.split(".")[-1] for b in bases}
        blob = " ".join(self.imports.values()) + " " + " ".join(self.from_imports.values())
        broker = None
        if shorts & DRAMATIQ_TASK_BASES or any("dramatiq" in b.lower() for b in bases):
            broker = "dramatiq"
        elif shorts & CELERY_TASK_BASES and (
            "celery" in blob.lower() or any("celery" in b.lower() for b in bases)
        ):
            broker = "celery"
        if broker is None:
            return False
        run = next(
            (
                stmt
                for stmt in node.body
                if isinstance(stmt, ast.FunctionDef) and stmt.name in {"run", "perform"}
            ),
            None,
        )
        args = [a.arg for a in run.args.args if a.arg not in {"self", "cls"}] if run else []
        self.add_node(
            NodeType.TASK,
            node.name,
            f"{self.app}.{node.name}",
            node.lineno,
            {
                "app": self.app,
                "args": args,
                "broker": broker,
                "task_class": True,
                "looks_idempotent_on_pk": _looks_idempotent(args),
            },
        )
        return True

    def _looks_like_celery(self, fname: str) -> bool:
        blob = " ".join(self.imports.values()) + " " + " ".join(self.from_imports.values()) + " " + self.source[:800]
        if "celery" in blob.lower() or "tasks.py" in self.rel_path:
            return True
        root = fname.split(".")[0]
        target = self.from_imports.get(root, self.imports.get(root, ""))
        return any(part in target for part in ("tasks", "celery", "actors"))

    def _looks_like_dramatiq_send(self, fname: str) -> bool:
        blob = " ".join(self.imports.values()) + " " + " ".join(self.from_imports.values()) + " " + self.source[:400]
        if "dramatiq" in blob:
            return True
        root = fname.split(".")[0]
        target = self.from_imports.get(root, self.imports.get(root, ""))
        return any(part in target for part in ("actors", "tasks", "dramatiq"))

    def _enqueue(self, node: ast.Call, fname: str, broker: str = "celery") -> None:
        app, short, qname = self._task_qname(fname)
        owner = self.class_stack[-1] if self.class_stack else Path(self.rel_path).stem
        owner_type = NodeType.VIEW
        if "management/commands" in self.rel_path:
            owner_type = NodeType.MANAGEMENT_COMMAND
            owner = Path(self.rel_path).stem
        elif owner.endswith("Serializer"):
            owner_type = NodeType.SERIALIZER
        elif "Service" in owner or owner.endswith("UseCase"):
            owner_type = NodeType.SERVICE
        self.add_edge(
            node_id(owner_type, f"{self.app}.{owner}"),
            node_id(NodeType.TASK, qname),
            EdgeType.ENQUEUES,
            confidence=0.9,
            extra={"call": fname, "line": node.lineno, "broker": broker},
        )
        self.add_node(
            NodeType.TASK,
            short,
            qname,
            node.lineno,
            {"referenced": True, "app": app, "broker": broker},
        )

    def _task_qname(self, fname: str) -> tuple[str, str, str]:
        task_name = fname.rsplit(".", 1)[0] if "." in fname else fname
        resolved = self._resolve(task_name)
        parts = [p for p in resolved.split(".") if p]
        short = parts[-1] if parts else task_name.split(".")[-1]
        app = self.app
        for marker in ("tasks", "actors", "jobs"):
            if marker in parts:
                idx = parts.index(marker)
                if idx > 0:
                    app = parts[idx - 1]
                    break
        return app, short, f"{app}.{short}"

    def _enqueue_from_canvas(self, node: ast.Call) -> None:
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for child in ast.walk(arg):
                if not isinstance(child, ast.Call):
                    continue
                fname = _name(child.func) or ""
                short = fname.split(".")[-1]
                if short in CELERY_ENQUEUE or short in CELERY_SIGNATURE:
                    self._enqueue(child, fname, broker="celery")
                elif short in DRAMATIQ_ENQUEUE:
                    self._enqueue(child, fname, broker="dramatiq")

    def _enqueue_from_on_commit(self, node: ast.Call) -> None:
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for child in ast.walk(arg):
                if isinstance(child, ast.Call):
                    fname = _name(child.func) or ""
                    short = fname.split(".")[-1]
                    if short in CELERY_ENQUEUE:
                        self._enqueue(child, fname, broker="celery")
                    elif short in DRAMATIQ_ENQUEUE:
                        self._enqueue(child, fname, broker="dramatiq")

    def _send_task(self, node: ast.Call) -> None:
        name = _const_str(node.args[0]) if node.args else None
        self.graph.residuals.append(
            f'celery.send_task("{name or "?"}") at {self.rel_path}:{node.lineno}'
        )
        if not name:
            return
        short = name.split(".")[-1]
        app = name.split(".")[0] if "." in name else self.app
        qname = f"{app}.{short}"
        owner = self.class_stack[-1] if self.class_stack else Path(self.rel_path).stem
        owner_type = NodeType.VIEW
        if "management/commands" in self.rel_path:
            owner_type = NodeType.MANAGEMENT_COMMAND
            owner = Path(self.rel_path).stem
        self.add_edge(
            node_id(owner_type, f"{self.app}.{owner}"),
            node_id(NodeType.TASK, qname),
            EdgeType.ENQUEUES,
            confidence=0.7,
            extra={"call": "send_task", "line": node.lineno, "broker": "celery", "task": name},
        )
        self.add_node(
            NodeType.TASK,
            short,
            qname,
            node.lineno,
            {"referenced": True, "app": app, "broker": "celery", "via": "send_task"},
        )

    def _beat_schedule(self, value: ast.AST) -> None:
        if not isinstance(value, ast.Dict):
            return
        for key, val in zip(value.keys, value.values, strict=True):
            entry_name = _const_str(key) or _name(key) or "beat"
            task_name = None
            if isinstance(val, ast.Dict):
                for k, v in zip(val.keys, val.values, strict=True):
                    label = _const_str(k) or _name(k)
                    if label == "task":
                        task_name = _const_str(v) or _name(v)
            if not task_name:
                continue
            parts = task_name.split(".")
            short = parts[-1]
            app = parts[0] if len(parts) > 1 else self.app
            qname = f"{app}.{short}"
            self.add_node(
                NodeType.TASK,
                short,
                qname,
                getattr(value, "lineno", 1),
                {
                    "referenced": True,
                    "app": app,
                    "broker": "celery",
                    "beat": True,
                    "schedule_name": entry_name,
                },
            )
            self.graph.residuals.append(
                f"Celery beat '{entry_name}' → {task_name} ({self.rel_path})"
            )

    def _maybe_fbv(self, node: ast.FunctionDef) -> None:
        decs = _decorator_names(node)
        if not any(d.split(".")[-1] in {"api_view", "csrf_exempt", "login_required", "permission_required", "require_GET", "require_POST"} for d in decs):
            return
        if node.name in {"get", "post", "put", "patch", "delete", "handle"}:
            return
        qname = f"{self.app}.{node.name}"
        extra = _with_doc({"app": self.app, "fbv": True, "decorators": decs}, node)
        view = self.add_node(NodeType.VIEW, node.name, qname, node.lineno, extra)
        self._note_cross_app_model_imports(view.id)
        self._link_model_queries(view.id, node)

    def _maybe_ninja(self, node: ast.FunctionDef) -> bool:
        hit = False
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fname = _name(dec.func) or ""
            short = fname.split(".")[-1]
            if short not in NINJA_HTTP:
                continue
            if not any(tok in fname.lower() for tok in ("api", "router", "ninja")):
                continue
            hit = True
            route = _const_str(dec.args[0]) if dec.args else None
            qname = f"{self.app}.{node.name}"
            view = self.add_node(
                NodeType.VIEW,
                node.name,
                qname,
                node.lineno,
                _with_doc({"app": self.app, "ninja": True, "method": short.upper()}, node),
            )
            if route:
                rn = self.add_node(
                    NodeType.ROUTE,
                    route,
                    f"{self.app}:{route}",
                    node.lineno,
                    {"app": self.app, "route": route, "ninja": True, "method": short.upper()},
                )
                self.add_edge(rn.id, view.id, EdgeType.PUBLISHES_ROUTE)
            for schema_name in self._ninja_response_schemas(node, dec):
                schema_q = f"{self.app}.{schema_name.split('.')[-1]}"
                self.add_edge(
                    view.id,
                    node_id(NodeType.PYDANTIC_MODEL, schema_q),
                    EdgeType.USES_SERIALIZER,
                    extra={"ninja_schema": True},
                )
                if route:
                    self.add_edge(
                        rn.id,
                        node_id(NodeType.PYDANTIC_MODEL, schema_q),
                        EdgeType.USES_SERIALIZER,
                        extra={"ninja_schema": True},
                    )
        return hit

    def _owner_id(self) -> tuple[NodeType, str]:
        owner = self.class_stack[-1] if self.class_stack else Path(self.rel_path).stem
        owner_type = NodeType.VIEW
        if "management/commands" in self.rel_path:
            owner_type = NodeType.MANAGEMENT_COMMAND
            owner = Path(self.rel_path).stem
        elif Path(self.rel_path).name in {"tasks.py", "actors.py"}:
            owner_type = NodeType.TASK
        elif Path(self.rel_path).name in {"services.py", "use_cases.py"}:
            owner_type = NodeType.SERVICE
        return owner_type, f"{self.app}.{owner}"

    def _maybe_fastapi(self, node: ast.FunctionDef) -> None:
        blob = " ".join(self.imports.values()) + " " + " ".join(self.from_imports.values())
        if "fastapi" not in blob.lower():
            return
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fname = _name(dec.func) or ""
            short = fname.split(".")[-1]
            if short not in FASTAPI_HTTP:
                continue
            route = _const_str(dec.args[0]) if dec.args else None
            if not route:
                continue
            qname = f"{self.app}.{node.name}"
            extra = _with_doc(
                {
                    "app": self.app,
                    "fastapi": True,
                    "method": "WS" if short == "websocket" else short.upper(),
                    "route": route,
                },
                node,
            )
            view = self.add_node(NodeType.VIEW, node.name, qname, node.lineno, extra)
            rn = self.add_node(
                NodeType.FASTAPI_ROUTE,
                f"{extra['method']} {route}",
                f"{self.app}:{extra['method']} {route}",
                node.lineno,
                extra,
            )
            self.add_edge(rn.id, view.id, EdgeType.PUBLISHES_ROUTE)
            self._link_model_queries(view.id, node)
            response_model = _name(_kw(dec, "response_model"))
            if response_model:
                self.add_edge(
                    rn.id,
                    node_id(NodeType.PYDANTIC_MODEL, f"{self.app}.{response_model.split('.')[-1]}"),
                    EdgeType.USES_SERIALIZER,
                    confidence=0.85,
                )

    def _graphql_class(self, node: ast.ClassDef) -> bool:
        decs = _decorator_names(node)
        if any("strawberry" in d.lower() and d.split(".")[-1] in STRAWBERRY_TYPE_DECS | {"type"} for d in decs):
            return True
        bases = {b.split(".")[-1] for b in _bases(node)}
        if not (bases & GRAPHENE_BASES):
            return False
        blob = " ".join(self.imports.values()) + " " + " ".join(self.from_imports.values())
        return any(tok in blob.lower() for tok in ("graphene", "strawberry", "graphql"))

    def _graphql_type(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        kind = "type"
        for d in _decorator_names(node):
            if "strawberry" in d.lower():
                kind = d.split(".")[-1]
                break
        bases = {b.split(".")[-1] for b in _bases(node)}
        if "Mutation" in bases:
            kind = "mutation"
        extra = _with_doc({"app": self.app, "kind": kind, "graphql": True}, node)
        gql = self.add_node(NodeType.GRAPHQL_TYPE, node.name, qname, node.lineno, extra)
        root = node.name in {"Query", "Mutation", "Subscription"} or kind == "mutation"
        for stmt in node.body:
            fname = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fname = stmt.target.id
            elif isinstance(stmt, ast.Assign) and stmt.targets and isinstance(stmt.targets[0], ast.Name):
                cand = stmt.targets[0].id
                if not cand.startswith("_") and cand not in {"Meta"}:
                    fname = cand
            elif isinstance(stmt, ast.FunctionDef) and stmt.name == "mutate":
                op = self.add_node(
                    NodeType.GRAPHQL_OPERATION,
                    node.name,
                    f"graphql.{node.name}",
                    stmt.lineno,
                    {"app": self.app, "kind": "mutation"},
                )
                self.add_edge(gql.id, op.id, EdgeType.PUBLISHES_GRAPHQL)
                self._link_model_queries(op.id, stmt)
            if not fname:
                continue
            field = self.add_node(
                NodeType.GRAPHQL_FIELD,
                fname,
                f"{qname}.{fname}",
                stmt.lineno,
                {"app": self.app},
            )
            self.add_edge(gql.id, field.id, EdgeType.HAS_FIELD)
            extra.setdefault("fields", []).append(fname)
            if root and not any(
                n.type is NodeType.GRAPHQL_OPERATION and n.name == fname for n in self.graph.nodes
            ):
                op_kind = (
                    "query"
                    if node.name == "Query"
                    else ("subscription" if node.name == "Subscription" else "mutation")
                )
                op = self.add_node(
                    NodeType.GRAPHQL_OPERATION,
                    fname,
                    f"graphql.{fname}",
                    stmt.lineno,
                    {"app": self.app, "kind": op_kind},
                )
                self.add_edge(gql.id, op.id, EdgeType.PUBLISHES_GRAPHQL)
        if kind == "mutation" or node.name in {"Query", "Mutation", "Subscription"}:
            op_kind = "query" if node.name == "Query" else ("subscription" if node.name == "Subscription" else "mutation")
            if not any(n.type is NodeType.GRAPHQL_OPERATION and n.name == node.name for n in self.graph.nodes):
                op = self.add_node(
                    NodeType.GRAPHQL_OPERATION,
                    node.name,
                    f"graphql.{node.name}",
                    node.lineno,
                    {"app": self.app, "kind": op_kind},
                )
                self.add_edge(gql.id, op.id, EdgeType.PUBLISHES_GRAPHQL)

    def _maybe_graphql_operation(self, node: ast.FunctionDef) -> None:
        for dec in node.decorator_list:
            dname = _name(dec.func if isinstance(dec, ast.Call) else dec) or ""
            if "strawberry" not in dname.lower():
                continue
            short = dname.split(".")[-1]
            if short not in {"mutation", "field", "subscription"}:
                continue
            kind = "query" if short == "field" else short
            op = self.add_node(
                NodeType.GRAPHQL_OPERATION,
                node.name,
                f"graphql.{node.name}",
                node.lineno,
                {"app": self.app, "kind": kind, "strawberry": True},
            )
            self._link_model_queries(op.id, node)
            if self.class_stack:
                self.add_edge(
                    node_id(NodeType.GRAPHQL_TYPE, f"{self.app}.{self.class_stack[-1]}"),
                    op.id,
                    EdgeType.PUBLISHES_GRAPHQL,
                )

    def _pydantic_model(self, node: ast.ClassDef, *, ninja: bool = False) -> None:
        qname = f"{self.app}.{node.name}"
        extra: dict = _with_doc({"app": self.app, "pydantic": True, "ninja_schema": ninja}, node)
        meta_fields: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                for m in stmt.body:
                    if isinstance(m, ast.Assign) and m.targets and isinstance(m.targets[0], ast.Name) and m.targets[0].id == "fields":
                        if isinstance(m.value, (ast.List, ast.Tuple)):
                            meta_fields = [
                                elt.value
                                for elt in m.value.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]
        extra["fields"] = []
        model = self.add_node(NodeType.PYDANTIC_MODEL, node.name, qname, node.lineno, extra)
        seen: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fname = stmt.target.id
                if fname.startswith("_") or fname in seen:
                    continue
                seen.add(fname)
                extra["fields"].append(fname)
                field = self.add_node(
                    NodeType.SERIALIZER_FIELD,
                    fname,
                    f"{qname}.{fname}",
                    stmt.lineno,
                    {"app": self.app, "pydantic": True, "ninja_schema": ninja},
                )
                self.add_edge(model.id, field.id, EdgeType.HAS_FIELD)
                for nested in _ann_class_names(stmt.annotation):
                    if nested in {"Optional", "List", "Dict", "Union", "Any", "Schema", "BaseModel", node.name}:
                        continue
                    self.add_edge(
                        field.id,
                        node_id(NodeType.PYDANTIC_MODEL, f"{self.app}.{nested}"),
                        EdgeType.USES_SERIALIZER,
                        extra={"nested": True},
                    )
                    self.add_edge(
                        model.id,
                        node_id(NodeType.PYDANTIC_MODEL, f"{self.app}.{nested}"),
                        EdgeType.CALLS,
                        extra={"nested": True},
                    )
        for fname in meta_fields:
            if fname in seen:
                continue
            seen.add(fname)
            extra["fields"].append(fname)
            field = self.add_node(
                NodeType.SERIALIZER_FIELD,
                fname,
                f"{qname}.{fname}",
                node.lineno,
                {"app": self.app, "pydantic": True, "ninja_schema": ninja},
            )
            self.add_edge(model.id, field.id, EdgeType.HAS_FIELD)

    def _looks_like_ninja(self) -> bool:
        return _looks_like_ninja_blob(self.imports, self.from_imports)

    def _ninja_response_schemas(self, node: ast.FunctionDef, dec: ast.Call) -> list[str]:
        names = _ann_class_names(node.returns)
        names.extend(_ann_class_names(_kw(dec, "response")))
        resp = _kw(dec, "response")
        if isinstance(resp, ast.Dict):
            for val in resp.values:
                names.extend(_ann_class_names(val))
        skip = {
            "dict",
            "list",
            "Dict",
            "List",
            "Any",
            "None",
            "int",
            "str",
            "bool",
            "float",
            "Optional",
            "Union",
            "HttpResponse",
            "HttpRequest",
        }
        out: list[str] = []
        seen: set[str] = set()
        for name in names:
            short = name.split(".")[-1]
            if short in skip or short in seen or not short[:1].isupper():
                continue
            seen.add(short)
            out.append(short)
        return out

    def _nested_serializer_fields(self, node: ast.ClassDef) -> dict[str, str]:
        found: dict[str, str] = {}
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or not stmt.targets or not isinstance(stmt.targets[0], ast.Name):
                continue
            fname = stmt.targets[0].id
            call = stmt.value if isinstance(stmt.value, ast.Call) else None
            raw = _name(call.func if call else stmt.value)
            if not raw:
                continue
            short = raw.split(".")[-1]
            if short.endswith("Serializer") and short not in SERIALIZER_BASES:
                found[fname] = short
        return found

    def _method_field_names(self, node: ast.ClassDef) -> set[str]:
        names: set[str] = set()
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or not stmt.targets or not isinstance(stmt.targets[0], ast.Name):
                continue
            call = stmt.value if isinstance(stmt.value, ast.Call) else None
            raw = _name(call.func if call else None) or ""
            if raw.split(".")[-1] == "SerializerMethodField":
                names.add(stmt.targets[0].id)
        return names

    def _to_representation_fields(self, node: ast.ClassDef) -> list[str]:
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "to_representation":
                keys: list[str] = []
                seen: set[str] = set()
                for child in ast.walk(stmt):
                    if not isinstance(child, ast.Return) or not isinstance(child.value, ast.Dict):
                        continue
                    for key in child.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            if key.value not in seen:
                                seen.add(key.value)
                                keys.append(key.value)
                return keys
        return []

    def _serializer_names_in(self, node: ast.AST) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for child in ast.walk(node):
            candidates: list[str] = []
            if isinstance(child, ast.Return) and child.value is not None:
                n = _name(child.value)
                if n:
                    candidates.append(n)
                if isinstance(child.value, ast.Dict):
                    for val in child.value.values:
                        vn = _name(val)
                        if vn:
                            candidates.append(vn)
            if isinstance(child, ast.Dict):
                for val in child.values:
                    vn = _name(val)
                    if vn:
                        candidates.append(vn)
            for n in candidates:
                short = n.split(".")[-1]
                if short.endswith("Serializer") and short not in SERIALIZER_BASES and short not in seen:
                    seen.add(short)
                    names.append(short)
        return names

    def _consumer(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        extra = _with_doc({"app": self.app, "bases": _bases(node), "websocket": True}, node)
        consumer = self.add_node(NodeType.CONSUMER, node.name, qname, node.lineno, extra)
        self._link_model_queries(consumer.id, node)

    def _link_model_queries(self, owner_id: str, node: ast.AST) -> None:
        seen: set[str] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Attribute) or child.attr != "objects":
                continue
            model = _name(child.value)
            if not model:
                continue
            short = model.split(".")[-1]
            if not short[:1].isupper():
                continue
            app = self.app
            head = model.split(".")[0]
            target = self.from_imports.get(head) or self.imports.get(head) or ""
            if "models" in target.split("."):
                parts = target.split(".")
                if "models" in parts:
                    idx = parts.index("models")
                    if idx > 0 and parts[idx - 1] not in {"django", "db"}:
                        app = parts[idx - 1]
            key = f"{app}.{short}"
            if key in seen:
                continue
            seen.add(key)
            self.add_edge(
                owner_id,
                node_id(NodeType.MODEL, key),
                EdgeType.QUERIES_MODEL,
                confidence=0.8,
            )

    def _looks_like_cache(self, fname: str) -> bool:
        low = fname.lower()
        return "cache" in low or low.startswith("caches[")

    def _looks_like_flag(self, fname: str) -> bool:
        low = fname.lower()
        if fname.split(".")[-1] not in FLAG_FUNCS | {"is_active", "is_enabled"}:
            return False
        return any(tok in low for tok in ("flag", "waffle", "feature", "unleash", "flags"))

    def _cache_call(self, node: ast.Call, fname: str, method: str) -> None:
        key = _const_str(node.args[0]) if node.args else None
        if not key:
            return
        qname = f"cache:{key}"
        cache = self.add_node(
            NodeType.CACHE_KEY,
            key,
            qname,
            node.lineno,
            {"app": self.app, "method": method},
        )
        owner_type, owner_q = self._owner_id()
        etype = EdgeType.INVALIDATES_CACHE if method in {"set", "delete", "add"} else EdgeType.CALLS
        self.add_edge(node_id(owner_type, owner_q), cache.id, etype, extra={"call": fname, "line": node.lineno})

    def _flag_call(self, node: ast.Call, fname: str) -> None:
        name = None
        for arg in node.args:
            name = _const_str(arg)
            if name:
                break
        if not name:
            name = _const_str(_kw(node, "name") or _kw(node, "flag") or _kw(node, "key"))
        if not name:
            return
        flag = self.add_node(
            NodeType.FEATURE_FLAG,
            name,
            f"flag:{name}",
            node.lineno,
            {"app": self.app, "call": fname},
        )
        owner_type, owner_q = self._owner_id()
        self.add_edge(node_id(owner_type, owner_q), flag.id, EdgeType.CHECKS_FLAG, extra={"line": node.lineno})

    def _side_effect_on_commit(self, node: ast.Call) -> None:
        self.graph.residuals.append(
            f"transaction.on_commit() at {self.rel_path}:{node.lineno} — async work may be hidden in a lambda"
        )
        owner_type, owner_q = self._owner_id()
        effect = self.add_node(
            NodeType.SIDE_EFFECT,
            "on_commit",
            f"{owner_q}:on_commit:{node.lineno}",
            node.lineno,
            {"app": self.app, "kind": "on_commit"},
        )
        self.add_edge(node_id(owner_type, owner_q), effect.id, EdgeType.ON_COMMIT, extra={"line": node.lineno})
        self._enqueue_from_on_commit(node)

    def _maybe_receiver(self, node: ast.FunctionDef) -> None:
        for dec in node.decorator_list:
            dname = _name(dec.func if isinstance(dec, ast.Call) else dec) or ""
            if dname.split(".")[-1] != "receiver":
                continue
            sender = None
            signal = None
            if isinstance(dec, ast.Call):
                if dec.args:
                    signal = _name(dec.args[0])
                sender_node = _kw(dec, "sender")
                sender = _name(sender_node)
            qname = f"{self.app}.{node.name}"
            extra = _with_doc({"app": self.app, "signal": signal, "sender": sender}, node)
            recv = self.add_node(NodeType.RECEIVER, node.name, qname, node.lineno, extra)
            if signal:
                sig_id = node_id(NodeType.SIGNAL, signal.split(".")[-1])
                self.graph.nodes.append(
                    Node(
                        id=sig_id,
                        type=NodeType.SIGNAL,
                        name=signal.split(".")[-1],
                        qualified_name=signal.split(".")[-1],
                    )
                )
                self.add_edge(sig_id, recv.id, EdgeType.RECEIVES)
            if sender:
                model_q = sender if "." in sender else f"{self.app}.{sender.split('.')[-1]}"
                self.add_edge(recv.id, node_id(NodeType.MODEL, model_q), EdgeType.EMITS_SIGNAL)

    def _maybe_plain_signal_handler(self, node: ast.FunctionDef) -> None:
        if self.class_stack:
            return
        if Path(self.rel_path).stem not in {"signals", "signal_handlers", "handlers"}:
            return
        for dec in node.decorator_list:
            dname = _name(dec.func if isinstance(dec, ast.Call) else dec) or ""
            if dname.split(".")[-1] == "receiver":
                return
        args = [a.arg for a in node.args.args]
        if not (node.args.kwarg or "instance" in args or "sender" in args):
            return
        qname = f"{self.app}.{node.name}"
        self.add_node(
            NodeType.RECEIVER,
            node.name,
            qname,
            node.lineno,
            {"app": self.app, "plain_handler": True},
        )

    def _maybe_command(self, node: ast.FunctionDef) -> None:
        if "management/commands" in self.rel_path and node.name == "handle":
            cmd = Path(self.rel_path).stem
            self.add_node(NodeType.MANAGEMENT_COMMAND, cmd, f"{self.app}.{cmd}", node.lineno, {"app": self.app})

    def _maybe_test(self, node: ast.FunctionDef) -> None:
        is_test_file = (
            Path(self.rel_path).name.startswith("test")
            or "/tests/" in f"/{self.rel_path}/"
            or Path(self.rel_path).name == "tests.py"
        )
        if not is_test_file:
            return
        if not (node.name.startswith("test_") or node.name.startswith("test")):
            return
        qname = f"{self.app}.{node.name}"
        extra = {"app": self.app, "nodeid": f"{self.rel_path}::{node.name}"}
        mentions: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                mentions.add(child.value)
            elif isinstance(child, ast.Attribute):
                mentions.add(child.attr)
        extra["mentions"] = sorted(mentions)
        test = self.add_node(NodeType.TEST, node.name, qname, node.lineno, extra)
        # crude: referenced class names in the test become tested_by
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id[:1].isupper():
                for ntype in (NodeType.SERIALIZER, NodeType.FORM, NodeType.VIEW, NodeType.MODEL, NodeType.SERVICE, NodeType.RECEIVER):
                    self.add_edge(
                        node_id(ntype, f"{self.app}.{child.id}"),
                        test.id,
                        EdgeType.TESTED_BY,
                        confidence=0.7,
                    )

    def _include_target(self, call: ast.Call) -> str | None:
        if not call.args:
            return None
        arg0 = call.args[0]
        hit = _const_str(arg0) or _name(arg0)
        if hit:
            return hit
        if isinstance(arg0, (ast.Tuple, ast.List)) and arg0.elts:
            return _const_str(arg0.elts[0]) or _name(arg0.elts[0])
        return None

    def _route_identity(
        self, route: str, include_mod: str | None, name: str | None, lineno: int
    ) -> tuple[str, str]:
        """Empty `path("")` / `re_path(r"^$")` must still show a label and a unique id."""
        stamp = f"{Path(self.rel_path).name}:{lineno}"
        pretty = pretty_url_pattern(route)
        if pretty:
            return pretty, f"{self.app}:{route}"
        if include_mod:
            return f"include:{include_mod}", f"{self.app}:include:{include_mod}:{stamp}"
        if name:
            return name, f"{self.app}:{name}:{stamp}"
        return "/", f"{self.app}:/:{stamp}"

    def _url_path(self, node: ast.Call) -> None:
        if not node.args:
            return
        route = _const_str(node.args[0])
        if route is None:
            return
        view_name = None
        asgi = False
        if len(node.args) > 1:
            view_expr = node.args[1]
            func_name = _name(view_expr.func) if isinstance(view_expr, ast.Call) else _name(view_expr)
            func_name = func_name or ""
            if isinstance(view_expr, ast.Call) and "as_view" in func_name:
                view_name = func_name.replace(".as_view", "")
                if view_expr.args and isinstance(view_expr.args[0], ast.Dict):
                    for k, v in zip(view_expr.args[0].keys, view_expr.args[0].values, strict=True):
                        method = _const_str(k)
                        action = _name(v)
                        if method and action:
                            pass
            elif isinstance(view_expr, ast.Call) and "as_asgi" in func_name:
                view_name = func_name.replace(".as_asgi", "")
                asgi = True
            else:
                view_name = func_name or _name(view_expr)
        name = _const_str(_kw(node, "name"))
        include_mod = None
        if len(node.args) > 1:
            view_expr = node.args[1]
            if isinstance(view_expr, ast.Call):
                fn = _name(view_expr.func) or ""
                if fn.split(".")[-1] == "include":
                    include_mod = self._include_target(view_expr)
                    view_name = None
        websocket = asgi or (route or "").lstrip("/").startswith("ws")
        extra = {
            "app": self.app,
            "route": route,
            "url_name": name,
            "view": view_name,
            "include": include_mod,
            "websocket": websocket,
        }
        display, qname = self._route_identity(route, include_mod, name, node.lineno)
        ntype = NodeType.WEBSOCKET_ROUTE if websocket else NodeType.ROUTE
        route_node = self.add_node(ntype, display, qname, node.lineno, extra)
        if name:
            un = self.add_node(NodeType.URL_NAME, name, name, node.lineno, extra)
            self.add_edge(route_node.id, un.id, EdgeType.BELONGS_TO)
        if view_name:
            short = view_name.split(".")[-1]
            target_type = NodeType.CONSUMER if websocket else NodeType.VIEW
            self.add_edge(route_node.id, node_id(target_type, f"{self.app}.{short}"), EdgeType.PUBLISHES_ROUTE)

    def _router_register(self, node: ast.Call) -> None:
        if len(node.args) < 2:
            return
        prefix = _const_str(node.args[0]) or ""
        viewset = _name(node.args[1])
        basename = _const_str(_kw(node, "basename"))
        route = prefix if prefix.startswith("/") else f"/{prefix}"
        extra = {"app": self.app, "router": True, "basename": basename, "view": viewset}
        route_node = self.add_node(
            NodeType.ROUTE, f"{route}", f"{self.app}:{route}", node.lineno, extra
        )
        if viewset:
            vq = f"{self.app}.{viewset.split('.')[-1]}"
            self.add_edge(route_node.id, node_id(NodeType.VIEW, vq), EdgeType.PUBLISHES_ROUTE)

    def _get_model(self, node: ast.Call) -> None:
        arg = node.args[0] if node.args else None
        label = _const_str(arg)
        if not label:
            if len(node.args) >= 2:
                app = _const_str(node.args[0])
                model = _const_str(node.args[1])
                label = f"{app}.{model}" if app and model else None
        if label:
            self.graph.residuals.append(
                f'string model ref apps.get_model("{label}") in {self.rel_path}:{node.lineno}'
            )
            self.add_node(NodeType.MODEL, label.split(".")[-1], label, node.lineno, {"string_ref": True})

    def _signal_connect(self, node: ast.Call, fname: str) -> None:
        handler_ast = node.args[0] if node.args else _kw(node, "receiver")
        handler = _name(handler_ast)
        signal = fname.rsplit(".", 1)[0] if "." in fname else None
        sender = _name(_kw(node, "sender"))
        if not handler:
            self.graph.residuals.append(f"signal.connect() at {self.rel_path}:{node.lineno} ({fname})")
            return
        handler_short = handler.split(".")[-1]
        qname = handler if "." in handler else f"{self.app}.{handler_short}"
        extra = {
            "app": self.app,
            "signal": signal,
            "sender": sender,
            "referenced": True,
            "via": "connect",
        }
        recv = self.add_node(NodeType.RECEIVER, handler_short, qname, node.lineno, extra)
        if signal:
            sig_short = signal.split(".")[-1]
            sig_id = node_id(NodeType.SIGNAL, sig_short)
            self.graph.nodes.append(
                Node(
                    id=sig_id,
                    type=NodeType.SIGNAL,
                    name=sig_short,
                    qualified_name=sig_short,
                    extra={"referenced": True},
                )
            )
            self.add_edge(sig_id, recv.id, EdgeType.RECEIVES)
        if sender:
            model_q = sender if "." in sender else f"{self.app}.{sender.split('.')[-1]}"
            self.add_edge(recv.id, node_id(NodeType.MODEL, model_q), EdgeType.EMITS_SIGNAL)

    def _reverse(self, node: ast.Call) -> None:
        name = _const_str(node.args[0]) if node.args else None
        if name:
            self.add_node(NodeType.URL_NAME, name, name, node.lineno, {"via": "reverse"})

    def _slice(self, node: ast.AST) -> str:
        try:
            return ast.get_source_segment(self.source, node) or ""
        except Exception:
            return ""


def _looks_idempotent(args: list[str]) -> bool:
    return any(
        a in {"pk", "id", "invoice_id", "object_id", "model_id"} or a.endswith("_id") or a.endswith("_pk")
        for a in args
    )


def extract_migrations(rel_path: str, source: str, config: LoadpathConfig) -> ExtractedGraph:
    graph = ExtractedGraph()
    app = _app_from_path(rel_path) or "unknown"
    context = config.context_for_django_app(app)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return graph
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        op = _name(node.func) or ""
        short = op.split(".")[-1]
        if short not in DESTRUCTIVE_MIGRATION_OPS and short not in {
            "CreateModel",
            "AddField",
            "RenameModel",
            "AlterUniqueTogether",
        }:
            continue
        args_repr = []
        for a in node.args:
            s = _const_str(a) or _name(a)
            if s:
                args_repr.append(s)
        kw: dict[str, str] = {}
        for keyword in node.keywords:
            if not keyword.arg:
                continue
            s = _const_str(keyword.value) or _name(keyword.value)
            if s:
                kw[keyword.arg] = s
        extra = {"op": short, "app": app, "args": args_repr, **kw}
        if short == "RemoveField":
            extra["model_name"] = kw.get("model_name") or (args_repr[0] if args_repr else None)
            extra["field_name"] = kw.get("name") or (args_repr[1] if len(args_repr) > 1 else None)
        elif short == "DeleteModel":
            extra["model_name"] = kw.get("name") or (args_repr[0] if args_repr else None)
        label_bits = [extra.get("model_name") or "", extra.get("field_name") or ""]
        label_bits = [b for b in label_bits if b] or args_repr[:3]
        label = f"{short}({', '.join(label_bits)})"
        qname = f"{app}.{Path(rel_path).stem}.{label}"
        n = Node(
            id=node_id(NodeType.MIGRATION_OP, qname),
            type=NodeType.MIGRATION_OP,
            name=label,
            qualified_name=qname,
            file_path=rel_path,
            start_line=node.lineno,
            context=context,
            extra=extra,
        )
        graph.nodes.append(n)
        if short in {"DeleteModel", "RemoveField", "RunPython"}:
            graph.edges.append(
                Edge(
                    src=n.id,
                    dst=n.id,
                    type=EdgeType.DESTRUCTIVE_MIGRATION,
                    extra={"op": short},
                )
            )
            if short == "RemoveField":
                model = extra.get("model_name")
                field = extra.get("field_name")
                if model and field:
                    graph.edges.append(
                        Edge(
                            src=n.id,
                            dst=node_id(NodeType.FIELD, f"{app}.{model}.{field}"),
                            type=EdgeType.DESTRUCTIVE_MIGRATION,
                        )
                    )
    return graph


def extract_django_file(rel_path: str, source: str, config: LoadpathConfig) -> ExtractedGraph:
    rel = rel_path.replace("\\", "/")
    if "/migrations/" in f"/{rel}/" and rel.endswith(".py"):
        return extract_migrations(rel, source, config)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        g = ExtractedGraph()
        g.residuals.append(f"Python syntax error in {rel}: {exc}")
        return g
    extractor = DjangoExtractor(rel, source, config)
    extractor.visit(tree)
    from loadpath.orm.nplusone import apply_nplusone

    apply_nplusone(extractor.graph, tree)
    from loadpath.orm.lookups import apply_lookups

    apply_lookups(extractor.graph, tree)
    return extractor.graph


def extract_django_paths(paths: Iterable[tuple[str, str]], config: LoadpathConfig) -> ExtractedGraph:
    combined = ExtractedGraph()
    for rel, source in paths:
        combined.extend(extract_django_file(rel, source, config))
    return combined
