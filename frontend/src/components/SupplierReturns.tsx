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
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorText, fmtDate, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import {
  applyFilters, emptyFilters, EntityLink, FilterBar, FilterState, FilterToggle,
} from "./Filters";
import { useToast } from "./Toast";
import { useCan } from "../session";
import { useAsk } from "./Confirm";
import Th from "./Th";

interface Line {
  product_id: number; product: string; batch: string; expiry: string;
  quantity: number; unit_cost: number; line_total: number;
}
interface Ret {
  id: number; reference: string; supplier: string; supplier_id: number;
  status: string; why: string; reason_code: string; notes: string; total: number;
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
  const ask = useAsk();
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  /** The one subset worth its own control: goods gone back and not paid for. */
  const [owedOnly, setOwedOnly] = useState(false);

  /** Move a row's standing on the screen, before the server has agreed.
   *
   *  These are state changes on a row already in front of somebody, which is
   *  the case the optimistic pattern is for: the badge moves on the click and
   *  goes back if the server refuses. The refusal is real and worth handling
   *  rather than assuming away — approving re-checks that the stock is still
   *  there, and it may not be. */
  function stand(id: number, status: string, extra: Partial<Ret> = {}) {
    setRows((all) => all.map((r) =>
      r.id === id ? { ...r, status, ...extra } : r));
  }

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

  /** Only the wholesalers something has actually gone back to. */
  const whoTook = useMemo(() => {
    const seen = new Map<number, string>();
    for (const r of rows) if (r.supplier_id) seen.set(r.supplier_id, r.supplier);
    return [...seen.entries()]
      .sort((a, b) => a[1].localeCompare(b[1]))
      .map(([id, name]) => [String(id), name] as [string, string]);
  }, [rows]);

  /** The reasons on file, said the way the rows say them. A fixed list would
   *  offer reasons this pharmacy has never used and miss ones it has. */
  const whyList = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of rows) if (r.reason_code) seen.set(r.reason_code, r.why || r.reason_code);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]))
      .map(([code, said]) => [code, said] as [string, string]);
  }, [rows]);

  const shown = useMemo(() => {
    let some = applyFilters(rows, filters, {
      search: (r) => [r.reference, r.supplier, r.why, r.credit_note,
                      r.notes, r.raised_by],
      date: (r) => r.created_at,
      dims: {
        status: (r) => r.status,
        supplier: (r) => String(r.supplier_id ?? ""),
        why: (r) => r.reason_code,
      },
    });
    if (owedOnly) some = some.filter((r) => r.status === "approved" && !r.credit_note);
    return some;
  }, [rows, filters, owedOnly]);

  /** The band at the top is the filter it describes. */
  function only(patch: { owed?: boolean }) {
    setOwedOnly(Boolean(patch.owed));
    setFilters(emptyFilters);
  }

  async function act(r: Ret, what: "approve" | "cancel", label: string) {
    const was = r.status;
    const owedBefore = owed;
    stand(r.id, what === "approve" ? "approved" : "cancelled");
    // Approving is money owed by the supplier from the moment it is agreed,
    // so the band at the top moves with the badge rather than waiting for a
    // reload to tell somebody what they already decided.
    if (what === "approve") {
      setOwed((o) => ({ count: o.count + 1,
                        total: Math.round((o.total + r.total) * 100) / 100 }));
    }
    try {
      const said = await api.post<{ message: string }>(
        `/api/supplier-returns/${r.id}/${what}`, {});
      toast.ok(said.message);
      load();
    } catch (e) {
      stand(r.id, was);
      setOwed(owedBefore);
      toast.error(errorText(e, `That return could not be ${label}.`));
    }
  }

  async function credit(r: Ret) {
    // The house dialog rather than window.prompt: a browser prompt freezes
    // the whole application until somebody clicks OK, and cannot say what is
    // about to happen or refuse an empty answer.
    const { ok, value } = await ask({
      title: `Credit note for ${r.reference}`,
      body: <>Enter the number {r.supplier} put on the credit. {money(r.total)}{" "}
            stops being owed once this is recorded.</>,
      field: "Credit note number",
      placeholder: "as it appears on the supplier's document",
      required: true,
      maxLength: 40,
      confirmLabel: "Record the credit",
    });
    if (!ok || !value.trim()) return;

    const was = r.status;
    const owedBefore = owed;
    stand(r.id, "credited", { credit_note: value.trim() });
    setOwed((o) => ({ count: Math.max(0, o.count - 1),
                      total: Math.round((o.total - r.total) * 100) / 100 }));
    try {
      const said = await api.post<{ message: string }>(
        `/api/supplier-returns/${r.id}/credit`, { credit_note: value.trim() });
      toast.ok(said.message);
      load();
    } catch (e) {
      stand(r.id, was, { credit_note: r.credit_note });
      setOwed(owedBefore);
      toast.error(errorText(e, "That credit could not be recorded."));
    }
  }

  return (
    <>
      {/* The money nobody is chasing, stated before anything else. */}
      {owed.count > 0 && (
        <button type="button" className="sr-owed sr-owed-act"
                aria-pressed={owedOnly}
                onClick={() => owedOnly ? only({}) : only({ owed: true })}>
          <span className="sr-owed-n">{money(owed.total)}</span>
          <span>
            owed across {owed.count} approved return
            {owed.count === 1 ? "" : "s"} with no credit note against
            {owed.count === 1 ? " it" : " them"}. These are goods the pharmacy
            has given back and has not been paid for.
            <b className="sr-owed-do">
              {owedOnly ? "Showing them. Press to show everything."
                        : "Show me what is owed"}
            </b>
          </span>
        </button>
      )}

      {/* Where a return STARTS, offered on the screen that lists them.
          The empty state explained that returns begin at Held stock and then
          left somebody to find it, which on a screen that already has rows
          it never said at all. */}
      {mayRaise && rows.length > 0 && (
        <p className="muted small sr-say">
          {rows.length} return{rows.length === 1 ? "" : "s"} on file.{" "}
          <Link to="/stock?tab=quarantine" className="btn-link">
            Send something back
          </Link>{" "}
          from held stock, where the damaged, expired and recalled lots wait.
        </p>
      )}

      {/* Said as a block rather than a line over an empty table, and it says
          where a return STARTS. A screen whose only content is "none" and a
          header teaches nobody how to make the first one. */}
      {rows.length === 0 && !loading ? (
        <div className="empty">
          <b>No returns on file</b>
          <p>
            {mayRaise
              ? "A return starts from Held stock, where damaged, expired and "
                + "recalled batches are already waiting: the supplier and the "
                + "quantity are known there, so it is one button rather than a "
                + "form. Raising one holds the goods; approving it is when they "
                + "leave and the credit becomes owed."
              : "Goods sent back to a wholesaler appear here with the credit "
                + "owed for them. Raising one needs permission to adjust stock."}
          </p>
        </div>
      ) : (
      <>
      <div className="dt-filters">
        <FilterBar
          value={filters}
          onChange={setFilters}
          placeholder="Reference, supplier, reason or credit note…"
          showDates
          dimensions={[
            // Named by what the state MEANS, the same words the badge uses.
            // "Approved" on a dropdown and "gone, credit owed" on the row is
            // one state spelled two ways on one screen.
            { key: "status", label: "Standing",
              options: [["raised", "Held, not yet gone"],
                        ["approved", "Gone, credit owed"],
                        ["credited", "Settled"],
                        ["cancelled", "Called off"]] },
            ...(whoTook.length > 1
              ? [{ key: "supplier", label: "Supplier", options: whoTook }]
              : []),
            ...(whyList.length > 1
              ? [{ key: "why", label: "Reason", options: whyList }]
              : []),
          ]}
          extras={{ active: owedOnly, clear: () => setOwedOnly(false) }}
        >
          <FilterToggle checked={owedOnly} onChange={setOwedOnly}
                        hint="Approved returns with no credit note recorded">
            Credit owed
          </FilterToggle>
          <span className="dt-count muted">{shown.length} of {rows.length}</span>
        </FilterBar>
      </div>

      <Refreshable loading={loading} hasData={rows.length > 0}
                   skeleton={<TableSkeleton cols={6} rows={5}
                                            widths={["12ch", "20ch", "12ch", "10ch", "12ch", "10ch"]} />}>
        <div className="dt-scroll">
          {/* Only the columns with a known shape carry a width; the supplier
              and the reason share what is left. See the note on the
              deliveries table: a width on every column adds up to more than
              the screen and pushes the action buttons off it. */}
          <table className="dt gr-table">
            <thead>
              <tr>
                <Th className="col-when">Reference</Th>
                <Th>Supplier</Th>
                <Th>Why</Th>
                <Th className="num col-money">Value</Th>
                {/* Undeclared: the badge says "gone, credit owed" and a code
                    width cut it to "gone, credit owe". A state that cannot be
                    read in full is a state nobody trusts. */}
                <Th>Standing</Th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                // Keyed on the fragment, not on the first row inside it: a
                // bare <> in a map gives React nothing to track, so it
                // rebuilds both rows on every change and loses the open
                // detail panel while somebody is reading it.
                <Fragment key={r.id}>
                  <tr>
                    <td>
                      {/* The reference opens the return. Expanding in
                          place stays for a quick look at the lines. */}
                      <EntityLink to={`/returns/${r.id}`}>{r.reference}</EntityLink>
                      <button type="button" className="btn-link small gr-peek"
                              aria-expanded={open === r.id}
                              onClick={() => setOpen(open === r.id ? null : r.id)}>
                        {open === r.id ? "Hide lines" : "Lines"}
                      </button>
                      <div className="muted small">{fmtDate(r.created_at)}</div>
                    </td>
                    {/* A credit that never arrives is a conversation with
                        this wholesaler, so the wholesaler is one click away. */}
                    <td>
                      <EntityLink kind="supplier" id={r.supplier_id}>
                        {r.supplier}
                      </EntityLink>
                    </td>
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
                      {/* Bordered, not ghost. A ghost button alone in a cell
                          has no chrome at all, so the only thing to do on a
                          row owed money read as a line of text and nobody
                          pressed it. Ghost is for the quiet half of a pair,
                          which is what Cancel is beside Approve. */}
                      {r.status === "approved" && mayRaise && (
                        <button type="button" className="btn small secondary"
                                onClick={() => credit(r)}>
                          Credit received
                        </button>
                      )}
                    </td>
                  </tr>
                  {open === r.id && (
                    <tr className="sr-detail">
                      <td colSpan={6}>
                        <ul>
                          {r.lines.map((l, i) => (
                            <li key={i}>
                              <EntityLink kind="product" id={l.product_id}>
                                <b>{l.product}</b>
                              </EntityLink>
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
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {shown.length === 0 && rows.length > 0 && (
          <div className="empty">
            <b>No return matches that</b>
            <p>
              {rows.length} return{rows.length === 1 ? " is" : "s are"} on file.
              Widen the search or clear the filters to see them.
            </p>
            <button type="button" className="btn secondary"
                    onClick={() => only({})}>
              Show every return
            </button>
          </div>
        )}
      </Refreshable>
      </>
      )}
    </>
  );
}
