import { useEffect, useState } from "react";
import type { LoadpathConfigDoc } from "./types";

export function ConfigEditor({
  config,
  busy,
  onSave,
  onWaiver,
}: {
  config: LoadpathConfigDoc;
  busy: boolean;
  onSave: (next: LoadpathConfigDoc) => void;
  onWaiver?: (rule: string, node: string, reason: string) => void;
}) {
  const [draft, setDraft] = useState(config);
  const [waiverRule, setWaiverRule] = useState(config.available_rules[0] || "");
  const [waiverNode, setWaiverNode] = useState("");
  const [waiverReason, setWaiverReason] = useState("");

  useEffect(() => {
    setDraft(config);
  }, [config]);

  const contexts = Object.entries(draft.contexts || {});

  const updateContext = (name: string, field: string, value: string) => {
    const ctx = draft.contexts[name];
    if (!ctx) return;
    const split = (raw: string) =>
      raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    setDraft({
      ...draft,
      contexts: {
        ...draft.contexts,
        [name]: {
          ...ctx,
          [field]: field === "name" ? value : split(value),
        },
      },
    });
  };

  const renameContext = (from: string, to: string) => {
    const nextName = to.trim();
    if (!nextName || nextName === from) return;
    const { [from]: current, ...rest } = draft.contexts;
    if (!current) return;
    setDraft({
      ...draft,
      contexts: { ...rest, [nextName]: { ...current, name: nextName } },
    });
  };

  const addContext = () => {
    let n = 1;
    while (draft.contexts[`context-${n}`]) n += 1;
    const name = `context-${n}`;
    setDraft({
      ...draft,
      contexts: {
        ...draft.contexts,
        [name]: { name, django_apps: [], react: [], public_api: [], owners: [] },
      },
    });
  };

  const removeContext = (name: string) => {
    const { [name]: _drop, ...rest } = draft.contexts;
    setDraft({ ...draft, contexts: rest });
  };

  const toggleRule = (rule: string) => {
    const on = draft.rules.includes(rule);
    setDraft({
      ...draft,
      rules: on ? draft.rules.filter((r) => r !== rule) : [...draft.rules, rule],
    });
  };

  return (
    <div className="config-editor" data-testid="config-editor">
      <p className="muted">
        {draft.exists ? draft.path : "No loadpath.yml yet — saving writes one at the repo root."}
      </p>
      {contexts.map(([name, ctx]) => (
        <details key={name} className="section" open>
          <summary>
            Context <span className="count">{name}</span>
          </summary>
          <label className="field">
            <span>Name</span>
            <input
              defaultValue={name}
              data-testid={`config-context-name-${name}`}
              onBlur={(e) => renameContext(name, e.target.value)}
            />
          </label>
          <label className="field">
            <span>Django apps</span>
            <input
              value={(ctx.django_apps || []).join(", ")}
              onChange={(e) => updateContext(name, "django_apps", e.target.value)}
            />
          </label>
          <label className="field">
            <span>React folders</span>
            <input value={(ctx.react || []).join(", ")} onChange={(e) => updateContext(name, "react", e.target.value)} />
          </label>
          <label className="field">
            <span>Public API</span>
            <input
              value={(ctx.public_api || []).join(", ")}
              onChange={(e) => updateContext(name, "public_api", e.target.value)}
            />
          </label>
          <label className="field">
            <span>Owners</span>
            <input
              value={(ctx.owners || []).join(", ")}
              onChange={(e) => updateContext(name, "owners", e.target.value)}
            />
          </label>
          <button type="button" className="btn" onClick={() => removeContext(name)}>
            Remove context
          </button>
        </details>
      ))}
      <div className="btn-row">
        <button type="button" className="btn" data-testid="config-add-context" onClick={addContext}>
          Add context
        </button>
      </div>
      <details className="section">
        <summary>
          Rules <span className="count">{draft.rules.length}</span>
        </summary>
        {(draft.available_rules.length ? draft.available_rules : draft.rules).map((rule) => (
          <label key={rule} className="check-row">
            <input type="checkbox" checked={draft.rules.includes(rule)} onChange={() => toggleRule(rule)} />
            {rule}
          </label>
        ))}
      </details>
      <details className="section" open>
        <summary>
          Waivers <span className="count">{(draft.waivers || []).length}</span>
        </summary>
        {(draft.waivers || []).map((w, i) => (
          <div key={`${w.rule}:${w.node}:${i}`} className="muted">
            <strong>{w.rule}</strong>
            {w.node ? ` · ${w.node}` : ""}
            {w.reason ? ` — ${w.reason}` : ""}
          </div>
        ))}
        <label className="field">
          <span>Rule</span>
          <select value={waiverRule} onChange={(e) => setWaiverRule(e.target.value)}>
            {(draft.available_rules.length ? draft.available_rules : draft.rules).map((rule) => (
              <option key={rule} value={rule}>
                {rule}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Node id (optional)</span>
          <input value={waiverNode} onChange={(e) => setWaiverNode(e.target.value)} placeholder="django.view:…" />
        </label>
        <label className="field">
          <span>Reason</span>
          <input value={waiverReason} onChange={(e) => setWaiverReason(e.target.value)} />
        </label>
        <button
          type="button"
          className="btn"
          data-testid="config-add-waiver"
          disabled={busy || !waiverRule}
          onClick={() => onWaiver?.(waiverRule, waiverNode, waiverReason)}
        >
          Add waiver
        </button>
      </details>
      <div className="btn-row">
        <button
          type="button"
          className="btn primary"
          data-testid="config-save"
          disabled={busy}
          onClick={() => onSave(draft)}
        >
          Save loadpath.yml
        </button>
      </div>
    </div>
  );
}
