from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loadpath.review.engine import run_review
from loadpath.review.render import render_html, render_markdown
from loadpath.server.app import create_app
from tests.conftest import copy_fixture, git_commit_all, git_init_with_main


def _change_serializer_total(repo: Path) -> None:
    path = repo / "backend/billing/serializers.py"
    text = path.read_text()
    path.write_text(
        text.replace(
            'fields = ["id", "customer_id", "total", "status"]',
            'fields = ["id", "customer_id", "total", "status"]\n        extra_kwargs = {"total": {"required": True}}',
        )
    )


def test_serializer_field_change_traces_to_react_form(tmp_path: Path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    _change_serializer_total(repo)
    git_commit_all(repo, "tighten Invoice.total contract")

    review = run_review(repo, base="HEAD~1", head="HEAD")
    node_types = {n["type"] for n in review["nodes"]}
    names = {n["name"] for n in review["nodes"]}

    assert "django.serializer" in node_types or "django.serializer_field" in node_types
    assert "total" in names or any("total" in (n.get("qualified_name") or "") for n in review["nodes"])
    assert any(n["type"] == "django.route" for n in review["nodes"])
    assert any(n["type"] == "react.api_client" for n in review["nodes"])
    assert any(n["name"] in {"useInvoice", "InvoicePage", "InvoiceForm", "invoiceSchema"} for n in review["nodes"])
    assert any(n["type"] == "react.form_schema" for n in review["nodes"])
    assert any(n["type"] == "django.task" and "send_invoice_email" in n["name"] for n in review["nodes"])
    assert any(n["type"] == "react.page" and n["name"] == "InvoicePage" for n in review["nodes"])
    assert not any(n["name"] in {"MePage", "MeView", "MeSerializer"} for n in review["nodes"])
    assert review["suggested_reviewers"] == ["billing-team"]
    assert any(e["type"] == "consumed_by_client" for e in review["edges"])
    assert any(e["type"] == "matches_schema" for e in review["edges"])

    assert review["confidence"]["level"] in {"medium", "low"}
    assert "cross_context" not in review["change_kinds"]
    assert "public_contract" in review["change_kinds"]
    assert any("billing" in (r.lower()) for r in review["suggested_reviewers"]) or review["suggested_reviewers"] == [
        "billing-team"
    ]

    md = render_markdown(review)
    assert "Loadpath:" in md
    assert "Invoice" in md or "total" in md.lower()
    html = render_html(review)
    assert "vis-network" in html
    assert review["nodes"]

    # residual: signal and/or inferred client stitch
    blob = " ".join(review["residuals"]) + review["tests_note"] + review["headline"]
    assert "InvoiceForm" in blob or "update_ledger" in blob or "inferred" in blob.lower() or "RTL" in blob or "test" in blob.lower()
    assert "update_ledger" in " ".join(review["residuals"])


def test_leaf_css_is_low_risk(tmp_path: Path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    css = repo / "frontend/src/features/billing/InvoiceForm.module.css"
    css.write_text(".form { padding: 8px; }\n")
    git_commit_all(repo, "leaf padding")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    # css is skipped as non-source; remaining empty / low
    assert review["low_risk"] or not review["clusters"] or review["confidence"]["level"] == "high"


def test_contract_drift_when_serializer_drops_field(tmp_path: Path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    path = repo / "backend/billing/serializers.py"
    path.write_text(path.read_text().replace('"total", ', ""))
    git_commit_all(repo, "remove total from serializer")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    rules = [f["rule"] for f in review["findings"] if not f.get("waived")]
    assert "serializers_are_the_only_published_contract" in rules
    assert review["confidence"]["level"] == "low"


def test_api_review_endpoint(tmp_path: Path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    _change_serializer_total(repo)
    git_commit_all(repo, "total")
    client = TestClient(create_app())
    r = client.post("/api/index", json={"repo_path": str(repo), "incremental": False})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["nodes"] > 10
    r = client.post(
        "/api/review",
        json={"repo_path": str(repo), "base": "HEAD~1", "head": "HEAD", "reindex": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confidence"]["level"] in {"high", "medium", "low"}
    assert "markdown" in body
    g = client.get("/api/graph", params={"repo_path": str(repo)})
    assert g.status_code == 200
    assert g.json()["counts"]["nodes"] > 0
