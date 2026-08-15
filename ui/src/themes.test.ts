import { describe, expect, it } from "vitest";
import { THEMES, colorSchemeFor, isThemeId } from "./themes";

describe("themes", () => {
  it("ships a dozen named palettes", () => {
    expect(THEMES.length).toBeGreaterThanOrEqual(12);
    expect(THEMES.some((t) => t.id === "obsidian")).toBe(true);
    expect(THEMES.some((t) => t.group === "light")).toBe(true);
    expect(THEMES.some((t) => t.group === "dark")).toBe(true);
    expect(isThemeId("nord")).toBe(true);
    expect(isThemeId("not-a-theme")).toBe(false);
    expect(colorSchemeFor("obsidian")).toBe("dark");
    expect(colorSchemeFor("paper")).toBe("light");
  });
});
