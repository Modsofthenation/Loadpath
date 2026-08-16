import { describe, expect, it } from "vitest";
import { assignEdgeStepPositions, stepForLane } from "./graphEdges";
import type { GraphEdge, GraphNode } from "./types";

function node(id: string, type: string): GraphNode {
  return { id, type, name: id, qualified_name: id };
}

function edge(src: string, dst: string): GraphEdge {
  return { id: `${src}->${dst}`, src, dst, type: "uses", weight: "cheap", confidence: 1 };
}

describe("assignEdgeStepPositions", () => {
  it("staggers overlapping column-to-column edges so they do not share a bend", () => {
    const nodes = [
      node("r1", "django.route"),
      node("r2", "django.route"),
      node("v1", "django.view"),
      node("v2", "django.view"),
    ];
    const pos = new Map([
      ["r1", { x: 0, y: 0 }],
      ["r2", { x: 0, y: 92 }],
      ["v1", { x: 296, y: 0 }],
      ["v2", { x: 296, y: 184 }],
    ]);
    const edges = [edge("r1", "v2"), edge("r2", "v2")];
    const steps = assignEdgeStepPositions(nodes, edges, pos);
    expect(steps.get("r1->v2")).toBeDefined();
    expect(steps.get("r2->v2")).toBeDefined();
    expect(steps.get("r1->v2")).not.toBe(steps.get("r2->v2"));
    expect(Math.abs((steps.get("r1->v2") ?? 0) - (steps.get("r2->v2") ?? 0))).toBeGreaterThan(0.3);
  });

  it("keeps far-apart edges on the default midpoint bend", () => {
    const nodes = [node("r1", "django.route"), node("r2", "django.route"), node("v1", "django.view"), node("v2", "django.view")];
    const pos = new Map([
      ["r1", { x: 0, y: 0 }],
      ["r2", { x: 0, y: 400 }],
      ["v1", { x: 296, y: 0 }],
      ["v2", { x: 296, y: 400 }],
    ]);
    const edges = [edge("r1", "v1"), edge("r2", "v2")];
    const steps = assignEdgeStepPositions(nodes, edges, pos);
    expect(steps.size).toBe(0);
  });

  it("spreads lanes between 0.22 and 0.78", () => {
    expect(stepForLane(0, 1)).toBe(0.5);
    expect(stepForLane(0, 2)).toBe(0.22);
    expect(stepForLane(1, 2)).toBe(0.78);
  });
});
