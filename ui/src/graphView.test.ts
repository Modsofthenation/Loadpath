import { afterEach, describe, expect, it } from "vitest";
import {
  GRAPH_LAYOUTS,
  LARGE_GRAPH,
  LAYER_LABELS,
  defaultDetail,
  defaultProjection,
  familyFor,
  isolatePathIds,
  isInferredEdge,
  layoutGraph,
  layoutNodes3d,
  layoutUsesColumns,
  neighborIds,
  nodeRadius3d,
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

  it("packs occupied layers instead of leaving empty architecture gaps", () => {
    const laid = layoutNodes3d([node("a", "django.model", "A"), node("c", "react.page", "C")]);
    expect(laid.get("c")!.x - laid.get("a")!.x).toBe(160);
  });

  it("pulls a connected neighbor closer in Y than an unrelated sibling", () => {
    const viewA = { ...node("view-a", "django.view", "AView"), context: "billing" };
    const viewB = { ...node("view-b", "django.view", "BView"), context: "billing" };
    const serZ = { ...node("ser-z", "django.serializer", "ZebraSerializer"), context: "billing" };
    const serA = { ...node("ser-a", "django.serializer", "AlphaSerializer"), context: "billing" };
    const laid = layoutNodes3d([viewA, viewB, serZ, serA], [edge("view-b", "ser-z")]);
    const dyLinked = Math.abs(laid.get("ser-z")!.y - laid.get("view-b")!.y);
    const dyOther = Math.abs(laid.get("ser-a")!.y - laid.get("view-b")!.y);
    expect(dyLinked).toBeLessThan(dyOther);
  });

  it("separates bounded contexts along Z", () => {
    const billing = { ...node("bill", "django.model", "Invoice"), context: "billing" };
    const identity = { ...node("id", "django.model", "User"), context: "identity" };
    const laid = layoutNodes3d([billing, identity]);
    expect(laid.get("bill")!.z).not.toBe(laid.get("id")!.z);
    expect(laid.get("bill")!.x).toBe(laid.get("id")!.x);
  });

  it("keeps radial's ring shape instead of packing unique x into columns", () => {
    const ring = [
      node("a", "django.view", "A"),
      node("b", "django.serializer", "B"),
      node("c", "react.page", "C"),
      node("d", "django.model", "D"),
    ];
    const ringEdges = [edge("a", "b"), edge("a", "c"), edge("a", "d")];
    const radial2d = layoutGraph(ring, ringEdges, "radial");
    const radial3d = layoutNodes3d(ring, ringEdges, "radial");
    const xs = ring.map((n) => radial3d.get(n.id)!.x);
    expect(new Set(xs.map((x) => Math.round(x * 10))).size).toBeGreaterThan(1);
    for (const n of ring) {
      expect(radial3d.get(n.id)!.x).toBeCloseTo(radial2d.get(n.id)!.x * 0.45);
      expect(radial3d.get(n.id)!.y).toBeCloseTo(-radial2d.get(n.id)!.y * 0.45);
    }
  });
});

describe("nodeRadius3d", () => {
  it("keeps fields smaller than sinks and models", () => {
    expect(nodeRadius3d("django.field")).toBeLessThan(nodeRadius3d("django.model"));
    expect(nodeRadius3d("django.field")).toBeLessThan(nodeRadius3d("django.route"));
    expect(nodeRadius3d("django.route")).toBeGreaterThan(nodeRadius3d("django.service"));
  });
});

describe("isInferredEdge", () => {
  it("treats low-confidence stitches as inferred", () => {
    expect(isInferredEdge(edge("a", "b"))).toBe(false);
    expect(isInferredEdge({ ...edge("a", "c"), confidence: 0.6 })).toBe(true);
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

  it("every listed algorithm places every node at finite coordinates", () => {
    for (const { id } of GRAPH_LAYOUTS) {
      const pos = layoutGraph(nodes, edges, id);
      expect(pos.size).toBe(nodes.length);
      for (const n of nodes) {
        const p = pos.get(n.id)!;
        expect(Number.isFinite(p.x)).toBe(true);
        expect(Number.isFinite(p.y)).toBe(true);
      }
      expect(layoutGraph([], [], id).size).toBe(0);
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

  it("tree stacks descendants below their parent", () => {
    const chain = [node("s", "django.view", "S"), node("m", "django.serializer", "M"), node("t", "react.page", "T")];
    const pos = layoutGraph(chain, [edge("s", "m"), edge("m", "t")], "tree");
    expect(pos.get("m")!.y).toBeGreaterThan(pos.get("s")!.y);
    expect(pos.get("t")!.y).toBeGreaterThan(pos.get("m")!.y);
  });

  it("circle keeps nodes on one ring", () => {
    const ring = [
      node("a", "django.view", "A"),
      node("b", "django.serializer", "B"),
      node("c", "django.model", "C"),
      node("d", "react.page", "D"),
    ];
    const pos = layoutGraph(ring, [], "circle");
    const radii = ring.map((n) => Math.hypot(pos.get(n.id)!.x, pos.get(n.id)!.y));
    const mean = radii.reduce((s, r) => s + r, 0) / radii.length;
    for (const r of radii) expect(Math.abs(r - mean)).toBeLessThan(1e-6);
    expect(mean).toBeGreaterThan(0);
  });

  it("concentric puts later architecture layers on a larger ring", () => {
    const inner = node("v", "django.view", "View");
    const outer = node("p", "react.page", "Page");
    const pos = layoutGraph([inner, outer], [], "concentric");
    const rInner = Math.hypot(pos.get("v")!.x, pos.get("v")!.y);
    const rOuter = Math.hypot(pos.get("p")!.x, pos.get("p")!.y);
    expect(rOuter).toBeGreaterThan(rInner);
  });

  it("clusters keep same-type nodes closer than other types", () => {
    const group = [
      node("a1", "django.view", "A1"),
      node("a2", "django.view", "A2"),
      node("b1", "react.page", "B1"),
      node("b2", "react.page", "B2"),
    ];
    const pos = layoutGraph(group, [], "clusters");
    const dist = (a: string, b: string) => {
      const pa = pos.get(a)!;
      const pb = pos.get(b)!;
      return Math.hypot(pa.x - pb.x, pa.y - pb.y);
    };
    expect(dist("a1", "a2")).toBeLessThan(dist("a1", "b1"));
    expect(dist("b1", "b2")).toBeLessThan(dist("b1", "a1"));
  });

  it("force layout is deterministic and pulls a linked pair together", () => {
    const trio = [node("a", "django.view", "A"), node("b", "django.serializer", "B"), node("c", "react.page", "C")];
    const linked = [edge("a", "b")];
    const first = layoutGraph(trio, linked, "force");
    const second = layoutGraph(trio, linked, "force");
    expect(first).toEqual(second);
    const dist = (map: typeof first, a: string, b: string) => {
      const pa = map.get(a)!;
      const pb = map.get(b)!;
      return Math.hypot(pa.x - pb.x, pa.y - pb.y);
    };
    expect(dist(first, "a", "b")).toBeLessThan(dist(first, "a", "c"));
  });

  it("treats only architecture and flow layouts as columns", () => {
    expect(layoutUsesColumns("layers")).toBe(true);
    expect(layoutUsesColumns("flow")).toBe(true);
    for (const id of ["tree", "radial", "concentric", "circle", "clusters", "grid", "force"] as const) {
      expect(layoutUsesColumns(id)).toBe(false);
    }
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
    writeGraphLayout("force");
    expect(readGraphLayout()).toBe("force");
  });
});
