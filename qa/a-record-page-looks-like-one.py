"""Every detail page wears the same header.

WHY THIS GUARD EXISTS

Four detail pages were measured side by side and had four different headers:
header heights of 76, 93, 93 and 142px; two with no record type above the
name; two whose breadcrumb ended "This record" rather than naming it; two
whose action buttons were not grouped, so `.page-head`'s space-between
scattered them across the width; and one with an avatar beside the title that
indented the name 58px further in than the breadcrumb above it, so nothing on
the page shared a left edge.

`RecordPage` exists so a page is only the part that differs. Twenty-five pages
used it and eleven had drifted off, including the two most-opened records in
the product: the patient and the product. Drift is the normal state of a
shared layout nobody checks, so this checks it.

WHAT IT DELIBERATELY DOES NOT DO

It does not read the rendered pixels. A page can use RecordPage and still be
laid out badly; what this catches is the class of problem that made those four
headers differ, which is a page building its own.
"""
import pathlib
import re
import sys

PAGES = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"

#: Pages whose name ends in Detail but which are not a single record.
#: Kept explicit so an exemption is a decision somebody wrote down.
NOT_A_RECORD: set[str] = set()

passed = failed = 0


def check(said, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {said}")
    else:
        failed += 1
        print(f"  X    {said}")
        if detail:
            print(f"       {detail}")


print("\n  every detail page wears the same header\n")

pages = sorted(p for p in PAGES.glob("*Detail.tsx") if p.name not in NOT_A_RECORD)
check(f"there are detail pages to check ({len(pages)})", bool(pages))

rolled_own, no_crumb, ungrouped, generic_tail = [], [], [], []

for page in pages:
    text = page.read_text(encoding="utf-8")

    if "RecordPage" not in text:
        rolled_own.append(page.name)
        # The three specific symptoms, so a failure says what is wrong rather
        # than only that something is.
        if "<Breadcrumbs" not in text:
            no_crumb.append(page.name)
        head = re.search(r'className="page-head"(.*?)</div>\s*\n', text, re.S)
        if head and "page-actions" not in head.group(1):
            ungrouped.append(page.name)

    # A trail ending "This record" names nothing. Somebody two pages deep
    # reads the trail to find out what they are looking at.
    if '{ label: "This record" }' in text.replace("'", '"'):
        generic_tail.append(page.name)

check("every detail page uses RecordPage", not rolled_own,
      f"building their own header: {', '.join(rolled_own)}")
check("no hand-rolled header is missing its breadcrumb", not no_crumb,
      f"no trail at all: {', '.join(no_crumb)}")
check("no hand-rolled header leaves its actions ungrouped", not ungrouped,
      f"actions not in .page-actions, so space-between scatters them: "
      f"{', '.join(ungrouped)}")
check('no breadcrumb ends with the words "This record"', not generic_tail,
      f"trail names nothing: {', '.join(generic_tail)}")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
