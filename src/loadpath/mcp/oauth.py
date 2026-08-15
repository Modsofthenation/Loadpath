from __future__ import annotations

import json
import os
import secrets
import threading
import time
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SCOPE = "loadpath"
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
CODE_TTL = 300


def oauth_store_path() -> Path:
    return Path.home() / ".loadpath" / "oauth.json"


def _now() -> float:
    return time.time()


class LoadpathOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """In-process OAuth 2.1 AS: DCR, PKCE, CIMD, consent. Tokens stay on this machine."""

    def __init__(
        self,
        issuer: str,
        resource: str,
        *,
        pin: str | None = None,
        auto_approve: bool = False,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.resource = resource.rstrip("/")
        self.pin = pin or os.environ.get("LOADPATH_OAUTH_PIN") or ""
        self.auto_approve = auto_approve or os.environ.get("LOADPATH_OAUTH_AUTO_APPROVE") == "1"
        self._lock = threading.RLock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        path = oauth_store_path()
        if not path.is_file():
            return {"clients": {}, "access": {}, "refresh": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"clients": {}, "access": {}, "refresh": {}}

    def _save(self) -> None:
        path = oauth_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._lock:
            raw = (self._data.get("clients") or {}).get(client_id)
        if raw:
            return OAuthClientInformationFull.model_validate(raw)
        if client_id.startswith("https://") or client_id.startswith("http://127.0.0.1") or client_id.startswith(
            "http://localhost"
        ):
            return await self._fetch_cimd(client_id)
        return None

    async def _fetch_cimd(self, client_id: str) -> OAuthClientInformationFull | None:
        parsed = urlparse(client_id)
        if parsed.scheme not in {"https", "http"}:
            return None
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                response = await client.get(client_id, headers={"Accept": "application/json"})
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(body, dict):
            return None
        body.setdefault("client_id", client_id)
        body.setdefault("token_endpoint_auth_method", "none")
        body.setdefault("grant_types", ["authorization_code", "refresh_token"])
        body.setdefault("response_types", ["code"])
        try:
            info = OAuthClientInformationFull.model_validate(body)
        except Exception:  # noqa: BLE001
            return None
        await self.register_client(info)
        return info

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with self._lock:
            self._data.setdefault("clients", {})[client_info.client_id] = client_info.model_dump(mode="json")
            self._save()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") not in {self.resource, self.issuer}:
            raise AuthorizeError("invalid_target", "Unknown resource")
        if self.auto_approve:
            return self._issue_code_redirect(client, params)
        txn = secrets.token_urlsafe(24)
        with self._lock:
            self._pending[txn] = {
                "client_id": client.client_id,
                "client_name": client.client_name or client.client_id,
                "params": params.model_dump(mode="json"),
                "expires_at": _now() + 600,
            }
        return f"{self.issuer}/consent?txn={txn}"

    def _issue_code_redirect(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        code = secrets.token_urlsafe(32)
        scopes = params.scopes or [SCOPE]
        record = AuthorizationCode(
            code=code,
            scopes=scopes,
            expires_at=_now() + CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource or self.resource,
            subject="local-owner",
        )
        with self._lock:
            self._codes[code] = record
        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
            iss=self.issuer,
        )

    async def handle_consent(self, request: Request) -> Response:
        txn = request.query_params.get("txn")
        if request.method == "POST":
            form = await request.form()
            txn = str(form.get("txn") or txn or "")
        txn = str(txn) if txn else ""
        with self._lock:
            pending = self._pending.get(txn)
        if not pending or pending["expires_at"] < _now():
            return HTMLResponse("<p>This authorization request expired. Start again from Cursor, Claude, ChatGPT, or Gemini.</p>", 400)
        client = await self.get_client(pending["client_id"])
        if not client:
            return HTMLResponse("<p>Unknown client.</p>", 400)
        params = AuthorizationParams.model_validate(pending["params"])
        if request.method == "GET":
            return HTMLResponse(self._consent_html(txn, pending["client_name"]))
        if str(form.get("decision") or "") != "allow":
            with self._lock:
                self._pending.pop(txn, None)
            return RedirectResponse(
                construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state),
                status_code=302,
            )
        if self.pin and str(form.get("pin") or "") != self.pin:
            return HTMLResponse(self._consent_html(txn, pending["client_name"], error="Wrong PIN."), 401)
        with self._lock:
            self._pending.pop(txn, None)
        return RedirectResponse(self._issue_code_redirect(client, params), status_code=302)

    def _consent_html(self, txn: str, client_name: str, error: str = "") -> str:
        pin_field = (
            '<label>PIN <input name="pin" type="password" required autocomplete="off"></label>' if self.pin else ""
        )
        err = f'<p class="err">{escape(error)}</p>' if error else ""
        return f"""<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Allow Loadpath access</title>
  <style>
    body {{ font: 16px/1.45 system-ui, sans-serif; background: #111; color: #eee; margin: 0; }}
    main {{ max-width: 28rem; margin: 12vh auto; padding: 1.5rem; background: #1c1c1c; border-radius: 12px; }}
    h1 {{ font-size: 1.15rem; }} .muted {{ color: #9aa; font-size: .9rem; }}
    .err {{ color: #f88; }} button {{ margin-right: .5rem; padding: .45rem .9rem; }}
    label {{ display: block; margin: 1rem 0; }}
  </style>
</head><body><main>
  <h1>Allow {escape(client_name)} to use Loadpath?</h1>
  <p class="muted">This host can index repos on this machine and run load-path reviews. Tokens never leave {escape(self.issuer)}.</p>
  {err}
  <form method="post" action="/consent">
    <input type="hidden" name="txn" value="{escape(txn)}"/>
    {pin_field}
    <button name="decision" value="allow" type="submit">Allow</button>
    <button name="decision" value="deny" type="submit">Deny</button>
  </form>
</main></body></html>"""

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self._lock:
            record = self._codes.get(authorization_code)
        if not record or record.client_id != client.client_id:
            return None
        if record.expires_at < _now():
            with self._lock:
                self._codes.pop(authorization_code, None)
            return None
        return record

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with self._lock:
            stored = self._codes.pop(authorization_code.code, None)
        if not stored:
            raise TokenError("invalid_grant", "Authorization code already used")
        return self._mint(client, stored.scopes, stored.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        with self._lock:
            raw = (self._data.get("refresh") or {}).get(refresh_token)
        if not raw or raw.get("client_id") != client.client_id:
            return None
        token = RefreshToken.model_validate(raw)
        if token.expires_at and token.expires_at < int(_now()):
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        granted = scopes or refresh_token.scopes
        if set(granted) - set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Cannot expand refresh token scopes")
        with self._lock:
            self._data.setdefault("refresh", {}).pop(refresh_token.token, None)
            self._save()
        resource = None
        with self._lock:
            for access in (self._data.get("access") or {}).values():
                if access.get("client_id") == client.client_id:
                    resource = access.get("resource")
                    break
        return self._mint(client, granted, resource or self.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._lock:
            raw = (self._data.get("access") or {}).get(token)
        if not raw:
            return None
        access = AccessToken.model_validate(raw)
        if access.expires_at and access.expires_at < int(_now()):
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._lock:
            self._data.setdefault("access", {}).pop(getattr(token, "token", ""), None)
            self._data.setdefault("refresh", {}).pop(getattr(token, "token", ""), None)
            self._save()

    def _mint(self, client: OAuthClientInformationFull, scopes: list[str], resource: str | None) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = int(_now())
        access_row = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=scopes or [SCOPE],
            expires_at=now + ACCESS_TTL,
            resource=resource or self.resource,
            subject="local-owner",
            claims={"iss": self.issuer},
        )
        refresh_row = RefreshToken(
            token=refresh,
            client_id=client.client_id,
            scopes=scopes or [SCOPE],
            expires_at=now + REFRESH_TTL,
            subject="local-owner",
        )
        with self._lock:
            self._data.setdefault("access", {})[access] = access_row.model_dump(mode="json")
            self._data.setdefault("refresh", {})[refresh] = refresh_row.model_dump(mode="json")
            self._save()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TTL,
            scope=" ".join(scopes or [SCOPE]),
            refresh_token=refresh,
        )
