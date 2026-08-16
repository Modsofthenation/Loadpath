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


def test_extracts_next_app_router_page_and_server_action():
    page = extract_react_file(
        "frontend/src/app/invoices/[id]/page.tsx",
        (FIXTURE / "frontend/src/app/invoices/[id]/page.tsx").read_text(),
        _cfg(),
    )
    routes = [n for n in page.nodes if n.type is NodeType.REACT_ROUTE]
    assert any(n.name == "/invoices/{id}" for n in routes)
    assert any(n.type is NodeType.PAGE and (n.extra or {}).get("next_app") for n in page.nodes)
    actions = extract_react_file(
        "frontend/src/app/invoices/[id]/actions.ts",
        (FIXTURE / "frontend/src/app/invoices/[id]/actions.ts").read_text(),
        _cfg(),
    )
    assert any(n.type is NodeType.SERVER_ACTION and n.name == "saveInvoice" for n in actions.nodes)


def test_extracts_rtk_openapi_fetch_and_trpc_clients():
    rtk = extract_react_file(
        "frontend/src/features/billing/invoiceApi.ts",
        (FIXTURE / "frontend/src/features/billing/invoiceApi.ts").read_text(),
        _cfg(),
    )
    clients = [n for n in rtk.nodes if n.type is NodeType.API_CLIENT]
    assert any(c.name == "/api/invoices/{id}" and c.extra.get("typed_client") == "rtk" for c in clients)
    assert all(not c.extra.get("inferred") for c in clients)
    fetch = extract_react_file(
        "frontend/src/features/billing/openapiFetch.ts",
        (FIXTURE / "frontend/src/features/billing/openapiFetch.ts").read_text(),
        _cfg(),
    )
    assert any(
        c.type is NodeType.API_CLIENT and c.extra.get("typed_client") == "openapi-fetch"
        for c in fetch.nodes
    )
    trpc = extract_react_file(
        "frontend/src/features/billing/trpc.ts",
        (FIXTURE / "frontend/src/features/billing/trpc.ts").read_text(),
        _cfg(),
    )
    assert any(n.extra.get("typed_client") == "trpc" and n.name == "invoice.get" for n in trpc.nodes)


def test_extracts_playwright_e2e_visits():
    g = extract_react_file(
        "frontend/e2e/invoice.spec.ts",
        (FIXTURE / "frontend/e2e/invoice.spec.ts").read_text(),
        _cfg(),
    )
    tests = [n for n in g.nodes if n.type is NodeType.REACT_TEST]
    assert tests
    assert tests[0].extra.get("e2e") is True
    visits = tests[0].extra.get("visits") or []
    assert "/invoices/{id}" in visits
    assert "/api/invoices/{id}" in visits
    assert any(e.type.value == "tested_by" for e in g.edges)


def test_extracts_graphql_codegen_and_document():
    g = extract_react_file(
        "frontend/src/generated/graphql.ts",
        (FIXTURE / "frontend/src/generated/graphql.ts").read_text(),
        _cfg(),
    )
    schemas = [n for n in g.nodes if n.type is NodeType.FORM_SCHEMA]
    assert any(n.name == "InvoiceType" and n.extra.get("kind") == "graphql-codegen" for n in schemas)
    doc = extract_react_file(
        "frontend/src/features/billing/invoice.graphql",
        (FIXTURE / "frontend/src/features/billing/invoice.graphql").read_text(),
        _cfg(),
    )
    assert any(n.type is NodeType.GRAPHQL_OPERATION and n.name == "Invoice" and n.extra.get("client") for n in doc.nodes)


def test_extracts_ts_rest_path_contract():
    src = """
import { initContract } from '@ts-rest/core';
const c = initContract();
export const invoiceContract = c.router({
  getInvoice: {
    method: 'GET',
    path: '/api/invoices/:id',
    responses: { 200: c.type<Invoice>() },
  },
});
"""
    g = extract_react_file("frontend/src/features/billing/contract.ts", src, _cfg())
    clients = [n for n in g.nodes if n.type is NodeType.API_CLIENT]
    assert any(c.name == "/api/invoices/{id}" and c.extra.get("typed_client") == "ts-rest" for c in clients)


def test_rtk_ignores_http_method_literals():
    src = """
import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
export const invoiceApi = createApi({
  baseQuery: fetchBaseQuery({ baseUrl: "/api" }),
  endpoints: (builder) => ({
    save: builder.mutation({
      query: (body) => ({ method: "POST", url: "/invoices", body }),
    }),
  }),
});
"""
    g = extract_react_file("frontend/src/features/billing/invoiceApi.ts", src, _cfg())
    clients = [n for n in g.nodes if n.type is NodeType.API_CLIENT]
    assert any(c.name == "/api/invoices" for c in clients)
    assert not any("POST" in c.name for c in clients)


def test_does_not_treat_generic_post_as_openapi_fetch():
    src = """
export function save() {
  return api.POST("/api/invoices", { body: {} });
}
"""
    g = extract_react_file("frontend/src/features/billing/api.ts", src, _cfg())
    typed = [n for n in g.nodes if n.type is NodeType.API_CLIENT and n.extra.get("typed_client") == "openapi-fetch"]
    assert not typed


def test_does_not_treat_api_usequery_as_trpc():
    src = """
export function useBilling() {
  return api.billing.list.useQuery();
}
"""
    g = extract_react_file("frontend/src/features/billing/useBilling.ts", src, _cfg())
    assert not any(n.extra.get("typed_client") == "trpc" for n in g.nodes)


def test_ts_rest_ignores_react_router_paths():
    src = """
import { initContract } from '@ts-rest/core';
const c = initContract();
export const routes = [{ path: '/settings/profile', element: <Profile /> }];
"""
    g = extract_react_file("frontend/src/features/billing/contract.ts", src, _cfg())
    assert not any(n.extra.get("typed_client") == "ts-rest" for n in g.nodes)


def test_app_router_route_handler_is_not_a_page():
    src = """
export async function GET() {
  return Response.json({});
}
"""
    g = extract_react_file("frontend/src/app/api/invoices/route.ts", src, _cfg())
    assert not any(n.type is NodeType.PAGE for n in g.nodes)
    assert not any(n.name == "GET" for n in g.nodes)
    assert any(n.type is NodeType.API_CLIENT and n.extra.get("next_api") for n in g.nodes)


def test_server_action_arrow_export():
    src = """
"use server";
export const saveInvoice = async (formData: FormData) => {
  return String(formData.get("id") || "");
};
"""
    g = extract_react_file("frontend/src/app/invoices/[id]/actions.ts", src, _cfg())
    assert any(n.type is NodeType.SERVER_ACTION and n.name == "saveInvoice" for n in g.nodes)


def test_typename_alone_is_not_graphql_codegen():
    src = """
export type ButtonProps = { __typename?: string; label: string };
"""
    g = extract_react_file("frontend/src/components/Button.tsx", src, _cfg())
    assert not any(n.extra.get("kind") == "graphql-codegen" for n in g.nodes)

