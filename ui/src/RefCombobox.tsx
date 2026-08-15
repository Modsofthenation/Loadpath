import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { IconChevron } from "./icons";
import { filterRefOptions, groupedRefOptions, groupLabel, refOptions, type RefOption } from "./refs";
import type { GitRefs } from "./types";

export function RefCombobox({
  value,
  onChange,
  placeholder,
  testId,
  menuTestId,
  refs,
  onNeedRefs,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  testId: string;
  menuTestId: string;
  refs: GitRefs | null;
  onNeedRefs: () => void;
}) {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<string | null>(null);
  const [active, setActive] = useState(0);

  const options = useMemo(() => {
    const all = refOptions(refs);
    return filter === null ? all : filterRefOptions(all, filter);
  }, [refs, filter]);
  const sections = useMemo(() => groupedRefOptions(options), [options]);

  useEffect(() => {
    if (!open) return;
    onNeedRefs();
  }, [open, onNeedRefs]);

  useEffect(() => {
    setActive(0);
  }, [filter, open]);

  const close = () => {
    setOpen(false);
    setFilter(null);
  };

  const pick = (option: RefOption) => {
    onChange(option.value);
    close();
  };

  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setActive((i) => Math.min(i + 1, Math.max(options.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) return;
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      const hit = options[active];
      if (hit) pick(hit);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
    }
  };

  return (
    <div
      className="combo"
      ref={rootRef}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) close();
      }}
    >
      <div className="combo-row">
        <input
          data-testid={testId}
          value={value}
          placeholder={placeholder}
          spellCheck={false}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          onChange={(e) => {
            onChange(e.target.value);
            if (open) setFilter(e.target.value);
          }}
          onKeyDown={onKey}
        />
        <button
          type="button"
          className="icon-btn combo-toggle"
          data-testid={`${testId}-toggle`}
          aria-label="Show recent refs"
          aria-expanded={open}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => (open ? close() : setOpen(true))}
        >
          <IconChevron />
        </button>
      </div>
      {open ? (
        <div className="combo-menu" id={listId} role="listbox" data-testid={menuTestId}>
          {sections.length === 0 ? (
            <div className="combo-empty muted">No matching refs — the typed value is kept</div>
          ) : (
            sections.map((section) => (
              <div key={section.group} className="combo-group">
                <div className="combo-heading">{groupLabel(section.group)}</div>
                {section.items.map((item) => {
                  const index = options.indexOf(item);
                  return (
                    <button
                      key={`${item.group}:${item.value}`}
                      type="button"
                      role="option"
                      aria-selected={index === active}
                      className={index === active ? "combo-option active" : "combo-option"}
                      data-testid={`ref-option-${item.group}`}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => pick(item)}
                    >
                      <span className="combo-label">{item.label}</span>
                      {item.detail ? <span className="combo-detail">{item.detail}</span> : null}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
