import { describe, expect, it } from "vitest";
import { filterRefOptions, groupedRefOptions, groupLabel, refOptions } from "./refs";
import type { GitRefs } from "./types";

const refs: GitRefs = {
  git: true,
  repo_path: "/tmp/acme",
  head: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  head_short: "aaaaaaaaaaaa",
  presets: ["HEAD", "HEAD~1"],
  branches: [
    { name: "main", sha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", short: "aaaaaaa", subject: "baseline", current: true },
    { name: "feat/total", sha: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", short: "bbbbbbb", subject: "wip", current: false },
  ],
  tags: [{ name: "v1.0", sha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", short: "aaaaaaa", subject: "baseline", current: false }],
  commits: [
    {
      sha: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      short: "bbbbbbb",
      subject: "tighten Invoice.total contract",
      author: "ada",
      date: "2026-08-14T00:00:00Z",
    },
    {
      sha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      short: "aaaaaaa",
      subject: "baseline",
      author: "ada",
      date: "2026-08-13T00:00:00Z",
    },
  ],
};

describe("refOptions", () => {
  it("falls back to HEAD presets when the folder is not a git repo", () => {
    const options = refOptions({ ...refs, git: false });
    expect(options.map((o) => o.value)).toEqual(["HEAD", "HEAD~1"]);
  });

  it("lists branches, tags, and commits for picking or pasting", () => {
    const options = refOptions(refs);
    expect(options.some((o) => o.value === "HEAD~1" && o.group === "preset")).toBe(true);
    expect(options.some((o) => o.value === "main" && o.label.includes("current"))).toBe(true);
    expect(options.some((o) => o.value === "v1.0" && o.group === "tag")).toBe(true);
    expect(options.some((o) => o.group === "commit" && o.detail?.includes("tighten"))).toBe(true);
  });

  it("filters by sha, branch, or subject", () => {
    const options = refOptions(refs);
    expect(filterRefOptions(options, "HEAD~1").map((o) => o.value)).toEqual(["HEAD~1"]);
    expect(filterRefOptions(options, "feat").some((o) => o.value === "feat/total")).toBe(true);
    expect(filterRefOptions(options, "invoice").some((o) => o.group === "commit")).toBe(true);
  });

  it("keeps group headings only for groups that have rows", () => {
    const sections = groupedRefOptions(filterRefOptions(refOptions(refs), "v1"));
    expect(sections.map((s) => s.group)).toEqual(["tag"]);
    expect(groupLabel("commit")).toBe("Recent commits");
  });
});
