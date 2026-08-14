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
FEATURE_FOLDER_RE = re.compile(r"""features/([^/]+)""")


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


def extract_react_file(rel_path: str, source: str, config: LoadpathConfig) -> ExtractedGraph:
    rel = rel_path.replace("\\", "/")
    graph = ExtractedGraph()
    feature = _feature_from_path(rel)
    context = config.context_for_react_path(rel)
    is_shared = config.is_shared_react(rel)
    is_test = bool(re.search(r"""(\.test|\.spec)\.(t|j)sx?$""", rel) or "/__tests__/" in rel)
    stem = Path(rel).stem

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

    if feature:
        feat = add(NodeType.FEATURE_MODULE, feature, f"features.{feature}", extra={"shared": is_shared})

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
        line = source[: m.start()].count("\n") + 1
        is_page = name.endswith("Page") or "pages/" in rel or name.endswith("Screen")
        ntype = NodeType.PAGE if is_page else NodeType.COMPONENT
        extra: dict = {"feature": feature}
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
        client = add(
            NodeType.API_CLIENT,
            norm,
            f"client:{norm}",
            line,
            {"raw": url, "inferred": True, "feature": feature, "file": rel},
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
        if any(n.qualified_name == f"client:{norm}" for n in graph.nodes):
            continue
        add(
            NodeType.API_CLIENT,
            norm,
            f"client:{norm}",
            line,
            {"raw": url, "inferred": True, "feature": feature, "file": rel},
        )

    for m in ROUTE_JSX_RE.finditer(source):
        attrs = m.group(1)
        path_m = ROUTE_ATTR_PATH.search(attrs)
        el_m = ROUTE_ATTR_ELEMENT.search(attrs)
        if not path_m:
            continue
        rpath = path_m.group(1)
        line = source[: m.start()].count("\n") + 1
        page_name = el_m.group(1) if el_m else rpath
        rn = add(NodeType.REACT_ROUTE, rpath, f"react.route:{rpath}", line, {"element": page_name})
        if el_m:
            feat = import_feature.get(page_name) or feature or "app"
            page = add(NodeType.PAGE, page_name, f"{feat}.{page_name}", line, {"feature": feat, "from_route": True})
            edge(rn.id, page.id, EdgeType.PUBLISHES_ROUTE)
            edge(rn.id, node_id(NodeType.COMPONENT, f"{feat}.{page_name}"), EdgeType.RENDERS)

    for m in PATH_OBJ_RE.finditer(source):
        rpath, page_name = m.group(1), m.group(2)
        line = source[: m.start()].count("\n") + 1
        rn = add(NodeType.REACT_ROUTE, rpath, f"react.route:{rpath}", line, {"element": page_name})
        edge(rn.id, node_id(NodeType.PAGE, f"{feature or 'app'}.{page_name}"), EdgeType.PUBLISHES_ROUTE)

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

    return graph
