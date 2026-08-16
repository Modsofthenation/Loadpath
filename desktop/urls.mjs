export function isEditorUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.username || parsed.password) return false;
  return parsed.protocol === "vscode:" || parsed.protocol === "cursor:" || parsed.protocol === "vscode-insiders:";
}

export function isAllowedExternalUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  if (parsed.username || parsed.password) return false;
    const host = parsed.hostname.toLowerCase();
    const githubLike =
      host === "github.com" ||
      host.endsWith(".github.com") ||
      (host.startsWith("github.") && !host.startsWith("github.com."));
    const gitlabLike =
      host === "gitlab.com" ||
      host.endsWith(".gitlab.com") ||
      (host.startsWith("gitlab.") && !host.startsWith("gitlab.com."));
    const bitbucketLike =
      host === "bitbucket.org" ||
      host.endsWith(".bitbucket.org") ||
      host === "id.atlassian.com" ||
      host.endsWith(".atlassian.com");
    return githubLike || gitlabLike || bitbucketLike;
}

export function isAppOrigin(url, port) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return parsed.protocol === "http:" && parsed.hostname === "127.0.0.1" && parsed.port === String(port);
}
