import { describe, expect, it } from "vitest";
import { layerFor, layoutNodes, type GraphNode } from "./types";

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
});
