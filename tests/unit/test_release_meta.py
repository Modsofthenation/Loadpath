from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "release_meta.py"


def _package_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


def _expected_prerelease(version: str) -> str:
    return "true" if re.search(r"(?:a|b|rc|dev|-)", version, re.I) else "false"


def test_current_versions_are_consistent():
    result = _run()
    assert result.returncode == 0, result.stderr
    version = _package_version()
    assert f"version={version}" in result.stdout
    assert f"tag=v{version}" in result.stdout
    assert f"prerelease={_expected_prerelease(version)}" in result.stdout


def test_matching_tag_succeeds():
    version = _package_version()
    result = _run("--tag", f"v{version}")
    assert result.returncode == 0, result.stderr
    assert f"tag=v{version}" in result.stdout


def test_refs_tags_prefix_is_stripped():
    version = _package_version()
    result = _run("--tag", f"refs/tags/v{version}")
    assert result.returncode == 0, result.stderr
    assert f"tag=v{version}" in result.stdout


def test_mismatched_tag_fails():
    result = _run("--tag", "v9.9.9")
    assert result.returncode == 1
    assert "does not match package version" in result.stderr


def test_github_output_writes_actions_fields(tmp_path: Path):
    version = _package_version()
    output = tmp_path / "github_output"
    result = _run("--tag", f"v{version}", "--github-output", env={"GITHUB_OUTPUT": str(output)})
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert f"version={version}" in text
    assert f"tag=v{version}" in text
    assert f"ref=v{version}" in text
    assert f"prerelease={_expected_prerelease(version)}" in text
