/** Folding dropdown.
 *
 *  A native <select> cannot be styled consistently across browsers, cannot show
 *  a description under an option, and on Windows renders a system list that
 *  ignores the design system entirely. This replaces it.
 *
 *  It is deliberately guarded: the trigger is exactly one control height, the
 *  panel matches the trigger width, and long lists become searchable rather
 *  than growing without bound. Pages choose options — never sizes.
 *
 *  Keyboard: ↑/↓ move, Enter/Space select, Esc closes, Home/End jump, typing
 *  filters once the list is searchable.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface Option {
  value: string;
  label: string;
  /** Secondary line, e.g. a role or a code. */
  hint?: string;
  disabled?: boolean;
  /** Optional grouping header this option sits under. */
  group?: string;
}

const SEARCH_THRESHOLD = 8;

export default function Select({
  value, onChange, options, placeholder = "Select…", disabled,
  searchable, clearable, id, invalid, ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
  searchable?: boolean;
  clearable?: boolean;
  id?: string;
  invalid?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [rect, setRect] = useState<{ top: number; left: number; width: number; above: boolean } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const showSearch = searchable ?? options.length >= SEARCH_THRESHOLD;
  const selected = options.find((o) => o.value === value) ?? null;

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) =>
      o.label.toLowerCase().includes(q) || (o.hint ?? "").toLowerCase().includes(q));
  }, [options, query]);

  /** Position against the trigger, flipping up when there is no room below. */
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const measure = () => {
      const r = triggerRef.current!.getBoundingClientRect();
      const spaceBelow = window.innerHeight - r.bottom;
      const above = spaceBelow < 240 && r.top > spaceBelow;
      setRect({
        top: above ? r.top : r.bottom + 4,
        left: r.left,
        width: r.width,
        above,
      });
    };
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, visible.findIndex((o) => o.value === value)));
    if (showSearch) requestAnimationFrame(() => searchRef.current?.focus());

    function onPointer(e: MouseEvent) {
      const t = e.target as Node;
      if (!triggerRef.current?.contains(t) && !panelRef.current?.contains(t)) close();
    }
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  function close() {
    setOpen(false);
    setQuery("");
  }

  function pick(option: Option) {
    if (option.disabled) return;
    onChange(option.value);
    close();
    triggerRef.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open) {
      if (["Enter", " ", "ArrowDown"].includes(e.key)) { e.preventDefault(); setOpen(true); }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); close(); triggerRef.current?.focus(); return; }
    if (e.key === "Tab") { close(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, visible.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    if (e.key === "Home") { e.preventDefault(); setActive(0); }
    if (e.key === "End") { e.preventDefault(); setActive(visible.length - 1); }
    if (e.key === "Enter" || (e.key === " " && !showSearch)) {
      e.preventDefault();
      if (visible[active]) pick(visible[active]);
    }
  }

  // Keep the highlighted row in view while arrowing through a long list.
  useEffect(() => {
    if (!open || !panelRef.current) return;
    panelRef.current.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  let lastGroup: string | undefined;

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        disabled={disabled}
        className={`sel-trigger${open ? " open" : ""}${invalid ? " invalid" : ""}${selected ? "" : " empty"}`}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onKeyDown}
      >
        <span className="sel-value">{selected ? selected.label : placeholder}</span>
        {clearable && selected && !disabled && (
          <span
            className="sel-clear"
            role="button"
            aria-label="Clear"
            onClick={(e) => { e.stopPropagation(); onChange(""); }}
          >✕</span>
        )}
        <span className="sel-caret" aria-hidden>▾</span>
      </button>

      {open && rect && createPortal(
        <div
          ref={panelRef}
          className="sel-panel"
          role="listbox"
          style={{
            top: rect.above ? undefined : rect.top,
            bottom: rect.above ? window.innerHeight - rect.top + 4 : undefined,
            left: rect.left,
            width: rect.width,
          }}
          onKeyDown={onKeyDown}
        >
          {showSearch && (
            <div className="sel-search">
              <input
                ref={searchRef}
                value={query}
                placeholder="Search…"
                onChange={(e) => { setQuery(e.target.value); setActive(0); }}
                onKeyDown={onKeyDown}
              />
            </div>
          )}
          <div className="sel-list">
            {visible.length === 0 && <div className="sel-empty">No matches</div>}
            {visible.map((o, i) => {
              const header = o.group && o.group !== lastGroup ? o.group : null;
              lastGroup = o.group;
              return (
                <div key={o.value || `__${i}`}>
                  {header && <div className="sel-group">{header}</div>}
                  <div
                    data-idx={i}
                    role="option"
                    aria-selected={o.value === value}
                    className={`sel-option${i === active ? " active" : ""}`
                      + `${o.value === value ? " selected" : ""}${o.disabled ? " disabled" : ""}`}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => pick(o)}
                  >
                    <span className="sel-option-main">
                      <span className="sel-option-label">{o.label}</span>
                      {o.hint && <span className="sel-option-hint">{o.hint}</span>}
                    </span>
                    {o.value === value && <span className="sel-tick" aria-hidden>✓</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
