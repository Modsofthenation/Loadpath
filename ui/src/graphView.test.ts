import { afterEach, describe, expect, it } from "vitest";
import {
  LARGE_GRAPH,
  LAYER_LABELS,
  defaultDetail,
  defaultProjection,
  familyFor,
  isolatePathIds,
  layoutGraph,
  layoutNodes3d,
  layoutUsesColumns,
  neighborIds,
  readGraphLayout,
  searchNodes,
  visibleGraph,
  writeGraphLayout,
} from "./graphView";
import { GRAPH_COL_GAP, GRAPH_NODE_WIDTH, LAYER_ORDER, layoutNodes, type GraphEdge, type GraphNode } from "./types";

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

describe("isolatePathIds", () => {
  it("keeps only nodes on the path from source to a sink", () => {
    const pathNodes: GraphNode[] = [
      node("field", "django.field", "total"),
      node("ser", "django.serializer", "InvoiceSerializer"),
      node("route", "django.route", "/api/invoices"),
      node("me", "react.page", "MePage"),
    ];
    const pathEdges: GraphEdge[] = [
      edge("field", "ser"),
      edge("ser", "route"),
      edge("ser", "me"),
    ];
    const isolated = isolatePathIds(pathNodes, pathEdges, "field", "route");
    expect([...isolated.nodeIds].sort()).toEqual(["field", "route", "ser"]);
    expect(isolated.edgeIds.has("ser->me")).toBe(false);
  });
});

describe("searchNodes", () => {
  it("matches name and type", () => {
    expect(searchNodes(nodes, "invoice").map((n) => n.id)).toEqual([]);
    expect(searchNodes(nodes, "component").map((n) => n.id)).toEqual(["c"]);
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

describe("layoutGraph", () => {
  it("layers matches the architecture-column layout", () => {
    expect(layoutGraph(nodes, edges, "layers")).toEqual(layoutNodes(nodes, edges));
  });

  it("flow ranks destinations to the right of sources", () => {
    const chain = [node("s", "django.view", "S"), node("m", "django.serializer", "M"), node("t", "react.page", "T")];
    const flowEdges = [edge("s", "m"), edge("m", "t")];
    const pos = layoutGraph(chain, flowEdges, "flow");
    expect(pos.get("m")!.x).toBeGreaterThan(pos.get("s")!.x);
    expect(pos.get("t")!.x).toBeGreaterThan(pos.get("m")!.x);
  });

  it("radial and grid produce finite coordinates for every node", () => {
    for (const layout of ["radial", "grid"] as const) {
      const pos = layoutGraph(nodes, edges, layout);
      expect(pos.size).toBe(nodes.length);
      for (const n of nodes) {
        const p = pos.get(n.id)!;
        expect(Number.isFinite(p.x)).toBe(true);
        expect(Number.isFinite(p.y)).toBe(true);
      }
    }
  });

  it("switching algorithm moves at least one node", () => {
    const layers = layoutGraph(nodes, edges, "layers");
    const radial = layoutGraph(nodes, edges, "radial");
    const moved = nodes.some(
      (n) => layers.get(n.id)!.x !== radial.get(n.id)!.x || layers.get(n.id)!.y !== radial.get(n.id)!.y,
    );
    expect(moved).toBe(true);
  });

  it("caps flow ranks so cycles do not explode into a long strip", () => {
    const cycle = [node("a", "django.view", "A"), node("b", "django.serializer", "B")];
    const loop = [edge("a", "b"), edge("b", "a")];
    const pos = layoutGraph(cycle, loop, "flow");
    const span = Math.abs(pos.get("a")!.x - pos.get("b")!.x);
    expect(span).toBeLessThanOrEqual(GRAPH_NODE_WIDTH + GRAPH_COL_GAP);
  });

  it("treats flow as columns and radial/grid as freeform", () => {
    expect(layoutUsesColumns("layers")).toBe(true);
    expect(layoutUsesColumns("flow")).toBe(true);
    expect(layoutUsesColumns("radial")).toBe(false);
    expect(layoutUsesColumns("grid")).toBe(false);
  });
});

describe("graph layout preference", () => {
  afterEach(() => {
    localStorage.removeItem("loadpath.graphLayout");
  });

  it("falls back to layers for invalid storage", () => {
    localStorage.setItem("loadpath.graphLayout", "force-atlas");
    expect(readGraphLayout()).toBe("layers");
  });

  it("round-trips a valid layout", () => {
    writeGraphLayout("radial");
    expect(readGraphLayout()).toBe("radial");
  });
});
