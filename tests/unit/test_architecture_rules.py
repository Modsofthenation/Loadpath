from __future__ import annotations

from pathlib import Path

from loadpath.architecture.rules import _nplusone, _related_accesses, evaluate
from loadpath.config import load_config
from loadpath.graph.store import GraphStore
from loadpath.index import index_repo
from loadpath.types import EdgeType, Node, NodeType, node_id

from tests.conftest import FIXTURE_ROOT as FIXTURE


def test_queryset_rule_and_task_rule(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    cfg = load_config(FIXTURE)
    findings = evaluate(store, cfg)
    # healthy fixture: task uses invoice_id, no queryset in serializer
    assert not any(f.rule == "no_queryset_in_serializer" and not f.waived for f in findings)
    assert not any(
        f.rule == "celery_tasks_must_be_idempotent_on_model_pk" and not f.waived for f in findings
    )
    store.close()


def test_foreign_model_import_is_blocker(tmp_path: Path):
    # mutate a copy
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    leak = root / "backend/billing/views.py"
    text = leak.read_text()
    leak.write_text("from accounts.models import UserProfile\n" + text)
    store = index_repo(root, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(root))
    hits = [f for f in findings if f.rule == "views_cannot_import_other_context_models" and not f.waived]
    assert hits, findings
    store.close()


def test_react_feature_calling_other_context_api(tmp_path: Path):
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    api = root / "frontend/src/features/billing/api.ts"
    api.write_text(api.read_text() + "\nexport const me = () => fetch('/api/me');\n")
    store = index_repo(root, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(root))
    hits = [
        f
        for f in findings
        if f.rule == "react_feature_may_only_call_own_or_shared_api" and not f.waived
    ]
    assert hits, [f.message for f in findings]
    store.close()


def test_nplusone_rule_on_fixture_service(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(FIXTURE))
    hits = [f for f in findings if f.rule == "queryset_nplusone" and not f.waived]
    assert hits
    assert any("account" in f.message for f in hits)
    store.close()


def _field(name: str, field_type: str, app: str = "billing") -> Node:
    qname = f"{app}.Invoice.{name}"
    return Node(
        id=node_id(NodeType.FIELD, qname),
        type=NodeType.FIELD,
        name=name,
        qualified_name=qname,
        extra={
            "app": app,
            "field_type": field_type,
            "relation": field_type in {"ForeignKey", "OneToOneField", "ManyToManyField"},
        },
    )


def test_related_accesses_drops_charfield_keeps_fk():
    fields = {
        "status": [_field("status", "CharField").to_row()],
        "account": [_field("account", "ForeignKey").to_row()],
    }
    related, conf = _related_accesses(["status", "account"], fields, "billing")
    assert related == ["account"]
    assert conf == "high"
    related, conf = _related_accesses(["status"], fields, "billing")
    assert related == []
    related, conf = _related_accesses(["ghost"], fields, "billing")
    assert related == ["ghost"]
    assert conf == "medium"


def test_nplusone_schema_aware_does_not_add_edges(tmp_path: Path):
    store = GraphStore(tmp_path / "g.sqlite3")
    status = _field("status", "CharField")
    account = _field("account", "ForeignKey")
    service = Node(
        id=node_id(NodeType.SERVICE, "billing.overdue"),
        type=NodeType.SERVICE,
        name="overdue",
        qualified_name="billing.overdue",
        extra={
            "app": "billing",
            "nplusone": [
                {
                    "accessed": ["status"],
                    "loop_var": "invoice",
                    "line": 4,
                    "suggested_fix": ".select_related()",
                },
                {
                    "accessed": ["account"],
                    "loop_var": "invoice",
                    "line": 8,
                    "suggested_fix": ".select_related('account')",
                },
            ],
        },
    )
    store.upsert_node(status)
    store.upsert_node(account)
    store.upsert_node(service)
    store.conn.commit()
    before = store.edges()
    hits = _nplusone(store)
    assert not any("status" in (f.extra.get("accessed") or []) for f in hits)
    assert any(f.extra.get("accessed") == ["account"] and f.extra.get("confidence") == "high" for f in hits)
    assert store.edges() == before
    assert not any(e["type"] == EdgeType.RELATES_TO.value for e in store.edges())
    store.close()


def test_nplusone_charfield_is_not_a_residual(tmp_path: Path):
    from loadpath.review.engine import collect_residuals

    store = GraphStore(tmp_path / "g.sqlite3")
    status = _field("status", "CharField")
    account = _field("account", "ForeignKey")
    service = Node(
        id=node_id(NodeType.SERVICE, "billing.overdue"),
        type=NodeType.SERVICE,
        name="overdue",
        qualified_name="billing.overdue",
        extra={
            "app": "billing",
            "nplusone": [
                {
                    "accessed": ["status"],
                    "loop_var": "invoice",
                    "line": 4,
                    "suggested_fix": ".select_related()",
                }
            ],
        },
    )
    store.upsert_node(status)
    store.upsert_node(account)
    store.upsert_node(service)
    store.conn.commit()
    blob = " ".join(collect_residuals(store, [service.to_row()]))
    assert "N+1" not in blob
    assert "status" not in blob
    store.close()


def test_cascade_across_contexts_is_warning(tmp_path: Path):
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    models = root / "backend/billing/models.py"
    models.write_text(
        models.read_text().replace(
            'account = models.ForeignKey("accounts.UserProfile", null=True, on_delete=models.SET_NULL)',
            'account = models.ForeignKey("accounts.UserProfile", null=True, on_delete=models.CASCADE)',
        )
    )
    store = index_repo(root, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(root))
    hits = [f for f in findings if f.rule == "cascade_crosses_context" and not f.waived]
    assert hits, [f.message for f in findings]
    assert any("Deleting" in f.message and "UserProfile" in f.message for f in hits)
    store.close()


def test_migration_blast_radius_for_remove_field(tmp_path: Path):
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / "backend/billing/migrations/0002_remove_total.py").write_text(
        "from django.db import migrations\n\n"
        "class Migration(migrations.Migration):\n"
        "    operations = [migrations.RemoveField(model_name='Invoice', name='total')]\n"
    )
    models = root / "backend/billing/models.py"
    models.write_text(models.read_text().replace("    total = models.DecimalField(max_digits=10, decimal_places=2)\n", ""))
    store = index_repo(root, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(root))
    hits = [f for f in findings if f.rule == "migration_blast_radius" and not f.waived]
    assert hits
    assert any("InvoiceSerializer.total" in f.message or "total" in f.message for f in hits)
    store.close()


def test_migration_blast_radius_keyword_order(tmp_path: Path):
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / "backend/billing/migrations/0002_remove_total.py").write_text(
        "from django.db import migrations\n\n"
        "class Migration(migrations.Migration):\n"
        "    operations = [migrations.RemoveField(name='total', model_name='Invoice')]\n"
    )
    models = root / "backend/billing/models.py"
    models.write_text(models.read_text().replace("    total = models.DecimalField(max_digits=10, decimal_places=2)\n", ""))
    store = index_repo(root, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(root))
    hits = [f for f in findings if f.rule == "migration_blast_radius" and not f.waived]
    assert hits
    assert any("total" in f.message for f in hits)
    store.close()


def test_missing_index_on_unindexed_filter(tmp_path: Path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    findings = evaluate(store, load_config(FIXTURE))
    hits = [f for f in findings if f.rule == "queryset_missing_index" and not f.waived]
    assert hits
    assert any("status" in f.message for f in hits)
    store.close()
