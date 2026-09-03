/** The colour language: what a colour means, everywhere in the product.
 *
 *  A pharmacy assistant should learn four colours once and then read every
 *  screen faster for ever. That only works if a colour means the same thing on
 *  the dispensing screen, in a table, on a badge and in the sidebar — so the
 *  mapping lives here, once, and nothing picks its own.
 *
 *  THE FOUR
 *
 *    person    navy      who it is for, or who did it
 *    script    violet    the document: a prescription, a repeat, a dispensing
 *    medicine  raspberry what is being handed over, and the stock behind it
 *    money     bronze    what is owed, taken, claimed or banked
 *
 *  Controlled substances keep the deeper wine they already had. That is
 *  deliberate rather than a leftover: a controlled substance IS a medicine, so
 *  it belongs on the medicine axis, at the end you have to look twice at.
 *
 *  WHY NOT MORE THAN FOUR
 *
 *  Twenty-five record types are linkable. Nobody memorises twenty-five
 *  colours, so they are grouped into the four things a person actually thinks
 *  in at a counter.
 *
 *  And the hue space is smaller than it looks. Green, amber and red already
 *  mean *states* here — fine, warning, stop — and a state colour must always
 *  win, so no entity may borrow one. That rules out the two most intuitive
 *  choices available: gold for money and teal for medicine. Both were tried
 *  and both measured too close to warn-amber and ok-green respectively, so
 *  they were dropped. Meaning has to give way to legibility, because a colour
 *  that reads as a warning when it is not is worse than one nobody has an
 *  instinct about.
 *
 *  MEASURED, NOT CHOSEN BY EYE
 *
 *  Every pair was measured in OKLab and again through deuteranopia and
 *  protanopia simulations, in both themes, against each other and against the
 *  four state colours. The first four hues picked by eye failed badly: person
 *  and money came out 1.4 apart under protanopia, which is to say identical.
 *  The set below has no pair under 17 in either theme.
 *
 *  qa/colour-language.py holds those measurements and fails if an edit breaks
 *  one, because this is the kind of thing that is only wrong on somebody
 *  else's monitor.
 */
import type { EntityKind } from "./entityRoutes";

export type Family = "person" | "script" | "medicine" | "money";

/** Every linkable record, and which of the four it belongs to.
 *
 *  Exhaustive on purpose: `Record<EntityKind, Family>` means a new record type
 *  cannot be added without deciding what colour it is, and TypeScript says so
 *  at the point the route is added rather than leaving it grey for ever.
 */
export const FAMILY: Record<EntityKind, Family> = {
  // Who
  patient: "person",
  prescriber: "person",
  staff: "person",
  contact: "person",
  lead: "person",
  driver: "person",

  // The document
  prescription: "script",
  repeat: "script",
  dispensing: "script",
  case: "script",
  message: "script",
  campaign: "script",

  // What is handed over, and the stock behind it
  product: "medicine",
  batch: "medicine",
  supplier: "medicine",
  order: "medicine",

  // What is owed, taken, claimed or banked
  sale: "money",
  layby: "money",
  invoice: "money",
  journal: "money",
  account: "money",
  shift: "money",
  claim: "money",
  claim_batch: "money",
  deal: "money",
  waybill: "money",
};

/** The class that carries the colour. One name, so a stylesheet rule and a
 *  check can both find it. */
export function toneClass(kind: EntityKind | undefined): string {
  return kind ? `tone-${FAMILY[kind]}` : "";
}

/** What each family is called, for a legend or a tooltip. */
export const FAMILY_MEANS: Record<Family, string> = {
  person: "someone: a patient, a prescriber, a member of staff",
  script: "a record of what was prescribed or dispensed",
  medicine: "a medicine, or the stock behind it",
  money: "money owed, taken, claimed or banked",
};


/** The same four colours, for the places that NAME a record type rather than
 *  link to one.
 *
 *  A colour language that only reached the links would be a language spoken in
 *  half the sentences. These are the other half: the word above a record page
 *  saying what kind of thing it is, and the sidebar, which is the one surface
 *  somebody looks at every few minutes all day and therefore where the
 *  association is actually learnt.
 *
 *  Kept as tables rather than derived from the text, because "Owed to a
 *  patient" is money and "On the shelf" is medicine, and no rule reads those
 *  correctly. qa/colour-language.py asserts that every eyebrow written in a
 *  page and every route in the sidebar appears here, so a new screen cannot
 *  quietly arrive uncoloured.
 */
export const LABEL_FAMILY: Record<string, Family> = {
  // Who
  Patient: "person", Prescriber: "person", Staff: "person",
  Contact: "person", Lead: "person", Driver: "person",

  // The document
  Prescription: "script", Repeat: "script", Dispensing: "script",
  Case: "script", Message: "script", Campaign: "script",
  Script: "script",

  // What is handed over, and the stock behind it
  Product: "medicine", Batch: "medicine", Supplier: "medicine",
  "Purchase order": "medicine", "On the shelf": "medicine",
  Branch: "medicine",

  // Money
  Sale: "money", "Lay-by": "money", "Supplier invoice": "money",
  Account: "money", "Till session": "money", Claim: "money",
  "Claim batch": "money", "Remittance advice": "money",
  Opportunity: "money", Waybill: "money", "Owed to a patient": "money",
  "Fiscal day": "money",
};

/** The sidebar. Every destination, and the thing it is mostly about.
 *
 *  "Mostly" is doing real work here: the dispensary is about scripts AND
 *  patients AND medicines. It is coloured for the document, because that is
 *  what a dispenser goes there to produce. Where a screen genuinely has no
 *  single subject — the command centre, the control panel — it takes no
 *  colour rather than a misleading one.
 */
export const ROUTE_FAMILY: Record<string, Family> = {
  "/dispense": "script", "/patients": "person", "/to-follows": "medicine",
  "/will-call": "medicine", "/dispensing-history": "script",
  "/scripts": "script", "/repeats": "script", "/compounding": "medicine",
  "/register": "medicine", "/deliveries": "money", "/drivers": "person",
  "/reminders": "person",

  "/pos": "money", "/shifts": "money", "/fiscal": "money",
  "/laybys": "money", "/money-owed": "money",

  "/stock": "medicine", "/stock-categories": "medicine",
  "/stock-performance": "medicine", "/orders": "medicine",
  "/stock-take": "medicine", "/samples": "medicine", "/recall": "medicine",
  "/branches": "medicine", "/compliance": "medicine",

  "/claiming": "money", "/remittances": "money", "/reconciliation": "money",
  "/payables": "money", "/ledger": "money", "/periods": "money",

  "/scorecard": "money", "/reports": "money", "/seasons": "medicine",
  "/helpdesk": "person", "/accounts": "person", "/leads": "person",
  "/pipeline": "money", "/marketing": "person", "/crm-reports": "money",
  "/head-office": "person", "/pharmacies": "person",
};

/** The class for a named record type, or nothing where it has no single
 *  subject. Nothing is the honest answer for a dashboard. */
export function labelTone(label: string | undefined): string {
  const f = label ? LABEL_FAMILY[label] : undefined;
  return f ? `tone-${f}` : "";
}

export function routeTone(to: string | undefined): string {
  const f = to ? ROUTE_FAMILY[to] : undefined;
  return f ? `tone-${f}` : "";
}
