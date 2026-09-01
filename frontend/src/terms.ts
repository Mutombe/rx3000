/** The words a Zimbabwean pharmacy already uses, in one place.
 *
 *  Somebody moving off Proppharm has twenty years of vocabulary and no
 *  patience for ours. Where this software invented a term for something the
 *  trade already names, the trade wins: a dispenser should be able to read a
 *  screen they have never seen and know what every figure is, because the
 *  figures are called what they call them.
 *
 *  SHORTFALL
 *
 *  The one that prompted this. When a medical aid does not cover the full
 *  price and the patient makes up the difference at the counter, that
 *  difference is a **shortfall**. Every pharmacy in the country says so. This
 *  software called it "patient pays" and "patient portion" — descriptions of
 *  the same number that nobody would say out loud.
 *
 *  It is not a synonym for "what the patient hands over". A private patient
 *  paying cash is not paying a shortfall; they are paying the price. A
 *  shortfall exists only where a scheme was billed and did not cover it all,
 *  which is why `patientOwes` below asks whether there is a scheme rather than
 *  substituting the word everywhere and being wrong half the time.
 *
 *  Its two parts keep their own names, because a patient querying the amount
 *  is querying one of them and not the other:
 *
 *    the **levy** is the scheme's own co-payment, fixed or a percentage, and
 *      is a term of the member's cover — arguing it is between them and the
 *      scheme;
 *    the amount **above the scheme rate** is the excess over the reference
 *      price (MMAP), and is a consequence of what was dispensed — a generic
 *      at the reference price would remove it.
 */

/** What to call the amount the patient settles at the counter.
 *
 *  @param onScheme whether a medical aid was billed for this at all.
 */
export function patientOwes(onScheme: boolean): string {
  return onScheme ? "Shortfall" : "Patient pays";
}

/** The sentence form, for a receipt line or a notice mid-paragraph. */
export function patientOwesPhrase(onScheme: boolean): string {
  return onScheme ? "shortfall" : "patient pays";
}

/** A script captured but not yet finished, so it holds no Rx number.
 *
 *  A **draft**. Its own thing, with its own section.
 *
 *  It was briefly called "N-Repeat" here, which was my misreading: an N-Repeat
 *  is a repeat with collections still to come (below), and a draft is a script
 *  that was never finished being typed. They have nothing to do with each
 *  other — one is about a script's future, the other about its capture — and
 *  putting one name on both would have been the same fault as calling a
 *  shortfall a "patient portion": one word over two different facts.
 */
export const DRAFT_SCRIPT = "Draft";
export const DRAFT_SCRIPT_PLURAL = "Drafts";

/** A repeat with collections still to come: the trade's "3-Repeat".
 *
 *  What the dispensary means by an N-Repeat: a script that is not finished
 *  *being repeated*. Five collections were authorised, two have gone out,
 *  three are still owed to the patient — that is a 3-Repeat, and the number is
 *  the point of the name.
 *
 *  It is not the same as "due". A 3-Repeat may not be due for a fortnight; it
 *  is a statement about what the script still holds, not about today's work.
 */
export function nRepeat(remaining: number | null | undefined): string {
  const n = remaining ?? 0;
  return n > 0 ? `${n}-Repeat` : "";
}

/** The same, spelt out, where a badge would be too terse. */
export function nRepeatPhrase(remaining: number | null | undefined): string {
  const n = remaining ?? 0;
  if (n <= 0) return "no repeats left";
  return `${n} repeat${n === 1 ? "" : "s"} still to come`;
}

/** The trade's word for each figure, so one edit changes every screen. */
export const TERMS = {
  shortfall: "Shortfall",
  levy: "Levy",
  aboveRate: "Above scheme rate",
  schemePays: "Scheme pays",
  gross: "Gross",
  dispensingFee: "Dispensing fee",
  referencePrice: "Reference price (MMAP)",
} as const;

/** What a shortfall is, in one sentence, for a tooltip or an empty state. */
export const SHORTFALL_MEANING =
  "The part of the price the scheme did not cover, which the patient settles "
  + "at the counter.";
