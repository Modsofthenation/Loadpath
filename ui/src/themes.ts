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
  | "lavender";

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
  { id: "paper", label: "Paper", group: "light" },
  { id: "solarized-light", label: "Solarized Light", group: "light" },
  { id: "seafoam", label: "Seafoam", group: "light" },
  { id: "high-contrast", label: "High Contrast", group: "light" },
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

export function applyTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* ignore */
  }
}
