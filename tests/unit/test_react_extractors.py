from __future__ import annotations

from loadpath.config import load_config
from loadpath.extractors.react import extract_react_file, normalize_url_template
from loadpath.types import NodeType

from tests.conftest import FIXTURE_ROOT as FIXTURE


def _cfg():
    return load_config(FIXTURE)


def test_normalize_url_templates():
    assert normalize_url_template("/api/invoices/${id}") == "/api/invoices/{id}"
    assert normalize_url_template("`/api/invoices/${id}`".strip("`")) == "/api/invoices/{id}"


def test_extracts_react_routes_and_pages():
    source = (FIXTURE / "frontend/src/App.tsx").read_text()
    g = extract_react_file("frontend/src/App.tsx", source, _cfg())
    routes = [n for n in g.nodes if n.type is NodeType.REACT_ROUTE]
    assert any(n.name == "/invoices/:id" for n in routes)
    assert any(n.type is NodeType.PAGE and n.name == "InvoicePage" for n in g.nodes)


def test_extracts_hook_query_key_and_fetch_url():
    hook = extract_react_file(
        "frontend/src/features/billing/useInvoice.ts",
        (FIXTURE / "frontend/src/features/billing/useInvoice.ts").read_text(),
        _cfg(),
    )
    assert any(n.type is NodeType.HOOK and n.name == "useInvoice" for n in hook.nodes)
    assert any(n.type is NodeType.QUERY_KEY for n in hook.nodes)
    api = extract_react_file(
        "frontend/src/features/billing/api.ts",
        (FIXTURE / "frontend/src/features/billing/api.ts").read_text(),
        _cfg(),
    )
    clients = [n for n in api.nodes if n.type is NodeType.API_CLIENT]
    assert any(c.name == "/api/invoices/{id}" for c in clients)


def test_generated_client_is_not_inferred():
    g = extract_react_file(
        "frontend/src/generated/invoices.ts",
        (FIXTURE / "frontend/src/generated/invoices.ts").read_text(),
        _cfg(),
    )
    clients = [n for n in g.nodes if n.type is NodeType.API_CLIENT]
    assert clients
    assert all(c.extra.get("generated") for c in clients)
    assert all(not c.extra.get("inferred") for c in clients)


def test_extracts_zod_schema_fields():
    g = extract_react_file(
        "frontend/src/features/billing/invoiceSchema.ts",
        (FIXTURE / "frontend/src/features/billing/invoiceSchema.ts").read_text(),
        _cfg(),
    )
    schema = next(n for n in g.nodes if n.type is NodeType.FORM_SCHEMA)
    assert schema.name == "invoiceSchema"
    assert set(schema.extra["fields"]) >= {"customer_id", "total", "status"}


def test_extracts_page_renders_form():
    g = extract_react_file(
        "frontend/src/features/billing/InvoicePage.tsx",
        (FIXTURE / "frontend/src/features/billing/InvoicePage.tsx").read_text(),
        _cfg(),
    )
    assert any(n.type is NodeType.PAGE and n.name == "InvoicePage" for n in g.nodes)
    assert any(e.type.value == "renders" for e in g.edges)


def test_feature_context_from_path():
    cfg = _cfg()
    g = extract_react_file(
        "frontend/src/features/auth/MePage.tsx",
        (FIXTURE / "frontend/src/features/auth/MePage.tsx").read_text(),
        cfg,
    )
    pages = [n for n in g.nodes if n.type in {NodeType.PAGE, NodeType.HOOK}]
    assert any(n.context == "identity" for n in pages)


def test_form_default_values_and_missing_boundary():
    g = extract_react_file(
        "frontend/src/features/billing/InvoiceForm.tsx",
        (FIXTURE / "frontend/src/features/billing/InvoiceForm.tsx").read_text(),
        _cfg(),
    )
    form = next(n for n in g.nodes if n.name == "InvoiceForm")
    assert "total" in (form.extra.get("form_fields") or [])
    page = extract_react_file(
        "frontend/src/features/billing/InvoicePage.tsx",
        (FIXTURE / "frontend/src/features/billing/InvoicePage.tsx").read_text(),
        _cfg(),
    )
    invoice_page = next(n for n in page.nodes if n.name == "InvoicePage")
    assert invoice_page.extra.get("has_error_boundary") is False


def test_invalidate_queries_marked():
    src = """
export function useSaveInvoice() {
  return useMutation({
    mutationFn: save,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invoice", id] }),
  });
}
"""
    g = extract_react_file("frontend/src/features/billing/useSaveInvoice.ts", src, _cfg())
    keys = [n for n in g.nodes if n.type is NodeType.QUERY_KEY]
    assert keys
    assert any((n.extra or {}).get("invalidation") for n in keys)
    hook = next(n for n in g.nodes if n.name == "useSaveInvoice")
    assert hook.extra.get("mutation") is True
