import { describe, expect, it } from "vitest";
import { factsFromExtra, inspectNode, typePurpose } from "./nodeInspector";
import type { GraphEdge, GraphNode } from "./types";

function node(partial: Partial<GraphNode> & Pick<GraphNode, "id" | "type" | "name">): GraphNode {
  return {
    qualified_name: partial.qualified_name ?? partial.name,
    ...partial,
  };
}

describe("typePurpose", () => {
  it("explains known types and falls back by family", () => {
    expect(typePurpose("django.field")).toMatch(/column/i);
    expect(typePurpose("react.form_schema")).toMatch(/typed/i);
    expect(typePurpose("graphql.operation")).toMatch(/GraphQL/i);
    expect(typePurpose("fastapi.route")).toMatch(/FastAPI/i);
    expect(typePurpose("django.template")).toMatch(/template/i);
    expect(typePurpose("django.mystery")).toMatch(/Django/);
  });
});

describe("factsFromExtra", () => {
  it("surfaces typed field metadata and skips noise", () => {
    const facts = factsFromExtra({
      field_type: "DecimalField",
      unique: true,
      db_index: false,
      referenced: true,
      on_delete: "CASCADE",
      related_name: "invoices",
    });
    expect(facts.map((f) => f.label)).toEqual(["Type", "on_delete", "related_name", "Unique"]);
    expect(facts[0].value).toBe("DecimalField");
    expect(facts.find((f) => f.key === "unique")?.value).toBe("yes");
  });

  it("keeps a false idempotency flag and joins field lists", () => {
    const facts = factsFromExtra({
      looks_idempotent_on_pk: false,
      fields: ["id", "total", "status"],
      placeholder: true,
    });
    expect(facts).toEqual([
      { key: "fields", label: "Fields", value: "id, total, status" },
      { key: "looks_idempotent_on_pk", label: "Idempotent on pk", value: "no" },
    ]);
  });

  it("does not repeat role chips as facts", () => {
    const facts = factsFromExtra({
      generated: true,
      inferred: true,
      mutation: true,
      fbv: true,
      ninja: true,
      method: "GET",
    });
    expect(facts.map((f) => f.key)).toEqual(["method"]);
  });
});

describe("inspectNode", () => {
  const view = node({
    id: "django.view:billing.InvoiceViewSet",
    type: "django.view",
    name: "InvoiceViewSet",
    qualified_name: "billing.InvoiceViewSet",
    file_path: "backend/billing/views.py",
    start_line: 12,
    context: "billing",
    extra: {
      app: "billing",
      bases: ["ModelViewSet"],
      permissions: ["IsAuthenticated"],
    },
  });
  const ser = node({
    id: "django.serializer:billing.InvoiceSerializer",
    type: "django.serializer",
    name: "InvoiceSerializer",
  });
  const route = node({
    id: "django.route:billing:/api/invoices/{id}",
    type: "django.route",
    name: "/api/invoices/{id}",
  });
  const ghost = {
    id: "ghost",
    src: view.id,
    dst: "django.model:billing.Missing",
    type: "queries_model",
    weight: "expensive",
    confidence: 0.6,
  } satisfies GraphEdge;
  const uses = {
    id: "uses",
    src: view.id,
    dst: ser.id,
    type: "uses_serializer",
    weight: "expensive",
    confidence: 1,
  } satisfies GraphEdge;
  const publishes = {
    id: "pub",
    src: route.id,
    dst: view.id,
    type: "publishes_route",
    weight: "critical",
    confidence: 1,
  } satisfies GraphEdge;

  it("builds purpose, typed facts, and input/output neighbors", () => {
    const info = inspectNode(view, [view, ser, route], [uses, publishes, ghost]);
    expect(info.typeLabel).toBe("view");
    expect(info.layer).toBe("views");
    expect(info.purpose).toMatch(/Request handler/);
    expect(info.roles).toEqual([]);
    expect(info.file).toBe("backend/billing/views.py:12");
    expect(info.facts.map((f) => `${f.label}: ${f.value}`)).toEqual([
      "Extends: ModelViewSet",
      "Permissions: IsAuthenticated",
    ]);
    expect(info.inputs).toEqual([
      expect.objectContaining({
        name: "/api/invoices/{id}",
        typeLabel: "route",
        edgeLabel: "publishes route",
        inferred: false,
      }),
    ]);
    expect(info.outputs.map((l) => l.name)).toEqual(["InvoiceSerializer", "billing.Missing"]);
    expect(info.outputs[1].inferred).toBe(true);
    expect(info.outputs[1].typeLabel).toBe("");
  });

  it("tags sinks and contracts", () => {
    const info = inspectNode(route, [route], []);
    expect(info.roles).toEqual(["sink", "contract"]);
  });

  it("tags django-filter FilterSets without repeating the flag as a fact", () => {
    const info = inspectNode(
      node({
        id: "django.form:api.IngredientFilterSet",
        type: "django.form",
        name: "IngredientFilterSet",
        extra: { filterset: true, fields: ["name"] },
      }),
      [],
      [],
    );
    expect(info.roles).toContain("filterset");
    expect(info.purpose).toMatch(/FilterSet/i);
    expect(info.facts.map((f) => f.key)).toEqual(["fields"]);
  });

  it("keeps app when it is not the bounded context", () => {
    const info = inspectNode(
      node({
        id: "django.view:billing.InvoiceViewSet",
        type: "django.view",
        name: "InvoiceViewSet",
        context: "commerce",
        extra: { app: "billing" },
      }),
      [],
      [],
    );
    expect(info.facts).toEqual([{ key: "app", label: "App", value: "billing" }]);
  });

  it("caps long neighbor lists", () => {
    const fieldEdges: GraphEdge[] = Array.from({ length: 20 }, (_, i) => ({
      id: `f${i}`,
      src: view.id,
      dst: `django.field:billing.Invoice.f${i}`,
      type: "has_field",
      weight: "cheap",
      confidence: 1,
    }));
    const info = inspectNode(view, [view], fieldEdges);
    expect(info.outputs).toHaveLength(16);
    expect(info.extraOutputs).toBe(4);
  });
});
