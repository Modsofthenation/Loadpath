import { kindLabel, typeLabel } from "./format";
import { LAYER_LABELS } from "./graphView";
import { layerFor, type GraphEdge, type GraphNode } from "./types";

const LINK_LIMIT = 16;
const LIST_LIMIT = 12;

export const SINK_TYPES = new Set([
  "django.route",
  "react.route",
  "react.page",
  "django.task",
  "django.migration_op",
  "django.permission",
  "django.throttle",
  "django.admin",
  "django.management_command",
  "openapi.path",
  "django.consumer",
  "django.websocket_route",
  "django.template",
  "django.cache_key",
  "django.feature_flag",
  "django.side_effect",
  "graphql.operation",
  "fastapi.route",
]);

export const CONTRACT_TYPES = new Set([
  "django.serializer",
  "django.serializer_field",
  "django.form",
  "openapi.path",
  "react.form_schema",
  "django.route",
  "graphql.type",
  "graphql.field",
  "graphql.operation",
  "fastapi.model",
  "fastapi.route",
]);

const TYPE_PURPOSE: Record<string, string> = {
  "arch.context": "Ownership boundary from loadpath.yml — the context this code belongs to.",
  "django.app": "Django app package that owns models, views, and jobs.",
  "django.route": "HTTP URL that publishes a view. A sink: this is where a change becomes a public request.",
  "django.url_name": "Named URL used by reverse() / {% url %} lookups.",
  "django.view": "Request handler (class-based view, function view, or ViewSet).",
  "django.viewset_action": "One ViewSet action (list, create, retrieve, update, destroy).",
  "django.permission": "Auth gate on a view — who is allowed to hit this path.",
  "django.throttle": "Rate-limit class attached to a view.",
  "django.serializer": "Request/response contract: which fields go in and come out.",
  "django.form": "Django form that validates submitted input.",
  "django.serializer_field": "One field on a serializer or form — the typed slot on the contract.",
  "django.service": "Internal service or use-case. Work that is not itself an HTTP sink.",
  "django.model": "ORM model. Schema and relations live here.",
  "django.field": "Model column. Type, indexes, and relations are the contract of the table.",
  "django.relation": "Model-to-model relation (FK / M2M / O2O).",
  "django.task": "Celery or Dramatiq job. Once enqueued, this is a sink.",
  "django.receiver": "Signal handler that runs after a model event.",
  "django.signal": "Django signal that receivers subscribe to.",
  "django.test": "Backend test that mentions symbols on this path.",
  "django.admin": "Django admin class for a model.",
  "django.migration_op": "Schema migration operation (CreateModel, AlterField, …).",
  "django.management_command": "manage.py command — an operational sink.",
  "django.consumer": "Django Channels WebSocket/HTTP consumer. A sink once a client connects.",
  "django.websocket_route": "ASGI WebSocket URL. A sink: this is where a change becomes a live connection.",
  "django.template": "Django template. HTML (and HTMX) the server renders.",
  "django.htmx": "HTMX call from a template to a URL — another published seam.",
  "django.cache_key": "Cache get/set key. Invalidation is part of the load path.",
  "django.feature_flag": "Feature flag checked on this path. The change may be dark-launched.",
  "django.side_effect": "transaction.on_commit (or similar) side effect that runs after the request commits.",
  "graphql.type": "GraphQL object/input type — a published contract.",
  "graphql.field": "One field on a GraphQL type.",
  "graphql.operation": "GraphQL query, mutation, or subscription. A published contract and a sink.",
  "fastapi.route": "FastAPI path operation sitting next to Django in this repo.",
  "fastapi.model": "Pydantic response/request model — the FastAPI contract.",
  "openapi.path": "Generated OpenAPI operation. The typed HTTP contract between stacks.",
  "react.api_client": "Frontend fetch or generated client call to an API path.",
  "react.query_key": "React Query cache key. Invalidation and reads share this name.",
  "react.hook": "Data hook wrapping query or mutation calls.",
  "react.feature": "Frontend feature module (folder).",
  "react.route": "Client-side route. A sink: this is a URL the user can open.",
  "react.page": "Page or screen component rendered by a route.",
  "react.component": "UI component.",
  "react.form_schema": "Zod (or similar) schema — typed form inputs on the client.",
  "react.test": "Frontend test covering a page, hook, or component.",
  "react.context": "React context provider.",
};

const FACT_LABELS: Record<string, string> = {
  field_type: "Type",
  fields: "Fields",
  form_fields: "Form fields",
  permissions: "Permissions",
  throttles: "Throttles",
  authentication: "Authentication",
  pagination: "Pagination",
  filterset: "Filterset",
  bases: "Extends",
  on_delete: "on_delete",
  related_name: "related_name",
  unique: "Unique",
  db_index: "Indexed",
  relation: "Relation field",
  looks_idempotent_on_pk: "Idempotent on pk",
  broker: "Broker",
  route: "Route",
  url_name: "URL name",
  view: "View",
  include: "Includes",
  mounted_at: "Mounted at",
  full_path: "Full path",
  method: "Method",
  path: "Path",
  operation_id: "Operation",
  raw: "URL",
  kind: "Schema",
  exclude: "Excludes",
  queryset_in_serializer: "Queryset in serializer",
  get_queryset: "Custom get_queryset",
  get_serializer_class: "Dynamic serializer",
  dynamic: "Dynamic",
  fbv: "Function view",
  ninja: "Django Ninja",
  django_form: "Django form",
  mutation: "Mutation",
  has_error_boundary: "Error boundary",
  invalidation: "Cache invalidation",
  inferred: "Inferred stitch",
  generated: "Generated",
  shared: "Shared module",
  element: "Renders",
  model_name: "Model",
  field_name: "Field",
  op: "Operation",
  app: "App",
  feature: "Feature",
  from_view: "From view",
  mentions: "Mentions",
  nodeid: "Test id",
  task: "Task",
  to: "Related to",
};

const FACT_ORDER = [
  "field_type",
  "method",
  "path",
  "operation_id",
  "raw",
  "route",
  "mounted_at",
  "full_path",
  "url_name",
  "view",
  "element",
  "fields",
  "form_fields",
  "exclude",
  "kind",
  "bases",
  "permissions",
  "authentication",
  "throttles",
  "pagination",
  "filterset",
  "on_delete",
  "related_name",
  "to",
  "unique",
  "db_index",
  "relation",
  "looks_idempotent_on_pk",
  "broker",
  "task",
  "model_name",
  "field_name",
  "op",
  "app",
  "feature",
  "from_view",
  "include",
  "fbv",
  "ninja",
  "django_form",
  "mutation",
  "has_error_boundary",
  "invalidation",
  "inferred",
  "generated",
  "shared",
  "queryset_in_serializer",
  "get_queryset",
  "get_serializer_class",
  "dynamic",
  "mentions",
  "nodeid",
];

const HIDDEN_EXTRA_KEYS = new Set([
  "referenced",
  "placeholder",
  "booted",
  "line",
  "call",
  "from",
  "import",
  "local",
  "source",
  "file",
  "plain_handler",
  "string_ref",
  "pagination_sink",
  "match",
  "via",
  "generated_client",
  "django",
  "react",
  "superseded_by_generated",
  "foreign_app",
  "imported",
]);

const ALWAYS_SHOW_FALSE = new Set(["looks_idempotent_on_pk"]);
const ROLE_FACT_KEYS = new Set(["inferred", "generated", "mutation", "fbv", "ninja"]);

export type InspectorLink = {
  id: string;
  name: string;
  type: string;
  typeLabel: string;
  edgeType: string;
  edgeLabel: string;
  inferred: boolean;
};

export type InspectorFact = {
  key: string;
  label: string;
  value: string;
};

export type NodeInspection = {
  type: string;
  typeLabel: string;
  layer: string;
  purpose: string;
  name: string;
  qualifiedName: string;
  file?: string;
  context?: string | null;
  roles: string[];
  facts: InspectorFact[];
  inputs: InspectorLink[];
  outputs: InspectorLink[];
  extraInputs: number;
  extraOutputs: number;
};

export function typePurpose(type: string): string {
  if (TYPE_PURPOSE[type]) return TYPE_PURPOSE[type];
  if (type.startsWith("react.")) return "A React node on the load path.";
  if (type.startsWith("django.")) return "A Django node on the load path.";
  if (type.startsWith("openapi.")) return "A stitch node between Django and React.";
  return "A node on the architecture graph.";
}

export function inspectNode(
  node: GraphNode,
  nodes: GraphNode[],
  edges: GraphEdge[],
): NodeInspection {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const roles: string[] = [];
  if (SINK_TYPES.has(node.type)) roles.push("sink");
  if (CONTRACT_TYPES.has(node.type)) roles.push("contract");
  const extra = node.extra ?? {};
  if (extra.inferred) roles.push("inferred");
  if (extra.generated) roles.push("generated");
  if (extra.mutation) roles.push("mutation");
  if (extra.fbv) roles.push("function view");
  if (extra.ninja) roles.push("ninja");

  const incoming = edges.filter((e) => e.dst === node.id);
  const outgoing = edges.filter((e) => e.src === node.id);
  const inputs = incoming.slice(0, LINK_LIMIT).map((e) => toLink(e, byId, e.src));
  const outputs = outgoing.slice(0, LINK_LIMIT).map((e) => toLink(e, byId, e.dst));

  const loc = node.file_path
    ? `${node.file_path}${node.start_line ? `:${node.start_line}` : ""}`
    : undefined;

  return {
    type: node.type,
    typeLabel: kindLabel(typeLabel(node.type)),
    layer: LAYER_LABELS[layerFor(node.type)] ?? "other",
    purpose: typePurpose(node.type),
    name: node.name,
    qualifiedName: node.qualified_name,
    file: loc,
    context: node.context,
    roles,
    facts: factsFromExtra(extra).filter((fact) => !(fact.key === "app" && fact.value === node.context)),
    inputs,
    outputs,
    extraInputs: Math.max(0, incoming.length - LINK_LIMIT),
    extraOutputs: Math.max(0, outgoing.length - LINK_LIMIT),
  };
}

function toLink(edge: GraphEdge, byId: Map<string, GraphNode>, otherId: string): InspectorLink {
  const other = byId.get(otherId);
  const fallback = otherId.includes(":") ? otherId.slice(otherId.indexOf(":") + 1) : otherId;
  return {
    id: otherId,
    name: other?.name || fallback,
    type: other?.type || "",
    typeLabel: other ? kindLabel(typeLabel(other.type)) : "",
    edgeType: edge.type,
    edgeLabel: kindLabel(edge.type),
    inferred: edge.confidence < 0.8,
  };
}

export function factsFromExtra(extra: Record<string, unknown>): InspectorFact[] {
  const keys = [
    ...FACT_ORDER.filter((k) => k in extra),
    ...Object.keys(extra).filter((k) => !FACT_ORDER.includes(k) && !HIDDEN_EXTRA_KEYS.has(k)),
  ];
  const facts: InspectorFact[] = [];
  const seen = new Set<string>();
  for (const key of keys) {
    if (seen.has(key) || HIDDEN_EXTRA_KEYS.has(key) || ROLE_FACT_KEYS.has(key)) continue;
    seen.add(key);
    const formatted = formatFact(key, extra[key]);
    if (formatted == null) continue;
    facts.push({
      key,
      label: FACT_LABELS[key] ?? kindLabel(key),
      value: formatted,
    });
  }
  return facts;
}

function formatFact(key: string, raw: unknown): string | null {
  if (raw == null) return null;
  if (typeof raw === "boolean") {
    if (!raw && !ALWAYS_SHOW_FALSE.has(key)) return null;
    return raw ? "yes" : "no";
  }
  if (typeof raw === "number") return String(raw);
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    return trimmed || null;
  }
  if (Array.isArray(raw)) {
    const items = raw
      .map((item) => (typeof item === "string" || typeof item === "number" ? String(item) : ""))
      .filter(Boolean);
    if (!items.length) return null;
    const shown = items.slice(0, LIST_LIMIT);
    const more = items.length - shown.length;
    return more > 0 ? `${shown.join(", ")} +${more} more` : shown.join(", ");
  }
  return null;
}
