import type { PullRequest, Review } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string; version: string }>("/api/health"),
  settings: () => req<Record<string, unknown>>("/api/settings"),
  saveSettings: (body: Record<string, unknown>) =>
    req<Record<string, unknown>>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  index: (repo_path: string) =>
    req<{ ok: boolean; counts: { nodes: number; edges: number } }>("/api/index", {
      method: "POST",
      body: JSON.stringify({ repo_path, incremental: true }),
    }),
  review: (repo_path: string, base: string, head?: string) =>
    req<Review>("/api/review", {
      method: "POST",
      body: JSON.stringify({ repo_path, base, head: head || null, reindex: true }),
    }),
  graph: (repo_path: string) =>
    req<{ nodes: unknown[]; edges: unknown[]; counts: { nodes: number; edges: number } }>(
      `/api/graph?repo_path=${encodeURIComponent(repo_path)}`,
    ),
  prs: (provider: string, repo: string, state = "open") =>
    req<{ pull_requests: PullRequest[] }>("/api/prs", {
      method: "POST",
      body: JSON.stringify({ provider, repo, state }),
    }),
  residual: (review: Review) =>
    req<{ note: string }>("/api/ai/residual", {
      method: "POST",
      body: JSON.stringify({ review }),
    }),
};
