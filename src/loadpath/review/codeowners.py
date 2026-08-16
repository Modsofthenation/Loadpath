"""Parse GitHub/GitLab CODEOWNERS and match review files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_COMMENT = re.compile(r"\s+#.*$")
_OWNER = re.compile(r"@[^\s]+|[^\s]+")


def find_codeowners(repo_root: Path) -> Path | None:
    root = repo_root.resolve()
    for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS"):
        path = root / rel
        if path.is_file():
            return path
    return None


def parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    """Return (pattern, owners) in file order. Last matching pattern wins."""
    rules: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = _COMMENT.sub("", raw).strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, rest = parts[0], parts[1:]
        owners = [p for p in rest if p and not p.startswith("#")]
        if owners:
            rules.append((pattern, owners))
    return rules


def _glob_to_re(pattern: str) -> re.Pattern[str]:
    pat = pattern.replace("\\", "/").strip()
    if pat.startswith("/"):
        pat = pat[1:]
        anchored = True
    else:
        anchored = False
    if pat.endswith("/"):
        pat = pat + "**"
    escaped: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            escaped.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("**", i):
            escaped.append(".*")
            i += 2
            continue
        ch = pat[i]
        if ch == "*":
            escaped.append("[^/]*")
        elif ch == "?":
            escaped.append("[^/]")
        else:
            escaped.append(re.escape(ch))
        i += 1
    body = "".join(escaped)
    if anchored:
        return re.compile(rf"^{body}(?:/.*)?$")
    return re.compile(rf"(?:^|/){body}(?:/.*)?$")


def owners_for_path(path: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    normalized = path.replace("\\", "/").removeprefix("./").lstrip("/")
    matched: list[str] = []
    for pattern, owners in rules:
        try:
            rx = _glob_to_re(pattern)
        except re.error:
            continue
        if rx.search(normalized):
            matched = owners
    return list(matched)


def review_codeowners(repo_root: Path, file_paths: list[str]) -> dict[str, Any]:
    path = find_codeowners(repo_root)
    if path is None:
        return {"path": None, "owners": [], "files": []}
    rules = parse_codeowners(path.read_text(encoding="utf-8"))
    files: list[dict[str, Any]] = []
    seen: list[str] = []
    have: set[str] = set()
    for rel in file_paths:
        owners = owners_for_path(rel, rules)
        if not owners:
            continue
        files.append({"path": rel, "owners": owners})
        for owner in owners:
            if owner not in have:
                have.add(owner)
                seen.append(owner)
    root = repo_root.resolve()
    return {
        "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "owners": seen,
        "files": files[:40],
    }
