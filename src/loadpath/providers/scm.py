from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

REPO_SLUG = re.compile(r"^[\w.-]+/[\w.-]+$")
LOADPATH_COMMENT_MARKER = "<!-- loadpath-review -->"
REMOTE_HOST = re.compile(
    r"(github\.com|bitbucket\.org)[:/](?P<slug>[\w.-]+/[\w.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
REPO_LIST_LIMIT = 500


def _marked_comment(markdown: str) -> str:
    body = markdown.strip()
    if LOADPATH_COMMENT_MARKER not in body:
        return f"{LOADPATH_COMMENT_MARKER}\n{body}\n"
    return body



def require_repo_slug(repo: str) -> str:
    slug = repo.strip().strip("/")
    if not REPO_SLUG.match(slug):
        raise ValueError("repo must be owner/name")
    return slug


def parse_remote_url(url: str) -> tuple[str, str] | None:
    """Return (provider, owner/name) for a GitHub or Bitbucket remote URL."""
    raw = (url or "").strip()
    match = REMOTE_HOST.search(raw)
    if not match:
        return None
    slug = match.group("slug").strip("/")
    if not REPO_SLUG.match(slug):
        return None
    host = match.group(1).lower()
    provider = "github" if host == "github.com" else "bitbucket"
    return provider, slug


def attach_local_paths(repos: list[RemoteRepo], workspace_paths: list[str]) -> list[RemoteRepo]:
    """Fill local_path when a registered workspace remote matches the repo slug."""
    index: dict[tuple[str, str], str] = {}
    for raw in workspace_paths:
        path = Path(raw).expanduser()
        try:
            if not path.is_dir():
                continue
            listed = subprocess.check_output(
                ["git", "-C", str(path), "remote", "-v"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        resolved = str(path.resolve()) if path.exists() else str(path)
        for line in listed.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            parsed = parse_remote_url(parts[1])
            if parsed:
                index[(parsed[0], parsed[1].lower())] = resolved
    for repo in repos:
        repo.local_path = index.get((repo.provider, repo.slug.lower()))
    return repos


@dataclass
class PullRequest:
    provider: str
    id: str
    number: int
    title: str
    url: str
    author: str
    source_branch: str
    target_branch: str
    repo: str
    state: str
    updated_at: str
    draft: bool = False
    head_sha: str = ""
    base_sha: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RemoteRepo:
    provider: str
    slug: str
    name: str
    owner: str
    url: str
    private: bool = False
    default_branch: str = ""
    updated_at: str = ""
    description: str = ""
    local_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class SCMProvider(Protocol):
    name: str

    def current_user(self) -> dict[str, str]: ...

    def list_repositories(self, limit: int = REPO_LIST_LIMIT) -> list[RemoteRepo]: ...

    def list_pull_requests(self, repo: str, state: str = "open") -> list[PullRequest]: ...

    def get_pull_request(self, repo: str, number: int) -> PullRequest: ...

    def get_diff(self, repo: str, number: int) -> str: ...

    def upsert_pull_request_comment(self, repo: str, number: int, markdown: str) -> dict[str, Any]: ...


class GitHubProvider:
    name = "github"

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.token = token
        self.client = client or httpx.Client(timeout=30.0)
        self.base = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def current_user(self) -> dict[str, str]:
        r = self.client.get(f"{self.base}/user", headers=self._headers())
        r.raise_for_status()
        item = r.json()
        return {
            "login": item.get("login") or "",
            "name": item.get("name") or item.get("login") or "",
            "url": item.get("html_url") or "",
        }

    def list_repositories(self, limit: int = REPO_LIST_LIMIT) -> list[RemoteRepo]:
        cap = max(1, min(limit, REPO_LIST_LIMIT))
        out: list[RemoteRepo] = []
        page = 1
        while len(out) < cap:
            per_page = min(100, cap - len(out))
            r = self.client.get(
                f"{self.base}/user/repos",
                params={
                    "per_page": per_page,
                    "page": page,
                    "sort": "updated",
                    "affiliation": "owner,collaborator,organization_member",
                },
                headers=self._headers(),
            )
            r.raise_for_status()
            batch = r.json() or []
            if not batch:
                break
            for item in batch:
                slug = item.get("full_name") or ""
                owner, _, name = slug.partition("/")
                html = item.get("html_url") or ""
                out.append(
                    RemoteRepo(
                        provider="github",
                        slug=slug,
                        name=name or slug,
                        owner=owner,
                        url=html,
                        private=bool(item.get("private")),
                        default_branch=item.get("default_branch") or "",
                        updated_at=item.get("updated_at") or "",
                        description=item.get("description") or "",
                    )
                )
            if len(batch) < per_page:
                break
            page += 1
        return out[:cap]

    def list_pull_requests(self, repo: str, state: str = "open") -> list[PullRequest]:
        repo = require_repo_slug(repo)
        r = self.client.get(
            f"{self.base}/repos/{repo}/pulls",
            params={"state": state, "per_page": 50, "sort": "updated"},
            headers=self._headers(),
        )
        r.raise_for_status()
        out = []
        for item in r.json():
            out.append(
                PullRequest(
                    provider="github",
                    id=str(item["id"]),
                    number=item["number"],
                    title=item["title"],
                    url=item["html_url"],
                    author=(item.get("user") or {}).get("login") or "",
                    source_branch=(item.get("head") or {}).get("ref") or "",
                    target_branch=(item.get("base") or {}).get("ref") or "",
                    repo=repo,
                    state=item.get("state") or "open",
                    updated_at=item.get("updated_at") or "",
                    draft=bool(item.get("draft")),
                    head_sha=(item.get("head") or {}).get("sha") or "",
                    base_sha=(item.get("base") or {}).get("sha") or "",
                )
            )
        return out

    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        repo = require_repo_slug(repo)
        r = self.client.get(f"{self.base}/repos/{repo}/pulls/{number}", headers=self._headers())
        r.raise_for_status()
        item = r.json()
        return PullRequest(
            provider="github",
            id=str(item["id"]),
            number=item["number"],
            title=item["title"],
            url=item["html_url"],
            author=(item.get("user") or {}).get("login") or "",
            source_branch=(item.get("head") or {}).get("ref") or "",
            target_branch=(item.get("base") or {}).get("ref") or "",
            repo=repo,
            state=item.get("state") or "open",
            updated_at=item.get("updated_at") or "",
            draft=bool(item.get("draft")),
            head_sha=(item.get("head") or {}).get("sha") or "",
            base_sha=(item.get("base") or {}).get("sha") or "",
        )

    def get_diff(self, repo: str, number: int) -> str:
        repo = require_repo_slug(repo)
        r = self.client.get(
            f"{self.base}/repos/{repo}/pulls/{number}",
            headers={**self._headers(), "Accept": "application/vnd.github.diff"},
        )
        r.raise_for_status()
        return r.text

    def upsert_pull_request_comment(self, repo: str, number: int, markdown: str) -> dict[str, Any]:
        repo = require_repo_slug(repo)
        body = _marked_comment(markdown)
        listed = self.client.get(
            f"{self.base}/repos/{repo}/issues/{number}/comments",
            params={"per_page": 100},
            headers=self._headers(),
        )
        listed.raise_for_status()
        existing_id = None
        for item in listed.json() or []:
            if LOADPATH_COMMENT_MARKER in (item.get("body") or ""):
                existing_id = item.get("id")
                break
        # Walk a couple of pages so a busy PR does not grow a second Loadpath comment.
        page = 2
        while existing_id is None and page <= 3:
            more = self.client.get(
                f"{self.base}/repos/{repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
                headers=self._headers(),
            )
            more.raise_for_status()
            batch = more.json() or []
            if not batch:
                break
            for item in batch:
                if LOADPATH_COMMENT_MARKER in (item.get("body") or ""):
                    existing_id = item.get("id")
                    break
            page += 1
        if existing_id:
            r = self.client.patch(
                f"{self.base}/repos/{repo}/issues/comments/{existing_id}",
                headers=self._headers(),
                json={"body": body},
            )
            r.raise_for_status()
            data = r.json()
            return {"id": str(data.get("id")), "url": data.get("html_url") or "", "updated": True}
        r = self.client.post(
            f"{self.base}/repos/{repo}/issues/{number}/comments",
            headers=self._headers(),
            json={"body": body},
        )
        r.raise_for_status()
        data = r.json()
        return {"id": str(data.get("id")), "url": data.get("html_url") or "", "updated": False}


class BitbucketProvider:
    name = "bitbucket"

    def __init__(
        self,
        token: str,
        username: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self.token = token
        self.username = username
        self.client = client or httpx.Client(timeout=30.0)
        self.base = "https://api.bitbucket.org/2.0"

    def _auth(self) -> tuple[str, str] | None:
        if self.username:
            return (self.username, self.token)
        return None

    def _headers(self) -> dict[str, str]:
        if self.username:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def current_user(self) -> dict[str, str]:
        r = self.client.get(f"{self.base}/user", headers=self._headers(), auth=self._auth())
        r.raise_for_status()
        item = r.json()
        login = item.get("username") or ""
        return {
            "login": login,
            "name": item.get("display_name") or login,
            "url": ((item.get("links") or {}).get("html") or {}).get("href") or "",
        }

    def list_repositories(self, limit: int = REPO_LIST_LIMIT) -> list[RemoteRepo]:
        cap = max(1, min(limit, REPO_LIST_LIMIT))
        out: list[RemoteRepo] = []
        url: str | None = f"{self.base}/repositories"
        params: dict[str, Any] | None = {"role": "member", "pagelen": min(50, cap), "sort": "-updated_on"}
        while url and len(out) < cap:
            r = self.client.get(url, params=params, headers=self._headers(), auth=self._auth())
            r.raise_for_status()
            data = r.json()
            params = None
            for item in data.get("values") or []:
                slug = item.get("full_name") or ""
                owner, _, name = slug.partition("/")
                html = ((item.get("links") or {}).get("html") or {}).get("href") or ""
                out.append(
                    RemoteRepo(
                        provider="bitbucket",
                        slug=slug,
                        name=name or slug,
                        owner=owner,
                        url=html,
                        private=item.get("is_private", True),
                        default_branch=((item.get("mainbranch") or {}).get("name") or ""),
                        updated_at=item.get("updated_on") or "",
                        description=item.get("description") or "",
                    )
                )
                if len(out) >= cap:
                    break
            url = data.get("next") or None
        return out[:cap]

    def list_pull_requests(self, repo: str, state: str = "open") -> list[PullRequest]:
        repo = require_repo_slug(repo)
        bb_state = "OPEN" if state == "open" else state.upper()
        r = self.client.get(
            f"{self.base}/repositories/{repo}/pullrequests",
            params={"state": bb_state, "pagelen": 50},
            headers=self._headers(),
            auth=self._auth(),
        )
        r.raise_for_status()
        out = []
        for item in r.json().get("values") or []:
            src = ((item.get("source") or {}).get("branch") or {}).get("name") or ""
            dst = ((item.get("destination") or {}).get("branch") or {}).get("name") or ""
            links = item.get("links") or {}
            html = (links.get("html") or {}).get("href") or ""
            author = ((item.get("author") or {}).get("display_name")) or ""
            out.append(
                PullRequest(
                    provider="bitbucket",
                    id=str(item.get("id")),
                    number=int(item.get("id")),
                    title=item.get("title") or "",
                    url=html,
                    author=author,
                    source_branch=src,
                    target_branch=dst,
                    repo=repo,
                    state=(item.get("state") or "").lower(),
                    updated_at=item.get("updated_on") or "",
                    draft=False,
                    head_sha=(((item.get("source") or {}).get("commit") or {}).get("hash") or ""),
                    base_sha=(((item.get("destination") or {}).get("commit") or {}).get("hash") or ""),
                )
            )
        return out

    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        repo = require_repo_slug(repo)
        r = self.client.get(
            f"{self.base}/repositories/{repo}/pullrequests/{number}",
            headers=self._headers(),
            auth=self._auth(),
        )
        r.raise_for_status()
        item = r.json()
        src = ((item.get("source") or {}).get("branch") or {}).get("name") or ""
        dst = ((item.get("destination") or {}).get("branch") or {}).get("name") or ""
        html = ((item.get("links") or {}).get("html") or {}).get("href") or ""
        return PullRequest(
            provider="bitbucket",
            id=str(item.get("id")),
            number=int(item.get("id")),
            title=item.get("title") or "",
            url=html,
            author=((item.get("author") or {}).get("display_name")) or "",
            source_branch=src,
            target_branch=dst,
            repo=repo,
            state=(item.get("state") or "").lower(),
            updated_at=item.get("updated_on") or "",
            head_sha=(((item.get("source") or {}).get("commit") or {}).get("hash") or ""),
            base_sha=(((item.get("destination") or {}).get("commit") or {}).get("hash") or ""),
        )

    def get_diff(self, repo: str, number: int) -> str:
        repo = require_repo_slug(repo)
        r = self.client.get(
            f"{self.base}/repositories/{repo}/pullrequests/{number}/diff",
            headers=self._headers(),
            auth=self._auth(),
        )
        r.raise_for_status()
        return r.text

    def upsert_pull_request_comment(self, repo: str, number: int, markdown: str) -> dict[str, Any]:
        repo = require_repo_slug(repo)
        body = _marked_comment(markdown)
        listed = self.client.get(
            f"{self.base}/repositories/{repo}/pullrequests/{number}/comments",
            params={"pagelen": 100},
            headers=self._headers(),
            auth=self._auth(),
        )
        listed.raise_for_status()
        existing_id = None
        for item in listed.json().get("values") or []:
            raw = ((item.get("content") or {}).get("raw")) or ""
            if LOADPATH_COMMENT_MARKER in raw:
                existing_id = item.get("id")
                break
        payload = {"content": {"raw": body}}
        if existing_id:
            r = self.client.put(
                f"{self.base}/repositories/{repo}/pullrequests/{number}/comments/{existing_id}",
                headers=self._headers(),
                auth=self._auth(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            url = ((data.get("links") or {}).get("html") or {}).get("href") or ""
            return {"id": str(data.get("id")), "url": url, "updated": True}
        r = self.client.post(
            f"{self.base}/repositories/{repo}/pullrequests/{number}/comments",
            headers=self._headers(),
            auth=self._auth(),
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        url = ((data.get("links") or {}).get("html") or {}).get("href") or ""
        return {"id": str(data.get("id")), "url": url, "updated": False}


def provider_for(name: str, token: str, username: str = "", client: httpx.Client | None = None) -> SCMProvider:
    if name == "github":
        return GitHubProvider(token, client=client)
    if name == "bitbucket":
        return BitbucketProvider(token, username=username, client=client)
    raise ValueError(f"Unknown SCM provider: {name}")
