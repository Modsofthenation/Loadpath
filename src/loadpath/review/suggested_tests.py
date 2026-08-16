"""Turn untested seams into pytest / RTL / GraphQL / HTMX sketches."""

from __future__ import annotations

from loadpath.stitch.openapi import published_route
from loadpath.types import NodeType


def suggested_tests(untested_sinks: list[dict], impact_nodes: list[dict]) -> list[dict]:
    by_id = {n["id"]: n for n in impact_nodes}
    out: list[dict] = []
    seen: set[str] = set()
    for sink in untested_sinks:
        node = by_id.get(sink.get("id") or "") or sink
        ntype = node.get("type") or ""
        name = node.get("name") or sink.get("name") or "sink"
        key = f"{ntype}:{name}"
        if key in seen:
            continue
        seen.add(key)
        sketch = _sketch(ntype, name, node)
        if not sketch:
            continue
        out.append(sketch)
    return out[:8]


def _sketch(ntype: str, name: str, node: dict) -> dict | None:
    extra = node.get("extra") or {}
    file_path = node.get("file_path") or ""
    if ntype == NodeType.ROUTE.value:
        route = published_route(node) if "extra" in node or "name" in node else name
        method = (extra.get("method") or "GET").upper()
        call = "get" if method in {"GET", "HEAD"} else method.lower()
        return {
            "sink": name,
            "type": ntype,
            "kind": "pytest",
            "title": f"Hit {route} through the published route",
            "body": (
                f"def test_{_ident(name)}_via_route(client):\n"
                f"    response = client.{call}({route!r})\n"
                f"    assert response.status_code in {{200, 201, 204}}\n"
            ),
        }
    if ntype == NodeType.FASTAPI_ROUTE.value:
        route = extra.get("route") or name
        method = (extra.get("method") or "GET").lower()
        return {
            "sink": name,
            "type": ntype,
            "kind": "pytest",
            "title": f"Hit FastAPI {name}",
            "body": (
                f"def test_{_ident(name)}_fastapi(client):\n"
                f"    response = client.{method}({route!r})\n"
                f"    assert response.status_code < 500\n"
            ),
        }
    if ntype == NodeType.PAGE.value and ((node.get("extra") or {}).get("next_app") or (node.get("extra") or {}).get("route")):
        route = (node.get("extra") or {}).get("route") or name
        return {
            "sink": name,
            "type": ntype,
            "kind": "playwright",
            "title": f"Hit {route} through the App Router page",
            "body": (
                f"test('{name} load path', async ({{ page }}) => {{\n"
                f"  await page.goto({route!r})\n"
                f"  await expect(page.getByRole('heading')).toBeVisible()\n"
                f"}})\n"
            ),
        }
    if ntype in {NodeType.PAGE.value, NodeType.FORM_SCHEMA.value}:
        component = name if ntype == NodeType.PAGE.value else name.replace("Schema", "Form")
        return {
            "sink": name,
            "type": ntype,
            "kind": "rtl",
            "title": f"Render {component} at the page seam",
            "body": (
                f"import {{ render, screen }} from '@testing-library/react'\n"
                f"import {{ {component} }} from './{component}'\n\n"
                f"it('renders {component}', () => {{\n"
                f"  render(<{component} />)\n"
                f"  expect(screen.getByRole('form', {{ hidden: true }}) || document.body).toBeTruthy()\n"
                f"}})\n"
            ),
        }
    if ntype == NodeType.GRAPHQL_OPERATION.value:
        kind = extra.get("kind") or "query"
        return {
            "sink": name,
            "type": ntype,
            "kind": "graphql",
            "title": f"Exercise GraphQL {kind} {name}",
            "body": (
                f"def test_{_ident(name)}_graphql(client):\n"
                f"    response = client.post('/graphql', {{'query': '{kind} {{ {name} {{ __typename }} }}'}})\n"
                f"    assert response.status_code == 200\n"
                f"    assert 'errors' not in response.json()\n"
            ),
        }
    if ntype in {NodeType.CONSUMER.value, NodeType.WEBSOCKET_ROUTE.value}:
        return {
            "sink": name,
            "type": ntype,
            "kind": "channels",
            "title": f"Connect to {name}",
            "body": (
                f"async def test_{_ident(name)}_ws(communicator):\n"
                f"    connected, _ = await communicator.connect()\n"
                f"    assert connected\n"
                f"    await communicator.disconnect()\n"
            ),
        }
    if ntype == NodeType.TEMPLATE.value:
        return {
            "sink": name,
            "type": ntype,
            "kind": "django",
            "title": f"Render template {name}",
            "body": (
                f"def test_{_ident(name)}_template(client):\n"
                f"    response = client.get('/')  # route that serves {file_path or name}\n"
                f"    assert response.status_code == 200\n"
            ),
        }
    if ntype == NodeType.CACHE_KEY.value:
        return {
            "sink": name,
            "type": ntype,
            "kind": "pytest",
            "title": f"Assert cache key {name} after the write",
            "body": (
                f"def test_{_ident(name)}_cache(client):\n"
                f"    # exercise the view that writes `{name}`\n"
                f"    client.get('/')\n"
                f"    assert cache.get({name!r}) is not None\n"
            ),
        }
    if ntype == NodeType.FEATURE_FLAG.value:
        return {
            "sink": name,
            "type": ntype,
            "kind": "pytest",
            "title": f"Both sides of flag {name}",
            "body": (
                f"@pytest.mark.parametrize('on', [True, False])\n"
                f"def test_{_ident(name)}_flag(client, on, monkeypatch):\n"
                f"    monkeypatch.setattr('waffle.flag_is_active', lambda *a, **k: on)\n"
                f"    response = client.get('/')\n"
                f"    assert response.status_code < 500\n"
            ),
        }
    if ntype == NodeType.SIDE_EFFECT.value:
        return {
            "sink": name,
            "type": ntype,
            "kind": "pytest",
            "title": f"on_commit side effect from {name}",
            "body": (
                f"def test_{_ident(name)}_on_commit(django_capture_on_commit_callbacks):\n"
                f"    with django_capture_on_commit_callbacks(execute=True):\n"
                f"        ...  # the write that schedules {name}\n"
            ),
        }
    if ntype == NodeType.TASK.value:
        return {
            "sink": name,
            "type": ntype,
            "kind": "pytest",
            "title": f"Call task {name} with a pk",
            "body": (
                f"def test_{_ident(name)}_task():\n"
                f"    {name}(1)  # pass a model pk, not a deserialized object\n"
            ),
        }
    if ntype == NodeType.SERVER_ACTION.value:
        return {
            "sink": name,
            "type": ntype,
            "kind": "playwright",
            "title": f"Submit server action {name}",
            "body": (
                f"test('{name} server action', async ({{ page }}) => {{\n"
                f"  await page.goto('/')\n"
                f"  await page.getByRole('button').click()\n"
                f"  await expect(page.getByRole('alert')).not.toBeVisible()\n"
                f"}})\n"
            ),
        }
    return None


def _ident(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name)
    return cleaned.strip("_").lower() or "sink"
