from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Layer(StrEnum):
    DJANGO = "django"
    REACT = "react"
    STITCH = "stitch"
    ARCH = "arch"
    TEST = "test"


class NodeType(StrEnum):
    # Architecture
    BOUNDED_CONTEXT = "arch.context"
    # Django
    APP = "django.app"
    ROUTE = "django.route"
    URL_NAME = "django.url_name"
    VIEW = "django.view"
    VIEWSET_ACTION = "django.viewset_action"
    SERIALIZER = "django.serializer"
    SERIALIZER_FIELD = "django.serializer_field"
    FORM = "django.form"
    SERVICE = "django.service"
    MODEL = "django.model"
    FIELD = "django.field"
    RELATION = "django.relation"
    SIGNAL = "django.signal"
    RECEIVER = "django.receiver"
    TASK = "django.task"
    PERMISSION = "django.permission"
    THROTTLE = "django.throttle"
    MIGRATION_OP = "django.migration_op"
    ADMIN = "django.admin"
    MANAGEMENT_COMMAND = "django.management_command"
    TEST = "django.test"
    # React
    REACT_ROUTE = "react.route"
    PAGE = "react.page"
    FEATURE_MODULE = "react.feature"
    COMPONENT = "react.component"
    HOOK = "react.hook"
    API_CLIENT = "react.api_client"
    QUERY_KEY = "react.query_key"
    FORM_SCHEMA = "react.form_schema"
    CONTEXT_PROVIDER = "react.context"
    REACT_TEST = "react.test"
    # Stitch
    OPENAPI_PATH = "openapi.path"


class EdgeType(StrEnum):
    CALLS = "calls"
    IMPORTS = "imports"
    RENDERS = "renders"
    BELONGS_TO = "belongs_to"
    HAS_FIELD = "has_field"
    SERIALIZES = "serializes"
    QUERIES_MODEL = "queries_model"
    ENQUEUES = "enqueues"
    EMITS_SIGNAL = "emits_signal"
    RECEIVES = "receives"
    PUBLISHES_ROUTE = "publishes_route"
    CONSUMED_BY_CLIENT = "consumed_by_client"
    CROSSES_CONTEXT = "crosses_context"
    CHANGES_PERMISSION = "changes_permission"
    DESTRUCTIVE_MIGRATION = "destructive_migration"
    TESTED_BY = "tested_by"
    USES_QUERY_KEY = "uses_query_key"
    MATCHES_SCHEMA = "matches_schema"
    USES_SERIALIZER = "uses_serializer"
    HAS_PERMISSION = "has_permission"
    SERVES = "serves"
    RELATES_TO = "relates_to"


class EdgeWeight(StrEnum):
    CHEAP = "cheap"
    EXPENSIVE = "expensive"
    CRITICAL = "critical"


CHEAP_EDGES = {
    EdgeType.CALLS,
    EdgeType.IMPORTS,
    EdgeType.RENDERS,
    EdgeType.BELONGS_TO,
    EdgeType.HAS_FIELD,
    EdgeType.SERVES,
    EdgeType.USES_QUERY_KEY,
    EdgeType.RELATES_TO,
}
EXPENSIVE_EDGES = {
    EdgeType.SERIALIZES,
    EdgeType.QUERIES_MODEL,
    EdgeType.ENQUEUES,
    EdgeType.EMITS_SIGNAL,
    EdgeType.RECEIVES,
    EdgeType.USES_SERIALIZER,
    EdgeType.HAS_PERMISSION,
    EdgeType.TESTED_BY,
    EdgeType.MATCHES_SCHEMA,
}
CRITICAL_EDGES = {
    EdgeType.PUBLISHES_ROUTE,
    EdgeType.CONSUMED_BY_CLIENT,
    EdgeType.CROSSES_CONTEXT,
    EdgeType.CHANGES_PERMISSION,
    EdgeType.DESTRUCTIVE_MIGRATION,
}

SINK_TYPES = {
    NodeType.ROUTE,
    NodeType.REACT_ROUTE,
    NodeType.PAGE,
    NodeType.TASK,
    NodeType.MIGRATION_OP,
    NodeType.PERMISSION,
    NodeType.THROTTLE,
    NodeType.ADMIN,
    NodeType.MANAGEMENT_COMMAND,
    NodeType.OPENAPI_PATH,
}

CONTRACT_TYPES = {
    NodeType.SERIALIZER,
    NodeType.SERIALIZER_FIELD,
    NodeType.FORM,
    NodeType.OPENAPI_PATH,
    NodeType.FORM_SCHEMA,
    NodeType.ROUTE,
}

GENERATED_PATH_MARKERS = (
    "node_modules/",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    ".min.js",
    "generated/",
    "__pycache__/",
    ".egg-info/",
)


class ChangeKind(StrEnum):
    LEAF_UI = "leaf_ui"
    INTERNAL_SERVICE = "internal_service"
    PUBLIC_CONTRACT = "public_contract"
    SCHEMA_MIGRATION = "schema_migration"
    AUTH = "auth"
    CROSS_CONTEXT = "cross_context"
    MIXED = "mixed"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RuleSeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"


def weight_for(edge_type: EdgeType) -> EdgeWeight:
    if edge_type in CRITICAL_EDGES:
        return EdgeWeight.CRITICAL
    if edge_type in EXPENSIVE_EDGES:
        return EdgeWeight.EXPENSIVE
    return EdgeWeight.CHEAP


def node_id(node_type: NodeType, qualified_name: str) -> str:
    return f"{node_type}:{qualified_name}"


@dataclass
class Node:
    id: str
    type: NodeType
    name: str
    qualified_name: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    context: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "context": self.context,
            "extra": self.extra,
        }


@dataclass
class Edge:
    src: str
    dst: str
    type: EdgeType
    confidence: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def weight(self) -> EdgeWeight:
        return weight_for(self.type)

    @property
    def id(self) -> str:
        return f"{self.src}|{self.type}|{self.dst}"

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "src": self.src,
            "dst": self.dst,
            "type": self.type.value,
            "weight": self.weight.value,
            "confidence": self.confidence,
            "extra": self.extra,
        }


@dataclass
class ExtractedGraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    residuals: list[str] = field(default_factory=list)

    def extend(self, other: ExtractedGraph) -> None:
        self.nodes.extend(other.nodes)
        self.edges.extend(other.edges)
        self.residuals.extend(other.residuals)
