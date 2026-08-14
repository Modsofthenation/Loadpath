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
MODEL_BASES = {"Model"}
ADMIN_BASES = {"ModelAdmin", "StackedInline", "TabularInline"}
TASK_DECORATORS = {"shared_task", "task", "periodic_task"}
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


def _app_from_path(rel: str) -> str | None:
    parts = Path(rel).parts
    # backend/billing/models.py → billing
    if "migrations" in parts:
        idx = parts.index("migrations")
        if idx > 0:
            return parts[idx - 1]
    for i, part in enumerate(parts):
        if part in {"models.py", "views.py", "serializers.py", "urls.py", "signals.py", "tasks.py", "admin.py", "apps.py"}:
            return parts[i - 1] if i > 0 else None
        if part == "management" and i > 0:
            return parts[i - 1]
    if len(parts) >= 2 and parts[-1].endswith(".py"):
        return parts[-2]
    return None


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
        elif _has_base(node, DJANGO_VIEW_BASES) or node.name.endswith(("View", "ViewSet")):
            self._view(node)
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
        self._maybe_command(node)
        self._maybe_test(node)
        self._maybe_service_fn(node)
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
        elif short in {"delay", "apply_async"}:
            self._enqueue(node, fname)
        elif short == "connect" and any(s in fname for s in SIGNAL_NAMES | {"signal"}):
            self._signal_connect(node, fname)
        elif short == "reverse":
            self._reverse(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # urlpatterns = [...]
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "urlpatterns" and isinstance(node.value, (ast.List, ast.Tuple)):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Call):
                        self.visit_Call(elt)
        self.generic_visit(node)

    def _model(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        model = self.add_node(NodeType.MODEL, node.name, qname, node.lineno, {"app": self.app})
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
                    to_arg = stmt.value.args[0] if stmt.value.args else _kw(stmt.value, "to")
                    rel_to = _const_str(to_arg) or _name(to_arg)
                    od = _kw(stmt.value, "on_delete")
                    on_delete = _name(od)
                    extra["on_delete"] = on_delete.split(".")[-1] if on_delete else None
                    extra["related_name"] = _const_str(_kw(stmt.value, "related_name"))
                field_node = self.add_node(NodeType.FIELD, fname, field_q, stmt.lineno, extra)
                self.add_edge(model.id, field_node.id, EdgeType.HAS_FIELD)
                if rel_to:
                    target = rel_to if "." in rel_to else f"{self.app}.{rel_to.split('.')[-1]}"
                    rel_id = node_id(NodeType.MODEL, target)
                    rel_node = Node(
                        id=rel_id,
                        type=NodeType.MODEL,
                        name=target.split(".")[-1],
                        qualified_name=target,
                        extra={"placeholder": True},
                    )
                    self.graph.nodes.append(rel_node)
                    self.add_edge(
                        field_node.id,
                        rel_id,
                        EdgeType.RELATES_TO,
                        extra={"on_delete": extra.get("on_delete")},
                    )
                    if extra.get("on_delete") == "CASCADE":
                        self.add_edge(model.id, rel_id, EdgeType.RELATES_TO, extra={"cascade": True})

    def _serializer(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        ser = self.add_node(NodeType.SERIALIZER, node.name, qname, node.lineno, {"app": self.app})
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
        body = self._slice(node)
        if queryset_in_serializer or ".objects." in body or "objects.filter" in body:
            ser.extra["queryset_in_serializer"] = True
        fields = declared[:]
        if meta_fields and meta_fields != ["__all__"]:
            existing = {n for n, _ in fields}
            for f in meta_fields:
                if f not in existing:
                    fields.append((f, node.lineno))
        for fname, lineno in fields:
            fq = f"{qname}.{fname}"
            fn = self.add_node(NodeType.SERIALIZER_FIELD, fname, fq, lineno, {"app": self.app})
            self.add_edge(ser.id, fn.id, EdgeType.HAS_FIELD)
            if meta_model:
                model_q = meta_model if "." in meta_model else f"{self.app}.{meta_model.split('.')[-1]}"
                self.add_edge(fn.id, node_id(NodeType.FIELD, f"{model_q}.{fname}"), EdgeType.SERIALIZES, confidence=0.85)
        if meta_model:
            model_q = meta_model if "." in meta_model else f"{self.app}.{meta_model.split('.')[-1]}"
            self.add_edge(ser.id, node_id(NodeType.MODEL, model_q), EdgeType.SERIALIZES)
        if meta_exclude:
            ser.extra["exclude"] = meta_exclude

    def _view(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        extra: dict = {"app": self.app, "bases": _bases(node)}
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
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "get_serializer_class":
                dynamic_serializer = True
                extra["get_serializer_class"] = True
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
        for perm in permissions:
            pid = node_id(NodeType.PERMISSION, perm)
            self.graph.nodes.append(
                Node(id=pid, type=NodeType.PERMISSION, name=perm, qualified_name=perm, extra={"from_view": qname})
            )
            self.add_edge(view.id, pid, EdgeType.HAS_PERMISSION)
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
        self.add_node(NodeType.ADMIN, node.name, qname, node.lineno, {"app": self.app})

    def _service_class(self, node: ast.ClassDef) -> None:
        qname = f"{self.app}.{node.name}"
        self.add_node(NodeType.SERVICE, node.name, qname, node.lineno, {"app": self.app})

    def _maybe_service_fn(self, node: ast.FunctionDef) -> None:
        if Path(self.rel_path).name in {"services.py", "use_cases.py", "usecases.py"}:
            qname = f"{self.app}.{node.name}"
            self.add_node(NodeType.SERVICE, node.name, qname, node.lineno, {"app": self.app})

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
        if not any(d.split(".")[-1] in TASK_DECORATORS for d in decs):
            if "tasks.py" not in self.rel_path:
                return
            if not node.name.endswith("task") and "task" not in node.name:
                return
        qname = f"{self.app}.{node.name}"
        args = [a.arg for a in node.args.args]
        extra = {"app": self.app, "args": args}
        extra["looks_idempotent_on_pk"] = any(
            a in {"pk", "id", "invoice_id", "object_id", "model_id"} or a.endswith("_id") or a.endswith("_pk")
            for a in args
        )
        self.add_node(NodeType.TASK, node.name, qname, node.lineno, extra)

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
            extra = {"app": self.app, "signal": signal, "sender": sender}
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
        test = self.add_node(NodeType.TEST, node.name, qname, node.lineno, extra)
        # crude: referenced class names in the test become tested_by
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id[:1].isupper():
                for ntype in (NodeType.SERIALIZER, NodeType.VIEW, NodeType.MODEL, NodeType.SERVICE):
                    self.add_edge(
                        node_id(ntype, f"{self.app}.{child.id}"),
                        test.id,
                        EdgeType.TESTED_BY,
                        confidence=0.7,
                    )

    def _url_path(self, node: ast.Call) -> None:
        if not node.args:
            return
        route = _const_str(node.args[0])
        if route is None:
            return
        view_name = None
        if len(node.args) > 1:
            view_expr = node.args[1]
            if isinstance(view_expr, ast.Call) and _name(view_expr.func) and "as_view" in (_name(view_expr.func) or ""):
                view_name = (_name(view_expr.func) or "").replace(".as_view", "")
                # mapping dict for viewsets
                if view_expr.args and isinstance(view_expr.args[0], ast.Dict):
                    for k, v in zip(view_expr.args[0].keys, view_expr.args[0].values):
                        method = _const_str(k)
                        action = _name(v)
                        if method and action:
                            pass
            else:
                view_name = _name(view_expr)
        name = _const_str(_kw(node, "name"))
        include_mod = None
        if len(node.args) > 1:
            view_expr = node.args[1]
            if isinstance(view_expr, ast.Call):
                fn = _name(view_expr.func) or ""
                if fn.split(".")[-1] == "include":
                    include_mod = _const_str(view_expr.args[0]) if view_expr.args else _name(view_expr.args[0] if view_expr.args else None)
                    view_name = None
        extra = {
            "app": self.app,
            "route": route,
            "url_name": name,
            "view": view_name,
            "include": include_mod,
        }
        route_node = self.add_node(NodeType.ROUTE, f"{route}", f"{self.app}:{route}", node.lineno, extra)
        if name:
            un = self.add_node(NodeType.URL_NAME, name, name, node.lineno, extra)
            self.add_edge(route_node.id, un.id, EdgeType.BELONGS_TO)
        if view_name:
            vq = view_name if "." in view_name else f"{self.app}.{view_name.split('.')[-1]}"
            self.add_edge(route_node.id, node_id(NodeType.VIEW, vq), EdgeType.PUBLISHES_ROUTE)

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
            vq = viewset if "." in viewset else f"{self.app}.{viewset.split('.')[-1]}"
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

    def _enqueue(self, node: ast.Call, fname: str) -> None:
        task_name = fname.rsplit(".", 1)[0]
        short = task_name.split(".")[-1]
        qname = f"{self.app}.{short}"
        owner = self.class_stack[-1] if self.class_stack else Path(self.rel_path).stem
        owner_type = NodeType.VIEW
        if owner.endswith("Serializer"):
            owner_type = NodeType.SERIALIZER
        elif "Service" in owner or owner.endswith("UseCase"):
            owner_type = NodeType.SERVICE
        self.add_edge(
            node_id(owner_type, f"{self.app}.{owner}"),
            node_id(NodeType.TASK, qname),
            EdgeType.ENQUEUES,
            confidence=0.9,
            extra={"call": fname, "line": node.lineno},
        )
        self.add_node(NodeType.TASK, short, qname, node.lineno, {"referenced": True, "app": self.app})

    def _signal_connect(self, node: ast.Call, fname: str) -> None:
        self.graph.residuals.append(f"signal.connect() at {self.rel_path}:{node.lineno} ({fname})")

    def _reverse(self, node: ast.Call) -> None:
        name = _const_str(node.args[0]) if node.args else None
        if name:
            self.add_node(NodeType.URL_NAME, name, name, node.lineno, {"via": "reverse"})

    def _slice(self, node: ast.AST) -> str:
        try:
            return ast.get_source_segment(self.source, node) or ""
        except Exception:
            return ""


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
        for kw in node.keywords:
            if kw.arg in {"name", "model_name"}:
                s = _const_str(kw.value) or _name(kw.value)
                if s:
                    args_repr.append(s)
        label = f"{short}({', '.join(args_repr[:3])})"
        qname = f"{app}.{Path(rel_path).stem}.{label}"
        extra = {"op": short, "app": app, "args": args_repr}
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
            if short == "RemoveField" and args_repr:
                model = args_repr[0]
                field = args_repr[1] if len(args_repr) > 1 else "?"
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
    return extractor.graph


def extract_django_paths(paths: Iterable[tuple[str, str]], config: LoadpathConfig) -> ExtractedGraph:
    combined = ExtractedGraph()
    for rel, source in paths:
        combined.extend(extract_django_file(rel, source, config))
    return combined
