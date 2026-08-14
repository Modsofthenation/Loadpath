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
    tasks = [n for n in g.nodes if n.type is NodeType.TASK]
    assert tasks[0].name == "send_invoice_email"
    assert tasks[0].extra["looks_idempotent_on_pk"] is True


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
