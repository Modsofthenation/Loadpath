"""GitHub device flow and Bitbucket authorization-code login. Tokens stay on this machine."""

from __future__ import annotations

import os
import secrets
import threading
import time
from html import escape
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from loadpath.providers.scm import provider_for
from loadpath.settings import AppSettings

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_SCOPES = "repo read:user read:org"
BITBUCKET_AUTHORIZE_URL = "https://bitbucket.org/site/oauth2/authorize"
BITBUCKET_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"
BITBUCKET_SCOPES = "account repository pullrequest"
GITLAB_SCOPES = "api read_user read_repository"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver", "testclient"})
GITHUB_DEVICE_HOSTS = frozenset({"github.com", "www.github.com"})
MAX_PENDING = 8

_lock = threading.RLock()
_pending: dict[str, dict[str, Any]] = {}


def _hostname(host_header: str) -> str:
    raw = (host_header or "").strip()
    if raw.startswith("["):
        return raw[1:].split("]", 1)[0].lower()
    return raw.split(":", 1)[0].lower()


def is_loopback_request(host_header: str, origin: str = "") -> bool:
    """True for the local UI, TestClient, or curl on loopback. False for other websites."""
    if (origin or "").strip():
        host = (urlparse(origin).hostname or "").lower().strip("[]")
        return host in LOOPBACK_HOSTS
    return _hostname(host_header) in LOOPBACK_HOSTS


def _is_github_device_url(url: str, host: str = "github.com") -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    hostname = (parsed.hostname or "").lower()
    allowed = {host.lower(), f"www.{host.lower()}"}
    if host.lower() in {"github.com", "www.github.com"}:
        allowed |= GITHUB_DEVICE_HOSTS
    if hostname not in allowed:
        return False
    return parsed.path.rstrip("/") == "/login/device"


def github_device_urls(data: dict[str, Any], user_code: str, host: str = "github.com") -> tuple[str, str]:
    origin = f"https://{host}"
    verification = data.get("verification_uri") or f"{origin}/login/device"
    if not _is_github_device_url(verification, host):
        raise ValueError("GitHub returned an unexpected verification URL")
    complete = data.get("verification_uri_complete") or ""
    if not _is_github_device_url(complete, host):
        complete = f"{origin}/login/device?user_code={user_code}"
    return verification, complete


def _remember_pending(flow_id: str, row: dict[str, Any]) -> None:
    with _lock:
        now = time.time()
        for key, item in list(_pending.items()):
            if float(item.get("expires_at") or 0) < now:
                _pending.pop(key, None)
        while len(_pending) >= MAX_PENDING:
            oldest = min(_pending, key=lambda key: float(_pending[key].get("expires_at") or 0))
            _pending.pop(oldest, None)
        _pending[flow_id] = row


def github_web_host(settings: AppSettings | None = None) -> str:
    settings = settings or AppSettings.load()
    host = (os.environ.get("LOADPATH_GITHUB_HOST") or settings.github_host or "github.com").strip()
    host = host.removeprefix("https://").removeprefix("http://").strip("/")
    if host in {"", "api.github.com", "www.github.com"}:
        return "github.com"
    return host


def gitlab_web_host(settings: AppSettings | None = None) -> str:
    settings = settings or AppSettings.load()
    host = (os.environ.get("LOADPATH_GITLAB_HOST") or settings.gitlab_host or "gitlab.com").strip()
    host = host.removeprefix("https://").removeprefix("http://").strip("/")
    return host or "gitlab.com"


def github_client_id(settings: AppSettings | None = None) -> str:
    settings = settings or AppSettings.load()
    return (os.environ.get("LOADPATH_GITHUB_CLIENT_ID") or settings.github_oauth_client_id or "").strip()


def bitbucket_oauth_client(settings: AppSettings | None = None) -> tuple[str, str]:
    settings = settings or AppSettings.load()
    client_id = (os.environ.get("LOADPATH_BITBUCKET_CLIENT_ID") or settings.bitbucket_oauth_client_id or "").strip()
    secret = (
        os.environ.get("LOADPATH_BITBUCKET_CLIENT_SECRET") or settings.bitbucket_oauth_client_secret or ""
    ).strip()
    return client_id, secret


def gitlab_oauth_client(settings: AppSettings | None = None) -> tuple[str, str]:
    settings = settings or AppSettings.load()
    client_id = (os.environ.get("LOADPATH_GITLAB_CLIENT_ID") or settings.gitlab_oauth_client_id or "").strip()
    secret = (
        os.environ.get("LOADPATH_GITLAB_CLIENT_SECRET") or settings.gitlab_oauth_client_secret or ""
    ).strip()
    return client_id, secret


def oauth_status(settings: AppSettings | None = None) -> dict[str, Any]:
    settings = settings or AppSettings.load()
    bb_id, bb_secret = bitbucket_oauth_client(settings)
    gl_id, gl_secret = gitlab_oauth_client(settings)
    return {
        "github": {
            "connected": bool(settings.github_token),
            "user": settings.github_user,
            "token_set": bool(settings.github_token),
            "oauth_ready": bool(github_client_id(settings)),
            "host": github_web_host(settings),
        },
        "gitlab": {
            "connected": bool(settings.gitlab_token),
            "user": settings.gitlab_user,
            "token_set": bool(settings.gitlab_token),
            "oauth_ready": bool(gl_id and gl_secret),
            "host": gitlab_web_host(settings),
        },
        "bitbucket": {
            "connected": bool(settings.bitbucket_token),
            "user": settings.bitbucket_user,
            "token_set": bool(settings.bitbucket_token),
            "oauth_ready": bool(bb_id and bb_secret),
        },
    }


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=30.0)


def start_github_device(client: httpx.Client | None = None) -> dict[str, Any]:
    settings = AppSettings.load()
    client_id = github_client_id(settings)
    if not client_id:
        raise ValueError(
            "GitHub OAuth client ID is not configured. Set LOADPATH_GITHUB_CLIENT_ID "
            "or paste a GitHub OAuth App client ID in Settings (enable Device Flow on the app)."
        )
    http = _client(client)
    host = github_web_host(settings)
    device_url = f"https://{host}/login/device/code"
    response = http.post(
        device_url,
        data={"client_id": client_id, "scope": GITHUB_SCOPES},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    device_code = data.get("device_code") or ""
    user_code = data.get("user_code") or ""
    if not device_code or not user_code:
        raise ValueError("GitHub did not return a device code")
    verification, complete = github_device_urls(data, user_code, host=host)
    flow_id = secrets.token_urlsafe(16)
    interval = int(data.get("interval") or 5)
    expires_in = int(data.get("expires_in") or 900)
    _remember_pending(
        flow_id,
        {
            "provider": "github",
            "device_code": device_code,
            "client_id": client_id,
            "host": host,
            "interval": interval,
            "expires_at": time.time() + expires_in,
        },
    )
    return {
        "flow_id": flow_id,
        "user_code": user_code,
        "verification_uri": verification,
        "verification_uri_complete": complete,
        "interval": interval,
        "expires_in": expires_in,
    }


def poll_github_device(flow_id: str, client: httpx.Client | None = None) -> dict[str, Any]:
    with _lock:
        pending = _pending.get(flow_id)
    if not pending or pending.get("provider") != "github":
        raise ValueError("Unknown or expired GitHub sign-in")
    if pending["expires_at"] < time.time():
        with _lock:
            _pending.pop(flow_id, None)
        return {"status": "expired"}
    http = _client(client)
    host = pending.get("host") or "github.com"
    token_url = f"https://{host}/login/oauth/access_token"
    response = http.post(
        token_url,
        data={
            "client_id": pending["client_id"],
            "device_code": pending["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        headers={"Accept": "application/json"},
    )
    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        data = {}
    if not isinstance(data, dict):
        response.raise_for_status()
        data = {}
    error = data.get("error")
    if error == "authorization_pending":
        return {"status": "pending", "interval": pending["interval"]}
    if error == "slow_down":
        return {"status": "slow_down", "interval": pending["interval"] + 5}
    if error in {"expired_token", "access_denied"}:
        with _lock:
            _pending.pop(flow_id, None)
        return {"status": "denied" if error == "access_denied" else "expired"}
    if error:
        raise ValueError(data.get("error_description") or error)
    response.raise_for_status()
    token = data.get("access_token") or ""
    if not token:
        raise ValueError("GitHub did not return an access token")
    with _lock:
        _pending.pop(flow_id, None)
    settings = _store_login("github", token, client=http, host=host)
    return {"status": "complete", **oauth_status(settings)["github"]}


def start_bitbucket_authorize(redirect_uri: str) -> dict[str, Any]:
    settings = AppSettings.load()
    client_id, secret = bitbucket_oauth_client(settings)
    if not client_id or not secret:
        raise ValueError(
            "Bitbucket OAuth consumer is not configured. Set LOADPATH_BITBUCKET_CLIENT_ID and "
            "LOADPATH_BITBUCKET_CLIENT_SECRET, or paste the consumer key and secret in Settings. "
            f"Callback URL must be {redirect_uri}."
        )
    flow_id = secrets.token_urlsafe(16)
    _remember_pending(
        flow_id,
        {
            "provider": "bitbucket",
            "redirect_uri": redirect_uri,
            "expires_at": time.time() + 600,
        },
    )
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": BITBUCKET_SCOPES,
            "state": flow_id,
            "redirect_uri": redirect_uri,
        }
    )
    return {"flow_id": flow_id, "authorize_url": f"{BITBUCKET_AUTHORIZE_URL}?{query}"}


def finish_bitbucket_authorize(
    code: str,
    state: str,
    client: httpx.Client | None = None,
) -> AppSettings:
    with _lock:
        pending = _pending.pop(state, None)
    if not pending or pending.get("provider") != "bitbucket":
        raise ValueError("Unknown or expired Bitbucket sign-in")
    if pending["expires_at"] < time.time():
        raise ValueError("Bitbucket sign-in expired. Start again from Settings.")
    settings = AppSettings.load()
    client_id, secret = bitbucket_oauth_client(settings)
    http = _client(client)
    response = http.post(
        BITBUCKET_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending["redirect_uri"],
        },
        auth=(client_id, secret),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token") or ""
    if not token:
        raise ValueError(data.get("error_description") or "Bitbucket did not return an access token")
    return _store_login(
        "bitbucket",
        token,
        refresh_token=data.get("refresh_token") or "",
        client=http,
    )


def start_gitlab_authorize(redirect_uri: str) -> dict[str, Any]:
    settings = AppSettings.load()
    client_id, secret = gitlab_oauth_client(settings)
    if not client_id or not secret:
        raise ValueError(
            "GitLab OAuth application is not configured. Set LOADPATH_GITLAB_CLIENT_ID and "
            "LOADPATH_GITLAB_CLIENT_SECRET, or paste the application id and secret in Settings. "
            f"Callback URL must be {redirect_uri}."
        )
    host = gitlab_web_host(settings)
    flow_id = secrets.token_urlsafe(16)
    _remember_pending(
        flow_id,
        {
            "provider": "gitlab",
            "redirect_uri": redirect_uri,
            "host": host,
            "expires_at": time.time() + 600,
        },
    )
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": GITLAB_SCOPES,
            "state": flow_id,
            "redirect_uri": redirect_uri,
        }
    )
    return {"flow_id": flow_id, "authorize_url": f"https://{host}/oauth/authorize?{query}"}


def finish_gitlab_authorize(
    code: str,
    state: str,
    client: httpx.Client | None = None,
) -> AppSettings:
    with _lock:
        pending = _pending.pop(state, None)
    if not pending or pending.get("provider") != "gitlab":
        raise ValueError("Unknown or expired GitLab sign-in")
    if pending["expires_at"] < time.time():
        raise ValueError("GitLab sign-in expired. Start again from Settings.")
    settings = AppSettings.load()
    client_id, secret = gitlab_oauth_client(settings)
    host = pending.get("host") or gitlab_web_host(settings)
    http = _client(client)
    response = http.post(
        f"https://{host}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending["redirect_uri"],
            "client_id": client_id,
            "client_secret": secret,
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token") or ""
    if not token:
        raise ValueError(data.get("error_description") or "GitLab did not return an access token")
    return _store_login(
        "gitlab",
        token,
        refresh_token=data.get("refresh_token") or "",
        client=http,
        host=host,
    )


def refresh_bitbucket_access_token(
    settings: AppSettings | None = None,
    client: httpx.Client | None = None,
) -> AppSettings:
    settings = settings or AppSettings.load()
    client_id, secret = bitbucket_oauth_client(settings)
    refresh = settings.bitbucket_refresh_token
    if not (client_id and secret and refresh):
        raise ValueError("Bitbucket refresh token is missing")
    http = _client(client)
    response = http.post(
        BITBUCKET_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        auth=(client_id, secret),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token") or ""
    if not token:
        raise ValueError("Bitbucket refresh did not return an access token")
    settings.bitbucket_token = token
    if data.get("refresh_token"):
        settings.bitbucket_refresh_token = data["refresh_token"]
    settings.save()
    return settings


def disconnect_scm(provider: str) -> AppSettings:
    settings = AppSettings.load()
    if provider == "github":
        settings.github_token = ""
        settings.github_user = ""
    elif provider == "bitbucket":
        settings.bitbucket_token = ""
        settings.bitbucket_user = ""
        settings.bitbucket_refresh_token = ""
    elif provider == "gitlab":
        settings.gitlab_token = ""
        settings.gitlab_user = ""
        settings.gitlab_refresh_token = ""
    else:
        raise ValueError(f"Unknown SCM provider: {provider}")
    settings.save()
    return settings


def _store_login(
    provider: str,
    token: str,
    *,
    refresh_token: str = "",
    client: httpx.Client | None = None,
    host: str = "",
) -> AppSettings:
    settings = AppSettings.load()
    username = ""
    if provider == "github":
        settings.github_token = token
        if host:
            settings.github_host = host if host != "github.com" else settings.github_host
    elif provider == "gitlab":
        settings.gitlab_token = token
        if host:
            settings.gitlab_host = host if host != "gitlab.com" else settings.gitlab_host
        if refresh_token:
            settings.gitlab_refresh_token = refresh_token
    else:
        settings.bitbucket_token = token
        settings.bitbucket_username = ""
        if refresh_token:
            settings.bitbucket_refresh_token = refresh_token
    try:
        scm = provider_for(provider, token, username=username, client=client, host=host)
        profile = scm.current_user()
        login = profile.get("login") or ""
        if provider == "github":
            settings.github_user = login
        elif provider == "gitlab":
            settings.gitlab_user = login
        else:
            settings.bitbucket_user = login
    except httpx.HTTPError:
        pass
    settings.save()
    return settings


def callback_html(*, ok: bool, title: str, body: str) -> str:
    tone = "#8fd4a0" if ok else "#f88"
    return f"""<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{escape(title)}</title>
  <style>
    body {{ font: 16px/1.45 system-ui, sans-serif; background: #111; color: #eee; margin: 0; }}
    main {{ max-width: 28rem; margin: 12vh auto; padding: 1.5rem; background: #1c1c1c; border-radius: 12px; }}
    h1 {{ font-size: 1.15rem; color: {tone}; }} .muted {{ color: #9aa; font-size: .9rem; }}
    a {{ color: #8ec8ff; }}
  </style>
</head><body><main>
  <h1>{escape(title)}</h1>
  <p class="muted">{escape(body)}</p>
  <p class="muted"><a href="/">Back to Loadpath</a></p>
</main></body></html>"""
