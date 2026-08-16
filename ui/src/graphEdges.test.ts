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
    expect(steps.get("r1->v1")).toBeCloseTo(0.2);
    expect(steps.get("r2->v2")).toBeCloseTo(0.8);
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

  it("puts skip-column and next-column edges on the same pixel tracks", () => {
    const nodes = [
      node("r1", "django.route"),
      node("r2", "django.route"),
      node("u", "django.url_name"),
      node("v1", "django.view"),
      node("v2", "django.view"),
    ];
    const pos = new Map([
      ["r1", { x: 0, y: 0 }],
      ["r2", { x: 0, y: 92 }],
      ["u", { x: 296, y: 0 }],
      ["v1", { x: 592, y: 184 }],
      ["v2", { x: 592, y: 276 }],
    ]);
    const edges = [edge("r1", "v1"), edge("r2", "u")];
    const steps = assignEdgeStepPositions(nodes, edges, pos);
    const srcX = 208;
    const laneX = (dst: number, step: number) => srcX + 20 + (dst - srcX - 40) * step;
    const xNext = laneX(296, steps.get("r2->u") ?? 0);
    const xSkip = laneX(592, steps.get("r1->v1") ?? 0);
    expect(Math.abs(xNext - xSkip)).toBeGreaterThan(20);
  });

  it("bends skip-column edges in the first gap so they do not sit on the next column", () => {
    const nodes = [
      node("r", "django.route"),
      node("u", "django.url_name"),
      node("v", "django.view"),
    ];
    const pos = new Map([
      ["r", { x: 0, y: 0 }],
      ["u", { x: 296, y: 92 }],
      ["v", { x: 592, y: 184 }],
    ]);
    const steps = assignEdgeStepPositions(nodes, [edge("r", "v")], pos);
    const step = steps.get("r->v") ?? 0.5;
    const srcX = 208;
    const laneX = srcX + 20 + (592 - srcX - 40) * step;
    expect(laneX).toBeLessThan(296);
  });

  it("gives two skip-column edges from one node distinct first-gap verticals", () => {
    const nodes = [
      node("v", "django.view"),
      node("c", "django.cache_key"),
      node("f", "django.feature_flag"),
      node("s", "django.serializer"),
    ];
    const pos = new Map([
      ["v", { x: 0, y: 184 }],
      ["s", { x: 296, y: 184 }],
      ["c", { x: 592, y: 0 }],
      ["f", { x: 592, y: 92 }],
    ]);
    const steps = assignEdgeStepPositions(nodes, [edge("v", "c"), edge("v", "f")], pos);
    const srcX = 208;
    const laneX = (dst: number, step: number) => srcX + 20 + (dst - srcX - 40) * step;
    const xc = laneX(592, steps.get("v->c") ?? 0.5);
    const xf = laneX(592, steps.get("v->f") ?? 0.5);
    expect(Math.abs(xc - xf)).toBeGreaterThan(20);
  });

  it("clamps skip-step into 0..1 when the next column is unusually close", () => {
    const nodes = [node("r", "django.route"), node("v", "django.view")];
    const pos = new Map([
      ["r", { x: 0, y: 0 }],
      ["v", { x: 240, y: 92 }],
    ]);
    const steps = assignEdgeStepPositions(nodes, [edge("r", "v")], pos);
    const step = steps.get("r->v") ?? 0.5;
    expect(step).toBeGreaterThanOrEqual(0);
    expect(step).toBeLessThanOrEqual(1);
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
