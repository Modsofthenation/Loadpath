import type { IndexProgress } from "./types";

/** Overall bar spans. Keep in sync with `loadpath.progress.PHASE_SPANS`. */
export const PHASE_SPANS: Record<string, { start: number; end: number }> = {
  scan: { start: 0, end: 20 },
  extract: { start: 20, end: 88 },
  boot: { start: 88, end: 94 },
  stitch: { start: 94, end: 99 },
  skipped: { start: 100, end: 100 },
  done: { start: 100, end: 100 },
};

export const LIVE_INDEX_PHASES = new Set(["scan", "extract", "boot", "stitch"]);

export function phasePercent(p: Pick<IndexProgress, "phase" | "done" | "total">): number | null {
  const phase = p.phase || "";
  if (!phase || phase === "idle") return null;
  const span = PHASE_SPANS[phase];
  if (!span) return null;
  if (span.start === span.end) return span.end;
  const total = p.total || 0;
  if (total <= 0) return span.start;
  const ratio = Math.min(1, Math.max(0, (p.done || 0) / total));
  return Math.round(span.start + (span.end - span.start) * ratio);
}

export function progressPercent(p: IndexProgress): number | null {
  if (!p.phase || p.phase === "idle") return null;
  if (typeof p.percent === "number" && Number.isFinite(p.percent)) {
    return Math.max(0, Math.min(100, Math.round(p.percent)));
  }
  return phasePercent(p);
}
