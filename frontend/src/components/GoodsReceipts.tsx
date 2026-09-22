/** Deliveries, as documents.
 *
 *  An order is what was asked for and an invoice is what is billed. The
 *  delivery is neither, and it was the one of the three nothing wrote down:
 *  stock went onto the shelf stamped with the ORDER number, so two vans a week
 *  apart against one order left batches nobody could tell apart afterwards.
 *
 *  WHAT LEADS THIS SCREEN
 *
 *  Goods on the shelf with no invoice number against them. Those are deliveries
 *  the pharmacy cannot check a bill against: when the statement arrives there is
 *  nothing to hold it up to, and a wholesaler's error becomes an argument about
 *  memory. It is stated at the top rather than filtered to, because a number
 *  nobody is shown is a number nobody chases.
 *
 *  OPEN AND SIGNED
 *
 *  Open means somebody is still unloading. A scanned delivery is thirty scans
 *  over twenty minutes down a pallet and they all join one document, which
 *  closes when the order does. One left open overnight is worth seeing: the
 *  goods are on the shelf either way, and the paperwork is not finished.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { api, errorText, fmtDate, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import {
  applyFilters, emptyFilters, EntityLink, FilterBar, FilterState, FilterToggle,
} from "./Filters";
import { useToast } from "./Toast";
import { useAsk } from "./Confirm";
import { useCan } from "../session";
import MatchToBill, { Candidate } from "./MatchToBill";

interface Item {
  product_id: number; product: string; batch_id: number | null; batch: string;
  expiry: string; quantity: number; unit_cost: number; line_total: number;
  condition: string;
}
interface Receipt {
  id: number; grv_number: string; status: string;
  supplier_id: number; supplier: string;
  order_id: number | null; order_number: string;
  delivery_note: string; invoice_number: string; invoice_id: number | null;
  goods_total: number; notes: string;
  received_by: string; received_at: string;
  lines: number; packs: number; damaged: number;
  items: Item[];
}

export default function GoodsReceipts() {
  const toast = useToast();
  const ask = useAsk();
  const mayReceive = useCan("stock.receive");
  const [rows, setRows] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  /** The delivery being put against a bill, and the bills it could be on. */
  const [matching, setMatching] = useState<Receipt | null>(null);
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  /** The two subsets somebody actually comes here for, on their own controls
   *  rather than buried in a dropdown of statuses. */
  const [unbilledOnly, setUnbilledOnly] = useState(false);
  const [damagedOnly, setDamagedOnly] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get<{ receipts: Receipt[] }>("/api/goods-receipts")
      .then((r) => setRows(r.receipts))
      .catch((e) => toast.error(errorText(e, "The deliveries could not be read.")))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  /** Goods received and not yet matched to a bill. The number this screen is for. */
  const unbilled = useMemo(() => {
    const some = rows.filter((r) => !r.invoice_number && r.status === "received");
    return {
      count: some.length,
      value: Math.round(some.reduce((sum, r) => sum + r.goods_total, 0) * 100) / 100,
    };
  }, [rows]);

  const stillOpen = useMemo(
    () => rows.filter((r) => r.status === "open").length, [rows]);

  /** Every supplier who has actually delivered, offered as a choice.
   *
   *  Not the supplier list: a pharmacy carries two hundred accounts and buys
   *  from nine of them, and a dropdown of two hundred names to pick one of
   *  nine is a worse control than no control. */
  const whoDelivers = useMemo(() => {
    const seen = new Map<number, string>();
    for (const r of rows) if (r.supplier_id) seen.set(r.supplier_id, r.supplier);
    return [...seen.entries()]
      .sort((a, b) => a[1].localeCompare(b[1]))
      .map(([id, name]) => [String(id), name] as [string, string]);
  }, [rows]);

  const shown = useMemo(() => {
    let some = applyFilters(rows, filters, {
      search: (r) => [r.grv_number, r.supplier, r.order_number,
                      r.delivery_note, r.invoice_number, r.received_by],
      date: (r) => r.received_at,
      dims: {
        status: (r) => r.status,
        supplier: (r) => String(r.supplier_id ?? ""),
      },
    });
    // A delivery still being unloaded has no invoice yet by definition, and
    // nobody is chasing a bill for goods that are still coming off the van.
    // Including them would put the whole morning's work on a list of things
    // going wrong.
    if (unbilledOnly) {
      some = some.filter((r) => !r.invoice_number && r.status === "received");
    }
    if (damagedOnly) some = some.filter((r) => r.damaged > 0);
    return some;
  }, [rows, filters, unbilledOnly, damagedOnly]);

  /** The bands at the top are the filters they describe.
   *
   *  A total nobody can act on is a total nobody chases. "$1,319 across three
   *  deliveries with no invoice" was a sentence; pressing it now puts those
   *  three deliveries on the screen underneath it. */
  function only(patch: { unbilled?: boolean; status?: string }) {
    setUnbilledOnly(Boolean(patch.unbilled));
    setDamagedOnly(false);
    setFilters({ ...emptyFilters,
                 dims: patch.status ? { status: patch.status } : {} });
  }

  async function putOn(r: Receipt, invoice: Candidate | null) {
    // Optimistic: the row moves out of "no invoice yet" on the click, because
    // this is a decision somebody has just made rather than a question.
    const was = r.invoice_number;
    setRows((all) => all.map((x) => x.id === r.id
      ? { ...x, invoice_number: invoice?.invoice_number ?? "" } : x));
    setMatching(null);
    try {
      const said = await api.post<{ message: string }>(
        `/api/goods-receipts/${r.id}/match`,
        { invoice_id: invoice?.id ?? null });
      toast.ok(said.message);
      load();
    } catch (e) {
      setRows((all) => all.map((x) => x.id === r.id
        ? { ...x, invoice_number: was } : x));
      toast.error(errorText(e, "That delivery could not be matched."));
    }
  }

  async function sign(r: Receipt) {
    const { ok, value } = await ask({
      title: `Sign for ${r.grv_number}`,
      body: <>
        {r.packs.toLocaleString()} pack{r.packs === 1 ? "" : "s"} from {r.supplier},
        {" "}{money(r.goods_total)} at cost. The goods are already on the shelf;
        {" "}this finishes the paperwork. Enter the number on the invoice if it
        {" "}came with the van.
      </>,
      field: "Invoice number",
      placeholder: "leave empty if it follows later",
      maxLength: 40,
      confirmLabel: "Sign for it",
    });
    if (!ok) return;

    // Optimistic: the badge moves on the click, because signing is a decision
    // somebody has just made rather than a question for the server.
    const was = { status: r.status, invoice_number: r.invoice_number };
    setRows((all) => all.map((x) => x.id === r.id
      ? { ...x, status: "received", invoice_number: value.trim() || x.invoice_number }
      : x));
    try {
      const said = await api.post<{ message: string }>(
        `/api/goods-receipts/${r.id}/close`, { invoice_number: value.trim() });
      toast.ok(said.message);
      load();
    } catch (e) {
      setRows((all) => all.map((x) => x.id === r.id ? { ...x, ...was } : x));
      toast.error(errorText(e, "That delivery could not be signed for."));
    }
  }

  return (
    <>
      {matching && (
        <MatchToBill delivery={matching} onClose={() => setMatching(null)}
                     onMatched={(inv) => void putOn(matching, inv)} />
      )}
      {/* Goods on the shelf that cannot be checked against a bill. */}
      {unbilled.count > 0 && (
        <button type="button" className="sr-owed sr-owed-act"
                aria-pressed={unbilledOnly}
                onClick={() => unbilledOnly ? only({}) : only({ unbilled: true })}>
          <span className="sr-owed-n">{money(unbilled.value)}</span>
          <span>
            of goods received across {unbilled.count} deliver
            {unbilled.count === 1 ? "y" : "ies"} with no invoice number against
            {unbilled.count === 1 ? " it" : " them"}. When the statement comes
            {" "}there is nothing to hold it up to.
            <b className="sr-owed-do">
              {unbilledOnly ? "Showing them. Press to show everything."
                            : "Show me those deliveries"}
            </b>
          </span>
        </button>
      )}

      {stillOpen > 0 && (
        <p className="muted small sr-say">
          <button type="button" className="btn-link"
                  onClick={() => only({ status: "open" })}>
            {stillOpen} deliver{stillOpen === 1 ? "y is" : "ies are"} still open
          </button>
          . The stock is on the shelf; the paperwork is not signed.
        </p>
      )}

      {rows.length === 0 && !loading ? (
        <div className="empty">
          <b>No deliveries on file</b>
          <p>
            {mayReceive
              ? "A delivery is recorded when an order is booked in, whether it "
                + "is keyed or scanned at the back door. Each van becomes one "
                + "document here, carrying the driver's note, the invoice "
                + "number, the lots and who signed for them."
              : "Deliveries booked in against an order appear here. Booking one "
                + "in needs permission to receive stock."}
          </p>
        </div>
      ) : (
      <>
      <div className="dt-filters">
        <FilterBar
          value={filters}
          onChange={setFilters}
          placeholder="Delivery, supplier, order, note or invoice…"
          showDates
          dimensions={[
            { key: "status", label: "Standing",
              options: [["open", "Still unloading"], ["received", "Signed for"]] },
            ...(whoDelivers.length > 1
              ? [{ key: "supplier", label: "Supplier", options: whoDelivers }]
              : []),
          ]}
          extras={{ active: unbilledOnly || damagedOnly,
                    clear: () => { setUnbilledOnly(false); setDamagedOnly(false); } }}
        >
          <FilterToggle checked={unbilledOnly} onChange={setUnbilledOnly}
                        hint="Signed deliveries with no invoice number on them">
            No invoice yet
          </FilterToggle>
          <FilterToggle checked={damagedOnly} onChange={setDamagedOnly}
                        hint="Deliveries carrying packs booked in as damaged">
            With damage
          </FilterToggle>
          <span className="dt-count muted">
            {shown.length} of {rows.length}
          </span>
        </FilterBar>
      </div>

      <Refreshable loading={loading} hasData={rows.length > 0}
                   skeleton={<TableSkeleton cols={6} rows={5}
                                            widths={["14ch", "20ch", "12ch", "10ch", "12ch", "10ch"]} />}>
        <div className="dt-scroll">
          {/* WIDTHS THAT ADD UP TO THE SCREEN.
              Declared on the header, because a fixed layout sizes from the
              first row alone. Only the columns with a known shape are given
              one: a date, an order number, a count and a money figure. The
              supplier and the paperwork share what is left, because those
              are the two that hold a sentence rather than a token, and a
              sixth width would be the one that pushed the action button off
              the right of the screen. */}
          <table className="dt gr-table">
            <thead>
              <tr>
                <th className="col-when">Delivery</th>
                <th>Supplier</th>
                <th className="col-code">Against</th>
                <th className="num col-count">Packs</th>
                <th className="num col-money">At cost</th>
                <th>Paperwork</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                // Keyed on the fragment: a bare <> in a map gives React nothing
                // to track, so it rebuilds both rows on every change and loses
                // the open panel while somebody is reading it.
                <Fragment key={r.id}>
                  <tr>
                    <td>
                      {/* An identifier opens the record. It used to only
                          expand a row, so the delivery document had a page
                          nothing could reach. The peek stays, on its own
                          control, for reading a line without leaving. */}
                      <EntityLink to={`/deliveries/${r.id}`}>{r.grv_number}</EntityLink>
                      <button type="button" className="btn-link small gr-peek"
                              aria-expanded={open === r.id}
                              onClick={() => setOpen(open === r.id ? null : r.id)}>
                        {open === r.id ? "Hide lines" : "Lines"}
                      </button>
                      {/* Two lines rather than one. The date and a username
                          joined by a dot overran the column and clipped mid
                          word, which reads as a rendering fault rather than as
                          a long name. */}
                      <div className="muted small">{fmtDate(r.received_at)}</div>
                      {r.received_by && (
                        <div className="muted small gr-by">signed {r.received_by}</div>
                      )}
                    </td>
                    {/* The supplier is the most useful thing on the row and
                        was the one thing on it nobody could follow: a van
                        arrives short, and the question straight afterwards is
                        what else this wholesaler has done lately. */}
                    <td>
                      <EntityLink kind="supplier" id={r.supplier_id}>
                        {r.supplier}
                      </EntityLink>
                    </td>
                    <td className="small">
                      {r.order_id
                        ? <EntityLink to={`/orders/${r.order_id}`}>
                            {r.order_number}
                          </EntityLink>
                        : <span className="muted" title={
                            "Booked in without an order, so there is nothing to "
                            + "check what arrived against what was asked for."}>
                            no order
                          </span>}
                    </td>
                    <td className="num">{r.packs.toLocaleString()}</td>
                    <td className="num">{money(r.goods_total)}</td>
                    <td>
                      {r.status === "open" && (
                        <span className="badge warn">still unloading</span>
                      )}
                      {r.delivery_note && (
                        <div className="muted small">note {r.delivery_note}</div>
                      )}
                      {r.invoice_number
                        ? <div className="small">
                            <span className="muted">invoice </span>
                            {r.invoice_id
                              ? <EntityLink to={`/payables/invoices/${r.invoice_id}`}>
                                  {r.invoice_number}
                                </EntityLink>
                              : <span className="muted" title={
                                  "The number was written on the delivery, but no "
                                  + "bill with it has been captured on Payables."}>
                                  {r.invoice_number}
                                </span>}
                          </div>
                        : r.status === "received" && (
                          <div className="muted small">no invoice yet</div>
                        )}
                      {/* Damaged goods are received and held, so they are on the
                          books and cannot be sold. Said here because it is the
                          credit somebody has to chase. */}
                      {r.damaged > 0 && (
                        <span className="badge danger">
                          {r.damaged} pack{r.damaged === 1 ? "" : "s"} damaged
                        </span>
                      )}
                    </td>
                    <td className="actions">
                      {r.status === "open" && mayReceive && (
                        <button type="button" className="btn small"
                                onClick={() => sign(r)}>
                          Sign for it
                        </button>
                      )}
                      {r.status === "received" && mayReceive && (
                        <button type="button" className="btn small secondary"
                                onClick={() => setMatching(r)}>
                          {r.invoice_number ? "Change invoice" : "Put on a bill"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {open === r.id && (
                    <tr className="sr-detail">
                      <td colSpan={7}>
                        <ul>
                          {r.items.map((l, i) => (
                            <li key={i}>
                              <EntityLink kind="product" id={l.product_id}>
                                <b>{l.product}</b>
                              </EntityLink>
                              <span className="muted">
                                {" · "}lot {l.batch || "unnamed"}
                                {l.expiry ? ` · expires ${fmtDate(l.expiry)}` : ""}
                                {" · "}{l.quantity.toLocaleString()} pack
                                {l.quantity === 1 ? "" : "s"}
                              </span>
                              {" "}{money(l.line_total)}
                              {l.condition === "damaged" && (
                                <span className="badge danger">damaged, held</span>
                              )}
                            </li>
                          ))}
                        </ul>
                        {r.notes && <p className="muted small">{r.notes}</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {/* Nothing matched, which is not the same as nothing on file. The
            screen used to show a header over an empty table and leave
            somebody wondering whether the deliveries had gone. */}
        {shown.length === 0 && rows.length > 0 && (
          <div className="empty">
            <b>No delivery matches that</b>
            <p>
              {rows.length} deliver{rows.length === 1 ? "y is" : "ies are"} on
              file. Widen the search or clear the filters to see them.
            </p>
            <button type="button" className="btn secondary"
                    onClick={() => only({})}>
              Show every delivery
            </button>
          </div>
        )}
      </Refreshable>
      </>
      )}
    </>
  );
}
