/** Adding another wholesaler to a request that is already out.
 *
 *  WHO IS SUGGESTED, AND WHY IT IS NOT A LIST OF EVERYBODY
 *
 *  The buying record already knows who actually supplies these lines. Leading
 *  with those three is the difference between asking the wholesalers who
 *  stock the thing and asking whoever somebody remembers, and most of the
 *  benefit of asking around comes from that one choice. The full list is
 *  still underneath, because a buyer trying a new supplier is exactly the
 *  person this screen should not get in the way of.
 *
 *  WHAT INVITING DOES NOT DO
 *
 *  It does not send anything. A supplier added here is invited, and the
 *  request is sent to them by the send button, like everybody else. Two
 *  separate acts, because adding the wrong name and emailing the wrong name
 *  should not be the same click.
 */
import { useEffect, useState } from "react";

import { api, errorText } from "../api";
import BusyButton from "../components/BusyButton";
import { useToast } from "../components/Toast";

interface Suggested {
  supplier_id: number;
  supplier: string;
  /** How many lines on this request they have supplied before. */
  lines: number;
  delivers: boolean;
  record: string;
}

interface SupplierLite { id: number; name: string; email: string }

export default function InviteSupplier({ rfqId, already, onClose, onInvited }: {
  rfqId: string;
  already: number[];
  onClose: () => void;
  onInvited: () => void;
}) {
  const toast = useToast();
  const [suggested, setSuggested] = useState<Suggested[] | null>(null);
  const [all, setAll] = useState<SupplierLite[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set());

  useEffect(() => {
    api.get<{ suppliers: Suggested[] }>(`/api/rfqs/${rfqId}/suggested-suppliers`)
      .then((r) => setSuggested(r.suppliers))
      // Said, not swallowed: without the suggestions this screen still works
      // off the full list, and a buyer who is not told wonders why the top
      // half is empty.
      .catch(() => {
        setSuggested([]);
        toast.error("The suggestions could not be worked out. Every supplier "
                    + "is still listed below.");
      });
    api.get<SupplierLite[]>("/api/suppliers").then(setAll).catch((e) =>
      toast.error(errorText(e, "The supplier list could not be loaded.")));
  }, [rfqId, toast]);

  function toggle(id: number) {
    setChosen((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function invite() {
    let added = 0;
    for (const supplier_id of chosen) {
      try {
        await api.post(`/api/rfqs/${rfqId}/invite`, { supplier_id });
        added += 1;
      } catch (e) {
        // Named, so a buyer knows which one did not go on rather than
        // finding a supplier missing from the grid tomorrow.
        const who = all.find((s) => s.id === supplier_id)?.name ?? "A supplier";
        toast.error(errorText(e, `${who} could not be added.`));
      }
    }
    if (added) {
      toast.ok(`${added} supplier(s) added. Send the request again so the new `
               + "ones get it.");
      onInvited();
    }
  }

  const newOnes = suggested?.filter((s) => !already.includes(s.supplier_id)) ?? [];
  const rest = all.filter((s) => !already.includes(s.id)
    && !newOnes.some((n) => n.supplier_id === s.id));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal rfq-invite" onClick={(e) => e.stopPropagation()}>
        <h2>Ask another supplier</h2>
        <p className="muted">
          They are added to the request. Nothing is sent until you send it.
        </p>

        {newOnes.length > 0 && (
          <>
            <label className="field-label">Who has supplied these lines before</label>
            <div className="rfq-invite-list">
              {newOnes.map((s) => (
                <label key={s.supplier_id} className="rfq-invite-row">
                  <input type="checkbox" checked={chosen.has(s.supplier_id)}
                         onChange={() => toggle(s.supplier_id)} />
                  <span>
                    <b>{s.supplier}</b>
                    <span className="muted small">
                      {[`${s.lines} line(s) on this request`,
                        s.delivers ? "delivers" : "",
                        s.record].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </>
        )}

        <label className="field-label">
          {newOnes.length > 0 ? "Everybody else" : "Suppliers"}
        </label>
        <div className="rfq-invite-list">
          {rest.length === 0 && (
            <p className="muted small">
              Everybody on file has already been asked.
            </p>
          )}
          {rest.map((s) => (
            <label key={s.id} className="rfq-invite-row">
              <input type="checkbox" checked={chosen.has(s.id)}
                     onChange={() => toggle(s.id)} />
              <span>
                <b>{s.name}</b>
                {!s.email && (
                  <span className="muted small">
                    no email on file, so you will have to send their link by hand
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={invite}
                      disabled={chosen.size === 0} busyLabel="Adding…">
            Add {chosen.size || "no"} supplier(s)
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
