/** The figures along the bottom of a script, read before it is finished.
 *
 *  The incumbent puts a dozen of them there, and the reason is not
 *  bookkeeping: a dispenser reads them at a glance to know the script is right
 *  *before* handing it over. Margin belongs here rather than in a report next
 *  month, because it is how a good dispenser notices they are about to sell
 *  below cost, and by the time it reaches a report the medicine has gone.
 *
 *  The endpoint has computed all of it since it was written and nothing called
 *  it. So the whole thing existed except the one part that makes it useful:
 *  being on the screen where the decision is.
 *
 *  What is shown is what changes a decision. Gross, what the scheme carries,
 *  what the patient actually pays, and the margin — with the per-line detail
 *  folded away, because one bad line inside a profitable script is invisible in
 *  a total and is exactly what somebody occasionally needs to open.
 */
import { useEffect, useState } from "react";
import { CaretDown, CaretRight, Warning } from "@phosphor-icons/react";
import { api, money } from "../api";
import { TERMS, patientOwes } from "../terms";

interface Line {
  product_id: number; description: string; quantity: number;
  gross: number; cost: number; claim: number; no_claim: boolean;
  margin_percent: number;
}
interface Totals {
  rx_gross: number; gross: number; nett: number; no_claim: number;
  surcharge: number; vat: number; levy: number; tot_levy: number;
  claim: number; cost: number; profit: number; profit_percent: number;
  patient_pays: number;
}
interface Reply { lines: Line[]; totals: Totals; scheme: string; warning: string }

/** The priced lines for a basket, fetched once and shared.
 *
 *  Extracted from the component because the same numbers are wanted in two
 *  places: along the bottom of the script, and on each line as it is built.
 *  Two components each doing their own POST would price the same basket twice
 *  on every keystroke, and could disagree with each other for a render — which
 *  on a margin figure somebody is about to grant a discount against is worse
 *  than not showing it.
 */
export function useScriptPricing(
  items: { product_id: number; quantity: number; no_claim?: boolean }[],
  medicalAidId?: number | null,
): Reply | null {
  const [data, setData] = useState<Reply | null>(null);
  const key = JSON.stringify(items) + `|${medicalAidId ?? ""}`;
  useEffect(() => {
    if (!items.length) { setData(null); return; }
    let live = true;
    api.post<Reply>("/api/script-totals", {
      items, medical_aid_id: medicalAidId ?? null,
    })
      .then((d) => { if (live) setData(d); })
      // A pricing figure that cannot be worked out must not stop anybody
      // dispensing. It simply does not appear.
      .catch(() => { if (live) setData(null); });
    return () => { live = false; };
  }, [key]);
  return data;
}

export default function ScriptTotals({ items, medicalAidId, data: given, variant = "bar" }: {
  /** What is on the script now. Recomputed as it changes. */
  items: { product_id: number; quantity: number; no_claim?: boolean }[];
  medicalAidId?: number | null;
  /** The basket already priced by `useScriptPricing`. Given, it is used as it
   *  is and nothing is fetched a second time. */
  data?: Reply | null;
  /** "footer" is one ruled line under a table: the figures, and nothing that
   *  opens. The rows above it already carry each line's amount and margin. */
  variant?: "bar" | "footer";
}) {
  const [open, setOpen] = useState(false);
  const fetched = useScriptPricing(given === undefined ? items : [], medicalAidId);
  const data = given === undefined ? fetched : given;

  if (!data) return null;
  const t = data.totals;

  // The sums of the table, drawn as the table's last row. A total is a fact
  // about the columns above it, and a total in a card of its own under the
  // table reads as a separate thing to go and look at.
  if (variant === "footer") {
    return (
      <div className={`st-foot${data.warning ? " st-loss" : ""}`}
           role="group" aria-label="Script totals">
        {data.warning && (
          <span className="st-foot-warn" title={data.warning}>
            <Warning size={13} weight="fill" /> {data.warning}
          </span>
        )}
        <span className="st-foot-cell"><span>Gross</span><b>{money(t.gross)}</b></span>
        {t.claim > 0.005 && (
          <span className="st-foot-cell">
            <span>{data.scheme || "Scheme"} pays</span><b>{money(t.claim)}</b>
          </span>
        )}
        <span className="st-foot-cell st-lead">
          <span>{patientOwes(!!data.scheme)}</span><b>{money(t.patient_pays)}</b>
        </span>
        {t.levy > 0.005 && (
          <span className="st-foot-cell"><span>{TERMS.levy}</span><b>{money(t.levy)}</b></span>
        )}
        {t.surcharge > 0.005 && (
          <span className="st-foot-cell">
            <span>{TERMS.aboveRate}</span><b>{money(t.surcharge)}</b>
          </span>
        )}
        <span className="st-foot-cell"><span>VAT</span><b>{money(t.vat)}</b></span>
        <span className="st-foot-cell"><span>Cost</span><b>{money(t.cost)}</b></span>
        <span className={`st-foot-cell${t.profit < 0 ? " is-bad" : ""}`}>
          <span>Margin</span><b>{money(t.profit)} · {t.profit_percent}%</b>
        </span>
      </div>
    );
  }

  return (
    <div className={`st-bar${data.warning ? " st-loss" : ""}`}>
      {/* Selling below cost is not a rounding question, and should not be left
          for somebody to spot in a column of ten numbers. */}
      {data.warning && (
        <p className="st-warning">
          <Warning size={15} weight="fill" />
          <span>{data.warning}</span>
        </p>
      )}

      <div className="st-figures">
        <div><span>Gross</span><b>{money(t.gross)}</b></div>
        {t.claim > 0.005 && (
          <div><span>{data.scheme || "Scheme"} pays</span><b>{money(t.claim)}</b></div>
        )}
        {/* A shortfall only exists where a scheme was billed and did not
            cover it all. A private patient paying cash is paying the price,
            not a shortfall, and calling it one would be wrong on every cash
            sale, which is most of them. */}
        <div className="st-lead">
          <span>{patientOwes(!!data.scheme)}</span><b>{money(t.patient_pays)}</b>
        </div>
        {/* The two halves of it, kept apart because a patient querying the
            amount is querying one and not the other: the levy is a term of
            their cover, the excess is a consequence of what was dispensed. */}
        {t.levy > 0.005 && (
          <div><span>{TERMS.levy}</span><b>{money(t.levy)}</b></div>
        )}
        {t.surcharge > 0.005 && (
          <div><span>{TERMS.aboveRate}</span><b>{money(t.surcharge)}</b></div>
        )}
        <div><span>VAT</span><b>{money(t.vat)}</b></div>
        <div><span>Cost</span><b>{money(t.cost)}</b></div>
        <div className={t.profit < 0 ? "is-bad" : ""}>
          <span>Margin</span>
          <b>{money(t.profit)} · {t.profit_percent}%</b>
        </div>
      </div>

      <button type="button" className="btn ghost small st-toggle"
              onClick={() => setOpen((o) => !o)}>
        {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        {open ? "Hide the lines" : `Line by line (${data.lines.length})`}
      </button>

      {open && (
        <table className="dt st-lines">
          <thead>
            <tr>
              <th>Item</th><th className="num">Qty</th>
              <th className="num">Gross</th><th className="num">Cost</th>
              <th className="num">Claimed</th><th className="num">Margin</th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((l) => (
              <tr key={l.product_id} className={l.margin_percent < 0 ? "row-flag" : ""}>
                <td>
                  {l.description}
                  {l.no_claim && <div className="muted small">not claimed</div>}
                </td>
                <td className="num">{l.quantity}</td>
                <td className="num">{money(l.gross)}</td>
                <td className="num muted">{money(l.cost)}</td>
                <td className="num">{l.claim ? money(l.claim) : <span className="muted">—</span>}</td>
                <td className={`num${l.margin_percent < 0 ? " is-bad" : ""}`}>
                  {l.margin_percent}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
