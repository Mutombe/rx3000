/** Booking a van in, as the van actually arrived.
 *
 *  The old form asked for one batch number and one expiry per order line and
 *  sent no quantity at all, which quietly asserted three things that are
 *  routinely untrue: that everything ordered turned up, that it all came from
 *  one lot, and that none of it was damaged.
 *
 *  Each of those had a cost. A supplier who sent eight of ten was recorded as
 *  having sent ten, so the shelf gained two packs that were not on it and the
 *  short delivery could not be chased because nothing said it was short. A
 *  supplier sending three cartons from three lots had two of them discarded or
 *  invented, and a recall cannot find a lot that was invented. A cracked
 *  carton was either booked in as good stock or refused at the door, and
 *  refusing it loses the claim against the wholesaler, which is the money.
 *
 *  The server has always been able to take all three. Nothing could send them.
 *
 *  WHAT IS AT THE TOP, AND WHY
 *
 *  The driver's note and the invoice number. They are on a piece of paper in
 *  somebody's hand at the back door and that is the only moment anybody has
 *  them: a system that asks for them later is a system that does not get them.
 *  They go onto the goods receipt, which is what a supplier return and a
 *  disputed invoice are both argued from.
 *
 *  WHAT IT REFUSES TO LET SOMEBODY DO
 *
 *  Send lots that do not add up to the quantity being booked in. The server
 *  refuses it too, and would be right to, but a refusal arriving after the
 *  button is a form that wasted somebody's time: the sum is shown while they
 *  type, against the number it has to reach.
 */
import { useMemo, useState } from "react";

import { api, errorText, money } from "../api";
import { useToast } from "./Toast";
import { PurchaseOrder } from "../types";

interface Lot {
  batch_number: string;
  expiry_date: string;
  quantity: number;
  condition: "good" | "damaged";
}
interface Line {
  item_id: number;
  name: string;
  outstanding: number;
  unit_cost: number;
  /** What arrived. Starts at everything outstanding, which is the common case. */
  arrived: number;
  lots: Lot[];
}

function freshLot(quantity: number): Lot {
  return { batch_number: "", expiry_date: "", quantity, condition: "good" };
}

export default function ReceiveDelivery({
  order, onDone, onCancel,
}: {
  order: PurchaseOrder;
  onDone: (said: string) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [invoice, setInvoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<Line[]>(() =>
    order.items
      .map((i) => {
        const outstanding = Math.max(
          0, (i.quantity_ordered || 0) - (i.quantity_received || 0));
        return {
          item_id: i.id,
          name: `${i.product?.name ?? ""} ${i.product?.strength ?? ""}`.trim(),
          outstanding,
          unit_cost: i.unit_cost || 0,
          arrived: outstanding,
          lots: [freshLot(outstanding)],
        };
      })
      // A line already fully received has nothing left to book in, so it is
      // not shown: a second van against one order should show what the second
      // van can carry and nothing else.
      .filter((l) => l.outstanding > 0));

  function edit(idx: number, how: (line: Line) => Line) {
    setLines((all) => all.map((l, i) => (i === idx ? how(l) : l)));
  }

  /** The sum a line's lots have to reach, and whether they do. */
  function counted(l: Line) {
    return l.lots.reduce((sum, lot) => sum + (Number(lot.quantity) || 0), 0);
  }

  const problem = useMemo(() => {
    const live = lines.filter((l) => l.arrived > 0);
    if (!live.length) return "Nothing is being booked in.";
    for (const l of live) {
      if (l.arrived > l.outstanding) {
        return `${l.name}: ${l.outstanding} pack(s) are outstanding and ${l.arrived} are entered. A delivery larger than the order is a separate receipt.`;
      }
      if (counted(l) !== l.arrived) {
        return `${l.name}: the lots add up to ${counted(l)} and ${l.arrived} arrived. Every pack has to be on a lot, or a recall cannot find it.`;
      }
      for (const lot of l.lots) {
        if (lot.expiry_date && lot.expiry_date <= new Date().toISOString().slice(0, 10)) {
          return `${l.name}: batch ${lot.batch_number || "unnamed"} is already expired. Do not book it in. Quarantine it and raise it with the supplier.`;
        }
      }
    }
    return "";
  }, [lines]);

  const short = lines.some((l) => l.arrived < l.outstanding);
  const worth = lines.reduce((sum, l) => sum + l.arrived * l.unit_cost, 0);
  const damaged = lines.reduce(
    (sum, l) => sum + l.lots.filter((x) => x.condition === "damaged")
      .reduce((n, x) => n + (Number(x.quantity) || 0), 0), 0);

  async function submit() {
    if (problem) { toast.error(problem); return; }
    setBusy(true);
    try {
      const said = await api.post<{ status: string; grv_number?: string }>(
        `/api/orders/${order.id}/status?status=received`,
        {
          delivery_note: note.trim(),
          invoice_number: invoice.trim(),
          lines: lines.filter((l) => l.arrived > 0).map((l) => ({
            item_id: l.item_id,
            quantity: l.arrived,
            batches: l.lots.map((lot) => ({
              batch_number: lot.batch_number.trim(),
              expiry_date: lot.expiry_date || null,
              quantity: Number(lot.quantity) || 0,
              condition: lot.condition,
            })),
          })),
        });
      onDone(
        `${said.grv_number ? said.grv_number + ": " : ""}`
        + `stock is on the shelf.`
        + (said.status === "sent"
          ? " The order stays open: some of it has not arrived yet."
          : " The order is complete.")
        + (damaged
          ? ` ${damaged} pack(s) came in damaged and are held, not on sale.`
          : ""));
    } catch (e) {
      toast.error(errorText(e, "That delivery could not be booked in."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal rd-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Receive {order.order_number}</h2>
        <p className="muted small">
          Book in what actually arrived. A short delivery leaves the order open
          so the rest can be booked against it when it comes.
        </p>

        {/* The paperwork in somebody's hand, captured at the only moment it is. */}
        <div className="form-row rd-paper">
          <div className="field">
            <label>Delivery note</label>
            <input value={note} maxLength={40} placeholder="the driver's number"
                   onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="field">
            <label>Invoice number</label>
            <input value={invoice} maxLength={40} placeholder="if it came with the van"
                   onChange={(e) => setInvoice(e.target.value)} />
          </div>
        </div>

        {lines.length === 0 && (
          <p className="muted">Every line on this order has already been received.</p>
        )}

        {lines.map((l, idx) => (
          <div key={l.item_id} className="rd-line">
            <div className="rd-line-head">
              <b>{l.name}</b>
              <span className="muted small">{l.outstanding} outstanding</span>
            </div>

            <div className="form-row">
              <div className="field rd-qty">
                <label>Packs arrived</label>
                <input type="number" min={0} max={l.outstanding} value={l.arrived}
                       onChange={(e) => {
                         const n = Math.max(0, Number(e.target.value) || 0);
                         edit(idx, (line) => ({
                           ...line,
                           arrived: n,
                           // One lot follows the quantity, because that is the
                           // ordinary delivery and retyping it is friction for
                           // no reason. Two or more are somebody's own split
                           // and are left exactly as entered.
                           lots: line.lots.length === 1
                             ? [{ ...line.lots[0], quantity: n }]
                             : line.lots,
                         }));
                       }} />
              </div>
              <div className="field rd-worth">
                <label>At cost</label>
                <div className="rd-worth-n">{money(l.arrived * l.unit_cost)}</div>
              </div>
            </div>

            {l.lots.map((lot, li) => (
              <div key={li} className="form-row rd-lot">
                <div className="field">
                  <label>Batch number</label>
                  <input value={lot.batch_number} placeholder="auto"
                         onChange={(e) => edit(idx, (line) => ({
                           ...line,
                           lots: line.lots.map((x, i) =>
                             i === li ? { ...x, batch_number: e.target.value } : x),
                         }))} />
                </div>
                <div className="field">
                  <label>Expiry</label>
                  <input type="date" value={lot.expiry_date}
                         onChange={(e) => edit(idx, (line) => ({
                           ...line,
                           lots: line.lots.map((x, i) =>
                             i === li ? { ...x, expiry_date: e.target.value } : x),
                         }))} />
                </div>
                <div className="field rd-qty">
                  <label>Packs</label>
                  <input type="number" min={0} value={lot.quantity}
                         onChange={(e) => edit(idx, (line) => ({
                           ...line,
                           lots: line.lots.map((x, i) =>
                             i === li ? { ...x, quantity: Math.max(0, Number(e.target.value) || 0) } : x),
                         }))} />
                </div>
                <div className="field rd-cond">
                  <label>Condition</label>
                  <select value={lot.condition}
                          onChange={(e) => edit(idx, (line) => ({
                            ...line,
                            lots: line.lots.map((x, i) =>
                              i === li ? { ...x, condition: e.target.value as "good" | "damaged" } : x),
                          }))}>
                    <option value="good">Good</option>
                    <option value="damaged">Damaged</option>
                  </select>
                </div>
                {l.lots.length > 1 && (
                  <button type="button" className="btn small ghost rd-drop"
                          onClick={() => edit(idx, (line) => ({
                            ...line,
                            lots: line.lots.filter((_x, i) => i !== li),
                          }))}>
                    Remove
                  </button>
                )}
              </div>
            ))}

            <div className="rd-line-foot">
              {/* Outlined rather than the house's ghost, and quieter than the
                  primary. A second lot on one
                  line is the case this form was rebuilt for, and a control
                  nobody finds is a case nobody records: the delivery gets
                  squeezed onto one invented batch number, which is exactly
                  what a recall cannot then trace. */}
              <button type="button" className="btn small secondary"
                      onClick={() => edit(idx, (line) => ({
                        ...line,
                        lots: [...line.lots,
                               freshLot(Math.max(0, line.arrived - counted(line)))],
                      }))}>
                + Another lot
              </button>
              {/* The sum, while somebody types, against the number it has to
                  reach. A refusal that arrives after the button is a form that
                  wasted their time. */}
              <span className={`muted small${counted(l) !== l.arrived ? " rd-off" : ""}`}>
                {counted(l)} of {l.arrived} pack{l.arrived === 1 ? "" : "s"} on a lot
              </span>
            </div>

            {/* A damaged lot is received and then held. Said here, because
                "damaged" reads like a refusal and it is the opposite. */}
            {l.lots.some((x) => x.condition === "damaged") && (
              <p className="muted small">
                Damaged packs come onto the books and straight into held stock,
                {" "}so they are counted, cannot be sold, and the credit can be
                {" "}claimed from the supplier.
              </p>
            )}
          </div>
        ))}

        {problem && <p className="rd-problem">{problem}</p>}

        <div className="rd-total">
          <span>{money(worth)} at cost</span>
          {short && <span className="badge warn">part delivery, order stays open</span>}
        </div>

        <div className="modal-actions">
          <button className="secondary" onClick={onCancel}>Cancel</button>
          <button onClick={submit} disabled={busy || !!problem || !lines.length}>
            {busy ? "Booking in…" : "Receive into stock"}
          </button>
        </div>
      </div>
    </div>
  );
}
