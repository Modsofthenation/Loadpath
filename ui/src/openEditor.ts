import { api } from "./api";

export type EditorKind = "auto" | "cursor" | "vscode" | "system";

export function editorPreference(): EditorKind {
  const raw = localStorage.getItem("loadpath.editor") || "auto";
  if (raw === "cursor" || raw === "vscode" || raw === "system") return raw;
  return "auto";
}

export function persistEditorPreference(kind: EditorKind) {
  localStorage.setItem("loadpath.editor", kind);
}

export function vscodeFileUrl(absPath: string, line?: number | null, scheme = "vscode"): string {
  const normalized = absPath.replaceAll("\\", "/");
  const withSlash = normalized.startsWith("/") ? normalized : `/${normalized}`;
  const loc = line && line > 0 ? `${withSlash}:${line}` : withSlash;
  return `${scheme}://file${loc}`;
}

export async function openInEditor(
  repoPath: string,
  relPath: string,
  line?: number | null,
  editor: EditorKind = editorPreference(),
): Promise<{ ok: boolean; message: string }> {
  try {
    const result = await api.openEditor(repoPath, relPath, line ?? undefined, editor);
    if (result.ok) {
      return { ok: true, message: `Opened ${relPath} in ${result.opened_with || "editor"}` };
    }
    const urls = result.urls || {};
    const preferred =
      editor === "vscode" ? urls.vscode : editor === "cursor" ? urls.cursor : urls.cursor || urls.vscode;
    if (preferred) {
      window.open(preferred, "_blank", "noopener,noreferrer");
      return { ok: true, message: `Opening ${relPath} via editor URL` };
    }
    return { ok: false, message: result.error || "Could not open editor" };
  } catch (err) {
    return { ok: false, message: err instanceof Error ? err.message : String(err) };
  }
}
