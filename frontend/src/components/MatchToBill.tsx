/** Which bill a delivery's goods are on.
 *
 *  WHY IT IS ITS OWN COMPONENT
 *
 *  It was written inside the deliveries list, so the delivery's own page could
 *  say "unbilled goods" in the facts at the top and offer nothing to do about
 *  it: somebody read the problem on the record and had to go back to the list
 *  and find the row again to fix it. The panel that answers the question now
 *  belongs to neither screen and is opened by both.
 *
 *  HOW THE LIST IS ORDERED, AND WHY
 *
 *  By how far each bill differs from what actually arrived, nearest first,
 *  because that is the question somebody is really answering. A bill for what
 *  the delivery cost is almost certainly the one; a bill that differs is the
 *  whole reason anybody checks. The list is narrowed to this supplier and to
 *  bills nothing else has claimed, which are the only ones it could honestly
 *  be.
 */
import { useEffect, useState } from "react";

import { api, errorText, fmtDate, money } from "../api";
import { useToast } from "./Toast";

/** A bill this delivery could be the goods for. */
export interface Candidate {
  id: number; invoice_number: string; invoice_date: string;
  total: number; status: string; differs_by: number; mine: boolean;
}

/** Only what the panel needs to speak about the delivery. Both callers hold
 *  a fuller record than this, and neither has to hand it over. */
export interface Delivery {
  id: number;
  grv_number: string;
  supplier: string;
  packs: number;
  goods_total: number;
  delivery_note: string;
  invoice_number: string;
}

export default function MatchToBill({ delivery, onClose, onMatched }: {
  delivery: Delivery;
  onClose: () => void;
  /** Called with the chosen bill, or null when it is taken off one. The
   *  caller owns what the screen then shows, because a list and a record
   *  page answer that differently. */
  onMatched: (invoice: Candidate | null) => void;
}) {
  const toast = useToast();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [looking, setLooking] = useState(true);

  useEffect(() => {
    let live = true;
    setLooking(true);
    api.get<{ invoices: Candidate[] }>(
      `/api/goods-receipts/${delivery.id}/invoice-candidates`)
      .then((said) => { if (live) setCandidates(said.invoices); })
      .catch((e) => {
        if (live) toast.error(errorText(e, "The invoices could not be read."));
      })
      .finally(() => { if (live) setLooking(false); });
    return () => { live = false; };
  }, [delivery.id, toast]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Which bill is {delivery.grv_number} on?</h2>
        <p className="muted small">
          {delivery.packs.toLocaleString()} pack
          {delivery.packs === 1 ? "" : "s"} from {delivery.supplier},
          {" "}{money(delivery.goods_total)} at cost
          {delivery.delivery_note ? `, on note ${delivery.delivery_note}` : ""}.
        </p>

        {looking && <p className="muted">Reading the bills on file…</p>}

        {!looking && candidates.length === 0 && (
          <div className="empty">
            <b>No bill on file from {delivery.supplier}</b>
            <p>
              An invoice arrives on the supplier's timetable, often weeks
              after the van. Capture it on Payables and come back, or leave
              this delivery unmatched until it does.
            </p>
          </div>
        )}

        {!looking && candidates.length > 0 && (
          <ul className="gr-bills">
            {candidates.map((inv) => (
              <li key={inv.id}>
                <button type="button"
                        className={`gr-bill${inv.mine ? " on" : ""}`}
                        onClick={() => onMatched(inv)}>
                  <span className="gr-bill-no">
                    {inv.invoice_number || "unnumbered"}
                  </span>
                  <span className="muted small">
                    {inv.invoice_date ? fmtDate(inv.invoice_date) : "no date"}
                    {" · "}{money(inv.total)}
                  </span>
                  {Math.abs(inv.differs_by) < 0.01
                    ? <span className="badge ok">agrees with the goods</span>
                    : <span className="badge warn">
                        {money(Math.abs(inv.differs_by))}{" "}
                        {inv.differs_by > 0 ? "more than" : "less than"} the goods
                      </span>}
                  {inv.mine && <span className="badge muted">currently on this</span>}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="modal-actions">
          {delivery.invoice_number && (
            <button className="secondary" onClick={() => onMatched(null)}>
              Take it off this bill
            </button>
          )}
          <button className="secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
