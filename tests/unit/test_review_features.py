from __future__ import annotations

from loadpath.review.auth import auth_path
from loadpath.review.contract import classify_contract_break
from loadpath.review.diff import DiffSet, FileDiff, git_diff
from loadpath.review.engine import classify_change, run_review
from loadpath.review.gate import FAIL_ON_CHOICES, gate_result, write_github_output
from loadpath.review.suggested_tests import suggested_tests
from loadpath.review.trend import confidence_trend
from loadpath.review.whatif import simulate_node
from loadpath.types import ChangeKind, ContractBreakKind

from tests.conftest import copy_fixture, git_commit_all, git_init_with_main, prepare_review_repo


def test_contract_break_required_field_is_breaking():
    diff = DiffSet(
        files=[
            FileDiff(
                path="backend/billing/serializers.py",
                status="M",
                patch='+        extra_kwargs = {"total": {"required": True}}\n',
            )
        ]
    )
    nodes = [
        {
            "type": "django.serializer",
            "name": "InvoiceSerializer",
            "file_path": "backend/billing/serializers.py",
        }
    ]
    result = classify_contract_break(nodes, diff)
    assert result["kind"] == ContractBreakKind.BREAKING.value
    assert "total" in result["fields"]


def test_contract_break_ignores_removed_required_true():
    diff = DiffSet(
        files=[
            FileDiff(
                path="backend/billing/serializers.py",
                status="M",
                patch='-        extra_kwargs = {"total": {"required": True}}\n',
            )
        ]
    )
    nodes = [
        {
            "type": "django.serializer",
            "name": "InvoiceSerializer",
            "file_path": "backend/billing/serializers.py",
        }
    ]
    result = classify_contract_break(nodes, diff)
    assert result["kind"] == ContractBreakKind.ADDITIVE.value
    assert "Required contract field" not in " ".join(result["reasons"])


def test_contract_break_ignores_untouched_graphql():
    diff = DiffSet(
        files=[
            FileDiff(
                path="backend/billing/serializers.py",
                status="M",
                patch="+        extra_kwargs = {\"total\": {\"required\": True}}\n",
            )
        ]
    )
    nodes = [
        {
            "type": "django.serializer",
            "name": "InvoiceSerializer",
            "file_path": "backend/billing/serializers.py",
        },
        {
            "type": "graphql.operation",
            "name": "invoice",
            "file_path": "backend/billing/schema.py",
        },
    ]
    result = classify_contract_break(nodes, diff)
    assert result["kind"] == ContractBreakKind.BREAKING.value
    assert not any("GraphQL" in r for r in result["reasons"])


def test_auth_path_flags_missing_permissions():
    views = [
        {
            "id": "django.view:billing.OpenView",
            "type": "django.view",
            "name": "OpenView",
            "extra": {},
        },
        {
            "id": "django.view:billing.InvoiceViewSet",
            "type": "django.view",
            "name": "InvoiceViewSet",
            "extra": {"permissions": ["IsAuthenticated"], "get_queryset": True},
        },
    ]
    routes = [
        {
            "id": "django.websocket_route:billing:ws/invoices/",
            "type": "django.websocket_route",
            "name": "ws/invoices/",
            "extra": {"websocket": True},
        }
    ]
    class _Store:
        def nodes(self, types=None):
            return []

    result = auth_path(_Store(), views + routes, [])
    names = {m["name"] for m in result["missing_permissions"]}
    assert "OpenView" in names
    assert "ws/invoices/" in names
    assert result["object_scope"]


def test_suggested_tests_cover_new_sinks():
    sketches = suggested_tests(
        [
            {"id": "fastapi.route:x", "name": "GET /internal/invoices/{id}", "type": "fastapi.route"},
            {"id": "graphql.operation:invoice", "name": "invoice", "type": "graphql.operation"},
            {"id": "django.consumer:c", "name": "InvoiceConsumer", "type": "django.consumer"},
            {"id": "django.template:t", "name": "invoice_board.html", "type": "django.template"},
        ],
        [
            {
                "id": "fastapi.route:x",
                "name": "GET /internal/invoices/{id}",
                "type": "fastapi.route",
                "extra": {"route": "/internal/invoices/{id}", "method": "GET"},
            },
            {"id": "graphql.operation:invoice", "name": "invoice", "type": "graphql.operation", "extra": {"kind": "query"}},
            {"id": "django.consumer:c", "name": "InvoiceConsumer", "type": "django.consumer", "extra": {}},
            {"id": "django.template:t", "name": "invoice_board.html", "type": "django.template", "extra": {}},
        ],
    )
    kinds = {s["kind"] for s in sketches}
    assert {"pytest", "graphql", "channels", "django"} <= kinds


def test_gate_fail_on_blocker_and_breaking_contract(tmp_path):
    assert "blocker" in FAIL_ON_CHOICES
    review = {
        "title": "Invoice.total",
        "confidence": {"level": "medium", "sinks": 4},
        "findings": [{"severity": "blocker", "waived": False}],
        "contract_break": {"kind": "breaking"},
    }
    blocked = gate_result(review, "blocker")
    assert blocked["passed"] is False
    assert blocked["exit_code"] == 2
    never = gate_result(review, "never")
    assert never["passed"] is True
    medium = gate_result(
        {
            "title": "x",
            "confidence": {"level": "medium", "sinks": 1},
            "findings": [],
            "contract_break": {"kind": "breaking"},
        },
        "medium",
    )
    assert medium["exit_code"] == 4
    out = tmp_path / "github_output"
    write_github_output(str(out), blocked, review)
    text = out.read_text()
    assert "passed=false" in text
    assert "contract_break=breaking" in text


def test_dirty_diff_includes_uncommitted_and_untracked(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    (repo / "backend/billing/serializers.py").write_text(
        (repo / "backend/billing/serializers.py").read_text() + "\n# dirty\n"
    )
    (repo / "backend/billing/scratch.py").write_text("VALUE = 1\n")
    committed = git_diff(repo, "HEAD", "HEAD", dirty=False)
    dirty = git_diff(repo, "HEAD", "HEAD", dirty=True)
    assert "backend/billing/serializers.py" not in committed.paths or committed.paths == []
    assert "backend/billing/serializers.py" in dirty.paths
    assert "backend/billing/scratch.py" in dirty.paths
    review = run_review(repo, base="HEAD", head="HEAD", dirty=True)
    assert review["workspace"]["dirty_included"] is True
    assert review["workspace"]["dirty_count"] >= 1


def test_whatif_walks_from_invoice_total(tmp_path):
    repo = prepare_review_repo(tmp_path)
    run_review(repo, base="HEAD~1", head="HEAD")
    payload = simulate_node(repo, "django.field:billing.Invoice.total")
    assert payload["ok"] is True
    assert payload["what_if"] is True
    names = {n["name"] for n in payload["nodes"]}
    assert "InvoiceSerializer" in names or "total" in names
    assert payload["sinks"]
    assert payload["read_order"]
    assert payload["auth"]["note"]


def test_confidence_trend_compares_same_range(tmp_path):
    repo = prepare_review_repo(tmp_path)
    first = run_review(repo, base="HEAD~1", head="HEAD")
    second = run_review(repo, base="HEAD~1", head="HEAD", reindex=False)
    trend = second["trend"]
    assert trend["points"]
    assert "Confidence" in trend["note"] or "First review" in trend["note"]
    from loadpath.graph.store import GraphStore
    from loadpath.index import default_db_path

    store = GraphStore(default_db_path(repo))
    note = confidence_trend(store, base=first["base"] if "base" in first else None, head=None)
    store.close()
    assert note["note"]


def test_empty_impact_is_not_leaf_ui():
    assert ChangeKind.LEAF_UI.value not in classify_change([], [])
    assert classify_change([], []) == [ChangeKind.INTERNAL_SERVICE.value]


def test_docs_only_review_does_not_attach_architecture_findings(tmp_path):
    repo = prepare_review_repo(tmp_path)
    (repo / "README.md").write_text("# docs only\n", encoding="utf-8")
    git_commit_all(repo, "docs")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    assert review["nodes"] == []
    assert review["edges"] == []
    assert "leaf_ui" not in review["change_kinds"]
    assert review["findings"] == []
    for item in review["checklist"]:
        assert not item.get("node_id")

