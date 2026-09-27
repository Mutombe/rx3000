/** Write down what the wholesaler actually billed.
 *
 *  WHY THIS WAS MISSING, WHICH IS THE ODD PART.
 *
 *  Creditors opens by saying that nothing in this system had ever read the
 *  invoice the wholesaler actually sent, and the whole screen is built around
 *  the difference between what was ordered, what arrived, and what was billed.
 *  The endpoint that records an invoice has existed all along, matches itself
 *  against the order, and had no caller anywhere in the product. So the screen
 *  could show a delivery with no bill behind it, call that "a debt that has
 *  not been recorded", and offer nothing.
 *
 *  IT OPENS FROM THE DELIVERY, NOT FROM A BLANK FORM.
 *
 *  A bill is always about something that arrived. Starting from the goods
 *  receipt means the supplier and the order are already known and cannot be
 *  got wrong, and the figure the pharmacy expected is on screen beside the box
 *  where the real one is typed. That comparison is the entire point of the
 *  exercise and it is free here: anywhere else it is a second query somebody
 *  has to think to run.
 *
 *  WHAT IT DOES NOT DO.
 *
 *  It does not approve anything. Recording what arrived in the post and
 *  agreeing to pay it are two decisions, made by two people on most days, and
 *  the approval already lives on the invoice's own panel.
 */
import { useState } from "react";
import { X } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";

export interface AwaitingBill {
  order_id: number;
  order_number: string;
  supplier_id: number;
  supplier: string;
  value: number;
}

export default function RecordTheBill({ against, onClose, onRecorded }: {
  /** The delivery this bill is for. */
  against: AwaitingBill;
  onClose: () => void;
  onRecorded: () => void;
}) {
  const [number, setNumber] = useState("");
  const [total, setTotal] = useState(String(against.value.toFixed(2)));
  const [vat, setVat] = useState("");
  const [dated, setDated] = useState("");
  const [due, setDue] = useState("");
  const [notes, setNotes] = useState("");
  const toast = useToast();

  const billed = Number(total) || 0;
  const differs = Math.abs(billed - against.value) > 0.005;

  async function save() {
    if (!number.trim()) {
      toast.warn("The supplier's own invoice number is what this is filed under.");
      return;
    }
    try {
      const made = await api.post<{ match?: { matched: boolean; says?: string } }>(
        "/api/payables/invoices", {
          invoice_number: number.trim(),
          supplier_id: against.supplier_id,
          order_id: against.order_id,
          total: billed,
          vat_total: Number(vat) || 0,
          invoice_date: dated || null,
          due_date: due || null,
          notes: notes.trim(),
        });
      // The match is the answer the pharmacy came for, so it is what the
      // message says rather than "Saved".
      toast.ok(made.match?.matched
        ? `${number.trim()} recorded and it agrees with ${against.order_number}.`
        : `${number.trim()} recorded. It does not agree with `
          + `${against.order_number}, so it is waiting to be looked at.`);
      onRecorded();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "That invoice could not be recorded."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="imp-head">
          <h2>Record {against.supplier}&rsquo;s bill</h2>
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>

        <p className="muted">
          For {against.order_number}, which came in at{" "}
          <b>{money(against.value)}</b> of goods. Recording it is not agreeing
          to pay it: approval is a separate press, on the invoice itself.
        </p>

        <div className="form-row">
          <label className="field">
            Their invoice number
            <input value={number} autoFocus maxLength={60}
                   placeholder="as printed on the document"
                   onChange={(e) => setNumber(e.target.value)} />
            <span className="field-hint">
              Filed under the supplier, so two wholesalers can both have an
              INV-1001.
            </span>
          </label>
          <label className="field">
            What they billed
            <input value={total} inputMode="decimal"
                   onChange={(e) => setTotal(e.target.value)} />
            {/* THE COMPARISON IS THE WHOLE EXERCISE.
                Said here, at the moment the figure is typed, rather than
                found later on a statement. A wholesaler billing more than
                they delivered is the commonest money leak in a pharmacy and
                the one nobody has time to go looking for. */}
            <span className={`field-hint${differs ? " is-bad" : ""}`}>
              {differs
                ? `${money(Math.abs(billed - against.value))} `
                  + `${billed > against.value ? "more" : "less"} than the goods `
                  + "that arrived. Worth a telephone call before it is approved."
                : "The same as the goods that arrived."}
            </span>
          </label>
        </div>

        <div className="form-row">
          <label className="field">
            VAT on it
            <input value={vat} inputMode="decimal" placeholder="0.00"
                   onChange={(e) => setVat(e.target.value)} />
          </label>
          <label className="field">
            Their invoice date
            <input type="date" value={dated}
                   onChange={(e) => setDated(e.target.value)} />
          </label>
          <label className="field">
            Due
            <input type="date" value={due}
                   onChange={(e) => setDue(e.target.value)} />
            <span className="field-hint">
              What ages it on this screen. Left blank it is due on their terms.
            </span>
          </label>
        </div>

        <label className="field">
          Anything to remember
          <input value={notes} maxLength={300}
                 placeholder="a short delivery, a price queried on the telephone"
                 onChange={(e) => setNotes(e.target.value)} />
        </label>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Not now</button>
          <BusyButton className="btn primary" onClick={save}
                      disabled={!number.trim()} busyLabel="Recording it…">
            Record it
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
