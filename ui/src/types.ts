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

export type ChecklistItem = {
  id: string;
  kind: string;
  status: "todo" | "done" | "info" | string;
  title: string;
  detail?: string;
  node_id?: string | null;
  file_path?: string | null;
  rule?: string | null;
  body?: string;
  action?: string;
};

export type ContractSideRow = {
  field: string;
  serializer: boolean;
  zod: boolean;
  openapi: boolean;
  graphql: boolean;
  status: string;
};

export type FileMark = {
  path: string;
  line?: number | null;
  roles: string[];
  node_id?: string;
  badge: string;
  tooltip: string;
};

export type Review = {
  id: string;
  title: string;
  headline: string;
  base?: string;
  head?: string;
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
  contract_break?: {
    kind: string;
    reasons: string[];
    fields: string[];
    sides?: {
      serializer: string[];
      zod: string[];
      openapi: string[];
      graphql: string[];
      rows: ContractSideRow[];
    };
  };
  auth?: {
    note: string;
    sinks: { id: string; name: string; permissions: string[] }[];
    missing_permissions: { id: string; name: string }[];
  };
  suggested_tests?: { sink: string; type: string; kind: string; title: string; body: string }[];
  trend?: { note: string; points: { id: string; created_at: string; level: string; sinks?: number }[] };
  what_if?: boolean;
  evolution?: {
    hotspots: { path: string; commits: number; bus_factor: number; complexity?: number }[];
    change_coupling: { a: string; b: string; together: number; cross_context?: boolean }[];
    notes: string[];
  };
  seed_ids?: string[];
  node_roles?: Record<string, string[]>;
  checklist?: ChecklistItem[];
  marks?: FileMark[];
  codeowners?: {
    path?: string | null;
    owners: string[];
    files: { path: string; owners: string[] }[];
  };
  codeowners_reviewers?: string[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  markdown?: string;
  pull_request?: Record<string, unknown>;
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
    dirty_included?: boolean;
    merge_base?: string | null;
    three_dot?: boolean;
    base_sha?: string | null;
    head_sha?: string | null;
  };
};

export type IndexProgress = {
  phase: string;
  done?: number;
  total?: number;
  current?: string;
  workers?: number;
  skipped?: number;
  elapsed_ms?: number;
  errors?: number;
  message?: string;
  repo_path?: string;
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

export type ReviewSummary = {
  id: string;
  created_at?: string;
  base_ref?: string | null;
  head_ref?: string | null;
  title?: string;
  level?: string;
  sinks?: number;
  covered_sinks?: number;
  contract_break?: string;
  findings?: number;
  low_risk?: boolean;
  labels?: string[];
  what_if?: boolean;
  contexts?: string[];
};

export type ReviewDiff = {
  direction: string;
  added_sinks: string[];
  removed_sinks: string[];
  added_findings: number;
  removed_findings: number;
  from_level?: string;
  to_level?: string;
  from_contract?: string;
  to_contract?: string;
  note: string;
};

export type ArchitectureHealth = {
  points: {
    id?: string;
    created_at?: string;
    level?: string;
    sinks?: number;
    findings?: number;
    inferred_ratio?: number;
    contexts?: Record<string, number>;
    title?: string;
  }[];
  contexts: Record<string, { created_at?: string; findings: number; level?: string }[]>;
};

export type LoadpathConfigDoc = {
  repo_root: string;
  path: string;
  exists: boolean;
  contexts: Record<
    string,
    { name: string; django_apps: string[]; react: string[]; public_api: string[]; owners: string[] }
  >;
  rules: string[];
  available_rules: string[];
  waivers: { rule: string; node?: string | null; reason?: string }[];
  django_root: string;
  react_root: string;
  openapi_paths: string[];
  boot_django: boolean;
  layers: { django: string[]; react: string[] };
};

export type WorkspaceStatus = {
  repo_path: string;
  dirty: string[];
  dirty_count: number;
  fingerprint: string;
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
  loadpath?: ReviewSummary;
};

export type RemoteRepo = {
  provider: string;
  slug: string;
  name: string;
  owner: string;
  url: string;
  private: boolean;
  default_branch?: string;
  updated_at?: string;
  description?: string;
  local_path?: string | null;
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
  "django.websocket_route": 1,
  "fastapi.route": 1,
  "django.url_name": 2,
  "django.view": 3,
  "django.viewset_action": 3,
  "django.permission": 3,
  "django.throttle": 3,
  "django.serializer": 4,
  "django.form": 4,
  "graphql.type": 4,
  "fastapi.model": 4,
  "django.serializer_field": 5,
  "django.service": 5,
  "graphql.field": 5,
  "django.model": 6,
  "django.field": 7,
  "django.relation": 7,
  "django.task": 8,
  "django.receiver": 8,
  "django.signal": 8,
  "django.test": 8,
  "django.migration_op": 8,
  "django.admin": 8,
  "django.management_command": 8,
  "django.consumer": 8,
  "django.cache_key": 8,
  "django.feature_flag": 8,
  "django.side_effect": 8,
  "openapi.path": 9,
  "graphql.operation": 9,
  "react.api_client": 10,
  "django.htmx": 10,
  "react.query_key": 11,
  "react.hook": 11,
  "react.feature": 11,
  "react.route": 12,
  "react.page": 12,
  "django.template": 12,
  "react.component": 13,
  "react.context": 13,
  "react.form_schema": 14,
  "react.test": 14,
};

export function layerFor(type: string): number {
  return LAYER_ORDER[type] ?? 8;
}

export const GRAPH_NODE_WIDTH = 208;
export const GRAPH_NODE_HEIGHT = 64;
export const GRAPH_COL_GAP = 88;
export const GRAPH_ROW_GAP = 28;

const LAYOUT_PASSES = 8;

function median(values: number[]): number {
  if (!values.length) return Number.NaN;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

/** Layered left-to-right layout: occupied columns only, barycenter ordering, no in-column overlap. */
export function layoutNodes(
  nodes: GraphNode[],
  edges: GraphEdge[] = [],
): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  if (!nodes.length) return pos;

  const columns = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const layer = layerFor(n.type);
    const list = columns.get(layer) ?? [];
    list.push(n);
    columns.set(layer, list);
  }

  const layers = [...columns.keys()].sort((a, b) => a - b);
  const order = layers.map((layer) =>
    [...(columns.get(layer) ?? [])].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id)),
  );

  const ids = new Set(nodes.map((n) => n.id));
  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  for (const n of nodes) {
    preds.set(n.id, []);
    succs.set(n.id, []);
  }
  for (const e of edges) {
    if (!ids.has(e.src) || !ids.has(e.dst) || e.src === e.dst) continue;
    succs.get(e.src)!.push(e.dst);
    preds.get(e.dst)!.push(e.src);
  }

  const colOf = new Map<string, number>();
  order.forEach((col, colIndex) => {
    for (const n of col) colOf.set(n.id, colIndex);
  });

  const rank = new Map<string, number>();
  const refreshRanks = () => {
    for (const col of order) {
      col.forEach((n, i) => rank.set(n.id, i));
    }
  };
  refreshRanks();

  const sortByBarycenter = (col: GraphNode[], neighborsOf: (id: string) => string[]) => {
    const keyed = col.map((n, i) => {
      const nbrs = neighborsOf(n.id)
        .map((id) => rank.get(id))
        .filter((v): v is number => v !== undefined);
      const bary = median(nbrs);
      return { n, bary: Number.isNaN(bary) ? i : bary, name: n.name, id: n.id };
    });
    keyed.sort((a, b) => a.bary - b.bary || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
    return keyed.map((k) => k.n);
  };

  const inColumn = (colIndex: number) => (nbr: string) => colOf.get(nbr) === colIndex;

  for (let pass = 0; pass < LAYOUT_PASSES; pass++) {
    for (let i = 1; i < order.length; i++) {
      order[i] = sortByBarycenter(order[i]!, (id) => (preds.get(id) ?? []).filter(inColumn(i - 1)));
      refreshRanks();
    }
    for (let i = order.length - 2; i >= 0; i--) {
      order[i] = sortByBarycenter(order[i]!, (id) => (succs.get(id) ?? []).filter(inColumn(i + 1)));
      refreshRanks();
    }
  }

  const colPitch = GRAPH_NODE_WIDTH + GRAPH_COL_GAP;
  const rowPitch = GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP;
  const maxRows = Math.max(...order.map((col) => col.length), 1);
  order.forEach((col, colIndex) => {
    const y0 = ((maxRows - col.length) * rowPitch) / 2;
    col.forEach((n, i) => {
      pos.set(n.id, { x: colIndex * colPitch, y: y0 + i * rowPitch });
    });
  });
  return pos;
}
