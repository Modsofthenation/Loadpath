# Security

Loadpath is a **local** tool. Tokens, OAuth state, and architecture indexes stay on the machine that runs it (`~/.loadpath/`, mode `0700` / files `0600`). Treat that host as trusted.

## Report a vulnerability

Please report vulnerabilities **privately**. Do not open a public issue for unreleased security problems.

1. Enable [GitHub private vulnerability reporting](https://docs.github.com/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository) on this repository (required before `/security/advisories/new` works).
2. Use **Security → Report a vulnerability**, or contact the repository owner (`Modsofthenation` on GitHub).

## What is in scope

- Token or OAuth secret leakage from the local API, UI, MCP server, or GitHub Action
- Cross-site request forgery against `loadpath serve` while it is running
- Path traversal or unexpected filesystem writes from `repo_path` / the repo explorer
- Remote use of stored SCM or AI credentials when the process is bound or tunneled

## What is out of scope

- Findings that require physical or local-user access to `~/.loadpath/`
- Issues that only apply if you set `LOADPATH_OAUTH_AUTO_APPROVE=1` (that flag skips consent; never use it outside tests)
- Unsigned desktop installers (macOS Gatekeeper) — tracked as packaging, not a vulnerability

## Hardening notes

- `loadpath serve` defaults to `127.0.0.1`. The HTTP UI (`/api/*` except `/api/health`) refuses non-loopback `Origin` / `Host`.
- SCM sign-in, settings, filesystem browse, review, and PR comments are local-UI only. A tunneled MCP server does not expose those routes.
- MCP over HTTP uses OAuth 2.1 (PKCE, consent). Prefer `--oauth-pin` when `--public-url` is set.
- The GitHub Action interpolates inputs through environment variables, not shell expansion.
