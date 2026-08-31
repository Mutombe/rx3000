/** The branch family: the shops, and what each of them is licensed to do.
 *
 *  Licences lived on their own sidebar entry, three sections away from
 *  Branches, and the two answer halves of one question. "Is the Bulawayo shop
 *  all right" means both "what is on its shelves and who is accountable for
 *  it" and "is its MCAZ premises licence current" — and a manager checking
 *  before an inspection was navigating between two unrelated-looking screens
 *  to assemble one picture.
 *
 *  Separate routes, one family. Deep links, prefetching and code splitting all
 *  still work and nothing that pointed at either breaks; they simply gain a
 *  strip saying where else you can go from here.
 */
import type { SectionTab } from "./components/SectionNav";

export const BRANCH_TABS: SectionTab[] = [
  { to: "/branches", label: "Branches",
    hint: "Each shop, who is accountable for it, and stock moving between them" },
  { to: "/compliance", label: "Licences & permits",
    hint: "What each branch is licensed to do, what expires when, and what is "
        + "not on file" },
];
