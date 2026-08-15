export type ThemeId =
  | "obsidian"
  | "paper"
  | "nord"
  | "solarized-dark"
  | "solarized-light"
  | "forest"
  | "rose"
  | "high-contrast"
  | "amber"
  | "seafoam"
  | "volcano"
  | "lavender"
  | "neon-noir"
  | "synthwave"
  | "phosphor"
  | "aurora"
  | "biolume"
  | "carbon"
  | "sakura"
  | "citrus"
  | "peach"
  | "candy"
  | "sky"
  | "coral";

export type Theme = { id: ThemeId; label: string; group: "dark" | "light" };

export const THEMES: Theme[] = [
  { id: "obsidian", label: "Obsidian", group: "dark" },
  { id: "nord", label: "Nord", group: "dark" },
  { id: "solarized-dark", label: "Solarized Dark", group: "dark" },
  { id: "forest", label: "Forest", group: "dark" },
  { id: "rose", label: "Rose Pine", group: "dark" },
  { id: "amber", label: "Midnight Amber", group: "dark" },
  { id: "volcano", label: "Volcano", group: "dark" },
  { id: "lavender", label: "Lavender", group: "dark" },
  { id: "neon-noir", label: "Neon Noir", group: "dark" },
  { id: "synthwave", label: "Synthwave", group: "dark" },
  { id: "phosphor", label: "Phosphor", group: "dark" },
  { id: "aurora", label: "Aurora", group: "dark" },
  { id: "biolume", label: "Biolume", group: "dark" },
  { id: "carbon", label: "Carbon", group: "dark" },
  { id: "paper", label: "Paper", group: "light" },
  { id: "solarized-light", label: "Solarized Light", group: "light" },
  { id: "seafoam", label: "Seafoam", group: "light" },
  { id: "high-contrast", label: "High Contrast", group: "light" },
  { id: "sakura", label: "Sakura", group: "light" },
  { id: "citrus", label: "Citrus", group: "light" },
  { id: "peach", label: "Peach Fuzz", group: "light" },
  { id: "candy", label: "Cotton Candy", group: "light" },
  { id: "sky", label: "Clear Sky", group: "light" },
  { id: "coral", label: "Coral Reef", group: "light" },
];

export const DEFAULT_THEME: ThemeId = "obsidian";
const STORAGE_KEY = "loadpath.theme";

export function isThemeId(value: string): value is ThemeId {
  return THEMES.some((t) => t.id === value);
}

export function readTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(STORAGE_KEY) || "";
    if (isThemeId(stored)) return stored;
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

export function colorSchemeFor(id: ThemeId): "light" | "dark" {
  return THEMES.find((t) => t.id === id)?.group === "light" ? "light" : "dark";
}

export function applyTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id;
  document.documentElement.style.colorScheme = colorSchemeFor(id);
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* ignore */
  }
}
