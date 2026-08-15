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
    return (
    host === "github.com" ||
    host.endsWith(".github.com") ||
    host === "bitbucket.org" ||
    host.endsWith(".bitbucket.org") ||
    host === "id.atlassian.com" ||
    host.endsWith(".atlassian.com")
  );
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
