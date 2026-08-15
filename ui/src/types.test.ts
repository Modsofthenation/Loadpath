import { describe, expect, it } from "vitest";
import {
  GRAPH_COL_GAP,
  GRAPH_NODE_HEIGHT,
  GRAPH_NODE_WIDTH,
  layerFor,
  layoutNodes,
  type GraphEdge,
  type GraphNode,
} from "./types";

function node(id: string, type: string, name = id): GraphNode {
  return { id, type, name, qualified_name: name };
}

function edge(src: string, dst: string): GraphEdge {
  return { id: `${src}->${dst}`, src, dst, type: "uses", weight: "cheap", confidence: 1 };
}

describe("load-path layout", () => {
  it("places Django left of the React stitch", () => {
    const nodes: GraphNode[] = [
      { id: "r", type: "django.route", name: "/api/invoices", qualified_name: "r" },
      { id: "c", type: "react.api_client", name: "/api/invoices/{id}", qualified_name: "c" },
      { id: "p", type: "react.page", name: "InvoicePage", qualified_name: "p" },
      { id: "f", type: "react.form_schema", name: "invoiceSchema", qualified_name: "f" },
    ];
    const pos = layoutNodes(nodes);
    expect(pos.get("r")!.x).toBeLessThan(pos.get("c")!.x);
    expect(pos.get("c")!.x).toBeLessThan(pos.get("p")!.x);
    expect(pos.get("p")!.x).toBeLessThan(pos.get("f")!.x);
    expect(layerFor("django.serializer_field")).toBeLessThan(layerFor("react.form_schema"));
  });

  it("packs occupied layers so empty columns do not open huge gaps", () => {
    const nodes = [node("r", "django.route"), node("f", "react.form_schema")];
    const pos = layoutNodes(nodes);
    expect(Math.abs(pos.get("f")!.x - pos.get("r")!.x)).toBe(GRAPH_NODE_WIDTH + GRAPH_COL_GAP);
    expect(Math.abs(pos.get("f")!.x - pos.get("r")!.x)).toBeLessThan(13 * 260);
  });

  it("keeps same-column nodes from overlapping", () => {
    const nodes = [
      node("a", "django.view", "AlphaView"),
      node("b", "django.view", "BetaView"),
      node("c", "django.view", "GammaView"),
      node("d", "django.serializer", "AlphaSer"),
    ];
    const pos = layoutNodes(nodes);
    const byX = new Map<number, { id: string; y: number }[]>();
    for (const n of nodes) {
      const p = pos.get(n.id)!;
      const list = byX.get(p.x) ?? [];
      list.push({ id: n.id, y: p.y });
      byX.set(p.x, list);
    }
    for (const col of byX.values()) {
      col.sort((a, b) => a.y - b.y);
      for (let i = 1; i < col.length; i++) {
        expect(col[i]!.y - col[i - 1]!.y).toBeGreaterThanOrEqual(GRAPH_NODE_HEIGHT);
      }
    }
  });

  it("uncrosses a swapped pair with a barycenter pass", () => {
    const nodes = [
      node("a", "django.route", "A"),
      node("b", "django.route", "B"),
      node("ap", "django.view", "APrime"),
      node("bp", "django.view", "BPrime"),
    ];
    const edges = [edge("a", "bp"), edge("b", "ap")];
    const pos = layoutNodes(nodes, edges);
    const sourceOrder = pos.get("a")!.y - pos.get("b")!.y;
    const swappedTargets = pos.get("bp")!.y - pos.get("ap")!.y;
    expect(sourceOrder * swappedTargets).toBeGreaterThan(0);
  });
});
