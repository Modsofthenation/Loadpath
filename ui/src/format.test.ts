import { describe, expect, it } from "vitest";
import { formatWhen, kindLabel, repoName, typeLabel } from "./format";

describe("display helpers", () => {
  it("humanizes kinds and types", () => {
    expect(kindLabel("public_contract")).toBe("public contract");
    expect(typeLabel("django.serializer_field")).toBe("serializer_field");
    expect(repoName("/tmp/acme-billing")).toBe("acme-billing");
  });

  it("formats timestamps or leaves junk alone", () => {
    expect(formatWhen("not-a-date")).toBe("not-a-date");
    expect(formatWhen()).toBe("");
    expect(formatWhen("2026-08-14T00:00:00Z")).toMatch(/2026/);
  });
});
