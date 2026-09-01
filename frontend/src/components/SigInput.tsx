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
  value, onChange, placeholder, id,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  id?: string;
}) {
  const [book, setBook] = useState<Book | null>(null);
  const [showBook, setShowBook] = useState(false);
  const [filter, setFilter] = useState("");
  const [expandedFrom, setExpandedFrom] = useState("");
  const [sheeting, setSheeting] = useState(false);
  const live = useRef(true);
  const panel = useRef<HTMLDivElement | null>(null);

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
    <div className="sig" ref={panel}>
      <div className="sig-row">
        <input
          id={id}
          value={value}
          placeholder={placeholder ?? "e.g. 1t tds pc"}
          onChange={(e) => { setExpandedFrom(""); onChange(e.target.value); }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); commit(); }
          }}
        />
        <button
          type="button"
          className="btn ghost small"
          aria-expanded={showBook}
          onClick={() => { setShowBook((s) => !s); setFilter(""); }}
          title="Show the dosage shorthand"
        >
          {showBook ? "Hide codes" : "Codes"}
        </button>
      </div>

      {/* What the box will say. Shown while typing, not after committing, so
          the decision is made against the sentence rather than the shorthand. */}
      {recognised && !expandedFrom && (
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

      {expandedFrom && (
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

  function append(code: string) {
    setExpandedFrom("");
    onChange(`${value}${value && !value.endsWith(" ") ? " " : ""}${code} `);
    setFilter("");
  }
}
