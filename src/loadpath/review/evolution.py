"""CodeScene-style evolution: hotspots, change coupling, knowledge, complexity.

Mined from git history and the current diff, then scoped to the load-path
impact set. Empty when the repo has no history.
"""

from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from loadpath.config import LoadpathConfig
from loadpath.review.diff import DiffSet, FileDiff

COMMIT_HEADER = re.compile(r"^([0-9a-f]{40})\t(.*)$")
LOG_LIMIT = 250
COUPLE_MIN = 3


def analyze_evolution(
    repo_root: Path,
    diff: DiffSet,
    impact_nodes: list[dict],
    config: LoadpathConfig | None = None,
    limit: int = LOG_LIMIT,
) -> dict:
    repo_root = repo_root.resolve()
    impact_files = sorted(
        {n["file_path"] for n in impact_nodes if n.get("file_path")} | set(diff.paths)
    )
    commits = _git_commits(repo_root, limit)
    if not commits:
        return {"hotspots": [], "change_coupling": [], "notes": [], "commits_sampled": 0}

    file_commits: dict[str, int] = Counter()
    file_authors: dict[str, set[str]] = defaultdict(set)
    pair_counts: Counter[tuple[str, str]] = Counter()
    for commit in commits:
        files = [f for f in commit["files"] if _sourcey(f)]
        for path in files:
            file_commits[path] += 1
            file_authors[path].add(commit["author"])
        for i, a in enumerate(files):
            for b in files[i + 1 :]:
                pair = (a, b) if a < b else (b, a)
                pair_counts[pair] += 1

    complexity = _complexity_for_diff(repo_root, diff)
    functions = _changed_functions(repo_root, diff)
    hotspots = []
    for path in impact_files:
        commits_n = file_commits.get(path, 0)
        authors = sorted(file_authors.get(path, set()))
        if not commits_n and path not in complexity:
            continue
        hotspots.append(
            {
                "path": path,
                "commits": commits_n,
                "authors": authors,
                "bus_factor": len(authors),
                "complexity": complexity.get(path, 0),
            }
        )
    hotspots.sort(key=lambda h: (h["commits"], h["complexity"]), reverse=True)

    coupling = []
    impact_set = set(impact_files)
    for (a, b), together in pair_counts.most_common(40):
        if together < COUPLE_MIN:
            continue
        if a not in impact_set and b not in impact_set:
            continue
        other = b if a in impact_set else a
        if other in impact_set and a in impact_set:
            # both on the path — expected if they are the same slice
            continue
        denom = max(file_commits.get(a, 1), file_commits.get(b, 1))
        coupling.append(
            {
                "a": a,
                "b": b,
                "together": together,
                "degree": round(together / denom, 3),
                "cross_context": _cross_context(a, b, config) if config else False,
            }
        )
        if len(coupling) >= 12:
            break

    notes = _notes(hotspots, coupling, functions)
    return {
        "hotspots": hotspots[:16],
        "change_coupling": coupling,
        "functions": functions[:12],
        "notes": notes,
        "commits_sampled": len(commits),
    }


def _notes(hotspots: list[dict], coupling: list[dict], functions: list[dict] | None = None) -> list[str]:
    notes: list[str] = []
    for h in hotspots:
        if h["commits"] >= 5 and h["bus_factor"] == 1:
            who = h["authors"][0] if h["authors"] else "one author"
            notes.append(
                f"{h['path']} is a hotspot ({h['commits']} commits, knowledge silo: {who})"
            )
        elif h["commits"] >= 8:
            notes.append(f"{h['path']} is a hotspot ({h['commits']} commits on the load path)")
        elif h["complexity"] >= 12 and h["commits"] >= 3:
            notes.append(
                f"{h['path']} changed with cyclomatic complexity {h['complexity']} in a historically active file"
            )
    for c in coupling:
        if c.get("cross_context") and c["degree"] >= 0.4:
            notes.append(
                f"Temporal coupling {c['a']} ↔ {c['b']} ({c['together']} co-changes, degree {c['degree']}) "
                "crosses a bounded context — the architecture graph may not show this dependency"
            )
        elif c["degree"] >= 0.6:
            notes.append(
                f"Temporal coupling {c['a']} ↔ {c['b']} ({c['together']} co-changes) — files move together"
            )
    for fn in functions or []:
        if fn.get("complexity", 0) >= 12:
            notes.append(
                f"{fn['path']}::{fn['name']} changed with cyclomatic complexity {fn['complexity']}"
            )
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:8]


def _git_commits(repo_root: Path, limit: int) -> list[dict]:
    try:
        raw = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                f"-n{limit}",
                "--name-only",
                "--no-merges",
                "--pretty=format:%H%x09%an",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []
    commits: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        header = COMMIT_HEADER.match(line)
        if header:
            current = {"sha": header.group(1), "author": header.group(2), "files": []}
            commits.append(current)
            continue
        if current is not None:
            current["files"].append(line.strip())
    return commits


def _changed_functions(repo_root: Path, diff: DiffSet) -> list[dict]:
    out: list[dict] = []
    for fd in diff.files:
        if fd.skip or not fd.path.endswith(".py"):
            continue
        changed = _changed_lines(fd)
        path = repo_root / fd.path
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = getattr(node, "lineno", 0) or 0
            end = getattr(node, "end_lineno", start) or start
            if changed and not any(start <= ln <= end for ln in changed):
                continue
            out.append({"path": fd.path, "name": node.name, "complexity": _cyclomatic(node)})
    out.sort(key=lambda f: f["complexity"], reverse=True)
    return out


def _complexity_for_diff(repo_root: Path, diff: DiffSet) -> dict[str, int]:
    out: dict[str, int] = {}
    for fd in diff.files:
        if fd.skip or not fd.path.endswith(".py"):
            continue
        changed = _changed_lines(fd)
        path = repo_root / fd.path
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        score = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = getattr(node, "lineno", 0) or 0
            end = getattr(node, "end_lineno", start) or start
            if changed and not any(start <= ln <= end for ln in changed):
                continue
            score += _cyclomatic(node)
        if score:
            out[fd.path] = score
    return out


def _cyclomatic(node: ast.AST) -> int:
    n = 1
    for child in ast.iter_child_nodes(node):
        n += _cyclomatic_body(child)
    return n


def _cyclomatic_body(node: ast.AST) -> int:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return 0
    n = 0
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.Assert)):
        n += 1
    elif isinstance(node, ast.BoolOp):
        n += max(0, len(node.values) - 1)
    elif isinstance(node, ast.comprehension):
        n += 1
    for child in ast.iter_child_nodes(node):
        n += _cyclomatic_body(child)
    return n


def _changed_lines(fd: FileDiff) -> set[int]:
    lines: set[int] = set()
    new_line = 0
    for raw in (fd.patch or "").splitlines():
        if raw.startswith("@@"):
            # @@ -a,b +c,d @@
            plus = raw.split("+", 1)[-1]
            start = plus.split(",")[0].split(" ")[0]
            try:
                new_line = int(start)
            except ValueError:
                new_line = 0
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            if new_line:
                lines.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    return lines


def _sourcey(path: str) -> bool:
    return path.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))


def _cross_context(a: str, b: str, config: LoadpathConfig) -> bool:
    ca = config.context_for_react_path(a) or _django_ctx(a, config)
    cb = config.context_for_react_path(b) or _django_ctx(b, config)
    return bool(ca and cb and ca != cb)


def _django_ctx(path: str, config: LoadpathConfig) -> str | None:
    parts = path.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part == config.django_root and i + 1 < len(parts):
            return config.context_for_django_app(parts[i + 1])
        if part in config.contexts:
            return part
    for ctx in config.contexts.values():
        for app in ctx.django_apps:
            if f"/{app}/" in f"/{path}/":
                return ctx.name
    return None
