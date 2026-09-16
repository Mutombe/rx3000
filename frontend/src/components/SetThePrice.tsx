/** Changing what a medicine costs, by price or by margin, once or for good.
 *
 *  Catalogue prices arrive from a supplier file and are wrong often enough that
 *  a dispenser has to be able to change one. Two things about that were missing
 *  and both are the same mistake — assuming the person knows the shape of the
 *  answer the software wants:
 *
 *  **They are often thinking in margin, not in price.** "This is loaded at 12%
 *  and it should be 40%" is the actual sentence, and making somebody work out
 *  what 40% of cost is, on a calculator, at a counter, is how a shop ends up
 *  with a drawer full of hand-written prices. Margin and price are the same
 *  number read two ways, so both are typed here and each moves the other.
 *
 *  **"Just this one" and "from now on" are different decisions.** A margin
 *  loaded wrong on import is wrong on every script until the shelf is fixed; a
 *  price rounded off for the person at the counter is nobody else's business.
 *  Only the dispenser knows which they are doing, so they are asked — and it is
 *  one checkbox, not a second dialog.
 */
import { useEffect, useMemo, useState } from "react";
import { Tag, Warning } from "@phosphor-icons/react";
import { money } from "../api";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";

export interface PriceAsked {
  /** Per unit, what the line will charge. */
  each: number;
  /** Also write it to the catalogue, for every script after this one. */
  keep: boolean;
  reason: string;
}

/** Margin on the selling price, the way the rest of this system reads it. */
function marginOf(each: number, cost: number): number | null {
  if (!each) return null;
  return Math.round(((each - cost) / each) * 1000) / 10;
}

/** The price that yields this margin. Inverse of the above, so typing 40 into
 *  the margin box and reading the price back gives 40 again. */
function priceFor(margin: number, cost: number): number | null {
  if (margin >= 100) return null;          // no price divides to 100% margin
  return cost / (1 - margin / 100);
}

export default function SetThePrice({
  name, strength, quantity, shelf, cost, current, busy, onCancel, onSet,
}: {
  name: string;
  strength?: string;
  quantity: number;
  /** What the catalogue says, per unit. */
  shelf: number;
  /** What it cost to buy, per unit. */
  cost: number;
  /** What the line charges now, per unit — the shelf, or an earlier override. */
  current: number;
  busy?: boolean;
  onCancel: () => void;
  onSet: (asked: PriceAsked) => void;
}) {
  const [each, setEach] = useState(current.toFixed(2));
  const [margin, setMargin] = useState(String(marginOf(current, cost) ?? ""));
  const [keep, setKeep] = useState(false);
  const [reason, setReason] = useState("");
  /* Which box the person is typing in. Without this the two fields fight: each
     rewrites the other on every keystroke, so a half-typed "4" in the margin
     box becomes a price, which becomes 4%, which overwrites the "40" they were
     in the middle of. */
  const [typing, setTyping] = useState<"price" | "margin">("price");

  useEffect(() => {
    setEach(current.toFixed(2));
    setMargin(String(marginOf(current, cost) ?? ""));
  }, [current, cost]);

  const asked = Number(each);
  const valid = Number.isFinite(asked) && asked >= 0;
  const line = valid ? asked * (quantity || 0) : 0;
  const belowCost = valid && cost > 0 && asked < cost;
  const changed = valid && Math.abs(asked - current) >= 0.005;

  const wasLine = useMemo(() => shelf * (quantity || 0), [shelf, quantity]);

  function typePrice(value: string) {
    setTyping("price");
    setEach(value);
    const n = Number(value);
    setMargin(Number.isFinite(n) && n > 0 ? String(marginOf(n, cost) ?? "") : "");
  }

  function typeMargin(value: string) {
    setTyping("margin");
    setMargin(value);
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    const price = priceFor(n, cost);
    if (price !== null && price >= 0) setEach(price.toFixed(2));
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-labelledby="price-title" onClick={onCancel}>
      <form className="modal price-modal" onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              if (valid && changed) onSet({ each: asked, keep, reason: reason.trim() });
            }}>
        <h2 id="price-title"><Tag size={18} weight="fill" /> Set the price</h2>
        <p className="muted">
          {name} {strength}. The catalogue says {money(shelf)} each
          {cost > 0 && <>, and it costs {money(cost)} to buy</>}.
        </p>

        <div className="price-pair">
          <div className="field">
            <label htmlFor="price-each">Price each</label>
            <input id="price-each" type="number" min={0} step="0.01" autoFocus
                   value={each} disabled={busy}
                   onFocus={(e) => e.currentTarget.select()}
                   onChange={(e) => typePrice(e.target.value)} />
          </div>
          <span className="price-or">or</span>
          <div className="field">
            <label htmlFor="price-margin">Margin</label>
            <div className="price-margin">
              <input id="price-margin" type="number" step="0.1" max={99.9}
                     value={margin} disabled={busy || cost <= 0}
                     onFocus={(e) => e.currentTarget.select()}
                     onChange={(e) => typeMargin(e.target.value)} />
              <span>%</span>
            </div>
          </div>
        </div>
        {cost <= 0 && (
          <p className="fin-note">
            Nothing is recorded for what this costs to buy, so a margin cannot be
            worked out. The price can still be set.
          </p>
        )}

        <dl className="price-sums">
          <dt>This line</dt>
          <dd>
            <b>{money(line)}</b> for {quantity}
            {Math.abs(line - wasLine) >= 0.005 && (
              <em className="price-was"> was {money(wasLine)}</em>
            )}
          </dd>
          {cost > 0 && (
            <>
              <dt>Makes</dt>
              <dd className={belowCost ? "is-bad" : ""}>
                {money((asked - cost) * (quantity || 0))}
                {typing === "price" && margin !== "" && <> · {margin}%</>}
              </dd>
            </>
          )}
        </dl>

        {belowCost && (
          <p className="fin-note is-warn">
            <Warning size={13} weight="fill" />
            <span>
              Below the {money(cost)} this costs to buy. Allowed, and recorded as
              a decision somebody made.
            </span>
          </p>
        )}

        {/* One checkbox, not a second dialog. The difference between the two
            answers is large and the question is small. */}
        <div className="price-keep">
          <Checkbox id="price-keep" checked={keep} onChange={setKeep}>
            Keep this price for good
          </Checkbox>
          <p className="muted small">
            {keep
              ? <>The catalogue changes to {money(asked || 0)} each. Every script
                  after this one is priced at it, and the change is recorded
                  against the medicine.</>
              : <>This script only. The shelf price stays at {money(shelf)} and
                  the next script is priced from the catalogue.</>}
          </p>
        </div>

        <div className="field">
          <label htmlFor="price-why">Why <span className="muted">(optional)</span></label>
          <input id="price-why" value={reason} maxLength={160} disabled={busy}
                 placeholder="Rounded at the counter · margin loaded wrong on import…"
                 onChange={(e) => setReason(e.target.value)} />
        </div>

        <p className="muted small">
          Setting a price needs your code, and is recorded against you either way.
        </p>

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>Never mind</button>
          <BusyButton type="submit" className="btn primary" busyLabel="Authorising…"
                      disabled={!valid || !changed}
                      onClick={() => {
                        if (valid && changed) onSet({ each: asked, keep, reason: reason.trim() });
                      }}>
            {keep ? "Set it, and keep it" : "Set it for this script"}
          </BusyButton>
        </div>
      </form>
    </div>
  );
}
