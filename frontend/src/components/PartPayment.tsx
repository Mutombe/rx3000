/** Take what the patient has, and record the rest as owed.
 *
 *  The commonest conversation at a Zimbabwean counter: the script comes to
 *  fifty-seven and the person in front of you has twenty. Refusing means they
 *  leave without their medicine, or the till rings it up as cash and the
 *  difference disappears somewhere nobody can find it later.
 *
 *  So the amount is asked for plainly, the balance is shown before anything is
 *  pressed, and a pharmacist puts their password to it — because the pharmacy
 *  is lending money and somebody should own that decision.
 */
import { useState } from "react";
import { money } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";

export interface PartPaymentChoice {
  amount: number;
  method: string;
  note: string;
}

export default function PartPayment({ owed, patient, onCancel, onConfirm }: {
  /** What is still due on this sale. */
  owed: number;
  /** Who will owe the balance. A debt needs somebody's name on it. */
  patient: string;
  onCancel: () => void;
  onConfirm: (choice: PartPaymentChoice) => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [note, setNote] = useState("");

  const taking = Math.max(0, Number(amount) || 0);
  const balance = Math.round((owed - taking) * 100) / 100;
  const tooMuch = taking > owed + 0.005;
  const nothing = taking <= 0.005;

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Take part of it</h2>
        <p className="muted">
          {patient} owes <b>{money(owed)}</b>. Whatever is not paid now stays
          against this sale until it is collected.
        </p>

        <label className="field">
          How much are they paying?
          <input
            type="number" min="0" step="0.01" autoFocus
            value={amount} onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
          />
          {tooMuch && (
            <span className="field-hint">
              That is more than is owed. Take {money(owed)} and settle it in full
              instead.
            </span>
          )}
        </label>

        <label className="field">
          Paid with
          <Select
            value={method} onChange={setMethod} ariaLabel="Method"
            options={[
              { value: "cash", label: "Cash" },
              { value: "card", label: "Card" },
              { value: "mobile_money", label: "Mobile money" },
            ]}
          />
        </label>

        <label className="field">
          Note (optional)
          <input
            value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. bringing the rest on Friday"
          />
          <span className="field-hint">
            Whoever chases this in a fortnight will read it.
          </span>
        </label>

        {/* Said before the button is pressed. A cashier should know exactly
            what they are creating, not find out from a receipt. */}
        {!nothing && !tooMuch && (
          <div className={`alert ${balance > 0.005 ? "warn" : "ok"}`}>
            {balance > 0.005
              ? <>Taking <b>{money(taking)}</b> now. <b>{money(balance)}</b> will
                  be owed by {patient}.</>
              : <>That settles it in full. Nothing will be owed.</>}
          </div>
        )}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <BusyButton
            disabled={nothing || tooMuch}
            onClick={() => onConfirm({ amount: taking, method, note: note.trim() })}
          >
            Take {taking > 0 ? money(taking) : "payment"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
