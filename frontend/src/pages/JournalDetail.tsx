/** One journal entry, in full.
 *
 *  The page an accountant reaches by clicking a figure that looked wrong. It
 *  shows every line, what caused the entry, and — where the cause was a sale or
 *  a credit note — links straight back to it, so the trail runs both ways:
 *  ledger → transaction as readily as transaction → ledger.
 *
 *  Reversal is the only edit. A posted entry is never changed, so the button
 *  says "Reverse", not "Edit", and asks for a reason that goes on the record.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import Breadcrumbs from "../components/Breadcrumbs";
import { EntityLink } from "../components/Filters";
import { FormSkeleton, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";

interface Line {
  account_code: string; debit: number; credit: number;
  description: string; party_type: string; party_id: number | null;
}
interface Entry {
  id: number; reference: string; period_code: string; entry_date: string;
  description: string; source: string; source_id: number | null;
  status: string; reverses_id: number | null; created_by: string;
  lines: Line[]; total: number;
}

export default function JournalDetail() {
  const { id } = useParams();
  const [entry, setEntry] = useState<Entry | null>(null);
  const [loading, setLoading] = useState(true);
  const [reversing, setReversing] = useState(false);
  const [reason, setReason] = useState("");
  const toast = useToast();

  function load() {
    setLoading(true);
    api.get<Entry>(`/api/ledger/entries/${id}`)
      .then(setEntry)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, [id]);

  async function reverse() {
    const res = await api
      .post<{ reversal: Entry }>(`/api/ledger/entries/${id}/reverse`, { reason })
      .catch((e) => { toast.error(errorText(e)); return null; });
    if (!res) return;
    toast.ok(`Reversed by ${res.reversal.reference}.`);
    setReversing(false);
    setReason("");
    load();
  }

  if (loading && !entry) {
    return (
      <div className="page">
        <FormSkeleton fields={3} />
        <TableSkeleton cols={5} rows={4} />
      </div>
    );
  }
  if (!entry) return <div className="page"><p className="muted pad">Not found.</p></div>;

  const debits = entry.lines.reduce((n, l) => n + l.debit, 0);
  const credits = entry.lines.reduce((n, l) => n + l.credit, 0);

  return (
    <div className="page">
      <Breadcrumbs
        trail={[
          { label: "Dashboard", to: "/" },
          { label: "General ledger", to: "/ledger" },
          { label: entry.reference },
        ]}
        actions={
          entry.status === "posted" && (
            <button className="btn danger sm" onClick={() => setReversing(true)}>
              Reverse
            </button>
          )
        }
      />

      <header className="page-head">
        <div>
          <h1 className="mono">{entry.reference}</h1>
          <p className="muted">
            {entry.description} · {fmtDate(entry.entry_date)} · period{" "}
            <span className="mono">{entry.period_code}</span>
            {entry.created_by && ` · posted by ${entry.created_by}`}
          </p>
        </div>
        {entry.status !== "posted" && (
          <span className="badge warn">{entry.status}</span>
        )}
      </header>

      {/* The trail runs both ways: from the ledger back to what caused it. */}
      {entry.source === "sale" && entry.source_id && (
        <p className="muted">
          Raised by <EntityLink to={`/sales/${entry.source_id}`}>this sale</EntityLink>.
        </p>
      )}
      {entry.reverses_id && (
        <p className="alert warn">
          This entry reverses{" "}
          <EntityLink to={`/ledger/entries/${entry.reverses_id}`}>
            journal {entry.reverses_id}
          </EntityLink>
          .
        </p>
      )}

      <div className="dt-scroll">
        <table className="dt">
          <thead>
            <tr>
              <th>Account</th><th>Description</th><th>Party</th>
              <th className="num">Debit</th><th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {entry.lines.map((l, i) => (
              <tr key={i}>
                <td className="mono">{l.account_code}</td>
                <td>{l.description || <span className="muted">—</span>}</td>
                <td>
                  {l.party_type ? (
                    <>
                      {l.party_type}
                      {l.party_id ? ` #${l.party_id}` : ""}
                    </>
                  ) : (
                    /* An unattributed line on a control account is what makes a
                       subledger stop reconciling — worth naming, not blanking. */
                    <span className="muted">unattributed</span>
                  )}
                </td>
                <td className="num">{l.debit ? money(l.debit) : "—"}</td>
                <td className="num">{l.credit ? money(l.credit) : "—"}</td>
              </tr>
            ))}
            <tr className="total-row">
              <td colSpan={3}>Totals</td>
              <td className="num">{money(debits)}</td>
              <td className="num">{money(credits)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {reversing && (
        <div className="modal-backdrop" onClick={() => setReversing(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Reverse {entry.reference}</h2>
            <p className="muted">
              A posted entry is never edited or deleted. Reversing posts its mirror
              with today's date, so the correction is visible as a correction rather
              than history being rewritten.
            </p>
            <label>
              Reason
              <input
                value={reason}
                autoFocus
                onChange={(e) => setReason(e.target.value)}
                placeholder="Keyed twice"
              />
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setReversing(false)}>
                Cancel
              </button>
              <button className="btn danger" onClick={reverse}>
                Post the reversal
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
