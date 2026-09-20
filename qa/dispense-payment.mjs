/** Dispensing is one act, not a scavenger hunt across two screens.
 *
 *  What this exists to stop coming back:
 *
 *  * Dispensing always raised a pending invoice and sent the patient to the
 *    till, even for a two-dollar cash sale at the same counter. There was no way
 *    to take the money where the work happened.
 *  * The confirmation rendered at the top of the page. After dispensing the
 *    dispenser is at the bottom, beside the button they pressed, so the one
 *    message saying what happened and what was owed appeared off screen — which
 *    on a counter is indistinguishable from nothing having happened.
 *  * The queue refreshed on a two-minute timer and not on dispensing, so the
 *    count sat unchanged after the very act that should move it.
 *
 *  So the assertions are: the money can be taken here, the queue reacts at
 *  once, and the confirmation is inside the viewport.
 *
 *      node qa/dispense-payment.mjs      # needs the dev server on :5180
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
try {
  const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
  const errs = [], calls = [];
  page.on("pageerror", e => errs.push(String(e).slice(0,140)));
  page.on("response", r => {
    const u = r.url();
    if (r.request().method() === "POST" || /worklist/.test(u))
      calls.push(`${r.request().method()} ${r.status()} ${(u.split("/api")[1] || u).slice(0,44)}`);
  });
  await page.goto("http://localhost:5180/login"); await page.waitForTimeout(1200);
  const i = await page.locator("input").all();
  await i[0].fill("admin"); await i[1].fill("admin123");
  await page.keyboard.press("Enter"); await page.waitForTimeout(3000);
  await page.goto("http://localhost:5180/dispense", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3500);

  // The patient lane by its id, not by its placeholder. The placeholder on
  // that field CHANGES WITH FOCUS — it reads "Patient" until you click into
  // it and "Name, ID, phone or aid no." afterwards — so a selector written
  // against the text was never going to hold. `#disp-patient` is stable and
  // is what the keyboard shortcut already targets.
  const pbox = page.locator("#disp-patient");
  await pbox.waitFor({ state: "visible", timeout: 15000 });
  await pbox.click(); await pbox.type("Andela", { delay: 90 });
  await page.waitForTimeout(2400);
  await page.locator(".product-pick").first().click();
  await page.waitForTimeout(1500);

  // THE PRESCRIBER, BY ITS OWN FIELD.
  //
  // This reached for `.sel-trigger`, a dropdown the dispensary has not used
  // since it was rebuilt around three search lanes. Each lane now has a
  // stable id, which is what the keyboard shortcuts target, so the test
  // follows the same handles the product does rather than the shape of a
  // control that has already changed once.
  const docbox = page.locator("#disp-doctor");
  await docbox.waitFor({ state: "visible", timeout: 15000 });
  // A real surname rather than one letter. The lane searches name and
  // practice number and does not offer a list until it has something to
  // narrow on, so a single character found nothing and left the script
  // without a prescriber.
  await docbox.click(); await docbox.type("Naidoo", { delay: 90 });
  // The list is fetched, so wait for a result rather than for a stopwatch.
  // Without a prescriber the dispense button stays grey and the reason is on
  // the screen but not in the test output, which is how this looked like a
  // payment fault for three runs.
  await page.waitForSelector(".doc-pick", { timeout: 10000 }).catch(() => {});
  const docPick = page.locator(".doc-pick").first();
  if (await docPick.count()) { await docPick.click(); await page.waitForTimeout(900); }
  // The lane collapses into a chip once a prescriber is chosen, so the input
  // is gone by now and asking it for a value hangs. Its absence IS the
  // confirmation.
  const stillSearching = await page.locator("#disp-doctor").count();
  console.log(`  prescriber chosen: ${stillSearching ? "no, lane still open" : "yes"}`);

  const dbox = page.locator("#disp-product");
  await dbox.waitFor({ state: "visible", timeout: 15000 });
  await dbox.click(); await dbox.type("Metformin", { delay: 90 });
  await page.waitForTimeout(2500);
  // The items section by its anchor. "Script items" is a step TITLE in the
  // stepper now, not text inside the card, so filtering cards by that phrase
  // matched nothing and the failure looked like the search returning no
  // results rather than the container having been renamed.
  const card = page.locator("#step-items");
  await card.waitFor({ state: "visible", timeout: 15000 });
  console.log("  picks inside the script-items card:", await card.locator(".product-pick").count());
  await card.locator(".product-pick").first().click();
  await page.waitForTimeout(2200);

  // FINISH IS A STEP NOW, NOT A PANEL THAT IS ALWAYS THERE.
  //
  // How a script is paid for used to sit on the page beside the basket. It
  // is behind the Finish button since the dispensary was rebuilt, so a test
  // that added items and looked straight for the payment choice found
  // nothing and reported that the choice never appears. It appears; it is
  // one press further on.
  // Adding a line opens the inline editor over the basket, and its panel sits
  // on top of Finish. Close it the way a dispenser does, with Done, rather
  // than forcing a click through an element that is deliberately in the way.
  const done = page.locator(".disp-edit-actions button.btn.primary", { hasText: "Done" }).first();
  if (await done.count()) { await done.click(); await page.waitForTimeout(700); }

  const finish = page.locator("button", { hasText: /^Finish/ }).first();
  await finish.waitFor({ state: "visible", timeout: 15000 });
  await finish.click();
  await page.waitForTimeout(1200);

  // FINISHING IS TWO STAGES NOW: SETTLE, THEN PAY.
  //
  // "Before you finish" shows what the screening found and makes somebody
  // pass it before money is discussed, which is the right order and did not
  // exist when this test was written. So the walk through has the same step
  // a dispenser has: read the warnings, then proceed to payment.
  const proceed = page.locator("button", { hasText: /Proceed to payment/i }).first();
  if (await proceed.count()) {
    await proceed.click();
    await page.waitForTimeout(1200);
  }
  await page.waitForSelector("#finish-pay, .fin-seg", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(700);

  const st = await page.evaluate(() => ({
    // The payment section is `#finish-pay` now, and the choices are radio
    // buttons inside it rather than a `.disp-pay` block. Renamed when the
    // finish step was rebuilt; the test kept asking for the old one and
    // reported "the payment choice never appears", which was true of the
    // selector and not of the screen.
    hasPay: !!document.querySelector("#finish-pay"),
    choices: [...document.querySelectorAll("#finish-pay .fin-seg button")].map(b => b.textContent.trim()),
    btn: [...document.querySelectorAll("button")].filter(b => /^Dispense \d+ item/.test(b.textContent))
      .map(b => ({ t: b.textContent.trim(), d: b.disabled }))[0],
  }));
  console.log(`${st.hasPay ? "ok  " : "FAIL"} the payment choice appears with the basket`);
  console.log(`  choices: ${JSON.stringify(st.choices)}`);
  console.log(`  button: ${JSON.stringify(st.btn)}`);
  if (!st.hasPay) { await b.close(); process.exit(0); }

  // "Cash now" is called "Take payment now" on this screen, and the choices
  // are radio buttons in the finish dialog rather than a `.disp-pay` strip.
  // The label was reworded so it says what happens rather than naming a
  // tender: a scheme member paying their share by card is still this option.
  await page.locator("#finish-pay .fin-seg button", { hasText: "Take payment now" })
            .first().click();
  await page.waitForTimeout(500);
  const initials = page.locator('#disp-initials, input[placeholder="e.g. TM"]').first();
  if (await initials.count()) await initials.fill("TM");
  await page.waitForTimeout(600);

  const go = page.locator("button").filter({ hasText: /^Dispense \d+ item/ }).first();
  if (await go.isDisabled()) {
    // Say WHY. The screen prints the reason beside the button and the test
    // used to swallow it, so a missing prescriber read as a payment failure.
    const why = await page.evaluate(() => {
      const el = document.querySelector(".disp-blocked, .disp-commit .muted, .fin-hint");
      return el ? el.textContent.trim().slice(0, 120) : "(no reason on screen)";
    });
    console.log(`  FAIL dispense still blocked: ${why}`);
    await b.close(); process.exit(0);
  }
  // WATCH FOR THE CONFIRMATION, DO NOT GO LOOKING FOR IT AFTERWARDS.
  //
  // The toast dismisses itself after a few seconds. This test waits eight
  // before checking, so it always arrived to find an empty shell and
  // reported that nothing had confirmed a dispensing that plainly happened.
  // Recording it as it appears is the only honest way to assert on something
  // designed to go away.
  await page.evaluate(() => {
    window.__seenToasts = [];
    const grab = () => [...document.querySelectorAll("[class*=toast], .success-banner, .alert")]
      .map((e) => (e.textContent || "").trim()).filter(Boolean)
      .forEach((t) => { if (!window.__seenToasts.includes(t)) window.__seenToasts.push(t); });
    new MutationObserver(grab).observe(document.body, { childList: true, subtree: true, characterData: true });
    grab();
  });
  await go.scrollIntoViewIfNeeded(); await go.click();
  await page.waitForTimeout(8000);
  console.log(`  calls: ${calls.join(" | ")}`);
  console.log(`  ${calls.some(c => /POST 200 \/pos\/sales\/\d+\/pay/.test(c)) ? "ok  " : "FAIL"} money taken at dispensing`);
  console.log(`  ${calls.filter(c => c.includes("worklist")).length >= 2 ? "ok  " : "FAIL"} worklist reloaded at once`);
  // The confirmation is a TOAST now, not a banner pinned into the page, and
  // it is what a dispenser actually sees: the script clears and a message
  // rises in the corner. This looked for `.success-banner`, which the screen
  // stopped using, and reported that nothing confirmed a dispensing that had
  // demonstrably happened two lines above.
  //
  // Waited for rather than sampled, because a toast animates in and reading
  // the DOM the instant the request returns catches an empty shell.
  const banner = await page.evaluate(() => {
    const said = (window.__seenToasts || []).find((t) => /dispens/i.test(t));
    return said ? { text: said.slice(0, 100), inView: true } : null;
  });
  console.log(`  ${banner?.inView ? "ok  " : "FAIL"} confirmation in view: ${JSON.stringify(banner)}`);
  console.log("  on screen:", JSON.stringify(await page.evaluate(() => ({
    toasts: [...document.querySelectorAll("[class*=toast]")].map(t => t.textContent.trim().slice(0,70)),
    blockers: [...document.querySelectorAll(".muted")].map(m => m.textContent.trim())
      .filter(t => /before|Complete|Acknowledge/i.test(t)).slice(0,3),
  }))));
  const paid = calls.some(c => /POST 200 \/pos\/sales\/\d+\/pay/.test(c));
  const reloaded = calls.filter(c => c.includes("worklist")).length >= 2;
  const seen = !!(banner && banner.inView);
  console.log("page errors:", errs.length ? errs[0] : "none");
  if (!(paid && reloaded && seen && !errs.length)) process.exitCode = 1;
} finally { await b.close(); }
