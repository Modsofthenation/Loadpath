from __future__ import annotations

import json
import re
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.extractors.react import normalize_url_template
from loadpath.graph.store import GraphStore
from loadpath.types import Edge, EdgeType, Node, NodeType, node_id

DJANGO_PATH_PARAM = re.compile(r"""<(?:(?:int|str|slug|uuid|path):)?([^>]+)>""")
METHOD_PREFIX = re.compile(r"""^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+""", re.I)


def _strip_regex_anchors(route: str) -> str:
    from loadpath.extractors.django import pretty_url_pattern

    return pretty_url_pattern(route)


def django_route_to_template(route: str) -> str:
    route = _strip_regex_anchors(route)
    if not route.startswith("/"):
        route = "/" + route
    route = DJANGO_PATH_PARAM.sub("{id}", route)
    route = re.sub(r"""/+""", "/", route)
    return route.rstrip("/") or "/"


def declared_route(route: dict) -> str:
    """URL pattern as written in path()/re_path(), including empty mounts."""
    extra = route.get("extra") or {}
    if "route" in extra and extra["route"] is not None:
        return str(extra["route"])
    name = str(route.get("name") or "")
    if name.startswith("include:"):
        return ""
    return name


def published_route(route: dict) -> str:
    extra = route.get("extra") or {}
    if extra.get("mounted_at"):
        return str(extra["mounted_at"])
    if extra.get("full_path"):
        return str(extra["full_path"])
    return declared_route(route)


def parse_public_api(spec: str) -> tuple[str | None, str]:
    m = METHOD_PREFIX.match(spec.strip())
    method = m.group(1).upper() if m else None
    path = spec[m.end() :].strip() if m else spec.strip()
    return method, django_route_to_template(path)


def load_openapi(repo_root: Path, config: LoadpathConfig) -> list[dict]:
    paths: list[dict] = []
    candidates = list(config.openapi_paths)
    if not candidates:
        for pattern in (
            "**/schema.yml",
            "**/schema.yaml",
            "**/openapi.yaml",
            "**/openapi.yml",
            "**/openapi.json",
            "**/schema.json",
            "**/swagger.json",
        ):
            candidates.extend(str(p.relative_to(repo_root)) for p in repo_root.glob(pattern))
    for rel in candidates:
        path = repo_root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix in {".json"}:
            data = json.loads(text)
        else:
            import yaml

            data = yaml.safe_load(text) or {}
        for pth, methods in (data.get("paths") or {}).items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.startswith("x-") or not isinstance(op, dict):
                    continue
                paths.append(
                    {
                        "path": django_route_to_template(pth),
                        "method": method.upper(),
                        "operation_id": op.get("operationId"),
                        "source": rel,
                        "generated": True,
                    }
                )
    return paths


def _join(prefix: str, route: str) -> str:
    prefix = _strip_regex_anchors(prefix).strip("/")
    route = _strip_regex_anchors(route).strip("/")
    if not prefix:
        return django_route_to_template(route)
    if not route:
        return django_route_to_template(prefix)
    return django_route_to_template(prefix + "/" + route)


def _include_child_app(inc: str) -> str | None:
    """billing.urls → billing; geonode.base.urls → base (not geonode)."""
    parts = [p for p in inc.split(".") if p not in {"", "urls", "urlpatterns"}]
    return parts[-1] if parts else None


def apply_url_includes(store: GraphStore) -> None:
    """Compose path('api/', include('billing.urls')) onto child routes."""
    includes: list[tuple[str, str]] = []
    for route in store.nodes([NodeType.ROUTE]):
        extra = route.get("extra") or {}
        inc = extra.get("include")
        if not inc:
            continue
        prefix = declared_route(route)
        includes.append((str(prefix), str(inc)))
    if not includes:
        return
    for route in store.nodes([NodeType.ROUTE]):
        extra = dict(route.get("extra") or {})
        if extra.get("include"):
            continue
        app = extra.get("app")
        raw = declared_route(route)
        mounted = None
        for prefix, inc in includes:
            target_app = _include_child_app(inc)
            if app and target_app and app == target_app:
                mounted = _join(prefix, str(raw))
                break
        if mounted:
            extra["mounted_at"] = mounted
            extra["full_path"] = mounted
            store.upsert_node(
                Node(
                    id=route["id"],
                    type=NodeType.ROUTE,
                    name=mounted,
                    qualified_name=route["qualified_name"],
                    file_path=route.get("file_path"),
                    start_line=route.get("start_line"),
                    context=route.get("context"),
                    extra=extra,
                )
            )
    store.conn.commit()


def stitch(store: GraphStore, config: LoadpathConfig, repo_root: Path) -> list[str]:
    residuals: list[str] = []
    apply_url_includes(store)
    openapi = load_openapi(repo_root, config)
    openapi_by_path: dict[str, list[dict]] = {}
    for item in openapi:
        openapi_by_path.setdefault(item["path"], []).append(item)
        nid = node_id(NodeType.OPENAPI_PATH, f"{item['method']} {item['path']}")
        store.upsert_node(
            Node(
                id=nid,
                type=NodeType.OPENAPI_PATH,
                name=f"{item['method']} {item['path']}",
                qualified_name=f"{item['method']} {item['path']}",
                file_path=item.get("source"),
                extra=item,
            )
        )

    routes = [n for n in store.nodes([NodeType.ROUTE])]
    clients = [n for n in store.nodes([NodeType.API_CLIENT])]
    serializers = [n for n in store.nodes([NodeType.SERIALIZER])]
    ser_fields = [n for n in store.nodes([NodeType.SERIALIZER_FIELD])]
    schemas = [n for n in store.nodes([NodeType.FORM_SCHEMA])]
    generated_files = _generated_client_files(repo_root, config)
    generated_templates: set[str] = set()
    for client in clients:
        raw = (client.get("extra") or {}).get("raw") or client["name"]
        tmpl = normalize_url_template(str(raw))
        if _client_is_generated(client, generated_files):
            generated_templates.add(tmpl)

    # Clients consumed_by matching routes / openapi
    for client in clients:
        raw = (client.get("extra") or {}).get("raw") or client["name"]
        tmpl = normalize_url_template(str(raw))
        matched = False
        generated = _client_is_generated(client, generated_files)

        for route in routes:
            extra = route.get("extra") or {}
            if extra.get("include"):
                continue
            rraw = published_route(route)
            rtmpl = django_route_to_template(str(rraw))
            if _paths_match(tmpl, rtmpl):
                if generated:
                    conf = 0.95
                elif tmpl in generated_templates:
                    conf = 0.4
                else:
                    conf = 0.55
                store.upsert_edge(
                    Edge(
                        src=route["id"],
                        dst=client["id"],
                        type=EdgeType.CONSUMED_BY_CLIENT,
                        confidence=conf,
                        extra={
                            "match": "url_template",
                            "generated_client": generated,
                            "django": rtmpl,
                            "react": tmpl,
                            "superseded_by_generated": bool(not generated and tmpl in generated_templates),
                        },
                    )
                )
                matched = True
                if not generated:
                    note = f"Inferred client stitch {tmpl} ↔ {rtmpl} from string URL in {client.get('file_path')}"
                    if tmpl in generated_templates:
                        note += " (generated OpenAPI client already covers this URL)"
                    else:
                        note += " (not a generated OpenAPI client)"
                    residuals.append(note)
        for op in openapi_by_path.get(tmpl, []):
            store.upsert_edge(
                Edge(
                    src=node_id(NodeType.OPENAPI_PATH, f"{op['method']} {op['path']}"),
                    dst=client["id"],
                    type=EdgeType.CONSUMED_BY_CLIENT,
                    confidence=1.0 if generated else (0.45 if tmpl in generated_templates else 0.7),
                    extra={"via": "openapi", "generated_client": generated},
                )
            )
            matched = True
        if not matched and tmpl.startswith("/api/"):
            residuals.append(f"React client {tmpl} has no matching Django route ({client.get('file_path')})")

    for route in routes:
        extra = route.get("extra") or {}
        if extra.get("include"):
            continue
        raw = published_route(route)
        tmpl = django_route_to_template(str(raw))
        ops = openapi_by_path.get(tmpl, [])
        if not ops:
            ops = [item for p, items in openapi_by_path.items() if _paths_match(tmpl, p) for item in items]
        for op in ops:
            store.upsert_edge(
                Edge(
                    src=route["id"],
                    dst=node_id(NodeType.OPENAPI_PATH, f"{op['method']} {op['path']}"),
                    type=EdgeType.PUBLISHES_ROUTE,
                    confidence=1.0,
                    extra={"via": "openapi"},
                )
            )

    # Serializer field ↔ Zod field overlap
    fields_by_serializer: dict[str, list[dict]] = {}
    for f in ser_fields:
        parent = f["qualified_name"].rsplit(".", 1)[0]
        fields_by_serializer.setdefault(parent, []).append(f)

    for schema in schemas:
        zod_fields = set((schema.get("extra") or {}).get("fields") or [])
        if not zod_fields:
            continue
        best: tuple[float, dict, set[str]] | None = None
        for ser in serializers:
            names = {f["name"] for f in fields_by_serializer.get(ser["qualified_name"], [])}
            if not names:
                continue
            overlap = zod_fields & names
            union = zod_fields | names
            score = len(overlap) / len(union) if union else 0
            if score >= 0.4 and (best is None or score > best[0]):
                best = (score, ser, overlap)
        if best:
            score, ser, overlap = best
            store.upsert_edge(
                Edge(
                    src=ser["id"],
                    dst=schema["id"],
                    type=EdgeType.MATCHES_SCHEMA,
                    confidence=min(0.85, 0.4 + score),
                    extra={"overlap": sorted(overlap), "score": score, "inferred": True},
                )
            )
            residuals.append(
                f"Inferred serializer/Zod overlap {ser['name']} ↔ {schema['name']} "
                f"fields={sorted(overlap)} score={score:.2f}"
            )
            # field-level edges
            ser_fields_map = {f["name"]: f for f in fields_by_serializer.get(ser["qualified_name"], [])}
            for fname in overlap:
                if fname in ser_fields_map:
                    store.upsert_edge(
                        Edge(
                            src=ser_fields_map[fname]["id"],
                            dst=schema["id"],
                            type=EdgeType.MATCHES_SCHEMA,
                            confidence=0.6,
                            extra={"field": fname, "inferred": True},
                        )
                    )

    # Public API from manifest
    for ctx in config.contexts.values():
        for spec in ctx.public_api:
            method, path = parse_public_api(spec)
            for route in routes:
                rraw = published_route(route)
                if _paths_match(django_route_to_template(str(rraw)), path):
                    if route.get("context") and route["context"] != ctx.name:
                        store.upsert_edge(
                            Edge(
                                src=route["id"],
                                dst=node_id(NodeType.BOUNDED_CONTEXT, ctx.name),
                                type=EdgeType.CROSSES_CONTEXT,
                                extra={"declared_public_api": spec},
                            )
                        )

    store.conn.commit()
    return residuals


def _paths_match(a: str, b: str) -> bool:
    a = normalize_url_template(a)
    b = django_route_to_template(b)
    if a == b:
        return True
    a_base = re.sub(r"""/\{id\}$""", "", a)
    b_base = re.sub(r"""/\{id\}$""", "", b)
    if a_base == b_base:
        return True
    # included Django urls often omit the /api mount until composed
    a_tail = a.rsplit("/", 2)[-2:] 
    b_tail = b.rsplit("/", 2)[-2:]
    if a.endswith(b) or b.endswith(a):
        return True
    return "/".join(a_tail) == "/".join(b_tail) and len(a_tail[-1]) > 2


def _client_is_generated(client: dict, generated_files: list[str]) -> bool:
    extra = client.get("extra") or {}
    if extra.get("generated"):
        return True
    fp = str(client.get("file_path") or extra.get("file") or "").replace("\\", "/")
    if not fp:
        return False
    generated = any(
        fp.endswith(g.replace("\\", "/")) or g.replace("\\", "/") in fp for g in generated_files
    )
    return generated or "/generated/" in f"/{fp}/" or "openapi" in Path(fp).name.lower()


def _generated_client_files(repo_root: Path, config: LoadpathConfig) -> list[str]:
    found: list[str] = []
    for pattern in config.generated_client_globs:
        # pathlib doesn't expand {ts,tsx}
        if "{" in pattern:
            pre, rest = pattern.split("{", 1)
            exts = rest.split("}", 1)[0].split(",")
            suffix = rest.split("}", 1)[1] if "}" in rest else ""
            for ext in exts:
                found.extend(str(p.relative_to(repo_root)) for p in repo_root.glob(pre + ext + suffix))
        else:
            found.extend(str(p.relative_to(repo_root)) for p in repo_root.glob(pattern))
    return found
