/** Confirm how a waiting sale is actually being settled.
 *
 *  The awaiting-payment list had three buttons — Cash, Card, Mobile — that
 *  settled the invoice the moment they were pressed. Fast, and unreconcilable:
 *  "cash" does not say USD or ZiG, "mobile" does not say EcoCash or Omari, and
 *  a drawer counted at five o'clock cannot be matched to a day of sales that
 *  each recorded one word.
 *
 *  So this is one step, not a form. It opens with the method already chosen and
 *  the amount already filled to what is owed, which means the common case is
 *  still a single press — the question is only asked where the answer cannot be
 *  guessed: which currency, which wallet, which bank.
 *
 *  It reuses the same tender rows as the till and the dispensary rather than
 *  asking a fourth, shallower version of the same question. Change is worked
 *  out and shown, because handing back the wrong change is the error a till
 *  makes most often.
 */
import { useMemo, useState } from "react";
import { money } from "../api";
import BusyButton from "./BusyButton";
import InsuranceStanding from "./InsuranceStanding";
import Tenders, { TenderLine, blankLine, inBase } from "./Tenders";

export interface SettleChoice {
  tenders: { method: string; currency_code: string; amount: number; reference: string }[];
  /** What was taken, in base currency. */
  taken: number;
  change: number;
}

const TITLE: Record<string, string> = {
  cash: "Take cash",
  card: "Take a card payment",
  mobile_money: "Take a mobile payment",
};

export default function SettleSale({
  sale, owed, method, patientId, currencies, base, rates, aidCovers = 0,
  onCancel, onConfirm,
}: {
  /** The invoice number, so the person can see they are settling the right one. */
  sale: string;
  owed: number;
  /** Which button was pressed. Pre-selected, still changeable. */
  method: string;
  patientId?: number | null;
  currencies: string[];
  base: string;
  rates: Record<string, number>;
  aidCovers?: number;
  onCancel: () => void;
  onConfirm: (choice: SettleChoice) => Promise<void>;
}) {
  // Pre-filled to what is owed, in the base currency, with the method already
  // chosen. Everything the cashier would have typed to reach the old
  // behaviour, so pressing Confirm is the same one press it used to be.
  const [lines, setLines] = useState<TenderLine[]>([
    { ...blankLine(base), method, amount: owed ? owed.toFixed(2) : "" },
  ]);

  const taken = useMemo(
    () => Math.round(lines.reduce((n, l) => n + inBase(l, rates, base), 0) * 100) / 100,
    [lines, rates, base]);
  const change = Math.round((taken - owed) * 100) / 100;
  const short = Math.round((owed - taken) * 100) / 100;

  // The same rule the rest of the product uses: a line nobody can match to a
  // statement is a line somebody has to chase.
  const incomplete = lines.find((l) =>
    Number(l.amount) > 0 && (
      (l.method === "mobile_money" && !l.wallet) ||
      (l.method === "card" && !l.scheme) ||
      (l.currency_code !== base && !rates[l.currency_code])
    ));

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>{TITLE[method] ?? "Take payment"}</h2>
        <p className="muted">
          <span className="mono">{sale}</span> · <b>{money(owed)}</b> to collect
          {aidCovers > 0.005 && (
            <> · {money(aidCovers)} is on the scheme</>
          )}
        </p>

        {/* The cashier is the last person who can decline to extend credit. */}
        <InsuranceStanding patientId={patientId ?? null} compact />

        <Tenders
          lines={lines}
          onChange={setLines}
          owed={owed}
          currencies={currencies}
          base={base}
          rates={rates}
          allowAid={false}
          aidCovers={aidCovers}
        />

        {incomplete && (
          <div className="alert warn">
            {incomplete.method === "mobile_money"
              ? "Say which wallet it came from — a drawer that says only “mobile money” cannot be matched to EcoCash, Omari or InnBucks at cash-up."
              : incomplete.method === "card"
                ? "Say which card or bank. The settlement arrives from one of them, on their own timetable."
                : `There is no exchange rate on file for ${incomplete.currency_code}, so this cannot be converted.`}
          </div>
        )}

        {/* Change, worked out and stated. Handing back the wrong change is the
            error a till makes most often, and it is the one a screen can
            simply prevent. */}
        {change > 0.005 && (
          <div className="alert ok">
            Give <b>{money(change)}</b> change.
          </div>
        )}
        {short > 0.005 && taken > 0.005 && (
          <div className="alert warn">
            That is <b>{money(short)}</b> short of what is owed. Use
            &ldquo;Part&rdquo; if they are paying some of it now.
          </div>
        )}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <BusyButton
            className="btn primary"
            disabled={taken <= 0.005 || short > 0.005 || !!incomplete}
            busyLabel="Taking…"
            onClick={() => onConfirm({
              taken,
              change: Math.max(0, change),
              tenders: lines
                .filter((l) => Number(l.amount) > 0)
                .map((l) => ({
                  method: l.method,
                  currency_code: l.currency_code || base,
                  amount: Number(l.amount),
                  reference: [l.wallet, l.phone, l.scheme,
                              l.last4 && `••${l.last4}`, l.auth]
                    .filter(Boolean).join(" "),
                })),
            })}
          >
            Take {money(taken || owed)}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
