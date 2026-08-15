# Security

Please report vulnerabilities privately to the repository owner (`Modsofthenation` on GitHub). Do not open a public issue for unreleased security problems.

Once this repository is public, enable [GitHub private vulnerability reporting](https://docs.github.com/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository) so researchers can use Security Advisories. The `/security/advisories/new` form 404s until that setting is on.

Tokens and OAuth state live on the machine that runs Loadpath (`~/.loadpath/`); treat that host as trusted. SCM sign-in, disconnect, and `/api/scm/repos` only accept the local Loadpath UI (loopback Origin/Host), so a tunneled MCP server does not list private repositories.
