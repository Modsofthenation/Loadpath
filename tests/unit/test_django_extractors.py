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
    total = names["billing.Invoice.total"].extra
    assert total.get("max_digits") == 10
    assert total.get("decimal_places") == 2
    status = names["billing.Invoice.status"].extra
    assert status.get("max_length") == 32
    assert status.get("default") == "draft"
    account = names["billing.Invoice.account"].extra
    assert account.get("null") is True


def test_extracts_model_docstring_and_null_false():
    source = (
        "from django.db import models\n"
        "class Ledger(models.Model):\n"
        "    \"\"\"Posted billing ledger.\\n\\nLonger body.\"\"\"\n"
        "    ref = models.CharField(max_length=16, null=False, blank=True)\n"
        "    owner = models.ForeignKey('auth.User', null=True, default=None, on_delete=models.SET_NULL)\n"
        "    status = models.CharField(max_length=8, default='open')\n"
    )
    g = extract_django_file("backend/billing/models.py", source, _cfg())
    ledger = next(n for n in g.nodes if n.name == "Ledger")
    assert ledger.extra.get("doc") == "Posted billing ledger."
    ref = next(n for n in g.nodes if n.name == "ref")
    assert ref.extra.get("null") is False
    assert ref.extra.get("blank") is True
    assert ref.extra.get("max_length") == 16
    owner = next(n for n in g.nodes if n.name == "owner")
    assert owner.extra.get("null") is True
    assert "default" not in owner.extra
    status = next(n for n in g.nodes if n.name == "status")
    assert status.extra.get("default") == "open"


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
    assert all(n.name for n in routes)


def test_empty_include_route_gets_a_readable_name():
    source = (
        "from django.urls import include, path\n"
        "urlpatterns = [\n"
        "    path('', include('custom_auth.mfa.urls')),\n"
        "    path('', include(ffadmin_user_router.urls)),\n"
        "    path('', InvoiceView.as_view(), name='index'),\n"
        "]\n"
    )
    g = extract_django_file("api/custom_auth/urls.py", source, _cfg())
    routes = [n for n in g.nodes if n.type is NodeType.ROUTE]
    names = {n.name for n in routes}
    assert "include:custom_auth.mfa.urls" in names
    assert "include:ffadmin_user_router.urls" in names
    assert "index" in names
    assert all(n.name for n in routes)
    ids = [n.id for n in routes]
    assert len(ids) == len(set(ids))
    assert len(routes) == 3


def test_empty_named_routes_keep_unique_ids():
    source = (
        "from django.urls import path\n"
        "urlpatterns = [\n"
        "    path('', Home.as_view(), name='index'),\n"
        "    path('', Other.as_view(), name='index'),\n"
        "]\n"
    )
    g = extract_django_file("api/custom_auth/urls.py", source, _cfg())
    routes = [n for n in g.nodes if n.type is NodeType.ROUTE]
    assert {n.name for n in routes} == {"index"}
    assert len(routes) == 2
    assert len({n.id for n in routes}) == 2


def test_module_prefixed_view_links_to_app_view_node():
    source = (
        "from django.urls import re_path\n"
        "from . import views\n"
        "urlpatterns = [\n"
        "    re_path(r'^add-leader$', views.add_leader, name='groups.add_leader'),\n"
        "]\n"
    )
    g = extract_django_file("kitsune/groups/urls.py", source, _cfg())
    edges = [e for e in g.edges if e.type.value == "publishes_route"]
    assert edges
    assert any(e.dst == "django.view:groups.add_leader" for e in edges)


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


def test_extracts_ninja_and_fastapi_docstrings():
    ninja = extract_django_file(
        "backend/billing/api.py",
        "from ninja import Router\napi = Router()\n"
        "@api.get('/ledger')\n"
        "def ledger():\n"
        "    \"\"\"Posted ledger totals.\"\"\"\n"
        "    return {}\n",
        _cfg(),
    )
    view = next(n for n in ninja.nodes if n.type is NodeType.VIEW and n.extra.get("ninja"))
    assert view.extra.get("doc") == "Posted ledger totals."
    fastapi = extract_django_file(
        "backend/billing/gateway.py",
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/internal/invoices')\n"
        "def get_invoice():\n"
        "    \"\"\"Internal invoice payload.\"\"\"\n"
        "    return {}\n",
        _cfg(),
    )
    view = next(n for n in fastapi.nodes if n.extra.get("fastapi") and n.type is NodeType.VIEW)
    assert view.extra.get("doc") == "Internal invoice payload."


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


def test_enqueue_resolves_foreign_app_task():
    src = """
from rest_framework.viewsets import ModelViewSet
from accounts.tasks import notify_user

class InvoiceViewSet(ModelViewSet):
    def create(self, request):
        notify_user.delay(1)
"""
    g = extract_django_file("backend/billing/views.py", src, _cfg())
    edges = [e for e in g.edges if e.type.value == "enqueues"]
    assert edges
    assert any(e.dst == "django.task:accounts.notify_user" for e in edges)


def test_discover_settings_uses_django_root():
    from loadpath.extractors.django_boot import _discover_settings_module

    assert _discover_settings_module(FIXTURE, "backend") == "config.settings"


def test_live_field_constraints_copy_null_and_max_length():
    from types import SimpleNamespace

    from loadpath.extractors.django_boot import _live_field_constraints

    extra = _live_field_constraints(
        SimpleNamespace(
            null=True,
            blank=False,
            max_length=32,
            primary_key=False,
            max_digits=None,
            auto_now_add=True,
        )
    )
    assert extra["null"] is True
    assert extra["blank"] is False
    assert extra["max_length"] == 32
    assert extra["auto_now_add"] is True
    assert "primary_key" not in extra
    assert "max_digits" not in extra


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


def test_nplusone_related_access_in_loop():
    src = """
from billing.models import Invoice

def overdue_account_emails():
    names = []
    for invoice in Invoice.objects.filter(status="open"):
        names.append(invoice.account.email)
    return names
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    hits = svc.extra.get("nplusone") or []
    assert hits
    assert hits[0]["kind"] == "select_related"
    assert "account" in hits[0]["accessed"]
    assert "select_related" in hits[0]["suggested_fix"]


def test_nplusone_silent_when_select_related():
    src = """
from billing.models import Invoice

def overdue_account_emails():
    names = []
    for invoice in Invoice.objects.filter(status="open").select_related("account"):
        names.append(invoice.account.email)
    return names
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    assert not svc.extra.get("nplusone")


def test_nplusone_ignores_non_queryset_and_private_attrs():
    src = """
def walk_cache():
    for invoice in fetch_all():
        print(invoice.account.email)
        print(invoice._state.db)
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "walk_cache")
    assert not svc.extra.get("nplusone")


def test_nplusone_uses_binding_before_loop_only():
    src = """
from billing.models import Invoice

def overdue_account_emails():
    for invoice in qs:
        names = invoice.account.email
    qs = Invoice.objects.filter(status="open")
    return names
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    assert not svc.extra.get("nplusone")


def test_nplusone_select_related_none_clears_cover():
    src = """
from billing.models import Invoice

def overdue_account_emails():
    names = []
    for invoice in Invoice.objects.select_related("account").select_related(None):
        names.append(invoice.account.email)
    return names
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    assert svc.extra.get("nplusone")


def test_nplusone_one_hop_helper_return():
    src = """
from billing.models import Invoice

def recent():
    return Invoice.objects.filter(status="open")

def overdue_account_emails():
    names = []
    for invoice in recent():
        names.append(invoice.account.email)
    return names
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    assert svc.extra.get("nplusone")
    assert "account" in svc.extra["nplusone"][0]["accessed"]


def test_nplusone_prefetch_object_covers_related():
    src = """
from django.db.models import Prefetch
from billing.models import Invoice

def overdue_account_emails():
    names = []
    for invoice in Invoice.objects.prefetch_related(Prefetch("lines")):
        names.append(list(invoice.lines.all()))
    return names
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    assert not svc.extra.get("nplusone")


def test_lookups_recorded_on_service():
    src = """
from billing.models import Invoice

def overdue_account_emails():
    return Invoice.objects.filter(status="open").order_by("created_at")
"""
    g = extract_django_file("backend/billing/services.py", src, _cfg())
    svc = next(n for n in g.nodes if n.name == "overdue_account_emails")
    kinds = {h["kind"] for h in svc.extra.get("lookups") or []}
    assert "filter" in kinds
    assert "order_by" in kinds


def test_pytest_mentions_serializer_field():
    source = (FIXTURE / "backend/billing/tests.py").read_text()
    g = extract_django_file("backend/billing/tests.py", source, _cfg())
    test = next(n for n in g.nodes if n.name == "test_serializer_includes_total")
    assert "total" in (test.extra.get("mentions") or [])


def test_throttles_are_nodes():
    src = """
from rest_framework.viewsets import ModelViewSet
from rest_framework.throttling import UserRateThrottle

class InvoiceViewSet(ModelViewSet):
    throttle_classes = [UserRateThrottle]
    serializer_class = object
"""
    g = extract_django_file("backend/billing/views.py", src, _cfg())
    assert any(n.type is NodeType.THROTTLE and n.name == "UserRateThrottle" for n in g.nodes)


def test_extracts_django_modelform_and_links_model():
    src = """
from django import forms
from billing.models import Invoice

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["total", "status"]
"""
    g = extract_django_file("backend/billing/forms.py", src, _cfg())
    forms_found = [n for n in g.nodes if n.type is NodeType.FORM]
    assert any(n.name == "InvoiceForm" for n in forms_found)
    assert any(e.type.value == "serializes" for e in g.edges)
    assert any(e.type.value == "has_field" for e in g.edges)


def test_extracts_signal_connect_and_plain_handlers():
    apps = """
from django.apps import AppConfig
from wagtail.signals import page_slug_changed
from .signal_handlers import autocreate_redirects_on_slug_change

class RedirectsAppConfig(AppConfig):
    def ready(self):
        page_slug_changed.connect(autocreate_redirects_on_slug_change)
"""
    handlers = """
def should_skip(page):
    return not page.live

def autocreate_redirects_on_slug_change(instance_before, instance, **kwargs):
    return None
"""
    connected = extract_django_file("wagtail/contrib/redirects/apps.py", apps, _cfg())
    assert any(n.type is NodeType.RECEIVER and n.name == "autocreate_redirects_on_slug_change" for n in connected.nodes)
    assert any(e.type.value == "receives" for e in connected.edges)
    plain = extract_django_file("wagtail/contrib/redirects/signal_handlers.py", handlers, _cfg())
    names = {n.name for n in plain.nodes if n.type is NodeType.RECEIVER}
    assert "autocreate_redirects_on_slug_change" in names
    assert "should_skip" not in names


def test_testcase_named_form_is_not_a_form():
    src = """
from django.test import TestCase
from kitsune.questions.forms import NewQuestionForm

class TestNewQuestionForm(TestCase):
    def test_ok(self):
        NewQuestionForm()
"""
    g = extract_django_file("kitsune/questions/tests/test_forms.py", src, _cfg())
    assert not any(n.type is NodeType.FORM for n in g.nodes)
    assert any(n.type is NodeType.TEST and n.name == "test_ok" for n in g.nodes)
    tests = [n for n in g.nodes if n.type is NodeType.TEST]
    assert tests[0].qualified_name.startswith("questions.")


def test_views_package_uses_django_app_not_views_namespace():
    from loadpath.extractors.django import _app_from_path

    assert _app_from_path("src/pretix/control/views/vouchers.py") == "control"
    assert _app_from_path("src/pretix/presale/views/widget.py") == "presale"
    assert _app_from_path("wger/nutrition/tests/test_search_api.py") == "nutrition"
    assert _app_from_path("wger/nutrition/api/views.py") == "nutrition"
    assert _app_from_path("wger/nutrition/api/filtersets.py") == "nutrition"
    assert _app_from_path("shop/api/viewsets/order.py") == "shop"
    assert _app_from_path("api/views.py") == "api"
    assert _app_from_path("backend/billing/views.py") == "billing"
    assert _app_from_path("backend/billing/migrations/0001_initial.py") == "billing"

    source = (
        "from django.views import View\n"
        "class CartApplyVoucher(View):\n"
        "    pass\n"
    )
    control = extract_django_file("src/pretix/control/views/vouchers.py", source, _cfg())
    presale = extract_django_file("src/pretix/presale/views/widget.py", source, _cfg())
    ids = {n.id for n in control.nodes + presale.nodes if n.type is NodeType.VIEW}
    assert ids == {"django.view:control.CartApplyVoucher", "django.view:presale.CartApplyVoucher"}


def test_regex_empty_and_named_group_routes_are_readable():
    source = (
        "from django.urls import re_path, include\n"
        "from . import views\n"
        "urlpatterns = [\n"
        "    re_path(r'^$', views.home, name='home'),\n"
        "    re_path(r'^', include('addons.urls')),\n"
        "    re_path(r'^(?P<slug>[\\w-]+)/clone/$', views.clone, name='clone'),\n"
        "]\n"
    )
    g = extract_django_file("experimenter/nimbus_ui/urls.py", source, _cfg())
    routes = [n for n in g.nodes if n.type is NodeType.ROUTE]
    names = {n.name for n in routes}
    assert "home" in names or "/" in names
    assert "^$" not in names
    assert "^" not in names
    assert any("{slug}/clone/" == n.name or n.name == "{slug}/clone" for n in routes)
    assert any(e.dst == "django.view:nimbus_ui.clone" for e in g.edges if e.type.value == "publishes_route")

    nested = extract_django_file(
        "shop/urls.py",
        (
            "from django.urls import re_path\n"
            "from . import views\n"
            "urlpatterns = [\n"
            "    re_path(r'^(?P<slug>(?:[\\w-]+))/$', views.item, name='item'),\n"
            "]\n"
        ),
        _cfg(),
    )
    nested_names = {n.name for n in nested.nodes if n.type is NodeType.ROUTE}
    assert "{slug}/" in nested_names or "{slug}" in nested_names
    assert not any(")" in name for name in nested_names)


def test_pretty_url_pattern_nested_named_groups():
    from loadpath.extractors.django import pretty_url_pattern

    assert pretty_url_pattern(r"^(?P<slug>(?:[\w-]+))/$") in {"{slug}/", "{slug}"}
    assert ")" not in pretty_url_pattern(r"^(?P<slug>(?:[\w-]+))/$")
    assert pretty_url_pattern(r"^$") in {"", "/"}
    assert pretty_url_pattern(r"^") == ""


def test_filterset_is_a_form_and_links_from_the_view():
    filters = (
        "from django_filters import FilterSet\n"
        "from .models import Ingredient\n"
        "class IngredientFilterSet(FilterSet):\n"
        "    class Meta:\n"
        "        model = Ingredient\n"
        "        fields = ['name']\n"
    )
    views = (
        "from rest_framework.viewsets import ModelViewSet\n"
        "from .filtersets import IngredientFilterSet\n"
        "from .serializers import IngredientSerializer\n"
        "from .models import Ingredient\n"
        "class IngredientViewSet(ModelViewSet):\n"
        "    serializer_class = IngredientSerializer\n"
        "    filterset_class = IngredientFilterSet\n"
        "    queryset = Ingredient.objects.all()\n"
    )
    fg = extract_django_file("wger/nutrition/api/filtersets.py", filters, _cfg())
    vg = extract_django_file("wger/nutrition/api/views.py", views, _cfg())
    fs = next(n for n in fg.nodes if n.name == "IngredientFilterSet")
    assert fs.type is NodeType.FORM
    assert fs.extra.get("filterset") is True
    assert fs.qualified_name == "nutrition.IngredientFilterSet"
    assert any(e.src == fs.id and e.type.value == "serializes" for e in fg.edges)
    assert any(
        e.src == "django.view:nutrition.IngredientViewSet" and e.dst == "django.form:nutrition.IngredientFilterSet"
        for e in vg.edges
    )

