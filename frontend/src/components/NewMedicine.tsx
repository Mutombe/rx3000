/** A medicine added at the counter, mid script.
 *
 *  The same gap the patient form closes, on the other search box. A dispenser
 *  holding a script for something the catalogue has never heard of had to
 *  leave the dispensary for the stock screens, create the line, book in what
 *  arrived, walk back, and start the script again with an empty basket. What
 *  actually happens instead is that the medicine goes out on a handwritten
 *  note and somebody enters it later, or nobody does.
 *
 *  So it is created here, booked in here, and lands on the script that is
 *  already open.
 *
 *  WHAT IT ASKS FOR, AND WHAT IT DOES NOT
 *
 *  Only `name` is required by the catalogue, and a form that asked for
 *  everything would be one nobody finishes with a patient waiting. So this
 *  asks for the six things that change what happens next: what it is called,
 *  its strength and form, its classification, what it costs, and how many
 *  arrived. Everything else has a sane default and can be filled in later from
 *  the product page, which is where a full record belongs.
 *
 *  The classification is the one field that is not optional in practice. It
 *  decides the letter on the label, whether the controlled register takes an
 *  entry, and whether the medicine may be handed over at all, so it is asked
 *  for plainly rather than defaulted to the least restrictive answer.
 *
 *  OPENING STOCK IS A RECEIPT, NOT A NUMBER
 *
 *  Typing a quantity onto a new product row would put stock on the shelf that
 *  no movement explains. It goes in as a receipt, through the same endpoint
 *  the stock screens use, so the ledger balances and the batch carries its
 *  expiry.
 */
import { FormEvent, useEffect, useRef, useState } from "react";

import { api, errorText } from "../api";
import { Product } from "../types";
import { useToast } from "./Toast";
import Select from "./Select";

/** The classifications a dispenser picks from, in the words on the label.
 *
 *  Taken from the jurisdiction the pharmacy trades under rather than written
 *  out here, so a South African shop is never shown Zimbabwean letters. */
const SCHEDULES = [
  { value: "0", label: "Unscheduled, general sale" },
  { value: "1", label: "Pharmacy medicine" },
  { value: "2", label: "Pharmacist supervision" },
  { value: "3", label: "Prescription only" },
  { value: "4", label: "Prescription only, restricted" },
  { value: "5", label: "Controlled, register entry" },
  { value: "6", label: "Controlled, strictest" },
];

const FORMS = ["Tablet", "Capsule", "Syrup", "Suspension", "Injection",
               "Cream", "Ointment", "Drops", "Inhaler", "Suppository"];

export interface MedicineDraft {
  name: string; strength: string; dosage_form: string; schedule: string;
  pack_size: string; units_per_pack: number; unit_price: number;
  cost_price: number; quantity: string; batch: string; expiry: string;
}

export default function NewMedicine({ draft, onClose, onAdded, onRefused }: {
  /** What was typed into the search, or the draft handed back after a refusal,
   *  so nobody types a record twice. */
  draft: MedicineDraft;
  onClose: () => void;
  /** The product as the catalogue now holds it, ready for the script. */
  onAdded: (product: Product) => void;
  /** The server would not have it. The dialog has already closed, so the draft
   *  goes back to whoever opened it rather than being lost: the whole argument
   *  against closing early is retyping eight fields, and handing the typing
   *  back answers it without making anybody wait. */
  onRefused: (draft: MedicineDraft) => void;
}) {
  const toast = useToast();
  const first = useRef<HTMLInputElement | null>(null);

  const [form, setForm] = useState({
    name: draft.name.trim(),
    strength: draft.strength,
    dosage_form: draft.dosage_form,
    schedule: draft.schedule,
    pack_size: draft.pack_size,
    units_per_pack: draft.units_per_pack,
    unit_price: draft.unit_price,
    cost_price: draft.cost_price,
  });
  const [quantity, setQuantity] = useState(draft.quantity);
  const [batch, setBatch] = useState(draft.batch);
  const [expiry, setExpiry] = useState(draft.expiry);
  const [busy, setBusy] = useState(false);

  useEffect(() => { first.current?.focus(); first.current?.select(); }, []);

  const set = (k: string) => (e: any) =>
    setForm({ ...form, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

  const count = Number(quantity);
  const booking = quantity.trim() !== "" && Number.isFinite(count) && count > 0;
  const past = !!expiry && expiry < new Date().toLocaleDateString("en-CA");

  const problem =
    !form.name.trim() ? "Give it a name."
      : form.unit_price <= 0 ? "Give it a selling price."
        : booking && !expiry ? "Enter the expiry printed on the pack."
          : past ? "That pack has expired."
            : "";

  /** Close first, then create it.
   *
   *  Same rule as every other dialog here: the dispenser has a patient in
   *  front of them and has already told us everything we need. Holding the
   *  screen while a round trip finishes makes them wait to be told what they
   *  just typed.
   *
   *  The one thing that cannot be optimistic is the line on the script. A
   *  script line points at a product id and there is no id until the
   *  catalogue has written one, so the medicine joins the basket the moment it
   *  comes back rather than the moment the button is pressed. The screen is
   *  theirs again either way, and the toast is the receipt.
   */
  function save(e: FormEvent) {
    e.preventDefault();
    if (problem || busy) return;

    const body = {
      ...form,
      schedule: Number(form.schedule),
      units_per_pack: Math.max(1, Number(form.units_per_pack) || 1),
      category: "medicine",
      quantity_on_hand: 0,
    };
    const opening = booking ? Math.round(count) : 0;
    const pack = { batch: batch.trim(), expiry };
    const called = form.name.trim();
    const typed: MedicineDraft = { ...form, quantity, batch, expiry };

    setBusy(true);
    onClose();

    void (async () => {
      try {
        const made = await api.post<Product>("/api/products", body);

        // Opening stock as a receipt, so the shelf and the ledger agree. A
        // failure here must not lose the medicine that was just created: the
        // catalogue line is the hard part and it is already saved.
        let onShelf = 0;
        if (opening > 0) {
          try {
            await api.post("/api/stock/adjust", {
              product_id: made.id,
              quantity_delta: opening,
              movement_type: "receive",
              batch_number: pack.batch,
              expiry_date: pack.expiry || null,
              reference: "Booked in at the counter",
              notes: "Added while dispensing, with the pack in hand.",
            });
            onShelf = opening;
          } catch {
            toast.warn(`${made.name} was added, but the ${opening} could not be `
                       + "booked in. Correct the count from the product page.");
          }
        }

        toast.ok(onShelf
          ? `${made.name} added, ${onShelf} on the shelf.`
          : `${made.name} added to the catalogue.`);
        onAdded({ ...made, quantity_on_hand: onShelf } as Product);
      } catch (err) {
        toast.error(errorText(err, `${called} could not be added.`));
        onRefused(typed);       // with everything that was typed still in it
      }
    })();
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-label="Add a medicine"
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form className="modal modal-wide patient-form med-form" onSubmit={save}
            onClick={(e) => e.stopPropagation()}>
        <h2>New medicine</h2>
        <p className="muted med-sub">
          Enough to dispense it today. The rest of the record can be filled in
          from the product page afterwards.
        </p>

        <div className="form-row">
          <div className="field span-6">
            <label>Name</label>
            <input ref={first} value={form.name} onChange={set("name")}
                   placeholder="As it reads on the box" />
          </div>
          <div className="field span-3">
            <label>Strength</label>
            <input value={form.strength} onChange={set("strength")}
                   placeholder="500mg" />
          </div>
          <div className="field span-3">
            <label>Form</label>
            <Select value={form.dosage_form}
                    onChange={(v) => setForm({ ...form, dosage_form: String(v) })}
                    options={FORMS.map((f) => ({ value: f, label: f }))} />
          </div>
        </div>

        <div className="form-row">
          <div className="field span-6">
            {/* The letter on the label, the register entry, and whether it may
                be handed over at all. Not defaulted quietly. */}
            <label>Classification</label>
            <Select value={form.schedule}
                    onChange={(v) => setForm({ ...form, schedule: String(v) })}
                    options={SCHEDULES} />
          </div>
          <div className="field span-3">
            <label>Selling price, each</label>
            <input type="number" step="0.01" min={0}
                   value={form.unit_price} onChange={set("unit_price")} />
          </div>
          <div className="field span-3">
            <label>Cost, each</label>
            <input type="number" step="0.01" min={0}
                   value={form.cost_price} onChange={set("cost_price")} />
          </div>
        </div>

        <h3 className="med-legend">What arrived</h3>
        <p className="muted small med-sub">
          Optional. Left empty the medicine is added to the catalogue with
          nothing on the shelf, which is right for something you are ordering
          rather than holding.
        </p>
        <div className="form-row">
          <div className="field span-3">
            <label>How many</label>
            <input type="number" min={0} value={quantity} inputMode="numeric"
                   onChange={(e) => setQuantity(e.target.value)}
                   placeholder="0" />
          </div>
          <div className="field span-3">
            <label>Units per pack</label>
            <input type="number" min={1} value={form.units_per_pack}
                   onChange={set("units_per_pack")} />
          </div>
          <div className="field span-3">
            <label>Batch</label>
            <input value={batch} onChange={(e) => setBatch(e.target.value)}
                   placeholder="off the box, optional" />
          </div>
          <div className="field span-3">
            <label>Expiry</label>
            <input type="date" value={expiry}
                   onChange={(e) => setExpiry(e.target.value)} />
          </div>
        </div>

        <div className="modal-actions adj-actions">
          {problem && <span className="adj-problem">{problem}</span>}
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary"
                  disabled={!!problem || busy}>
            {busy ? "Adding…"
              : booking ? `Add and book in ${Math.round(count) || 0}`
                : "Add medicine"}
          </button>
        </div>
      </form>
    </div>
  );
}
