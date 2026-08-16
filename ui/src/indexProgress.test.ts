import { describe, expect, it } from "vitest";
import { LIVE_INDEX_PHASES, phasePercent, progressPercent } from "./indexProgress";

describe("phasePercent", () => {
  it("maps each phase onto one 0–100 scale so extract does not restart at 0", () => {
    const scanHalf = phasePercent({ phase: "scan", done: 50, total: 100 });
    const scanDone = phasePercent({ phase: "scan", done: 100, total: 100 });
    const extractStart = phasePercent({ phase: "extract", done: 0, total: 80 });
    const extractHalf = phasePercent({ phase: "extract", done: 40, total: 80 });
    const extractDone = phasePercent({ phase: "extract", done: 80, total: 80 });
    const boot = phasePercent({ phase: "boot", done: 0, total: 1 });
    const stitch = phasePercent({ phase: "stitch", done: 0, total: 1 });
    const done = phasePercent({ phase: "done", done: 5, total: 100 });

    expect(scanHalf).toBe(10);
    expect(scanDone).toBe(20);
    expect(extractStart).toBe(20);
    expect(extractHalf).toBe(54);
    expect(extractDone).toBe(88);
    expect(boot).toBe(88);
    expect(stitch).toBe(94);
    expect(done).toBe(100);

    const seq = [scanHalf, scanDone, extractStart, extractHalf, extractDone, boot, stitch, done];
    for (let i = 1; i < seq.length; i++) {
      expect(seq[i]).toBeGreaterThanOrEqual(seq[i - 1]!);
    }
  });

  it("treats an unknown total as the start of the current phase, not 100%", () => {
    expect(phasePercent({ phase: "scan", done: 0, total: 0 })).toBe(0);
    expect(phasePercent({ phase: "extract", done: 0, total: 0 })).toBe(20);
  });

  it("returns null while idle", () => {
    expect(phasePercent({ phase: "idle", done: 0, total: 0 })).toBeNull();
    expect(progressPercent({ phase: "idle" })).toBeNull();
  });

  it("prefers the server percent when present", () => {
    expect(progressPercent({ phase: "extract", done: 0, total: 80, percent: 41 })).toBe(41);
  });
});

describe("LIVE_INDEX_PHASES", () => {
  it("does not treat a leftover done payload as an in-flight run", () => {
    expect(LIVE_INDEX_PHASES.has("done")).toBe(false);
    expect(LIVE_INDEX_PHASES.has("scan")).toBe(true);
  });
});
