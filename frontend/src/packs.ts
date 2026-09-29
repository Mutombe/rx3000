/** Packs and units, said the same way everywhere.
 *
 *  THE SHELF COUNTS IN UNITS. PEOPLE COUNT IN BOXES.
 *
 *  `quantity_on_hand` is dispensable units and always has been: a tub of a
 *  thousand capsules is 1000, receiving a pack adds `units_per_pack`, and
 *  dispensing thirty subtracts thirty. That is the right thing to store,
 *  because it is the only figure that survives a script for thirty out of a
 *  tub of a hundred.
 *
 *  It is the wrong thing to show on its own. A pharmacist standing at a shelf
 *  is looking at boxes. "227" against a pack of thirty means seven boxes and
 *  seventeen loose, and those are the two numbers somebody counts, orders and
 *  answers for. Printing only the first makes a stock take an arithmetic
 *  exercise and an order a guess.
 *
 *  So the unit figure stays the figure, and the pack breakdown is said beside
 *  it. One place, because the wording has to be identical on the stock table,
 *  in an adjustment, on a receipt and in a count: two screens that describe the
 *  same shelf differently are two screens somebody has to reconcile.
 */

/** Units in one pack, never zero. Division by this must always be safe.
 *
 *  Mirrors `Product.per_pack` on the server, which is the authority. One means
 *  the pack IS the unit: a bottle of syrup, a tube of cream, every front shop
 *  line, and every product nobody has told us about.
 */
export function perPackOf(p: { units_per_pack?: number | null } | null | undefined): number {
  const n = Number(p?.units_per_pack ?? 1);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
}

/** Whether the pack breakdown says anything this product does not already. */
export function packsMatter(perPack: number): boolean {
  return perPack > 1;
}

export interface InPacks {
  /** Whole packs. */
  packs: number;
  /** Units left over, which is what "loose" means on a shelf. */
  loose: number;
  perPack: number;
}

/** Split a unit figure into whole packs and what is left over.
 *
 *  Negative figures keep their sign on the packs and report the shortfall as
 *  loose, because a negative shelf is a real state the software can be in and
 *  saying "minus one pack and twenty nine loose" about it would be nonsense.
 */
export function inPacks(units: number, perPack: number): InPacks {
  const each = perPack >= 1 ? Math.floor(perPack) : 1;
  const whole = Math.trunc(units / each);
  return { packs: whole, loose: units - whole * each, perPack: each };
}

/** The short form, for a table cell: "7 packs + 17".
 *
 *  Empty where the pack is the unit, so a column of shampoo and plasters does
 *  not carry a second line saying the same thing twice.
 */
export function saidShort(units: number, perPack: number): string {
  if (!packsMatter(perPack)) return "";
  const { packs, loose } = inPacks(units, perPack);
  if (packs === 0) return `${loose} loose`;
  const word = Math.abs(packs) === 1 ? "pack" : "packs";
  return loose === 0 ? `${packs} ${word}` : `${packs} ${word} + ${loose}`;
}

/** The whole of it in words, for a tooltip or a dialog, where there is room to
 *  be unambiguous: "227 units. 7 packs of 30, and 17 loose." */
export function saidLong(units: number, perPack: number): string {
  const unitWord = Math.abs(units) === 1 ? "unit" : "units";
  if (!packsMatter(perPack)) return `${units} ${unitWord}`;
  const { packs, loose } = inPacks(units, perPack);
  const packWord = Math.abs(packs) === 1 ? "pack" : "packs";
  if (packs === 0) return `${units} ${unitWord}, none of them a whole pack of ${perPack}`;
  if (loose === 0) return `${units} ${unitWord}. ${packs} ${packWord} of ${perPack}.`;
  return `${units} ${unitWord}. ${packs} ${packWord} of ${perPack}, and ${loose} loose.`;
}
