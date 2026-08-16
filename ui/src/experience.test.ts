import { describe, expect, it } from "vitest";
import { filterActions } from "./CommandPalette";
import { vscodeFileUrl } from "./openEditor";

describe("filterActions", () => {
  const actions = [
    { id: "a", label: "Review this range", hint: "⌘Enter", group: "Run", run: () => undefined },
    { id: "b", label: "InvoiceSerializer", hint: "serializer", group: "Nodes", run: () => undefined },
  ];

  it("filters by label, hint, and group", () => {
    expect(filterActions(actions, "review").map((a) => a.id)).toEqual(["a"]);
    expect(filterActions(actions, "serializer").map((a) => a.id)).toEqual(["b"]);
    expect(filterActions(actions, "nodes").map((a) => a.id)).toEqual(["b"]);
    expect(filterActions(actions, "")).toHaveLength(2);
  });
});

describe("vscodeFileUrl", () => {
  it("builds a cursor/vscode file URI with a line", () => {
    expect(vscodeFileUrl("/tmp/acme/a.py", 12, "cursor")).toBe("cursor://file/tmp/acme/a.py:12");
    expect(vscodeFileUrl("C:\\repo\\a.py", 1, "vscode")).toContain("vscode://file/");
  });
});
