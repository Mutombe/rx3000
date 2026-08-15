/** Where the cash went.
 *
 *  This is the report a pharmacy owner should read first and usually cannot,
 *  because most small systems do not produce one. Profit is not cash: a month
 *  can show a healthy margin while the bank balance falls, because the profit is
 *  sitting on a shelf as stock and in claims a medical scheme has not paid yet.
 *  That gap is what closes otherwise profitable pharmacies, and this is the only
 *  statement that shows it.
 *
 *  So the working-capital lines carry a plain-English note — "more cash tied
 *  up", "cash held back" — rather than leaving a reader to work out why a
 *  positive number appears as a deduction. And the statement states whether it
 *  ties back to the bank, because a cash flow that cannot be reconciled to the
 *  actual cash accounts is a guess with a heading on it.
 */
import { useEffect, useState } from "react";
import { api, money } from "../api";
import { TableSkeleton } from "./Skeleton";

interface Line { label: string; amount: number; note?: string }
interface Section { key: string; heading: string; total: number; lines: Line[] }
interface Flow {
  from: string; to: string; sections: Section[];
  net_movement: number; opening_cash: number; closing_cash: number;
  actual_movement: number; cash_accounts: { code: string; name: string }[];
  reconciles: boolean; difference: number; note: string;
}

export default function CashFlow() {
  const [upto, setUpto] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<Flow | null>(null);

  useEffect(() => {
    setData(null);
    api.get<Flow>(`/api/ledger/cash-flow?upto=${upto}`).then(setData).catch(() => {});
  }, [upto]);

  return (
    <div className="card">
      <div className="st-controls">
        <label className="st-control">
          <span>Up to</span>
          <input type="date" value={upto} onChange={(e) => setUpto(e.target.value)} />
        </label>
        {data && (
          <span className="muted">
            {data.from} to {data.to} · cash is{" "}
            {data.cash_accounts.map((a) => a.name).join(" and ") || "not flagged on any account"}
          </span>
        )}
      </div>

      {!data ? (
        <TableSkeleton cols={2} rows={9} />
      ) : (
        <>
          <table className="st-table">
            {data.sections.map((s) => (
              <tbody key={s.key}>
                <tr className="st-section">
                  <td>{s.heading}</td>
                  <td className="mono st-amount">{money(s.total)}</td>
                </tr>
                {s.lines.map((l, i) => (
                  <tr key={s.key + i} className="st-line">
                    <td>
                      {l.label}
                      {/* The sign is not self-explanatory to most readers, so
                          it is explained where it appears rather than in a
                          legend nobody scrolls to. */}
                      {l.note && <span className="cf-note">{l.note}</span>}
                    </td>
                    <td className="mono st-amount">{money(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
            ))}
            <tfoot>
              <tr>
                <td>Cash at {data.from}</td>
                <td className="mono st-amount">{money(data.opening_cash)}</td>
              </tr>
              <tr>
                <td>Net movement</td>
                <td className="mono st-amount">{money(data.net_movement)}</td>
              </tr>
              <tr className="st-total">
                <td>Cash at {data.to}</td>
                <td className="mono st-amount">{money(data.closing_cash)}</td>
              </tr>
            </tfoot>
          </table>

          <p className={`st-note ${data.reconciles ? "is-ok" : "is-bad"}`}>{data.note}</p>
        </>
      )}
    </div>
  );
}
