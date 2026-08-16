from __future__ import annotations

import re
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.types import Edge, EdgeType, ExtractedGraph, Node, NodeType, node_id

IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]"""
    r"""|^\s*import\s+(?:type\s+)?(\w+)\s+from\s+['"]([^'"]+)['"]"""
    r"""|^\s*import\s+['"]([^'"]+)['"]""",
    re.M,
)
COMPONENT_RE = re.compile(
    r"""(?:export\s+)?(?:default\s+)?(?:function|const|let)\s+([A-Z][A-Za-z0-9_]*)\s*(?:=|\()"""
)
HOOK_RE = re.compile(
    r"""(?:export\s+)?(?:function|const|let)\s+(use[A-Z][A-Za-z0-9_]*)\s*(?:=|\()"""
)
USE_QUERY_RE = re.compile(
    r"""use(?:Query|Mutation|InfiniteQuery|SuspenseQuery)\s*\(\s*\{(?P<body>.*?)\}\s*\)""",
    re.S,
)
QUERY_KEY_RE = re.compile(r"""queryKey\s*:\s*(\[[^\]]*\])""")
FETCH_RE = re.compile(
    r"""(?:fetch|axios\.(?:get|post|put|patch|delete)|api\.(?:get|post|put|patch|delete))\s*\(\s*(['"`])(?P<url>.*?)\1""",
    re.S,
)
TEMPLATE_FETCH_RE = re.compile(
    r"""(?:fetch|axios\.(?:get|post|put|patch|delete)|api\.(?:get|post|put|patch|delete))\s*\(\s*(`(?P<turl>[^`]+)`|'([^']+)'|"([^"]+)")"""
)
ROUTE_JSX_RE = re.compile(
    r"""<Route\b([^>]*)>""",
    re.S,
)
ROUTE_ATTR_PATH = re.compile(r"""path\s*=\s*{?\s*['"]([^'"]+)['"]""")
ROUTE_ATTR_ELEMENT = re.compile(r"""element\s*=\s*\{\s*<([A-Z][A-Za-z0-9_]*)""")
ZOD_RE = re.compile(
    r"""(?:export\s+)?const\s+(\w+)\s*=\s*z\.object\(\s*\{(.*?)\}\s*\)""",
    re.S,
)
ZOD_FIELD_RE = re.compile(r"""^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:""", re.M)
CONTEXT_RE = re.compile(
    r"""(?:createContext|React\.createContext)\s*\("""
)
PROVIDER_RE = re.compile(
    r"""(?:export\s+)?(?:function|const)\s+(\w*Provider)\b"""
)
TEST_IMPORT_RE = re.compile(
    r"""from\s+['"]([^'"]+)['"]"""
)
RTL_RENDER_RE = re.compile(r"""\brender\s*\(\s*<([A-Z][A-Za-z0-9_]*)""")
ROUTER_OBJ_RE = re.compile(
    r"""(?:createBrowserRouter|createHashRouter|createRoutesFromElements)\s*\(""",
)
PATH_OBJ_RE = re.compile(
    r"""path\s*:\s*['"]([^'"]+)['"][^}]*?(?:element|Component)\s*:\s*<?\s*([A-Z][A-Za-z0-9_]*)""",
    re.S,
)
INVALIDATE_RE = re.compile(
    r"""invalidateQueries\s*\(\s*\{[^}]*queryKey\s*:\s*(\[[^\]]*\])""",
    re.S,
)
DEFAULT_VALUE_RE = re.compile(r"""(?:defaultValue|name)\s*=\s*(?:\{[^}]*\.(\w+)|['"](\w+)['"])""")
BOUNDARY_RE = re.compile(r"""\b(ErrorBoundary|Suspense)\b""")
RTK_RE = re.compile(r"""createApi\s*\(\s*\{""")
RTK_ENDPOINT_RE = re.compile(
    r"""(?P<name>[A-Za-z_]\w*)\s*:\s*builder\.(?P<kind>query|mutation|infiniteQuery)\b"""
)
RTK_BASE_URL_RE = re.compile(r"""baseUrl\s*:\s*['"`]([^'"`]+)""")
OPENAPI_FETCH_RE = re.compile(
    r"""\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\(\s*['"`]([^'"`]+)"""
)
TRPC_RE = re.compile(
    r"""\btrpc\.((?:[A-Za-z_]\w*\.)+)use(?:Query|Mutation|InfiniteQuery|SuspenseQuery)\b"""
)
TS_REST_ROUTE_RE = re.compile(
    r"""method\s*:\s*['"](?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"][^}]*?path\s*:\s*['"]([^'"]+)['"]"""
    r"""|path\s*:\s*['"]([^'"]+)['"][^}]*?method\s*:\s*['"](?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"]""",
    re.S,
)
E2E_VISIT_RE = re.compile(
    r"""(?:page\.goto|cy\.visit|cy\.request|page\.request\.(?:get|post|put|patch|delete)|request\.(?:get|post))\(\s*(?:['"`]([^'"`]+)['"`]|`([^`]+)`)""",
    re.I,
)
E2E_GOTO_RE = re.compile(
    r"""(?:page\.goto|cy\.visit)\(\s*(?:['"`]([^'"`]+)['"`]|`([^`]+)`)""",
    re.I,
)
SERVER_ACTION_FN_RE = re.compile(
    r"""export\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("""
    r"""|export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>"""
)
CODEGEN_TYPE_RE = re.compile(r"""export\s+type\s+([A-Z][A-Za-z0-9_]*)\s*=\s*\{""")
CODEGEN_FIELD_RE = re.compile(r"""^\s{1,6}([A-Za-z_]\w*)\s*\??\s*:""", re.M)
FEATURE_FOLDER_RE = re.compile(r"""features/([^/]+)""")
GQL_DOC_RE = re.compile(
    r"""(?:gql|graphql)\s*(?:<[^>]*>)?\s*`([^`]+)`""",
    re.S,
)
GQL_FILE_OP_RE = re.compile(
    r"""^\s*(query|mutation|subscription)\s+([A-Za-z_]\w*)""",
    re.M,
)
GQL_OP_RE = re.compile(r"""\b(query|mutation|subscription)\s+([A-Za-z_]\w*)""")
GQL_SELECTION_RE = re.compile(r"""\{\s*([A-Za-z_]\w*)""")
APP_SPECIAL = {"page", "layout", "route", "loading", "error", "default", "template"}
HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
E2E_TEST_RE = re.compile(
    r"""(\.test|\.spec|\.cy)\.(t|j)sx?$"""
)


def _feature_from_path(rel: str) -> str | None:
    m = FEATURE_FOLDER_RE.search(rel.replace("\\", "/"))
    return m.group(1) if m else None


def normalize_url_template(url: str) -> str:
    url = url.strip()
    url = re.sub(r"""\$\{[^}]+\}""", "{id}", url)
    url = re.sub(r""":[A-Za-z_][A-Za-z0-9_]*""", "{id}", url)
    url = re.sub(r"""<[^>]+>""", "{id}", url)
    if not url.startswith("/"):
        if url.startswith("http"):
            # strip origin
            url = re.sub(r"""https?://[^/]+""", "", url)
        else:
            url = "/" + url
    url = re.sub(r"""/+""", "/", url)
    return url.rstrip("/") or "/"


def _feature_from_app_segments(segments: list[str]) -> str | None:
    for seg in segments:
        if seg.startswith("[") or seg.startswith("(") or seg.startswith("@"):
            continue
        return seg
    return None


def _dynamic_to_template(seg: str) -> str:
    if seg.startswith("[[...") or seg.startswith("[..."):
        return "{id}"
    if seg.startswith("[") and seg.endswith("]"):
        inner = seg.strip("[]")
        if inner in {"id", "pk", "slug", "uuid"}:
            return "{id}"
        return "{" + inner + "}"
    return seg


def app_router_info(rel: str) -> dict | None:
    """Map app/**/page.tsx (and layout/route) to a URL template."""
    parts = rel.replace("\\", "/").split("/")
    stem = Path(rel).stem
    if stem not in APP_SPECIAL:
        return None
    if "app" not in parts:
        return None
    idx = len(parts) - 1 - parts[::-1].index("app")
    segs = [p for p in parts[idx + 1 : -1] if not (p.startswith("(") and p.endswith(")")) and not p.startswith("@")]
    url_parts = [_dynamic_to_template(s) for s in segs]
    route = "/" + "/".join(url_parts) if url_parts else "/"
    return {"route": normalize_url_template(route), "kind": stem, "segments": segs}


def pages_router_info(rel: str) -> dict | None:
    parts = rel.replace("\\", "/").split("/")
    if "pages" not in parts:
        return None
    idx = parts.index("pages")
    rest = parts[idx + 1 :]
    if not rest:
        return None
    filename = rest[-1]
    if filename.startswith("_"):
        return None
    stem = Path(filename).stem
    segs = list(rest[:-1])
    api = bool(segs and segs[0] == "api")
    if stem != "index":
        segs.append(stem)
    if api and segs[:1] == ["api"]:
        segs = segs[1:]
    url_parts = [_dynamic_to_template(s) for s in segs]
    if api:
        url_parts = ["api", *url_parts]
    route = "/" + "/".join(url_parts) if url_parts else "/"
    return {"route": normalize_url_template(route), "kind": "api" if api else "page", "segments": segs, "api": api}


def _e2e_template(url: str) -> str:
    url = normalize_url_template(url)
    url = re.sub(r"/\d+(?=/|$)", "/{id}", url)
    return url


def is_e2e_file(rel: str) -> bool:
    path = rel.replace("\\", "/")
    if E2E_TEST_RE.search(path):
        if any(part in path for part in ("/e2e/", "/cypress/", "/playwright/", ".cy.")):
            return True
    return any(f"/{part}/" in f"/{path}/" for part in ("e2e", "cypress", "playwright")) and path.endswith(
        (".ts", ".tsx", ".js", ".jsx")
    )


def is_frontend_test(rel: str) -> bool:
    path = rel.replace("\\", "/")
    return bool(
        re.search(r"""(\.test|\.spec|\.cy)\.(t|j)sx?$""", path)
        or "/__tests__/" in path
        or is_e2e_file(path)
    )


def _join_base(base: str, path: str) -> str:
    path = path.strip()
    if path.startswith("http") or path.startswith("/api/"):
        return normalize_url_template(path)
    base = (base or "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    if base:
        return normalize_url_template(base + path)
    return normalize_url_template(path)


def _page_name_for_route(route: str, kind: str) -> str:
    parts = [p for p in route.strip("/").split("/") if p and not p.startswith("{")]
    if not parts:
        stem = "Home"
    else:
        stem = "".join(p[:1].upper() + p[1:] for p in parts[-1].replace("-", "_").split("_") if p)
    suffix = {"layout": "Layout", "route": "Route", "loading": "Loading", "error": "Error"}.get(kind, "Page")
    return f"{stem}{suffix}"


def _looks_like_graphql_codegen(rel: str, source: str) -> bool:
    path = rel.replace("\\", "/").lower()
    if any(tok in path for tok in ("/generated/", "gql.ts", "graphql.ts", "graphql-codegen")):
        return True
    head = source[:2500].lower()
    return "typeddocumentnode" in head or "graphql-codegen" in head or (
        "generated by" in head and "graphql" in head
    )


def _extract_graphql_document(graph: ExtractedGraph, add, edge, body: str, line: int, feature, hooks, components, stem: str) -> None:
    ops = GQL_OP_RE.findall(body) or GQL_FILE_OP_RE.findall(body)
    if not ops:
        ops = [("query", f"{stem}Query")]
    selections = GQL_SELECTION_RE.findall(body)
    for kind, op_name in ops:
        extra = {
            "kind": kind.lower(),
            "feature": feature,
            "client": True,
            "selections": [s for s in selections if s not in {"query", "mutation", "subscription"}][:8],
        }
        op = add(
            NodeType.GRAPHQL_OPERATION,
            op_name,
            f"graphql.{op_name}",
            line,
            extra,
        )
        for owner in hooks or components:
            edge(owner.id, op.id, EdgeType.CALLS)
        if feature:
            edge(node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), op.id, EdgeType.CALLS)


def extract_react_file(rel_path: str, source: str, config: LoadpathConfig) -> ExtractedGraph:
    rel = rel_path.replace("\\", "/")
    graph = ExtractedGraph()
    app_info = app_router_info(rel)
    pages_info = pages_router_info(rel) if not app_info else None
    feature = _feature_from_path(rel)
    if not feature and app_info:
        feature = _feature_from_app_segments(app_info.get("segments") or [])
    if not feature and pages_info:
        feature = _feature_from_app_segments(pages_info.get("segments") or [])
    context = config.context_for_react_path(rel)
    is_shared = config.is_shared_react(rel)
    is_test = is_frontend_test(rel)
    e2e = is_e2e_file(rel)
    stem = Path(rel).stem
    graphql_file = Path(rel).suffix.lower() in {".graphql", ".gql"}

    def add(ntype: NodeType, name: str, qname: str, line: int = 1, extra: dict | None = None) -> Node:
        n = Node(
            id=node_id(ntype, qname),
            type=ntype,
            name=name,
            qualified_name=qname,
            file_path=rel,
            start_line=line,
            context=context,
            extra=extra or {},
        )
        graph.nodes.append(n)
        return n

    def edge(src: str, dst: str, etype: EdgeType, confidence: float = 1.0, extra: dict | None = None) -> None:
        graph.edges.append(Edge(src=src, dst=dst, type=etype, confidence=confidence, extra=extra or {}))

    if graphql_file:
        _extract_graphql_document(graph, add, edge, source, 1, feature, [], [], stem)
        return graph

    if feature:
        add(NodeType.FEATURE_MODULE, feature, f"features.{feature}", extra={"shared": is_shared})

    if e2e:
        _extract_e2e(add, edge, rel, source, feature, stem)
        return graph

    imports: list[tuple[str, str]] = []
    import_feature: dict[str, str] = {}
    for m in IMPORT_RE.finditer(source):
        if m.group(1) and m.group(2):
            names = [n.strip().split(" as ")[-1] for n in m.group(1).split(",") if n.strip()]
            for name in names:
                imports.append((name, m.group(2)))
                feat = _feature_from_path(m.group(2))
                if feat:
                    import_feature[name] = feat
        elif m.group(3) and m.group(4):
            imports.append((m.group(3), m.group(4)))
            feat = _feature_from_path(m.group(4))
            if feat:
                import_feature[m.group(3)] = feat

    for local, source_mod in imports:
        if feature and ("/shared/" in source_mod or source_mod.startswith("shared") or "/features/" in source_mod):
            other = _feature_from_path(source_mod)
            if other and other != feature:
                edge(
                    node_id(NodeType.FEATURE_MODULE, f"features.{feature}"),
                    node_id(NodeType.FEATURE_MODULE, f"features.{other}"),
                    EdgeType.IMPORTS,
                    extra={"from": rel, "import": source_mod},
                )
        edge_src = node_id(NodeType.FEATURE_MODULE, f"features.{feature}") if feature else node_id(
            NodeType.COMPONENT, f"{rel}:{stem}"
        )
        graph.edges.append(
            Edge(
                src=edge_src,
                dst=node_id(NodeType.COMPONENT, source_mod),
                type=EdgeType.IMPORTS,
                confidence=0.6,
                extra={"local": local, "placeholder": True},
            )
        )

    components: list[Node] = []
    for m in COMPONENT_RE.finditer(source):
        name = m.group(1)
        if name in HTTP_VERBS:
            continue
        line = source[: m.start()].count("\n") + 1
        is_page = (
            name.endswith("Page")
            or "pages/" in rel
            or name.endswith("Screen")
            or (app_info and app_info.get("kind") == "page")
            or (pages_info and pages_info.get("kind") == "page" and not pages_info.get("api"))
        )
        ntype = NodeType.PAGE if is_page else NodeType.COMPONENT
        extra: dict = {"feature": feature}
        if app_info:
            extra["next_app"] = True
            extra["next_kind"] = app_info["kind"]
            extra["route"] = app_info["route"]
        if pages_info and not pages_info.get("api"):
            extra["next_pages"] = True
            extra["route"] = pages_info["route"]
        if is_page:
            extra["has_error_boundary"] = bool(BOUNDARY_RE.search(source))
        defaults = [a or b for a, b in DEFAULT_VALUE_RE.findall(source)]
        if defaults:
            extra["form_fields"] = sorted(set(defaults))
        n = add(ntype, name, f"{feature or 'app'}.{name}", line, extra)
        components.append(n)
        if feature:
            edge(n.id, node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), EdgeType.BELONGS_TO)

    hooks: list[Node] = []
    for m in HOOK_RE.finditer(source):
        name = m.group(1)
        line = source[: m.start()].count("\n") + 1
        n = add(NodeType.HOOK, name, f"{feature or 'app'}.{name}", line, {"feature": feature})
        hooks.append(n)
        if feature:
            edge(n.id, node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), EdgeType.BELONGS_TO)

    for m in re.finditer(r"""\b(use[A-Z][A-Za-z0-9_]*)\s*\(""", source):
        hook_name = m.group(1)
        if hook_name in {"useQuery", "useMutation", "useEffect", "useState", "useMemo", "useCallback", "useRef"}:
            continue
        for owner in components:
            edge(
                owner.id,
                node_id(NodeType.HOOK, f"{feature or 'app'}.{hook_name}"),
                EdgeType.CALLS,
                confidence=0.9,
            )

    for m in USE_QUERY_RE.finditer(source):
        body = m.group("body")
        line = source[: m.start()].count("\n") + 1
        km = QUERY_KEY_RE.search(body)
        key_raw = km.group(1) if km else None
        if key_raw:
            key_name = re.sub(r"""\s+""", "", key_raw)
            qn = add(
                NodeType.QUERY_KEY,
                key_name,
                f"{feature or 'app'}.queryKey.{key_name}",
                line,
                {"raw": key_raw, "feature": feature},
            )
            for h in hooks or components:
                edge(h.id, qn.id, EdgeType.USES_QUERY_KEY)
            if m.group(0).startswith("useMutation"):
                for h in hooks:
                    h.extra["mutation"] = True

    for m in INVALIDATE_RE.finditer(source):
        key_raw = m.group(1)
        line = source[: m.start()].count("\n") + 1
        key_name = re.sub(r"""\s+""", "", key_raw)
        qn = add(
            NodeType.QUERY_KEY,
            key_name,
            f"{feature or 'app'}.queryKey.{key_name}",
            line,
            {"raw": key_raw, "feature": feature, "invalidation": True},
        )
        for h in hooks or components:
            edge(h.id, qn.id, EdgeType.USES_QUERY_KEY, extra={"invalidates": True})

    for m in TEMPLATE_FETCH_RE.finditer(source):
        url = m.group("turl") or m.group(3) or m.group(4)
        if not url:
            continue
        if "/api/" not in url and not url.startswith("/"):
            continue
        line = source[: m.start()].count("\n") + 1
        norm = normalize_url_template(url)
        generated_file = "/generated/" in f"/{rel}/" or "openapi" in Path(rel).stem.lower()
        qname = f"client:{rel}:{norm}"
        if any(n.qualified_name == qname for n in graph.nodes):
            continue
        client = add(
            NodeType.API_CLIENT,
            norm,
            qname,
            line,
            {
                "raw": url,
                "inferred": not generated_file,
                "generated": generated_file,
                "feature": feature,
                "file": rel,
            },
        )
        for owner in hooks or components:
            edge(owner.id, client.id, EdgeType.CALLS)
        if feature:
            edge(node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), client.id, EdgeType.CALLS)

    # also catch fetch(`/api/...`) missed by grouping
    for m in re.finditer(r"""[`'"](/api/[^`'"]+)[`'"]""", source):
        url = m.group(1)
        line = source[: m.start()].count("\n") + 1
        norm = normalize_url_template(url)
        generated_file = "/generated/" in f"/{rel}/" or "openapi" in Path(rel).stem.lower()
        qname = f"client:{rel}:{norm}"
        if any(n.qualified_name == qname for n in graph.nodes):
            continue
        add(
            NodeType.API_CLIENT,
            norm,
            qname,
            line,
            {
                "raw": url,
                "inferred": not generated_file,
                "generated": generated_file,
                "feature": feature,
                "file": rel,
            },
        )

    for m in ROUTE_JSX_RE.finditer(source):
        attrs = m.group(1)
        path_m = ROUTE_ATTR_PATH.search(attrs)
        el_m = ROUTE_ATTR_ELEMENT.search(attrs)
        if not path_m:
            continue
        rpath = path_m.group(1) or "/"
        line = source[: m.start()].count("\n") + 1
        page_name = el_m.group(1) if el_m else rpath
        rn = add(NodeType.REACT_ROUTE, rpath, f"react.route:{rpath}", line, {"element": page_name})
        if el_m:
            feat = import_feature.get(page_name) or feature or "app"
            page = add(NodeType.PAGE, page_name, f"{feat}.{page_name}", line, {"feature": feat, "from_route": True})
            edge(rn.id, page.id, EdgeType.PUBLISHES_ROUTE)
            edge(rn.id, node_id(NodeType.COMPONENT, f"{feat}.{page_name}"), EdgeType.RENDERS)

    for m in PATH_OBJ_RE.finditer(source):
        rpath, page_name = m.group(1) or "/", m.group(2)
        line = source[: m.start()].count("\n") + 1
        rn = add(NodeType.REACT_ROUTE, rpath, f"react.route:{rpath}", line, {"element": page_name})
        edge(rn.id, node_id(NodeType.PAGE, f"{feature or 'app'}.{page_name}"), EdgeType.PUBLISHES_ROUTE)

    for m in GQL_DOC_RE.finditer(source):
        body = m.group(1)
        line = source[: m.start()].count("\n") + 1
        ops = GQL_OP_RE.findall(body)
        if not ops:
            ops = [("query", f"{stem}Query")]
        selections = GQL_SELECTION_RE.findall(body)
        for kind, op_name in ops:
            extra = {
                "kind": kind.lower(),
                "feature": feature,
                "client": True,
                "selections": [s for s in selections if s not in {"query", "mutation", "subscription"}][:8],
            }
            op = add(
                NodeType.GRAPHQL_OPERATION,
                op_name,
                f"graphql.{op_name}",
                line,
                extra,
            )
            for owner in hooks or components:
                edge(owner.id, op.id, EdgeType.CALLS)
            if feature:
                edge(node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), op.id, EdgeType.CALLS)

    for m in ZOD_RE.finditer(source):
        name, body = m.group(1), m.group(2)
        line = source[: m.start()].count("\n") + 1
        fields = ZOD_FIELD_RE.findall(body)
        schema = add(
            NodeType.FORM_SCHEMA,
            name,
            f"{feature or 'app'}.{name}",
            line,
            {"fields": fields, "kind": "zod", "feature": feature},
        )
        for owner in components:
            edge(owner.id, schema.id, EdgeType.CALLS, confidence=0.7)

    if CONTEXT_RE.search(source):
        for m in PROVIDER_RE.finditer(source):
            name = m.group(1)
            line = source[: m.start()].count("\n") + 1
            add(NodeType.CONTEXT_PROVIDER, name, f"{feature or 'app'}.{name}", line)

    if is_test:
        line = 1
        tn = add(
            NodeType.REACT_TEST,
            stem,
            f"test.{rel}",
            line,
            {"file": rel, "mentions": sorted(set(re.findall(r"""['"](\w+)['"]""", source)))},
        )
        for m in RTL_RENDER_RE.finditer(source):
            name = m.group(1)
            edge(node_id(NodeType.PAGE, f"{feature or 'app'}.{name}"), tn.id, EdgeType.TESTED_BY)
            edge(node_id(NodeType.COMPONENT, f"{feature or 'app'}.{name}"), tn.id, EdgeType.TESTED_BY)
        for m in TEST_IMPORT_RE.finditer(source):
            spec = m.group(1)
            if spec.startswith(".") or "features/" in spec:
                base = Path(spec).stem
                if base[0:1].isupper() or base.startswith("use"):
                    ntype = NodeType.HOOK if base.startswith("use") else NodeType.COMPONENT
                    edge(node_id(ntype, f"{feature or 'app'}.{base}"), tn.id, EdgeType.TESTED_BY, confidence=0.75)

    # composition: JSX usage of other components
    defined = {n.name for n in components}
    for other in re.findall(r"""<([A-Z][A-Za-z0-9_]*)\b""", source):
        if other in {"Route", "Routes", "BrowserRouter", "QueryClientProvider"}:
            continue
        if other in defined:
            continue
        for owner in components:
            edge(
                owner.id,
                node_id(NodeType.COMPONENT, f"{feature or 'app'}.{other}"),
                EdgeType.RENDERS,
                confidence=0.8,
            )
            edge(
                owner.id,
                node_id(NodeType.PAGE, f"{feature or 'app'}.{other}"),
                EdgeType.RENDERS,
                confidence=0.5,
            )

    _extract_next_routes(add, edge, graph, rel, source, feature, app_info, pages_info, components)
    _extract_typed_clients(add, edge, graph, rel, source, feature, hooks, components)
    _extract_server_actions(add, edge, rel, source, feature, components)
    if _looks_like_graphql_codegen(rel, source):
        _extract_graphql_codegen(add, edge, source, feature, components)

    return graph


def _add_client(add, edge, graph, rel, feature, hooks, components, url: str, line: int, extra: dict) -> Node | None:
    norm = normalize_url_template(url)
    qname = f"client:{rel}:{norm}"
    if any(n.qualified_name == qname for n in graph.nodes):
        existing = next(n for n in graph.nodes if n.qualified_name == qname)
        if extra.get("typed_client") and not existing.extra.get("typed_client"):
            existing.extra.update(extra)
            existing.extra["inferred"] = False
        return existing
    payload = {
        "raw": url,
        "feature": feature,
        "file": rel,
        **extra,
    }
    client = add(NodeType.API_CLIENT, norm, qname, line, payload)
    for owner in hooks or components:
        edge(owner.id, client.id, EdgeType.CALLS)
    if feature:
        edge(node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), client.id, EdgeType.CALLS)
    return client


def _extract_next_routes(add, edge, graph, rel, source, feature, app_info, pages_info, components) -> None:
    info = app_info or pages_info
    if not info:
        return
    route = info["route"]
    kind = info["kind"]
    line = 1
    if info.get("api") or kind == "route":
        url = route if route.startswith("/") else "/" + route
        if info.get("api") and not url.startswith("/api"):
            url = "/api" + url
        _add_client(
            add,
            edge,
            graph,
            rel,
            feature,
            [],
            components,
            url,
            line,
            {"typed_client": "next-api", "generated": False, "inferred": False, "next_api": True},
        )
        return
    page_name = _page_name_for_route(route, kind)
    extra = {
        "feature": feature,
        "route": route,
        "next_app": bool(app_info),
        "next_pages": bool(pages_info),
        "next_kind": kind,
        "has_error_boundary": bool(BOUNDARY_RE.search(source)),
    }
    ntype = NodeType.PAGE if kind in {"page", "route"} else NodeType.COMPONENT
    if kind == "layout":
        ntype = NodeType.COMPONENT
        extra["next_layout"] = True
    existing = [n for n in graph.nodes if n.type is ntype and n.extra.get("route") == route]
    if not existing:
        page = add(ntype, page_name, f"{feature or 'app'}.{page_name}", line, extra)
        components.append(page)
        if feature:
            edge(page.id, node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), EdgeType.BELONGS_TO)
    else:
        page = existing[0]
    rn = add(
        NodeType.REACT_ROUTE,
        route,
        f"react.route:{route}",
        line,
        {"element": page_name, "next_app": bool(app_info), "next_kind": kind},
    )
    edge(rn.id, page.id, EdgeType.PUBLISHES_ROUTE)
    if kind == "layout":
        # layout wraps pages under this prefix — linked later if a page route starts with this path
        for other in list(graph.nodes):
            if other.type is NodeType.PAGE and str((other.extra or {}).get("route") or "").startswith(route.rstrip("/") or "/"):
                edge(page.id, other.id, EdgeType.RENDERS, confidence=0.7)


def _extract_typed_clients(add, edge, graph, rel, source, feature, hooks, components) -> None:
    if RTK_RE.search(source) or "injectEndpoints" in source:
        base = ""
        bm = RTK_BASE_URL_RE.search(source)
        if bm:
            base = bm.group(1)
        for m in RTK_ENDPOINT_RE.finditer(source):
            name = m.group("name")
            kind = m.group("kind")
            window = source[m.end() : m.end() + 500]
            raw = _rtk_endpoint_url(window)
            if not raw or raw.upper() in HTTP_VERBS:
                continue
            if raw.startswith("http") and "/api/" not in raw and not raw.startswith("/"):
                continue
            url = _join_base(base, raw)
            line = source[: m.start()].count("\n") + 1
            _add_client(
                add,
                edge,
                graph,
                rel,
                feature,
                hooks,
                components,
                url,
                line,
                {
                    "typed_client": "rtk",
                    "generated": True,
                    "inferred": False,
                    "endpoint": name,
                    "kind": kind,
                },
            )
    if "createClient" in source or "openapi-fetch" in source or "openapifetch" in rel.replace("\\", "/").lower().replace("-", ""):
        for m in OPENAPI_FETCH_RE.finditer(source):
            method, raw = m.group(1), m.group(2)
            if not raw.startswith("/") and "/api/" not in raw:
                continue
            line = source[: m.start()].count("\n") + 1
            _add_client(
                add,
                edge,
                graph,
                rel,
                feature,
                hooks,
                components,
                raw,
                line,
                {
                    "typed_client": "openapi-fetch",
                    "generated": True,
                    "inferred": False,
                    "method": method,
                },
            )
    if "initContract" in source or "@ts-rest" in source or "ts-rest" in rel:
        for m in TS_REST_ROUTE_RE.finditer(source):
            raw = m.group(1) or m.group(2) or ""
            if not raw.startswith("/") and "/api/" not in raw:
                continue
            line = source[: m.start()].count("\n") + 1
            _add_client(
                add,
                edge,
                graph,
                rel,
                feature,
                hooks,
                components,
                raw,
                line,
                {"typed_client": "ts-rest", "generated": True, "inferred": False},
            )
    for m in TRPC_RE.finditer(source):
        proc = m.group(1).rstrip(".")
        line = source[: m.start()].count("\n") + 1
        qname = f"client:{rel}:trpc.{proc}"
        if any(n.qualified_name == qname for n in graph.nodes):
            continue
        client = add(
            NodeType.API_CLIENT,
            proc,
            qname,
            line,
            {
                "typed_client": "trpc",
                "generated": True,
                "inferred": False,
                "trpc": True,
                "procedure": proc,
                "feature": feature,
                "file": rel,
            },
        )
        for owner in hooks or components:
            edge(owner.id, client.id, EdgeType.CALLS)
        if feature:
            edge(node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), client.id, EdgeType.CALLS)


def _extract_server_actions(add, edge, rel, source, feature, components) -> None:
    if '"use server"' not in source and "'use server'" not in source:
        return
    for m in SERVER_ACTION_FN_RE.finditer(source):
        name = m.group(1) or m.group(2)
        if not name or name in HTTP_VERBS:
            continue
        line = source[: m.start()].count("\n") + 1
        action = add(
            NodeType.SERVER_ACTION,
            name,
            f"{feature or 'app'}.{name}",
            line,
            {"feature": feature, "server_action": True, "next_app": True},
        )
        for owner in components:
            edge(owner.id, action.id, EdgeType.CALLS, confidence=0.8)
        if feature:
            edge(node_id(NodeType.FEATURE_MODULE, f"features.{feature}"), action.id, EdgeType.CALLS)


def _extract_graphql_codegen(add, edge, source, feature, components) -> None:
    for m in CODEGEN_TYPE_RE.finditer(source):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(source) and depth:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        body = source[start : i - 1]
        fields = [f for f in CODEGEN_FIELD_RE.findall(body) if f not in {"__typename", "Query", "Mutation", "Subscription"}]
        if not fields:
            continue
        line = source[: m.start()].count("\n") + 1
        schema = add(
            NodeType.FORM_SCHEMA,
            name,
            f"{feature or 'app'}.{name}",
            line,
            {"fields": fields, "kind": "graphql-codegen", "feature": feature, "generated": True, "typed_client": "graphql-codegen"},
        )
        for owner in components:
            edge(owner.id, schema.id, EdgeType.CALLS, confidence=0.6)


def _extract_e2e(add, edge, rel, source, feature, stem) -> None:
    visits: list[str] = []
    for m in E2E_VISIT_RE.finditer(source):
        raw = m.group(1) or m.group(2) or ""
        if not raw:
            continue
        if raw.startswith("http"):
            raw = re.sub(r"""https?://[^/]+""", "", raw)
        if not raw.startswith("/") and "/api/" not in raw:
            continue
        visits.append(_e2e_template(raw))
    tn = add(
        NodeType.REACT_TEST,
        stem,
        f"test.{rel}",
        1,
        {
            "file": rel,
            "e2e": True,
            "visits": visits,
            "kind": "cypress" if ".cy." in rel or "/cypress/" in rel else "playwright",
            "mentions": sorted(set(re.findall(r"""['"](\w+)['"]""", source))),
        },
    )
    for tmpl in visits:
        edge(node_id(NodeType.REACT_ROUTE, f"react.route:{tmpl}"), tn.id, EdgeType.TESTED_BY, extra={"via": "e2e"})
        # common react-router param form
        alt = tmpl.replace("{id}", ":id")
        if alt != tmpl:
            edge(node_id(NodeType.REACT_ROUTE, f"react.route:{alt}"), tn.id, EdgeType.TESTED_BY, extra={"via": "e2e"})
        page_name = _page_name_for_route(tmpl, "page")
        edge(node_id(NodeType.PAGE, f"{feature or 'app'}.{page_name}"), tn.id, EdgeType.TESTED_BY, extra={"via": "e2e"}, confidence=0.7)


def _rtk_endpoint_url(window: str) -> str:
    nxt = re.search(r"""\b[A-Za-z_]\w*\s*:\s*builder\.(?:query|mutation|infiniteQuery)\b""", window)
    if nxt:
        window = window[: nxt.start()]
    labeled = re.search(r"""url\s*:\s*(?:['"`]([^'"`]+)['"`])""", window)
    if labeled:
        return labeled.group(1) or ""
    template = re.search(r"""=>\s*`([^`]+)`""", window)
    if template:
        return template.group(1) or ""
    literal = re.search(r"""=>\s*['"]([^'"]+)['"]""", window)
    return (literal.group(1) if literal else "") or ""
