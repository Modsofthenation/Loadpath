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
