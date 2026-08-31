import { TrendDown, Warning } from "@phosphor-icons/react";
import { money } from "../api";

/** What this line makes, on the line, while the script is being built.
 *
 *  WHY IT IS HERE AND NOT ONLY IN THE TOTALS BAR
 *
 *  The bar along the bottom has carried per-line margin since it was written,
 *  folded away behind "Line by line". That is the right place to *audit* a
 *  script and the wrong place to *price* one: the moment a discount gets
 *  granted is the moment somebody is looking at one medicine, and a figure two
 *  scrolls down behind a toggle is a figure nobody consults before saying yes.
 *
 *  So it sits on the line it describes. A dispenser asked for ten percent off
 *  can see, without moving, whether ten percent is most of what the line makes.
 *
 *  WHAT THE BANDS MEAN
 *
 *  They are read at a glance rather than computed, so they are coarse on
 *  purpose and they say what to do rather than what the number is:
 *
 *    below zero   selling under cost — this is the one that must interrupt;
 *    under 10%    a discount here mostly comes out of the pharmacy;
 *    under 25%    ordinary for a scheme line at the reference price;
 *    above that   there is room to negotiate.
 *
 *  The thresholds are deliberately not configurable yet. A number somebody has
 *  to set before the colour means anything is a number that stays at its
 *  default, and a default nobody chose is worse than a stated convention.
 */

/** Percentage of gross that is margin, banded. */
function band(percent: number): { tone: string; hint: string } {
  if (percent < 0) {
    return { tone: "loss", hint: "Below cost. Check the price before dispensing." };
  }
  if (percent < 10) {
    return { tone: "thin", hint: "Thin. A discount here comes out of the pharmacy." };
  }
  if (percent < 25) {
    return { tone: "ok", hint: "Ordinary for a scheme line." };
  }
  return { tone: "good", hint: "Room to discount." };
}

export default function MarginTag({ percent, profit, gross, compact }: {
  percent: number;
  /** Money made on the line. Shown alongside, because 40% of two dollars and
   *  40% of two hundred are not the same conversation. */
  profit?: number;
  gross?: number;
  compact?: boolean;
}) {
  const { tone, hint } = band(percent);
  const rounded = Math.round(percent);
  return (
    <span className={`mtag mtag-${tone}`}
          title={`${hint}${gross !== undefined ? ` Gross ${money(gross)}.` : ""}`}>
      {percent < 0 && <TrendDown size={11} weight="fill" />}
      {percent >= 0 && percent < 10 && <Warning size={11} weight="fill" />}
      <b>{rounded}%</b>
      {!compact && profit !== undefined && (
        <span className="mtag-money">{money(profit)}</span>
      )}
    </span>
  );
}

/** The same badge from a shelf price and a cost, with no basket priced.
 *
 *  Used in the search results, before a medicine is on the script at all —
 *  which is where a substitution is actually decided. It is the cash margin,
 *  not the scheme margin: no scheme has been chosen for a product nobody has
 *  added yet, and quoting a scheme figure that has not been worked out would
 *  be inventing one.
 */
export function shelfMargin(unitPrice: number, costPrice: number): number | null {
  // No cost on file is not a margin of one hundred percent. It is not knowing,
  // and the difference matters when the number is about to justify a discount.
  if (!costPrice || costPrice <= 0 || !unitPrice || unitPrice <= 0) return null;
  return ((unitPrice - costPrice) / unitPrice) * 100;
}
