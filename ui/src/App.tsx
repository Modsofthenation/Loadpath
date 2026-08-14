import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { ImpactGraph } from "./ImpactGraph";
import type { PullRequest, Review } from "./types";

type Tab = "review" | "prs" | "graph" | "settings";

export function App() {
  const [tab, setTab] = useState<Tab>("review");
  const [repo, setRepo] = useState(localStorage.getItem("loadpath.repo") || "");
  const [base, setBase] = useState("HEAD~1");
  const [head, setHead] = useState("HEAD");
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [prs, setPrs] = useState<PullRequest[]>([]);
  const [scmRepo, setScmRepo] = useState("");
  const [provider, setProvider] = useState("github");
  const [aiNote, setAiNote] = useState("");

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined);
  }, []);

  const runReview = async () => {
    setError("");
    setBusy("Tracing load path…");
    localStorage.setItem("loadpath.repo", repo);
    try {
      const r = await api.review(repo, base, head);
      setReview(r);
      setTab("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const runIndex = async () => {
    setError("");
    setBusy("Indexing…");
    try {
      await api.index(repo);
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
      workspaces: repo ? [{ path: repo, name: repo.split(/[\\/]/).pop() }] : [],
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

  const graphNodes = useMemo(() => review?.nodes ?? [], [review]);
  const graphEdges = useMemo(() => review?.edges ?? [], [review]);

  return (
    <div className="app">
      <nav className="rail">
        <div className="brand">Loadpath</div>
        <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>
          Review
        </button>
        <button className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>
          Impact graph
        </button>
        <button className={tab === "prs" ? "active" : ""} onClick={() => setTab("prs")}>
          Pull requests
        </button>
        <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
          Settings
        </button>
        <div style={{ flex: 1 }} />
        <div className="muted">{busy || "Django + React load paths"}</div>
      </nav>
      <div className="main">
        <div className="topbar">
          <input
            className="path"
            placeholder="Local monorepo path"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
          />
          <input value={base} onChange={(e) => setBase(e.target.value)} placeholder="base" />
          <input value={head} onChange={(e) => setHead(e.target.value)} placeholder="head" />
          <button onClick={runIndex}>Index</button>
          <button className="btn primary" onClick={runReview}>
            Review
          </button>
        </div>
        {error ? <div className="error">{error}</div> : null}

        {tab === "review" && (
          <div className="content">
            <aside className="brief">
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
                  <button className="btn" onClick={askAi} style={{ marginTop: 12 }}>
                    Ask configured model
                  </button>
                  {aiNote ? <pre className="headline">{aiNote}</pre> : null}
                  <div className="kicker">Reviewers</div>
                  <div className="muted">{review.suggested_reviewers.join(", ") || "—"}</div>
                </>
              ) : (
                <p className="muted">
                  Point at a Django + React monorepo with <code>loadpath.yml</code>, then review a git
                  range. The graph — not hunk comments — is the artifact.
                </p>
              )}
            </aside>
            <div className="graph-wrap">
              {review ? <ImpactGraph nodes={graphNodes} edges={graphEdges} /> : null}
            </div>
          </div>
        )}

        {tab === "graph" && (
          <div className="graph-wrap" style={{ height: "100%" }}>
            {review ? <ImpactGraph nodes={graphNodes} edges={graphEdges} /> : <p className="muted">Run a review first.</p>}
          </div>
        )}

        {tab === "prs" && (
          <div className="pr-list">
            <div className="topbar" style={{ border: 0, padding: 0, marginBottom: 12 }}>
              <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="github">GitHub</option>
                <option value="bitbucket">Bitbucket</option>
              </select>
              <input
                className="path"
                placeholder="owner/repo"
                value={scmRepo}
                onChange={(e) => setScmRepo(e.target.value)}
              />
              <button onClick={loadPrs}>List PRs</button>
            </div>
            {prs.map((p) => (
              <article className="pr" key={`${p.provider}-${p.number}`}>
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
          <form className="settings" onSubmit={saveSettings}>
            <h1>Keys & providers</h1>
            <p className="muted">
              Tokens stay on this machine in ~/.loadpath/settings.json. GitHub and Bitbucket power the
              PR list. AI is used only for residual uncertainty the graph could not close.
            </p>
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
