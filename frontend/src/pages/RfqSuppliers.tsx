/** Who was asked on a request for quotation, and the two things a buyer does
 *  about it: send them their own link, or write down what they said.
 *
 *  PROVENANCE IS SHOWN, NOT ASSUMED
 *
 *  A price the wholesaler typed into their own link and one a member of staff
 *  wrote down from a telephone call are different levels of confidence in the
 *  same figure, and the difference is what matters when a supplier later
 *  disputes it. The card says which, and by whom.
 *
 *  OPENED IS NOT ANSWERED
 *
 *  A wholesaler who never opened the email needs it re-sending; one who read
 *  it three days ago and has gone quiet needs ringing. Those are different
 *  phone calls, so they are different states here rather than one "waiting".
 */
import { useState } from "react";

import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import { useToast } from "../components/Toast";
import Th from "../components/Th";

export interface QuoteAnswer {
  rfq_supplier_id: number;
  answered: boolean;
  available: boolean | null;
  unit_price: number | null;
  lead_days: number | null;
}

export interface QuoteLine {
  rfq_line_id: number;
  product: string;
  quantity: number;
  answers: QuoteAnswer[];
}

export interface InvitedSupplier {
  rfq_supplier_id: number;
  supplier_id: number;
  supplier: string;
  sent_at: string | null;
  opened_at: string | null;
  responded_at: string | null;
  declined: boolean;
  note: string;
  self_quoted: boolean;
  recorded_by: string;
}

interface Draft { price: string; lead: string; out: boolean }

export default function SupplierCard({ rfqId, invited, lines, closed, onRecorded }: {
  rfqId: string;
  invited: InvitedSupplier;
  lines: QuoteLine[];
  closed: boolean;
  onRecorded: () => void;
}) {
  const toast = useToast();
  const [recording, setRecording] = useState(false);

  async function copyLink() {
    try {
      const said = await api.get<{ link: string; share_text: string }>(
        `/api/rfqs/${rfqId}/suppliers/${invited.rfq_supplier_id}/link`);
      await navigator.clipboard.writeText(said.share_text);
      toast.ok(`${invited.supplier}'s link is on the clipboard, with a message `
        + "around it. Paste it into WhatsApp or an email.");
    } catch (e) {
      toast.error(errorText(e, "That link could not be made."));
    }
  }

  const state = invited.declined
    ? { tone: "bad", text: "Cannot supply this request" }
    : invited.responded_at
      ? { tone: "ok", text: `Answered ${fmtDate(invited.responded_at)}` }
      : invited.opened_at
        ? { tone: "warn", text: `Opened ${fmtDate(invited.opened_at)}, no prices yet` }
        : invited.sent_at
          ? { tone: "warn", text: `Sent ${fmtDate(invited.sent_at)}, not opened` }
          : { tone: "muted", text: "Not asked yet" };

  return (
    <div className="rfq-who-card">
      <div className="rfq-who-head">
        <EntityLink to={`/suppliers/${invited.supplier_id}`}>
          {invited.supplier}
        </EntityLink>
        <span className={`badge ${state.tone}`}>{state.text}</span>
      </div>

      {invited.responded_at && (
        <div className="muted small">
          {invited.self_quoted
            ? "They entered these prices themselves."
            : invited.recorded_by
              ? `Written down by ${invited.recorded_by}.`
              : "Written down here. Who did it was not recorded."}
        </div>
      )}
      {invited.note && (
        <div className="muted small wrap rfq-who-note">{invited.note}</div>
      )}

      {!closed && (
        <div className="rfq-who-acts">
          <button type="button" className="btn secondary small" onClick={copyLink}>
            Copy their link
          </button>
          <button type="button" className="btn secondary small"
                  onClick={() => setRecording(true)}>
            {invited.responded_at ? "Change" : "Record"} what they said
          </button>
        </div>
      )}

      {recording && (
        <RecordAnswer rfqId={rfqId} invited={invited} lines={lines}
                      onClose={() => setRecording(false)}
                      onSaved={() => { setRecording(false); onRecorded(); }} />
      )}
    </div>
  );
}

/** Typing in what a wholesaler said on the telephone.
 *
 *  Their own link is the better route and the email carries it, but a
 *  supplier who rings back is not going to be told to go and use a link.
 *  What this keeps is who typed it, so the figure can be queried later.
 */
function RecordAnswer({ rfqId, invited, lines, onClose, onSaved }: {
  rfqId: string;
  invited: InvitedSupplier;
  lines: QuoteLine[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [note, setNote] = useState(invited.note ?? "");
  const [rows, setRows] = useState<Record<number, Draft>>(
    () => Object.fromEntries(lines.map((l) => {
      // Whatever is already against this supplier comes back, so correcting
      // one price does not wipe the rest.
      const had = l.answers.find((a) => a.rfq_supplier_id === invited.rfq_supplier_id);
      return [l.rfq_line_id, {
        price: had?.unit_price != null ? String(had.unit_price) : "",
        lead: had?.lead_days != null ? String(had.lead_days) : "",
        out: !!had?.answered && had.available === false,
      }];
    })));

  function set(id: number, patch: Partial<Draft>) {
    setRows((all) => ({ ...all, [id]: { ...all[id], ...patch } }));
  }

  const total = lines.reduce((sum, l) => {
    const r = rows[l.rfq_line_id];
    return sum + (r && !r.out ? (Number(r.price) || 0) * l.quantity : 0);
  }, 0);

  async function save(declined: boolean) {
    try {
      const said = await api.post<{ message: string }>(
        `/api/rfqs/${rfqId}/answers/${invited.rfq_supplier_id}`, {
          declined, note,
          answers: declined ? [] : lines
            // A line nobody typed anything against stays unanswered. Silence
            // and a price of nought are different facts, and the comparison
            // keeps them apart.
            .filter((l) => {
              const r = rows[l.rfq_line_id];
              return r && (r.out || r.price.trim() !== "");
            })
            .map((l) => {
              const r = rows[l.rfq_line_id];
              return {
                rfq_line_id: l.rfq_line_id,
                available: !r.out,
                unit_price: r.out ? 0 : Number(r.price) || 0,
                lead_days: r.lead.trim() === "" ? null : Number(r.lead),
              };
            }),
        });
      toast.ok(said.message);
      onSaved();
    } catch (e) {
      toast.error(errorText(e, "That answer could not be saved."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal rfq-answer" onClick={(e) => e.stopPropagation()}>
        <h2>What {invited.supplier} said</h2>
        <p className="muted">
          Better entered by the wholesaler themselves, on the link in their
          email. This is for one who rang back.
        </p>

        <div className="table-wrap">
          <table className="dt">
            <thead>
              <tr>
                <Th>Medicine</Th><Th className="num">Wanted</Th>
                <Th className="num">Unit price</Th><Th className="num">Lead days</Th>
                <Th className="num">Line total</Th><Th>Cannot supply</Th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const r = rows[l.rfq_line_id];
                return (
                  <tr key={l.rfq_line_id}>
                    <td>{l.product}</td>
                    <td className="num">{l.quantity}</td>
                    <td className="num">
                      <input className="st-control" inputMode="decimal"
                             value={r.price} disabled={r.out} placeholder="0.00"
                             onChange={(e) => set(l.rfq_line_id, { price: e.target.value })} />
                    </td>
                    <td className="num">
                      <input className="st-control" inputMode="numeric"
                             value={r.lead} disabled={r.out} placeholder="days"
                             onChange={(e) => set(l.rfq_line_id, { lead: e.target.value })} />
                    </td>
                    {/* The extended figure, where a misplaced decimal point
                        shows up while somebody can still fix it. */}
                    <td className="num">
                      {r.out ? <span className="muted">Not supplied</span>
                             : money((Number(r.price) || 0) * l.quantity)}
                    </td>
                    <td>
                      <input type="checkbox" checked={r.out}
                             onChange={(e) => set(l.rfq_line_id, { out: e.target.checked })} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>If they supplied everything quoted</th>
                <th className="num">{money(total)}</th>
                <th />
              </tr>
            </tfoot>
          </table>
        </div>

        <div className="field">
          <label htmlFor="rfq-ans-note">
            Anything else they said <span className="muted">optional</span>
          </label>
          <input id="rfq-ans-note" value={note} maxLength={400}
                 onChange={(e) => setNote(e.target.value)}
                 placeholder="delivery terms, minimum order, part supply" />
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <button className="btn secondary" onClick={() => save(true)}>
            They cannot supply any of it
          </button>
          <BusyButton className="btn primary" onClick={() => save(false)}
                      busyLabel="Saving…">
            Save what they said
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
