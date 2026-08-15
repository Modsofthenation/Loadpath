from __future__ import annotations

from typing import Protocol

import httpx

RESIDUAL_SYSTEM = """You are Loadpath's residual-uncertainty analyst.
You do NOT comment on every hunk. You only inspect dynamic/inferred coupling
the deterministic graph could not close: getattr, raw SQL, get_serializer_class,
AppConfig.ready() signal registration, string model refs, inferred URL stitches.
Use these terms exactly: module, interface, depth, seam, adapter, leverage, locality.
A module is deep when a lot of behaviour sits behind a small interface.
The deletion test: if deleting a module just moves complexity, it was a pass-through.
The interface is the test surface — tests should not poke past it.
Do not say component, API, or boundary when you mean module, interface, or seam.
Return a short markdown note: what might still be coupled, how sure you are, and
what a reviewer should verify. No style nits. No generic praise.
"""


class CompletionClient(Protocol):
    name: str

    def complete(self, prompt: str, system: str = RESIDUAL_SYSTEM) -> str: ...


class OpenAICompatible:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=60.0)

    def complete(self, prompt: str, system: str = RESIDUAL_SYSTEM) -> str:
        r = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


class AnthropicClient:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=60.0)

    def complete(self, prompt: str, system: str = RESIDUAL_SYSTEM) -> str:
        r = self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 800,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()
        parts = data.get("content") or []
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


PROVIDERS = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "grok": ("https://api.x.ai/v1", "grok-3"),
    "xai": ("https://api.x.ai/v1", "grok-3"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "cursor": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "ollama": ("http://127.0.0.1:11434/v1", "llama3.1"),
}


def client_for(provider: str, api_key: str, model: str = "", base_url: str = "") -> CompletionClient:
    name = provider.lower().strip()
    if name in {"none", "", "off"}:
        raise ValueError("No AI provider configured")
    if name == "anthropic":
        return AnthropicClient(api_key, model=model or "claude-sonnet-4-20250514")
    url, default_model = PROVIDERS.get(name, (base_url or "https://api.openai.com/v1", "gpt-4.1-mini"))
    return OpenAICompatible(api_key, model=model or default_model, base_url=base_url or url)


def residual_prompt(review: dict) -> str:
    residuals = review.get("residuals") or []
    findings = [f for f in review.get("findings") or [] if not f.get("waived")]
    path = []
    for n in review.get("nodes") or []:
        path.append(f"- {n.get('type')} {n.get('qualified_name')} ({n.get('file_path')})")
    return (
        f"Change: {review.get('title')}\n"
        f"Confidence: {review.get('confidence', {}).get('level')}\n"
        f"Kinds: {review.get('change_kinds')}\n\n"
        f"Residuals:\n" + "\n".join(f"- {r}" for r in residuals) + "\n\n"
        f"Architecture findings:\n"
        + "\n".join(f"- {f.get('rule')}: {f.get('message')}" for f in findings)
        + "\n\nDeepening opportunities:\n"
        + "\n".join(
            f"- {c.get('strength')}: {c.get('title')} — {c.get('message')}"
            for c in (review.get("deepening") or [])[:6]
        )
        + "\n\nImpact nodes:\n"
        + "\n".join(path[:80])
    )
