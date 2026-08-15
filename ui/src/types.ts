export type GraphNode = {
  id: string;
  type: string;
  name: string;
  qualified_name: string;
  file_path?: string | null;
  start_line?: number | null;
  context?: string | null;
  extra?: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  src: string;
  dst: string;
  type: string;
  weight: string;
  confidence: number;
  extra?: Record<string, unknown>;
};

export type Finding = {
  rule: string;
  severity: string;
  message: string;
  node_id?: string | null;
  file_path?: string | null;
  waived: boolean;
  extra?: Record<string, unknown>;
};

export type DeepeningCandidate = {
  rule: string;
  strength: "strong" | "worth_exploring" | "speculative" | string;
  title: string;
  message: string;
  file_path?: string | null;
  node_id?: string | null;
  deletion_test?: string;
  leverage?: string;
  locality?: string;
  before?: string;
  after?: string;
  top?: boolean;
};

export type Review = {
  id: string;
  title: string;
  headline: string;
  change_kinds: string[];
  confidence: {
    level: "high" | "medium" | "low";
    reasons: string[];
    sinks: number;
    covered_sinks: number;
    untested_sinks: { id: string; name: string; type: string }[];
  };
  labels: string[];
  low_risk: boolean;
  clusters: { id: string; title: string; files: string[]; contexts: string[] }[];
  read_order: { path: string; why: string; status: string }[];
  skip: string[];
  findings: Finding[];
  residuals: string[];
  suggested_reviewers: string[];
  knowledge_owners?: string[];
  sinks: { id: string; type: string; name: string }[];
  tests_note: string;
  architecture_note: string;
  depth_note?: string;
  deepening?: DeepeningCandidate[];
  evolution?: {
    hotspots: { path: string; commits: number; bus_factor: number; complexity?: number }[];
    change_coupling: { a: string; b: string; together: number; cross_context?: boolean }[];
    notes: string[];
  };
  nodes: GraphNode[];
  edges: GraphEdge[];
  markdown?: string;
  index?: {
    db: string;
    counts: { nodes: number; edges: number };
    type_counts?: Record<string, number>;
    indexed_at?: string | null;
    reindexed: boolean;
    incremental: boolean;
    reindex_skipped?: boolean;
    files_extracted?: number;
    stale?: boolean;
    django_boot?: string;
    django_boot_detail?: string;
  };
  workspace?: {
    dirty: string[];
    dirty_count: number;
    dirty_overlaps_review: boolean;
    dirty_overlap: string[];
    merge_base?: string | null;
    three_dot?: boolean;
    base_sha?: string | null;
    head_sha?: string | null;
  };
};

export type ArchitectureReport = {
  ok: boolean;
  indexed: boolean;
  repo_root: string;
  db?: string;
  indexed_at?: string | null;
  incremental?: boolean;
  counts: { nodes: number; edges: number };
  type_counts: Record<string, number>;
  file_count?: number;
  contexts: Record<
    string,
    { name: string; django_apps: string[]; react: string[]; public_api: string[]; owners: string[] }
  >;
  rules: string[];
  findings: Finding[];
  deepening?: DeepeningCandidate[];
  residuals: string[];
  has_config?: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  stale?: boolean;
  django_boot?: string;
  django_boot_detail?: string;
  reindex_skipped?: boolean;
  files_extracted?: number;
  boot_residuals?: string[];
};

export type IndexedRepo = {
  path: string;
  name: string;
  exists: boolean;
  indexed: boolean;
  counts: { nodes: number; edges: number };
  indexed_at?: string | null;
  contexts?: string[];
  has_config?: boolean;
  stale?: boolean;
  django_boot?: string;
};

export type PullRequest = {
  provider: string;
  id: string;
  number: number;
  title: string;
  url: string;
  author: string;
  source_branch: string;
  target_branch: string;
  repo: string;
  state: string;
  updated_at: string;
  draft: boolean;
  head_sha?: string;
  base_sha?: string;
};

export type FsEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  is_git: boolean;
};

export type FsListing = {
  path: string;
  name: string;
  parent: string | null;
  home: string;
  is_git: boolean;
  truncated: boolean;
  entries: FsEntry[];
};

export type GitRefItem = {
  name: string;
  sha: string;
  short: string;
  subject: string;
  current: boolean;
};

export type GitCommit = {
  sha: string;
  short: string;
  subject: string;
  author: string;
  date: string;
};

export type GitRefs = {
  git: boolean;
  repo_path: string;
  head: string | null;
  head_short: string | null;
  branches: GitRefItem[];
  tags: GitRefItem[];
  commits: GitCommit[];
  presets: string[];
};

export const LAYER_ORDER: Record<string, number> = {
  "arch.context": 0,
  "django.app": 0,
  "django.route": 1,
  "django.url_name": 1,
  "django.view": 2,
  "django.viewset_action": 2,
  "django.permission": 2,
  "django.serializer": 3,
  "django.form": 3,
  "django.serializer_field": 4,
  "django.service": 4,
  "django.model": 5,
  "django.field": 6,
  "django.relation": 6,
  "django.task": 7,
  "django.receiver": 7,
  "django.signal": 7,
  "django.test": 7,
  "django.migration_op": 7,
  "django.admin": 7,
  "openapi.path": 8,
  "react.api_client": 9,
  "react.query_key": 10,
  "react.hook": 10,
  "react.feature": 10,
  "react.route": 11,
  "react.page": 11,
  "react.component": 12,
  "react.form_schema": 13,
  "react.test": 13,
  "react.context": 12,
};

export function layerFor(type: string): number {
  return LAYER_ORDER[type] ?? 8;
}

export function layoutNodes(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const columns = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const layer = layerFor(n.type);
    const list = columns.get(layer) ?? [];
    list.push(n);
    columns.set(layer, list);
  }
  const pos = new Map<string, { x: number; y: number }>();
  for (const [layer, list] of columns) {
    list.sort((a, b) => a.name.localeCompare(b.name));
    list.forEach((n, i) => {
      pos.set(n.id, { x: layer * 260, y: i * 108 });
    });
  }
  return pos;
}
