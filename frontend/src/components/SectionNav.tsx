/** Tabs across the top of a group of pages that belong together.
 *
 *  The sidebar had grown to about fifty entries, and the cost of that is not
 *  the length — it is that everything looks equally important. Claiming,
 *  Claiming calendar, Authorisations and Claims held were four siblings in one
 *  list when three of them are things you do *from within* claiming, and
 *  reconciliation had five entries scattered across three sections.
 *
 *  So related pages keep their own routes — deep links, prefetching and code
 *  splitting all still work, and nothing that pointed at them breaks — and
 *  gain a strip that says which family they are in and where else you can go.
 *  One entry in the sidebar per family.
 *
 *  Links rather than state. A tab that changes a variable loses the page on
 *  refresh and cannot be sent to somebody, and half the reason a person opens
 *  Authorisations is that a colleague sent them the link.
 */
import { NavLink } from "react-router-dom";
import { prefetchRoute } from "../api";

export interface SectionTab {
  to: string;
  label: string;
  /** Shown as a count beside the label. Omitted rather than rendered as 0 —
   *  "Claims held (0)" reads as a broken counter, not as good news. */
  count?: number | null;
  hint?: string;
}

export default function SectionNav(
  { tabs, end }: { tabs: SectionTab[]; end?: string },
) {
  return (
    <nav className="section-nav" aria-label="Section">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          title={t.hint}
          // `end` on the family's own root, or /claiming stays highlighted
          // while you are on /claiming/authorisations and two tabs look active.
          end={t.to === end}
          onMouseEnter={() => prefetchRoute(t.to)}
          className={({ isActive }) => (isActive ? "active" : "")}
        >
          {t.label}
          {t.count ? <span className="section-nav-count">{t.count}</span> : null}
        </NavLink>
      ))}
    </nav>
  );
}
