from __future__ import annotations

from pathlib import Path

from loadpath.review.engine import run_review
from tests.conftest import change_serializer_total, copy_fixture, git_commit_all, git_init_with_main


def test_evolution_hotspot_and_cross_context_coupling(tmp_path: Path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    views = repo / "backend/billing/views.py"
    identity = repo / "backend/accounts/models.py"
    for i in range(6):
        views.write_text(views.read_text() + f"\n# churn {i}\n")
        identity.write_text(identity.read_text() + f"\n# churn {i}\n")
        git_commit_all(repo, f"churn {i}")
    change_serializer_total(repo)
    git_commit_all(repo, "tighten Invoice.total contract")

    review = run_review(repo, base="HEAD~1", head="HEAD")
    evo = review["evolution"]
    assert evo["commits_sampled"] >= 7
    hot = [h for h in evo["hotspots"] if h["path"].endswith("billing/views.py")]
    assert hot
    assert hot[0]["commits"] >= 5
    assert hot[0]["bus_factor"] == 1
    assert any("hotspot" in n or "silo" in n for n in evo["notes"])
    coupled = evo["change_coupling"]
    assert any(c.get("cross_context") for c in coupled) or any(
        "accounts/models.py" in f"{c['a']} {c['b']}" for c in coupled
    )
    md = review.get("markdown") or ""
    # engine does not attach markdown; render in the test
    from loadpath.review.render import render_markdown

    text = render_markdown(review)
    assert "Churn" in text
    assert "views.py" in text or evo["notes"]


def test_complexity_does_not_count_unchanged_sibling_methods(tmp_path: Path):
    import subprocess

    from loadpath.review.diff import git_diff
    from loadpath.review.evolution import _complexity_for_diff

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo, stdout=subprocess.DEVNULL)
    subprocess.check_call(["git", "config", "user.email", "loadpath@test"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "Loadpath Tests"], cwd=repo)
    target = repo / "mod.py"
    target.write_text(
        "class Big:\n"
        "    def unchanged(self, a, b, c):\n"
        "        if a:\n"
        "            if b:\n"
        "                if c:\n"
        "                    return 1\n"
        "        return 0\n"
        "    def changed(self):\n"
        "        return 1\n"
    )
    subprocess.check_call(["git", "add", "-A"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "base"], cwd=repo, stdout=subprocess.DEVNULL)
    target.write_text(
        "class Big:\n"
        "    def unchanged(self, a, b, c):\n"
        "        if a:\n"
        "            if b:\n"
        "                if c:\n"
        "                    return 1\n"
        "        return 0\n"
        "    def changed(self, flag):\n"
        "        if flag:\n"
        "            return 2\n"
        "        return 1\n"
    )
    subprocess.check_call(["git", "add", "-A"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "touch changed"], cwd=repo, stdout=subprocess.DEVNULL)
    diff = git_diff(repo, "HEAD~1", "HEAD")
    scores = _complexity_for_diff(repo, diff)
    # changed() has one if → ~2, not the sibling's three nested ifs
    assert scores.get("mod.py", 0) < 6
