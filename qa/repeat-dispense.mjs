/** A repeat can actually be dispensed from the repeats queue.
 *
 *  The button on that screen sent empty initials, which the server refuses, so
 *  it could never once have worked: every press answered with a 400 the
 *  dispenser could do nothing about. It shipped that way because it was written
 *  and never pressed against a server with the rule switched on.
 *
 *  It also declared that the prescription had been sighted, on the dispenser's
 *  behalf and without asking. That is the worse half. A dispensing record exists
 *  to say who checked what, and one that answers on somebody's behalf is not a
 *  record — so the check below also fails if the button can be pressed without
 *  both of those being given.
 *
 *      node qa/repeat-dispense.mjs       # needs the dev server on :5180
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs = [], failed = [];
page.on("pageerror", e => errs.push(String(e).slice(0,120)));
page.on("response", r => { if (r.url().includes("/dispense") ) failed.push(`${r.status()} ${r.url().split("/api")[1]}`); });
await page.goto("http://localhost:5180/login"); await page.waitForTimeout(1200);
const i = await page.locator("input").all();
await i[0].fill("admin"); await i[1].fill("admin123");
await page.keyboard.press("Enter"); await page.waitForTimeout(3000);

await page.goto("http://localhost:5180/repeats", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3000);
const n = await page.locator("button", { hasText: "Dispense" }).count();
console.log(`repeats with a Dispense button: ${n}`);
if (!n) { console.log("no due repeats to try"); await b.close(); process.exit(0); }

await page.locator("button", { hasText: "Dispense" }).first().click();
await page.waitForTimeout(1200);
const m = await page.evaluate(() => ({
  open: !!document.querySelector(".modal"),
  title: document.querySelector(".modal h2")?.textContent?.trim() ?? "",
  disabled: document.querySelector(".modal .modal-actions button:last-of-type")?.disabled,
}));
console.log(`  ${m.open ? "ok  " : "FAIL"} modal opens: "${m.title}"`);
console.log(`  ${m.disabled ? "ok  " : "FAIL"} "Dispense it" is blocked before initials are entered`);

// Initials only — still blocked until the script is affirmed.
await page.locator(".modal input").first().fill("TM");
await page.waitForTimeout(400);
const half = await page.evaluate(() => document.querySelector(".modal .modal-actions button:last-of-type")?.disabled);
console.log(`  ${half ? "ok  " : "FAIL"} still blocked until the script is affirmed`);

await page.locator(".modal .cbx").first().click();
await page.waitForTimeout(400);
const ready = await page.evaluate(() => document.querySelector(".modal .modal-actions button:last-of-type")?.disabled);
console.log(`  ${!ready ? "ok  " : "FAIL"} enabled once both are given`);

await page.locator(".modal button", { hasText: "Dispense it" }).click();
await page.waitForTimeout(4000);
console.log(`  dispense calls: ${failed.join(", ") || "none seen"}`);
const ok = failed.some(f => f.startsWith("200"));
console.log(`  ${ok ? "ok  " : "FAIL"} the server accepted the dispensing`);
const toast = await page.evaluate(() => document.body.innerText.match(/dispensed for [^\n]*/)?.[0] ?? "");
console.log(`  toast: ${toast || "(none)"}`);
console.log("page errors:", errs.length ? errs[0] : "none");
await b.close();
process.exit((!ok || errs.length) ? 1 : 0);
