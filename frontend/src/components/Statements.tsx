/** The income statement and the balance sheet.
 *
 *  Two presentation rules, both taken from how accountants actually read these
 *  and both easy to get wrong:
 *
 *  **A section is shown even when it is empty.** A zero next to Stock write-offs
 *  says the pharmacy wrote nothing off, which is information. An absent line
 *  says nobody knows whether it is zero or forgotten. Zero rows can be hidden on
 *  request, never by default.
 *
 *  **Every total can be opened.** A figure a pharmacist cannot decompose is a
 *  figure they cannot check, and a statement that cannot be checked is not worth
 *  signing. Each section expands into the accounts behind it.
 *
 *  The balance sheet says plainly whether it balances. If it does not, the
 *  difference is printed rather than rounded away — being out by a cent means
 *  something is wrong, and hiding it destroys the only evidence.
 */
import { useEffect, useState } from "react";
import { api, money } from "../api";
import { TableSkeleton } from "./Skeleton";
import Checkbox from "./Checkbox";

interface Line {
  code: string; name: string; amount: number; subledger?: string; computed?: boolean;
}
interface Section {
  key: string; heading: string; total: number; accounts: Line[]; subtotal?: boolean;
}
interface Income {
  from: string; to: string; sections: Section[];
  revenue: number; cost_of_sales: number; gross_profit: number; gross_margin: number;
  operating_expenses: number; net_profit: number;
}
interface Balance {
  as_at: string; sections: Section[];
  total_assets: number; total_liabilities: number; total_equity: number;
  profit_for_period: number; balances: boolean; difference: number; note: string;
}

/** The first day of the month `n` months back, as an ISO date. */
function isoToday() {
  return new Date().toISOString().slice(0, 10);
}

export default function Statements({ kind }: { kind: "income" | "balance" }) {
  const [upto, setUpto] = useState(isoToday);
  const [hideZero, setHideZero] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [income, setIncome] = useState<Income | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);

  useEffect(() => {
    const q = `upto=${upto}&hide_zero=${hideZero}`;
    if (kind === "income") {
      setIncome(null);
      api.get<Income>(`/api/ledger/income-statement?${q}`).then(setIncome).catch(() => {});
    } else {
      setBalance(null);
      api.get<Balance>(`/api/ledger/balance-sheet?${q}`).then(setBalance).catch(() => {});
    }
  }, [kind, upto, hideZero]);

  const data = kind === "income" ? income : balance;

  function SectionRows({ sections }: { sections: Section[] }) {
    return (
      <>
        {sections.map((s) => {
          const expanded = open[s.key];
          return (
            <tbody key={s.key} className={s.subtotal ? "st-subtotal" : undefined}>
              <tr
                className={`st-section${s.accounts.length ? " is-openable" : ""}`}
                onClick={() => s.accounts.length && setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
              >
                <td>
                  {s.accounts.length > 0 && (
                    <span className={`st-caret${expanded ? " is-open" : ""}`} aria-hidden="true">›</span>
                  )}
                  {s.heading}
                  {s.accounts.length > 0 && (
                    <span className="muted st-count"> {s.accounts.length}</span>
                  )}
                </td>
                <td className="mono st-amount">{money(s.total)}</td>
              </tr>
              {expanded && s.accounts.map((a) => (
                <tr key={s.key + a.code} className="st-line">
                  <td>
                    <span className="mono muted">{a.code}</span> {a.name}
                    {a.computed && <span className="badge muted st-badge">calculated</span>}
                    {a.subledger && <span className="badge st-badge">{a.subledger}</span>}
                  </td>
                  <td className="mono st-amount">{money(a.amount)}</td>
                </tr>
              ))}
            </tbody>
          );
        })}
      </>
    );
  }

  return (
    <div className="card">
      <div className="st-controls">
        <label className="st-control">
          <span>{kind === "income" ? "Up to" : "As at"}</span>
          <input type="date" value={upto} onChange={(e) => setUpto(e.target.value)} />
        </label>
        <div className="st-control st-check">
          <Checkbox checked={hideZero} onChange={setHideZero}>
            Hide empty sections
          </Checkbox>
        </div>
        {kind === "income" && income && (
          <span className="muted">
            {income.from} to {income.to}
          </span>
        )}
      </div>

      {!data ? (
        <TableSkeleton cols={2} rows={7} />
      ) : (
        <>
          <table className="st-table">
            <SectionRows sections={data.sections} />
            <tfoot>
              {kind === "income" && income && (
                <>
                  <tr>
                    <td>Gross margin</td>
                    <td className="mono st-amount">{income.gross_margin}%</td>
                  </tr>
                  <tr className="st-total">
                    <td>{income.net_profit >= 0 ? "Net profit" : "Net loss"}</td>
                    <td className="mono st-amount">{money(income.net_profit)}</td>
                  </tr>
                </>
              )}
              {kind === "balance" && balance && (
                <>
                  <tr>
                    <td>Total assets</td>
                    <td className="mono st-amount">{money(balance.total_assets)}</td>
                  </tr>
                  <tr className="st-total">
                    <td>Liabilities and equity</td>
                    <td className="mono st-amount">
                      {money(balance.total_liabilities + balance.total_equity)}
                    </td>
                  </tr>
                </>
              )}
            </tfoot>
          </table>

          {kind === "balance" && balance && (
            // Stated either way. A statement that only speaks up when it is
            // wrong leaves a reader unable to tell "checked and fine" from
            // "never checked".
            <p className={`st-note ${balance.balances ? "is-ok" : "is-bad"}`}>
              {balance.note}
            </p>
          )}
        </>
      )}
    </div>
  );
}
