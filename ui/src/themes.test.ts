import { describe, expect, it } from "vitest";
import { THEMES, colorSchemeFor, isThemeId } from "./themes";

describe("themes", () => {
  it("ships two dozen named palettes", () => {
    expect(THEMES).toHaveLength(24);
    expect(new Set(THEMES.map((t) => t.id)).size).toBe(24);
    expect(THEMES.filter((t) => t.group === "dark")).toHaveLength(14);
    expect(THEMES.filter((t) => t.group === "light")).toHaveLength(10);
    expect(THEMES.some((t) => t.id === "obsidian")).toBe(true);
    expect(isThemeId("nord")).toBe(true);
    expect(isThemeId("synthwave")).toBe(true);
    expect(isThemeId("citrus")).toBe(true);
    expect(isThemeId("not-a-theme")).toBe(false);
    expect(colorSchemeFor("obsidian")).toBe("dark");
    expect(colorSchemeFor("neon-noir")).toBe("dark");
    expect(colorSchemeFor("paper")).toBe("light");
    expect(colorSchemeFor("sakura")).toBe("light");
  });
});
