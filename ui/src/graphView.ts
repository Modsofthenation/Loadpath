import { layerFor, type GraphEdge, type GraphNode } from "./types";

export type GraphFamily = "django" | "react" | "stitch" | "arch";
export type GraphDetail = "overview" | "full";
export type GraphProjection = "2d" | "3d";

export const LARGE_GRAPH = 90;

/** Leaf noise that turns a load-path into an unreadable field cloud. */
export const OVERVIEW_HIDDEN_TYPES = new Set([
  "django.field",
  "django.serializer_field",
  "django.relation",
  "django.test",
  "react.test",
  "graphql.field",
  "django.url_name",
  "django.throttle",
]);

export const TYPE_COLOR: Record<string, string> = {
  "arch.context": "#edf2f4",
  "django.app": "#8d99ae",
  "django.route": "#4cc9f0",
  "django.url_name": "#4cc9f0",
  "django.view": "#4895ef",
  "django.viewset_action": "#4361ee",
  "django.permission": "#7b8cde",
  "django.serializer": "#f4a261",
  "django.form": "#e9c46a",
  "django.serializer_field": "#e9c46a",
  "django.service": "#90be6d",
  "django.model": "#2a9d8f",
  "django.field": "#8ac926",
  "django.task": "#e76f51",
  "django.receiver": "#e85d04",
  "django.signal": "#f4a261",
  "django.test": "#6c757d",
  "django.admin": "#adb5bd",
  "django.migration_op": "#9d4edd",
  "django.consumer": "#e76f51",
  "django.websocket_route": "#4cc9f0",
  "django.template": "#c77dff",
  "django.htmx": "#ff6b6b",
  "django.cache_key": "#6c757d",
  "django.feature_flag": "#f4a261",
  "django.side_effect": "#e85d04",
  "graphql.type": "#00bbf9",
  "graphql.operation": "#00bbf9",
  "fastapi.route": "#4cc9f0",
  "fastapi.model": "#f4a261",
  "openapi.path": "#00bbf9",
  "react.api_client": "#ff6b6b",
  "react.query_key": "#adb5bd",
  "react.hook": "#7b2cbf",
  "react.feature": "#9d4edd",
  "react.route": "#c77dff",
  "react.page": "#c77dff",
  "react.component": "#9d4edd",
  "react.form_schema": "#ffd166",
  "react.test": "#6c757d",
};

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const LAYER_GAP = 220;
const SPIRAL = 26;

export const LAYER_LABELS: Record<number, string> = {
  0: "context",
  1: "routes",
  2: "url names",
  3: "views",
  4: "serializers",
  5: "services",
  6: "models",
  7: "fields",
  8: "jobs / signals",
  9: "openapi",
  10: "api client",
  11: "hooks",
  12: "pages",
  13: "components",
  14: "forms / tests",
};

export function familyFor(type: string): GraphFamily {
  if (type.startsWith("react.")) return "react";
  if (type.startsWith("openapi.") || type.startsWith("graphql.") || type.startsWith("fastapi.")) return "stitch";
  if (type.startsWith("arch.")) return "arch";
  return "django";
}

export function colorForType(type: string): string {
  if (TYPE_COLOR[type]) return TYPE_COLOR[type];
  if (type.startsWith("react.")) return "#9d4edd";
  if (type.startsWith("openapi.")) return "#00bbf9";
  return "#4a5568";
}

export function defaultProjection(nodeCount: number): GraphProjection {
  return nodeCount >= LARGE_GRAPH ? "3d" : "2d";
}

export function defaultDetail(nodeCount: number): GraphDetail {
  return nodeCount >= LARGE_GRAPH ? "overview" : "full";
}

export function neighborIds(seed: string, edges: GraphEdge[], hops = 1): Set<string> {
  const ids = new Set<string>([seed]);
  let frontier = new Set<string>([seed]);
  for (let i = 0; i < hops; i += 1) {
    const next = new Set<string>();
    for (const edge of edges) {
      if (frontier.has(edge.src) && !ids.has(edge.dst)) {
        ids.add(edge.dst);
        next.add(edge.dst);
      }
      if (frontier.has(edge.dst) && !ids.has(edge.src)) {
        ids.add(edge.src);
        next.add(edge.src);
      }
    }
    frontier = next;
    if (!frontier.size) break;
  }
  return ids;
}

export function visibleGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts: {
    detail: GraphDetail;
    families: ReadonlySet<GraphFamily>;
    focusId?: string | null;
    neighborhoodOnly?: boolean;
  },
): { nodes: GraphNode[]; edges: GraphEdge[]; neighborIds: Set<string> } {
  let kept = nodes.filter((n) => opts.families.has(familyFor(n.type)));
  if (opts.detail === "overview") {
    kept = kept.filter((n) => !OVERVIEW_HIDDEN_TYPES.has(n.type));
  }
  const ids = new Set(kept.map((n) => n.id));
  const linked = edges.filter((e) => ids.has(e.src) && ids.has(e.dst));
  const neighbors = opts.focusId ? neighborIds(opts.focusId, linked, 1) : new Set<string>();
  if (opts.neighborhoodOnly && opts.focusId && neighbors.size) {
    kept = kept.filter((n) => neighbors.has(n.id));
    const focusIds = new Set(kept.map((n) => n.id));
    return {
      nodes: kept,
      edges: linked.filter((e) => focusIds.has(e.src) && focusIds.has(e.dst)),
      neighborIds: neighbors,
    };
  }
  return { nodes: kept, edges: linked, neighborIds: neighbors };
}

export function layoutNodes3d(nodes: GraphNode[]): Map<string, { x: number; y: number; z: number }> {
  const columns = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const layer = layerFor(n.type);
    const list = columns.get(layer) ?? [];
    list.push(n);
    columns.set(layer, list);
  }
  const pos = new Map<string, { x: number; y: number; z: number }>();
  for (const [layer, list] of columns) {
    list.sort((a, b) => a.name.localeCompare(b.name));
    const x = layer * LAYER_GAP;
    list.forEach((n, i) => {
      if (list.length === 1) {
        pos.set(n.id, { x, y: 0, z: 0 });
        return;
      }
      const r = SPIRAL * Math.sqrt(i + 1);
      const theta = i * GOLDEN_ANGLE;
      pos.set(n.id, { x, y: r * Math.cos(theta), z: r * Math.sin(theta) });
    });
  }
  return pos;
}

export function layerCenters(nodes: GraphNode[]): { layer: number; x: number; count: number }[] {
  const counts = new Map<number, number>();
  for (const n of nodes) {
    const layer = layerFor(n.type);
    counts.set(layer, (counts.get(layer) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([layer, count]) => ({ layer, x: layer * LAYER_GAP, count }));
}
