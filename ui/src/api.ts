import type { ArchitectureReport, IndexedRepo, PullRequest, Review } from "./types";

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
  repos: () => req<{ repos: IndexedRepo[] }>("/api/repos"),
  index: (repo_path: string, incremental = true) =>
    req<ArchitectureReport>("/api/index", {
      method: "POST",
      body: JSON.stringify({ repo_path, incremental }),
    }),
  indexStatus: (repo_path: string) =>
    req<ArchitectureReport>(`/api/index?repo_path=${encodeURIComponent(repo_path)}`),
  architecture: (repo_path: string) =>
    req<ArchitectureReport>(`/api/architecture?repo_path=${encodeURIComponent(repo_path)}`),
  review: (repo_path: string, base: string, head?: string, reindex = true) =>
    req<Review>("/api/review", {
      method: "POST",
      body: JSON.stringify({ repo_path, base, head: head || null, reindex, incremental: true, three_dot: true }),
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
  residual: (review: Review) =>
    req<{ note: string }>("/api/ai/residual", {
      method: "POST",
      body: JSON.stringify({ review }),
    }),
};
