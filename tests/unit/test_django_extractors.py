from __future__ import annotations

from loadpath.config import load_config
from loadpath.extractors.django import extract_django_file
from loadpath.types import NodeType

from tests.conftest import FIXTURE_ROOT as FIXTURE


def _cfg():
    return load_config(FIXTURE)


def test_extracts_model_fields_and_relations():
    source = (FIXTURE / "backend/billing/models.py").read_text()
    g = extract_django_file("backend/billing/models.py", source, _cfg())
    names = {n.qualified_name: n for n in g.nodes}
    assert "billing.Invoice" in names
    assert "billing.Invoice.total" in names
    assert names["billing.Invoice.total"].type is NodeType.FIELD


def test_extracts_serializer_fields_and_model_link():
    source = (FIXTURE / "backend/billing/serializers.py").read_text()
    g = extract_django_file("backend/billing/serializers.py", source, _cfg())
    fields = [n for n in g.nodes if n.type is NodeType.SERIALIZER_FIELD]
    assert {f.name for f in fields} >= {"id", "customer_id", "total", "status"}
    assert any(e.type.value == "serializes" for e in g.edges)


def test_extracts_view_serializer_permissions_and_enqueue():
    source = (FIXTURE / "backend/billing/views.py").read_text()
    g = extract_django_file("backend/billing/views.py", source, _cfg())
    views = [n for n in g.nodes if n.type is NodeType.VIEW]
    assert any(v.name == "InvoiceViewSet" for v in views)
    assert any(e.type.value == "uses_serializer" for e in g.edges)
    assert any(e.type.value == "enqueues" for e in g.edges)
    assert any(
        e.type.value == "enqueues" and "InvoiceViewSet" in e.src for e in g.edges
    )
    perms = [n for n in g.nodes if n.type is NodeType.PERMISSION]
    assert any(p.name == "IsAuthenticated" for p in perms)


def test_extracts_router_and_path_routes():
    source = (FIXTURE / "backend/billing/urls.py").read_text()
    g = extract_django_file("backend/billing/urls.py", source, _cfg())
    routes = [n for n in g.nodes if n.type is NodeType.ROUTE]
    assert routes
    assert any(e.type.value == "publishes_route" for e in g.edges)


def test_extracts_signal_receiver():
    source = (FIXTURE / "backend/billing/signals.py").read_text()
    g = extract_django_file("backend/billing/signals.py", source, _cfg())
    rec = [n for n in g.nodes if n.type is NodeType.RECEIVER]
    assert rec[0].name == "update_ledger"
    assert rec[0].extra.get("sender") in {"Invoice", "billing.Invoice"}


def test_extracts_celery_task_pk_idempotency():
    source = (FIXTURE / "backend/billing/tasks.py").read_text()
    g = extract_django_file("backend/billing/tasks.py", source, _cfg())
    defined = [
        n
        for n in g.nodes
        if n.type is NodeType.TASK and n.name == "send_invoice_email" and n.extra.get("looks_idempotent_on_pk") is not None
    ]
    assert defined
    assert defined[0].extra["looks_idempotent_on_pk"] is True
    assert defined[0].extra.get("broker") == "celery"


def test_extracts_celery_task_class_canvas_and_send_task():
    source = (FIXTURE / "backend/billing/tasks.py").read_text()
    g = extract_django_file("backend/billing/tasks.py", source, _cfg())
    recalc = next(n for n in g.nodes if n.name == "RecalcTotals")
    assert recalc.type is NodeType.TASK
    assert recalc.extra.get("broker") == "celery"
    assert recalc.extra.get("task_class") is True
    assert any("send_task" in r for r in g.residuals)
    assert any("canvas" in r.lower() for r in g.residuals)
    assert any(
        e.type.value == "enqueues" and "apply_credit" in e.dst for e in g.edges
    )


def test_extracts_dramatiq_actor():
    source = (FIXTURE / "backend/billing/actors.py").read_text()
    g = extract_django_file("backend/billing/actors.py", source, _cfg())
    actors = [n for n in g.nodes if n.type is NodeType.TASK]
    names = {n.name for n in actors}
    assert "rebuild_ledger" in names
    assert "NotifyCustomer" in names
    ledger = next(n for n in actors if n.name == "rebuild_ledger")
    assert ledger.extra.get("broker") == "dramatiq"
    assert ledger.extra["looks_idempotent_on_pk"] is True
    notify = next(n for n in actors if n.name == "NotifyCustomer")
    assert notify.extra.get("task_class") is True


def test_extracts_celery_beat_schedule():
    source = (FIXTURE / "backend/config/settings.py").read_text()
    g = extract_django_file("backend/config/settings.py", source, _cfg())
    assert any(n.extra.get("beat") and n.name == "apply_credit" for n in g.nodes)
    assert any("Celery beat" in r for r in g.residuals)


def test_management_command_enqueues_celery():
    rel = "backend/billing/management/commands/resend_invoices.py"
    source = (FIXTURE / rel).read_text()
    g = extract_django_file(rel, source, _cfg())
    assert any(n.type is NodeType.MANAGEMENT_COMMAND for n in g.nodes)
    assert any(
        e.type.value == "enqueues" and "resend_invoices" in e.src for e in g.edges
    )


def test_view_enqueues_celery_and_dramatiq():
    source = (FIXTURE / "backend/billing/views.py").read_text()
    g = extract_django_file("backend/billing/views.py", source, _cfg())
    brokers = {e.extra.get("broker") for e in g.edges if e.type.value == "enqueues"}
    assert "celery" in brokers
    assert "dramatiq" in brokers
    assert any(n.type is NodeType.VIEW and n.extra.get("fbv") for n in g.nodes)
    view = next(n for n in g.nodes if n.name == "InvoiceViewSet")
    assert view.extra.get("get_queryset") is True
    assert view.extra.get("filterset") == "InvoiceFilter"


def test_extracts_ninja_route():
    source = (FIXTURE / "backend/billing/api.py").read_text()
    g = extract_django_file("backend/billing/api.py", source, _cfg())
    assert any(n.type is NodeType.ROUTE and "ledger" in n.name for n in g.nodes)
    assert any(n.type is NodeType.VIEW and n.extra.get("ninja") for n in g.nodes)


def test_task_definition_file_survives_call_site_placeholder(tmp_path):
    from loadpath.index import index_repo

    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    ledger = next(n for n in store.nodes() if n["name"] == "rebuild_ledger")
    assert "actors.py" in (ledger.get("file_path") or "")
    assert not (ledger.get("extra") or {}).get("referenced")
    email = next(
        n
        for n in store.nodes()
        if n["name"] == "send_invoice_email" and (n.get("extra") or {}).get("looks_idempotent_on_pk")
    )
    assert "tasks.py" in (email.get("file_path") or "")
    store.close()


def test_extracts_management_command():
    rel = "backend/billing/management/commands/resend_invoices.py"
    source = (FIXTURE / rel).read_text()
    g = extract_django_file(rel, source, _cfg())
    assert any(n.type is NodeType.MANAGEMENT_COMMAND for n in g.nodes)


def test_on_commit_and_apply_async():
    source = (FIXTURE / "backend/billing/tasks.py").read_text()
    g = extract_django_file("backend/billing/tasks.py", source, _cfg())
    assert any("on_commit" in r for r in g.residuals)
    assert any(e.type.value == "enqueues" and "apply_async" in (e.extra.get("call") or "") for e in g.edges)


def test_foreignkey_string_ref():
    source = (FIXTURE / "backend/billing/models.py").read_text()
    g = extract_django_file("backend/billing/models.py", source, _cfg())
    assert any("string model ref" in r for r in g.residuals)
    account = next(n for n in g.nodes if n.name == "account")
    assert account.extra.get("on_delete") == "SET_NULL"


def test_extracts_service_and_admin_and_tests():
    cfg = _cfg()
    svc = extract_django_file(
        "backend/billing/services.py",
        (FIXTURE / "backend/billing/services.py").read_text(),
        cfg,
    )
    assert any(n.type is NodeType.SERVICE and n.name == "recalculate_total" for n in svc.nodes)
    admin = extract_django_file(
        "backend/billing/admin.py",
        (FIXTURE / "backend/billing/admin.py").read_text(),
        cfg,
    )
    assert any(n.type is NodeType.ADMIN for n in admin.nodes)
    tests = extract_django_file(
        "backend/billing/tests.py",
        (FIXTURE / "backend/billing/tests.py").read_text(),
        cfg,
    )
    assert any(n.type is NodeType.TEST for n in tests.nodes)
    assert any(e.type.value == "tested_by" for e in tests.edges)


def test_extracts_migration_ops():
    source = (FIXTURE / "backend/billing/migrations/0001_initial.py").read_text()
    g = extract_django_file("backend/billing/migrations/0001_initial.py", source, _cfg())
    assert any(n.type is NodeType.MIGRATION_OP and "CreateModel" in n.name for n in g.nodes)


def test_appconfig_ready_is_residual():
    source = (FIXTURE / "backend/billing/apps.py").read_text()
    g = extract_django_file("backend/billing/apps.py", source, _cfg())
    assert any("AppConfig.ready" in r for r in g.residuals)


def test_get_model_string_ref_is_residual():
    src = 'from django.apps import apps\nm = apps.get_model("billing.Invoice")\n'
    g = extract_django_file("backend/billing/dynamic.py", src, _cfg())
    assert any("get_model" in r for r in g.residuals)


def test_cross_app_model_import_on_view():
    src = """
from rest_framework.views import APIView
from accounts.models import UserProfile

class LeakView(APIView):
    def get(self, request):
        return UserProfile.objects.all()
"""
    g = extract_django_file("backend/billing/legacy.py", src, _cfg())
    assert any(e.extra.get("foreign_app") == "accounts" for e in g.edges)


def test_queryset_in_serializer_flagged():
    src = """
from rest_framework import serializers
from billing.models import Invoice

class BadSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        Invoice.objects.filter(total=attrs["total"])
        return attrs
    class Meta:
        model = Invoice
        fields = ["total"]
"""
    g = extract_django_file("backend/billing/serializers.py", src, _cfg())
    ser = next(n for n in g.nodes if n.type is NodeType.SERIALIZER)
    assert ser.extra.get("queryset_in_serializer") is True
