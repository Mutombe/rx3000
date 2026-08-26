/** Taking a mobile wallet payment at the till.
 *
 *  Built around what actually happens at a counter in Zimbabwe. The customer
 *  says "EcoCash" and holds up a phone; the cashier has one hand on the keyboard
 *  and a queue behind. So:
 *
 *    - **EcoCash is preselected**, because it is most of the traffic. The common
 *      payment is a phone number and nothing else.
 *    - **Only currencies the wallet can actually take are offered.** InnBucks
 *      settles in USD; offering ZiG there produces a decline at the worst
 *      possible moment, with the customer watching.
 *    - **The number is checked against the network, gently.** 077 and 078 are
 *      Econet, 071 is NetOne, 073 is Telecel. Typing a NetOne number with
 *      EcoCash selected is nearly always a slip, so it is said out loud and the
 *      right wallet is offered as one click. It is never enforced: dual-SIM and
 *      ported numbers exist, and a till that refuses a valid payment is worse
 *      than one that asks.
 *    - **The amount is shown in the currency being charged**, converted at
 *      today's rate, because the cashier reads it back to the customer before
 *      sending the prompt.
 */
import { useEffect, useMemo } from "react";

export interface Wallet {
  id: string;
  name: string;
  /** Currencies this wallet settles in, most common first. */
  currencies: string[];
  /** Mobile prefixes normally on this wallet's network. */
  prefixes: string[];
  network: string;
}

export const WALLETS: Wallet[] = [
  { id: "ecocash", name: "EcoCash", currencies: ["USD", "ZWG"], prefixes: ["077", "078"], network: "Econet" },
  { id: "omari", name: "Omari", currencies: ["ZWG", "USD"], prefixes: ["071"], network: "NetOne" },
  { id: "innbucks", name: "InnBucks", currencies: ["USD"], prefixes: [], network: "any network" },
];

/** Which wallet a number suggests, by prefix. Null when it says nothing. */
export function walletForNumber(phone: string): Wallet | null {
  const digits = (phone || "").replace(/\D/g, "");
  const local = digits.startsWith("263") ? `0${digits.slice(3)}` : digits;
  if (local.length < 3) return null;
  const prefix = local.slice(0, 3);
  return WALLETS.find((w) => w.prefixes.includes(prefix)) ?? null;
}

export default function MobileMoney({
  wallet, onWallet, currency, onCurrency, phone, onPhone, amountDue, rates, base,
  agentReady, reference, onReference,
}: {
  wallet: string;
  onWallet: (id: string) => void;
  currency: string;
  onCurrency: (code: string) => void;
  phone: string;
  onPhone: (value: string) => void;
  /** What is owed, in the pharmacy's base currency. */
  amountDue: number;
  /** code to units-per-base, for showing the charge in the chosen currency. */
  rates: Record<string, number>;
  base: string;
  /** Whether the device agent can push a prompt to the handset. */
  agentReady?: boolean;
  /** The confirmation code, when the payment is taken by hand. */
  reference?: string;
  onReference?: (value: string) => void;
}) {
  const chosen = WALLETS.find((w) => w.id === wallet) ?? WALLETS[0];
  const suggested = useMemo(() => walletForNumber(phone), [phone]);
  const mismatch = suggested && suggested.id !== chosen.id;

  // A wallet that cannot take the selected currency would decline at the till,
  // so the selection follows the wallet rather than waiting to be corrected.
  useEffect(() => {
    if (!chosen.currencies.includes(currency)) onCurrency(chosen.currencies[0]);
  }, [chosen, currency, onCurrency]);

  const rate = currency === base ? 1 : rates[currency];
  const charge = rate ? amountDue * rate : null;

  return (
    <div className="mm">
      <div className="mm-wallets" role="radiogroup" aria-label="Mobile wallet">
        {WALLETS.map((w) => (
          <button
            key={w.id}
            type="button"
            role="radio"
            aria-checked={w.id === chosen.id}
            className={`mm-wallet${w.id === chosen.id ? " is-on" : ""}`}
            onClick={() => onWallet(w.id)}
          >
            <b>{w.name}</b>
            <span>{w.currencies.join(" · ")}</span>
          </button>
        ))}
      </div>

      <div className="mm-row">
        <label className="mm-field">
          <span>Customer mobile number</span>
          <input
            value={phone}
            onChange={(e) => onPhone(e.target.value)}
            placeholder="077…"
            inputMode="tel"
            autoComplete="off"
          />
        </label>

        {/* Only ever the currencies this wallet settles in. */}
        <div className="mm-field">
          <span>Charge in</span>
          <div className="mm-currencies" role="radiogroup" aria-label="Currency">
            {chosen.currencies.map((code) => (
              <button
                key={code}
                type="button"
                role="radio"
                aria-checked={code === currency}
                className={`mm-cur${code === currency ? " is-on" : ""}`}
                onClick={() => onCurrency(code)}
              >
                {code}
              </button>
            ))}
          </div>
        </div>
      </div>

      {mismatch && (
        // Said, not enforced. Dual-SIM and ported numbers are ordinary.
        <p className="mm-hint">
          That number looks like {suggested!.network}.{" "}
          <button type="button" className="ghost small" onClick={() => onWallet(suggested!.id)}>
            Use {suggested!.name} instead
          </button>
        </p>
      )}

      <p className="mm-charge">
        {charge === null ? (
          <span className="mm-norate">
            No rate published for {currency} today, so the charge cannot be worked out.
            Take another currency or publish a rate first.
          </span>
        ) : (
          <>
            Charging <b>{currency} {charge.toFixed(2)}</b>
            {currency !== base && <span className="muted"> ({base} {amountDue.toFixed(2)} at today's rate)</span>}
            {" "}to {chosen.name}.
          </>
        )}
      </p>

      {agentReady ? (
        <p className="mm-note">
          A prompt goes to the customer's phone when you complete the sale.
          Nothing is charged until they approve it on the handset.
        </p>
      ) : (
        <>
          <label className="mm-field">
            <span>Confirmation code from the customer</span>
            <input
              value={reference ?? ""}
              onChange={(e) => onReference?.(e.target.value.toUpperCase())}
              placeholder="e.g. MP240826.1432.A12345"
              autoComplete="off"
            />
          </label>
          <p className="mm-note">
            {/* The honest version of taking a wallet payment without an
                integration. Recording the code is what makes the takings
                reconcilable at cash-up; a sale rung up as cash because the
                option was hidden is a hole nobody can close later. */}
            No payment device is connected, so take the payment as usual and
            enter the code the customer reads back. It is kept with the sale for
            cash-up.
          </p>
        </>
      )}
    </div>
  );
}
