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
import { useState } from "react";
import { CheckCircle, UploadSimple, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import FileDrop from "./FileDrop";
import { useToast } from "./Toast";

interface Line {
  row: number; key: string; name: string; action: string; reason: string;
  product_id: number | null; changes: Record<string, [number | null, number]>;
  quantity: number; batch: string; expiry: string | null;
}
interface Result {
  applied: boolean;
  columns_read: string[]; columns_ignored: string[];
  rows: number; create: number; update: number; skip: number; refuse: number;
  units: number; lines: Line[]; truncated: boolean;
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
  const toast = useToast();

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
      </div>

      <FileDrop
        label="Catalogue or delivery note (CSV)"
        hint="Stock code, description, cost, selling price, and quantity, batch
              and expiry where you are receiving stock. Column names are matched
              loosely, so a supplier's own export usually works as it comes."
        onFile={(text, fileName) => preview(text, fileName)}
      />

      {result && (
        <>
          <div className="wc-bands" style={{ marginTop: 14 }}>
            <div className="wl-stat">
              <b>{result.rows}</b><span>rows in {name || "the file"}</span>
            </div>
            <div className="wl-stat">
              <b className="tone-ok">{result.create}</b><span>new products</span>
            </div>
            <div className="wl-stat">
              <b>{result.update}</b><span>to change</span>
            </div>
            <div className={`wl-stat${result.refuse ? " wc-abandoned" : ""}`}>
              <b className={result.refuse ? "tone-danger" : undefined}>
                {result.refuse}
              </b>
              <span>will not load</span>
            </div>
            {result.units > 0 && (
              <div className="wl-stat">
                <b>{result.units.toLocaleString()}</b><span>units to receive</span>
              </div>
            )}
          </div>

          <p className="muted small">
            Columns read: {result.columns_read.join(", ") || "none"}.
            {result.columns_ignored.length > 0 && (
              <> Ignored: {result.columns_ignored.slice(0, 8).join(", ")}
                {result.columns_ignored.length > 8
                  && ` and ${result.columns_ignored.length - 8} more`}.</>
            )}
          </p>

          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th style={{ width: "4rem" }}>Row</th>
                  <th>Product</th>
                  <th style={{ width: "8rem" }}>What happens</th>
                  <th className="num">Cost</th>
                  <th className="num">Price</th>
                  <th className="num">Qty</th>
                  <th>Batch</th>
                  <th>Why not</th>
                </tr>
              </thead>
              <tbody>
                {result.lines.map((l) => (
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
                        : <span className="muted">—</span>}
                    </td>
                    <td className="num">
                      {l.changes.price
                        ? <>{l.changes.price[0] !== null
                              && <s className="muted">{money(l.changes.price[0])}</s>}{" "}
                            {money(l.changes.price[1])}</>
                        : <span className="muted">—</span>}
                    </td>
                    <td className="num">
                      {l.quantity ? l.quantity.toLocaleString()
                        : <span className="muted">—</span>}
                    </td>
                    <td className="mono small">
                      {l.batch || <span className="muted">—</span>}
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
            <p className="alert ok">
              <CheckCircle size={16} weight="fill" />
              <span>{result.message}</span>
            </p>
          ) : (
            <>
              {result.refuse > 0 && (
                <p className="alert warn">
                  <Warning size={16} weight="fill" />
                  <span>
                    {result.refuse} row{result.refuse === 1 ? "" : "s"} will not
                    load. Loading the rest is fine — the file can be corrected
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
