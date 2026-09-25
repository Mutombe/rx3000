/** A column heading, with the icon its name implies.
 *
 *  Every interface studied puts a small icon before each column name. It is
 *  not decoration: a table header is ten words in 10.5px uppercase, which is
 *  the hardest text on the screen to read, and the icon is what lets somebody
 *  find the money column or the date column without reading any of them. On a
 *  screen looked at for nine hours that difference compounds.
 *
 *  THE ICON IS DERIVED, NOT TYPED.
 *
 *  There are 218 hand-rolled tables in this product. Asking each of them to
 *  name an icon would mean 218 chances to pick a different one for the same
 *  column, which is how "consistent" becomes "nearly consistent" — the exact
 *  failure this whole pass exists to undo. So the icon comes from the column's
 *  own name, through one table, and every "Patient" column in the product
 *  wears the same mark because there is only one place that decides.
 *
 *  A name this does not recognise gets NO icon rather than a guessed one. A
 *  wrong icon is worse than none: it is a label that says something untrue and
 *  costs a reader the moment it takes to discount it.
 */
import { ReactNode } from "react";
import {
  Barcode, Buildings, Calendar, ChatText, CurrencyDollar, Hash, Icon,
  MapPin, Package, Percent, Phone, Pill, Stack, Tag, User, Warning,
} from "@phosphor-icons/react";

/** What a column name means, in the words this product actually uses.
 *
 *  Matched on whole words against the lower-cased heading, longest first, so
 *  "at cost" is money rather than a date and "on hand" is a quantity rather
 *  than a body part. */
const MEANS: [RegExp, Icon][] = [
  // People. The commonest column in the product and the one a face already
  // marks in the cell; the header says which kind of person it is.
  [/\b(patient|prescriber|doctor|driver|staff|cashier|dispenser|user|owner|contact|recipient|assignee|member|created by|approved by|requested by|by)\b/, User],
  // Money. Anything a pharmacy counts in dollars.
  [/\b(total|amount|value|worth|price|cost|at cost|paid|owed|claimed|balance|due|takings|margin|fee|subtotal|vat|tender|change|shortfall)\b/, CurrencyDollar],
  [/\b(percent|rate|share|%)\b/, Percent],
  // Time.
  [/\b(when|date|written|raised|created|dispensed|expiry|expires|promised|collected|settled|last|next|opened|closed|period|at)\b/, Calendar],
  // Counts and quantities.
  [/\b(qty|quantity|items|lines|line|count|units|on hand|packs|stock|remaining|left)\b/, Stack],
  // The medicine itself.
  [/\b(medicine|product|drug|item|ingredient|formulation)\b/, Pill],
  // A batch, a pack, a delivery.
  [/\b(batch|pack|delivery|consignment|shipment|bag)\b/, Package],
  // Numbers a person reads off paper and types back in.
  [/\b(reference|ref|code|number|no\.?|invoice|waybill|script|rx|barcode|serial)\b/, Barcode],
  // Places and organisations.
  [/\b(supplier|branch|pharmacy|company|account|scheme|funder|department|wholesaler)\b/, Buildings],
  [/\b(address|location|bin|shelf|area|route|town|city)\b/, MapPin],
  [/\b(phone|mobile|telephone|cell)\b/, Phone],
  // Free text somebody wrote.
  [/\b(why|reason|note|notes|comment|message|instruction|remark)\b/, ChatText],
  // What kind of thing this row is.
  [/\b(type|category|schedule|class|kind|channel|method|source)\b/, Tag],
  // Where it has got to. Deliberately last: "status" is specific, but words
  // like "state" appear inside other phrases.
  [/\b(status|state|stage|progress|outcome|result)\b/, Warning],
  [/\b(id|identifier)\b/, Hash],
];

/** The icon a column name implies, or null when nothing here fits it. */
export function columnIcon(label: string): Icon | null {
  const said = label.toLowerCase().trim();
  if (!said) return null;
  for (const [pattern, icon] of MEANS) {
    if (pattern.test(said)) return icon;
  }
  return null;
}

export default function Th({
  children, className, icon, ...rest
}: {
  children?: ReactNode;
  className?: string;
  /** Override where the heading's words do not imply the right mark. */
  icon?: Icon | null;
} & Omit<React.ThHTMLAttributes<HTMLTableCellElement>, "className" | "children">) {
  // Only a plain-text heading can be read for meaning. A heading built from
  // markup is already saying something in its own way and is left alone.
  const said = typeof children === "string" ? children : "";
  const Mark = icon === undefined ? columnIcon(said) : icon;
  return (
    <th className={className} {...rest}>
      {Mark ? (
        <span className="th-said">
          <Mark size={12} weight="bold" aria-hidden />
          {children}
        </span>
      ) : children}
    </th>
  );
}
