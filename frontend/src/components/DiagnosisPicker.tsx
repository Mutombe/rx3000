/** ICD-10 picker.
 *
 *  A claim line without a diagnosis is rejected by the scheme, so this is not
 *  optional metadata — it sits on the script line itself. Type a code or a
 *  description; the list is server-side because the full ICD-10 release is far
 *  too large to ship to the browser.
 *
 *  Two things were missing, and the endpoints written to supply them had never
 *  been called.
 *
 *  **The local table is a subset, not the release.** Searching for a code it
 *  does not hold used to end at "No matching diagnosis", which is a dead end in
 *  the one field a claim cannot go out without. The server distinguishes "we
 *  hold no description for this" from "this is not a real code" — the first is
 *  perfectly claimable — so a well-formed code in a real chapter is now offered
 *  with the caveat rather than refused.
 *
 *  **Nobody remembers codes.** Browsing by body system is what makes this a
 *  reference instead of a field you have to guess at, and the chapter list was
 *  published for exactly that.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { DiagnosisCode } from "../types";

interface Chapter { range: string; title: string }

/** What the server can say about a code it was handed. */
interface Verdict {
  valid_structure: boolean; chapter: string | null; acceptable: boolean;
  in_local_table: boolean; description: string; note: string;
}

export default function DiagnosisPicker({ value, onChange, autoFocus }: {
  value: string;
  onChange: (code: string) => void;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DiagnosisCode[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [chosen, setChosen] = useState<DiagnosisCode | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chapter, setChapter] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  // Resolve an existing code to its description so the line reads properly.
  useEffect(() => {
    if (!value) { setChosen(null); return; }
    if (chosen?.code === value) return;
    api.get<DiagnosisCode>(`/api/claiming/diagnoses/${encodeURIComponent(value)}`)
      .then(setChosen).catch(() => setChosen(null));
  }, [value]);

  // The chapter list is small and fixed, so it is fetched once and kept.
  useEffect(() => {
    api.get<Chapter[]>("/api/claiming/diagnoses/chapters")
      .then(setChapters).catch(() => setChapters([]));
  }, []);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); setVerdict(null); return; }
    const t = setTimeout(() => {
      const q = new URLSearchParams({ q: query.trim() });
      if (chapter) q.set("chapter", chapter);
      api.get<DiagnosisCode[]>(`/api/claiming/diagnoses?${q}`)
        .then((r) => {
          setResults(r); setActive(0);
          // Nothing found locally is not the same as nothing valid. Ask what
          // the code actually is before telling somebody they cannot use it.
          if (r.length === 0) {
            api.get<Verdict>(
              `/api/claiming/diagnoses/validate?code=${encodeURIComponent(query.trim())}`)
              .then(setVerdict).catch(() => setVerdict(null));
          } else {
            setVerdict(null);
          }
        })
        .catch(() => setResults([]));
    }, 180);
    return () => clearTimeout(t);
  }, [query, chapter]);

  useEffect(() => {
    function onPointer(e: MouseEvent) {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, []);

  function pick(code: DiagnosisCode) {
    onChange(code.code);
    setChosen(code);
    setQuery("");
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    if (e.key === "Enter") { e.preventDefault(); pick(results[active]); }
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
  }

  return (
    <div className="dx-picker" ref={boxRef}>
      {chosen ? (
        <div className="dx-chosen">
          <span className="mono dx-code">{chosen.code}</span>
          <span className="dx-desc" title={chosen.description}>{chosen.description}</span>
          <button type="button" className="ghost small" onClick={() => { onChange(""); setChosen(null); }}>
            Change
          </button>
        </div>
      ) : (
        <>
          <input
            autoFocus={autoFocus}
            value={query}
            placeholder="ICD-10 code or diagnosis…"
            onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
          />
          {open && results.length > 0 && (
            <div className="dx-list">
              {results.map((r, i) => (
                <div
                  key={r.code}
                  className={`dx-option${i === active ? " active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(r)}
                >
                  <span className="mono dx-code">{r.code}</span>
                  <span className="dx-desc">{r.description}</span>
                </div>
              ))}
            </div>
          )}
          {open && query.trim().length >= 2 && results.length === 0 && (
            <div className="dx-list">
              {verdict?.acceptable ? (
                <div
                  className="dx-option"
                  onClick={() => {
                    onChange(query.trim().toUpperCase());
                    setChosen({
                      code: query.trim().toUpperCase(),
                      description: verdict.description
                        || "no description held locally",
                    } as DiagnosisCode);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <span className="mono dx-code">{query.trim().toUpperCase()}</span>
                  <span className="dx-desc">
                    Use it anyway &mdash; well formed and in a real chapter
                    <div className="muted small">{verdict.note}</div>
                  </span>
                </div>
              ) : (
                <div className="dx-empty">
                  {verdict && !verdict.valid_structure
                    ? "That is not the shape of an ICD-10 code."
                    : verdict && !verdict.chapter
                      ? "That code sits in no ICD-10 chapter."
                      : "No matching diagnosis"}
                </div>
              )}
            </div>
          )}

          {/* Browsing by body system, which is how somebody who does not
              already know the code finds one. */}
          {open && chapters.length > 0 && (
            <select className="dx-chapter" value={chapter}
                    onChange={(e) => setChapter(e.target.value)}>
              <option value="">Any body system</option>
              {chapters.map((c) => (
                <option key={c.range} value={c.range}>
                  {c.title} ({c.range})
                </option>
              ))}
            </select>
          )}
        </>
      )}
    </div>
  );
}
