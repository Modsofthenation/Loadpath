import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api } from "./api";
import { IconFolder } from "./icons";
import type { FsListing } from "./types";

export function RepoExplorer({
  initialPath,
  onSelect,
  onClose,
}: {
  initialPath: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const [listing, setListing] = useState<FsListing | null>(null);
  const [pathDraft, setPathDraft] = useState(initialPath);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pathRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef(0);

  const load = async (path: string) => {
    const request = requestRef.current + 1;
    requestRef.current = request;
    setBusy(true);
    try {
      const data = await api.browse(path);
      if (requestRef.current !== request) return;
      setListing(data);
      setPathDraft(data.path);
      setSelected(data.is_git ? data.path : null);
      setError("");
    } catch (e) {
      if (requestRef.current !== request) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (requestRef.current === request) setBusy(false);
    }
  };

  useEffect(() => {
    void load(initialPath);
    pathRef.current?.focus();
    pathRef.current?.select();
  }, [initialPath]);

  const chosen = selected || listing?.path || pathDraft;
  const useLabel = (selected && selected !== listing?.path
    ? selected.split(/[\\/]/).filter(Boolean).pop()
    : listing?.is_git
      ? "this repository"
      : "this folder");

  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  };

  return (
    <div
      className="modal-backdrop"
      data-testid="repo-explorer"
      data-overlay="true"
      onClick={onClose}
      onKeyDown={onKey}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="explorer-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <h2 id="explorer-title">Select repository</h2>
            <p className="muted">Browse to a git root, or paste the full path.</p>
          </div>
          <button type="button" className="btn ghost" data-testid="explorer-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
        <form
          className="explorer-path"
          onSubmit={(e) => {
            e.preventDefault();
            void load(pathDraft);
          }}
        >
          <input
            ref={pathRef}
            data-testid="explorer-path"
            value={pathDraft}
            onChange={(e) => setPathDraft(e.target.value)}
            spellCheck={false}
            aria-label="Directory path"
          />
          <button type="button" className="btn" disabled={!listing?.parent} onClick={() => listing?.parent && void load(listing.parent)}>
            Up
          </button>
          <button type="button" className="btn" onClick={() => listing && void load(listing.home)}>
            Home
          </button>
          <button type="submit" className="btn">
            Go
          </button>
        </form>
        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}
        <div className="explorer-list" role="listbox" aria-label="Folders" aria-busy={busy}>
          {listing?.entries.length ? (
            listing.entries.map((entry) => {
              const active = selected === entry.path;
              return (
                <button
                  key={entry.path}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={active ? "explorer-row active" : "explorer-row"}
                  data-testid="explorer-entry"
                  data-path={entry.path}
                  onClick={() => setSelected(entry.path)}
                  onDoubleClick={() => void load(entry.path)}
                >
                  <IconFolder />
                  <span className="explorer-name">{entry.name}</span>
                  {entry.is_git ? <span className="chip git-badge">git</span> : null}
                </button>
              );
            })
          ) : (
            <div className="muted explorer-empty">{busy ? "Loading…" : "No folders here"}</div>
          )}
        </div>
        <div className="modal-foot">
          <span className="muted explorer-current" title={chosen}>
            {chosen}
          </span>
          <button
            type="button"
            className="btn primary"
            data-testid="explorer-use"
            disabled={!chosen}
            onClick={() => chosen && onSelect(chosen)}
          >
            Use {useLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
