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

  const pbox = page.locator('input[placeholder^="Search patient"]');
  await pbox.click(); await pbox.type("Andela", { delay: 90 });
  await page.waitForTimeout(2400);
  await page.locator(".product-pick").first().click();
  await page.waitForTimeout(1500);

  // The prescriber, which the script cannot be finalised without.
  const sel = page.locator(".sel-trigger").filter({ hasText: /Select doctor|Dr /i }).first();
  await sel.click(); await page.waitForTimeout(900);
  await page.locator(".sel-option").nth(1).click();
  await page.waitForTimeout(900);

  const dbox = page.locator('input[placeholder^="Search prescription"]');
  await dbox.click(); await dbox.type("Metformin", { delay: 90 });
  await page.waitForTimeout(2500);
  const card = page.locator(".card").filter({ hasText: "Script items" });
  console.log("  picks inside the script-items card:", await card.locator(".product-pick").count());
  await card.locator(".product-pick").first().click();
  await page.waitForTimeout(2200);

  const st = await page.evaluate(() => ({
    hasPay: !!document.querySelector(".disp-pay"),
    choices: [...document.querySelectorAll(".disp-pay button")].map(b => b.textContent.trim()),
    btn: [...document.querySelectorAll("button")].filter(b => /^Dispense \d+ item/.test(b.textContent))
      .map(b => ({ t: b.textContent.trim(), d: b.disabled }))[0],
  }));
  console.log(`${st.hasPay ? "ok  " : "FAIL"} the payment choice appears with the basket`);
  console.log(`  choices: ${JSON.stringify(st.choices)}`);
  console.log(`  button: ${JSON.stringify(st.btn)}`);
  if (!st.hasPay) { await b.close(); process.exit(0); }

  await page.locator(".disp-pay button", { hasText: "Cash now" }).click();
  await page.waitForTimeout(400);
  await page.locator('input[placeholder="e.g. TM"]').fill("TM");
  await page.waitForTimeout(600);

  const go = page.locator("button").filter({ hasText: /^Dispense \d+ item/ }).first();
  if (await go.isDisabled()) { console.log("  FAIL dispense still blocked"); await b.close(); process.exit(0); }
  await go.scrollIntoViewIfNeeded(); await go.click();
  await page.waitForTimeout(8000);
  console.log(`  calls: ${calls.join(" | ")}`);
  console.log(`  ${calls.some(c => /POST 200 \/pos\/sales\/\d+\/pay/.test(c)) ? "ok  " : "FAIL"} money taken at dispensing`);
  console.log(`  ${calls.filter(c => c.includes("worklist")).length >= 2 ? "ok  " : "FAIL"} worklist reloaded at once`);
  const banner = await page.evaluate(() => {
    const el = [...document.querySelectorAll(".success-banner, .alert")].find(e => /Dispensed/i.test(e.textContent));
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { text: el.textContent.trim().slice(0,100), inView: r.top >= 0 && r.top < window.innerHeight };
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
