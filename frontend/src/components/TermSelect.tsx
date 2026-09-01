/** Pick several things from a vocabulary, and add one when it is not there.
 *
 *  Allergies were a text box. That is not a tidiness problem: the allergy field
 *  is read by code, not only by people — it raises a blocking warning at
 *  dispensing by matching what was typed against product names and active
 *  ingredients. "Penicilin" with one L therefore is not a typo somebody
 *  corrects later, it is a safety check that silently never fires, on the one
 *  record whose entire purpose is to fire. Chronic conditions are the same
 *  shape: the dispensary worklist decides whose repeat is urgent by matching
 *  words in that field.
 *
 *  So the common answer is a click. The list stays open, though, and that is
 *  the important half — a vocabulary a pharmacy cannot extend is one people
 *  work around by typing into a notes field, and an allergy in the notes warns
 *  nobody at all. When what somebody typed is not on the list, the last row of
 *  the panel offers to add it, there and then, without leaving the form they
 *  are halfway through.
 *
 *  The value is still the comma-separated string the rest of the system reads,
 *  so nothing downstream had to change to benefit from this.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Plus, X } from "@phosphor-icons/react";
import { api, errorText } from "../api";
import { useToast } from "./Toast";

export interface Term {
  id: number; kind: string; name: string;
  synonyms: string; category: string; common: boolean; times_used: number;
}

interface Props {
  /** Which vocabulary — "allergy" or "condition". */
  kind: string;
  /** The comma-separated string held on the record. */
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  /** Wording for the empty state, in the field's own terms. */
  emptyLabel?: string;
}

/** Split the stored string the same way the dispensing check does. */
export function parseTerms(value: string): string[] {
  return (value || "")
    .replace(/;/g, ",")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** Join back the way the record stores it. */
function joinTerms(list: string[]): string {
  return list.join(", ");
}

export default function TermSelect({
  kind, value, onChange, placeholder, id, disabled, emptyLabel,
}: Props) {
  const chosen = useMemo(() => parseTerms(value), [value]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Term[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const toast = useToast();

  const search = useCallback((q: string) => {
    setLoading(true);
    api.get<{ items: Term[] }>(
      `/api/clinical-terms?kind=${encodeURIComponent(kind)}`
      + `&q=${encodeURIComponent(q)}&limit=40`)
      .then((d) => setOptions(d.items ?? []))
      .catch(() => setOptions([]))
      .finally(() => setLoading(false));
  }, [kind]);

  // Debounced, because this runs on every keystroke and the list is small
  // enough that a slower, steadier request beats a burst of them.
  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => search(query), query ? 180 : 0);
    return () => window.clearTimeout(t);
  }, [open, query, search]);

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

  const typed = query.trim();
  // Terms already on the record stay visible, greyed, rather than being removed
  // from the list. Hiding them looked tidier and was actively dangerous: a
  // patient already recorded as allergic to Penicillin, searched as "pen",
  // matched only that one option, which was then filtered out, leaving "add
  // pen to the list" as the single row on offer. Taking it created an allergen
  // called "pen" and put it on the patient. Junk in this particular vocabulary
  // is not untidiness; it is a warning that will not fire for anybody else.
  const already = (name: string) =>
    chosen.some((c) => c.toLowerCase() === name.toLowerCase());
  const shown = options;

  // Adding is offered only when the search found nothing at all. If anything
  // matched, the answer is to pick it — a fragment of a term that exists is
  // never a new term. Searching the full "Penicillamine" still finds nothing
  // and can still be added, because that genuinely is not Penicillin.
  const canAdd = typed.length >= 2 && options.length === 0 && !loading;
  const rows = shown.length + (canAdd ? 1 : 0);

  function commit(list: string[]) {
    onChange(joinTerms(list));
  }

  function pick(name: string) {
    if (chosen.some((c) => c.toLowerCase() === name.toLowerCase())) return;
    commit([...chosen, name]);
    setQuery("");
    setHighlight(0);
    // The panel closes on picking, and this is not fussiness. Left open it
    // covers whatever sits under the field — in the patient editor that is the
    // Save button, so the form could be filled in and then not submitted, with
    // the click landing silently on a dropdown row instead. Focus stays in the
    // input, so typing the next allergy reopens it without a second click.
    setOpen(false);
    inputRef.current?.focus();
    // Best effort, and never in the way: the tally only reorders the list.
    api.post("/api/clinical-terms/used", { kind, names: [name] }).catch(() => undefined);
  }

  function remove(name: string) {
    commit(chosen.filter((c) => c !== name));
  }

  async function addNew() {
    if (!canAdd || adding) return;
    setAdding(true);
    try {
      const term = await api.post<Term>("/api/clinical-terms", { kind, name: typed });
      pick(term.name);
      search("");
    } catch (e) {
      toast.error(errorText(e, "That could not be added to the list."));
    } finally {
      setAdding(false);
    }
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setHighlight((h) => Math.min(h + 1, rows - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHighlight((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const opt = shown[highlight];
      if (highlight < shown.length) { if (opt && !already(opt.name)) pick(opt.name); }
      else if (canAdd) addNew();
    } else if (e.key === "Escape") { setOpen(false); setQuery(""); }
    else if (e.key === "Backspace" && !query && chosen.length) {
      // The ordinary behaviour of a field made of chips.
      remove(chosen[chosen.length - 1]);
    }
  }

  return (
    <>
      <div
        ref={boxRef}
        className={`term-select${disabled ? " is-disabled" : ""}${open ? " is-open" : ""}`}
        onClick={() => { if (!disabled) { setOpen(true); inputRef.current?.focus(); } }}
      >
        {chosen.map((name) => (
          <span className="term-chip" key={name}>
            {name}
            {!disabled && (
              <button
                type="button"
                aria-label={`Remove ${name}`}
                onClick={(e) => { e.stopPropagation(); remove(name); }}
              >
                <X size={11} weight="bold" />
              </button>
            )}
          </span>
        ))}
        <input
          ref={inputRef}
          id={id}
          className="term-input"
          value={query}
          disabled={disabled}
          placeholder={chosen.length ? "" : (placeholder ?? "Search or add…")}
          onChange={(e) => { setQuery(e.target.value); setHighlight(0); setOpen(true); }}
          // Deliberately not opened by focus alone. Picking a term keeps the
          // caret in the field so the next one can just be typed, and an
          // onFocus that opens would immediately reopen the panel that was
          // just closed, putting it straight back over the Save button.
          // Clicking the field or typing opens it; both are explicit.
          onKeyDown={onKey}
          autoComplete="off"
        />
      </div>

      {open && rect && createPortal(
        <div
          ref={panelRef}
          className="term-panel"
          style={{
            position: "fixed",
            top: rect.bottom + 4,
            left: rect.left,
            width: rect.width,
          }}
        >
          {loading && !options.length ? (
            <div className="term-empty">Looking…</div>
          ) : (
            <>
              {shown.map((o, n) => {
                const have = already(o.name);
                return (
                  <button
                    type="button"
                    key={o.id}
                    className={`term-option${n === highlight && !have ? " is-on" : ""}`
                               + (have ? " is-had" : "")}
                    disabled={have}
                    onMouseEnter={() => !have && setHighlight(n)}
                    onClick={() => pick(o.name)}
                  >
                    <span>
                      {o.name}
                      {/* The word the patient is likely to say, where it differs
                          from the catalogue's. Somebody hunting "sulfa" needs to
                          see why "Sulphonamides" is the right row. */}
                      {o.synonyms && (
                        <span className="term-syn">
                          {o.synonyms.split(",").slice(0, 3).join(", ")}
                        </span>
                      )}
                    </span>
                    {/* A tick means SELECTED, everywhere. Marking "this is a
                        common one" with the same glyph put a column of ticks
                        beside things nobody had chosen — on a picker whose
                        whole job is to show what has been chosen. Said in a
                        word instead, which cannot be misread as a state. */}
                    {have
                      ? <span className="term-had">already recorded</span>
                      : o.common
                        ? <span className="term-common">common</span>
                        : null}
                  </button>
                );
              })}

              {canAdd && (
                <button
                  type="button"
                  className={`term-option term-add${highlight >= shown.length ? " is-on" : ""}`}
                  onMouseEnter={() => setHighlight(shown.length)}
                  onClick={addNew}
                  disabled={adding}
                >
                  <Plus size={12} weight="bold" />
                  <span>
                    {adding ? "Adding…" : <>Add &ldquo;<b>{typed}</b>&rdquo; to the list</>}
                  </span>
                </button>
              )}

              {!shown.length && !canAdd && (
                <div className="term-empty">
                  {typed
                    ? "Nothing matches. Type at least two letters to add it."
                    : (emptyLabel ?? "Start typing to search the list.")}
                </div>
              )}
            </>
          )}
        </div>,
        document.body)}
    </>
  );
}
