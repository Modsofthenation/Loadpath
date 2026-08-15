# Loadpath editor gutter

Marks files on the current Loadpath walk while `loadpath serve` is running on this machine.

```
code --install-extension /path/to/PR-Reviewer/editors/vscode
```

Or in Cursor: **Install from Location** → `editors/vscode`.

Settings:

- `loadpath.url` — default `http://127.0.0.1:7345`
- `loadpath.repoPath` — defaults to the workspace folder

Badges: `S` seed (the diff), `!` untested sink, `C` contract, `✓` tested, `→` downstream.
