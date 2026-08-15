import type { ArchitectureReport, FsListing, GitRefs, GraphNode, IndexedRepo, IndexProgress, PullRequest, RemoteRepo, Review } from "./types";

export function formatApiError(text: string, fallback = "Request failed"): string {
  const trimmed = (text || "").trim();
  if (!trimmed) return fallback;
  try {
    const parsed = JSON.parse(trimmed) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return "";
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  } catch {
    /* not JSON */
  }
  return trimmed;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(formatApiError(text, res.statusText || "Request failed"));
  }
  return res.json() as Promise<T>;
}

const BLANK_SETTINGS_KEYS = [
  "github_token",
  "gitlab_token",
  "gitlab_oauth_client_secret",
  "bitbucket_token",
  "bitbucket_oauth_client_secret",
  "ai_api_key",
  "ai_model",
  "ai_base_url",
];

export const api = {
  health: () => req<{ status: string; version: string }>("/api/health"),
  settings: () => req<Record<string, unknown>>("/api/settings"),
  saveSettings: (body: Record<string, unknown>) => {
    const payload: Record<string, unknown> = { ...body };
    for (const key of BLANK_SETTINGS_KEYS) {
      if (payload[key] === "") delete payload[key];
    }
    return req<Record<string, unknown>>("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
  },
  repos: () => req<{ repos: IndexedRepo[] }>("/api/repos"),
  browse: (path?: string) =>
    req<FsListing>(`/api/fs${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  gitRefs: (repo_path: string, limit = 50) =>
    req<GitRefs>(`/api/git/refs?repo_path=${encodeURIComponent(repo_path)}&limit=${limit}`),
  index: (repo_path: string, incremental = true) =>
    req<ArchitectureReport>("/api/index", {
      method: "POST",
      body: JSON.stringify({ repo_path, incremental }),
    }),
  indexStatus: (repo_path: string) =>
    req<ArchitectureReport>(`/api/index?repo_path=${encodeURIComponent(repo_path)}`),
  indexProgress: (repo_path: string) =>
    req<IndexProgress>(`/api/index/progress?repo_path=${encodeURIComponent(repo_path)}`),
  architecture: (repo_path: string) =>
    req<ArchitectureReport>(`/api/architecture?repo_path=${encodeURIComponent(repo_path)}`),
  review: (repo_path: string, base: string, head?: string, reindex = true, dirty = false) =>
    req<Review>("/api/review", {
      method: "POST",
      body: JSON.stringify({
        repo_path,
        base,
        head: head || null,
        reindex,
        incremental: true,
        three_dot: true,
        dirty,
      }),
    }),
  whatIf: (repo_path: string, node_id: string) =>
    req<
      Review & {
        ok: boolean;
        node: GraphNode;
        what_if?: boolean;
      }
    >("/api/whatif", { method: "POST", body: JSON.stringify({ repo_path, node_id }) }),
  reviewPr: (provider: string, repo: string, number: number, repo_path?: string) =>
    req<Review & { pull_request?: Record<string, unknown> }>("/api/prs/review", {
      method: "POST",
      body: JSON.stringify({ provider, repo, number, repo_path: repo_path || null }),
    }),
  init: (repo_path: string, overwrite = false) =>
    req<{ wrote: boolean; message: string; django_root: string; react_root: string; has_config: boolean }>(
      "/api/init",
      { method: "POST", body: JSON.stringify({ repo_path, overwrite }) },
    ),
  postComment: (provider: string, repo: string, number: number, markdown: string) =>
    req<{ id: string; url: string; updated: boolean }>("/api/prs/comment", {
      method: "POST",
      body: JSON.stringify({ provider, repo, number, markdown }),
    }),
  graph: (repo_path: string, scope: "full" | "architecture" = "full") =>
    req<{ nodes: unknown[]; edges: unknown[]; counts: { nodes: number; edges: number } }>(
      `/api/graph?repo_path=${encodeURIComponent(repo_path)}&scope=${scope}`,
    ),
  prs: (provider: string, repo: string, state = "open") =>
    req<{ pull_requests: PullRequest[] }>("/api/prs", {
      method: "POST",
      body: JSON.stringify({ provider, repo, state }),
    }),
  scmRepos: (provider: string) =>
    req<{ provider: string; user: { login: string; name: string; url: string }; repos: RemoteRepo[] }>(
      `/api/scm/repos?provider=${encodeURIComponent(provider)}`,
    ),
  oauthStatus: () =>
    req<{
      github: { connected: boolean; user: string; token_set: boolean; oauth_ready: boolean; host?: string };
      gitlab: { connected: boolean; user: string; token_set: boolean; oauth_ready: boolean; host?: string };
      bitbucket: { connected: boolean; user: string; token_set: boolean; oauth_ready: boolean };
    }>("/api/oauth/status"),
  githubOAuthStart: () =>
    req<{
      flow_id: string;
      user_code: string;
      verification_uri: string;
      verification_uri_complete: string;
      interval: number;
      expires_in: number;
    }>("/api/oauth/github/start", { method: "POST", body: "{}" }),
  githubOAuthPoll: (flow_id: string) =>
    req<{ status: string; interval?: number; user?: string; connected?: boolean }>("/api/oauth/github/poll", {
      method: "POST",
      body: JSON.stringify({ flow_id }),
    }),
  bitbucketOAuthStart: () =>
    req<{ flow_id: string; authorize_url: string }>("/api/oauth/bitbucket/start"),
  gitlabOAuthStart: () =>
    req<{ flow_id: string; authorize_url: string }>("/api/oauth/gitlab/start"),
  oauthDisconnect: (provider: string) =>
    req<Record<string, unknown>>("/api/oauth/disconnect", {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),
  residual: (review: Review) =>
    req<{ note: string }>("/api/ai/residual", {
      method: "POST",
      body: JSON.stringify({ review }),
    }),
};
