import { GRAPH_NODE_HEIGHT, GRAPH_NODE_WIDTH, layoutNodes, type GraphEdge, type GraphNode } from "./types";

const HORIZONTAL_EPS = 12;
const STEP_LO = 0.2;
const STEP_HI = 0.8;

type Span = {
  id: string;
  sourceY: number;
  corridor: string;
};

/** Give each bent edge in a column gap its own vertical so parallel routes do not share one x. */
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
      sourceY,
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
    const sorted = [...group].sort((a, b) => a.sourceY - b.sourceY || a.id.localeCompare(b.id));
    const n = sorted.length;
    sorted.forEach((span, i) => {
      steps.set(span.id, stepForLane(i, n));
    });
  }
  return steps;
}

export function stepForLane(lane: number, laneCount: number): number {
  if (laneCount <= 1) return 0.5;
  return STEP_LO + ((STEP_HI - STEP_LO) * lane) / (laneCount - 1);
}
