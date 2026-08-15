"""Django templates and HTMX attributes as sinks on the load path."""

from __future__ import annotations

import re
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.types import Edge, EdgeType, ExtractedGraph, Node, NodeType, node_id

HTMX_RE = re.compile(
    r"""\bhx-(get|post|put|patch|delete)\s*=\s*["']([^"']+)["']""",
    re.I,
)
URL_TAG_RE = re.compile(r"""\{\%\s*url\s+['"]([^'"]+)['"]""")
INCLUDE_RE = re.compile(r"""\{\%\s*include\s+['"]([^'"]+)['"]""")
EXTENDS_RE = re.compile(r"""\{\%\s*extends\s+['"]([^'"]+)['"]""")
BLOCK_RE = re.compile(r"""\{\%\s*block\s+(\w+)""")


def _app_from_template(rel: str) -> str:
    parts = Path(rel).parts
    if "templates" in parts:
        idx = parts.index("templates")
        if idx > 0:
            return parts[idx - 1]
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if len(parts) >= 2:
        return parts[-2]
    return "unknown"


def template_qname(rel: str) -> str:
    """Django template name: path after `templates/`, else the relative file path."""
    parts = Path(rel.replace("\\", "/")).parts
    if "templates" in parts:
        idx = parts.index("templates")
        tail = "/".join(parts[idx + 1 :])
        if tail:
            return tail
    return rel.replace("\\", "/")


def extract_template_file(rel_path: str, source: str, config: LoadpathConfig) -> ExtractedGraph:
    rel = rel_path.replace("\\", "/")
    graph = ExtractedGraph()
    app = _app_from_template(rel)
    context = config.context_for_django_app(app)
    name = Path(rel).name
    qname = template_qname(rel)
    extra = {
        "app": app,
        "blocks": BLOCK_RE.findall(source)[:12],
        "htmx": bool(HTMX_RE.search(source)),
    }
    template = Node(
        id=node_id(NodeType.TEMPLATE, qname),
        type=NodeType.TEMPLATE,
        name=name,
        qualified_name=qname,
        file_path=rel,
        start_line=1,
        context=context,
        extra=extra,
    )
    graph.nodes.append(template)

    for tag in URL_TAG_RE.findall(source):
        graph.edges.append(
            Edge(
                src=template.id,
                dst=node_id(NodeType.URL_NAME, tag),
                type=EdgeType.CALLS,
                confidence=0.8,
                extra={"url_name": tag},
            )
        )

    for other in INCLUDE_RE.findall(source) + EXTENDS_RE.findall(source):
        graph.edges.append(
            Edge(
                src=template.id,
                dst=node_id(NodeType.TEMPLATE, other),
                type=EdgeType.RENDERS,
                confidence=0.9,
                extra={"include": other},
            )
        )

    for match in HTMX_RE.finditer(source):
        method, url = match.group(1).upper(), match.group(2)
        call_name = f"{method} {url}"
        call = Node(
            id=node_id(NodeType.HTMX_CALL, f"{rel}:{call_name}"),
            type=NodeType.HTMX_CALL,
            name=call_name,
            qualified_name=f"{rel}:{call_name}",
            file_path=rel,
            start_line=source[: match.start()].count("\n") + 1,
            context=context,
            extra={"app": app, "method": method, "url": url},
        )
        graph.nodes.append(call)
        graph.edges.append(Edge(src=template.id, dst=call.id, type=EdgeType.HTMX_CALLS))
    return graph
