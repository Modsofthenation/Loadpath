import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { THEMES, colorSchemeFor, isThemeId } from "./themes";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "styles.css"), "utf8");
const boot = readFileSync(join(here, "../index.html"), "utf8");

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

  it("has CSS tokens and a boot-script color-scheme for every palette", () => {
    const lightBoot = boot.match(/var light = \{([^}]+)\}/)?.[1] ?? "";
    expect(lightBoot).toBeTruthy();
    for (const theme of THEMES) {
      expect(css).toContain(`[data-theme="${theme.id}"]`);
      if (theme.group === "light") {
        expect(lightBoot).toContain(theme.id);
      } else {
        expect(lightBoot).not.toContain(theme.id);
      }
    }
  });
});
