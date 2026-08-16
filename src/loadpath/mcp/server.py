from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from pydantic import AnyHttpUrl
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings

from loadpath import __version__
from loadpath.mcp import tools
from loadpath.mcp.oauth import SCOPE, LoadpathOAuthProvider

INSTRUCTIONS = """Loadpath reviews Django + React pull requests as load-path inspection, not hunk comments.
A change is a force: index the repo, then review a git range until the force hits a sink (HTTP, UI, Celery/Dramatiq, migration).
Return confidence, sinks, suggested reviewers, and residual uncertainty. Do not dump the full graph unless asked.
Tokens and indexes stay on the machine running Loadpath."""


def public_base_url(host: str = "127.0.0.1", port: int = 7345, public_url: str | None = None) -> str:
    explicit = public_url or os.environ.get("LOADPATH_PUBLIC_URL")
    if explicit:
        return explicit.rstrip("/")
    bind = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    scheme = "http"
    return f"{scheme}://{bind}:{port}"


def resource_url(base: str) -> str:
    return f"{base.rstrip('/')}/mcp"


def _register_tools(mcp: MCPServer) -> None:
    mcp.tool(
        name="list_workspaces",
        description="List registered Loadpath workspaces and whether each is indexed.",
    )(tools.list_workspaces)
    mcp.tool(
        name="init_repo",
        description="Detect Django/React roots and draft loadpath.yml. Does not overwrite an existing file unless overwrite=true.",
    )(tools.init_repo)
    mcp.tool(
        name="index_repo",
        description="Build or refresh the architecture graph (SQLite) for a Django + React repo. Incremental by default.",
    )(tools.index_workspace)
    mcp.tool(
        name="architecture",
        description="Show indexed bounded contexts, rules, and findings. Does not include the full node graph.",
    )(tools.architecture)
    mcp.tool(
        name="review",
        description="Review a git range as a load path: confidence, sinks, reviewers, residuals. Not a hunk-comment bot. Prefer three-dot (merge-base) ranges for PRs.",
    )(tools.review_range)
    mcp.tool(
        name="detect_repo",
        description="Detect Django/React layout without writing loadpath.yml.",
    )(tools.detect_repo)
    mcp.tool(
        name="list_pull_requests",
        description="List GitHub, GitLab, or Bitbucket pull requests using tokens stored in Loadpath settings.",
    )(tools.list_pull_requests)
    mcp.tool(
        name="list_remote_repositories",
        description="List GitHub, GitLab, or Bitbucket repositories the signed-in account can access.",
    )(tools.list_remote_repositories)
    mcp.tool(
        name="post_review_comment",
        description="Upsert the single Loadpath markdown brief on a pull request (updated in place).",
    )(tools.post_review_comment)
    mcp.tool(
        name="what_if",
        description="Simulate a change from one indexed node and list sinks, auth, and suggested tests. No git range.",
    )(tools.what_if)
    mcp.tool(
        name="review_pull_request",
        description="Fetch a GitHub/GitLab/Bitbucket PR into a local clone and review the three-dot range.",
    )(tools.review_pull_request)
    mcp.tool(
        name="load_path_marks",
        description="Files on the current load path with roles for editor gutters: seed, untested sink, contract, tested.",
    )(tools.load_path_marks)
    mcp.tool(
        name="list_reviews",
        description="List stored Loadpath reviews for a workspace (confidence, sinks, contract) without the full graph.",
    )(tools.list_reviews)
    mcp.tool(
        name="save_config",
        description="Write loadpath.yml contexts, owners, rules, and waivers for a repo.",
    )(tools.save_config)


def create_mcp_server(
    *,
    http: bool = False,
    public_url: str | None = None,
    oauth_pin: str | None = None,
    auto_approve: bool | None = None,
) -> MCPServer:
    if not http:
        mcp = MCPServer(
            name="Loadpath",
            version=__version__,
            instructions=INSTRUCTIONS,
            website_url="https://github.com/Modsofthenation/PR-Reviewer",
        )
        _register_tools(mcp)
        return mcp

    base = public_url or public_base_url()
    resource = resource_url(base)
    auto = os.environ.get("LOADPATH_OAUTH_AUTO_APPROVE") == "1" if auto_approve is None else auto_approve
    provider = LoadpathOAuthProvider(
        issuer=base,
        resource=resource,
        pin=oauth_pin,
        auto_approve=auto,
    )
    mcp = MCPServer(
        name="Loadpath",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/Modsofthenation/PR-Reviewer",
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(base),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[SCOPE],
                default_scopes=[SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    _register_tools(mcp)

    @mcp.custom_route("/consent", methods=["GET", "POST"])
    async def consent(request: Request) -> Response:
        return await provider.handle_consent(request)

    mcp._loadpath_provider = provider  # type: ignore[attr-defined]
    return mcp


def mcp_transport_security(public_url: str | None = None) -> TransportSecuritySettings:
    """Allow loopback (and an optional tunnel origin). Reject other Host/Origin values."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver", "testclient"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    explicit = (public_url or os.environ.get("LOADPATH_PUBLIC_URL") or "").strip()
    if explicit:
        parsed = urlparse(explicit)
        host = (parsed.hostname or "").lower().strip("[]")
        if host and host not in {"127.0.0.1", "localhost", "::1"}:
            hosts.extend([host, f"{host}:*"])
            if parsed.scheme:
                origins.extend([f"{parsed.scheme}://{host}", f"{parsed.scheme}://{host}:*"])
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def mcp_host_allowed(host_header: str, public_url: str | None = None) -> bool:
    """True when Host is loopback, TestClient, or the optional tunnel hostname."""
    settings = mcp_transport_security(public_url)
    return TransportSecurityMiddleware(settings)._validate_host(host_header or "")


def build_mcp_http(mcp: MCPServer, public_url: str | None = None):
    """Create the Streamable HTTP Starlette app (initializes session_manager)."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=mcp_transport_security(public_url),
        host="0.0.0.0",
    )


def copy_mcp_routes(app: Any, mcp_http: Any) -> None:
    for route in mcp_http.routes:
        app.router.routes.append(route)


def add_mcp_auth_middleware(app: Any, mcp: MCPServer) -> None:
    verifier = mcp._token_verifier
    if verifier is None:
        return
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier))


def mcp_lifespan(mcp: MCPServer):
    @asynccontextmanager
    async def _lifespan(_app: Any) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    return _lifespan


async def run_stdio() -> None:
    mcp = create_mcp_server(http=False)
    await mcp.run_stdio_async()
