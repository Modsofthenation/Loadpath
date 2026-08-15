from __future__ import annotations

from pathlib import Path

from loadpath.architecture.depth import deepening_candidates, evaluate_depth
from loadpath.architecture.rules import evaluate
from loadpath.config import load_config
from loadpath.index import index_repo
from loadpath.review.engine import run_review
from loadpath.review.render import render_markdown
from tests.conftest import FIXTURE_ROOT as FIXTURE
from tests.conftest import prepare_review_repo


def test_fixture_leaks_queryset_past_query_module(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate_depth(store, load_config(FIXTURE))
    hits = [f for f in findings if f.rule == "leaked_seam"]
    assert hits, [f.message for f in findings]
    assert any("InvoiceViewSet" in f.message and "seam" in f.message for f in hits)
    assert any(f.extra.get("strength") == "strong" for f in hits)
    store.close()


def test_fixture_tests_bypass_published_route_seam(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate_depth(store, load_config(FIXTURE))
    hits = [f for f in findings if f.rule == "tests_bypass_interface"]
    assert hits, [f.message for f in findings]
    assert any("interface is the test surface" in f.message for f in hits)
    store.close()


def test_architecture_survey_ranks_a_top_candidate(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(FIXTURE))
    cards = deepening_candidates(findings)
    assert cards
    assert cards[0]["top"] is True
    assert cards[0]["strength"] in {"strong", "worth_exploring", "speculative"}
    assert cards[0]["deletion_test"]
    store.close()


def test_review_scopes_depth_to_the_change(tmp_path: Path):
    repo = prepare_review_repo(tmp_path)
    review = run_review(repo, base="HEAD~1", head="HEAD")
    assert review["depth_note"]
    assert "Depth:" in review["headline"]
    rules = {f["rule"] for f in review["findings"] if not f.get("waived")}
    assert "leaked_seam" in rules or "tests_bypass_interface" in rules
    md = render_markdown(review)
    assert "### Depth" in md
    assert review["deepening"]
    assert review["deepening"][0]["top"] is True
