/** Search a reference list and pick one, instead of typing it from memory.
 *
 *  The sibling of TermSelect, for the other half of the problem. Where that one
 *  holds several values from a vocabulary the pharmacy owns and can extend, this
 *  holds one value from a list somebody else publishes — an ICD-10 code, a
 *  funder. The difference matters, and it is why this one has no "add new" row:
 *  a pharmacy may decide what it calls an allergy, but it may not invent a
 *  diagnosis code. A made-up code does not fail loudly, it fails at the funder,
 *  weeks later, as a rejected claim nobody can explain.
 *
 *  The field these replaced said `placeholder="e.g. E11.9"`, which is a form
 *  asking somebody to remember a code — and the ones they remember are the four
 *  they always use, whether or not those are right for this patient.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle, MagnifyingGlass, Warning, X } from "@phosphor-icons/react";
import { api } from "../api";

export interface LookupItem {
  /** What gets stored — a code, or an id as a string. */
  value: string;
  /** The human name for it. */
  label: string;
  /** A second line: the chapter, the type, whatever narrows it. */
  hint?: string;
  /** Set false to show the row as not usable here, with the reason in `hint`. */
  usable?: boolean;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** Fetch matches for what has been typed. */
  search: (q: string) => Promise<LookupItem[]>;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  required?: boolean;
  /** Said when nothing matches, in the field's own terms. */
  emptyLabel?: string;
}

export default function LookupInput({
  value, onChange, search, placeholder, id, disabled, required, emptyLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<LookupItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [picked, setPicked] = useState<LookupItem | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const run = useCallback((q: string) => {
    setLoading(true);
    search(q)
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [search]);

  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => run(query), query ? 200 : 0);
    return () => window.clearTimeout(t);
  }, [open, query, run]);

  // A value arriving from the record (an edit, not a fresh form) has no label
  // yet. Looked up once so the field can show what the code means rather than
  // the bare code, which is the whole point of not typing it from memory.
  useEffect(() => {
    if (!value || picked?.value === value) return;
    let cancelled = false;
    search(value)
      .then((rows) => {
        if (cancelled) return;
        const hit = rows.find((r) => r.value.toLowerCase() === value.toLowerCase());
        if (hit) setPicked(hit);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [value, picked, search]);

  useEffect(() => {
    if (!open) return;
    function place() {
      const r = boxRef.current?.getBoundingClientRect();
      if (r) setRect(r);
    }
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function away(e: MouseEvent) {
      const t = e.target as Node;
      if (boxRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
      setQuery("");
    }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  function choose(item: LookupItem) {
    if (item.usable === false) return;
    setPicked(item);
    onChange(item.value);
    setQuery("");
    // Closed on picking, for the reason TermSelect explains: an open panel sits
    // over whatever follows the field, which is usually the button that submits
    // the form it is in.
    setOpen(false);
  }

  function clear() {
    setPicked(null);
    onChange("");
    setQuery("");
    inputRef.current?.focus();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setHighlight((h) => Math.min(h + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHighlight((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const it = items[highlight];
      if (it) choose(it);
    } else if (e.key === "Escape") { setOpen(false); setQuery(""); }
  }

  // A value the record holds but the list does not recognise. It is shown
  // rather than silently cleared, because it is somebody's existing data — but
  // it is flagged, since an unrecognised code is exactly what will be rejected.
  const unknown = !!value && !picked;

  return (
    <>
      <div
        ref={boxRef}
        className={`lookup${disabled ? " is-disabled" : ""}${open ? " is-open" : ""}`
                   + (unknown ? " is-unknown" : "")}
        onClick={() => { if (!disabled) { setOpen(true); inputRef.current?.focus(); } }}
      >
        {value && !open ? (
          <span className="lookup-picked">
            {unknown
              ? <Warning size={13} weight="fill" className="lookup-warn" />
              : <CheckCircle size={13} weight="fill" className="lookup-ok" />}
            <span className="lookup-code">{value}</span>
            {picked?.label && <span className="lookup-label">{picked.label}</span>}
            {!disabled && (
              <button type="button" aria-label="Clear"
                      onClick={(e) => { e.stopPropagation(); clear(); }}>
                <X size={11} weight="bold" />
              </button>
            )}
          </span>
        ) : (
          <>
            <MagnifyingGlass size={13} className="lookup-icon" />
            <input
              ref={inputRef}
              id={id}
              className="lookup-input"
              value={query}
              disabled={disabled}
              required={required && !value}
              placeholder={placeholder ?? "Search…"}
              onChange={(e) => { setQuery(e.target.value); setHighlight(0); setOpen(true); }}
              onKeyDown={onKey}
              autoComplete="off"
            />
          </>
        )}
      </div>

      {unknown && !open && (
        <p className="muted small">
          Not on the list. It will be sent as typed, and an unrecognised value is
          what comes back rejected.
        </p>
      )}

      {open && rect && createPortal(
        <div
          ref={panelRef}
          className="term-panel"
          style={{ position: "fixed", top: rect.bottom + 4, left: rect.left, width: rect.width }}
        >
          {loading && !items.length ? (
            <div className="term-empty">Looking…</div>
          ) : items.length ? (
            items.map((it, n) => (
              <button
                type="button"
                key={it.value}
                className={`term-option${n === highlight ? " is-on" : ""}`
                           + (it.usable === false ? " is-had" : "")}
                disabled={it.usable === false}
                onMouseEnter={() => setHighlight(n)}
                onClick={() => choose(it)}
              >
                <span>
                  <span className="lookup-code">{it.value}</span> {it.label}
                  {it.hint && <span className="term-syn">{it.hint}</span>}
                </span>
              </button>
            ))
          ) : (
            <div className="term-empty">
              {query
                ? (emptyLabel ?? "Nothing matches that.")
                : "Start typing to search."}
            </div>
          )}
        </div>,
        document.body)}
    </>
  );
}
