import {
  GRAPH_COL_GAP,
  GRAPH_NODE_HEIGHT,
  GRAPH_NODE_WIDTH,
  layoutNodes,
  type GraphEdge,
  type GraphNode,
} from "./types";

const HORIZONTAL_EPS = 12;
const STEP_LO = 0.2;
const STEP_HI = 0.8;
/** Adjacent stacked steps sit ~one node apart; reuse a vertical only beyond that. */
const CLEARANCE = GRAPH_NODE_HEIGHT;

type Span = {
  id: string;
  y0: number;
  y1: number;
  sourceX: number;
  targetX: number;
  corridor: string;
};

/** Offset bent edges whose verticals would overlap so parallel routes stay distinct. */
export function assignEdgeStepPositions(
  nodes: GraphNode[],
  edges: GraphEdge[],
  pos?: Map<string, { x: number; y: number }>,
): Map<string, number> {
  const placed = pos ?? layoutNodes(nodes, edges);
  const colXs = [...new Set([...placed.values()].map((p) => p.x))].sort((a, b) => a - b);
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
    const gap = targetX - sourceX;
    if (gap < HORIZONTAL_EPS) continue;
    const y0 = Math.min(sourceY, targetY);
    const y1 = Math.max(sourceY, targetY);
    spans.push({
      id: edge.id,
      y0,
      y1,
      sourceX,
      targetX,
      corridor: `${Math.round(sourceX / 8)}`,
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
    const laneOf = lanesFor(sorted);
    const laneCount = Math.max(0, ...laneOf.values()) + 1;
    const sourceX = sorted[0]!.sourceX;
    const gutter = gapAfter(colXs, sourceX);
    for (const span of sorted) {
      const t = stepForLane(laneOf.get(span.id) ?? 0, laneCount);
      const denom = span.targetX - span.sourceX;
      if (Math.abs(denom - gutter) < 0.5) {
        steps.set(span.id, t);
        continue;
      }
      const laneX = span.sourceX + gutter * t;
      steps.set(span.id, Math.min(0.92, Math.max(0.08, (laneX - span.sourceX) / denom)));
    }
  }
  return steps;
}

function gapAfter(colXs: number[], sourceX: number): number {
  const colX = sourceX - GRAPH_NODE_WIDTH;
  const next = colXs.find((x) => x > colX + 1);
  if (next === undefined) return GRAPH_COL_GAP;
  return Math.max(GRAPH_COL_GAP, next - sourceX);
}

/** First-fit coloring: two verticals share an x only when their y ranges stay apart. */
function lanesFor(spans: Span[]): Map<string, number> {
  const laneEnds: number[] = [];
  const laneOf = new Map<string, number>();
  for (const span of spans) {
    let lane = -1;
    for (let i = 0; i < laneEnds.length; i++) {
      if (span.y0 > laneEnds[i]! + CLEARANCE) {
        lane = i;
        break;
      }
    }
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(span.y1);
    } else {
      laneEnds[lane] = Math.max(laneEnds[lane]!, span.y1);
    }
    laneOf.set(span.id, lane);
  }
  return laneOf;
}

export function stepForLane(lane: number, laneCount: number): number {
  if (laneCount <= 1) return 0.5;
  return STEP_LO + ((STEP_HI - STEP_LO) * lane) / (laneCount - 1);
}
