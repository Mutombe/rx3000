/** The exchange rate, where the person who knows it can set it.
 *
 *  Zimbabwe trades in USD and ZWG, and the rate between them moves. That number
 *  was reachable only through the API, which meant the one figure a pharmacy
 *  adjusts most often was the one figure it could not adjust.
 *
 *  Rates are append-only on the server and this screen does not pretend
 *  otherwise: there is no edit and no delete, a correction is a new entry, and
 *  the history stays visible underneath. A sale settled last week has to keep
 *  last week's rate or historical totals drift silently, and the only way to
 *  guarantee that is to make the past unwritable.
 */
import { useEffect, useState } from "react";
import { api, fmtDateTime, errorText  } from "../api";
import { useToast } from "./Toast";
import { TableSkeleton } from "./Skeleton";

interface Currency {
  code: string; symbol: string; decimals: number; rate: number; is_base: boolean;
}
interface State { base: string; currencies: Currency[]; multi_currency: boolean }
interface Rate {
  id: number; currency_code: string; units_per_base: number;
  effective_from: string; source: string; note: string;
}

export default function CurrencyRates() {
  const toast = useToast();
  const [state, setState] = useState<State | null>(null);
  const [history, setHistory] = useState<Rate[] | null>(null);
  const [code, setCode] = useState("");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api.get<State>("/api/currency").then((s) => {
      setState(s);
      // Default to the first currency that is not the base — on a two-currency
      // installation that is the only one anybody ever sets.
      setCode((c) => c || s.currencies.find((x) => !x.is_base)?.code || "");
    }).catch(() => {});
    api.get<Rate[]>("/api/currency/rates?limit=25").then(setHistory).catch(() => setHistory([]));
  }
  useEffect(load, []);

  async function publish() {
    const units = Number(value);
    if (!Number.isFinite(units) || units <= 0) {
      toast.error("Enter how many units of that currency one " + (state?.base ?? "unit") + " buys.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/currency/rates", {
        currency_code: code, units_per_base: units, source: "manual", note: note.trim(),
      });
      toast.ok(`1 ${state?.base} is now ${units} ${code}. Earlier sales keep the rate they were settled at.`);
      setValue(""); setNote("");
      load();
    } catch (e: any) {
      toast.error(errorText(e, "That rate could not be published."));
    } finally {
      setBusy(false);
    }
  }

  const base = state?.currencies.find((c) => c.is_base);
  const others = state?.currencies.filter((c) => !c.is_base) ?? [];

  return (
    <>
      <div className="card">
        <h3>Currencies</h3>
        {!state ? (
          <TableSkeleton rows={2} cols={3} />
        ) : (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              Prices are held in {base?.code}. Everything else is converted for display
              and at the till, at the rate in force when the sale is settled.
            </p>
            <div className="rate-grid">
              {state.currencies.map((c) => (
                <div key={c.code} className="rate-card">
                  <div className="rate-code">
                    {c.code} <span className="muted">{c.symbol}</span>
                  </div>
                  <div className="rate-value mono">
                    {c.is_base ? "base" : c.rate ? c.rate.toFixed(4) : "no rate set"}
                  </div>
                  {!c.is_base && (
                    <div className="muted" style={{ fontSize: ".78rem" }}>
                      per 1 {state.base}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {others.length > 0 && (
        <div className="card">
          <h3>Publish a rate</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            How many units of the currency one {state?.base} buys. Rates are never
            edited — publishing a correction adds an entry, so what a past sale was
            settled at stays true.
          </p>
          <div className="form-row">
            <div className="field">
              <label>Currency</label>
              <select value={code} onChange={(e) => setCode(e.target.value)}>
                {others.map((c) => (
                  <option key={c.code} value={c.code}>{c.code} — {c.symbol}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Units per 1 {state?.base}</label>
              <input
                type="number" step="0.0001" min="0" value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") publish(); }}
                placeholder="e.g. 26.5000"
              />
            </div>
            <div className="field">
              <label>Note</label>
              <input
                value={note} onChange={(e) => setNote(e.target.value)}
                placeholder="Where this rate came from"
              />
            </div>
          </div>
          <button className="small" onClick={publish} disabled={busy || !code}>
            {busy ? "Publishing…" : "Publish rate"}
          </button>
        </div>
      )}

      <div className="card">
        <h3>Rate history</h3>
        {history === null ? (
          <TableSkeleton rows={5} cols={4} />
        ) : history.length === 0 ? (
          <div className="empty">No rate has been published yet</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Currency</th>
                <th style={{ textAlign: "right" }}>Units per base</th>
                <th>In force from</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td>{r.currency_code}</td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {r.units_per_base.toFixed(4)}
                  </td>
                  <td>{fmtDateTime(r.effective_from)}</td>
                  <td className="muted">{r.note || r.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
