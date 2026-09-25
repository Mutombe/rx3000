/** The top of a list page: what this screen is, and what you can do to it.
 *
 *  WHY THIS EXISTS.
 *
 *  Fifty-eight list pages hand-rolled this block, sixty-one times, and they
 *  had drifted the way sixty-one copies of anything drift. Forty-one opened
 *  with `<div>` and seventeen with `<header>`, so the same heading was a
 *  landmark to a screen reader on some pages and not on others. One page wrote
 *  its subtitle as `page-sub` rather than `sub`, which is styled nowhere, so
 *  it rendered at body size on a screen where every other subtitle is smaller
 *  and quieter. Only thirty-six wrapped their actions in `.page-actions`; the
 *  rest dropped bare buttons into a flex row and relied on `space-between`,
 *  which is precisely the bug `RecordPage` carries a comment about having
 *  fixed for detail pages — two buttons push apart instead of sitting
 *  together, and a third lands in the middle of the title.
 *
 *  Detail pages have had `RecordPage` for this all along. List pages had
 *  nothing, which is why they are the ones that drifted.
 *
 *  THE COUNT BELONGS UP HERE.
 *
 *  Every one of the sixteen interfaces studied states the size of the list
 *  near its name: "120 Results", "324 Customer", "661". It answers the first
 *  question anybody has about a list before they have to scroll to find out,
 *  and it gives the page somewhere honest to say "of 4,812" when it is showing
 *  fifty. Given as a `count`, it sits against the title as a chip.
 */
import { ReactNode } from "react";

export default function PageHead({
  title, sub, count, children, eyebrow,
}: {
  title: ReactNode;
  /** One line saying what this screen is for. */
  sub?: ReactNode;
  /** How many things are in the list. A number, or a phrase where the number
   *  needs qualifying ("50 of 4,812"). */
  count?: ReactNode;
  /** What kind of thing this page is about, above the title. */
  eyebrow?: ReactNode;
  /** The page's actions. Always grouped, so two buttons sit together instead
   *  of being pushed to opposite ends of the row. */
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-said">
        {eyebrow ? <div className="page-eyebrow">{eyebrow}</div> : null}
        <h1>
          {title}
          {count !== undefined && count !== null
            ? <span className="page-count">{count}</span> : null}
        </h1>
        {sub ? <div className="sub">{sub}</div> : null}
      </div>
      {children ? <div className="page-actions">{children}</div> : null}
    </header>
  );
}
