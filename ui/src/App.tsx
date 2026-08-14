import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { ImpactGraph } from "./ImpactGraph";
import { THEMES, applyTheme, readTheme, type ThemeId } from "./themes";
import type { ArchitectureReport, IndexedRepo, PullRequest, Review } from "./types";

type Tab = "review" | "architecture" | "graph" | "prs" | "settings";
type GraphMode = "review" | "architecture";

export function App() {
  const [tab, setTab] = useState<Tab>("review");
  const [repo, setRepo] = useState(localStorage.getItem("loadpath.repo") || "");
  const [base, setBase] = useState("HEAD~1");
  const [head, setHead] = useState("HEAD");
  const [review, setReview] = useState<Review | null>(null);
  const [architecture, setArchitecture] = useState<ArchitectureReport | null>(null);
  const [repos, setRepos] = useState<IndexedRepo[]>([]);
  const [graphMode, setGraphMode] = useState<GraphMode>("review");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [prs, setPrs] = useState<PullRequest[]>([]);
  const [scmRepo, setScmRepo] = useState("");
  const [provider, setProvider] = useState("github");
  const [aiNote, setAiNote] = useState("");
  const [theme, setTheme] = useState<ThemeId>(readTheme);
  const repoRef = useRef(repo);
  repoRef.current = repo;

  const persistTheme = (id: ThemeId) => {
    setTheme(id);
    applyTheme(id);
  };

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined);
    api.repos().then((r) => setRepos(r.repos)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (tab !== "architecture" || !repo) return;
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
  };

  const loadArchitecture = async (path = repo) => {
    if (!path) return null;
    const report = await api.architecture(path);
    if (repoRef.current === path) setArchitecture(report);
    return report;
  };

  const runReview = async () => {
    setError("");
    setBusy("Tracing load path…");
    persistRepo(repo);
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
      setBusy("");
    }
  };

  const runIndex = async (incremental = true) => {
    setError("");
    setBusy(incremental ? "Indexing…" : "Full reindex…");
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
      setBusy("");
    }
  };

  const loadPrs = async () => {
    setError("");
    setBusy("Fetching pull requests…");
    try {
      const r = await api.prs(provider, scmRepo);
      setPrs(r.pull_requests);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const saveSettings = async (evt: React.FormEvent<HTMLFormElement>) => {
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
      workspaces: repos.length
        ? repos.map((r) => ({ path: r.path, name: r.name }))
        : repo
          ? [{ path: repo, name: repo.split(/[\\/]/).pop() }]
          : [],
    };
    setSettings(await api.saveSettings(body));
  };

  const askAi = async () => {
    if (!review) return;
    setBusy("Residual analysis…");
    try {
      const r = await api.residual(review);
      setAiNote(r.note);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const graphNodes = useMemo(() => {
    if (graphMode === "architecture") return architecture?.nodes ?? [];
    return review?.nodes ?? [];
  }, [graphMode, architecture, review]);
  const graphEdges = useMemo(() => {
    if (graphMode === "architecture") return architecture?.edges ?? [];
    return review?.edges ?? [];
  }, [graphMode, architecture, review]);

  const indexLine = review?.index
    ? `${review.index.counts.nodes} nodes / ${review.index.counts.edges} edges · ${review.index.incremental ? "incremental" : "full"}`
    : architecture?.indexed
      ? `${architecture.counts.nodes} nodes / ${architecture.counts.edges} edges indexed`
      : "Not indexed";

  return (
    <div className="app">
      <nav className="rail" data-testid="rail">
        <div className="brand">Loadpath</div>
        <button data-testid="tab-review" className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>
          Review
        </button>
        <button
          data-testid="tab-architecture"
          className={tab === "architecture" ? "active" : ""}
          onClick={() => setTab("architecture")}
        >
          Architecture
        </button>
        <button data-testid="tab-graph" className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>
          Impact graph
        </button>
        <button data-testid="tab-prs" className={tab === "prs" ? "active" : ""} onClick={() => setTab("prs")}>
          Pull requests
        </button>
        <button data-testid="tab-settings" className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
          Settings
        </button>
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
        <div style={{ flex: 1 }} />
        <div className="muted">{busy || indexLine}</div>
      </nav>
      <div className="main">
        <div className="topbar" data-testid="topbar">
          {repos.length > 0 ? (
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
          ) : null}
          <input
            data-testid="repo-path"
            className="path"
            placeholder="Local monorepo path"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
          />
          <input data-testid="base-ref" value={base} onChange={(e) => setBase(e.target.value)} placeholder="base" />
          <input data-testid="head-ref" value={head} onChange={(e) => setHead(e.target.value)} placeholder="head" />
          <button data-testid="btn-index" onClick={() => runIndex(true)}>
            Index
          </button>
          <button data-testid="btn-review" className="btn primary" onClick={runReview}>
            Review
          </button>
        </div>
        {error ? <div className="error">{error}</div> : null}

        {tab === "review" && (
          <div className="content" data-testid="review-layout">
            <aside className="brief" data-testid="brief">
              {review ? (
                <>
                  <div className={`level ${review.confidence.level}`}>
                    {review.confidence.level.toUpperCase()} — {review.title}
                  </div>
                  {review.low_risk ? <span className="chip">loadpath:low-risk</span> : null}
                  {review.change_kinds.map((k) => (
                    <span className="chip" key={k}>
                      {k.replaceAll("_", " ")}
                    </span>
                  ))}
                  <pre className="headline">{review.headline}</pre>
                  {review.index ? (
                    <>
                      <div className="kicker">Index</div>
                      <div className="muted">
                        Walked {review.index.counts.nodes} nodes / {review.index.counts.edges} edges
                        {review.index.reindexed ? " after an incremental refresh" : " from the existing index"}.
                      </div>
                    </>
                  ) : null}
                  <div className="kicker">Read this</div>
                  {review.read_order.map((f) => (
                    <div key={f.path}>
                      <span className="file">{f.path}</span>
                      <div className="muted">{f.why}</div>
                    </div>
                  ))}
                  <div className="kicker">Clusters</div>
                  {review.clusters.map((c) => (
                    <div key={c.id} className="muted">
                      <strong>{c.title}</strong> — {c.files.join(", ")}
                    </div>
                  ))}
                  <div className="kicker">Architecture</div>
                  {review.findings.filter((f) => !f.waived).length === 0 ? (
                    <div className="muted">{review.architecture_note}</div>
                  ) : (
                    review.findings
                      .filter((f) => !f.waived)
                      .map((f) => (
                        <div key={f.rule + f.message} className="muted">
                          <span className={`chip ${f.severity}`}>{f.severity}</span>
                          {f.message}
                        </div>
                      ))
                  )}
                  <div className="kicker">Residual (AI only here)</div>
                  {review.residuals.map((r) => (
                    <div key={r} className="muted">
                      {r}
                    </div>
                  ))}
                  {(review.evolution?.notes?.length || review.evolution?.hotspots?.some((h) => h.commits)) ? (
                    <>
                      <div className="kicker">Churn & coupling</div>
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
                    </>
                  ) : null}
                  <button className="btn" onClick={askAi} style={{ marginTop: 12 }}>
                    Ask configured model
                  </button>
                  {aiNote ? <pre className="headline">{aiNote}</pre> : null}
                  <div className="kicker">Reviewers</div>
                  <div className="muted">{review.suggested_reviewers.join(", ") || "—"}</div>
                </>
              ) : (
                <p className="muted">
                  Index a Django + React monorepo with <code>loadpath.yml</code>, inspect architecture, then review a
                  git range against that graph.
                </p>
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
                <>
                  <div className="level high">INDEXED — {architecture.counts.nodes} nodes</div>
                  <span className="chip">
                    {architecture.counts.edges} edges
                  </span>
                  {architecture.has_config ? <span className="chip">loadpath.yml</span> : null}
                  <div className="muted" style={{ marginTop: 8 }}>
                    {architecture.indexed_at ? `Last index ${architecture.indexed_at}` : "Indexed"}
                    {architecture.incremental ? " · incremental" : " · full"}
                  </div>
                  <div className="kicker">Bounded contexts</div>
                  {Object.values(architecture.contexts).map((ctx) => (
                    <div key={ctx.name} className="muted">
                      <strong>{ctx.name}</strong> — {(ctx.django_apps || []).join(", ") || "no apps"} ·{" "}
                      {(ctx.owners || []).join(", ") || "unowned"}
                    </div>
                  ))}
                  <div className="kicker">Rules</div>
                  {(architecture.rules || []).map((rule) => (
                    <div key={rule} className="muted">
                      {rule}
                    </div>
                  ))}
                  <div className="kicker">Findings on the indexed graph</div>
                  {architecture.findings.filter((f) => !f.waived).length === 0 ? (
                    <div className="muted">No architecture rule hits on the full graph.</div>
                  ) : (
                    architecture.findings
                      .filter((f) => !f.waived)
                      .map((f) => (
                        <div key={f.rule + f.message} className="muted">
                          <span className={`chip ${f.severity}`}>{f.severity}</span>
                          {f.message}
                        </div>
                      ))
                  )}
                  <div className="kicker">Types</div>
                  <div className="muted">
                    {Object.entries(architecture.type_counts || {})
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 12)
                      .map(([t, n]) => `${t.split(".").pop()} ${n}`)
                      .join(" · ")}
                  </div>
                  <button className="btn" style={{ marginTop: 12 }} onClick={() => runIndex(false)} data-testid="btn-full-reindex">
                    Full reindex
                  </button>
                  <button className="btn primary" style={{ marginTop: 8 }} onClick={runReview}>
                    Review against this index
                  </button>
                </>
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
          <div className="graph-wrap" data-testid="graph-full" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
            <div className="graph-modes">
              <button
                data-testid="graph-mode-review"
                className={graphMode === "review" ? "active" : ""}
                onClick={() => setGraphMode("review")}
              >
                This review
              </button>
              <button
                data-testid="graph-mode-architecture"
                className={graphMode === "architecture" ? "active" : ""}
                onClick={() => setGraphMode("architecture")}
              >
                Indexed architecture
              </button>
            </div>
            {graphNodes.length ? (
              <div style={{ flex: 1, minHeight: 0 }}>
                <ImpactGraph nodes={graphNodes} edges={graphEdges} />
              </div>
            ) : (
              <p className="muted">Index the repo or run a review first.</p>
            )}
          </div>
        )}

        {tab === "prs" && (
          <div className="pr-list" data-testid="pr-list">
            <div className="topbar" style={{ border: 0, padding: 0, marginBottom: 12 }}>
              <select data-testid="pr-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="github">GitHub</option>
                <option value="bitbucket">Bitbucket</option>
              </select>
              <input
                data-testid="pr-repo"
                className="path"
                placeholder="owner/repo"
                value={scmRepo}
                onChange={(e) => setScmRepo(e.target.value)}
              />
              <button data-testid="btn-list-prs" onClick={loadPrs}>
                List PRs
              </button>
            </div>
            {prs.map((p) => (
              <article className="pr" data-testid={`pr-${p.number}`} key={`${p.provider}-${p.number}`}>
                <h3>
                  #{p.number} {p.title}
                </h3>
                <div className="muted">
                  {p.author} · {p.source_branch} → {p.target_branch} · {p.provider}
                </div>
                <a href={p.url} target="_blank" rel="noreferrer">
                  Open on {p.provider}
                </a>
                <div>
                  <button
                    className="btn"
                    onClick={() => {
                      setBase(p.target_branch);
                      setHead(p.source_branch);
                      setTab("review");
                    }}
                  >
                    Review this branch range
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        {tab === "settings" && (
          <form className="settings" data-testid="settings-form" onSubmit={saveSettings}>
            <h1>Keys & providers</h1>
            <p className="muted">
              Tokens stay on this machine in ~/.loadpath/settings.json. GitHub and Bitbucket power the PR list. Indexed
              repos are remembered as workspaces. AI is used only for residual uncertainty the graph could not close.
            </p>
            <h1>Theme</h1>
            <p className="muted">Appearance is local to this browser. Pick a palette that matches how you review.</p>
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
            <label>GitHub token</label>
            <input name="github_token" type="password" placeholder="ghp_…" />
            <label>Bitbucket token</label>
            <input name="bitbucket_token" type="password" />
            <label>Bitbucket username (app passwords)</label>
            <input name="bitbucket_username" defaultValue={String(settings.bitbucket_username || "")} />
            <label>AI provider</label>
            <select name="ai_provider" defaultValue={String((settings.ai as { provider?: string } | undefined)?.provider || "none")}>
              <option value="none">none (graph only)</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="grok">Grok / xAI</option>
              <option value="deepseek">DeepSeek</option>
              <option value="cursor">Cursor-compatible (OpenAI protocol)</option>
              <option value="ollama">Ollama local</option>
            </select>
            <label>AI API key</label>
            <input name="ai_api_key" type="password" />
            <label>Model</label>
            <input name="ai_model" placeholder="optional override" />
            <label>Base URL</label>
            <input name="ai_base_url" placeholder="optional, OpenAI-compatible" />
            <button className="btn primary" type="submit">
              Save
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
