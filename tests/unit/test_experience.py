from __future__ import annotations

from loadpath.config import add_waiver, config_document, load_config, write_config
from loadpath.review.codeowners import owners_for_path, parse_codeowners, review_codeowners
from loadpath.review.editor import editor_urls
from loadpath.review.experience import (
    architecture_health,
    attach_experience,
    checklist,
    contract_sides,
    diff_reviews,
    file_marks,
    isolate_paths,
    match_reviews_to_prs,
    node_roles,
    summarize_stored_review,
)
from loadpath.workspace import workspace_status

from tests.conftest import prepare_review_repo


def test_codeowners_last_match_wins():
    rules = parse_codeowners(
        "* @everyone\n"
        "/backend/ @backend-team\n"
        "/backend/billing/ @billing-team @alice\n"
        "*.md @docs\n"
    )
    assert owners_for_path("frontend/src/App.tsx", rules) == ["@everyone"]
    assert owners_for_path("backend/accounts/models.py", rules) == ["@backend-team"]
    assert owners_for_path("backend/billing/serializers.py", rules) == ["@billing-team", "@alice"]
    assert owners_for_path("README.md", rules) == ["@docs"]


def test_review_codeowners_from_github_file(tmp_path):
    repo = tmp_path / "repo"
    github = repo / ".github"
    github.mkdir(parents=True)
    (github / "CODEOWNERS").write_text("/backend/billing/ @billing-team\n", encoding="utf-8")
    result = review_codeowners(repo, ["backend/billing/serializers.py", "frontend/src/App.tsx"])
    assert result["owners"] == ["@billing-team"]
    assert result["files"][0]["path"] == "backend/billing/serializers.py"


def test_node_roles_seed_downstream_tested():
    nodes = [
        {"id": "ser", "type": "django.serializer", "name": "InvoiceSerializer"},
        {"id": "page", "type": "react.page", "name": "InvoicePage"},
        {"id": "test", "type": "django.test", "name": "test_invoice"},
    ]
    edges = [
        {"id": "e1", "src": "ser", "dst": "page", "type": "consumed_by_client", "confidence": 1},
        {"id": "e2", "src": "ser", "dst": "test", "type": "tested_by", "confidence": 1},
    ]
    roles = node_roles(nodes, edges, {"ser"})
    assert "seed" in roles["ser"]
    assert "contract" in roles["ser"]
    assert "tested" in roles["ser"]
    assert "downstream" in roles["page"]
    assert "sink" in roles["page"]
    assert "untested" in roles["page"]


def test_contract_sides_flags_missing_zod_field():
    nodes = [
        {"id": "f1", "type": "django.serializer_field", "name": "total"},
        {"id": "f2", "type": "django.serializer_field", "name": "status"},
        {"id": "z", "type": "react.form_schema", "name": "InvoiceSchema", "extra": {"fields": ["status"]}},
    ]
    sides = contract_sides(nodes, ["total"])
    by_name = {row["field"]: row for row in sides["rows"]}
    assert by_name["total"]["serializer"] is True
    assert by_name["total"]["zod"] is False
    assert by_name["total"]["status"] == "missing_client"
    assert by_name["status"]["status"] == "aligned"


def test_checklist_ready_when_high_and_clean():
    items = checklist(
        {
            "confidence": {"level": "high", "untested_sinks": []},
            "findings": [],
            "residuals": [],
            "low_risk": True,
            "contract_break": {"kind": "none"},
        }
    )
    assert items[0]["kind"] == "ready"
    assert items[0]["status"] == "done"


def test_checklist_todos_for_blocker_and_untested():
    items = checklist(
        {
            "confidence": {
                "level": "low",
                "untested_sinks": [{"id": "page", "name": "InvoicePage", "type": "react.page"}],
            },
            "findings": [
                {
                    "rule": "views_cannot_import_other_context_models",
                    "severity": "blocker",
                    "message": "billing view imports accounts",
                    "node_id": "view",
                    "waived": False,
                }
            ],
            "suggested_tests": [
                {"sink": "InvoicePage", "title": "Render InvoicePage", "body": "it('renders') {}"}
            ],
            "contract_break": {"kind": "breaking", "reasons": ["Required total"]},
        }
    )
    kinds = {i["kind"] for i in items}
    assert "finding" in kinds
    assert "test" in kinds
    assert "contract" in kinds
    blocker = next(i for i in items if i["kind"] == "finding")
    assert blocker["rule"] == "views_cannot_import_other_context_models"
    test_item = next(i for i in items if i["kind"] == "test")
    assert "it('renders')" in (test_item.get("body") or "")


def test_isolate_paths_keeps_only_source_to_sink():
    nodes = [
        {"id": "a", "type": "django.field", "name": "total"},
        {"id": "b", "type": "django.serializer", "name": "Ser"},
        {"id": "c", "type": "django.route", "name": "/api"},
        {"id": "noise", "type": "react.page", "name": "MePage"},
    ]
    edges = [
        {"id": "ab", "src": "a", "dst": "b", "type": "has_field"},
        {"id": "bc", "src": "b", "dst": "c", "type": "publishes_route"},
        {"id": "bn", "src": "b", "dst": "noise", "type": "consumed_by_client"},
    ]
    isolated = isolate_paths(nodes, edges, "a", "c")
    assert set(isolated["node_ids"]) == {"a", "b", "c"}
    assert "bn" not in isolated["edge_ids"]
    assert "ab" in isolated["edge_ids"]


def test_diff_reviews_new_sinks_and_dropped_confidence():
    current = {
        "confidence": {"level": "low"},
        "sinks": [{"name": "InvoicePage"}, {"name": "send_invoice_email"}],
        "findings": [],
        "contract_break": {"kind": "breaking"},
    }
    previous = {
        "confidence": {"level": "medium"},
        "sinks": [{"name": "InvoicePage"}],
        "findings": [],
        "contract_break": {"kind": "additive"},
    }
    diff = diff_reviews(current, previous)
    assert diff["direction"] == "dropped"
    assert "send_invoice_email" in diff["added_sinks"]
    assert "breaking" in diff["note"]


def test_summarize_and_match_pr():
    item = {
        "id": "abc",
        "created_at": "2026-01-01T00:00:00+00:00",
        "base_ref": "main",
        "head_ref": "feature/total",
        "payload": {
            "title": "Invoice.total",
            "confidence": {"level": "medium", "sinks": 3, "covered_sinks": 1},
            "contract_break": {"kind": "breaking"},
            "findings": [{"waived": False}],
        },
    }
    summary = summarize_stored_review(item)
    assert summary["level"] == "medium"
    assert summary["contract_break"] == "breaking"
    matched = match_reviews_to_prs(
        [summary],
        [{"number": 12, "source_branch": "feature/total", "target_branch": "main", "title": "x"}],
    )
    assert matched[0]["loadpath"]["id"] == "abc"


def test_architecture_health_points():
    health = architecture_health(
        [
            {
                "id": "1",
                "created_at": "2026-01-01T00:00:00Z",
                "payload": {
                    "confidence": {"level": "high", "sinks": 1},
                    "findings": [],
                    "edges": [{"confidence": 1}],
                    "nodes": [],
                },
            },
            {
                "id": "2",
                "created_at": "2026-01-02T00:00:00Z",
                "payload": {
                    "confidence": {"level": "low", "sinks": 4},
                    "findings": [{"node_id": "n1", "waived": False}],
                    "edges": [{"confidence": 0.4}, {"confidence": 1}],
                    "nodes": [{"id": "n1", "context": "billing"}],
                },
            },
        ]
    )
    assert len(health["points"]) == 2
    assert health["points"][-1]["findings"] == 1
    assert health["contexts"]["billing"][-1]["findings"] == 1


def test_file_marks_badge_prefers_seed(tmp_path):
    review = {
        "seed_ids": ["ser"],
        "nodes": [
            {
                "id": "ser",
                "type": "django.serializer",
                "name": "InvoiceSerializer",
                "file_path": "backend/billing/serializers.py",
                "start_line": 4,
            }
        ],
        "edges": [],
    }
    attach_experience(review, seed_ids={"ser"})
    marks = file_marks(review)
    assert marks[0]["badge"] == "S"
    assert "seed" in marks[0]["roles"]


def test_write_config_and_waiver(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "loadpath.yml").write_text(
        "contexts:\n  billing:\n    django_apps: [billing]\n    owners: [billing-team]\nrules:\n  - leaked_seam\n",
        encoding="utf-8",
    )
    write_config(
        repo,
        {
            "contexts": {
                "billing": {
                    "django_apps": ["billing"],
                    "react": ["frontend/src/features/billing"],
                    "public_api": ["GET /api/invoices"],
                    "owners": ["billing-team"],
                }
            },
            "rules": ["leaked_seam", "tests_bypass_interface"],
        },
    )
    doc = config_document(load_config(repo))
    assert doc["contexts"]["billing"]["react"] == ["frontend/src/features/billing"]
    waived = add_waiver(repo, "leaked_seam", "django.view:billing.InvoiceViewSet", "legacy")
    assert waived["waivers"][0]["rule"] == "leaked_seam"
    assert "legacy" in (repo / "loadpath.yml").read_text()


def test_workspace_status_fingerprint_changes(tmp_path):
    repo = prepare_review_repo(tmp_path)
    clean = workspace_status(repo)
    assert clean["fingerprint"] == "clean"
    (repo / "backend/billing/serializers.py").write_text("changed\n", encoding="utf-8")
    dirty = workspace_status(repo)
    assert dirty["dirty_count"] >= 1
    assert dirty["fingerprint"] != "clean"
    (repo / "backend/billing/serializers.py").write_text("changed again\n", encoding="utf-8")
    later = workspace_status(repo)
    assert later["fingerprint"] != dirty["fingerprint"]


def test_editor_urls_include_line():
    from pathlib import Path

    urls = editor_urls(Path("/tmp/acme/backend/a.py"), 12)
    assert urls["cursor"].endswith("a.py:12")
    assert urls["vscode"].startswith("vscode://file/")
