import type { GitRefs } from "./types";

export type RefGroup = "preset" | "branch" | "tag" | "commit";

export type RefOption = {
  value: string;
  label: string;
  detail?: string;
  group: RefGroup;
};

const PRESETS: RefOption[] = [
  { value: "HEAD", label: "HEAD", group: "preset" },
  { value: "HEAD~1", label: "HEAD~1", group: "preset" },
];

const GROUP_ORDER: RefGroup[] = ["preset", "branch", "tag", "commit"];

export function refOptions(refs: GitRefs | null | undefined): RefOption[] {
  if (!refs?.git) return [...PRESETS];
  const presets: RefOption[] = (refs.presets?.length ? refs.presets : PRESETS.map((p) => p.value)).map((value) => ({
    value,
    label: value,
    group: "preset",
  }));
  const seen = new Set(presets.map((item) => item.value));
  const options: RefOption[] = [...presets];
  for (const branch of refs.branches || []) {
    if (seen.has(branch.name)) continue;
    seen.add(branch.name);
    options.push({
      value: branch.name,
      label: branch.current ? `${branch.name} (current)` : branch.name,
      detail: branch.subject,
      group: "branch",
    });
  }
  for (const tag of refs.tags || []) {
    if (seen.has(tag.name)) continue;
    seen.add(tag.name);
    options.push({
      value: tag.name,
      label: tag.name,
      detail: tag.subject,
      group: "tag",
    });
  }
  for (const commit of refs.commits || []) {
    if (seen.has(commit.sha)) continue;
    seen.add(commit.sha);
    options.push({
      value: commit.sha,
      label: commit.short,
      detail: commit.subject,
      group: "commit",
    });
  }
  return options;
}

export function filterRefOptions(options: RefOption[], query: string): RefOption[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return options;
  return options.filter(
    (item) =>
      item.value.toLowerCase().includes(needle) ||
      item.label.toLowerCase().includes(needle) ||
      (item.detail || "").toLowerCase().includes(needle),
  );
}

export function groupedRefOptions(options: RefOption[]): { group: RefGroup; items: RefOption[] }[] {
  return GROUP_ORDER.map((group) => ({ group, items: options.filter((item) => item.group === group) })).filter(
    (section) => section.items.length > 0,
  );
}

export function groupLabel(group: RefGroup): string {
  if (group === "preset") return "Common";
  if (group === "branch") return "Branches";
  if (group === "tag") return "Tags";
  return "Recent commits";
}
