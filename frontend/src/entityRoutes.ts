/** Where each kind of record lives, in one place.
 *
 *  Eighty-odd tables name people, medicines, scripts and invoices. Left to
 *  themselves each one writes its own `/patients/${id}` and a renamed route
 *  becomes eighty edits and a handful of dead links nobody notices until a
 *  customer does. One map instead.
 */
export const ENTITY_ROUTES = {
  account: (id: Id) => `/accounts/${id}`,
  batch: (id: Id) => `/batches/${id}`,
  campaign: (id: Id) => `/campaigns/${id}`,
  case: (id: Id) => `/cases/${id}`,
  claim: (id: Id) => `/claims/${id}`,
  // The claim batch, not the stock batch above it. Two different
  // things called a batch in one pharmacy, and conflating them sends
  // somebody chasing a wholesaler's lot number for a short payment.
  claim_batch: (id: Id) => `/claim-batches/${id}`,
  waybill: (id: Id) => `/waybills/${id}`,
  contact: (id: Id) => `/contacts/${id}`,
  deal: (id: Id) => `/deals/${id}`,
  driver: (id: Id) => `/drivers/${id}`,
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
