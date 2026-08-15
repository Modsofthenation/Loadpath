from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from loadpath.paths import package_dir

TEMPLATE_DIR = package_dir() / "report"


def render_markdown(review: dict) -> str:
    conf = review["confidence"]
    lines = [
        f"## Loadpath: {conf['level'].upper()} — {review['title']}",
        "",
        review["headline"],
        "",
        "### What kind of change is this?",
        ", ".join(k.replace("_", " ") for k in review["change_kinds"]) or "unknown",
        "",
        "### Read this, skip that",
    ]
    for item in review["read_order"]:
        lines.append(f"- `{item['path']}` — {item['why']}")
    if review["skip"]:
        lines.append("")
        lines.append("Skip: " + ", ".join(f"`{p}`" for p in review["skip"][:20]))
    lines += ["", "### Clusters"]
    for c in review["clusters"]:
        files = ", ".join(f"`{f}`" for f in c["files"][:12])
        lines.append(f"- **{c['title']}** ({', '.join(c['contexts']) or 'unscoped'}): {files}")
    lines += ["", "### Architecture"]
    findings = review["findings"]
    active = [f for f in findings if not f.get("waived")]
    if not active:
        lines.append("No rule hits on the impact path.")
    for f in active:
        flag = "BLOCKER" if f["severity"] == "blocker" else "warn"
        lines.append(f"- [{flag}] `{f['rule']}`: {f['message']}")
    lines += ["", "### Confidence"]
    for r in conf["reasons"]:
        lines.append(f"- {r}")
    if review["residuals"]:
        lines += ["", "### Residual uncertainty (AI-eligible)"]
        for r in review["residuals"][:12]:
            lines.append(f"- {r}")
    if review["low_risk"]:
        lines += ["", "_Fast-track: `loadpath:low-risk`. Human review can be a glance._"]
    evolution = review.get("evolution") or {}
    if evolution.get("notes") or evolution.get("hotspots"):
        lines += ["", "### Churn & coupling"]
        for note in evolution.get("notes") or []:
            lines.append(f"- {note}")
        for h in (evolution.get("hotspots") or [])[:6]:
            if h.get("commits"):
                lines.append(
                    f"- `{h['path']}` — {h['commits']} commits, bus factor {h.get('bus_factor', 0)}"
                    + (f", complexity {h['complexity']}" if h.get("complexity") else "")
                )
        for c in (evolution.get("change_coupling") or [])[:4]:
            flag = " (cross-context)" if c.get("cross_context") else ""
            lines.append(f"- coupling `{c['a']}` ↔ `{c['b']}` ×{c['together']}{flag}")
        for fn in (evolution.get("functions") or [])[:4]:
            lines.append(f"- `{fn['path']}::{fn['name']}` cyclomatic {fn.get('complexity', 0)}")
    knowledge = review.get("knowledge_owners") or []
    if knowledge:
        lines += ["", "### Knowledge on this path", ", ".join(f"`{k}`" for k in knowledge)]
    index = review.get("index") or {}
    counts = index.get("counts") or review.get("counts") or {}
    if counts:
        mode = "incremental" if index.get("incremental") else "full"
        skipped = " · hashes unchanged, extract skipped" if index.get("reindex_skipped") else ""
        boot = index.get("django_boot")
        boot_bit = f" · django boot {boot}" if boot and boot != "off" else ""
        stale = " · STALE" if index.get("stale") else ""
        lines += [
            "",
            "### Index",
            f"{counts.get('nodes', 0)} nodes / {counts.get('edges', 0)} edges"
            + (f" · {mode}" if index else "")
            + skipped
            + boot_bit
            + stale
            + (f" · {index['indexed_at']}" if index.get("indexed_at") else ""),
        ]
    workspace = review.get("workspace") or {}
    if workspace.get("dirty_overlaps_review"):
        lines += [
            "",
            "### Working tree",
            "Uncommitted files overlap this review: "
            + ", ".join(f"`{p}`" for p in (workspace.get("dirty_overlap") or [])[:8]),
        ]
    elif workspace.get("dirty_count"):
        lines += [
            "",
            "### Working tree",
            f"{workspace['dirty_count']} uncommitted file(s); they are not in this git range.",
        ]
    return "\n".join(lines) + "\n"


def render_html(review: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("graph.html")
    return template.render(review=review, markdown=render_markdown(review))
