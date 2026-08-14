from __future__ import annotations

from loadpath.config import load_config
from loadpath.extractors.django_boot import try_boot_models
from loadpath.index import index_repo
from loadpath.review.engine import run_review
from loadpath.types import NodeType
from tests.conftest import FIXTURE_ROOT, copy_fixture, git_commit_all, git_init_with_main, prepare_review_repo


def test_serializer_change_includes_celery_and_dramatiq_sinks(tmp_path):
    repo = prepare_review_repo(tmp_path)
    review = run_review(repo, base="HEAD~1", head="HEAD")
    names = {n["name"] for n in review["nodes"]}
    types = {n["type"] for n in review["nodes"]}
    assert "send_invoice_email" in names
    assert "rebuild_ledger" in names
    assert "django.task" in types
    brokers = {
        (n.get("extra") or {}).get("broker")
        for n in review["nodes"]
        if n["type"] == "django.task"
    }
    assert "celery" in brokers
    assert "dramatiq" in brokers
    assert any(e["type"] == "enqueues" for e in review["edges"])


def test_dramatiq_actor_change_is_its_own_load_path(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    actors = repo / "backend/billing/actors.py"
    actors.write_text(actors.read_text().replace("return str(invoice.total)", "return f'{invoice.total:.2f}'"))
    git_commit_all(repo, "touch dramatiq actor")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    assert any(n["name"] == "rebuild_ledger" for n in review["nodes"])
    assert any((n.get("extra") or {}).get("broker") == "dramatiq" for n in review["nodes"])


def test_non_idempotent_dramatiq_task_warns(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    (repo / "backend/billing/actors.py").write_text(
        "import dramatiq\n\n@dramatiq.actor\ndef blast(invoice):\n    return invoice\n"
    )
    git_commit_all(repo, "unsafe dramatiq payload")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    rules = [f["rule"] for f in review["findings"] if not f.get("waived")]
    assert "celery_tasks_must_be_idempotent_on_model_pk" in rules
    assert any("Dramatiq" in f["message"] for f in review["findings"])


def test_destructive_migration_is_classified(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    mig = repo / "backend/billing/migrations/0002_remove_total.py"
    mig.write_text(
        "from django.db import migrations\n\n"
        "class Migration(migrations.Migration):\n"
        "    operations = [migrations.RemoveField(model_name='Invoice', name='total')]\n"
    )
    git_commit_all(repo, "remove total field")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    assert "schema_migration" in review["change_kinds"]
    assert any(n["type"] == "django.migration_op" for n in review["nodes"])
    assert any(e["type"] == "destructive_migration" for e in review["edges"])


def test_cross_context_view_is_blocker_on_pr(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    views = repo / "backend/billing/views.py"
    views.write_text("from accounts.models import UserProfile\n" + views.read_text())
    git_commit_all(repo, "leak identity model")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    assert "cross_context" in review["change_kinds"]
    assert review["confidence"]["level"] == "low"
    assert any(f["rule"] == "views_cannot_import_other_context_models" for f in review["findings"])


def test_django_boot_overlay_reports_skip_or_models(tmp_path):
    cfg = load_config(FIXTURE_ROOT)
    cfg.boot_django = True
    graph = try_boot_models(FIXTURE_ROOT, cfg)
    assert graph.residuals
    assert any("django.setup()" in r for r in graph.residuals)
    # Either Django isn't installed, settings failed, or models were booted.
    if any(n.type is NodeType.MODEL and (n.extra or {}).get("booted") for n in graph.nodes):
        assert any(n.name == "Invoice" for n in graph.nodes)


def test_boot_payload_ignores_stdout_noise():
    from loadpath.extractors.django_boot import BOOT_JSON_MARKER, _parse_boot_payload

    raw = (
        "Watching for file changes with StatReloader\n"
        + BOOT_JSON_MARKER
        + '{"nodes":[],"edges":[],"residuals":["django.setup() skipped: boom"]}\n'
    )
    data = _parse_boot_payload(raw)
    assert data is not None
    assert data["residuals"][0].startswith("django.setup() skipped:")


def test_boot_payload_malformed_nodes_become_residual():
    from loadpath.extractors.django_boot import _graph_from_boot_data

    graph = _graph_from_boot_data({"nodes": [{"id": 1}], "edges": [], "residuals": []})
    assert not graph.nodes
    assert any("django.setup() skipped: boot payload malformed" in r for r in graph.residuals)


def test_index_counts_grow_with_new_django_files(tmp_path):
    store = index_repo(FIXTURE_ROOT, db_path=tmp_path / "g.sqlite3", incremental=False)
    types = {n["type"] for n in store.nodes()}
    assert "django.task" in types
    assert "django.management_command" in types
    tasks = [n for n in store.nodes() if n["type"] == "django.task"]
    brokers = {(n.get("extra") or {}).get("broker") for n in tasks}
    assert {"celery", "dramatiq"} <= brokers
    names = {n["name"] for n in tasks}
    assert "RecalcTotals" in names
    assert "NotifyCustomer" in names
    assert any((n.get("extra") or {}).get("beat") for n in tasks)
    store.close()


def test_celery_canvas_and_send_task_are_residuals_on_task_pr(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    tasks = repo / "backend/billing/tasks.py"
    tasks.write_text(tasks.read_text() + "\n# touch canvas\n")
    git_commit_all(repo, "touch celery canvas")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    blob = " ".join(review["residuals"])
    assert "send_task" in blob or "canvas" in blob.lower()
    assert any(n["name"] == "send_invoice_email" for n in review["nodes"])


def test_management_command_change_traces_to_celery(tmp_path):
    repo = copy_fixture(tmp_path)
    git_init_with_main(repo)
    cmd = repo / "backend/billing/management/commands/resend_invoices.py"
    cmd.write_text(cmd.read_text().replace("invoice.id", "invoice.pk"))
    git_commit_all(repo, "command uses pk")
    review = run_review(repo, base="HEAD~1", head="HEAD")
    names = {n["name"] for n in review["nodes"]}
    assert "resend_invoices" in names
    assert "send_invoice_email" in names
    assert any(e["type"] == "enqueues" for e in review["edges"])


def test_ninja_and_fbv_are_indexed(tmp_path):
    store = index_repo(FIXTURE_ROOT, db_path=tmp_path / "g.sqlite3", incremental=False)
    names = {n["name"] for n in store.nodes()}
    assert "invoice_totals" in names
    assert any("ledger" in n["name"] for n in store.nodes() if n["type"] == "django.route")
    store.close()
