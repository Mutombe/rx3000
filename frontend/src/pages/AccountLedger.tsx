/** One account, and everything that moved it.
 *
 *  The page reached from a trial-balance figure that looks wrong. It carries a
 *  running balance down the rows, because the question actually asked is "what
 *  was this account at on the 14th" — and a list of movements alone cannot
 *  answer it without the reader doing arithmetic the machine should have done.
 *
 *  Every row opens the journal entry behind it, so the chain runs
 *  trial balance → account → entry → the sale that caused it, without anyone
 *  searching for the same thing twice.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fmtDate, money, prefetchRoute, errorText  } from "../api";
import Breadcrumbs from "../components/Breadcrumbs";
import RowLink from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";

interface Line {
  entry_id: number; reference: string; entry_date: string; period_code: string;
  description: string; source: string; source_id: number | null; status: string;
  party_type: string; party_id: number | null;
  debit: number; credit: number; balance: number;
}
interface AccountView {
  code: string; name: string; type: string; subledger: string;
  balance: number; opening_balance: number; truncated: boolean;
  line_count: number; lines: Line[];
}

export default function AccountLedger() {
  const { code } = useParams();
  const [view, setView] = useState<AccountView | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    setLoading(true);
    api
      .get<AccountView>(`/api/ledger/accounts/${code}`)
      .then(setView)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [code]);

  return (
    <div className="page">
      <Breadcrumbs
        trail={[
          { label: "Dashboard", to: "/" },
          { label: "General ledger", to: "/ledger" },
          { label: view ? `${view.code} ${view.name}` : String(code) },
        ]}
      />

      <header className="page-head">
        <div>
          <h1>
            <span className="mono">{view?.code ?? code}</span> {view?.name ?? ""}
          </h1>
          <p className="muted">
            {view
              ? `${view.type}${view.subledger ? ` · ${view.subledger} control` : ""} · ` +
                `${view.line_count} movement${view.line_count === 1 ? "" : "s"} · ` +
                `balance ${money(view.balance)}`
              : ""}
          </p>
        </div>
      </header>

      <Refreshable
        loading={loading}
        hasData={!!view?.lines.length}
        skeleton={
          <TableSkeleton cols={7} rows={8}
            widths={["12ch", "10ch", "24ch", "12ch", "9ch", "9ch", "10ch"]} />
        }
      >
        <table className="dt">
          <thead>
            <tr>
              <th>Entry</th><th>Date</th><th>Description</th><th>Party</th>
              <th className="num">Debit</th><th className="num">Credit</th>
              <th className="num">Balance</th>
            </tr>
          </thead>
          <tbody>
            {view && view.truncated && (
              /* The window is the latest movements, carried on an opening
                 balance. Saying so is what stops the first figure looking
                 unexplained. */
              <tr className="total-row">
                <td colSpan={6}>
                  Balance brought forward — showing the most recent {view.line_count}{" "}
                  movements
                </td>
                <td className="num">{money(view.opening_balance)}</td>
              </tr>
            )}
            {view?.lines.map((l, i) => (
              <RowLink
                key={`${l.entry_id}-${i}`}
                to={`/ledger/entries/${l.entry_id}`}
                prefetch={prefetchRoute}
                className={l.status === "reversed" ? "row-flag" : ""}
              >
                <td className="mono">{l.reference}</td>
                <td>{fmtDate(l.entry_date)}</td>
                <td>
                  {l.description}
                  {l.status === "reversed" && <span className="badge warn">reversed</span>}
                </td>
                <td>
                  {l.party_type ? (
                    `${l.party_type}${l.party_id ? ` #${l.party_id}` : ""}`
                  ) : (
                    /* On a control account this is the line that will stop the
                       subledger reconciling, so it is named rather than blank. */
                    <span className="muted">unattributed</span>
                  )}
                </td>
                <td className="num">{l.debit ? money(l.debit) : "—"}</td>
                <td className="num">{l.credit ? money(l.credit) : "—"}</td>
                <td className="num">{money(l.balance)}</td>
              </RowLink>
            ))}
            {view && !view.lines.length && (
              <tr>
                <td colSpan={7} className="muted pad">
                  Nothing has moved this account yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Refreshable>
    </div>
  );
}
