from __future__ import annotations

from loadpath.config import load_config
from loadpath.extractors.django import extract_django_file
from loadpath.extractors.react import extract_react_file
from loadpath.extractors.templates import extract_template_file
from loadpath.index import index_repo
from loadpath.types import EdgeType, NodeType

from tests.conftest import FIXTURE_ROOT as FIXTURE


def _cfg():
    return load_config(FIXTURE)


def test_extracts_strawberry_and_graphene():
    source = (FIXTURE / "backend/billing/schema.py").read_text()
    g = extract_django_file("backend/billing/schema.py", source, _cfg())
    types = {n.name: n for n in g.nodes if n.type is NodeType.GRAPHQL_TYPE}
    assert "InvoiceType" in types
    assert "Query" in types
    assert "CreditInvoice" in types
    ops = {n.name for n in g.nodes if n.type is NodeType.GRAPHQL_OPERATION}
    assert "invoice" in ops
    assert "credit_invoice" in ops
    assert any(n.type is NodeType.GRAPHQL_FIELD and n.name == "total" for n in g.nodes)
    assert any(e.type is EdgeType.PUBLISHES_GRAPHQL for e in g.edges)
    assert any(e.type is EdgeType.QUERIES_MODEL and "Invoice" in e.dst for e in g.edges)


def test_extracts_channels_consumer_and_websocket_route():
    consumer = extract_django_file(
        "backend/billing/consumers.py",
        (FIXTURE / "backend/billing/consumers.py").read_text(),
        _cfg(),
    )
    assert any(n.type is NodeType.CONSUMER and n.name == "InvoiceConsumer" for n in consumer.nodes)
    routing = extract_django_file(
        "backend/billing/routing.py",
        (FIXTURE / "backend/billing/routing.py").read_text(),
        _cfg(),
    )
    ws = [n for n in routing.nodes if n.type is NodeType.WEBSOCKET_ROUTE]
    assert ws
    assert any("ws/invoices" in n.name for n in ws)
    assert any(e.type is EdgeType.PUBLISHES_ROUTE and "InvoiceConsumer" in e.dst for e in routing.edges)


def test_extracts_fastapi_next_to_django_not_ninja():
    gateway = extract_django_file(
        "backend/billing/gateway.py",
        (FIXTURE / "backend/billing/gateway.py").read_text(),
        _cfg(),
    )
    assert any(n.type is NodeType.FASTAPI_ROUTE and "/internal/invoices" in n.name for n in gateway.nodes)
    assert any(n.type is NodeType.PYDANTIC_MODEL and n.name == "InvoiceOut" for n in gateway.nodes)
    assert any(e.type is EdgeType.USES_SERIALIZER for e in gateway.edges)
    ninja = extract_django_file(
        "backend/billing/api.py",
        (FIXTURE / "backend/billing/api.py").read_text(),
        _cfg(),
    )
    assert not any(n.type is NodeType.FASTAPI_ROUTE for n in ninja.nodes)
    assert any(n.type is NodeType.ROUTE and n.extra.get("ninja") for n in ninja.nodes)


def test_extracts_templates_htmx_and_url_tags():
    rel = "backend/billing/templates/billing/invoice_board.html"
    g = extract_template_file(rel, (FIXTURE / rel).read_text(), _cfg())
    templates = [n for n in g.nodes if n.type is NodeType.TEMPLATE]
    assert templates[0].qualified_name == "billing/invoice_board.html"
    assert any(n.type is NodeType.HTMX_CALL and "/api/invoices/totals/" in n.name for n in g.nodes)
    assert any(e.type is EdgeType.HTMX_CALLS for e in g.edges)
    assert any(e.extra.get("url_name") == "invoice-board" for e in g.edges)


def test_view_serves_template_and_cache_flag_on_commit():
    source = (FIXTURE / "backend/billing/views.py").read_text()
    g = extract_django_file("backend/billing/views.py", source, _cfg())
    assert any(n.type is NodeType.TEMPLATE and n.qualified_name == "billing/invoice_board.html" for n in g.nodes)
    assert any(e.type is EdgeType.SERVES_TEMPLATE for e in g.edges)
    assert any(n.type is NodeType.CACHE_KEY and n.name == "invoice:list" for n in g.nodes)
    assert any(n.type is NodeType.FEATURE_FLAG and n.name == "async_ledger" for n in g.nodes)
    assert any(n.type is NodeType.SIDE_EFFECT for n in g.nodes)
    assert any(e.type is EdgeType.ON_COMMIT for e in g.edges)
    assert any(e.type is EdgeType.INVALIDATES_CACHE for e in g.edges)
    assert any(e.type is EdgeType.CHECKS_FLAG for e in g.edges)


def test_react_gql_document_is_a_client_operation():
    source = (FIXTURE / "frontend/src/features/billing/InvoicePage.tsx").read_text()
    g = extract_react_file("frontend/src/features/billing/InvoicePage.tsx", source, _cfg())
    ops = [n for n in g.nodes if n.type is NodeType.GRAPHQL_OPERATION]
    assert any(n.name == "Invoice" and n.extra.get("client") for n in ops)
    assert any("invoice" in (n.extra.get("selections") or []) for n in ops)


def test_index_stitches_graphql_htmx_and_fastapi(tmp_path):
    store = index_repo(FIXTURE, db_path=tmp_path / "g.sqlite3", incremental=False)
    types = store.type_counts()
    assert types.get("graphql.operation", 0) >= 2
    assert types.get("fastapi.route", 0) >= 1
    assert types.get("django.template", 0) >= 1
    assert types.get("django.consumer", 0) >= 1
    gql_edges = [
        e
        for e in store.edges()
        if e["type"] == "consumed_by_client" and (e.get("extra") or {}).get("via") == "graphql"
    ]
    assert gql_edges, "client Invoice query should stitch to server invoice field"
    htmx_edges = [
        e for e in store.edges() if e["type"] == "consumed_by_client" and (e.get("extra") or {}).get("htmx")
    ]
    assert htmx_edges, "HTMX totals call should stitch to the Django totals route"
    fastapi = next(n for n in store.nodes() if n["type"] == "fastapi.route")
    openapi = [
        e
        for e in store.edges()
        if e["src"] == fastapi["id"] and e["type"] == "publishes_route" and "openapi" in (e.get("extra") or {}).get("via", "")
    ]
    assert openapi, "FastAPI /internal/invoices/{id} should stitch to OpenAPI"
    store.close()
