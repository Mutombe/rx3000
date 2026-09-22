/** Load a catalogue, or a delivery, from a spreadsheet.
 *
 *  The price file beside this can only update what is already on the shelf.
 *  This is the other half: a pharmacy arriving from another system, opening a
 *  second shop, or taking on a supplier's range had no way in except typing
 *  products one at a time, and a catalogue is four thousand lines.
 *
 *  Two steps, always. Nothing is written until somebody has read what would
 *  happen — because a file that quietly makes eight hundred duplicate products
 *  is far worse than one that was refused, and the refusal is the cheap half of
 *  that trade.
 *
 *  What the preview shows is not a summary. It is the rows: what would be
 *  created, what would change and from what, and — the part that matters —
 *  every row that will not load with the reason in a sentence.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle, DownloadSimple, UploadSimple, Warning,
} from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import FileDrop from "./FileDrop";
import { FilterToggle } from "./Filters";
import { useToast } from "./Toast";

interface Line {
  row: number; key: string; name: string; action: string; reason: string;
  product_id: number | null; changes: Record<string, [number | null, number]>;
  quantity: number; batch: string; expiry: string | null; warning?: string;
}
/** A figure in the file that cannot be right, carried outside `lines`. */
interface Question { row: number; name: string; says: string; }
interface Result {
  applied: boolean;
  columns_read: string[]; columns_ignored: string[];
  rows: number; create: number; update: number; skip: number; refuse: number;
  units: number; lines: Line[]; truncated: boolean;
  questions?: Question[];
  created?: number; updated?: number; batches?: number; message?: string;
}

const TONE: Record<string, string> = {
  create: "ok", update: "warn", skip: "muted", refuse: "bad",
};
const VERB: Record<string, string> = {
  create: "new product", update: "change", skip: "no change", refuse: "will not load",
};

export default function StockUpload({ onDone }: { onDone?: () => void }) {
  const [csv, setCsv] = useState("");
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  // A 2MB workbook takes a few seconds to turn into rows, and a screen that
  // sits still for that long reads as one that did not accept the file.
  const [reading, setReading] = useState(false);
  const toast = useToast();
  /** Which rows of the preview to show. "Will not load" is the one somebody
   *  actually wants alone: four hundred rows are listed and twelve are the
   *  reason they are still reading. */
  const [only, setOnly] = useState<string>("");
  const [q, setQ] = useState("");

  /** The example file, fetched rather than linked: a plain href cannot carry
   *  the Authorization header, and the usual workaround writes the token into
   *  every access log it passes through. Same reasoning as ExportButton. */
  async function getExample() {
    try {
      const file = await api.blob("/api/stock/upload/example");
      const url = URL.createObjectURL(file.body);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename || "rx5000-stock-upload-example.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      toast.error(errorText(e, "The example file could not be fetched."));
    }
  }

  async function preview(text: string, fileName: string) {
    setCsv(text);
    setName(fileName);
    setResult(null);
    try {
      const r = await api.post<Result>("/api/stock/upload",
                                       { csv_text: text, apply: false });
      setResult(r);
    } catch (e) {
      // The server refuses a file with no identifying column and says which
      // ones it would take. Shown as written.
      toast.error(errorText(e, "That file could not be read."));
    }
  }

  async function load() {
    try {
      const r = await api.post<Result>("/api/stock/upload", {
        csv_text: csv, apply: true, reference: reference.trim(),
      });
      setResult(r);
      toast.ok(r.message || "Loaded.");
      onDone?.();
    } catch (e) {
      toast.error(errorText(e, "That file could not be loaded."));
    }
  }

  const willWrite = (result?.create ?? 0) + (result?.update ?? 0) > 0;

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (result?.lines ?? []).filter((l) =>
      (!only || l.action === only)
      && (!needle
          || l.name.toLowerCase().includes(needle)
          || l.key.toLowerCase().includes(needle)
          || String(l.row) === needle));
  }, [result, only, q]);

  /** A tile presses to show its own rows, and presses again to show them all. */
  function pick(action: string) {
    setOnly((was) => (was === action ? "" : action));
    setQ("");
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>Upload stock</h3>
          <span className="muted small">
            New products and existing ones, with quantities where the file
            carries them. Nothing is written until you have read what it would
            do.
          </span>
        </div>
        {/* THE COMMONEST WAY THIS FAILED WAS NOT KNOWING WHAT TO SEND.
            The columns were named in a hint under the drop zone and the rest
            was guesswork, so a pharmacy's first file was usually refused and
            the second was a phone call. The example is generated from the
            same map that reads a file, so it cannot drift away from what the
            parser accepts. */}
        <button type="button" className="btn secondary" onClick={getExample}>
          <DownloadSimple size={14} weight="bold" /> Example file
        </button>
      </div>

      <FileDrop
        accept=".csv,text/csv,.xlsx,.xlsm"
        label="Catalogue or delivery note"
        hint="Stock code, description, cost, selling price, and quantity, batch
              and expiry where you are receiving stock. Column names are matched
              loosely, so a supplier's own export usually works as it comes."
        onFile={(text, fileName, file) => {
          // A workbook goes to the server to be turned into rows first. Every
          // supplier and every legacy system sends one, and the pharmacy's own
          // answer was to open it in Excel and save as CSV, which is a step
          // where dates silently become American and a leading zero is eaten
          // off a stock code.
          if (!text && file) {
            const form = new FormData();
            form.append("file", file);
            setReading(true);
            api.post<{ csv_text: string; sheet: string; sheets: string[]; rows: number }>(
              "/api/stock/upload/spreadsheet", form)
              .then((r) => {
                if (r.sheets.length > 1) {
                  // A workbook with four sheets is a question, and reading the
                  // first one silently is how somebody imports last year's
                  // price list without noticing.
                  toast.warn(`That workbook has ${r.sheets.length} sheets. `
                             + `Read ${r.sheet}, which had `
                             + `${r.rows.toLocaleString()} rows.`);
                }
                preview(r.csv_text, fileName);
              })
              .catch((e) => toast.error(errorText(e, "That spreadsheet could not be read.")))
              .finally(() => setReading(false));
            return;
          }
          preview(text, fileName);
        }}
      />

      {reading && (
        <p className="muted" style={{ marginTop: 12 }}>
          Reading the spreadsheet…
        </p>
      )}

      {result && (
        <>
          {/* THREE OF THESE ARE CONTROLS AND TWO ARE READINGS.
              All five were divs carrying .wl-stat, which sets a pointer
              cursor and a hover state because every tile filters on the queue
              it came from. Here the row count and the unit total have nothing
              to narrow to, so they looked clickable and were not. The three
              that answer "show me those rows" are buttons. */}
          <div className="wc-bands" style={{ marginTop: 14 }}>
            <button type="button"
                    className={`wl-stat rc-pick${only ? "" : " is-on"}`}
                    aria-pressed={!only}
                    onClick={() => pick("")}>
              <b>{result.rows}</b>
              <span>
                rows in {name || "the file"}
                <em className="rc-pick-do">
                  {only ? "show all of them" : "showing all of them"}
                </em>
              </span>
            </button>
            <button type="button"
                    className={`wl-stat rc-pick${only === "create" ? " is-on" : ""}`}
                    aria-pressed={only === "create"} disabled={!result.create}
                    onClick={() => pick("create")}>
              <b className="tone-ok">{result.create}</b>
              <span>
                New products
                {result.create > 0 && (
                  <em className="rc-pick-do">
                    {only === "create" ? "showing only these" : "show only these"}
                  </em>
                )}
              </span>
            </button>
            <button type="button"
                    className={`wl-stat rc-pick${only === "update" ? " is-on" : ""}`}
                    aria-pressed={only === "update"} disabled={!result.update}
                    onClick={() => pick("update")}>
              <b>{result.update}</b>
              <span>
                To change
                {result.update > 0 && (
                  <em className="rc-pick-do">
                    {only === "update" ? "showing only these" : "show only these"}
                  </em>
                )}
              </span>
            </button>
            {/* The one anybody came here to look at. */}
            <button type="button"
                    className={`wl-stat rc-pick${result.refuse ? " wc-abandoned" : ""}`
                               + `${only === "refuse" ? " is-on" : ""}`}
                    aria-pressed={only === "refuse"} disabled={!result.refuse}
                    onClick={() => pick("refuse")}>
              <b className={result.refuse ? "tone-danger" : undefined}>
                {result.refuse}
              </b>
              <span>
                Will not load
                {result.refuse > 0 && (
                  <em className="rc-pick-do">
                    {only === "refuse" ? "showing only these" : "show me which"}
                  </em>
                )}
              </span>
            </button>
            {result.units > 0 && (
              <div className="wl-stat rc-read">
                <b>{result.units.toLocaleString()}</b><span>Units to receive</span>
              </div>
            )}
          </div>

          {/* BEFORE the column note and before the table, because `lines`
              stops at 400 rows and the row that prompted this check was
              11,701 of 16,038. A warning that can only be found by scrolling
              a truncated table is one nobody is ever shown. */}
          {result.questions && result.questions.length > 0 && (
            <section className="su-questions">
              <h4>
                {result.questions.length} figure
                {result.questions.length === 1 ? "" : "s"} in this file
                {result.questions.length === 1 ? " does" : " do"} not look right
              </h4>
              <p className="muted small">
                Loaded exactly as sent, where the row loads at all. Nothing here
                is changed for you: a price corrected quietly is a price that
                comes back on the next upload.
              </p>
              <ul>
                {result.questions.map((q) => (
                  <li key={q.row}>
                    <b>{q.name || `Row ${q.row}`}</b>
                    <span className="muted"> · row {q.row.toLocaleString()}</span>
                    <div>{q.says}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <p className="muted small">
            Columns read: {result.columns_read.join(", ") || "none"}.
            {result.columns_ignored.length > 0 && (
              <> Ignored: {result.columns_ignored.slice(0, 8).join(", ")}
                {result.columns_ignored.length > 8
                  && ` and ${result.columns_ignored.length - 8} more`}.</>
            )}
          </p>

          {/* Four hundred rows listed and no way to find one. Somebody is
              usually looking for a line they know the name of, or checking
              what happened to row 2,317 that the file's own author asked
              about. */}
          <div className="dt-filters">
            <input type="search" className="filter-search" value={q}
                   placeholder="Find a line by name, code or row number…"
                   onChange={(e) => setQ(e.target.value)} />
            <FilterToggle checked={only === "refuse"}
                          onChange={(on) => setOnly(on ? "refuse" : "")}
                          hint="Only the rows that will not load">
              Will not load
            </FilterToggle>
            {(q || only) && (
              <button className="ghost small filter-clear"
                      onClick={() => { setQ(""); setOnly(""); }}>
                Clear
              </button>
            )}
            <span className="dt-count muted">
              {shown.length} of {result.lines.length}
            </span>
          </div>

          <div className="dt-scroll">
            <table className="dt su-table">
              <thead>
                <tr>
                  <th className="col-row">Row</th>
                  <th>Product</th>
                  {/* col-code (7rem) cut the heading itself: a column has to be as
                      wide as the question it asks. */}
                  <th className="col-city">What happens</th>
                  <th className="num col-money">Cost</th>
                  <th className="num col-money">Price</th>
                  <th className="num col-count">Qty</th>
                  {/* Carries the expiry under the lot number, and "exp 30 Jun, 2028"
                      is wider than the lot is. */}
                  <th className="col-city">Batch</th>
                  <th>Why not</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((l) => (
                  <tr key={l.row}
                      className={l.action === "refuse" ? "row-danger"
                        : l.action === "create" ? "row-ok" : undefined}>
                    <td className="muted">{l.row}</td>
                    <td>
                      <b>{l.name || l.key}</b>
                      {l.key !== l.name && (
                        <div className="muted small mono">{l.key}</div>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${TONE[l.action]}`}>
                        {VERB[l.action]}
                      </span>
                    </td>
                    <td className="num">
                      {l.changes.cost
                        ? <>{l.changes.cost[0] !== null
                              && <s className="muted">{money(l.changes.cost[0])}</s>}{" "}
                            {money(l.changes.cost[1])}</>
                        : <span className="muted">unchanged</span>}
                    </td>
                    <td className="num">
                      {l.changes.price
                        ? <>{l.changes.price[0] !== null
                              && <s className="muted">{money(l.changes.price[0])}</s>}{" "}
                            {money(l.changes.price[1])}</>
                        : <span className="muted">unchanged</span>}
                    </td>
                    <td className="num">
                      {/* A catalogue line carries no quantity, which is not
                          a gap in the file. */}
                      {l.quantity ? l.quantity.toLocaleString()
                        : <span className="muted">none</span>}
                    </td>
                    <td className="mono small">
                      {l.batch || <span className="muted">none</span>}
                      {l.expiry && (
                        <div className="muted">exp {fmtDate(l.expiry)}</div>
                      )}
                    </td>
                    <td className="wrap muted small">{l.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.truncated && (
            <p className="muted small">
              The first 400 rows are shown. All of them load.
            </p>
          )}

          {result.applied ? (
            <>
              <p className="alert ok">
                <CheckCircle size={16} weight="fill" />
                <span>{result.message}</span>
              </p>
              {/* WHERE THE STOCK WENT.
                  The screen said "247 products created, 1,880 units received"
                  and ended there, so the one question straight afterwards,
                  "did that land the way I meant", had no answer on it. These
                  are the three screens that hold what the file just made. */}
              <div className="su-after">
                <Link to="/stock?tab=products" className="btn secondary">
                  See the products
                </Link>
                {(result.batches ?? 0) > 0 && (
                  <Link to="/stock?tab=batches" className="btn secondary">
                    The batches it created
                  </Link>
                )}
                {(result.batches ?? 0) > 0 && (
                  <Link to="/stock?tab=movements" className="btn secondary">
                    The stock it received
                  </Link>
                )}
              </div>
            </>
          ) : (
            <>
              {result.refuse > 0 && (
                <p className="alert warn">
                  <Warning size={16} weight="fill" />
                  <span>
                    {result.refuse} row{result.refuse === 1 ? "" : "s"} will not
                    load. Loading the rest is fine. The file can be corrected
                    and uploaded again, and anything already loaded is left
                    alone the second time.
                  </span>
                </p>
              )}
              <div className="form-row">
                <div className="field span-6">
                  <label>Reference <span className="muted">optional</span></label>
                  <input value={reference} maxLength={40}
                         onChange={(e) => setReference(e.target.value)}
                         placeholder="Delivery note 88213" />
                  <span className="hint">
                    Written onto every batch and movement this creates, so the
                    stock can be traced back to the paperwork.
                  </span>
                </div>
              </div>
              <BusyButton className="btn primary" onClick={load}
                          disabled={!willWrite} icon={UploadSimple}
                          busyLabel="Loading…">
                {willWrite
                  ? `Load ${result.create} new and change ${result.update}`
                  : "Nothing in this file to load"}
              </BusyButton>
            </>
          )}
        </>
      )}
    </div>
  );
}
