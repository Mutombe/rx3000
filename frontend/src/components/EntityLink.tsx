/** A name in a table that you can click through to the thing itself.
 *
 *  Most tables in this system printed names as plain text. A recall listed the
 *  patients holding a batch and you could not open one of them; the ageing
 *  listed six suppliers and you could not see what any of them had billed. The
 *  reader's next move was always to memorise a name, go to another screen and
 *  search for it — which is the difference between software and a printout.
 *
 *  Everything routes through here rather than each table writing its own
 *  `<Link to={...}>`, for two reasons. The paths live in one place, so a route
 *  that gets renamed is one edit instead of eighty. And an id that is missing —
 *  a walk-in with no patient record, a batch nobody recorded — degrades to
 *  plain text instead of producing a link to `/patients/undefined`, which is
 *  the failure this pattern otherwise makes eighty times over.
 */
import { Link } from "react-router-dom";
import type { ReactNode } from "react";

/** Every kind of thing a row can name, and where its page lives. */
export const ENTITY_ROUTES = {
  account: (id: Id) => `/accounts/${id}`,
  batch: (id: Id) => `/batches/${id}`,
  campaign: (id: Id) => `/campaigns/${id}`,
  case: (id: Id) => `/cases/${id}`,
  claim: (id: Id) => `/claims/${id}`,
  contact: (id: Id) => `/contacts/${id}`,
  deal: (id: Id) => `/deals/${id}`,
  invoice: (id: Id) => `/payables/invoices/${id}`,
  journal: (id: Id) => `/ledger/journal/${id}`,
  layby: (id: Id) => `/laybys/${id}`,
  lead: (id: Id) => `/leads/${id}`,
  message: (id: Id) => `/messages/${id}`,
  order: (id: Id) => `/orders/${id}`,
  patient: (id: Id) => `/patients/${id}`,
  prescriber: (id: Id) => `/prescribers/${id}`,
  prescription: (id: Id) => `/prescriptions/${id}`,
  product: (id: Id) => `/products/${id}`,
  sale: (id: Id) => `/sales/${id}`,
  shift: (id: Id) => `/shifts/${id}`,
  staff: (id: Id) => `/staff/${id}`,
  supplier: (id: Id) => `/suppliers/${id}`,
} as const;

type Id = string | number;
export type EntityKind = keyof typeof ENTITY_ROUTES;

export function entityHref(kind: EntityKind, id: Id): string {
  return ENTITY_ROUTES[kind](id);
}

interface Props {
  kind: EntityKind;
  /** Null, zero or undefined all mean "there is no such thing to open". */
  id: Id | null | undefined;
  children: ReactNode;
  /** Extra classes for the anchor, e.g. `mono` on a reference number. */
  className?: string;
  /** Shown on hover. Defaults to nothing rather than a laboured "View the…". */
  title?: string;
  /** Renders when there is no id. Defaults to the children as plain text. */
  fallback?: ReactNode;
}

export default function EntityLink({ kind, id, children, className = "",
                                     title, fallback }: Props) {
  // A walk-in sale has no patient, a batch may have no supplier recorded, and a
  // line entered by hand may name a product that is not in the catalogue. None
  // of those is an error; none of them is a link either.
  if (id === null || id === undefined || id === 0 || id === "") {
    return <>{fallback ?? children}</>;
  }
  return (
    <Link to={entityHref(kind, id)} className={`elink ${className}`.trim()}
          title={title}>
      {children}
    </Link>
  );
}
