const vscode = require("vscode");

function badgeColor(roles) {
  if (roles.includes("untested")) return new vscode.ThemeColor("list.warningForeground");
  if (roles.includes("seed")) return new vscode.ThemeColor("list.highlightForeground");
  if (roles.includes("tested")) return new vscode.ThemeColor("testing.iconPassed");
  return new vscode.ThemeColor("foreground");
}

class LoadpathDecorations {
  constructor() {
    this._onDidChange = new vscode.EventEmitter();
    this.onDidChangeFileDecorations = this._onDidChange.event;
    this.byPath = new Map();
  }

  provideFileDecoration(uri) {
    const item = this.byPath.get(uri.fsPath) || this.byPath.get(uri.path);
    if (!item) return;
    return {
      badge: item.badge || "·",
      tooltip: item.tooltip || "On the Loadpath walk",
      color: badgeColor(item.roles || []),
      propagate: true,
    };
  }

  replace(files, folder) {
    this.byPath = new Map();
    for (const file of files || []) {
      const abs = folder ? require("path").join(folder, file.path) : file.path;
      this.byPath.set(abs, file);
      this.byPath.set(file.path, file);
    }
    this._onDidChange.fire(undefined);
  }
}

async function fetchMarks(url, repoPath) {
  const endpoint = `${url.replace(/\/$/, "")}/api/marks?repo_path=${encodeURIComponent(repoPath)}`;
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`Loadpath marks ${res.status}`);
  return res.json();
}

function activate(context) {
  const decorations = new LoadpathDecorations();
  context.subscriptions.push(vscode.window.registerFileDecorationProvider(decorations));

  const refresh = async () => {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const cfg = vscode.workspace.getConfiguration("loadpath");
    const url = cfg.get("url") || "http://127.0.0.1:7345";
    const repoPath = cfg.get("repoPath") || folder;
    if (!repoPath) return;
    try {
      const payload = await fetchMarks(url, repoPath);
      decorations.replace(payload.files || [], folder || repoPath);
    } catch {
      decorations.replace([], folder);
    }
  };

  context.subscriptions.push(vscode.commands.registerCommand("loadpath.refreshMarks", refresh));
  const timer = setInterval(refresh, 4000);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
  void refresh();
}

function deactivate() {}

module.exports = { activate, deactivate };
