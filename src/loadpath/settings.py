from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_SETTINGS_LOCK = threading.RLock()


def settings_path() -> Path:
    return Path.home() / ".loadpath" / "settings.json"


class AISettings(BaseModel):
    provider: str = "none"
    api_key: str = ""
    model: str = ""
    base_url: str = ""


class SCMConnection(BaseModel):
    provider: str  # github | bitbucket
    token: str = ""
    username: str = ""
    workspace: str = ""
    repos: list[str] = Field(default_factory=list)


class Workspace(BaseModel):
    path: str
    name: str = ""
    remote: str | None = None


class AppSettings(BaseModel):
    github_token: str = ""
    github_user: str = ""
    github_oauth_client_id: str = ""
    github_host: str = ""
    gitlab_token: str = ""
    gitlab_user: str = ""
    gitlab_host: str = ""
    gitlab_oauth_client_id: str = ""
    gitlab_oauth_client_secret: str = ""
    gitlab_refresh_token: str = ""
    bitbucket_token: str = ""
    bitbucket_username: str = ""
    bitbucket_workspace: str = ""
    bitbucket_user: str = ""
    bitbucket_refresh_token: str = ""
    bitbucket_oauth_client_id: str = ""
    bitbucket_oauth_client_secret: str = ""
    ai: AISettings = Field(default_factory=AISettings)
    workspaces: list[Workspace] = Field(default_factory=list)
    connections: list[SCMConnection] = Field(default_factory=list)

    def save(self, path: Path | None = None) -> None:
        with _SETTINGS_LOCK:
            self._write(path)

    def _write(self, path: Path | None = None) -> None:
        p = path or settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p.parent, 0o700)
        except OSError:
            pass
        payload = self.model_dump_json(indent=2)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    @classmethod
    def load(cls, path: Path | None = None) -> AppSettings:
        p = path or settings_path()
        if not p.is_file():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.model_validate(data)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return value[:4] + "…" + value[-2:]


def _should_update_secret(value: str | None, current: str) -> bool:
    if value is None or value == "" or "…" in value:
        return False
    return value != current


def register_workspace(path: Path, name: str | None = None) -> AppSettings:
    with _SETTINGS_LOCK:
        settings = AppSettings.load()
        resolved = str(path.expanduser().resolve())
        if not any(w.path == resolved for w in settings.workspaces):
            settings.workspaces.append(Workspace(path=resolved, name=name or Path(resolved).name))
            settings._write()
        return settings


def public_settings(settings: AppSettings) -> dict[str, Any]:
    data = settings.model_dump()
    data["github_token"] = mask_secret(settings.github_token)
    data["gitlab_token"] = mask_secret(settings.gitlab_token)
    data["gitlab_refresh_token"] = mask_secret(settings.gitlab_refresh_token)
    data["gitlab_oauth_client_secret"] = mask_secret(settings.gitlab_oauth_client_secret)
    data["bitbucket_token"] = mask_secret(settings.bitbucket_token)
    data["bitbucket_refresh_token"] = mask_secret(settings.bitbucket_refresh_token)
    data["bitbucket_oauth_client_secret"] = mask_secret(settings.bitbucket_oauth_client_secret)
    data["github_token_set"] = bool(settings.github_token)
    data["gitlab_token_set"] = bool(settings.gitlab_token)
    data["gitlab_oauth_client_secret_set"] = bool(settings.gitlab_oauth_client_secret)
    data["bitbucket_token_set"] = bool(settings.bitbucket_token)
    data["bitbucket_oauth_client_secret_set"] = bool(settings.bitbucket_oauth_client_secret)
    data["github_oauth_ready"] = bool(
        (os.environ.get("LOADPATH_GITHUB_CLIENT_ID") or settings.github_oauth_client_id or "").strip()
    )
    data["gitlab_oauth_ready"] = bool(
        (os.environ.get("LOADPATH_GITLAB_CLIENT_ID") or settings.gitlab_oauth_client_id or "").strip()
        and (os.environ.get("LOADPATH_GITLAB_CLIENT_SECRET") or settings.gitlab_oauth_client_secret or "").strip()
    )
    data["bitbucket_oauth_ready"] = bool(
        (os.environ.get("LOADPATH_BITBUCKET_CLIENT_ID") or settings.bitbucket_oauth_client_id or "").strip()
        and (os.environ.get("LOADPATH_BITBUCKET_CLIENT_SECRET") or settings.bitbucket_oauth_client_secret or "").strip()
    )
    data["ai"] = {
        "provider": settings.ai.provider,
        "model": settings.ai.model,
        "base_url": settings.ai.base_url,
        "api_key_set": bool(settings.ai.api_key),
        "api_key": mask_secret(settings.ai.api_key),
    }
    for conn in data.get("connections") or []:
        token = conn.get("token") or ""
        conn["token_set"] = bool(token)
        conn["token"] = mask_secret(token)
    return data
