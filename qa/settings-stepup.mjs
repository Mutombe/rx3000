/** End-to-end for the global settings screen and the step-up chain behind it.
 *
 *  What this is actually testing is not "does the form render" but the sequence
 *  that has no other way of being checked: save → server answers 428 → the
 *  dialog appears with the server's own wording → password → the save retries
 *  and reports success. A typecheck cannot see any of that.
 *
 *  Past failures this guards against, all of which passed a build:
 *    - the component asked the server with POST when the route is PUT (405)
 *    - the cancel path never settled its promise, so Save stuck on "Saving…"
 *    - the dialog was rebuilt from scratch and lost the supervisor-override flow
 */
export default async function run(page, ui) {
  const out = { steps: [] };
  const say = (s, d) => out.steps.push({ [s]: d });

  // ---- sign in -------------------------------------------------------------
  // The sign-in button is not a type=submit, so selecting on that matched
  // nothing and the run died 30s later with a timeout that read like a hang.
  // Driving from what the snapshot actually lists instead.
  await page.locator("input").first().fill("admin");
  await page.locator('input[type="password"]').first().fill("admin123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(3000);
  say("signedIn", !/login/i.test(await page.locator("body").innerText()));

  // ---- the settings tab ----------------------------------------------------
  await page.goto("http://localhost:5180/admin?tab=settings");
  await page.waitForTimeout(600);
  // Wait for content, not a fixed delay: a slow render and a broken one look
  // identical otherwise.
  await page.waitForSelector(".gs-row", { timeout: 15000 }).catch(() => {});

  const rows = await page.locator(".gs-row").count();
  const effects = await page.locator(".gs-effect").count();
  say("rowsRendered", rows);
  say("effectsRendered", effects);

  // Every row must explain what it does. An effect line that renders empty is
  // the whole point of the screen going missing.
  const emptyEffects = await page.locator(".gs-effect").evaluateAll(
    (ns) => ns.filter((n) => !n.textContent.trim()).length,
  );
  say("emptyEffectLines", emptyEffects);

  // Nothing may overflow its row — the report-card overflow bug was found only
  // from a screenshot, so it is measured here instead.
  const overflow = await page.locator(".gs-row").evaluateAll((ns) =>
    ns.filter((n) => n.scrollWidth > n.clientWidth + 1).length);
  say("rowsOverflowing", overflow);

  if (!rows) return { ...out, error: "no settings rows", snapshot: await ui.snapshot() };

  // ---- change a value and save --------------------------------------------
  const numeric = page.locator('.gs-row input[type="number"]').first();
  await numeric.scrollIntoViewIfNeeded().catch(() => {});
  if (!(await numeric.count())) return { ...out, error: "no numeric setting to edit" };

  const before = await numeric.inputValue();
  const next = String(Number(before || 0) + 1);
  await numeric.fill(next);

  // Filtering `.gs-row` by a locator that was itself scoped to `.gs-row input`
  // asks for a row inside a row and matches nothing — which surfaced as a 30s
  // timeout rather than "no such element", so it read like a hung page.
  const row = page.locator(".gs-row").filter({
    has: page.locator('input[type="number"]'),
  }).first();
  const saveBtn = row.getByRole("button", { name: /sav/i }).first();
  say("saveEnabledOnlyWhenDirty", await saveBtn.isEnabled());
  await saveBtn.click();
  await page.waitForTimeout(1800);

  // ---- the dialog ----------------------------------------------------------
  const dialogUp = await page.locator(".modal").count();
  const heading = dialogUp ? await page.locator(".modal h2").first().innerText() : "";
  const why = dialogUp ? await page.locator(".modal .muted").first().innerText() : "";
  say("stepUpAppeared", !!dialogUp);
  say("stepUpHeading", heading);
  // The reason must come from the server's declaration, not be hard-coded here.
  say("whyFromServer", /whole system|every transaction/i.test(why));

  if (!dialogUp) {
    return { ...out, error: "no step-up dialog after saving a guarded setting" };
  }

  // ---- cancel must release the button -------------------------------------
  await page.locator(".modal button", { hasText: /cancel/i }).first().click();
  await page.waitForTimeout(700);
  const stuck = await row.locator("button", { hasText: /saving/i }).count();
  say("saveStuckAfterCancel", !!stuck);   // must be false
  say("dialogClosedOnCancel", (await page.locator(".modal").count()) === 0);

  // ---- and now actually authorise -----------------------------------------
  await saveBtn.click();
  await page.waitForTimeout(1500);
  const pw = page.locator('.modal input[type="password"]').first();
  if (!(await pw.count())) return { ...out, error: "no password field in dialog" };
  await pw.fill("admin123");
  await page.locator('.modal button[type="submit"]').first().click();
  await page.waitForTimeout(2500);

  say("dialogClosedAfterGrant", (await page.locator(".modal").count()) === 0);
  const toast = await page.locator(".toast, [class*=toast]").allInnerTexts().catch(() => []);
  say("toast", toast.join(" | ").slice(0, 200));

  // The value must have actually changed on the server, not just on screen.
  await page.reload();
  await page.waitForSelector(".gs-row", { timeout: 15000 }).catch(() => {});
  const after = await page.locator('.gs-row input[type="number"]').first().inputValue();
  say("persisted", { before, wanted: next, after, ok: after === next });

  return out;
}
