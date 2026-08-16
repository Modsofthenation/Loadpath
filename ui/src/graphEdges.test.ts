import { getSmoothStepPath, Position } from "@xyflow/react";
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

  it("separates stacked route-to-view verticals that would read as one bus", () => {
    const nodes = [node("r1", "django.route"), node("r2", "django.route"), node("v1", "django.view"), node("v2", "django.view")];
    const pos = new Map([
      ["r1", { x: 0, y: 0 }],
      ["r2", { x: 0, y: 92 }],
      ["v1", { x: 296, y: 48 }],
      ["v2", { x: 296, y: 140 }],
    ]);
    const edges = [edge("r1", "v1"), edge("r2", "v2")];
    const steps = assignEdgeStepPositions(nodes, edges, pos);
    expect(steps.get("r1->v1")).toBe(0.2);
    expect(steps.get("r2->v2")).toBe(0.8);
  });

  it("reuses a vertical when two bent edges are far apart in y", () => {
    const nodes = [node("r1", "django.route"), node("r2", "django.route"), node("v1", "django.view"), node("v2", "django.view")];
    const pos = new Map([
      ["r1", { x: 0, y: 0 }],
      ["r2", { x: 0, y: 400 }],
      ["v1", { x: 296, y: 48 }],
      ["v2", { x: 296, y: 448 }],
    ]);
    const edges = [edge("r1", "v1"), edge("r2", "v2")];
    const steps = assignEdgeStepPositions(nodes, edges, pos);
    expect(steps.get("r1->v1")).toBe(0.5);
    expect(steps.get("r2->v2")).toBe(0.5);
  });

  it("spreads lanes between 0.2 and 0.8", () => {
    expect(stepForLane(0, 1)).toBe(0.5);
    expect(stepForLane(0, 2)).toBe(0.2);
    expect(stepForLane(1, 2)).toBe(0.8);
  });
});

describe("getSmoothStepPath stepPosition", () => {
  it("moves the vertical segment when stepPosition changes", () => {
    const shared = {
      sourceX: 208,
      sourceY: 32,
      targetY: 120,
      targetX: 336,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    };
    const [left] = getSmoothStepPath({ ...shared, stepPosition: 0.2 });
    const [right] = getSmoothStepPath({ ...shared, stepPosition: 0.8 });
    expect(left).not.toBe(right);
  });
});
