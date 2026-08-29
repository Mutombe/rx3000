/** How a payment is actually made up, in a country that pays in pieces.
 *
 *  A Zimbabwean counter does not take "card". It takes eleven US dollars on
 *  EcoCash, forty in ZiG cash, and the rest on a Stanbic card — and the medical
 *  aid has already covered half of it. Three different questions hide inside the
 *  word "payment": which instrument, whose instrument, and in which currency.
 *
 *  This exists because that was asked properly in one place and nowhere else.
 *  The till already knew about EcoCash, Omari and InnBucks, which currencies
 *  each of them can actually settle in, and how to read a wallet off a phone
 *  number — while the part-payment modal offered "Cash / Card / Mobile money"
 *  with no currency at all, and the dispensary offered three buttons. Same
 *  transaction, three different depths of question, and two of them produced a
 *  record nobody can reconcile: "card, 40.00" says nothing about whether that
 *  was forty US dollars or forty ZiG.
 *
 *  So the question is asked once, here, and the places that need it use this
 *  rather than inventing a shallower version.
 */
import { useMemo } from "react";
import { Plus, Trash } from "@phosphor-icons/react";
import { money } from "../api";
import Select from "./Select";
import { WALLETS, walletForNumber } from "./MobileMoney";

export interface TenderLine {
  /** cash | card | mobile_money | medical_aid */
  method: string;
  currency_code: string;
  amount: string;
  /** Which wallet, for mobile money. */
  wallet?: string;
  /** The payer's number, for mobile money. */
  phone?: string;
  /** Which card scheme or bank. */
  scheme?: string;
  /** Last four digits from the slip, so a card sale can be reconciled. */
  last4?: string;
  /** Authorisation code from the terminal. */
  auth?: string;
  /** The scheme's own reference, for a medical aid line. */
  reference?: string;
  /** Hold this claim rather than sending it now. */
  claimLater?: boolean;
  /** Why it is being held — read by whoever sends it later. */
  claimLaterReason?: string;
}

/** The card schemes and banks a Zimbabwean pharmacy actually sees on a slip.
 *
 *  "Card" on its own cannot be reconciled: the settlement comes from a bank, on
 *  that bank's own timetable, and a drawer that says only "card 40.00" cannot be
 *  matched to any of them.
 */
export const CARD_SCHEMES = [
  "Visa", "Mastercard", "ZimSwitch",
  "CBZ", "Stanbic", "Steward", "FBC", "NMB", "ZB", "Ecobank", "First Capital",
];

/** The currency world, read off whatever /api/currency returned.
 *
 *  Derived in one place because three screens need the same two things — which
 *  codes may be offered, and what each is worth — and each of them deriving it
 *  separately is how one ends up offering a currency it cannot convert.
 */
export function currencyWorld(state: any): {
  base: string; currencies: string[]; rates: Record<string, number>;
} {
  const base = state?.base ?? "USD";
  const list: any[] = state?.currencies ?? [];
  const rates: Record<string, number> = {};
  for (const c of list) {
    if (c?.code) rates[c.code] = c.is_base ? 1 : Number(c.rate) || 0;
  }
  return {
    base,
    currencies: list.map((c) => c.code).filter(Boolean).length
      ? list.map((c) => c.code).filter(Boolean)
      : [base],
    rates: Object.keys(rates).length ? rates : { [base]: 1 },
  };
}


export function blankLine(currency: string): TenderLine {
  return { method: "cash", currency_code: currency, amount: "" };
}

/** What a line is worth in the pharmacy's base currency. */
export function inBase(line: TenderLine, rates: Record<string, number>, base: string): number {
  const n = Number(line.amount) || 0;
  if (!n) return 0;
  const code = (line.currency_code || base).toUpperCase();
  if (code === base.toUpperCase()) return n;
  const rate = rates[code];
  // No rate on file means the figure cannot be converted, and guessing one
  // would quietly understate or overstate what was taken. Nought is wrong too,
  // but it is visibly wrong — the total will not add up and somebody looks.
  return rate ? n / rate : 0;
}

export default function Tenders({
  lines, onChange, owed, currencies, base, rates, allowAid = true, aidCovers = 0,
}: {
  lines: TenderLine[];
  onChange: (lines: TenderLine[]) => void;
  /** What is being settled, in base currency. */
  owed: number;
  currencies: string[];
  base: string;
  /** Units of each currency per one of the base. */
  rates: Record<string, number>;
  /** Whether a medical aid line makes sense here. */
  allowAid?: boolean;
  /** What the scheme has already agreed to carry, if anything. */
  aidCovers?: number;
}) {
  const taken = useMemo(
    () => lines.reduce((n, l) => n + inBase(l, rates, base), 0),
    [lines, rates, base]);
  const balance = Math.round((owed - taken) * 100) / 100;

  function set(i: number, patch: Partial<TenderLine>) {
    onChange(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  }

  const METHODS = [
    { value: "cash", label: "Cash" },
    { value: "card", label: "Card" },
    { value: "mobile_money", label: "Mobile money" },
    ...(allowAid ? [{ value: "medical_aid", label: "Medical aid" }] : []),
  ];

  return (
    <div className="tenders">
      {lines.map((line, i) => {
        const wallet = WALLETS.find((w) => w.id === line.wallet);
        // A wallet can only settle in what it actually supports — offering ZiG
        // on InnBucks produces a payment the customer cannot make.
        const codes = line.method === "mobile_money" && wallet
          ? wallet.currencies
          : currencies;
        const suggested = line.method === "mobile_money"
          ? walletForNumber(line.phone || "")
          : null;

        return (
          <div className="tender-line" key={i}>
            <div className="tender-row">
              <Select
                value={line.method}
                onChange={(v) => set(i, {
                  method: v,
                  // A method change invalidates what belonged to the old one.
                  wallet: undefined, phone: undefined, scheme: undefined,
                  last4: undefined, auth: undefined,
                  currency_code: v === "medical_aid" ? base : line.currency_code,
                })}
                options={METHODS}
                ariaLabel="How it was paid"
              />
              <Select
                value={line.currency_code}
                onChange={(v) => set(i, { currency_code: v })}
                options={codes.map((c) => ({ value: c, label: c }))}
                ariaLabel="Currency"
                disabled={line.method === "medical_aid"}
              />
              <input
                type="number" min="0" step="0.01" className="tender-amount"
                value={line.amount}
                onChange={(e) => set(i, { amount: e.target.value })}
                placeholder="0.00"
                aria-label="Amount"
              />
              {lines.length > 1 && (
                <button
                  className="btn ghost small" aria-label="Remove this payment"
                  onClick={() => onChange(lines.filter((_, n) => n !== i))}
                >
                  <Trash size={14} />
                </button>
              )}
            </div>

            {/* What the instrument needs before it can be reconciled later. */}
            {line.method === "mobile_money" && (
              <div className="tender-row tender-detail">
                <Select
                  value={line.wallet ?? ""}
                  onChange={(v) => {
                    const w = WALLETS.find((x) => x.id === v);
                    set(i, {
                      wallet: v,
                      currency_code: w && !w.currencies.includes(line.currency_code)
                        ? w.currencies[0] : line.currency_code,
                    });
                  }}
                  options={[{ value: "", label: "Which wallet?" },
                            ...WALLETS.map((w) => ({ value: w.id, label: w.name,
                                                     hint: w.network }))]}
                  ariaLabel="Wallet"
                />
                <input
                  value={line.phone ?? ""}
                  onChange={(e) => set(i, { phone: e.target.value })}
                  placeholder="Paying from (07…)"
                  aria-label="Wallet number"
                />
                {suggested && suggested.id !== line.wallet && (
                  <button className="btn ghost small"
                          onClick={() => set(i, { wallet: suggested.id })}>
                    {/* Offered, never forced: dual-SIM is ordinary here and a
                        number's prefix is a hint, not a fact. */}
                    That is {suggested.name}?
                  </button>
                )}
              </div>
            )}

            {line.method === "card" && (
              <div className="tender-row tender-detail">
                <Select
                  value={line.scheme ?? ""}
                  onChange={(v) => set(i, { scheme: v })}
                  options={[{ value: "", label: "Which card or bank?" },
                            ...CARD_SCHEMES.map((c) => ({ value: c, label: c }))]}
                  ariaLabel="Card scheme"
                />
                <input
                  value={line.last4 ?? ""} maxLength={4}
                  onChange={(e) => set(i, { last4: e.target.value.replace(/\D/g, "") })}
                  placeholder="Last 4"
                  aria-label="Last four digits"
                />
                <input
                  value={line.auth ?? ""}
                  onChange={(e) => set(i, { auth: e.target.value })}
                  placeholder="Auth code from the slip"
                  aria-label="Authorisation code"
                />
              </div>
            )}

            {line.method === "medical_aid" && (
              <>
                <div className="tender-row tender-detail">
                  <input
                    value={line.reference ?? ""}
                    onChange={(e) => set(i, { reference: e.target.value })}
                    placeholder="Scheme reference, if they gave one"
                    aria-label="Scheme reference"
                  />
                  <span className="muted small">
                    {aidCovers > 0.005
                      ? <>The claim covers <b>{money(aidCovers)}</b> of this.</>
                      : "Recorded against the claim rather than the drawer."}
                  </span>
                </div>
                {/* The switch goes down, and the medicine still has to go out.
                    Holding the claim is the only answer that neither turns the
                    patient away nor loses the money — and the server has done
                    it all along with nothing on any screen to ask for it. */}
                <div className="tender-row tender-detail">
                  <label className="cbx">
                    <input
                      type="checkbox"
                      checked={!!line.claimLater}
                      onChange={(e) => set(i, { claimLater: e.target.checked })}
                    />
                    <span>Hold this claim — do not send it now</span>
                  </label>
                  {line.claimLater && (
                    <input
                      value={line.claimLaterReason ?? ""}
                      onChange={(e) => set(i, { claimLaterReason: e.target.value })}
                      placeholder="Why — the switch is down, no card, …"
                      aria-label="Why the claim is held"
                    />
                  )}
                </div>
                {line.claimLater && (
                  <div className="muted small tender-conv">
                    It will wait in <b>Claims held</b> until somebody sends it.
                    The patient settles now and is refunded when the funder pays.
                  </div>
                )}
              </>
            )}

            {/* Anything not in the base currency is shown converted, because
                the balance below is in base and two numbers that cannot be
                compared are how a cashier takes the wrong amount. */}
            {line.currency_code !== base && Number(line.amount) > 0 && (
              <div className="muted small tender-conv">
                {line.currency_code} {Number(line.amount).toFixed(2)}
                {rates[line.currency_code]
                  ? <> = {money(inBase(line, rates, base))}</>
                  : <> — no rate on file for {line.currency_code}, so this cannot
                      be converted. Record the rate before taking it.</>}
              </div>
            )}
          </div>
        );
      })}

      <button className="btn ghost small"
              onClick={() => onChange([...lines, blankLine(base)])}>
        <Plus size={13} /> Another payment
      </button>

      <div className={`tender-total ${balance > 0.005 ? "short" : balance < -0.005 ? "over" : "exact"}`}>
        <span>Taking <b>{money(taken)}</b> of {money(owed)}</span>
        {balance > 0.005 && <span><b>{money(balance)}</b> still owing</span>}
        {balance < -0.005 && <span><b>{money(-balance)}</b> change</span>}
        {Math.abs(balance) <= 0.005 && <span>settles it exactly</span>}
      </div>
    </div>
  );
}
