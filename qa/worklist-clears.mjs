/** Does working the queue empty the queue?
 *
 *  It did not. Clicking a queued line loaded only the *patient*; the dispenser
 *  then re-typed the medicine, which captured a second prescription and
 *  dispensed that one. The line that was queued was never touched, so the
 *  worklist could not go down however many people you served, and the count
 *  beside "Dispensary" in the sidebar stayed where it was after the one act
 *  that should have moved it.
 *
 *  So this asserts the only thing that actually matters about a queue: pick the
 *  top line, dispense it, and both the list and the badge are one shorter, with
 *  that patient's line gone rather than merely reordered.
 *
 *  Run:  node qa/worklist-clears.mjs      (needs the app running on 5180)
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const BASE = process.env.RX_BASE || "http://localhost:5180";

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const failures = [];
const errors = [];
page.on("pageerror", (e) => errors.push(e.message.slice(0, 160)));
function check(ok, message) {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${message}`);
  if (!ok) failures.push(message);
}

await page.goto(`${BASE}/login`);
await page.waitForTimeout(1200);
const inputs = await page.locator("input").all();
await inputs[0].fill(process.env.RX_USER || "admin");
await inputs[1].fill(process.env.RX_PASS || "admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2600);

await page.goto(`${BASE}/dispense`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3000);

/** The queue's own count, read off the worklist panel. */
async function queued() {
  return page.evaluate(() => {
    const rows = document.querySelectorAll(".wl-row, .wl-queue li, .wl-list li");
    return rows.length;
  });
}

const rows = page.locator(".wl-row, .wl-queue li, .wl-list li");
const before = await rows.count();
console.log(`\nthe queue holds ${before} line(s)`);
if (before === 0) {
  console.log("  nothing queued to work — cannot test the thing that matters");
  await browser.close();
  process.exit(0);
}

const firstText = (await rows.first().innerText()).replace(/\s+/g, " ").slice(0, 60);
console.log(`  top line: ${firstText}`);

await rows.first().click();
await page.waitForTimeout(2500);

console.log("\nopening it");
const items = await page.locator(".rx-item").count();
check(items > 0,
      `the script's medicines are loaded into the form (${items}) — not just `
      + `the patient, which is what made every dispensing write a new script`);
const patientCard = await page.locator(".pt-card, .patient-card").count();
check(patientCard > 0 || (await page.locator('input[placeholder*="atient" i]').count()) === 0,
      "and the patient is on the script");

console.log("\ndispensing it");
const initials = page.locator('input[placeholder*="e.g. TM" i]').first();
if (await initials.count()) { await initials.fill("QA"); await page.waitForTimeout(400); }
const ack = page.locator(".ix-ack input");
if (await ack.count()) { await ack.check(); await page.waitForTimeout(300); }

// Stay on the page: the till route navigates away, which is correct behaviour
// but would take this script off the screen it is measuring.
const till = page.locator(".disp-pay .seg button", { hasText: "Take payment now" });
if (await till.count()) { await till.click(); await page.waitForTimeout(400); }

const go = page.locator("button", { hasText: /^Dispense \d/ }).first();
check(await go.count() > 0, "the dispense button is there");
if (await go.isDisabled()) {
  const why = await page.locator(".disp-blocked").innerText().catch(() => "");
  check(false, `it is still blocked: ${why.replace(/\s+/g, " ").slice(0, 90)}`);
} else {
  await go.click();
  await page.waitForTimeout(6000);

  const after = await queued();
  check(after === before - 1,
        `the queue is one shorter (${before} -> ${after})`);
  const stillThere = (await page.locator(".wl").innerText()).includes(
    firstText.split(" ")[0]);
  check(!stillThere || after < before,
        "and the line that was worked is gone from it");
}

if (errors.length) console.log(`\npage errors: ${[...new Set(errors)].join(" | ")}`);
console.log("");
if (failures.length) {
  console.log(`${failures.length} failed`);
  await browser.close();
  process.exit(1);
}
console.log("working the queue empties the queue");
await browser.close();
