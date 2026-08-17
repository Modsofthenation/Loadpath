#!/usr/bin/env python3
"""Check that package versions agree, and optionally match a git tag."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = (
    "pyproject.toml",
    "src/loadpath/__init__.py",
    "desktop/package.json",
    "ui/package.json",
    "editors/vscode/package.json",
)
PRE_RELEASE_RE = re.compile(r"(?:a|b|rc|dev|-)", re.IGNORECASE)


def _pyproject_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _init_version(root: Path) -> str:
    text = (root / "src/loadpath/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not find __version__ in src/loadpath/__init__.py")
    return match.group(1)


def _json_version(root: Path, rel: str) -> str:
    data = json.loads((root / rel).read_text(encoding="utf-8"))
    return str(data["version"])


def collect_versions(root: Path) -> dict[str, str]:
    return {
        "pyproject.toml": _pyproject_version(root),
        "src/loadpath/__init__.py": _init_version(root),
        "desktop/package.json": _json_version(root, "desktop/package.json"),
        "ui/package.json": _json_version(root, "ui/package.json"),
        "editors/vscode/package.json": _json_version(root, "editors/vscode/package.json"),
    }


def is_prerelease(version: str) -> bool:
    return bool(PRE_RELEASE_RE.search(version))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="", help="Git tag that must equal v{version}")
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Append version, tag, ref, and prerelease to $GITHUB_OUTPUT",
    )
    args = parser.parse_args(argv)

    versions = collect_versions(ROOT)
    unique = set(versions.values())
    if len(unique) != 1:
        print("Version mismatch across package files:", file=sys.stderr)
        for loc in VERSION_FILES:
            print(f"  {loc}: {versions[loc]}", file=sys.stderr)
        return 1

    version = unique.pop()
    tag = args.tag.strip()
    if tag.startswith("refs/tags/"):
        tag = tag.removeprefix("refs/tags/")
    expected_tag = f"v{version}"
    if tag and tag != expected_tag:
        print(f"Tag {tag!r} does not match package version {expected_tag!r}", file=sys.stderr)
        return 1

    resolved_tag = tag or expected_tag
    prerelease = "true" if is_prerelease(version) else "false"
    print(f"version={version}")
    print(f"tag={resolved_tag}")
    print(f"prerelease={prerelease}")

    if args.github_output:
        github_output = os.environ.get("GITHUB_OUTPUT")
        if not github_output:
            print("GITHUB_OUTPUT is not set", file=sys.stderr)
            return 1
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")
            handle.write(f"tag={resolved_tag}\n")
            handle.write(f"ref={resolved_tag}\n")
            handle.write(f"prerelease={prerelease}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
