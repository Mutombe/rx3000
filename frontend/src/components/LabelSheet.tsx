/** Look at the labels before they go on the boxes.
 *
 *  The straight-through path after dispensing prints immediately — at a counter
 *  with a queue, a confirmation step is just a key to press. This screen is for
 *  the other case: a reprint, where somebody is deciding how many stickers they
 *  need and for which item, usually because the first attempt smudged or a
 *  repeat came in three boxes.
 *
 *  The preview is a preview, not a second implementation. `printLabels` owns the
 *  printed layout and the millimetre sizing; this only shows what it will
 *  produce. The first version of this file drew its own stickers, which meant
 *  two label designs that would drift apart at the first change — and it typed
 *  its own copy of the label fields, which is how it ended up reading a
 *  `pharmacist` field that does not exist while TypeScript stayed quiet.
 */
import { useEffect, useRef, useState } from "react";
import { api, errorText, fmtDate } from "../api";
import { printLabels } from "../print";
import type { Label } from "../types";
import { useToast } from "./Toast";

export default function LabelSheet({
  rxId, onClose,
}: { rxId: number; onClose: () => void }) {
  const toast = useToast();
  const [labels, setLabels] = useState<Label[] | null>(null);
  const [copies, setCopies] = useState(1);

  // The fetch depends on the script and nothing else. Holding the callbacks in a
  // ref rather than in the dependency list means a caller that passes an inline
  // arrow — the normal way to write this — cannot cause a refetch on every
  // render, which with a state update in the handler is an endless request loop.
  const cb = useRef({ onClose, toast });
  cb.current = { onClose, toast };

  useEffect(() => {
    let live = true;
    api.get<Label[]>(`/api/prescriptions/${rxId}/labels`)
      .then((l) => { if (live) setLabels(l); })
      .catch((e) => {
        if (!live) return;
        cb.current.toast.error(errorText(e, "Those labels could not be prepared."));
        cb.current.onClose();
      });
    return () => { live = false; };
  }, [rxId]);

  if (!labels) {
    return (
      <div className="modal-backdrop" role="presentation">
        <div className="modal"><p className="muted">Preparing labels…</p></div>
      </div>
    );
  }

  if (labels.length === 0) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h2>Nothing to print</h2>
          <p className="muted">
            This script has no dispensed items, so there are no labels for it yet.
          </p>
          <div className="modal-actions">
            <button className="btn primary" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal lbl-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Reprint labels</h2>
        <p className="muted">
          {labels.length} item{labels.length === 1 ? "" : "s"} on {labels[0].rx_number}
          {" · "}{labels.length * copies} sticker
          {labels.length * copies === 1 ? "" : "s"} will print.
        </p>

        <div className="lbl-preview">
          {labels.map((l, i) => (
            <article className="lbl" key={i}>
              <span className="lbl-pharmacy">{l.pharmacy_name}</span>
              <span className="lbl-patient">{l.patient_name}</span>
              <span className="lbl-med">
                {l.product_name} {l.strength}
                {l.dosage_form ? ` (${l.dosage_form})` : ""} — Qty {l.quantity}
              </span>
              {/* The line the sticker exists for. */}
              <span className="lbl-dose">{l.dosage_instructions || "As directed"}</span>
              {l.warnings && <span className="lbl-warn">{l.warnings}</span>}
              <span className="lbl-meta">
                <span>
                  {l.batch_number && `Batch ${l.batch_number}`}
                  {l.expiry_date && ` · Exp ${fmtDate(l.expiry_date)}`}
                  {l.repeats_remaining > 0 && ` · ${l.repeats_remaining} repeat(s) left`}
                </span>
                {/* Who checked it — this is what replaced the witness signature,
                    and the one thing on the label a patient can hold somebody to.
                    The field is `dispensed_by`; an invented name would have left
                    this blank on every label without any error. */}
                <span>{l.dispensed_by}</span>
              </span>
            </article>
          ))}
        </div>

        <label className="lbl-copies">
          Copies of each
          <input
            type="number" min={1} max={9} value={copies}
            onChange={(e) =>
              setCopies(Math.max(1, Math.min(9, Number(e.target.value) || 1)))}
          />
        </label>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn primary"
            onClick={() => { printLabels(labels, copies); onClose(); }}
          >
            Print
          </button>
        </div>
      </div>
    </div>
  );
}
