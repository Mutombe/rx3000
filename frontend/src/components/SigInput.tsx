/** Dosage directions, typed as shorthand and printed as a sentence.
 *
 *  "the propharm software had it" — and it is the single biggest saving of
 *  keystrokes in the dispensary. A dispenser types `1 t tds pc` and the label
 *  says "1 t three times a day after food". Forty-four codes were seeded, an
 *  endpoint expanded them, and nothing in the front end called it.
 *
 *  Expansion happens when the field is left, not on every keystroke. Rewriting
 *  text while somebody is still typing it is the behaviour that makes people
 *  fight an input, and `tds` is a prefix of nothing but is a whole word here —
 *  expanding mid-word would turn half-typed shorthand into a sentence and then
 *  try to expand the sentence.
 *
 *  Unknown words pass through untouched, which is what makes the field safe to
 *  use for ordinary English. A dispenser who types "One tablet at night" gets
 *  exactly that back.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";

interface Group { code: string; expansion: string; meaning: string }
interface Book { count: number; groups: Record<string, Group[]> }

/** Fetched once for the whole session and shared: the book is 44 rows that
 *  change perhaps yearly, and every script line would otherwise ask for it. */
let bookPromise: Promise<Book> | null = null;
function loadBook(): Promise<Book> {
  if (!bookPromise) {
    bookPromise = api.get<Book>("/api/dosage-abbreviations")
      .catch(() => ({ count: 0, groups: {} }));
  }
  return bookPromise;
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
  const [expandedFrom, setExpandedFrom] = useState("");
  const live = useRef(true);

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

  async function expand() {
    const shorthand = value.trim();
    if (!shorthand) return;
    try {
      const res = await api.post<{ directions: string }>(
        "/api/dosage-abbreviations/expand", { shorthand });
      if (res.directions && res.directions !== value) {
        // Kept so the dispenser can see what their shorthand became, and undo it
        // if the book expanded something they meant literally.
        setExpandedFrom(shorthand);
        onChange(res.directions);
      }
    } catch {
      // An expansion that cannot be reached is not worth an error: what was
      // typed is still a valid instruction, and the label prints it as written.
    }
  }

  return (
    <div className="sig">
      <div className="sig-row">
        <input
          id={id}
          value={value}
          placeholder={placeholder ?? "e.g. 1 t tds pc"}
          onChange={(e) => { setExpandedFrom(""); onChange(e.target.value); }}
          onBlur={expand}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); expand(); }
          }}
        />
        <button
          type="button"
          className="btn ghost small"
          aria-expanded={showBook}
          onClick={() => setShowBook((s) => !s)}
          title="Show the dosage shorthand"
        >
          {showBook ? "Hide codes" : "Codes"}
        </button>
      </div>

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
          {Object.entries(book.groups).map(([category, codes]) => (
            <div key={category}>
              <h5>{category}</h5>
              <ul>
                {codes.map((c) => (
                  <li key={c.code}>
                    {/* Clicking appends rather than replaces: directions are
                        built from several codes, and a picker that overwrote the
                        field would make the second click undo the first. */}
                    <button type="button" onClick={() => {
                      setExpandedFrom("");
                      onChange(`${value}${value && !value.endsWith(" ") ? " " : ""}${c.code}`);
                    }}>
                      <b>{c.code}</b> {c.expansion}
                      {c.meaning && <span className="muted"> · {c.meaning}</span>}
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
}
