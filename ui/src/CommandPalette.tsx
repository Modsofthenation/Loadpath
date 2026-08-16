import { useEffect, useMemo, useRef, useState } from "react";

export type PaletteAction = {
  id: string;
  label: string;
  hint?: string;
  group?: string;
  run: () => void;
};

export function filterActions(actions: PaletteAction[], query: string): PaletteAction[] {
  const q = query.trim().toLowerCase();
  if (!q) return actions;
  return actions.filter(
    (a) =>
      a.label.toLowerCase().includes(q) ||
      (a.hint || "").toLowerCase().includes(q) ||
      (a.group || "").toLowerCase().includes(q),
  );
}

export function CommandPalette({
  open,
  actions,
  onClose,
}: {
  open: boolean;
  actions: PaletteAction[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const hits = useMemo(() => filterActions(actions, query), [actions, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setIndex(0);
    const t = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    setIndex(0);
  }, [query]);

  if (!open) return null;
  const shown = hits.slice(0, 40);
  const current = shown[Math.min(index, Math.max(shown.length - 1, 0))];

  const run = (action?: PaletteAction) => {
    if (!action) return;
    onClose();
    action.run();
  };

  return (
    <div
      className="palette-scrim"
      data-testid="command-palette"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-label="Command palette">
        <input
          ref={inputRef}
          data-testid="command-palette-input"
          placeholder="Jump to a node, run a review, toggle overlays…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setIndex((i) => Math.min(Math.max(shown.length - 1, 0), i + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setIndex((i) => Math.max(0, i - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              run(current);
            }
          }}
        />
        <ul>
          {shown.length === 0 ? <li className="muted">No matches</li> : null}
          {shown.map((action, i) => (
            <li key={action.id}>
              <button
                type="button"
                className={i === index ? "active" : ""}
                onMouseEnter={() => setIndex(i)}
                onClick={() => run(action)}
              >
                <span>{action.label}</span>
                {action.hint ? <span className="muted">{action.hint}</span> : null}
              </button>
            </li>
          ))}
        </ul>
        <div className="palette-foot muted">
          <kbd>↑</kbd>
          <kbd>↓</kbd> move · <kbd>Enter</kbd> run · <kbd>Esc</kbd> close
        </div>
      </div>
    </div>
  );
}
