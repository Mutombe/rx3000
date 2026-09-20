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
import { useToast } from "./Toast";
import { useAsk } from "./Confirm";
import { useCan } from "../session";

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
      {/* Goods on the shelf that cannot be checked against a bill. */}
      {unbilled.count > 0 && (
        <div className="sr-owed">
          <span className="sr-owed-n">{money(unbilled.value)}</span>
          <span>
            of goods received across {unbilled.count} deliver
            {unbilled.count === 1 ? "y" : "ies"} with no invoice number against
            {unbilled.count === 1 ? " it" : " them"}. When the statement comes
            {" "}there is nothing to hold it up to.
          </span>
        </div>
      )}

      {stillOpen > 0 && (
        <p className="muted small sr-say">
          {stillOpen} deliver{stillOpen === 1 ? "y is" : "ies are"} still open.
          {" "}The stock is on the shelf; the paperwork is not signed.
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
      <Refreshable loading={loading} hasData={rows.length > 0}
                   skeleton={<TableSkeleton cols={6} rows={5}
                                            widths={["14ch", "20ch", "12ch", "10ch", "12ch", "10ch"]} />}>
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>Delivery</th>
                <th>Supplier</th>
                <th>Against</th>
                <th className="num">Packs</th>
                <th className="num">At cost</th>
                <th>Paperwork</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                // Keyed on the fragment: a bare <> in a map gives React nothing
                // to track, so it rebuilds both rows on every change and loses
                // the open panel while somebody is reading it.
                <Fragment key={r.id}>
                  <tr>
                    <td>
                      <button type="button" className="btn-link"
                              onClick={() => setOpen(open === r.id ? null : r.id)}>
                        {r.grv_number}
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
                    <td>{r.supplier}</td>
                    <td className="muted small">{r.order_number || "no order"}</td>
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
                        ? <div className="muted small">invoice {r.invoice_number}</div>
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
                    </td>
                  </tr>
                  {open === r.id && (
                    <tr className="sr-detail">
                      <td colSpan={7}>
                        <ul>
                          {r.items.map((l, i) => (
                            <li key={i}>
                              <b>{l.product}</b>
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
      </Refreshable>
      )}
    </>
  );
}
