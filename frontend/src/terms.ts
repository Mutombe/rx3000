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
