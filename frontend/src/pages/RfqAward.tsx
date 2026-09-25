/** Who won, why, and the second signature on it.
 *
 *  WHY THE APPROVAL IS ON THE AWARD AND NOT ON THE REQUEST
 *
 *  Asking three wholesalers for a price commits the pharmacy to nothing.
 *  Deciding which of them gets the business commits it to the money, and that
 *  is the decision somebody asks about afterwards.
 *
 *  THE REASON IS ASKED FOR ONLY WHEN IT IS NEEDED
 *
 *  Pick the cheapest on every line and there is nothing to explain and
 *  nothing to type. Pick a dearer supplier and the reason is asked for at the
 *  one moment anybody still knows it: they could not deliver until the 20th,
 *  they short-delivered the last three orders, the price was for a pack we
 *  cannot split. All perfectly good on the day and unrecoverable six weeks
 *  later, when the only surviving fact is that the pharmacy paid more than it
 *  had to.
 *
 *  THE REFUSAL SAYS WHY, IN WORDS
 *
 *  A disabled button that does not explain itself is how somebody concludes
 *  the software is broken and telephones the order through instead, which
 *  defeats the entire control.
 */
import { useState } from "react";

import { errorText, fmtDateTime, money } from "../api";
import BusyButton from "../components/BusyButton";
import Th from "../components/Th";

export interface DearerLine {
  rfq_line_id: number;
  product: string;
  chosen: string;
  chosen_price: number;
  chosen_lead_days: number | null;
  cheapest: string;
  cheapest_price: number;
  cheapest_lead_days: number | null;
  extra: number;
}

export interface AwardState {
  threshold: number;
  approval_used: boolean;
  value: number;
  needs_approval: boolean;
  approved: boolean;
  approved_at: string | null;
  approved_by: string;
  awarded_at: string | null;
  awarded_by: string;
  award_reason: string;
  refused_reason: string;
  refused_by: string;
  refused_at: string | null;
  dearer_lines: DearerLine[];
  why_refused: string;
  chosen: Record<string, number>;
}

/** Waiting on a second person: what they need to see to decide. */
export function AwaitingApproval({ award, onApprove, onSendBack }: {
  award: AwardState;
  onApprove: () => Promise<void>;
  onSendBack: (reason: string) => Promise<void>;
}) {
  const [sendingBack, setSendingBack] = useState(false);
  const [reason, setReason] = useState("");

  return (
    <div className="card rfq-approval">
      <div className="rfq-approval-head">
        <div>
          <b>Waiting to be signed off</b>
          <div className="muted small">
            {award.awarded_by
              ? `${award.awarded_by} chose these suppliers`
              : "Somebody chose these suppliers"}
            {award.awarded_at && ` on ${fmtDateTime(award.awarded_at)}`}
            {". "}
            Whoever made the choice cannot also approve it.
          </div>
        </div>
        <div className="rfq-approval-worth">
          <span className="muted small">Committing</span>
          <b>{money(award.value)}</b>
        </div>
      </div>

      {award.award_reason && (
        <div className="rfq-approval-reason">
          <span className="field-label">Why this award</span>
          <p>{award.award_reason}</p>
        </div>
      )}

      {award.dearer_lines.length > 0 && (
        <>
          <span className="field-label">
            Where the cheapest quote did not win
          </span>
          <div className="table-wrap">
            <table className="dt">
              <thead>
                <tr>
                  <Th>Medicine</Th><Th>Chosen</Th><Th>Cheapest</Th>
                  <Th className="num">Costs more</Th>
                </tr>
              </thead>
              <tbody>
                {award.dearer_lines.map((d) => (
                  <tr key={d.rfq_line_id}>
                    <td>{d.product}</td>
                    <td>
                      {d.chosen}
                      <div className="muted small">
                        {money(d.chosen_price)}
                        {d.chosen_lead_days !== null
                          && ` · ${d.chosen_lead_days} day(s)`}
                      </div>
                    </td>
                    <td>
                      {d.cheapest}
                      <div className="muted small">
                        {money(d.cheapest_price)}
                        {d.cheapest_lead_days !== null
                          && ` · ${d.cheapest_lead_days} day(s)`}
                      </div>
                    </td>
                    <td className="num">{money(d.extra)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {sendingBack ? (
        <div className="rfq-approval-back">
          <div className="field">
            <label htmlFor="rfq-back-why">Why it is going back</label>
            <input id="rfq-back-why" value={reason} maxLength={500} autoFocus
                   onChange={(e) => setReason(e.target.value)}
                   placeholder="what the buyer should do differently" />
            <span className="hint">
              A refusal the buyer cannot act on produces the same proposal
              again tomorrow.
            </span>
          </div>
          <div className="rfq-approval-acts">
            <button className="btn secondary"
                    onClick={() => { setSendingBack(false); setReason(""); }}>
              Cancel
            </button>
            <BusyButton className="btn danger" disabled={!reason.trim()}
                        onClick={() => onSendBack(reason)}
                        busyLabel="Sending back…">
              Send it back
            </BusyButton>
          </div>
        </div>
      ) : (
        <div className="rfq-approval-acts">
          <button className="btn secondary" onClick={() => setSendingBack(true)}>
            Send it back
          </button>
          <BusyButton className="btn primary" onClick={onApprove}
                      busyLabel="Approving…">
            Approve this award
          </BusyButton>
        </div>
      )}
    </div>
  );
}

/** Asking for the reason the cheapest lost, before the award is proposed. */
export function WhyNotCheapest({ dearer, onClose, onSaid }: {
  dearer: DearerLine[];
  onClose: () => void;
  onSaid: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const extra = dearer.reduce((sum, d) => sum + d.extra, 0);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal rfq-why" onClick={(e) => e.stopPropagation()}>
        <h2>The cheapest quote did not win</h2>
        <p className="muted">
          On {dearer.length} line{dearer.length === 1 ? "" : "s"}, costing{" "}
          {money(extra)} more. That is usually a perfectly good decision, and
          in six weeks this sentence will be the only record of why.
        </p>

        <div className="table-wrap rfq-why-list">
          <table className="dt">
            <thead>
              <tr>
                <Th>Medicine</Th><Th>Chosen</Th><Th>Cheapest</Th>
                <Th className="num">More</Th>
              </tr>
            </thead>
            <tbody>
              {dearer.map((d) => (
                <tr key={d.rfq_line_id}>
                  <td>{d.product}</td>
                  <td>
                    {d.chosen}
                    <div className="muted small">
                      {money(d.chosen_price)}
                      {d.chosen_lead_days !== null
                        && ` · ${d.chosen_lead_days} day(s)`}
                    </div>
                  </td>
                  <td>
                    {d.cheapest}
                    <div className="muted small">
                      {money(d.cheapest_price)}
                      {d.cheapest_lead_days !== null
                        && ` · ${d.cheapest_lead_days} day(s)`}
                    </div>
                  </td>
                  <td className="num">{money(d.extra)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="field">
          <label htmlFor="rfq-why-reason">Why</label>
          <input id="rfq-why-reason" value={reason} maxLength={500} autoFocus
                 onChange={(e) => setReason(e.target.value)}
                 placeholder="they are the only ones who can deliver this week" />
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!reason.trim()}
                      onClick={() => onSaid(reason)} busyLabel="Awarding…">
            Award them anyway
          </BusyButton>
        </div>
      </div>
    </div>
  );
}

/** The one line that says why the orders cannot be raised yet. */
export function WhyRefused({ award }: { award: AwardState }) {
  if (!award.why_refused && !award.refused_reason) return null;
  return (
    <>
      {award.refused_reason && (
        <div className="alert warn">
          <b>Sent back{award.refused_by ? ` by ${award.refused_by}` : ""}</b>
          <div>{award.refused_reason}</div>
        </div>
      )}
      {award.why_refused && <div className="alert">{award.why_refused}</div>}
    </>
  );
}

export { errorText };
