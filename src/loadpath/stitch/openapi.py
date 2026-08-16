from __future__ import annotations

import json
import re
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.extractors.react import normalize_url_template
from loadpath.graph.store import GraphStore
from loadpath.scan import iter_named_files
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
        names = {
            "schema.yml",
            "schema.yaml",
            "openapi.yaml",
            "openapi.yml",
            "openapi.json",
            "schema.json",
            "swagger.json",
        }
        candidates.extend(str(p.relative_to(repo_root)) for p in iter_named_files(repo_root, names))
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

    routes = [n for n in store.nodes([NodeType.ROUTE, NodeType.FASTAPI_ROUTE, NodeType.WEBSOCKET_ROUTE])]
    clients = [n for n in store.nodes([NodeType.API_CLIENT])]
    serializers = [n for n in store.nodes([NodeType.SERIALIZER])]
    ser_fields = [n for n in store.nodes([NodeType.SERIALIZER_FIELD])]
    schemas = [n for n in store.nodes([NodeType.FORM_SCHEMA])]
    generated_files = _generated_client_files(config, store.indexed_paths())
    generated_templates: set[str] = set()
    for client in clients:
        raw = (client.get("extra") or {}).get("raw") or client["name"]
        tmpl = normalize_url_template(str(raw))
        if _client_is_generated(client, generated_files):
            generated_templates.add(tmpl)

    # Clients consumed_by matching routes / openapi
    routes_by_tmpl: dict[str, list[dict]] = {}
    prepared_routes: list[tuple[dict, str]] = []
    for route in routes:
        extra = route.get("extra") or {}
        if extra.get("include"):
            continue
        rtmpl = django_route_to_template(str(published_route(route)))
        prepared_routes.append((route, rtmpl))
        routes_by_tmpl.setdefault(rtmpl, []).append(route)

    for client in clients:
        raw = (client.get("extra") or {}).get("raw") or client["name"]
        tmpl = normalize_url_template(str(raw))
        matched = False
        generated = _client_is_generated(client, generated_files)

        hits = routes_by_tmpl.get(tmpl)
        if hits is None:
            hits = [route for route, rtmpl in prepared_routes if _paths_match(tmpl, rtmpl)]
        for route in hits:
            extra = route.get("extra") or {}
            rtmpl = django_route_to_template(str(published_route(route)))
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

    # Serializer / Pydantic / GraphQL field ↔ Zod / codegen schema overlap
    contract_parents: list[dict] = []
    contract_parents.extend(serializers)
    contract_parents.extend(store.nodes([NodeType.PYDANTIC_MODEL]))
    contract_parents.extend(store.nodes([NodeType.GRAPHQL_TYPE]))
    fields_by_parent: dict[str, list[dict]] = {}
    for f in ser_fields:
        parent = f["qualified_name"].rsplit(".", 1)[0]
        fields_by_parent.setdefault(parent, []).append(f)
    for f in store.nodes([NodeType.GRAPHQL_FIELD]):
        parent = f["qualified_name"].rsplit(".", 1)[0]
        fields_by_parent.setdefault(parent, []).append(f)

    for schema in schemas:
        zod_fields = set((schema.get("extra") or {}).get("fields") or [])
        if not zod_fields:
            continue
        schema_kind = (schema.get("extra") or {}).get("kind") or "zod"
        typed = schema_kind == "graphql-codegen" or (schema.get("extra") or {}).get("generated")
        best: tuple[float, dict, set[str]] | None = None
        for ser in contract_parents:
            names = {f["name"] for f in fields_by_parent.get(ser["qualified_name"], [])}
            extra_fields = (ser.get("extra") or {}).get("fields") or []
            names.update(extra_fields)
            if not names:
                continue
            overlap = zod_fields & names
            union = zod_fields | names
            score = len(overlap) / len(union) if union else 0
            if score >= 0.4 and (best is None or score > best[0]):
                best = (score, ser, overlap)
        if best:
            score, ser, overlap = best
            inferred = not typed
            store.upsert_edge(
                Edge(
                    src=ser["id"],
                    dst=schema["id"],
                    type=EdgeType.MATCHES_SCHEMA,
                    confidence=min(0.95, 0.55 + score) if typed else min(0.85, 0.4 + score),
                    extra={
                        "overlap": sorted(overlap),
                        "score": score,
                        "inferred": inferred,
                        "via": schema_kind,
                    },
                )
            )
            if inferred:
                residuals.append(
                    f"Inferred serializer/Zod overlap {ser['name']} ↔ {schema['name']} "
                    f"fields={sorted(overlap)} score={score:.2f}"
                )
            # field-level edges
            ser_fields_map = {f["name"]: f for f in fields_by_parent.get(ser["qualified_name"], [])}
            for fname in overlap:
                if fname in ser_fields_map:
                    store.upsert_edge(
                        Edge(
                            src=ser_fields_map[fname]["id"],
                            dst=schema["id"],
                            type=EdgeType.MATCHES_SCHEMA,
                            confidence=0.85 if typed else 0.6,
                            extra={"field": fname, "inferred": inferred},
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

    residuals.extend(_stitch_graphql(store))
    residuals.extend(_stitch_htmx(store))
    residuals.extend(_stitch_e2e(store))
    residuals.extend(_stitch_trpc(store, routes))
    store.conn.commit()
    return residuals


def _stitch_graphql(store: GraphStore) -> list[str]:
    residuals: list[str] = []
    ops = store.nodes([NodeType.GRAPHQL_OPERATION])
    server = [n for n in ops if not (n.get("extra") or {}).get("client")]
    clients = [n for n in ops if (n.get("extra") or {}).get("client")]
    by_name = {n["name"].lower(): n for n in server}

    def match_server(name: str) -> dict | None:
        return by_name.get((name or "").lower())

    for client in clients:
        extra = client.get("extra") or {}
        match = match_server(client["name"])
        if not match:
            for sel in extra.get("selections") or []:
                match = match_server(str(sel))
                if match:
                    break
        if not match:
            residuals.append(
                f"GraphQL client operation {client['name']} has no matching server field "
                f"({client.get('file_path')})"
            )
            continue
        store.upsert_edge(
            Edge(
                src=match["id"],
                dst=client["id"],
                type=EdgeType.CONSUMED_BY_CLIENT,
                confidence=0.92,
                extra={"via": "graphql", "operation": client["name"], "server": match["name"]},
            )
        )
    schemas = [
        n
        for n in store.nodes([NodeType.FORM_SCHEMA])
        if (n.get("extra") or {}).get("kind") == "graphql-codegen"
    ]
    types = store.nodes([NodeType.GRAPHQL_TYPE])
    type_fields = store.nodes([NodeType.GRAPHQL_FIELD])
    fields_by_type: dict[str, set[str]] = {}
    for f in type_fields:
        parent = f["qualified_name"].rsplit(".", 1)[0]
        fields_by_type.setdefault(parent, set()).add(f["name"])
    for schema in schemas:
        zod = set((schema.get("extra") or {}).get("fields") or [])
        if not zod:
            continue
        best: tuple[float, dict, set[str]] | None = None
        for gql in types:
            names = set(fields_by_type.get(gql["qualified_name"]) or [])
            names.update((gql.get("extra") or {}).get("fields") or [])
            if not names:
                continue
            overlap = zod & names
            union = zod | names
            score = len(overlap) / len(union) if union else 0
            if score >= 0.4 and (best is None or score > best[0]):
                best = (score, gql, overlap)
        if not best:
            continue
        score, gql, overlap = best
        store.upsert_edge(
            Edge(
                src=gql["id"],
                dst=schema["id"],
                type=EdgeType.MATCHES_SCHEMA,
                confidence=min(0.95, 0.6 + score),
                extra={"via": "graphql-codegen", "overlap": sorted(overlap), "score": score, "inferred": False},
            )
        )
    return residuals


def _stitch_htmx(store: GraphStore) -> list[str]:
    residuals: list[str] = []
    calls = store.nodes([NodeType.HTMX_CALL])
    if not calls:
        return residuals
    routes = [
        n
        for n in store.nodes([NodeType.ROUTE, NodeType.FASTAPI_ROUTE])
        if not (n.get("extra") or {}).get("include")
    ]
    for call in calls:
        url = str((call.get("extra") or {}).get("url") or "")
        if not url or url.startswith("{%"):
            continue
        tmpl = django_route_to_template(url)
        matched = False
        for route in routes:
            rtmpl = django_route_to_template(str(published_route(route)))
            if not _paths_match(tmpl, rtmpl) and not (tmpl.endswith(rtmpl) or rtmpl.endswith(tmpl)):
                continue
            store.upsert_edge(
                Edge(
                    src=route["id"],
                    dst=call["id"],
                    type=EdgeType.CONSUMED_BY_CLIENT,
                    confidence=0.8,
                    extra={"via": "htmx", "htmx": True, "django": rtmpl, "htmx_url": tmpl},
                )
            )
            matched = True
            break
        if not matched:
            residuals.append(f"HTMX {tmpl} has no matching Django route ({call.get('file_path')})")
    return residuals


def _stitch_e2e(store: GraphStore) -> list[str]:
    residuals: list[str] = []
    tests = [n for n in store.nodes([NodeType.REACT_TEST]) if (n.get("extra") or {}).get("e2e")]
    if not tests:
        return residuals
    routes = [
        n
        for n in store.nodes([NodeType.ROUTE, NodeType.FASTAPI_ROUTE, NodeType.REACT_ROUTE, NodeType.OPENAPI_PATH])
        if not (n.get("extra") or {}).get("include")
    ]
    pages = store.nodes([NodeType.PAGE])
    for test in tests:
        visits = [(normalize_url_template(str(v)), str(v)) for v in ((test.get("extra") or {}).get("visits") or [])]
        for tmpl, raw in visits:
            matched = False
            for route in routes:
                extra = route.get("extra") or {}
                if route["type"] == NodeType.OPENAPI_PATH.value:
                    rtmpl = django_route_to_template(str(extra.get("path") or route["name"]))
                elif route["type"] == NodeType.REACT_ROUTE.value:
                    rtmpl = normalize_url_template(str(route["name"]))
                else:
                    rtmpl = django_route_to_template(str(published_route(route)))
                if not _paths_match(tmpl, rtmpl) and tmpl.replace("{id}", ":id") != rtmpl:
                    continue
                store.upsert_edge(
                    Edge(
                        src=route["id"],
                        dst=test["id"],
                        type=EdgeType.TESTED_BY,
                        confidence=0.9,
                        extra={"via": "e2e", "visit": raw},
                    )
                )
                matched = True
            for page in pages:
                proute = str((page.get("extra") or {}).get("route") or "")
                if proute and _paths_match(tmpl, normalize_url_template(proute)):
                    store.upsert_edge(
                        Edge(
                            src=page["id"],
                            dst=test["id"],
                            type=EdgeType.TESTED_BY,
                            confidence=0.9,
                            extra={"via": "e2e", "visit": raw},
                        )
                    )
                    matched = True
            if not matched and tmpl.startswith("/api/"):
                residuals.append(f"E2E visit {tmpl} has no matching route ({test.get('file_path')})")
    return residuals


def _stitch_trpc(store: GraphStore, routes: list[dict]) -> list[str]:
    residuals: list[str] = []
    clients = [
        n
        for n in store.nodes([NodeType.API_CLIENT])
        if (n.get("extra") or {}).get("typed_client") == "trpc"
    ]
    if not clients:
        return residuals
    ops = store.nodes([NodeType.GRAPHQL_OPERATION])
    for client in clients:
        proc = str((client.get("extra") or {}).get("procedure") or client["name"])
        last = proc.split(".")[-1].lower()
        full = proc.lower()
        aliases = {full, full.replace(".", "_")}
        if last not in {"get", "list", "create", "update", "delete", "query", "mutate"}:
            aliases.add(last)
        matched = False
        for op in ops:
            if op["name"].lower() in aliases:
                store.upsert_edge(
                    Edge(
                        src=op["id"],
                        dst=client["id"],
                        type=EdgeType.CONSUMED_BY_CLIENT,
                        confidence=0.8,
                        extra={"via": "trpc", "procedure": proc},
                    )
                )
                matched = True
        for route in routes:
            rraw = published_route(route).lower()
            if f"/trpc/{full}" in rraw or rraw.rstrip("/").endswith("/" + full.replace(".", "/")):
                store.upsert_edge(
                    Edge(
                        src=route["id"],
                        dst=client["id"],
                        type=EdgeType.CONSUMED_BY_CLIENT,
                        confidence=0.7,
                        extra={"via": "trpc", "procedure": proc, "inferred": True},
                    )
                )
                matched = True
        if not matched:
            residuals.append(
                f"tRPC procedure {proc} has no matching GraphQL field or route ({client.get('file_path')})"
            )
    return residuals


_API_MOUNTS = {"api", "v1", "v2", "v3", "backend"}


def _path_segments(path: str) -> list[str]:
    return [part for part in path.strip("/").split("/") if part]


def _seg_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    def is_param(s: str) -> bool:
        return s.startswith("{") or s.startswith(":") or s.startswith("<")
    return is_param(a) and is_param(b)


def _segs_match(a: list[str], b: list[str]) -> bool:
    return len(a) == len(b) and all(_seg_eq(x, y) for x, y in zip(a, b))


def _paths_match(a: str, b: str) -> bool:
    a = normalize_url_template(a)
    b = django_route_to_template(b)
    if a == b:
        return True
    sa, sb = _path_segments(a), _path_segments(b)
    if _segs_match(sa, sb):
        return True
    if len(sa) == len(sb) + 1 and sa[0].lower() in _API_MOUNTS and _segs_match(sa[1:], sb):
        return True
    if len(sb) == len(sa) + 1 and sb[0].lower() in _API_MOUNTS and _segs_match(sb[1:], sa):
        return True
    return False


def _client_is_generated(client: dict, generated_files: list[str]) -> bool:
    extra = client.get("extra") or {}
    if extra.get("generated") or extra.get("typed_client"):
        return True
    fp = str(client.get("file_path") or extra.get("file") or "").replace("\\", "/")
    if not fp:
        return False
    generated = any(
        fp.endswith(g.replace("\\", "/")) or g.replace("\\", "/") in fp for g in generated_files
    )
    return generated or "/generated/" in f"/{fp}/" or "openapi" in Path(fp).name.lower()


def _generated_client_files(config: LoadpathConfig, indexed_rels: list[str]) -> list[str]:
    """Match already-indexed paths against generated-client globs (no tree walk)."""
    from fnmatch import fnmatch

    patterns: list[str] = []
    for pattern in config.generated_client_globs:
        if "{" in pattern:
            pre, rest = pattern.split("{", 1)
            exts = rest.split("}", 1)[0].split(",")
            suffix = rest.split("}", 1)[1] if "}" in rest else ""
            for ext in exts:
                patterns.append(_glob_to_fnmatch(pre + ext + suffix))
        else:
            patterns.append(_glob_to_fnmatch(pattern))
    found: list[str] = []
    for rel in indexed_rels:
        path = rel.replace("\\", "/")
        if any(fnmatch(path, pat) for pat in patterns):
            found.append(rel)
    return found


def _glob_to_fnmatch(pattern: str) -> str:
    return pattern.replace("\\", "/").replace("**/", "*").replace("**", "*")
