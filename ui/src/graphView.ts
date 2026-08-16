import {
  GRAPH_COL_GAP,
  GRAPH_NODE_HEIGHT,
  GRAPH_NODE_WIDTH,
  GRAPH_ROW_GAP,
  layerFor,
  layoutNodes,
  type GraphEdge,
  type GraphNode,
} from "./types";

export type GraphFamily = "django" | "react" | "stitch" | "arch";
export type GraphDetail = "overview" | "full";
export type GraphProjection = "2d" | "3d";
export type GraphLayoutId = "layers" | "flow" | "radial" | "grid";

export const GRAPH_LAYOUTS: { id: GraphLayoutId; label: string }[] = [
  { id: "layers", label: "Architecture layers" },
  { id: "flow", label: "Edge flow" },
  { id: "radial", label: "Radial" },
  { id: "grid", label: "Compact grid" },
];

const GRAPH_LAYOUT_IDS = new Set<GraphLayoutId>(GRAPH_LAYOUTS.map((item) => item.id));
const LAYOUT_STORAGE = "loadpath.graphLayout";
const LAYOUT_PASSES = 8;

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
  "react.server_action": "#e76f51",
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

export function readGraphLayout(): GraphLayoutId {
  if (typeof localStorage === "undefined") return "layers";
  const raw = localStorage.getItem(LAYOUT_STORAGE);
  return raw && GRAPH_LAYOUT_IDS.has(raw as GraphLayoutId) ? (raw as GraphLayoutId) : "layers";
}

export function writeGraphLayout(id: GraphLayoutId): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(LAYOUT_STORAGE, id);
}

export function layoutUsesColumns(layout: GraphLayoutId): boolean {
  return layout === "layers" || layout === "flow";
}

function median(values: number[]): number {
  if (!values.length) return Number.NaN;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

function byName(a: GraphNode, b: GraphNode): number {
  return a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
}

function placeColumns(order: GraphNode[][], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (!order.length) return pos;

  const ids = new Set(order.flat().map((n) => n.id));
  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  for (const n of order.flat()) {
    preds.set(n.id, []);
    succs.set(n.id, []);
  }
  for (const e of edges) {
    if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
    succs.get(e.src)!.push(e.dst);
    preds.get(e.dst)!.push(e.src);
  }

  const colOf = new Map<string, number>();
  order.forEach((col, colIndex) => {
    for (const n of col) colOf.set(n.id, colIndex);
  });

  const rank = new Map<string, number>();
  const refreshRanks = () => {
    for (const col of order) col.forEach((n, i) => rank.set(n.id, i));
  };
  refreshRanks();

  const sortByBarycenter = (col: GraphNode[], neighborsOf: (id: string) => string[]) => {
    const keyed = col.map((n, i) => {
      const nbrs = neighborsOf(n.id)
        .map((id) => rank.get(id))
        .filter((v): v is number => v !== undefined);
      const bary = median(nbrs);
      return { n, bary: Number.isNaN(bary) ? i : bary, name: n.name, id: n.id };
    });
    keyed.sort((a, b) => a.bary - b.bary || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
    return keyed.map((k) => k.n);
  };
  const inColumn = (colIndex: number) => (nbr: string) => colOf.get(nbr) === colIndex;

  for (let pass = 0; pass < LAYOUT_PASSES; pass++) {
    for (let i = 1; i < order.length; i++) {
      order[i] = sortByBarycenter(order[i]!, (id) => (preds.get(id) ?? []).filter(inColumn(i - 1)));
      refreshRanks();
    }
    for (let i = order.length - 2; i >= 0; i--) {
      order[i] = sortByBarycenter(order[i]!, (id) => (succs.get(id) ?? []).filter(inColumn(i + 1)));
      refreshRanks();
    }
  }

  const colPitch = GRAPH_NODE_WIDTH + GRAPH_COL_GAP;
  const rowPitch = GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP;
  const maxRows = Math.max(...order.map((col) => col.length), 1);
  order.forEach((col, colIndex) => {
    const y0 = ((maxRows - col.length) * rowPitch) / 2;
    col.forEach((n, i) => {
      pos.set(n.id, { x: colIndex * colPitch, y: y0 + i * rowPitch });
    });
  });
  return pos;
}

function layoutFlow(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const ids = new Set(nodes.map((n) => n.id));
  const rank = new Map<string, number>();
  for (const n of nodes) rank.set(n.id, 0);
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false;
    for (const e of edges) {
      if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
      const next = (rank.get(e.src) || 0) + 1;
      if (next > (rank.get(e.dst) || 0)) {
        rank.set(e.dst, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const byRank = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const r = rank.get(n.id) || 0;
    const list = byRank.get(r) ?? [];
    list.push(n);
    byRank.set(r, list);
  }
  const order = [...byRank.keys()]
    .sort((a, b) => a - b)
    .map((r) => (byRank.get(r) ?? []).sort(byName));
  return placeColumns(order, edges);
}

function layoutRadial(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (!nodes.length) return pos;
  const ids = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, string[]>();
  const degree = new Map<string, number>();
  for (const n of nodes) {
    adj.set(n.id, []);
    degree.set(n.id, 0);
  }
  for (const e of edges) {
    if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
    adj.get(e.src)!.push(e.dst);
    adj.get(e.dst)!.push(e.src);
    degree.set(e.src, (degree.get(e.src) || 0) + 1);
    degree.set(e.dst, (degree.get(e.dst) || 0) + 1);
  }
  const root =
    [...nodes].sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0) || byName(a, b))[0] ?? nodes[0]!;

  const depth = new Map<string, number>();
  const rings: GraphNode[][] = [[root]];
  depth.set(root.id, 0);
  const queue = [root];
  while (queue.length) {
    const cur = queue.shift()!;
    const d = depth.get(cur.id) || 0;
    const nbrs = (adj.get(cur.id) ?? [])
      .map((id) => nodes.find((n) => n.id === id))
      .filter((n): n is GraphNode => Boolean(n))
      .sort(byName);
    for (const nbr of nbrs) {
      if (depth.has(nbr.id)) continue;
      depth.set(nbr.id, d + 1);
      const ring = rings[d + 1] ?? [];
      ring.push(nbr);
      rings[d + 1] = ring;
      queue.push(nbr);
    }
  }
  const leftover = nodes.filter((n) => !depth.has(n.id)).sort(byName);
  if (leftover.length) rings.push(leftover);

  const minArc = GRAPH_NODE_WIDTH + 32;
  rings.forEach((ring, d) => {
    if (d === 0 && ring.length === 1) {
      pos.set(ring[0]!.id, { x: 0, y: 0 });
      return;
    }
    const radius = Math.max(
      d * (GRAPH_NODE_WIDTH + GRAPH_COL_GAP),
      ring.length <= 1 ? GRAPH_NODE_WIDTH : (ring.length * minArc) / (2 * Math.PI),
    );
    ring.forEach((n, i) => {
      const theta = -Math.PI / 2 + (2 * Math.PI * i) / ring.length;
      pos.set(n.id, { x: Math.cos(theta) * radius, y: Math.sin(theta) * radius });
    });
  });
  return pos;
}

function layoutGrid(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const sorted = [...nodes].sort((a, b) => layerFor(a.type) - layerFor(b.type) || byName(a, b));
  const cols = Math.max(1, Math.ceil(Math.sqrt(sorted.length)));
  const colPitch = GRAPH_NODE_WIDTH + GRAPH_COL_GAP;
  const rowPitch = GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP;
  sorted.forEach((n, i) => {
    pos.set(n.id, {
      x: (i % cols) * colPitch,
      y: Math.floor(i / cols) * rowPitch,
    });
  });
  return pos;
}

/** 2D positions for the selected layout. `layers` is the architecture-column default. */
export function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[] = [],
  layout: GraphLayoutId = "layers",
): Map<string, { x: number; y: number }> {
  if (layout === "flow") return layoutFlow(nodes, edges);
  if (layout === "radial") return layoutRadial(nodes, edges);
  if (layout === "grid") return layoutGrid(nodes);
  return layoutNodes(nodes, edges);
}
