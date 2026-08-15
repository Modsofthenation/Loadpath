import { describe, expect, it } from "vitest";
import { LAYER_ORDER } from "./types";
import {
  LARGE_GRAPH,
  LAYER_LABELS,
  defaultDetail,
  defaultProjection,
  familyFor,
  layoutNodes3d,
  neighborIds,
  visibleGraph,
} from "./graphView";
import type { GraphEdge, GraphNode } from "./types";

function node(id: string, type: string, name = id): GraphNode {
  return { id, type, name, qualified_name: name };
}

function edge(src: string, dst: string): GraphEdge {
  return { id: `${src}->${dst}`, src, dst, type: "uses", weight: "cheap", confidence: 1 };
}

const nodes: GraphNode[] = [
  node("a", "django.model", "A"),
  node("b", "django.field", "B"),
  node("c", "react.component", "C"),
  node("d", "django.test", "test_a"),
];

const edges: GraphEdge[] = [edge("a", "b"), edge("a", "c"), edge("d", "a")];

const allFamilies = new Set(["django", "react", "stitch", "arch"] as const);

describe("visibleGraph", () => {
  it("overview hides fields and tests", () => {
    const g = visibleGraph(nodes, edges, { detail: "overview", families: allFamilies });
    expect(g.nodes.map((n) => n.id).sort()).toEqual(["a", "c"]);
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0].dst).toBe("c");
  });

  it("neighborhood keeps both directions", () => {
    const g = visibleGraph(nodes, edges, {
      detail: "full",
      families: allFamilies,
      focusId: "a",
      neighborhoodOnly: true,
    });
    expect(g.nodes.map((n) => n.id).sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("does not shrink the graph when a node is selected without neighborhood mode", () => {
    const g = visibleGraph(nodes, edges, {
      detail: "full",
      families: allFamilies,
      focusId: "b",
      neighborhoodOnly: false,
    });
    expect(g.nodes.map((n) => n.id).sort()).toEqual(["a", "b", "c", "d"]);
    expect(g.edges).toHaveLength(3);
  });

  it("family chips drop other stacks", () => {
    const g = visibleGraph(nodes, edges, { detail: "full", families: new Set(["django"]) });
    expect(g.nodes.map((n) => n.id).sort()).toEqual(["a", "b", "d"]);
    expect(g.edges.map((e) => `${e.src}->${e.dst}`).sort()).toEqual(["a->b", "d->a"]);
  });
});

describe("layoutNodes3d", () => {
  it("places later layers further along x", () => {
    const laid = layoutNodes3d(nodes.filter((n) => n.id === "a" || n.id === "c"));
    const django = laid.get("a")!;
    const react = laid.get("c")!;
    expect(react.x).toBeGreaterThan(django.x);
  });
});

describe("neighborIds", () => {
  it("includes self and both edge directions", () => {
    expect([...neighborIds("a", edges)].sort()).toEqual(["a", "b", "c", "d"]);
  });
});

describe("defaults", () => {
  it("uses 3d overview once the graph is large", () => {
    expect(defaultProjection(LARGE_GRAPH - 1)).toBe("2d");
    expect(defaultProjection(LARGE_GRAPH)).toBe("3d");
    expect(defaultDetail(LARGE_GRAPH - 1)).toBe("full");
    expect(defaultDetail(LARGE_GRAPH)).toBe("overview");
  });

  it("places GraphQL and FastAPI with the stitch family", () => {
    expect(familyFor("graphql.operation")).toBe("stitch");
    expect(familyFor("fastapi.route")).toBe("stitch");
    expect(familyFor("django.template")).toBe("django");
  });

  it("names every architecture layer used in 2d layout", () => {
    for (const layer of new Set(Object.values(LAYER_ORDER))) {
      expect(LAYER_LABELS[layer]).toBeTruthy();
    }
  });
});
