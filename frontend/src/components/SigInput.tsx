/** Dosage directions, typed as shorthand and printed as a sentence.
 *
 *  "the propharm software had it", and it is the single biggest saving of
 *  keystrokes in the dispensary. A dispenser types `1t tds pc` and the label
 *  says "Take ONE tablet three times a day after food."
 *
 *  WHY THE EXPANSION IS DONE HERE AND NOT ON THE SERVER
 *
 *  It used to POST the shorthand and wait. The book was already in the browser
 *  — the same book, fetched once for the session, so the round trip bought
 *  nothing and cost the one thing that matters at a counter: the answer was not
 *  there when the dispenser looked up. On a Zimbabwean connection with the
 *  server in another city that is a visible pause on every script line, dozens
 *  of times a day, for a substitution the browser could have done in a
 *  microsecond.
 *
 *  So it expands locally and immediately. The rule is applied in one place —
 *  `expandLocal` below mirrors `sig.expand` on the server, including the
 *  pluralisation, and the server remains the authority for what actually
 *  prints, because the label is rendered there. If the two ever disagree, the
 *  label is right and this was only ever a preview.
 *
 *  WHAT IS SHOWN WHILE TYPING
 *
 *  The sentence that will print, live, under the field. That is the thing the
 *  dispenser is actually deciding about, and having it on screen removes most
 *  of the reason to open the code book at all. Words the book does not know are
 *  named beneath it — not as an error, because ordinary English is a perfectly
 *  good direction and passes straight through, but so that `stst` is visibly
 *  not `stat`.
 *
 *  The field itself is never rewritten while somebody is typing in it. Text
 *  that changes under the cursor is the behaviour that makes people fight an
 *  input. The shorthand stays; the sentence appears beside it.
 *
 *  THE PICKER OPENS AS YOU TYPE, BECAUSE THAT IS WHERE THE MUSCLE MEMORY IS
 *
 *  Proppharm — the system most Zimbabwean dispensaries are coming off — put a
 *  dialog on screen the moment you touched the Directions field: "Possible
 *  Descriptions (Press <Enter> to Select)", every code beginning with what you
 *  had typed, arrow keys to move, Enter to take one. A dispenser who has done
 *  that for fifteen years types `q` and then looks down, without deciding to.
 *
 *  This does the same thing. It matches on the word under the cursor, not the
 *  whole field, because directions are built from several codes in a row and
 *  the second one has to complete as readily as the first.
 *
 *  Enter is overloaded on purpose and in one direction only: while the list is
 *  open it takes the highlighted code, and otherwise it expands the field as it
 *  always did. Nothing is ever inserted without a keystroke that means it —
 *  there is no completion-on-blur and no first-match-wins, because a code
 *  quietly substituted into a direction is a label nobody chose.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { MagnifyingGlass, Warning, X } from "@phosphor-icons/react";
import { api } from "../api";

interface Entry {
  code: string;
  expansion: string;
  meaning: string;
  caution?: string;
}
interface Book { count: number; groups: Record<string, Entry[]> }

/** Fetched once for the whole session and shared: the book changes perhaps
 *  yearly, and every script line would otherwise ask for it. */
let bookPromise: Promise<Book> | null = null;
function loadBook(): Promise<Book> {
  if (!bookPromise) {
    bookPromise = api.get<Book>("/api/dosage-abbreviations")
      .catch(() => ({ count: 0, groups: {} }));
  }
  return bookPromise;
}

const GROUP_TITLES: Record<string, string> = {
  quantity: "How much",
  frequency: "How often",
  timing: "When",
  route: "Where it goes",
  form: "What it is",
  // Carried over with the Proppharm vocabulary.
  indication: "What it is for",
  caution: "Warnings",
  dispensary: "For the dispensary",
  greeting: "Greetings",
};

/** Nouns a numeral in front of has to agree with. Mirrors `sig.PLURALS`. */
const PLURALS: Record<string, string> = {
  tablet: "tablets", capsule: "capsules", drop: "drops", puff: "puffs",
  spoon: "spoons", sachet: "sachets", suppository: "suppositories",
  pessary: "pessaries", spray: "sprays", patch: "patches",
  lozenge: "lozenges",
};
const MANY = new Set(["two", "three", "four", "five", "six", "seven", "eight",
  "nine", "ten"]);

/** The same expansion the server does, done here so it is instant.
 *
 *  Unknown tokens pass through untouched rather than being dropped: a label
 *  missing part of its instruction is worse than one that reads awkwardly,
 *  because nothing on the box shows the omission.
 */
export function expandLocal(shorthand: string, codes: Map<string, string>): string {
  const text = (shorthand || "").trim();
  if (!text) return "";
  const words = text.split(/\s+/).map((token) => {
    // Trailing punctuation stays attached to whatever it followed. Hyphens are
    // left alone: `r-eye` is a code, not two words.
    const bare = token.replace(/[.,;]+$/, "").toLowerCase();
    return codes.get(bare) ?? token;
  });

  const out = words.join(" ").split(" ");
  for (let i = 1; i < out.length; i++) {
    const before = out[i - 1].replace(/[.,;]+$/, "").toLowerCase();
    const many = MANY.has(before) || (/^\d+$/.test(before) && Number(before) !== 1);
    if (!many) continue;
    const bare = out[i].replace(/[.,;]+$/, "").toLowerCase();
    if (PLURALS[bare]) out[i] = out[i].toLowerCase().replace(bare, PLURALS[bare]);
  }

  let sentence = out.join(" ").trim();
  if (!sentence) return "";
  sentence = sentence[0].toUpperCase() + sentence.slice(1);
  if (!".!".includes(sentence[sentence.length - 1])) sentence += ".";
  return sentence;
}

export default function SigInput({
  value, onChange, placeholder, id, compact = false, autoFocus, onKeyDown, onBlur,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  id?: string;
  /** For a table cell: the field and its suggestions, without the Codes button,
   *  the label preview or the expansion note, and with the suggestions floated
   *  on the viewport so a scrolling table cannot clip them. */
  compact?: boolean;
  autoFocus?: boolean;
  /** Called for keys the suggestion list did not use. */
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  /** Called after the field's own blur has committed the expansion. */
  onBlur?: () => void;
}) {
  const [book, setBook] = useState<Book | null>(null);
  const [showBook, setShowBook] = useState(false);
  const [filter, setFilter] = useState("");
  const [expandedFrom, setExpandedFrom] = useState("");
  const [sheeting, setSheeting] = useState(false);
  /** The word under the cursor, and where in the field it sits. Empty when the
   *  suggestion list should not be on screen at all. */
  const [typing, setTyping] = useState<{ word: string; from: number; to: number } | null>(null);
  const [cursor, setCursor] = useState(0);
  const live = useRef(true);
  const panel = useRef<HTMLDivElement | null>(null);
  const field = useRef<HTMLInputElement | null>(null);
  const list = useRef<HTMLUListElement | null>(null);

  useEffect(() => {
    // Set true on every mount, not just at creation. React's development mode
    // mounts, unmounts and mounts again; the cleanup below set this false, and
    // without resetting it the second mount threw away the answer it had asked
    // for. The panel opened onto nothing, the request having plainly returned
    // 200 — a bug that only exists in development, which is where the panel was
    // being looked at.
    live.current = true;
    loadBook().then((b) => { if (live.current) setBook(b); });
    return () => { live.current = false; };
  }, []);

  const entries = useMemo(
    () => Object.values(book?.groups ?? {}).flat(), [book]);
  const codes = useMemo(
    () => new Map(entries.map((e) => [e.code.toLowerCase(), e.expansion])),
    [entries]);

  /** What the label will say, right now. */
  const preview = useMemo(
    () => (codes.size ? expandLocal(value, codes) : ""), [value, codes]);

  /** Words the book does not recognise. Not an error — see the note above. */
  const unknown = useMemo(() => {
    if (!codes.size) return [];
    return (value || "").trim().split(/\s+/)
      .filter((t) => t && !codes.has(t.replace(/[.,;]+$/, "").toLowerCase()));
  }, [value, codes]);

  /** The codes that could complete the word being typed.
   *
   *  Prefix first, which is what Proppharm did and therefore what a hand coming
   *  off it expects: typing `q` listed Q, Q12, Q6H, QH, QID, QQH, QW and
   *  nothing else. Where a prefix finds nothing the words are searched instead,
   *  so somebody who knows what they mean but not what it is called still gets
   *  an answer rather than an empty box — that tier never fires while the
   *  familiar one is producing results, so it cannot surprise anybody.
   *
   *  Capped, because a list longer than the screen is one nobody reads, and
   *  because `1` alone matches thirty-odd codes.
   */
  const suggestions = useMemo(() => {
    const q = (typing?.word ?? "").toLowerCase();
    if (!q || !entries.length) return [];
    const prefix = entries.filter((e) => e.code.toLowerCase().startsWith(q));
    const pool = prefix.length ? prefix : entries.filter((e) =>
      e.expansion.toLowerCase().includes(q));
    return pool
      .sort((a, b) => a.code.length - b.code.length
        || a.code.toLowerCase().localeCompare(b.code.toLowerCase()))
      .slice(0, 12);
  }, [typing, entries]);

  const picking = suggestions.length > 0;

  // Back to the top whenever the list changes under the highlight, so Enter
  // never takes a row that scrolled away while somebody was still typing.
  useEffect(() => { setCursor(0); }, [typing?.word]);

  // Keep the highlighted row in view when it is moved with the keyboard, which
  // is the only way it moves — the list is taller than the box it sits in.
  useEffect(() => {
    const el = list.current?.children[cursor] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  /** Nothing was recognised at all, so the preview is only an echo. */
  const recognised = preview && unknown.length
    < (value.trim() ? value.trim().split(/\s+/).length : 0);

  function commit() {
    const shorthand = value.trim();
    if (!shorthand || !codes.size) return;
    const next = expandLocal(shorthand, codes);
    if (next && next !== value) {
      // Kept so the dispenser can see what their shorthand became, and undo it
      // if the book expanded something they meant literally.
      setExpandedFrom(shorthand);
      onChange(next);
    }
  }

  /** The book, narrowed to what is being looked for.
   *
   *  Opening onto seventy-five codes and asking somebody to read is the panel
   *  they close again. The filter matches the code, the words it prints and its
   *  Latin origin, so "night" finds `nocte` and `on` — a dispenser who knows
   *  what they mean but not what it is called is the person this is for.
   */
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const groups: [string, Entry[]][] = Object.entries(book?.groups ?? {});
    if (!q) return groups;
    return groups
      .map(([g, list]) => [g, list.filter((e) =>
        e.code.toLowerCase().includes(q)
        || e.expansion.toLowerCase().includes(q)
        || (e.meaning || "").toLowerCase().includes(q))] as [string, Entry[]])
      .filter(([, list]) => list.length > 0);
  }, [book, filter]);

  const hits = shown.reduce((n, [, list]) => n + list.length, 0);

  // Close on Escape and on a click outside — the two ways a person expects a
  // panel to go away. Without them the only way out was the button that opened
  // it, which is behind the panel on a narrow screen.
  useEffect(() => {
    if (!showBook) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setShowBook(false); };
    const away = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) {
        setShowBook(false);
      }
    };
    document.addEventListener("keydown", key);
    document.addEventListener("mousedown", away);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("mousedown", away);
    };
  }, [showBook]);

  return (
    <div className={`sig${compact ? " is-compact" : ""}`} ref={panel}>
      <div className="sig-row">
        <input
          id={id}
          ref={field}
          autoFocus={autoFocus}
          value={value}
          autoComplete="off"
          placeholder={placeholder ?? "e.g. 1t tds pc"}
          aria-expanded={picking}
          onChange={(e) => {
            setExpandedFrom("");
            onChange(e.target.value);
            track(e.target.value, e.target.selectionStart ?? e.target.value.length);
          }}
          // Moving the caret changes which word is being completed, so the list
          // has to follow it. Without this, clicking back into `1t tds` to fix
          // the `1t` went on offering completions for `tds`.
          onClick={(e) => track(value, e.currentTarget.selectionStart ?? 0)}
          onKeyUp={(e) => {
            if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End") {
              track(value, e.currentTarget.selectionStart ?? 0);
            }
          }}
          onBlur={() => {
            // The list closes, and nothing is taken from it. A completion that
            // happens because somebody clicked elsewhere is a word they did not
            // choose, printed on a label they will not re-read.
            setTyping(null);
            commit();
            onBlur?.();
          }}
          onKeyDown={(e) => {
            if (picking) {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => (c + 1) % suggestions.length);
                return;
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => (c - 1 + suggestions.length) % suggestions.length);
                return;
              }
              if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault();
                take(suggestions[cursor]);
                return;
              }
              if (e.key === "Escape") {
                // Dismiss the list, keep the field. Escape twice does not clear
                // anything — this is the only thing it closes.
                e.preventDefault();
                setTyping(null);
                return;
              }
            }
            if (e.key === "Enter") { e.preventDefault(); commit(); }
            onKeyDown?.(e);
          }}
        />
        {!compact && (
        <button
          type="button"
          className="btn ghost small"
          aria-expanded={showBook}
          onClick={() => { setShowBook((s) => !s); setFilter(""); }}
          title="Show the dosage shorthand"
        >
          {showBook ? "Hide codes" : "Codes"}
        </button>
        )}
      </div>

      {/* "Possible Descriptions (Press <Enter> to Select)" — the dialog a
          dispenser coming off Proppharm has typed into for years, in the place
          they expect it: under the field, on the first keystroke.

          Rendered as a listbox rather than buttons so a screen reader announces
          the highlighted row as the arrow keys move it, which the code book
          panel below cannot do because it is a grid of categories. */}
      {picking && (
        <div className="sig-suggest"
             style={compact && field.current ? (() => {
               const r = field.current!.getBoundingClientRect();
               return { position: "fixed" as const, left: r.left, top: r.bottom + 4,
                        right: "auto", width: Math.max(r.width, 420), zIndex: 500 };
             })() : undefined}>
          <div className="sig-suggest-head">
            Possible descriptions
            <span className="muted"> · Enter to select, Esc to dismiss</span>
          </div>
          <ul ref={list} role="listbox" aria-label="Possible descriptions">
            {suggestions.map((c, i) => (
              <li
                key={c.code}
                role="option"
                aria-selected={i === cursor}
                className={i === cursor ? "on" : undefined}
                // Taken on mousedown, not click: the field's own blur fires
                // first on a click and closes the list out from under it.
                onMouseDown={(e) => { e.preventDefault(); take(c); }}
                onMouseEnter={() => setCursor(i)}
              >
                <b>{c.code}</b>
                <span>{c.expansion}</span>
                {c.caution && (
                  <span className="sig-caution">
                    <Warning size={11} weight="fill" /> {c.caution}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* What the box will say. Shown while typing, not after committing, so
          the decision is made against the sentence rather than the shorthand. */}
      {!compact && recognised && !expandedFrom && (
        <p className="sig-preview">
          <span className="sig-preview-label">The label will read</span>
          <b>{preview}</b>
          {unknown.length > 0 && (
            <span className="sig-unknown">
              Not in the book, printed as typed: {unknown.join(", ")}
            </span>
          )}
        </p>
      )}

      {!compact && expandedFrom && (
        <p className="sig-note">
          <b>{expandedFrom}</b> expanded.{" "}
          <button type="button" className="linkish"
            onClick={() => { onChange(expandedFrom); setExpandedFrom(""); }}>
            Undo
          </button>
        </p>
      )}

      {showBook && book && (
        <div className="sig-book">
          <div className="sig-find">
            <MagnifyingGlass size={14} />
            <input
              autoFocus
              value={filter}
              placeholder="Find a code, or the words it prints…"
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => {
                // One match and Enter takes it: the fast path for somebody who
                // knows what they want and is only here to spell it.
                if (e.key === "Enter" && hits === 1) {
                  e.preventDefault();
                  const only = shown[0][1][0];
                  append(only.code);
                }
              }}
            />
            {filter && (
              <button type="button" className="sig-clear"
                      onClick={() => setFilter("")} aria-label="Clear">
                <X size={13} />
              </button>
            )}
          </div>

          {/* The same book as a sheet, because an inspector asks for one on
              paper and a new dispenser is handed one on their first morning.
              Generated from this same list, so the printed copy and the
              software cannot disagree.

              Fetched rather than linked: an `<a href>` cannot carry the
              session's Authorization header, and the usual workaround puts the
              token in the query string, where it lands in every access log the
              request passes through. */}
          <p className="sig-sheet">
            <button type="button" className="linkish" onClick={sheet}>
              {sheeting ? "Preparing…" : "Print the code sheet"}
            </button>
            <span className="muted"> · for the inspection file, or for a new
              dispenser</span>
          </p>

          {hits === 0 ? (
            <p className="sig-none">
              Nothing matches &ldquo;{filter.trim()}&rdquo;. Type it in plain
              words instead — anything the book does not know prints exactly as
              written.
            </p>
          ) : shown.map(([category, list]) => (
            <div key={category}>
              <h5>{GROUP_TITLES[category] ?? category}</h5>
              <ul>
                {list.map((c) => (
                  <li key={c.code}>
                    {/* Clicking appends rather than replaces: directions are
                        built from several codes, and a picker that overwrote the
                        field would make the second click undo the first. */}
                    <button type="button" onClick={() => append(c.code)}>
                      <b>{c.code}</b> {c.expansion}
                      {c.meaning && <span className="muted"> · {c.meaning}</span>}
                      {c.caution && (
                        <span className="sig-caution">
                          <Warning size={11} weight="fill" /> {c.caution}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  async function sheet() {
    setSheeting(true);
    try {
      const file = await api.blob("/api/dosage-abbreviations/sheet.pdf");
      const url = URL.createObjectURL(file.body);
      // Opened rather than saved: somebody reaching for this is usually
      // checking a code, and printing it is one keystroke from there. The
      // browser's own viewer is also the print dialogue.
      window.open(url, "_blank", "noopener");
      // Revoked on a delay: released immediately, Safari cancels the load it
      // has not started yet.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      // The sheet is a convenience over a book that is already on screen.
      // Failing to fetch it is not worth taking over the dispenser's screen.
    } finally {
      setSheeting(false);
    }
  }

  /** Work out which word the caret is in, and whether to offer completions.
   *
   *  The word, not the field: `1t tds` with the caret at the end is completing
   *  `tds`, and the `1t` in front of it is already decided.
   */
  function track(text: string, caret: number) {
    const before = text.slice(0, caret);
    // A single-line field, so a space is the only thing that starts a word.
    const from = before.lastIndexOf(" ") + 1;
    const rest = text.slice(caret);
    const end = rest.search(/\s/);
    const to = end === -1 ? text.length : caret + end;
    const word = text.slice(from, to).replace(/[.,;]+$/, "");
    setTyping(word ? { word, from, to } : null);
  }

  /** Put the chosen code where the word being typed was.
   *
   *  Replaces that word rather than appending, because the dispenser has
   *  already typed the first letters of it — appending would leave `q qid`.
   */
  function take(entry: Entry) {
    if (!typing) return;
    const next = `${value.slice(0, typing.from)}${entry.code} ${value.slice(typing.to)}`;
    setExpandedFrom("");
    onChange(next);
    setTyping(null);
    // Back into the field, caret after the space this just added, so the next
    // code can be typed without reaching for the mouse.
    const at = typing.from + entry.code.length + 1;
    requestAnimationFrame(() => {
      field.current?.focus();
      field.current?.setSelectionRange(at, at);
    });
  }

  function append(code: string) {
    setExpandedFrom("");
    onChange(`${value}${value && !value.endsWith(" ") ? " " : ""}${code} `);
    setFilter("");
  }
}
