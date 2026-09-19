/** Goods going back to the wholesaler, and the credit owed for them.
 *
 *  Returns happened constantly and left no record. A short dated delivery, a
 *  cracked bottle, a line ordered in error: each was a telephone call and a
 *  note on a spike, and the stock was adjusted out as a write-off if it was
 *  adjusted at all. The shelf ended up right and the story was gone.
 *
 *  WHAT LEADS THIS SCREEN
 *
 *  The money nobody is chasing. An approved return with no credit note
 *  against it is stock the pharmacy has given back and not been paid for, and
 *  a pharmacy that cannot list those does not chase them. That total sits at
 *  the top; everything else is the detail behind it.
 *
 *  RAISED, APPROVED, CREDITED
 *
 *  Raised holds the goods but has not moved them, so it can be cancelled and
 *  the stock goes back on the shelf as if nothing happened. Approved is when
 *  they leave. Credited is the supplier's answer, which arrives on their
 *  timetable and often weeks later, which is exactly why it is a separate
 *  state rather than something assumed at approval.
 */
import { useCallback, useEffect, useState } from "react";

import { api, errorText, fmtDate, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";
import { useCan } from "../session";

interface Line {
  product_id: number; product: string; batch: string; expiry: string;
  quantity: number; unit_cost: number; line_total: number;
}
interface Ret {
  id: number; reference: string; supplier: string; supplier_id: number;
  status: string; why: string; notes: string; total: number;
  credit_note: string; credited_at: string;
  raised_by: string; approved_by: string; approved_at: string;
  created_at: string; lines: Line[];
}

const TONE: Record<string, string> = {
  raised: "warn", approved: "ok", credited: "muted", cancelled: "muted",
};
/** What each state MEANS, rather than what it is called. */
const SAYS: Record<string, string> = {
  raised: "held, not yet gone",
  approved: "gone, credit owed",
  credited: "settled",
  cancelled: "called off",
};

export default function SupplierReturns() {
  const toast = useToast();
  const [rows, setRows] = useState<Ret[]>([]);
  const [owed, setOwed] = useState({ count: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const mayApprove = useCan("stock.write_off");
  const mayRaise = useCan("stock.adjust");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<{ returns: Ret[] }>("/api/supplier-returns"),
      api.get<{ count: number; total: number }>("/api/supplier-returns/outstanding"),
    ])
      .then(([all, out]) => { setRows(all.returns); setOwed(out); })
      .catch((e) => toast.error(errorText(e, "The returns could not be read.")))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  async function act(r: Ret, what: "approve" | "cancel", label: string) {
    try {
      const said = await api.post<{ message: string }>(
        `/api/supplier-returns/${r.id}/${what}`, {});
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, `That return could not be ${label}.`));
    }
  }

  async function credit(r: Ret) {
    const note = window.prompt(
      `Credit note number from ${r.supplier} for ${r.reference}:`, "");
    if (!note?.trim()) return;
    try {
      const said = await api.post<{ message: string }>(
        `/api/supplier-returns/${r.id}/credit`, { credit_note: note.trim() });
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That credit could not be recorded."));
    }
  }

  return (
    <>
      {/* The money nobody is chasing, stated before anything else. */}
      {owed.count > 0 && (
        <div className="sr-owed">
          <span className="sr-owed-n">{money(owed.total)}</span>
          <span>
            owed across {owed.count} approved return
            {owed.count === 1 ? "" : "s"} with no credit note against
            {owed.count === 1 ? " it" : " them"}. These are goods the pharmacy
            has given back and has not been paid for.
          </span>
        </div>
      )}

      <p className="muted small sr-say">
        {rows.length === 0 && !loading
          ? mayRaise
            ? "No returns on file. Raise one from Held stock, where damaged, "
              + "expired and recalled batches are already waiting."
            : "No returns on file."
          : `${rows.length} return${rows.length === 1 ? "" : "s"} on file.`}
      </p>

      <Refreshable loading={loading} hasData={rows.length > 0}
                   skeleton={<TableSkeleton cols={6} rows={5}
                                            widths={["12ch", "20ch", "12ch", "10ch", "12ch", "10ch"]} />}>
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>Reference</th>
                <th>Supplier</th>
                <th>Why</th>
                <th className="num">Value</th>
                <th>Standing</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <>
                  <tr key={r.id}>
                    <td>
                      <button type="button" className="btn-link"
                              onClick={() => setOpen(open === r.id ? null : r.id)}>
                        {r.reference}
                      </button>
                      <div className="muted small">{fmtDate(r.created_at)}</div>
                    </td>
                    <td>{r.supplier}</td>
                    <td>{r.why}</td>
                    <td className="num">{money(r.total)}</td>
                    <td>
                      <span className={`badge ${TONE[r.status] ?? "muted"}`}>
                        {SAYS[r.status] ?? r.status}
                      </span>
                      {r.credit_note && (
                        <div className="muted small">note {r.credit_note}</div>
                      )}
                    </td>
                    <td className="actions">
                      {r.status === "raised" && mayApprove && (
                        <button type="button" className="btn small"
                                onClick={() => act(r, "approve", "approved")}>
                          Approve
                        </button>
                      )}
                      {r.status === "raised" && mayRaise && (
                        <button type="button" className="btn small ghost"
                                onClick={() => act(r, "cancel", "cancelled")}>
                          Cancel
                        </button>
                      )}
                      {r.status === "approved" && mayRaise && (
                        <button type="button" className="btn small ghost"
                                onClick={() => credit(r)}>
                          Credit received
                        </button>
                      )}
                    </td>
                  </tr>
                  {open === r.id && (
                    <tr key={`${r.id}-lines`} className="sr-detail">
                      <td colSpan={6}>
                        <ul>
                          {r.lines.map((l, i) => (
                            <li key={i}>
                              <b>{l.product}</b>
                              <span className="muted">
                                {" · "}batch {l.batch || "unnamed"}
                                {l.expiry ? ` · expires ${fmtDate(l.expiry)}` : ""}
                                {" · "}{l.quantity.toLocaleString()} units
                              </span>
                              {" "}{money(l.line_total)}
                            </li>
                          ))}
                        </ul>
                        {r.notes && <p className="muted small">{r.notes}</p>}
                        <p className="muted small">
                          Raised by {r.raised_by || "unknown"}
                          {r.approved_by && `, approved by ${r.approved_by}`}
                          {r.approved_at && ` on ${fmtDate(r.approved_at)}`}.
                        </p>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </Refreshable>
    </>
  );
}
