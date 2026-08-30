/** How old the money is, and who is sitting on it.
 *
 *  A total is nearly useless on its own. A pharmacy owed 80,000 is in good
 *  health if all of it is current and in trouble if half of it is past ninety
 *  days, and the same number appears on the balance sheet either way. The
 *  buckets are the report; the total is the footnote.
 *
 *  Two decisions worth stating:
 *
 *  **The oldest column carries the weight.** Money past ninety days is the
 *  money that needs a phone call today, so it is emphasised rather than left as
 *  one number among five in a row of identical cells. A report where nothing
 *  stands out is a report nobody acts on.
 *
 *  **A settled party disappears.** Anyone whose balance nets to zero is not a
 *  debtor any more, and leaving them in pads the list with rows that need no
 *  action — which is how a list stops being read.
 */
import { useEffect, useState } from "react";
import { Printer } from "@phosphor-icons/react";
import { api, fmtDate, money } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { TableSkeleton } from "./Skeleton";

interface Party {
  party_type: string; party_id: number | null; name: string;
  buckets: Record<string, number>; total: number;
}
interface Ageing {
  subledger: string; as_at: string; buckets: string[];
  parties: Party[]; totals: Record<string, number>;
  total: number; overdue: number; overdue_percent: number;
}

const LEDGERS: { key: string; label: string; blurb: string }[] = [
  { key: "debtors", label: "Owed to us",
    blurb: "Patients and medical schemes who have not paid yet." },
  { key: "creditors", label: "Owed by us",
    blurb: "Suppliers waiting to be paid." },
];

export default function AgedAnalysis() {
  const [subledger, setSubledger] = useState("debtors");
  const [asof, setAsof] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<Ageing | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null); setError("");
    api.get<Ageing>(`/api/ledger/ageing/${subledger}?asof=${asof}`)
      .then(setData)
      .catch((e) => setError(e?.message || "That ageing report could not be built."));
  }, [subledger, asof]);

  const active = LEDGERS.find((l) => l.key === subledger);

  /** The ageing as a document — the one a bookkeeper walks into a meeting with.
   *
   *  The bucket columns are built from whatever the server sent rather than
   *  hard-coded, so a change to the bands on the server does not silently
   *  produce a printed report with the wrong headings on the right figures,
   *  which is the worst kind of wrong a financial document can be.
   */
  async function print() {
    if (!data) return;
    const head = await letterhead();
    const buckets = data.buckets;
    printDocument(head, {
      kind: subledger === "debtors" ? "Aged debtors" : "Aged creditors",
      meta: [
        { label: "As at", value: fmtDate(data.as_at) },
        { label: "Accounts", value: String(data.parties.length) },
        { label: "Past due", value: `${money(data.overdue)} · ${data.overdue_percent}%` },
        { label: "Total outstanding", value: money(data.total), strong: true },
      ],
      columns: [
        { key: "name", label: "Account" },
        ...buckets.map((b) => ({ key: b, label: b, numeric: true, width: "24mm" })),
        { key: "__total", label: "Total", numeric: true, width: "26mm" },
      ],
      rows: data.parties.map((party) => ({
        name: party.name,
        ...Object.fromEntries(buckets.map((b) => [b, money(party.buckets[b] ?? 0)])),
        __total: money(party.total),
      })),
      totals: {
        name: "Total",
        ...Object.fromEntries(buckets.map((b) => [b, money(data.totals[b] ?? 0)])),
        __total: money(data.total),
      },
      note: subledger === "debtors"
        ? "Amounts shown are what remains unpaid at the date above, aged from "
          + "the date of the sale or claim."
        : "Amounts shown are what remains unpaid at the date above, aged from "
          + "each invoice's due date where terms are recorded.",
    });
  }

  return (
    <div className="card">
      <div className="st-controls">
        <div className="seg">
          {LEDGERS.map((l) => (
            <button
              key={l.key}
              className={subledger === l.key ? "on" : ""}
              onClick={() => setSubledger(l.key)}
            >
              {l.label}
            </button>
          ))}
        </div>
        <label className="st-control">
          <span>As at</span>
          <input type="date" value={asof} onChange={(e) => setAsof(e.target.value)} />
        </label>
        {active && <span className="muted">{active.blurb}</span>}
        <button className="btn secondary small" onClick={print} disabled={!data}
                style={{ marginLeft: "auto" }}>
          <Printer size={15} /> Print
        </button>
      </div>

      {error ? (
        <div className="empty">{error}</div>
      ) : !data ? (
        <TableSkeleton cols={6} rows={6} />
      ) : (
        <>
          <div className="age-summary">
            <div className="age-stat">
              <span className="age-stat-label">Total outstanding</span>
              <span className="age-stat-value mono">{money(data.total)}</span>
            </div>
            <div className={`age-stat${data.overdue > 0 ? " is-warn" : ""}`}>
              <span className="age-stat-label">Past due</span>
              <span className="age-stat-value mono">{money(data.overdue)}</span>
              <span className="age-stat-hint">{data.overdue_percent}% of the book</span>
            </div>
            <div className="age-stat">
              <span className="age-stat-label">Accounts</span>
              <span className="age-stat-value mono">{data.parties.length}</span>
            </div>
          </div>

          {data.parties.length === 0 ? (
            <div className="empty">
              Nothing outstanding at {data.as_at}. Every account is settled.
            </div>
          ) : (
            <div className="age-scroll">
              <table className="age-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    {data.buckets.map((b) => (
                      <th
                        key={b}
                        className={`st-amount${b === "90 days" || b === "120+ days" ? " is-old" : ""}`}
                      >
                        {b}
                      </th>
                    ))}
                    <th className="st-amount">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {data.parties.map((p) => (
                    <tr key={`${p.party_type}-${p.party_id}`}>
                      <td>
                        {p.name}
                        {p.party_type && p.party_type !== "(none)" && (
                          <span className="badge muted st-badge">{p.party_type}</span>
                        )}
                      </td>
                      {data.buckets.map((b) => {
                        const value = p.buckets[b] ?? 0;
                        const old = b === "90 days" || b === "120+ days";
                        return (
                          <td
                            key={b}
                            className={`mono st-amount${old && value ? " is-old" : ""}${
                              value ? "" : " is-nil"
                            }`}
                          >
                            {/* An em dash, not 0.00. A column of zeros is
                                visual noise that hides the figures that matter. */}
                            {value ? money(value) : "—"}
                          </td>
                        );
                      })}
                      <td className="mono st-amount age-row-total">{money(p.total)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td>Total</td>
                    {data.buckets.map((b) => (
                      <td
                        key={b}
                        className={`mono st-amount${
                          (b === "90 days" || b === "120+ days") && data.totals[b] ? " is-old" : ""
                        }`}
                      >
                        {data.totals[b] ? money(data.totals[b]) : "—"}
                      </td>
                    ))}
                    <td className="mono st-amount">{money(data.total)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
