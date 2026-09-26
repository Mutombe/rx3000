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
  title, sub, count, eyebrow, bring, take, also, primary,
}: {
  title: ReactNode;
  /** One line saying what this screen is for. */
  sub?: ReactNode;
  /** How many things are in the list. A number, or a phrase where the number
   *  needs qualifying ("50 of 4,812"). */
  count?: ReactNode;
  /** What kind of thing this page is about, above the title. */
  eyebrow?: ReactNode;

  /* FOUR SLOTS, IN ONE ORDER, AND A PAGE FILLS THE ONES IT HAS.
   *
   * The space between the title and the far edge was empty on twenty pages
   * and held a single button on twenty-six more, and the commonest thing in
   * it across the whole product was Refresh — a control that says the page
   * might be stale and you should not trust it, sitting where the eye goes
   * first.
   *
   * Filling it by hand, page by page, is how fifty-six headers end up in
   * fifty-six arrangements, which is the drift this component was written to
   * stop. So the slots are named and ordered here, and a page chooses what
   * goes in them rather than where.
   *
   * Left to right, quietest to loudest, because the last thing before the
   * edge is the thing somebody came to do:
   *
   *   bring    work arriving from outside: import, receive, fetch.
   *   take     work leaving: export, print. ONE control, not three.
   *   also     the second thing somebody would start here.
   *   primary  the one thing this page exists to let you start.
   *
   * TWO THINGS THAT DO NOT BELONG HERE, AND WHY.
   *
   * An action on ROWS goes in the bulk bar, which appears when something is
   * ticked. "Export selected" in the header would be a button that is wrong
   * most of the time it is visible.
   *
   * An action that NARROWS the list goes in the rail above the table with
   * the search and the count. A filter in the header reads as something that
   * changes the records rather than the view of them.
   */
  bring?: ReactNode;
  take?: ReactNode;
  also?: ReactNode;
  primary?: ReactNode;

  /* THERE IS NO `children` ANY MORE, AND THAT IS THE POINT.
   *
   * It existed for one pass, while fifty-six pages were moved over, and every
   * page is now on the slots. Leaving it would leave the drift a door: a page
   * added next month would pass its actions as children, land in the same
   * visual place, and be indistinguishable on screen from a page using the
   * slots — which is exactly how sixty-one hand-rolled headers happened the
   * first time. Nine of those pages had ALSO wrapped their children in a
   * second `.page-actions`, nesting one flex row inside another, so the gap
   * between their buttons came from the inner one and did not match the rest
   * of the product.
   *
   * A page with an action that fits none of the four names is a page that has
   * found a fifth kind of action, and that is worth a name here rather than an
   * escape hatch. */
}) {
  const slots = [bring, take, also, primary].filter(Boolean);
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
      {slots.length > 0 ? (
        <div className="page-actions">
          {bring}
          {take}
          {also}
          {primary}
        </div>
      ) : null}
    </header>
  );
}
