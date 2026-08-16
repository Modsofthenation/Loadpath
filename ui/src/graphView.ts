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
export type GraphLayoutId =
  | "layers"
  | "flow"
  | "tree"
  | "radial"
  | "concentric"
  | "circle"
  | "clusters"
  | "grid"
  | "force";

export const GRAPH_LAYOUTS: { id: GraphLayoutId; label: string }[] = [
  { id: "layers", label: "Architecture layers" },
  { id: "flow", label: "Edge flow" },
  { id: "tree", label: "Spanning tree" },
  { id: "radial", label: "Radial" },
  { id: "concentric", label: "Concentric layers" },
  { id: "circle", label: "Circle" },
  { id: "clusters", label: "Type clusters" },
  { id: "grid", label: "Compact grid" },
  { id: "force", label: "Force directed" },
];

const GRAPH_LAYOUT_IDS = new Set<GraphLayoutId>(GRAPH_LAYOUTS.map((item) => item.id));
const LAYOUT_STORAGE = "loadpath.graphLayout";
const LAYOUT_PASSES = 8;
const FORCE_ITERS = 64;
const MIN_ARC = GRAPH_NODE_WIDTH + 32;
const COL_PITCH = GRAPH_NODE_WIDTH + GRAPH_COL_GAP;
const ROW_PITCH = GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP;

export const PATH_SINK_TYPES = new Set([
  "django.route",
  "react.route",
  "react.page",
  "react.server_action",
  "django.task",
  "django.migration_op",
  "django.permission",
  "openapi.path",
  "django.consumer",
  "django.websocket_route",
  "django.template",
  "graphql.operation",
  "fastapi.route",
]);

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

export function searchNodes(nodes: GraphNode[], query: string): GraphNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return nodes
    .filter((n) => {
      const hay = `${n.name} ${n.qualified_name} ${n.type} ${n.file_path || ""} ${n.context || ""}`.toLowerCase();
      return hay.includes(q);
    })
    .slice(0, 24);
}

export function isolatePathIds(
  nodes: GraphNode[],
  edges: GraphEdge[],
  sourceId: string,
  targetId?: string | null,
): { nodeIds: Set<string>; edgeIds: Set<string> } {
  const ids = new Set(nodes.map((n) => n.id));
  if (!ids.has(sourceId)) return { nodeIds: new Set(), edgeIds: new Set() };
  const succ = new Map<string, { dst: string; id: string }[]>();
  const pred = new Map<string, { src: string; id: string }[]>();
  for (const e of edges) {
    if (!ids.has(e.src) || !ids.has(e.dst)) continue;
    const s = succ.get(e.src) ?? [];
    s.push({ dst: e.dst, id: e.id });
    succ.set(e.src, s);
    const p = pred.get(e.dst) ?? [];
    p.push({ src: e.src, id: e.id });
    pred.set(e.dst, p);
  }
  const sinks = new Set(nodes.filter((n) => PATH_SINK_TYPES.has(n.type)).map((n) => n.id));
  const targets = targetId && ids.has(targetId) ? new Set([targetId]) : sinks.size ? sinks : ids;

  const reachable = new Set<string>();
  const stack = [sourceId];
  while (stack.length) {
    const cur = stack.pop()!;
    if (reachable.has(cur)) continue;
    reachable.add(cur);
    for (const nxt of succ.get(cur) ?? []) {
      if (!reachable.has(nxt.dst)) stack.push(nxt.dst);
    }
  }
  const keep = new Set<string>([sourceId]);
  const back = [...targets].filter((t) => reachable.has(t));
  const seen = new Set(back);
  while (back.length) {
    const cur = back.pop()!;
    keep.add(cur);
    for (const prev of pred.get(cur) ?? []) {
      if (reachable.has(prev.src) && !seen.has(prev.src)) {
        seen.add(prev.src);
        back.push(prev.src);
      }
    }
  }
  const edgeIds = new Set<string>();
  for (const e of edges) {
    if (keep.has(e.src) && keep.has(e.dst)) edgeIds.add(e.id);
  }
  return { nodeIds: keep, edgeIds };
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
  try {
    if (typeof localStorage === "undefined") return "layers";
    const raw = localStorage.getItem(LAYOUT_STORAGE);
    return raw && GRAPH_LAYOUT_IDS.has(raw as GraphLayoutId) ? (raw as GraphLayoutId) : "layers";
  } catch {
    return "layers";
  }
}

export function writeGraphLayout(id: GraphLayoutId): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(LAYOUT_STORAGE, id);
  } catch {
    /* ignore quota / private-mode */
  }
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

function byLayerThenName(a: GraphNode, b: GraphNode): number {
  return layerFor(a.type) - layerFor(b.type) || byName(a, b);
}

function placeRing(
  ring: GraphNode[],
  radius: number,
  pos: Map<string, { x: number; y: number }>,
): void {
  ring.forEach((n, i) => {
    const theta = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(ring.length, 1);
    pos.set(n.id, { x: Math.cos(theta) * radius, y: Math.sin(theta) * radius });
  });
}

function ringRadius(count: number, ringIndex: number): number {
  return Math.max(
    ringIndex * COL_PITCH,
    count <= 1 ? (ringIndex === 0 ? 0 : GRAPH_NODE_WIDTH) : (count * MIN_ARC) / (2 * Math.PI),
  );
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
  const cap = Math.max(nodes.length - 1, 0);
  const rank = new Map<string, number>();
  for (const n of nodes) rank.set(n.id, 0);
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false;
    for (const e of edges) {
      if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
      const next = Math.min((rank.get(e.src) || 0) + 1, cap);
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

function layoutCircle(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const ordered = [...nodes].sort(byLayerThenName);
  if (ordered.length <= 1) {
    if (ordered[0]) pos.set(ordered[0].id, { x: 0, y: 0 });
    return pos;
  }
  placeRing(ordered, ringRadius(ordered.length, 1), pos);
  return pos;
}

function layoutConcentric(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (!nodes.length) return pos;
  const rings = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const layer = layerFor(n.type);
    const list = rings.get(layer) ?? [];
    list.push(n);
    rings.set(layer, list);
  }
  const layers = [...rings.keys()].sort((a, b) => a - b);
  layers.forEach((layer, d) => {
    const ring = (rings.get(layer) ?? []).sort(byName);
    if (d === 0 && ring.length === 1) {
      pos.set(ring[0]!.id, { x: 0, y: 0 });
      return;
    }
    placeRing(ring, ringRadius(ring.length, d === 0 ? 1 : d), pos);
  });
  return pos;
}

function layoutClusters(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (!nodes.length) return pos;
  const groups = new Map<string, GraphNode[]>();
  for (const n of nodes) {
    const list = groups.get(n.type) ?? [];
    list.push(n);
    groups.set(n.type, list);
  }
  const types = [...groups.keys()].sort((a, b) => layerFor(a) - layerFor(b) || a.localeCompare(b));
  const packed = types.map((type) => {
    const members = (groups.get(type) ?? []).sort(byName);
    const cols = Math.max(1, Math.ceil(Math.sqrt(members.length)));
    const rows = Math.ceil(members.length / cols);
    return {
      members,
      cols,
      width: Math.max(0, cols - 1) * COL_PITCH,
      height: Math.max(0, rows - 1) * ROW_PITCH,
    };
  });
  const maxSpan = Math.max(...packed.map((g) => Math.hypot(g.width, g.height) / 2 + GRAPH_NODE_WIDTH), GRAPH_NODE_WIDTH);
  const radius =
    packed.length <= 1 ? 0 : Math.max(COL_PITCH, (packed.length * (maxSpan * 2 + GRAPH_COL_GAP)) / (2 * Math.PI));
  packed.forEach((group, tIndex) => {
    const theta = packed.length === 1 ? 0 : -Math.PI / 2 + (2 * Math.PI * tIndex) / packed.length;
    const cx = Math.cos(theta) * radius;
    const cy = Math.sin(theta) * radius;
    group.members.forEach((n, i) => {
      const col = i % group.cols;
      const row = Math.floor(i / group.cols);
      pos.set(n.id, {
        x: cx - group.width / 2 + col * COL_PITCH,
        y: cy - group.height / 2 + row * ROW_PITCH,
      });
    });
  });
  return pos;
}

function layoutTree(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (!nodes.length) return pos;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ids = new Set(byId.keys());
  const outgoing = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  for (const n of nodes) {
    outgoing.set(n.id, []);
    indeg.set(n.id, 0);
  }
  for (const e of edges) {
    if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
    outgoing.get(e.src)!.push(e.dst);
    indeg.set(e.dst, (indeg.get(e.dst) || 0) + 1);
  }
  for (const [id, list] of outgoing) {
    const unique = [...new Set(list)];
    unique.sort((a, b) => byName(byId.get(a)!, byId.get(b)!));
    outgoing.set(id, unique);
  }

  const roots: GraphNode[] = nodes.filter((n) => (indeg.get(n.id) || 0) === 0).sort(byName);
  if (!roots.length) {
    const fallback = [...nodes].sort(
      (a, b) => (outgoing.get(b.id)?.length || 0) - (outgoing.get(a.id)?.length || 0) || byName(a, b),
    )[0]!;
    roots.push(fallback);
  }

  const inTree = new Set<string>();
  const treeKids = new Map<string, string[]>();
  for (const n of nodes) treeKids.set(n.id, []);
  const grow = (id: string) => {
    inTree.add(id);
    for (const kid of outgoing.get(id) ?? []) {
      if (inTree.has(kid)) continue;
      treeKids.get(id)!.push(kid);
      grow(kid);
    }
  };
  for (const root of roots) {
    if (!inTree.has(root.id)) grow(root.id);
  }
  for (const n of [...nodes].sort(byName)) {
    if (inTree.has(n.id)) continue;
    roots.push(n);
    grow(n.id);
  }

  let leaf = 0;
  const place = (id: string, depth: number) => {
    const kids = treeKids.get(id) ?? [];
    if (!kids.length) {
      pos.set(id, { x: leaf * COL_PITCH, y: depth * ROW_PITCH });
      leaf += 1;
      return;
    }
    const start = leaf;
    for (const kid of kids) place(kid, depth + 1);
    pos.set(id, { x: ((start + leaf - 1) / 2) * COL_PITCH, y: depth * ROW_PITCH });
  };
  for (const root of roots) {
    if (!pos.has(root.id)) place(root.id, 0);
  }
  return pos;
}

function separateNodes(pos: Map<string, { x: number; y: number }>, nodes: GraphNode[]): void {
  const minX = GRAPH_NODE_WIDTH + 24;
  const minY = GRAPH_NODE_HEIGHT + 16;
  for (let pass = 0; pass < 8; pass++) {
    for (let i = 0; i < nodes.length; i++) {
      const a = pos.get(nodes[i]!.id)!;
      for (let j = i + 1; j < nodes.length; j++) {
        const b = pos.get(nodes[j]!.id)!;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const overlapX = minX - Math.abs(dx);
        const overlapY = minY - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        if (overlapX < overlapY) {
          const push = overlapX / 2;
          const sign = dx < 0 ? -1 : 1;
          a.x -= sign * push;
          b.x += sign * push;
        } else {
          const push = overlapY / 2;
          const sign = dy < 0 ? -1 : 1;
          a.y -= sign * push;
          b.y += sign * push;
        }
      }
    }
  }
}

function layoutForce(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const ordered = [...nodes].sort(byLayerThenName);
  if (ordered.length <= 1) {
    if (ordered[0]) pos.set(ordered[0].id, { x: 0, y: 0 });
    return pos;
  }

  const n = ordered.length;
  const k = COL_PITCH;
  placeRing(ordered, ringRadius(n, 1), pos);

  const ids = new Set(ordered.map((node) => node.id));
  const links: [string, string][] = [];
  const seen = new Set<string>();
  for (const e of edges) {
    if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
    const a = e.src < e.dst ? e.src : e.dst;
    const b = e.src < e.dst ? e.dst : e.src;
    const key = `${a}|${b}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([a, b]);
  }

  const disp = new Map<string, { x: number; y: number }>();
  let temp = k;
  const iters = Math.min(FORCE_ITERS, 24 + n);
  for (let iter = 0; iter < iters; iter++) {
    for (const node of ordered) disp.set(node.id, { x: 0, y: 0 });
    for (let i = 0; i < n; i++) {
      const a = ordered[i]!;
      const pa = pos.get(a.id)!;
      for (let j = i + 1; j < n; j++) {
        const b = ordered[j]!;
        const pb = pos.get(b.id)!;
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) {
          dx = ((i % 2) * 2 - 1) * 0.01;
          dy = ((j % 2) * 2 - 1) * 0.01;
          dist = Math.hypot(dx, dy);
        }
        const force = (k * k) / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        const da = disp.get(a.id)!;
        const db = disp.get(b.id)!;
        da.x += fx;
        da.y += fy;
        db.x -= fx;
        db.y -= fy;
      }
    }
    for (const [src, dst] of links) {
      const pa = pos.get(src)!;
      const pb = pos.get(dst)!;
      const dx = pa.x - pb.x;
      const dy = pa.y - pb.y;
      const dist = Math.hypot(dx, dy) || 0.01;
      const force = (dist * dist) / k;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      const da = disp.get(src)!;
      const db = disp.get(dst)!;
      da.x -= fx;
      da.y -= fy;
      db.x += fx;
      db.y += fy;
    }
    for (const node of ordered) {
      const p = pos.get(node.id)!;
      const d = disp.get(node.id)!;
      const mag = Math.hypot(d.x, d.y) || 0.01;
      const limited = Math.min(mag, temp);
      p.x += (d.x / mag) * limited;
      p.y += (d.y / mag) * limited;
    }
    temp *= 0.9;
  }
  separateNodes(pos, ordered);
  return pos;
}

/** 2D positions for the selected layout. `layers` is the architecture-column default. */
export function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[] = [],
  layout: GraphLayoutId = "layers",
): Map<string, { x: number; y: number }> {
  if (layout === "flow") return layoutFlow(nodes, edges);
  if (layout === "tree") return layoutTree(nodes, edges);
  if (layout === "radial") return layoutRadial(nodes, edges);
  if (layout === "concentric") return layoutConcentric(nodes);
  if (layout === "circle") return layoutCircle(nodes);
  if (layout === "clusters") return layoutClusters(nodes);
  if (layout === "grid") return layoutGrid(nodes);
  if (layout === "force") return layoutForce(nodes, edges);
  return layoutNodes(nodes, edges);
}
