"""Optional django.setup() overlay. AST is the default; boot enriches model _meta when settings import."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.types import Edge, EdgeType, ExtractedGraph, Node, NodeType, node_id

BOOT_JSON_MARKER = "__LOADPATH_BOOT_JSON__"


def try_boot_models(repo_root: Path, config: LoadpathConfig) -> ExtractedGraph:
    """Boot Django in a subprocess so django.setup() is not process-global."""
    if os.environ.get("LOADPATH_BOOT_INPROCESS") == "1":
        return _boot_inprocess(repo_root, config)
    return _boot_subprocess(repo_root, config)


def _boot_subprocess(repo_root: Path, config: LoadpathConfig) -> ExtractedGraph:
    src_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["LOADPATH_BOOT_INPROCESS"] = "1"
    env["PYTHONPATH"] = str(src_root) + os.pathsep + env.get("PYTHONPATH", "")
    payload = json.dumps(
        {
            "repo_root": str(repo_root.resolve()),
            "django_root": config.django_root,
        }
    )
    code = (
        "import io,json,sys\n"
        "from contextlib import redirect_stdout\n"
        "from pathlib import Path\n"
        "from loadpath.config import load_config\n"
        "from loadpath.extractors.django_boot import _boot_inprocess\n"
        "meta=json.loads(sys.argv[1])\n"
        "root=Path(meta['repo_root'])\n"
        "cfg=load_config(root)\n"
        "cfg.django_root=meta['django_root']\n"
        "cfg.boot_django=True\n"
        "buf=io.StringIO()\n"
        "with redirect_stdout(buf):\n"
        "    g=_boot_inprocess(root,cfg)\n"
        "print(" + repr(BOOT_JSON_MARKER) + " + json.dumps("
        "{'nodes':[n.to_row() for n in g.nodes],"
        "'edges':[e.to_row() for e in g.edges],'residuals':g.residuals}))\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, payload],
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired:
        graph = ExtractedGraph()
        graph.residuals.append("django.setup() skipped: boot subprocess timed out")
        return graph
    if proc.returncode != 0:
        graph = ExtractedGraph()
        err = (proc.stderr or proc.stdout or "unknown error").strip().splitlines()
        tail = err[-1] if err else "unknown error"
        graph.residuals.append(f"django.setup() skipped: {tail}")
        return graph
    data = _parse_boot_payload(proc.stdout)
    if data is None:
        graph = ExtractedGraph()
        graph.residuals.append("django.setup() skipped: boot subprocess returned invalid JSON")
        return graph
    graph = ExtractedGraph()
    graph.residuals.extend(data.get("residuals") or [])
    for row in data.get("nodes") or []:
        graph.nodes.append(
            Node(
                id=row["id"],
                type=NodeType(row["type"]),
                name=row["name"],
                qualified_name=row["qualified_name"],
                file_path=row.get("file_path"),
                start_line=row.get("start_line"),
                end_line=row.get("end_line"),
                context=row.get("context"),
                extra=row.get("extra") or {},
            )
        )
    for row in data.get("edges") or []:
        graph.edges.append(
            Edge(
                src=row["src"],
                dst=row["dst"],
                type=EdgeType(row["type"]),
                confidence=float(row.get("confidence") or 1),
                extra=row.get("extra") or {},
            )
        )
    return graph


def _parse_boot_payload(stdout: str | None) -> dict | None:
    text = stdout or ""
    idx = text.rfind(BOOT_JSON_MARKER)
    blob = text[idx + len(BOOT_JSON_MARKER) :] if idx >= 0 else text
    blob = blob.strip().splitlines()[0] if blob.strip() else ""
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _boot_inprocess(repo_root: Path, config: LoadpathConfig) -> ExtractedGraph:
    graph = ExtractedGraph()
    settings_mod = _discover_settings_module(repo_root, config.django_root)
    if not settings_mod:
        return graph
    try:
        import django
        from django.apps import apps
    except ImportError:
        graph.residuals.append("django.setup() skipped: Django is not installed (AST graph still used)")
        return graph

    prev = os.environ.get("DJANGO_SETTINGS_MODULE")
    added: list[str] = []
    try:
        root = str(repo_root)
        backend = str(repo_root / config.django_root)
        for p in (root, backend):
            if p not in sys.path:
                sys.path.insert(0, p)
                added.append(p)
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_mod
        django.setup()
        for model in apps.get_models():
            app = model._meta.app_label
            qname = f"{app}.{model.__name__}"
            context = config.context_for_django_app(app)
            graph.nodes.append(
                Node(
                    id=node_id(NodeType.MODEL, qname),
                    type=NodeType.MODEL,
                    name=model.__name__,
                    qualified_name=qname,
                    context=context,
                    extra={
                        "app": app,
                        "db_table": model._meta.db_table,
                        "booted": True,
                    },
                )
            )
            for field in model._meta.get_fields():
                fname = getattr(field, "name", None)
                if not fname:
                    continue
                extra = {
                    "app": app,
                    "field_type": field.__class__.__name__,
                    "booted": True,
                }
                if getattr(field, "is_relation", False):
                    remote = getattr(field, "related_model", None)
                    on_delete = getattr(getattr(field, "remote_field", None), "on_delete", None)
                    extra["on_delete"] = getattr(on_delete, "__name__", None) if on_delete else None
                    extra["related_name"] = getattr(field, "related_name", None)
                    if remote is not None:
                        target = f"{remote._meta.app_label}.{remote.__name__}"
                        extra["to"] = target
                        graph.edges.append(
                            Edge(
                                src=node_id(NodeType.FIELD, f"{qname}.{fname}"),
                                dst=node_id(NodeType.MODEL, target),
                                type=EdgeType.RELATES_TO,
                                extra={"on_delete": extra["on_delete"], "booted": True},
                            )
                        )
                graph.nodes.append(
                    Node(
                        id=node_id(NodeType.FIELD, f"{qname}.{fname}"),
                        type=NodeType.FIELD,
                        name=fname,
                        qualified_name=f"{qname}.{fname}",
                        context=context,
                        extra=extra,
                    )
                )
                graph.edges.append(
                    Edge(
                        src=node_id(NodeType.MODEL, qname),
                        dst=node_id(NodeType.FIELD, f"{qname}.{fname}"),
                        type=EdgeType.HAS_FIELD,
                    )
                )
        graph.residuals.append(f"django.setup() overlay applied via {settings_mod}")
    except Exception as exc:  # noqa: BLE001
        graph.residuals.append(f"django.setup() skipped: {exc}")
    finally:
        if prev is None:
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        else:
            os.environ["DJANGO_SETTINGS_MODULE"] = prev
        for p in added:
            if p in sys.path:
                sys.path.remove(p)
    return graph


def _discover_settings_module(repo_root: Path, django_root: str = "backend") -> str | None:
    env = os.environ.get("DJANGO_SETTINGS_MODULE")
    if env:
        return env
    django_path = (repo_root / django_root).resolve()
    candidates: list[Path] = []
    for settings in repo_root.rglob("settings.py"):
        rel = settings.relative_to(repo_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if "site-packages" in rel.parts:
            continue
        candidates.append(settings)
    if not candidates:
        return None
    for settings in candidates:
        try:
            rel = settings.resolve().relative_to(django_path).with_suffix("")
            return ".".join(rel.parts)
        except ValueError:
            continue
    rel = candidates[0].relative_to(repo_root).with_suffix("")
    return ".".join(rel.parts)
