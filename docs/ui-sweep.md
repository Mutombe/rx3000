# The UI sweep: what was wrong, and how a clean report can lie

## The first version of this audit was worthless, and said "0 faults"

Two reasons, both worth writing down because they are the general case.

**It audited pages that do not exist.** The route list was written from memory:
`/dispensary`, `/prescriptions`, `/suppliers`, `/claims`, `/customers`,
`/campaigns`, `/settings`. None of them are routes. The router mounts
`/dispense`, `/stock`, `/contacts/:id`, `/marketing`, `/system`. Every one of
those invented paths fell through to the dashboard, which is clean — so the
audit measured the dashboard twenty-nine times and reported the application
healthy while the dispensary was visibly broken.

*The guard:* `ROUTES` now comes from `App.tsx`, and any route whose heading
matches the dashboard's is reported as `fellThroughToDashboard` — a failure, not
a silent pass.

**It only ever opened the first tab.** A tabbed page shows one panel by default,
and that is the one the audit measured — every time, on every page. On Deliveries
the default tab is "To go out", which held **zero rows**; the failure reasons live
on "Failed", which held fourteen and had a cell painting straight off the edge of
its table onto the page background. The default tab is a sample of one, and often
the emptiest one.

*The guard:* every `.pill-tabs button` / `[role=tab]` on a route is clicked and
audited. The matrix is routes x tabs x widths.

**It only measured 1280px.** A laptop at a high device-pixel ratio has far fewer
CSS pixels than its screenshots suggest. Every fault below is invisible at 1280
and severe at 900–1230.

*The guard:* `WIDTHS = [900, 1100, 1280, 1440, 1680]`. 165 checks, not 29.

## The faults, once it was actually looking

| | |
|---|---|
| **Tables had no floor** | A fixed-layout table with no `min-width` squeezes to whatever it is given. At 900px one compressed to 578px, handing each column 60px, and "TOFOLLOW Probe Syrup" became a five-line tower. 400 such cells on one page. |
| **`text-overflow: ellipsis` on wrapping text** | Ellipsis only ever truncates a single line. Cells declared they would clip and then stacked instead. It does nothing without `white-space: nowrap`. |
| **The guard only covered `.dt`** | Twelve hand-written tables were in no scroll container at all. A guard that covers the components you remembered is not a guard. |
| **The dispensary crushed its own middle column** | `.cols-2` nested inside a grid that already reserves 320px for the worklist: the remainder was split again, leaving ~215px. A repeat line rendered as "Tramadol / 50mg" over "02 / Sept, / 2026" with the Dispense button sliced off. |
| **The two headers were never aligned** | The brand block and the top bar had independent paddings — 77px against 65px — so their bottom borders met the sidebar's edge twelve pixels apart. |
| **Avatars were white on pale** | `hsl(h 42% 78%)` under white text is about 1.7:1. |
| **7,001 reminders behind a cap of 200** | Rendered in full, with nothing on screen saying what was not shown. |
| **A cell painted outside its own table** | The action column had `overflow: visible` so buttons would never be sliced. On Deliveries that column carries a button on rows still out and the failure reason on rows that came back — so "Nobody home, gate locked" ran past the table's white background and onto the page. `overflow: visible` was the wrong tool: it stops a clip by removing the boundary. The column is now sized for what it holds and clips anything beyond, and a new check fails any cell whose box escapes its table. |

## Five measurement bugs, all mine, all the same mistake

Each of these produced a confident number about code that was fine. The pattern
is identical every time: **measuring the DOM instead of what is actually
painted.**

1. **Contrast read 1.05 on legible text.** The luminance function took the first
   three numbers of `rgba(22,22,29,0.06)` and ignored the alpha, treating a 6%
   tint as near-black.
2. **Contrast read 1.0 on gradient-filled avatars.** Only `background-color` was
   read; a gradient reports `rgba(0,0,0,0)`, so it fell through to the white card
   behind. (The avatars *were* wrong — at 1.7:1, not 1.0.)
3. **Contrast read 2.34 on chart labels.** They are positioned `top: -20px`,
   outside their bar, and painted on the card — but the DOM ancestry said dark
   bar. Ancestors are now only counted when their box is genuinely behind the
   element.
4. **"400 crushed cells" from row height.** A cell's height is its *row's*
   height, set by the tallest cell in it, so one stacked cell made every plain
   cell beside it look crushed. Then counting `getClientRects()` was wrong too —
   one rect per text box, so adjacent text nodes on the same line each count.
   Lines are **distinct top offsets**.
5. **A blanket assumption about markup.** Converting every trailing `<th />` to
   `className="actions"` assumed an empty last header always means buttons. On
   Deliveries it meant the outcome column, which then inherited the action
   column's width and overflow rules — and that is what put the failure reason
   outside the table. A mechanical edit across twelve files needs each site
   checked, not the pattern assumed.
6. **"Sliced buttons" that were reachable.** The walk up the ancestry skipped
   `overflow: auto` boxes and kept going until it found `.shell`'s
   `overflow: hidden` — reporting a scrollable table's buttons as severed. A
   scrollable ancestor ends the search.

**A measurement that has not been checked against the pixels is a claim, not a
result.** Every fix above was confirmed by looking at a screenshot afterwards.

## What tab coverage found the moment it was switched on

Adding tabs took the matrix from 165 checks to 420 and immediately surfaced
faults on panels nothing had ever opened:

- **The controlled-drugs register showed 200 of 423 hand-overs**, with nothing on
  screen saying so. Of every list in this application that is the one where a
  silent cap is indefensible — it is the list an inspector reads. Now paged, and
  the screen states the true total.
- **The pharmacy-medicine (S1/S2) register** dumped 92 rows with no pager.
- **Campaign history** dumped 91.
- **A lay-by reference** was clipped by 29px, losing the end of the number that
  identifies it.
- **Stock valuation rendered 433 lines**, and the **reorder sheet 104**, neither
  with a pager. Both endpoints deliberately return everything — a valuation has
  to sum every line to state a total, a reorder sheet has to know the whole
  shortfall before anyone buys — so the fix was `useClientPage`, which bounds the
  *render* and leaves the data whole. The totals beside them are still computed
  over the full array: paging to the next page leaves "$7,424,059.45" exactly
  where it was, which is the property worth testing and the one that is easy to
  break.

## Running it

    node qa/layout-audit.mjs        # app on 5180

The full matrix takes long enough to outlive some runners, so it splits:

    AUDIT_WIDTHS=900,1100  node qa/layout-audit.mjs
    AUDIT_WIDTHS=1280,1440 node qa/layout-audit.mjs
    AUDIT_WIDTHS=1680      node qa/layout-audit.mjs

Current state: **420 checks (33 routes x their tabs x 5 widths), 0 faults**, and
backend smoke at 135 GET endpoints, 0 failing. That number is only worth anything
because the route list is now real and the widths are the ones people use.
