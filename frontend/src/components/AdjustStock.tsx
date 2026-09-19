/** Put the shelf right, from wherever you noticed it was wrong.
 *
 *  A dispenser finds out the count is wrong at the moment they reach for the
 *  box: the screen says two and the shelf has none, or the screen says none and
 *  there are three in their hand. Until now the only way to fix that was to
 *  leave the script, go to Stock, find the medicine again, correct it, and come
 *  back to a form that had forgotten what they were doing.
 *
 *  So it is asked for here, over the script, and hands the dispenser back to
 *  exactly where they were. The same idea as Proppharm's `<F12> Adjust Stock
 *  OH`, which is one key from the item they are already looking at.
 *
 *  WHAT IT ASKS FOR, AND WHY IT IS NOT JUST A NUMBER
 *
 *  Adding stock needs a batch and an expiry. Not as bureaucracy: this pharmacy
 *  dispenses First-Expiry-First-Out, so stock with no date cannot be drawn at
 *  all, and a correction that adds twenty undated units has added twenty units
 *  nobody can sell. The date is on the box in their hand at the moment they are
 *  typing this, and it will never be easier to ask for.
 *
 *  Removing stock does not, because the batch it comes off is decided by expiry
 *  order rather than by whoever is correcting the count.
 */
import { useEffect, useState } from "react";
import { ArrowRight, Warning } from "@phosphor-icons/react";

import { api, errorText } from "../api";
import type { Product } from "../types";
import BusyButton from "./BusyButton";
import { useToast } from "./Toast";
import { useCan } from "../session";

/** Why a count is being corrected. The reason is what makes an adjustment an
 *  adjustment rather than an unexplained change, and a list beats free text:
 *  these five cover what actually happens, and they can be counted later. */
const REASONS = [
  { key: "count", label: "Counted the shelf", note: "The count was wrong." },
  // Stock LEAVING the building, which is a write-off and a different
  // capability from correcting a figure. Offered only to somebody who holds
  // it: the server refuses either way, and a chip that always returns
  // "you may not" is a worse answer than a chip that is not there.
  { key: "damaged", label: "Damaged or broken", note: "", writesOff: true },
  { key: "expired", label: "Expired, taken off the shelf", note: "", writesOff: true },
  { key: "received", label: "Delivery not booked in", note: "" },
  { key: "returned", label: "Returned by a patient", note: "" },
] as const;

export default function AdjustStock({ product, onClose, onAdjusted }: {
  product: Product;
  onClose: () => void;
  /** The new figure for this branch, so the screen behind can move on without
   *  asking the server again.
   *
   *  Called TWICE: once the moment the dialog closes, with what the shelf is
   *  expected to become, and once when the server has said what it actually
   *  is. `settled` is false on the first and true on the second, so a screen
   *  that wants to re-read something heavier can wait for the second without
   *  every screen having to wait for the first. On a refusal the second call
   *  carries the figure back to what it was.
   */
  onAdjusted: (onHand: number, settled: boolean) => void;
}) {
  const here = Number(product.here ?? product.quantity_on_hand ?? 0);
  const undated = Number(product.here_undated ?? 0);

  const [mode, setMode] = useState<"set" | "add" | "remove">("set");
  const [count, setCount] = useState(String(here));
  const [batch, setBatch] = useState("");
  const [expiry, setExpiry] = useState("");
  const mayWriteOff = useCan("stock.write_off");
  const reasons = REASONS.filter((r) => mayWriteOff || !("writesOff" in r));
  const [reason, setReason] = useState<string>(REASONS[0].key);
  const [note, setNote] = useState("");
  const toast = useToast();

  useEffect(() => { setCount(mode === "set" ? String(here) : ""); }, [mode]);

  const typed = Number(count);
  const valid = count.trim() !== "" && Number.isFinite(typed) && typed >= 0;
  // What the shelf becomes, and what has to move to get there. Shown rather
  // than worked out in somebody's head: "set to 12" and "add 10" are the same
  // act from different directions and the mistake is always the direction.
  const delta = !valid ? 0
    : mode === "set" ? Math.round(typed) - here
    : mode === "add" ? Math.round(typed)
    : -Math.round(typed);
  const after = here + delta;

  const needsBatch = delta > 0;
  const past = !!expiry && expiry < new Date().toLocaleDateString("en-CA");
  const problem = !valid ? "Type a number."
    : delta === 0 ? "That is what the shelf already says."
    : after < 0 ? `This branch only holds ${here}.`
    : needsBatch && !expiry ? "Enter the expiry printed on the pack."
    : past ? "That pack has expired."
    : "";

  /** Close first, then do it.
   *
   *  A correction is one number and one reason, and the person making it is
   *  standing at the shelf holding the box. Keeping the dialog open across a
   *  round trip makes them wait on a server to be told what they already know.
   *  So it closes on the click, the shelf behind it moves at once, and the
   *  request runs where it was started. The toast is the receipt.
   *
   *  If the server refuses, the toast says so and the figure goes back: an
   *  optimistic screen that cannot put the number back is not optimistic, it
   *  is wrong.
   */
  function save() {
    if (problem) return;
    const why = REASONS.find((r) => r.key === reason);
    const body = {
      product_id: product.id,
      quantity_delta: delta,
      // The movement type the ledger files it under. A correction after a
      // count is not the same event as a write-off, and a report that cannot
      // tell them apart cannot tell shrinkage from bad counting.
      movement_type: delta > 0 ? "receive" : reason === "count" ? "adjustment" : "write_off",
      batch_number: batch.trim(),
      expiry_date: needsBatch ? expiry : null,
      reference: `ADJ ${why?.label ?? ""}`.trim().slice(0, 60),
      notes: [why?.label, note.trim()].filter(Boolean).join(". "),
    };
    const was = here;
    const expected = after;
    const name = product.name;

    onAdjusted(expected, false);
    onClose();

    void (async () => {
      try {
        const said = await api.post<{ quantity_on_hand: number }>("/api/stock/adjust", body);
        const real = Number(said?.quantity_on_hand ?? expected);
        toast.ok(`${name}: ${was} to ${real} on this shelf.`);
        onAdjusted(real, true);
      } catch (e) {
        toast.error(errorText(e, "That adjustment could not be made."));
        onAdjusted(was, true);
      }
    })();
  }

  const howMany = mode === "set" ? "The count on the shelf"
    : mode === "add" ? "How many to add" : "How many to remove";

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-label={`Adjust the stock of ${product.name}`}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal adj-modal">
        <h2>{product.name} {product.strength}</h2>
        <p className="muted adj-sub">
          This branch holds <b>{here}</b>
          {undated > 0 && <> in date, and {undated} with no expiry recorded</>}.
          Correcting it here writes a stock movement with your name on it.
        </p>

        {/* One question at a time, in the order it is answered: which way, how
            many, what the shelf becomes. It used to be three of those crammed
            onto a single row with the number hanging off the end of it. */}
        <div className="adj-how" role="radiogroup" aria-label="How to correct it">
          {([["set", "Set it to"], ["add", "Add"], ["remove", "Remove"]] as const)
            .map(([key, label]) => (
              <button key={key} type="button" role="radio" aria-checked={mode === key}
                      className={`adj-mode${mode === key ? " is-on" : ""}`}
                      onClick={() => setMode(key)}>{label}</button>
            ))}
        </div>

        <div className="adj-figure">
          <label className="adj-count-field">
            <span>{howMany}</span>
            <input className="adj-count" type="number" min={0} autoFocus
                   inputMode="numeric"
                   aria-label={howMany}
                   value={count} onChange={(e) => setCount(e.target.value)} />
          </label>

          {/* What the shelf becomes. The whole reason this is here rather than
              left in somebody's head: "set to 12" and "add 12" are the same act
              from different directions, and the mistake is always the
              direction. Cheap to notice here, expensive afterwards. */}
          <div className={`adj-becomes${valid && delta !== 0 ? " is-live" : ""}`}>
            <span className="adj-was">{here}</span>
            <ArrowRight size={15} className="adj-arrow" aria-hidden="true" />
            <span className={`adj-now${delta > 0 ? " is-up" : delta < 0 ? " is-down" : ""}`}>
              {valid ? after : here}
            </span>
            {valid && delta !== 0 && (
              <span className={`adj-delta${delta > 0 ? " is-up" : " is-down"}`}>
                {delta > 0 ? `+${delta}` : delta}
              </span>
            )}
          </div>
        </div>

        {needsBatch && (
          <div className="adj-block">
            <span className="adj-legend">The pack going on</span>
            <div className="form-row adj-pack">
              <div className="field">
                <label>Batch</label>
                <input value={batch} placeholder="off the box, optional"
                       onChange={(e) => setBatch(e.target.value)} />
              </div>
              <div className="field">
                <label>Expiry</label>
                <input type="date" value={expiry}
                       onChange={(e) => setExpiry(e.target.value)} />
              </div>
            </div>
            <span className={`hint${past ? " is-bad" : ""}`}>
              {past
                ? <><Warning size={12} weight="fill" /> That pack has expired.</>
                : <>Stock with no expiry cannot be dispensed, so this is asked
                    for while the box is in your hand.</>}
            </span>
          </div>
        )}

        {/* The label above the chips rather than beside them. Beside, it sat
            vertically centred against three ragged rows of buttons and belonged
            to none of them. */}
        <div className="adj-block">
          <span className="adj-legend">Why</span>
          <div className="adj-reasons">
            {reasons.map((r) => (
              <button key={r.key} type="button"
                      className={`adj-reason${reason === r.key ? " is-on" : ""}`}
                      aria-pressed={reason === r.key}
                      onClick={() => setReason(r.key)}>{r.label}</button>
            ))}
          </div>
        </div>

        <div className="adj-block">
          <span className="adj-legend">Note</span>
          <input value={note} placeholder="anything the reason does not cover"
                 onChange={(e) => setNote(e.target.value)} />
        </div>

        <div className="modal-actions adj-actions">
          {/* Why the button is off, said beside it. On the button itself it
              read as a control that had been renamed to an apology. */}
          {problem && <span className="adj-problem">{problem}</span>}
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" disabled={!!problem} onClick={save}
                      busyLabel="Correcting…">
            {delta > 0 ? `Add ${delta}` : delta < 0 ? `Remove ${-delta}`
              : "Correct the shelf"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
