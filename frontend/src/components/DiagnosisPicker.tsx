/** ICD-10 picker.
 *
 *  A claim line without a diagnosis is rejected by the scheme, so this is not
 *  optional metadata — it sits on the script line itself. Type a code or a
 *  description; the list is server-side because the full ICD-10 release is far
 *  too large to ship to the browser.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { DiagnosisCode } from "../types";

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
  const boxRef = useRef<HTMLDivElement>(null);

  // Resolve an existing code to its description so the line reads properly.
  useEffect(() => {
    if (!value) { setChosen(null); return; }
    if (chosen?.code === value) return;
    api.get<DiagnosisCode>(`/api/claiming/diagnoses/${encodeURIComponent(value)}`)
      .then(setChosen).catch(() => setChosen(null));
  }, [value]);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api.get<DiagnosisCode[]>(`/api/claiming/diagnoses?q=${encodeURIComponent(query.trim())}`)
        .then((r) => { setResults(r); setActive(0); })
        .catch(() => setResults([]));
    }, 180);
    return () => clearTimeout(t);
  }, [query]);

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
            <div className="dx-list"><div className="dx-empty">No matching diagnosis</div></div>
          )}
        </>
      )}
    </div>
  );
}
