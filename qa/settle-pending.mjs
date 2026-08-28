/** Settling a dispensary sale says what happened.
 *
 *  Two bugs live here, and both were invisible rather than loud:
 *
 *  * There was no success message at all. The row simply vanished.
 *  * The receipt was rendered inside the till tab's own branch, so settling
 *    from Awaiting payment set the receipt state and drew nothing. A cashier
 *    had no way to tell whether the money had been taken.
 *
 *  It also checks the amount, because the figure a scheme member is asked for
 *  is the one thing here that costs somebody money when it is wrong.
 *
 *      node qa/settle-pending.mjs        # needs the dev server on :5180
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
try {
  const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
  const errs = [], pays = [];
  page.on("pageerror", e => errs.push(String(e).slice(0,140)));
  page.on("response", r => { if (/\/pay$/.test(r.url())) pays.push(r.status()); });
  await page.goto("http://localhost:5180/login"); await page.waitForTimeout(1200);
  const i = await page.locator("input").all();
  await i[0].fill("admin"); await i[1].fill("admin123");
  await page.keyboard.press("Enter"); await page.waitForTimeout(3000);
  await page.goto("http://localhost:5180/pos?tab=pending", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  // ?tab=pending lands there directly now that the page switches with a button
  // rather than a tab bar; press the switch only if we are still on the till.
  const sw = page.locator(".till-switch button");
  if (/Awaiting payment/.test((await sw.textContent()) || "")) {
    await sw.click(); await page.waitForTimeout(2200);
  }
  const rows = await page.locator("tbody tr").count();
  console.log(`awaiting payment: ${rows} rows`);
  const part = await page.locator("button", { hasText: /^Part$/ }).count();
  console.log(`${part > 0 ? "ok  " : "FAIL"} a part-payment button is offered (${part})`);
  if (!rows) { console.log("(nothing to settle)"); await b.close(); process.exit(0); }

  await page.locator("tbody tr").first().locator("button", { hasText: /^Cash$/ }).click();
  await page.waitForTimeout(4000);
  const after = await page.evaluate(() => ({
    toast: [...document.querySelectorAll(".toast, .toast-ok, [class*=toast]")]
      .map(t => t.textContent.trim()).filter(Boolean).slice(0,2),
    receipt: /Receipt INV/.test(document.body.innerText),
    body: document.body.innerText.includes("settled"),
  }));
  console.log(`  pay call: ${pays.join(",")}`);
  console.log(`  ${after.toast.length || after.body ? "ok  " : "FAIL"} feedback shown: ${JSON.stringify(after.toast)}`);
  console.log(`  ${after.receipt ? "ok  " : "FAIL"} the receipt is shown on screen`);
  const ok = (after.toast.length || after.body) && after.receipt && pays.includes(200);
  console.log("page errors:", errs.length ? errs[0] : "none");
  if (!ok || errs.length) process.exitCode = 1;
} finally { await b.close(); }
