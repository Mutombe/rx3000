/** Open every report in the catalogue and check each one actually ran.
 *
 *  Run with the browser-automation skill:
 *
 *      node <skill-dir>/browser.mjs http://localhost:5180 --script qa/reports-sweep.mjs
 *
 *  ---
 *
 *  Two things about this file are worth reading before changing it, because
 *  both were learned the hard way.
 *
 *  **It matches on the title element, not on the catalogue card.** A card
 *  contains the report's name *and* its purpose sentence, and one report's
 *  purpose mentions another report's name — "products with no cost price…
 *  quietly distort stock valuation". A `hasText` match on the card therefore
 *  matched two cards, `.first()` opened the wrong one, and the sweep printed
 *  that report's footer under a different report's heading. It reported
 *  `broken: []` with no console errors while silently checking the wrong thing.
 *
 *  **It waits for the requested report to be open, not for a table to exist.**
 *  Waiting for `.rr-table` passes the moment *any* table renders, including the
 *  wrong report's. The wait here is on the title matching what was asked for,
 *  so opening the wrong report is a failure rather than a pass.
 *
 *  A verification tool that can quietly check the wrong thing is worse than no
 *  verification, because it launders a guess into a fact.
 */
export default async function run(page, ui) {
  const out = { ran: [], broken: [] };

  const snap = await ui.snapshot();
  const user = snap.match(/@(e\d+) textbox/)?.[1];
  if (!user) return { error: "no sign-in field", snapshot: snap.slice(0, 600) };
  await ui.fill(user, "admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(3500);

  await page.goto("http://localhost:5180/reports");
  await page.waitForSelector(".rc-item", { timeout: 20000 });
  out.total = await page.locator(".rc-item").count();

  // What the server is actually serving, against what the source declares. A
  // sweep of a stale process reports "60 ran, 0 broken, of 60" — internally
  // consistent, entirely wrong, and indistinguishable from success. The server
  // holds the catalogue in memory, so a report added since the last restart is
  // invisible to it and to this.
  out.headingSays = await page.locator(".rc-head h3").innerText().catch(() => "");
  const declared = Number((out.headingSays.match(/^(\d+)/) || [])[1] || 0);
  if (declared && declared !== out.total) {
    out.broken.push({
      title: "(catalogue)",
      why: `the page says ${declared} reports but ${out.total} cards rendered`,
    });
  }

  // The manager badge is part of the title cell but not part of the name.
  const titles = (await page.locator(".rc-item-title").allInnerTexts())
    .map((t) => t.replace(/\s*manager\s*$/i, "").trim())
    .filter(Boolean);

  for (const title of titles) {
    await page.goto("http://localhost:5180/reports");
    await page.waitForSelector(".rc-item", { timeout: 15000 });
    await page.locator(".rc-item-title").filter({ hasText: title }).first().click();

    const opened = await page
      .waitForFunction(
        (t) => document.querySelector(".rr-title")?.textContent?.trim() === t,
        title,
        { timeout: 15000 },
      )
      .then(() => true)
      .catch(() => false);

    if (!opened) {
      out.broken.push({ title, why: "opened a different report, or never loaded" });
      continue;
    }

    // Let the fetch settle before judging what is on screen.
    await page.waitForTimeout(1200);
    const toasts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".toast")).map((t) => t.textContent.trim()));
    const table = await page.locator(".rr-table").count();
    const empty = await page.locator(".empty").count();

    // A toast on a report screen is an error; a report with neither a table nor
    // an empty state has not finished, whatever it looks like.
    if (toasts.length || (!table && !empty)) {
      out.broken.push({ title, toasts, table, empty });
      continue;
    }

    const foot = await page.locator(".rr-table tfoot").innerText().catch(() => "");
    out.ran.push(`${title} :: ${foot.split("\n")[0] || "(no rows)"}`);
  }

  out.summary = `${out.ran.length} ran, ${out.broken.length} broken, of ${out.total}`;
  return out;
}
