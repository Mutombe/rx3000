/** A file field you can drop onto.
 *
 *  The native control is a grey button labelled "No file chosen" that cannot be
 *  styled, gives no hint about what it will accept, and offers nowhere to drop
 *  the file somebody has just downloaded from their bank. Both places that took
 *  a file used it, and both wanted the same three things: say what is accepted,
 *  accept a drop, and show what was read.
 *
 *  It hands back the file's text rather than the File, because that is what both
 *  callers do with it — one reads a bank statement, the other a price list, and
 *  neither wants a FileReader of its own.
 *
 *  The input itself is kept in the DOM rather than replaced with a click
 *  handler: it is what makes the control reachable by keyboard and what a screen
 *  reader announces. It is visually hidden and the label is the target, which is
 *  the plain way to do this and needs no ARIA.
 */
import { DragEvent, useId, useRef, useState } from "react";

interface Props {
  /** e.g. ".csv,text/csv" — also shown to the user, so it is never a mystery. */
  accept?: string;
  /** Called with the file's text and its name. */
  onFile: (text: string, name: string) => void;
  /** Overrides the "CSV file" wording where something else is expected. */
  label?: string;
  hint?: string;
  /** Refused above this, in megabytes. A browser reading a 300MB file as text
   *  simply stops responding, which reads as a crash rather than a limit. */
  maxMb?: number;
}

export default function FileDrop({
  accept = ".csv,text/csv", onFile, label = "CSV file", hint, maxMb = 20,
}: Props) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [chosen, setChosen] = useState<{ name: string; size: number } | null>(null);
  const [error, setError] = useState("");

  function accepts(file: File): boolean {
    if (!accept.trim()) return true;
    const wanted = accept.split(",").map((a) => a.trim().toLowerCase()).filter(Boolean);
    const name = file.name.toLowerCase();
    return wanted.some((a) => (a.startsWith(".")
      ? name.endsWith(a)
      // A wildcard like text/* as well as an exact type. Browsers are
      // inconsistent about the type they report for CSV — text/csv,
      // application/vnd.ms-excel, or nothing at all, so the extension is
      // checked first and this is the fallback.
      : a.endsWith("/*")
        ? file.type.startsWith(a.slice(0, -1))
        : file.type === a));
  }

  function take(file: File | undefined) {
    setError("");
    if (!file) return;
    if (!accepts(file)) {
      setError(`That is not ${accept.includes("csv") ? "a CSV" : "an accepted"} file. `
        + `Expected ${accept}.`);
      return;
    }
    if (file.size > maxMb * 1024 * 1024) {
      setError(`That file is ${(file.size / 1024 / 1024).toFixed(1)}MB, and the limit `
        + `is ${maxMb}MB. Split it, or paste the part you need below.`);
      return;
    }
    file.text()
      .then((text) => {
        setChosen({ name: file.name, size: file.size });
        onFile(text, file.name);
      })
      .catch(() => setError("That file could not be read."));
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files?.[0]);
  }

  return (
    <div className="fd">
      <label
        htmlFor={id}
        className={`fd-zone${over ? " is-over" : ""}${chosen ? " is-set" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <input
          ref={input}
          id={id}
          type="file"
          accept={accept}
          className="fd-input"
          onChange={(e) => take(e.target.files?.[0])}
        />
        {chosen ? (
          <>
            <span className="fd-name">{chosen.name}</span>
            <span className="fd-meta">
              {(chosen.size / 1024).toFixed(0)} KB · read
            </span>
            <span className="fd-swap">Choose another, or drop one here</span>
          </>
        ) : (
          <>
            <span className="fd-name">Drop a {label} here</span>
            <span className="fd-meta">or click to choose one</span>
            {hint && <span className="fd-swap">{hint}</span>}
          </>
        )}
      </label>
      {error && <p className="fd-error">{error}</p>}
    </div>
  );
}
