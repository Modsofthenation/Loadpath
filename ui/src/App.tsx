import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api } from "./api";
import { formatWhen, kindLabel, strengthLabel, typeLabel } from "./format";
import { IconArchitecture, IconFolder, IconGraph, IconPrs, IconReview, IconSettings } from "./icons";
import { ImpactGraph } from "./ImpactGraph";
import { RefCombobox } from "./RefCombobox";
import { RepoExplorer } from "./RepoExplorer";
import { THEMES, applyTheme, readTheme, type ThemeId } from "./themes";
import type { ArchitectureReport, DeepeningCandidate, GitRefs, IndexedRepo, PullRequest, Review } from "./types";

type Tab = "review" | "architecture" | "graph" | "prs" | "settings";
type GraphMode = "review" | "architecture";

const TABS: { id: Tab; label: string; testId: string; shortcut: string; icon: typeof IconReview }[] = [
  { id: "review", label: "Review", testId: "tab-review", shortcut: "1", icon: IconReview },
  { id: "architecture", label: "Architecture", testId: "tab-architecture", shortcut: "2", icon: IconArchitecture },
  { id: "graph", label: "Impact graph", testId: "tab-graph", shortcut: "3", icon: IconGraph },
  { id: "prs", label: "Pull requests", testId: "tab-prs", shortcut: "4", icon: IconPrs },
  { id: "settings", label: "Settings", testId: "tab-settings", shortcut: "5", icon: IconSettings },
];

export function App() {
  const [tab, setTab] = useState<Tab>("review");
  const [repo, setRepo] = useState(localStorage.getItem("loadpath.repo") || "");
  const [base, setBase] = useState(localStorage.getItem("loadpath.base") || "HEAD~1");
  const [head, setHead] = useState(localStorage.getItem("loadpath.head") || "HEAD");
  const [review, setReview] = useState<Review | null>(null);
  const [architecture, setArchitecture] = useState<ArchitectureReport | null>(null);
  const [repos, setRepos] = useState<IndexedRepo[]>([]);
  const [graphMode, setGraphMode] = useState<GraphMode>("review");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState("");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [prs, setPrs] = useState<PullRequest[]>([]);
  const [scmRepo, setScmRepo] = useState(localStorage.getItem("loadpath.scmRepo") || "");
  const [provider, setProvider] = useState(localStorage.getItem("loadpath.provider") || "github");
  const [prNumber, setPrNumber] = useState(localStorage.getItem("loadpath.prNumber") || "");
  const [aiNote, setAiNote] = useState("");
  const [theme, setTheme] = useState<ThemeId>(readTheme);
  const [settingsReady, setSettingsReady] = useState(false);
  const [explorerOpen, setExplorerOpen] = useState(false);
  const [gitRefs, setGitRefs] = useState<GitRefs | null>(null);
  const repoRef = useRef(repo);
  repoRef.current = repo;
  const explorerOpenRef = useRef(false);
  explorerOpenRef.current = explorerOpen;
  const gitRefsPath = useRef("");

  const persistTheme = (id: ThemeId) => {
    setTheme(id);
    applyTheme(id);
  };

  const busyRef = useRef("");
  const markBusy = (msg: string) => {
    busyRef.current = msg;
    setBusy(msg);
  };

  useEffect(() => {
    api
      .settings()
      .then(setSettings)
      .catch(() => undefined)
      .finally(() => setSettingsReady(true));
    api.repos().then((r) => setRepos(r.repos)).catch(() => undefined);
  }, []);

  const requireRepo = () => {
    if (!repo.trim()) {
      setError("Point at a local repository path first.");
      return false;
    }
    return true;
  };

  useEffect(() => {
    if (tab !== "architecture" || !repo.trim()) return;
    const requested = repo;
    let cancelled = false;
    api
      .architecture(requested)
      .then((report) => {
        if (!cancelled && repoRef.current === requested) setArchitecture(report);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tab, repo]);

  const persistRepo = (path: string) => {
    setRepo(path);
    localStorage.setItem("loadpath.repo", path);
    if (path.trim() !== gitRefsPath.current) {
      gitRefsPath.current = "";
      setGitRefs(null);
    }
  };

  const loadGitRefs = useCallback(() => {
    const path = repoRef.current.trim();
    if (!path || gitRefsPath.current === path) return;
    gitRefsPath.current = path;
    api
      .gitRefs(path)
      .then((next) => {
        if (repoRef.current.trim() === path) setGitRefs(next);
      })
      .catch(() => {
        if (gitRefsPath.current === path) {
          gitRefsPath.current = "";
          setGitRefs(null);
        }
      });
  }, []);

  const persistRefs = (nextBase: string, nextHead: string) => {
    setBase(nextBase);
    setHead(nextHead);
    localStorage.setItem("loadpath.base", nextBase);
    localStorage.setItem("loadpath.head", nextHead);
  };

  const persistPr = (nextProvider: string, nextRepo: string, number?: string) => {
    setProvider(nextProvider);
    setScmRepo(nextRepo);
    localStorage.setItem("loadpath.provider", nextProvider);
    localStorage.setItem("loadpath.scmRepo", nextRepo);
    if (number !== undefined) {
      setPrNumber(number);
      localStorage.setItem("loadpath.prNumber", number);
    }
  };

  const loadArchitecture = async (path = repo) => {
    if (!path.trim()) return null;
    const report = await api.architecture(path);
    if (repoRef.current === path) setArchitecture(report);
    return report;
  };

  const runReview = async () => {
    if (busyRef.current) return;
    if (!requireRepo()) return;
    setError("");
    setCopied("");
    markBusy("Tracing load path…");
    persistRepo(repo);
    persistRefs(base, head);
    try {
      const r = await api.review(repo, base, head, true);
      setReview(r);
      setGraphMode("review");
      setTab("review");
      await api.repos().then((x) => setRepos(x.repos)).catch(() => undefined);
      await loadArchitecture(repo);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      markBusy("");
    }
  };

  const runIndex = async (incremental = true) => {
    if (busyRef.current) return;
    if (!requireRepo()) return;
    setError("");
    setCopied("");
    markBusy(incremental ? "Indexing…" : "Full reindex…");
    persistRepo(repo);
    try {
      await api.index(repo, incremental);
      const report = await loadArchitecture(repo);
      await api.repos().then((x) => setRepos(x.repos)).catch(() => undefined);
      if (report?.indexed) {
        setGraphMode("architecture");
        setTab("architecture");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      markBusy("");
    }
  };

  const draftConfig = async () => {
    if (busyRef.current) return;
    if (!requireRepo()) return;
    setError("");
    setCopied("");
    markBusy("Detecting layout…");
    persistRepo(repo);
    try {
      const layout = await api.init(repo);
      setCopied(layout.message);
      await api.repos().then((x) => setRepos(x.repos)).catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      markBusy("");
    }
  };

  const copyMarkdown = async () => {
    if (!review?.markdown) return;
    try {
      await navigator.clipboard.writeText(review.markdown);
      setCopied("Copied markdown brief");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const postComment = async () => {
    if (busyRef.current) return;
    if (!review?.markdown || !scmRepo || !prNumber) {
      setError("Pick a pull request first (Pull requests tab), then post the brief.");
      return;
    }
    markBusy("Posting Loadpath brief…");
    try {
      const posted = await api.postComment(provider, scmRepo, Number(prNumber), review.markdown);
      setCopied(posted.updated ? "Updated the Loadpath PR comment" : "Posted the Loadpath PR comment");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      markBusy("");
    }
  };

  const loadPrs = async () => {
    if (busyRef.current) return;
    setError("");
    markBusy("Fetching pull requests…");
    try {
      const r = await api.prs(provider, scmRepo);
      setPrs(r.pull_requests);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      markBusy("");
    }
  };

  const saveSettings = async (evt: FormEvent<HTMLFormElement>) => {
    evt.preventDefault();
    const fd = new FormData(evt.currentTarget);
    const body = {
      github_token: String(fd.get("github_token") || ""),
      bitbucket_token: String(fd.get("bitbucket_token") || ""),
      bitbucket_username: String(fd.get("bitbucket_username") || ""),
      ai_provider: String(fd.get("ai_provider") || "none"),
      ai_api_key: String(fd.get("ai_api_key") || ""),
      ai_model: String(fd.get("ai_model") || ""),
      ai_base_url: String(fd.get("ai_base_url") || ""),
    };
    const payload = repos.length
      ? { ...body, workspaces: repos.map((r) => ({ path: r.path, name: r.name })) }
      : body;
    try {
      setSettings(await api.saveSettings(payload));
      setCopied("Settings saved on this machine");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const askAi = async () => {
    if (!review || busyRef.current) return;
    markBusy("Residual analysis…");
    try {
      const r = await api.residual(review);
      setAiNote(r.note);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      markBusy("");
    }
  };

  const runReviewRef = useRef(runReview);
  runReviewRef.current = runReview;
  const tabRef = useRef(tab);
  tabRef.current = tab;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (explorerOpenRef.current) {
        if (event.key === "Escape") {
          event.preventDefault();
          setExplorerOpen(false);
        }
        return;
      }
      const el = event.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) {
        if (event.key === "Escape") (el as HTMLInputElement).blur();
        return;
      }
      if (event.key === "Escape") {
        setError("");
        setCopied("");
        return;
      }
      const hit = TABS.find((item) => item.shortcut === event.key);
      if (hit && !event.metaKey && !event.ctrlKey && !event.altKey) setTab(hit.id);
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        if (tabRef.current === "settings" || tabRef.current === "prs") return;
        if (busyRef.current) return;
        event.preventDefault();
        void runReviewRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const graphNodes = useMemo(() => {
    if (graphMode === "architecture") return architecture?.nodes ?? [];
    return review?.nodes ?? [];
  }, [graphMode, architecture, review]);
  const graphEdges = useMemo(() => {
    if (graphMode === "architecture") return architecture?.edges ?? [];
    return review?.edges ?? [];
  }, [graphMode, architecture, review]);

  const indexLine = review?.index
    ? `${review.index.counts.nodes} nodes · ${review.index.counts.edges} edges`
    : architecture?.indexed
      ? `${architecture.counts.nodes} nodes · ${architecture.counts.edges} edges`
      : "Not indexed";

  const findings = (review?.findings || []).filter((f) => !f.waived);

  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <nav className="rail" data-testid="rail" aria-label="Primary">
        <div className="brand">
          <div className="brand-mark">Loadpath</div>
          <div className="brand-sub">Load-path review</div>
        </div>
        {TABS.map((item) => {
          const Icon = item.icon;
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              data-testid={item.testId}
              className={active ? "nav-item active" : "nav-item"}
              aria-current={active ? "page" : undefined}
              aria-label={item.label}
              onClick={() => setTab(item.id)}
            >
              <Icon />
              <span>{item.label}</span>
            </button>
          );
        })}
        <div className="theme-pick">
          <label htmlFor="theme-select">Theme</label>
          <select
            id="theme-select"
            data-testid="theme-select"
            value={theme}
            onChange={(e) => persistTheme(e.target.value as ThemeId)}
          >
            {THEMES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="rail-foot">
          <div className="muted" role="status">
            {busy || indexLine}
          </div>
          <div className="kbd-hint">
            <kbd>1</kbd>–<kbd>5</kbd> tabs · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> review
          </div>
        </div>
      </nav>
      <div className="main" id="main">
        {busy ? (
          <div className="progress" role="status" aria-live="polite" aria-busy="true">
            <i />
            <span className="sr-only">{busy}</span>
          </div>
        ) : null}
        <header className="topbar" data-testid="topbar">
          {repos.length > 0 ? (
            <label className="field workspace">
              <span>Workspace</span>
              <select
                data-testid="workspace-select"
                value={repos.some((r) => r.path === repo) ? repo : ""}
                onChange={(e) => {
                  if (e.target.value) persistRepo(e.target.value);
                }}
              >
                <option value="">Indexed repos…</option>
                {repos.map((r) => (
                  <option key={r.path} value={r.path}>
                    {r.name}
                    {r.indexed ? ` (${r.counts.nodes})` : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="field path">
            <span>Repository</span>
            <div className="path-row">
              <input
                data-testid="repo-path"
                placeholder="Local monorepo path"
                value={repo}
                onChange={(e) => {
                  const next = e.target.value;
                  setRepo(next);
                  if (next.trim() !== gitRefsPath.current) {
                    gitRefsPath.current = "";
                    setGitRefs(null);
                  }
                }}
                spellCheck={false}
              />
              <button
                type="button"
                className="icon-btn"
                data-testid="btn-browse-repo"
                aria-label="Browse for a local repository"
                onClick={() => setExplorerOpen(true)}
              >
                <IconFolder />
              </button>
            </div>
          </label>
          <label className="field ref">
            <span>Base</span>
            <RefCombobox
              testId="base-ref"
              menuTestId="base-ref-menu"
              value={base}
              onChange={(next) => persistRefs(next, head)}
              placeholder="base"
              refs={gitRefs}
              onNeedRefs={loadGitRefs}
            />
          </label>
          <label className="field ref">
            <span>Head</span>
            <RefCombobox
              testId="head-ref"
              menuTestId="head-ref-menu"
              value={head}
              onChange={(next) => persistRefs(base, next)}
              placeholder="head"
              refs={gitRefs}
              onNeedRefs={loadGitRefs}
            />
          </label>
          <div className="topbar-actions">
            <button type="button" data-testid="btn-init" disabled={!!busy} onClick={draftConfig}>
              Draft config
            </button>
            <button type="button" data-testid="btn-index" disabled={!!busy} onClick={() => runIndex(true)}>
              Index
            </button>
            <button
              type="button"
              data-testid="btn-review"
              className="btn primary"
              disabled={!!busy}
              onClick={runReview}
            >
              Review
            </button>
          </div>
        </header>
        <div className="alerts">
          {error ? (
            <div className="error" data-testid="error" role="alert">
              <span>{error}</span>
              <button type="button" className="dismiss" onClick={() => setError("")} aria-label="Dismiss error">
                ×
              </button>
            </div>
          ) : null}
          {copied ? (
            <div className="banner" data-testid="status-note">
              <span>{copied}</span>
              <button type="button" className="dismiss" onClick={() => setCopied("")} aria-label="Dismiss">
                ×
              </button>
            </div>
          ) : null}
          {(review?.index?.stale || architecture?.stale) && (tab === "review" || tab === "architecture") ? (
            <div className="banner stale" data-testid="index-stale">
              Index is stale — files changed since the last extract. Index again before trusting this walk.
            </div>
          ) : null}
          {(review?.index?.django_boot === "failed" || architecture?.django_boot === "failed") ? (
            <div className="banner warn" data-testid="django-boot-failed">
              {review?.index?.django_boot_detail || architecture?.django_boot_detail || "django.setup() failed"}
            </div>
          ) : null}
          {review?.workspace?.dirty_overlaps_review && tab === "review" ? (
            <div className="banner warn" data-testid="dirty-tree">
              Uncommitted files overlap this review: {(review.workspace.dirty_overlap || []).slice(0, 6).join(", ")}
            </div>
          ) : null}
        </div>

        <div className="stage">
          {tab === "review" && (
            <div className="content" data-testid="review-layout">
              <aside className="brief" data-testid="brief">
                {review ? (
                  <ReviewBrief
                    review={review}
                    findings={findings}
                    aiNote={aiNote}
                    busy={!!busy}
                    onAskAi={askAi}
                    onCopy={copyMarkdown}
                    onPost={postComment}
                  />
                ) : (
                  <div className="empty" data-testid="review-empty">
                    <h2>Trace the force of this diff</h2>
                    <p>The graph is the architecture. The brief is where this change travels — not a hunk list.</p>
                    <ol>
                      <li>Point at a Django + React monorepo, or pick an indexed workspace.</li>
                      <li>
                        Index it. Missing <code>loadpath.yml</code> is drafted from <code>manage.py</code> and{" "}
                        <code>src/features</code>.
                      </li>
                      <li>Review a git range, or open a pull request so base/head become a three-dot merge-base.</li>
                    </ol>
                  </div>
                )}
              </aside>
              <div className="graph-wrap" data-testid="review-graph">
                {review ? <ImpactGraph nodes={review.nodes} edges={review.edges} /> : null}
              </div>
            </div>
          )}

          {tab === "architecture" && (
            <div className="content" data-testid="architecture-panel">
              <aside className="brief" data-testid="architecture-brief">
                {architecture?.indexed ? (
                  <ArchitectureBrief architecture={architecture} busy={!!busy} onReindex={() => runIndex(false)} onReview={runReview} />
                ) : (
                  <p className="muted" data-testid="architecture-empty">
                    Index this repo to build the architecture graph. Review then walks that same graph for a git range —
                    it does not start from a hunk list.
                  </p>
                )}
              </aside>
              <div className="graph-wrap" data-testid="architecture-graph">
                {architecture?.indexed ? (
                  <ImpactGraph nodes={architecture.nodes} edges={architecture.edges} />
                ) : null}
              </div>
            </div>
          )}

          {tab === "graph" && (
            <div className="graph-wrap" data-testid="graph-full" style={{ height: "100%" }}>
              <div className="graph-modes">
                <div className="seg" aria-label="Graph scope">
                  <button
                    type="button"
                    aria-pressed={graphMode === "review"}
                    data-testid="graph-mode-review"
                    className={graphMode === "review" ? "active" : ""}
                    onClick={() => setGraphMode("review")}
                  >
                    This review
                  </button>
                  <button
                    type="button"
                    aria-pressed={graphMode === "architecture"}
                    data-testid="graph-mode-architecture"
                    className={graphMode === "architecture" ? "active" : ""}
                    onClick={() => setGraphMode("architecture")}
                  >
                    Indexed architecture
                  </button>
                </div>
                <div className="legend" aria-hidden="true">
                  <span>
                    <i /> cheap
                  </span>
                  <span>
                    <i className="exp" /> expensive
                  </span>
                  <span>
                    <i className="crit" /> critical
                  </span>
                  <span>
                    <i className="dash" /> inferred
                  </span>
                </div>
              </div>
              {graphNodes.length ? (
                <ImpactGraph nodes={graphNodes} edges={graphEdges} />
              ) : (
                <p className="empty" data-testid="graph-empty">
                  Index the repo or run a review first. Click a node to inspect it.
                </p>
              )}
            </div>
          )}

          {tab === "prs" && (
            <div className="pr-list" data-testid="pr-list">
              <div className="pr-toolbar">
                <label className="field provider">
                  <span>Provider</span>
                  <select
                    data-testid="pr-provider"
                    value={provider}
                    onChange={(e) => persistPr(e.target.value, scmRepo, prNumber)}
                  >
                    <option value="github">GitHub</option>
                    <option value="bitbucket">Bitbucket</option>
                  </select>
                </label>
                <label className="field">
                  <span>Repository</span>
                  <input
                    data-testid="pr-repo"
                    placeholder="owner/repo"
                    value={scmRepo}
                    onChange={(e) => persistPr(provider, e.target.value, prNumber)}
                    spellCheck={false}
                  />
                </label>
                <button type="button" data-testid="btn-list-prs" className="btn" disabled={!!busy} onClick={loadPrs}>
                  List PRs
                </button>
              </div>
              {prs.length === 0 ? (
                <div className="empty" data-testid="pr-empty">
                  <h2>No pull requests loaded</h2>
                  <p>Enter an owner/repo, then list open PRs. Reviewing a PR fills base and head from its SHAs.</p>
                </div>
              ) : (
                prs.map((p) => (
                  <article className="pr" data-testid={`pr-${p.number}`} key={`${p.provider}-${p.number}`}>
                    <h3>
                      #{p.number} {p.title}
                    </h3>
                    <div className="pr-meta muted">
                      <span className={`chip ${p.draft ? "" : "open"}`}>{p.draft ? "draft" : p.state}</span>
                      <span>{p.author}</span>
                      <span>
                        {p.source_branch} → {p.target_branch}
                      </span>
                    </div>
                    <div className="pr-actions">
                      <a href={p.url} target="_blank" rel="noreferrer">
                        Open on {p.provider}
                      </a>
                      <button
                        type="button"
                        className="btn primary"
                        data-testid={`pr-review-${p.number}`}
                        onClick={() => {
                          persistRefs(p.base_sha || p.target_branch, p.head_sha || p.source_branch);
                          persistPr(p.provider, p.repo, String(p.number));
                          setTab("review");
                        }}
                      >
                        Review this range
                      </button>
                    </div>
                  </article>
                ))
              )}
            </div>
          )}

          {tab === "settings" && settingsReady && (
            <form className="settings" data-testid="settings-form" onSubmit={saveSettings}>
              <div>
                <h1>Settings</h1>
                <p className="muted">
                  Tokens stay on this machine in ~/.loadpath/settings.json. AI runs only on residual uncertainty the
                  graph could not close.
                </p>
              </div>
              <section className="settings-card">
                <h2>Appearance</h2>
                <p className="muted">Local to this browser. High contrast is a first-class theme, not an afterthought.</p>
                <div className="theme-grid" data-testid="theme-grid">
                  {THEMES.map((t) => (
                    <button
                      type="button"
                      key={t.id}
                      className={theme === t.id ? "theme-swatch active" : "theme-swatch"}
                      data-testid={`theme-${t.id}`}
                      onClick={() => persistTheme(t.id)}
                    >
                      <div className="name">{t.label}</div>
                      <div className="group">{t.group}</div>
                    </button>
                  ))}
                </div>
              </section>
              <section className="settings-card">
                <h2>Source control</h2>
                <label htmlFor="github_token">GitHub token</label>
                <input id="github_token" name="github_token" type="password" placeholder="ghp_…" autoComplete="off" />
                <label htmlFor="bitbucket_token">Bitbucket token</label>
                <input id="bitbucket_token" name="bitbucket_token" type="password" autoComplete="off" />
                <label htmlFor="bitbucket_username">Bitbucket username (app passwords)</label>
                <input
                  id="bitbucket_username"
                  name="bitbucket_username"
                  defaultValue={String(settings.bitbucket_username || "")}
                />
              </section>
              <section className="settings-card">
                <h2>Residual AI</h2>
                <label htmlFor="ai_provider">Provider</label>
                <select
                  id="ai_provider"
                  name="ai_provider"
                  defaultValue={String((settings.ai as { provider?: string } | undefined)?.provider || "none")}
                >
                  <option value="none">none (graph only)</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                  <option value="grok">Grok / xAI</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="cursor">Cursor-compatible (OpenAI protocol)</option>
                  <option value="ollama">Ollama local</option>
                </select>
                <label htmlFor="ai_api_key">API key</label>
                <input id="ai_api_key" name="ai_api_key" type="password" autoComplete="off" />
                <label htmlFor="ai_model">Model</label>
                <input
                  id="ai_model"
                  name="ai_model"
                  data-testid="ai-model"
                  placeholder="optional override"
                  defaultValue={String((settings.ai as { model?: string } | undefined)?.model || "")}
                />
                <label htmlFor="ai_base_url">Base URL</label>
                <input
                  id="ai_base_url"
                  name="ai_base_url"
                  data-testid="ai-base-url"
                  placeholder="optional, OpenAI-compatible"
                  defaultValue={String((settings.ai as { base_url?: string } | undefined)?.base_url || "")}
                />
                <button className="btn primary" type="submit" data-testid="btn-save-settings">
                  Save
                </button>
              </section>
            </form>
          )}
        </div>
      </div>
      {explorerOpen ? (
        <RepoExplorer
          initialPath={repo}
          onClose={() => setExplorerOpen(false)}
          onSelect={(path) => {
            persistRepo(path);
            setExplorerOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function ReviewBrief({
  review,
  findings,
  aiNote,
  busy,
  onAskAi,
  onCopy,
  onPost,
}: {
  review: Review;
  findings: Review["findings"];
  aiNote: string;
  busy: boolean;
  onAskAi: () => void;
  onCopy: () => void;
  onPost: () => void;
}) {
  const uniqueReasons = [...new Set(review.confidence.reasons || [])];
  return (
    <>
      <div className={`merge-box ${review.confidence.level}`}>
        <div className={`level ${review.confidence.level}`}>
          {review.confidence.level.toUpperCase()} — {review.title}
        </div>
        {uniqueReasons.length ? (
          <ul className="reasons">
            {uniqueReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
        {review.low_risk ? <span className="chip">low-risk</span> : null}
        {review.change_kinds.map((k) => (
          <span className="chip" key={k}>
            {kindLabel(k)}
          </span>
        ))}
      </div>
      <div className="metrics">
        <div className="metric">
          <div className="n">
            {review.confidence.covered_sinks}/{review.confidence.sinks}
          </div>
          <div className="l">Sinks tested</div>
        </div>
        <div className="metric">
          <div className="n">{findings.length}</div>
          <div className="l">Findings</div>
        </div>
        <div className="metric">
          <div className="n">{review.residuals.length}</div>
          <div className="l">Residuals</div>
        </div>
      </div>
      <pre className="headline">{review.headline}</pre>
      {review.index ? (
        <details className="section" open>
          <summary>
            Index <span className="count">{review.index.counts.nodes}</span>
          </summary>
          <div className="muted">
            Walked {review.index.counts.nodes} nodes / {review.index.counts.edges} edges
            {review.index.reindex_skipped
              ? " from an unchanged index"
              : review.index.reindexed
                ? " after an incremental refresh"
                : " from the existing index"}
            {review.index.django_boot && review.index.django_boot !== "off"
              ? ` · Django boot ${review.index.django_boot}`
              : ""}
            {review.workspace?.three_dot ? " · three-dot range" : ""}
          </div>
        </details>
      ) : null}
      <details className="section" open>
        <summary>
          Read this <span className="count">{review.read_order.length}</span>
        </summary>
        {review.read_order.map((f, i) => (
          <div key={f.path} className="read-item">
            <span className="file">
              {i + 1}. {f.path}
            </span>
            <div className="why">{f.why}</div>
          </div>
        ))}
      </details>
      <details className="section">
        <summary>
          Clusters <span className="count">{review.clusters.length}</span>
        </summary>
        {review.clusters.map((c) => (
          <div key={c.id} className="muted">
            <strong>{c.title}</strong> — {c.files.join(", ")}
          </div>
        ))}
      </details>
      <details className="section" open>
        <summary>
          Architecture <span className="count">{findings.length}</span>
        </summary>
        {findings.length === 0 ? (
          <div className="muted">{review.architecture_note}</div>
        ) : (
          findings.map((f) => (
            <div key={f.rule + f.message} className="finding">
              <span className={`chip ${f.severity}`}>{f.severity}</span>
              {f.message}
            </div>
          ))
        )}
      </details>
      <DeepeningList cards={review.deepening} />
      <details className="section" open>
        <summary>
          Residual <span className="count">{review.residuals.length}</span>
        </summary>
        <p className="muted">AI is only used here, on what the graph could not close.</p>
        {review.residuals.map((r) => (
          <div key={r} className="residual muted">
            {r}
          </div>
        ))}
      </details>
      {(review.evolution?.notes?.length || review.evolution?.hotspots?.some((h) => h.commits)) ? (
        <details className="section">
          <summary>Churn & coupling</summary>
          {(review.evolution?.notes || []).map((note) => (
            <div key={note} className="muted">
              {note}
            </div>
          ))}
          {(review.evolution?.hotspots || [])
            .filter((h) => h.commits)
            .slice(0, 6)
            .map((h) => (
              <div key={h.path} className="muted">
                <span className="file">{h.path}</span> — {h.commits} commits, bus factor {h.bus_factor}
              </div>
            ))}
        </details>
      ) : null}
      <div className="btn-row">
        <button type="button" className="btn" disabled={busy} onClick={onAskAi}>
          Ask configured model
        </button>
        <button type="button" className="btn" data-testid="btn-copy-markdown" onClick={onCopy}>
          Copy markdown
        </button>
        <button type="button" className="btn" data-testid="btn-post-comment" onClick={onPost}>
          Post to PR
        </button>
      </div>
      {aiNote ? <pre className="headline">{aiNote}</pre> : null}
      <div className="kicker">Reviewers</div>
      <div className="muted">{review.suggested_reviewers.join(", ") || "—"}</div>
      {review.knowledge_owners?.length ? (
        <div className="muted">Knowledge: {review.knowledge_owners.join(", ")}</div>
      ) : null}
    </>
  );
}

function ArchitectureBrief({
  architecture,
  busy,
  onReindex,
  onReview,
}: {
  architecture: ArchitectureReport;
  busy: boolean;
  onReindex: () => void;
  onReview: () => void;
}) {
  const hits = architecture.findings.filter((f) => !f.waived);
  return (
    <>
      <div className="merge-box high">
        <div className="level high">INDEXED — {architecture.counts.nodes} nodes</div>
        <div className="muted" style={{ marginTop: 8 }}>
          {architecture.indexed_at ? `Last index ${formatWhen(architecture.indexed_at)}` : "Indexed"}
          {architecture.incremental ? " · incremental" : " · full"}
          {architecture.stale ? " · stale" : ""}
          {architecture.django_boot && architecture.django_boot !== "off"
            ? ` · Django boot ${architecture.django_boot}`
            : ""}
        </div>
        <span className="chip">{architecture.counts.edges} edges</span>
        {architecture.has_config ? <span className="chip">loadpath.yml</span> : null}
      </div>
      <details className="section" open>
        <summary>Bounded contexts</summary>
        {Object.values(architecture.contexts).map((ctx) => (
          <div key={ctx.name} className="muted">
            <strong>{ctx.name}</strong> — {(ctx.django_apps || []).join(", ") || "no apps"} ·{" "}
            {(ctx.owners || []).join(", ") || "unowned"}
          </div>
        ))}
      </details>
      <details className="section">
        <summary>
          Rules <span className="count">{(architecture.rules || []).length}</span>
        </summary>
        {(architecture.rules || []).map((rule) => (
          <div key={rule} className="muted">
            {rule}
          </div>
        ))}
      </details>
      <details className="section" open>
        <summary>
          Findings <span className="count">{hits.length}</span>
        </summary>
        {hits.length === 0 ? (
          <div className="muted">No architecture rule hits on the full graph.</div>
        ) : (
          hits.map((f) => (
            <div key={f.rule + f.message} className="finding">
              <span className={`chip ${f.severity}`}>{f.severity}</span>
              {f.message}
            </div>
          ))
        )}
      </details>
      <DeepeningList cards={architecture.deepening} />
      <details className="section" open>
        <summary>Types</summary>
        <table className="type-table">
          <tbody>
            {Object.entries(architecture.type_counts || {})
              .sort((a, b) => b[1] - a[1])
              .slice(0, 12)
              .map(([t, n]) => (
                <tr key={t}>
                  <td>{typeLabel(t)}</td>
                  <td>{n}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
      <div className="btn-row">
        <button type="button" className="btn" disabled={busy} onClick={onReindex} data-testid="btn-full-reindex">
          Full reindex
        </button>
        <button type="button" className="btn primary" disabled={busy} onClick={onReview}>
          Review against this index
        </button>
      </div>
    </>
  );
}

function DeepeningList({ cards }: { cards?: DeepeningCandidate[] }) {
  const list = cards || [];
  if (!list.length) return null;
  return (
    <details className="section" open data-testid="deepening-list">
      <summary>
        Depth <span className="count">{list.length}</span>
      </summary>
      <p className="muted">Deepening opportunities: more behaviour behind a smaller interface, at a real seam.</p>
      {list.map((card) => (
        <div key={card.rule + card.title} className="finding" data-testid="deepening-card">
          <span className={`chip ${card.strength}`}>{strengthLabel(card.strength)}</span>
          {card.top ? <span className="chip">top</span> : null}
          <strong>{card.title}</strong>
          <div className="why">{card.message}</div>
          {card.deletion_test ? <div className="muted">Deletion test: {card.deletion_test}</div> : null}
          {card.before && card.after ? (
            <div className="muted">
              {card.before} → {card.after}
            </div>
          ) : null}
        </div>
      ))}
    </details>
  );
}
