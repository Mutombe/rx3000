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
import { Block, Figure, GhostRows } from "./Skeleton";
import Select from "./Select";
import Th from "./Th";

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
  const [historyUnknown, setHistoryUnknown] = useState(false);
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
    // Deliberately silent: this screen is only reachable where currencies
    // are already configured, and it renders its own empty state.
    }).catch(() => {});
    api.get<Rate[]>("/api/currency/rates?limit=25")
      .then((r) => { setHistory(r); setHistoryUnknown(false); })
      // "No rate has been published yet" on the screen a shop's whole price
      // list hangs off is not a sentence to say on a guess.
      .catch(() => { setHistory([]); setHistoryUnknown(true); });
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
        {/* SCOPED LOADING.
            A grey table stood where a grid of rate cards goes, which is neither
            the right shape nor the right height, and it hid a sentence that is
            true of this pharmacy whatever the rate happens to be. Only the codes
            and the figures are fetched now. */}
        <p className="muted" style={{ marginTop: 0 }}>
          Prices are held in <Figure ready={!!state} w="4ch">{base?.code}</Figure>.
          Everything else is converted for display
          and at the till, at the rate in force when the sale is settled.
        </p>
        <div className="rate-grid">
          {!state && [0, 1].map((i) => (
            <div key={i} className="rate-card" aria-busy="true">
              <div className="rate-code"><Block w="7ch" h="1em" className="sk-val" /></div>
              <div className="rate-value mono"><Block w="8ch" h="1em" className="sk-val" /></div>
              <div className="muted" style={{ fontSize: ".78rem" }}>
                <Block w="9ch" h="1em" className="sk-val" />
              </div>
            </div>
          ))}
          {(state?.currencies ?? []).map((c) => (
            <div key={c.code} className="rate-card">
              <div className="rate-code">
                {c.code} <span className="muted">{c.symbol}</span>
              </div>
              <div className="rate-value mono">
                {c.is_base ? "base" : c.rate ? c.rate.toFixed(4) : "No rate set"}
              </div>
              {!c.is_base && (
                <div className="muted" style={{ fontSize: ".78rem" }}>
                  per 1 {state?.base}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* The form is kept up while the currencies are read: its three labels and
          its button are written here, and a control that appears a beat later is
          one somebody has already clicked past. */}
      {(!state || others.length > 0) && (
        <div className="card">
          <h3>Publish a rate</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            How many units of the currency one{" "}
            <Figure ready={!!state} w="4ch">{state?.base}</Figure> buys. Rates are never
            edited, publishing a correction adds an entry, so what a past sale was
            settled at stays true.
          </p>
          <div className="form-row">
            <div className="field">
              <label>Currency</label>
              <Select
                value={String(code ?? "")}
                onChange={(__value) => setCode(__value)}
                options={others.map((c) => ({ value: String(c.code), label: `${c.code} (${c.symbol})` }))}
              />
            </div>
            <div className="field">
              <label>Units per 1 <Figure ready={!!state} w="4ch">{state?.base}</Figure></label>
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
        {/* The head is written here and the same on every visit, so it is drawn
            under the heading straight away. "No rate has been published yet" is
            still the last arm of the four: a shop's whole price list hangs off
            that sentence and it must never be said on a guess. */}
        {historyUnknown ? (
          <div className="empty">
            The rate history could not be read. That is not the same as no
            rate having been published.
          </div>
        ) : history !== null && history.length === 0 ? (
          <div className="empty">No rate has been published yet</div>
        ) : (
          <table>
            <thead>
              <tr>
                <Th>Currency</Th>
                <Th className="num">Units per base</Th>
                <Th>In force from</Th>
                <Th>Source</Th>
              </tr>
            </thead>
            {history === null ? (
              <GhostRows cols={4} rows={5}
                         widths={["40%", "50%", "70%", "60%"]} />
            ) : (
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td>{r.currency_code}</td>
                  {/* `num`, not an inline style. These were the only two
                      hand-placed alignments left in the product, and they
                      right-aligned without the lining, tabular figures every
                      other numeric column gets — so a rate column did not
                      line up with itself. */}
                  <td className="num mono">
                    {r.units_per_base.toFixed(4)}
                  </td>
                  <td>{fmtDateTime(r.effective_from)}</td>
                  <td className="muted">{r.note || r.source}</td>
                </tr>
              ))}
            </tbody>
            )}
          </table>
        )}
      </div>
    </>
  );
}
