from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

REPO_SLUG = re.compile(r"^[\w.-]+/[\w.-]+$")
LOADPATH_COMMENT_MARKER = "<!-- loadpath-review -->"


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


class SCMProvider(Protocol):
    name: str

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
