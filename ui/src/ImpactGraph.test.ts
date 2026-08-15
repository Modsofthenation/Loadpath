import { describe, expect, it } from "vitest";
import { MarkerType, Position } from "@xyflow/react";
import { toReactFlowElements } from "./ImpactGraph";
import type { GraphEdge, GraphNode } from "./types";

const nodes: GraphNode[] = [
  { id: "view", type: "django.view", name: "InvoiceView", qualified_name: "billing.InvoiceView" },
  { id: "ser", type: "django.serializer", name: "InvoiceSerializer", qualified_name: "billing.InvoiceSerializer" },
];

const edges: GraphEdge[] = [
  { id: "ok", src: "view", dst: "ser", type: "uses_serializer", weight: "cheap", confidence: 1 },
  { id: "ghost", src: "view", dst: "missing", type: "calls", weight: "cheap", confidence: 1 },
];

describe("toReactFlowElements", () => {
  it("drops dangling edges and attaches remaining edges left-to-right", () => {
    const { rfNodes, rfEdges } = toReactFlowElements(nodes, edges);
    expect(rfNodes.map((n) => n.id)).toEqual(["view", "ser"]);
    expect(rfNodes.every((n) => n.sourcePosition === Position.Right)).toBe(true);
    expect(rfNodes.every((n) => n.targetPosition === Position.Left)).toBe(true);
    expect(rfEdges).toHaveLength(1);
    expect(rfEdges[0]).toMatchObject({
      id: "ok",
      source: "view",
      target: "ser",
      type: "smoothstep",
    });
    expect(rfEdges[0].markerEnd).toMatchObject({ type: MarkerType.ArrowClosed });
  });
});
