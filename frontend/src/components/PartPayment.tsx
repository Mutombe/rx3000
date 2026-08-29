/** Take what the patient has, and record the rest as owed.
 *
 *  The commonest conversation at a Zimbabwean counter: the script comes to
 *  fifty-seven and the person in front of you has twenty. Refusing means they
 *  leave without their medicine, or the till rings it up as cash and the
 *  difference disappears somewhere nobody can find it later.
 *
 *  What they have is rarely one thing. It is eleven dollars on EcoCash and a
 *  handful of ZiG, or a card for part and cash for the rest, with the medical
 *  aid already carrying half. This asked for a single amount and a choice of
 *  three words — "Cash / Card / Mobile money", no currency, no wallet, no bank —
 *  which is not how anybody pays here, and produced a record that could not be
 *  reconciled: "card 40.00" does not say forty of what, on whose card.
 *
 *  The tender rows are the shared component the till already uses, so the same
 *  question is asked the same way wherever money is taken.
 */
import { useState } from "react";
import { money } from "../api";
import BusyButton from "./BusyButton";
import Tenders, { TenderLine, blankLine, inBase } from "./Tenders";

export interface PartPaymentChoice {
  /** What was taken, in base currency. */
  amount: number;
  /** Kept for callers that only care about the headline instrument. */
  method: string;
  note: string;
  /** Every payment that made it up, for the server to record individually. */
  tenders: {
    method: string; currency_code: string; amount: number; reference: string;
  }[];
}

export default function PartPayment({
  owed, patient, onCancel, onConfirm, currencies, base, rates, aidCovers = 0,
}: {
  /** What is still due on this sale. */
  owed: number;
  /** Who will owe the balance. A debt needs somebody's name on it. */
  patient: string;
  onCancel: () => void;
  onConfirm: (choice: PartPaymentChoice) => Promise<void>;
  currencies: string[];
  base: string;
  rates: Record<string, number>;
  /** What the scheme is already carrying on this sale. */
  aidCovers?: number;
}) {
  const [lines, setLines] = useState<TenderLine[]>([blankLine(base)]);
  const [note, setNote] = useState("");

  const taking = Math.round(
    lines.reduce((n, l) => n + inBase(l, rates, base), 0) * 100) / 100;
  const balance = Math.round((owed - taking) * 100) / 100;
  const tooMuch = taking > owed + 0.005;
  const nothing = taking <= 0.005;

  // A line that cannot be reconciled later is a line somebody has to chase.
  // Blocked here rather than discovered at cash-up.
  const incomplete = lines.find((l) =>
    Number(l.amount) > 0 && (
      (l.method === "mobile_money" && !l.wallet) ||
      (l.method === "card" && !l.scheme) ||
      (l.currency_code !== base && !rates[l.currency_code])
    ));

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Take part of it</h2>
        <p className="muted">
          {patient} owes <b>{money(owed)}</b>. Whatever is not paid now stays
          against this sale until it is collected.
        </p>

        <Tenders
          lines={lines}
          onChange={setLines}
          owed={owed}
          currencies={currencies}
          base={base}
          rates={rates}
          aidCovers={aidCovers}
        />

        {tooMuch && (
          <div className="alert warn">
            That is more than is owed. Take {money(owed)} and settle it in full
            instead.
          </div>
        )}

        {incomplete && (
          <div className="alert warn">
            {incomplete.method === "mobile_money"
              ? "Say which wallet the mobile money came from — a drawer that says only “mobile money” cannot be matched to EcoCash, Omari or InnBucks at cash-up."
              : incomplete.method === "card"
                ? "Say which card or bank. The settlement arrives from one of them, on their own timetable, and “card” matches none of it."
                : `There is no exchange rate on file for ${incomplete.currency_code}, so this cannot be converted. Record today’s rate first.`}
          </div>
        )}

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
            disabled={nothing || tooMuch || !!incomplete}
            onClick={() => onConfirm({
              amount: taking,
              method: lines.length === 1 ? lines[0].method : "split",
              note: note.trim(),
              tenders: lines
                .filter((l) => Number(l.amount) > 0)
                .map((l) => ({
                  method: l.method,
                  currency_code: l.currency_code || base,
                  amount: Number(l.amount),
                  // Everything needed to match this against a statement later:
                  // the wallet and number, or the bank and the last four.
                  reference: [l.wallet, l.phone, l.scheme, l.last4 && `••${l.last4}`,
                              l.auth, l.reference]
                    .filter(Boolean).join(" "),
                })),
            })}
          >
            Take {taking > 0 ? money(taking) : "payment"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
