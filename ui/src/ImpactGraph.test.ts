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
    expect(rfEdges[0].label).toBeUndefined();
  });

  it("labels only edges incident to the selected node", () => {
    const extraNodes: GraphNode[] = [
      ...nodes,
      { id: "model", type: "django.model", name: "Invoice", qualified_name: "billing.Invoice" },
    ];
    const extra: GraphEdge = {
      id: "other",
      src: "ser",
      dst: "model",
      type: "serializes",
      weight: "cheap",
      confidence: 1,
    };
    const { rfEdges } = toReactFlowElements(extraNodes, [...edges, extra], "view");
    expect(rfEdges.find((e) => e.id === "ok")?.label).toBe("uses serializer");
    expect(rfEdges.find((e) => e.id === "other")?.label).toBeUndefined();
  });
});
