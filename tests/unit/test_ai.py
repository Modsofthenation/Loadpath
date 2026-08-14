from __future__ import annotations

import json

from loadpath.ai.providers import OpenAICompatible, residual_prompt


def test_openai_compatible_completion():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Signal update_ledger still formats total."}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ai = OpenAICompatible("sk-test", "grok-3", base_url="https://api.x.ai/v1", client=client)
    note = ai.complete("residuals: update_ledger")
    assert "update_ledger" in note


def test_residual_prompt_includes_graph():
    prompt = residual_prompt(
        {
            "title": "Invoice.total",
            "confidence": {"level": "medium"},
            "change_kinds": ["public_contract"],
            "residuals": ["inferred client /api/invoices/{id}"],
            "findings": [],
            "nodes": [{"type": "django.serializer", "qualified_name": "billing.InvoiceSerializer", "file_path": "s.py"}],
        }
    )
    assert "Invoice.total" in prompt
    assert "inferred client" in prompt
