/** The reconciliation family, and the claiming family.
 *
 *  Listed once so the strip is identical on every page in the group. Defined
 *  outside the pages themselves because each page renders the whole strip
 *  including its own entry, and a list that lives inside one of them makes the
 *  other three import a page to draw their navigation.
 */
import type { SectionTab } from "./components/SectionNav";

/** Everything with two records of one fact.
 *
 *  Cash and stock point at the screens that already did those jobs rather than
 *  being rebuilt here. The cash-up is the cash office's whole reason to exist
 *  and stock drift is read next to the catalogue it describes; moving them
 *  would be tidying at the cost of the people who use them daily.
 */
export const RECON_TABS: SectionTab[] = [
  { to: "/reconciliation", label: "What does not tie up",
    hint: "Every reconciliation, and which have not been run" },
  { to: "/reconciliation/card", label: "Card",
    hint: "The acquirer's settlement file against the card sales recorded" },
  { to: "/reconciliation/bank", label: "Bank",
    hint: "The bank statement against the ledger" },
  { to: "/remittances", label: "Claims",
    hint: "What was claimed against what the funder paid" },
  { to: "/reconciliation/settlements", label: "Settlements",
    hint: "Is each funder paying us, in full, on time" },
  { to: "/shifts", label: "Cash",
    hint: "Counted drawers against what passed through the till" },
  { to: "/stock?tab=reconcile", label: "Stock",
    hint: "Each product's own count against the batches behind it" },
];

/** Claiming and the three things you do from inside it. */
export const CLAIMING_TABS: SectionTab[] = [
  { to: "/claiming", label: "Batches" },
  { to: "/claiming-calendar", label: "Calendar",
    hint: "When each scheme has to be claimed by" },
  { to: "/authorisations", label: "Authorisations",
    hint: "Pre-authorisations asked for and granted" },
  { to: "/claims-held", label: "Claims held",
    hint: "Claims deferred rather than sent" },
];
