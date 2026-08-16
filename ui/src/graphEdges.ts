import { GRAPH_NODE_HEIGHT, GRAPH_NODE_WIDTH, layoutNodes, type GraphEdge, type GraphNode } from "./types";

const HORIZONTAL_EPS = 12;
const Y_PAD = 6;
const STEP_LO = 0.22;
const STEP_HI = 0.78;

type Span = {
  id: string;
  y0: number;
  y1: number;
  corridor: string;
};

/** Spread overlapping smooth-step bends so parallel verticals do not share one x. */
export function assignEdgeStepPositions(
  nodes: GraphNode[],
  edges: GraphEdge[],
  pos?: Map<string, { x: number; y: number }>,
): Map<string, number> {
  const placed = pos ?? layoutNodes(nodes, edges);
  const spans: Span[] = [];
  for (const edge of edges) {
    const src = placed.get(edge.src);
    const dst = placed.get(edge.dst);
    if (!src || !dst) continue;
    const sourceY = src.y + GRAPH_NODE_HEIGHT / 2;
    const targetY = dst.y + GRAPH_NODE_HEIGHT / 2;
    if (Math.abs(sourceY - targetY) < HORIZONTAL_EPS) continue;
    const sourceX = src.x + GRAPH_NODE_WIDTH;
    const targetX = dst.x;
    spans.push({
      id: edge.id,
      y0: Math.min(sourceY, targetY),
      y1: Math.max(sourceY, targetY),
      corridor: `${Math.round(sourceX / 8)}>${Math.round(targetX / 8)}`,
    });
  }

  const groups = new Map<string, Span[]>();
  for (const span of spans) {
    const list = groups.get(span.corridor) ?? [];
    list.push(span);
    groups.set(span.corridor, list);
  }

  const steps = new Map<string, number>();
  for (const group of groups.values()) {
    const sorted = [...group].sort((a, b) => a.y0 - b.y0 || a.y1 - b.y1 || a.id.localeCompare(b.id));
    const lanes: Span[][] = [];
    const laneOf = new Map<string, number>();
    for (const span of sorted) {
      let lane = lanes.findIndex((items) => items.every((other) => !yOverlap(span, other)));
      if (lane < 0) {
        lane = lanes.length;
        lanes.push([]);
      }
      lanes[lane].push(span);
      laneOf.set(span.id, lane);
    }
    const n = lanes.length;
    for (const span of group) {
      steps.set(span.id, stepForLane(laneOf.get(span.id) ?? 0, n));
    }
  }
  return steps;
}

function yOverlap(a: Span, b: Span): boolean {
  return a.y0 < b.y1 + Y_PAD && b.y0 < a.y1 + Y_PAD;
}

export function stepForLane(lane: number, laneCount: number): number {
  if (laneCount <= 1) return 0.5;
  return STEP_LO + ((STEP_HI - STEP_LO) * lane) / (laneCount - 1);
}
