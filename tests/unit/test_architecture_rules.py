from __future__ import annotations

from pathlib import Path

from loadpath.architecture.rules import evaluate
from loadpath.config import load_config
from loadpath.index import index_repo
from loadpath.types import NodeType

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
