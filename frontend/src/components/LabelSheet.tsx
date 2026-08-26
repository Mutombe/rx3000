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
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { printLabels } from "../print";
import type { Label } from "../types";
import { useToast } from "./Toast";
import IconButton from "./IconButton";

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
              {/* Read in the order a label is read, which is not the order the
                  data arrives in.

                  The patient's name is first and unmissable because the first
                  question at a counter is whether this bag is the right one.
                  The medicine and its directions are the largest thing on the
                  sticker because that is what somebody reads at home, sometimes
                  without their glasses. Everything that exists for the pharmacy
                  and the inspector sits below the rule, quiet and tabular. The
                  shop's own name is last, where somebody with a question looks. */}
              <header className="lbl-top">
                <span className="lbl-patient">{l.patient_name}</span>
                {l.line_total > 0 && (
                  <span className="lbl-price">{money(l.line_total)}</span>
                )}
              </header>

              <div className="lbl-drug">
                <span className="lbl-med">
                  {l.product_name} {l.strength}
                </span>
                <span className="lbl-form">
                  {[l.dosage_form, l.quantity ? `Qty ${l.quantity}` : ""]
                    .filter(Boolean).join(" · ")}
                </span>
              </div>

              <p className="lbl-dose">{l.dosage_instructions || "As directed"}</p>

              {l.warnings && <p className="lbl-warn">{l.warnings}</p>}

              <dl className="lbl-audit">
                {/* Each label and its value is one unit that cannot be split.
                    Left as loose dt/dd in a wrapping row, "Checked" kept its
                    value but "On" ended a line and dropped its date onto the
                    next one, which reads as a stray timestamp. */}
                <div className="lbl-row">
                  <div className="lbl-pair">
                    <dt>Batch</dt><dd className="mono">{l.batch_number || "not recorded"}</dd>
                  </div>
                  {l.expiry_date && (
                    <div className="lbl-pair">
                      <dt>Exp</dt><dd className="mono">{fmtDate(l.expiry_date)}</dd>
                    </div>
                  )}
                </div>
                <div className="lbl-row">
                  <div className="lbl-pair">
                    <dt>Script</dt><dd className="mono">{l.rx_number}</dd>
                  </div>
                  <div className="lbl-pair">
                    <dt>Item</dt><dd>{l.item_number} of {l.item_count}</dd>
                  </div>
                </div>
                <div className="lbl-row">
                  <div className="lbl-pair">
                    <dt>Checked</dt><dd>{l.dispensed_by || "not recorded"}</dd>
                  </div>
                  <div className="lbl-pair">
                    <dt>On</dt><dd>{fmtDateTime(l.dispensed_at)}</dd>
                  </div>
                </div>
                {l.doctor_name && (
                  <div className="lbl-row">
                    <div className="lbl-pair">
                      <dt>Prescriber</dt>
                      <dd>
                        {l.doctor_name}
                        {l.doctor_practice_no && <span className="mono"> {l.doctor_practice_no}</span>}
                      </dd>
                    </div>
                  </div>
                )}
                {l.repeats_remaining > 0 && (
                  <div className="lbl-row">
                    <div className="lbl-pair">
                      <dt>Repeats</dt>
                      <dd>{l.repeats_remaining} left{l.next_repeat_date ? `, next ${fmtDate(l.next_repeat_date)}` : ""}</dd>
                    </div>
                  </div>
                )}
              </dl>

              <footer className="lbl-foot">
                <b>{l.pharmacy_name}</b>
                <span>
                  {[l.pharmacy_address, l.pharmacy_phone].filter(Boolean).join("  ·  ")}
                  {!l.pharmacy_address && !l.pharmacy_phone && l.pharmacy_reg_no
                    ? `Reg ${l.pharmacy_reg_no}` : ""}
                </span>
              </footer>
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
          <IconButton action="print" onClick={() => { printLabels(labels, copies); onClose(); }} />
        </div>
      </div>
    </div>
  );
}
