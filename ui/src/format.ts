export function kindLabel(kind: string): string {
  return kind.replaceAll("_", " ");
}

export function strengthLabel(strength: string): string {
  return strength.replaceAll("_", " ");
}

export function typeLabel(type: string): string {
  return type.split(".").pop() || type;
}

export function formatWhen(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

export function repoName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

/** Soft wrap opportunities after path/identifier separators. */
export function wrapHint(text: string): string {
  return text.replace(/([/\\._:@-])/g, "$1\u200b");
}
