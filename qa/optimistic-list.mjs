/** Does the list show what you did before the server has agreed to it?
 *
 *  And, the half that actually matters, does it put things back when the
 *  server refuses? An optimistic UI that only works when everything succeeds is
 *  not an optimistic UI, it is a lie with good timing.
 *
 *  Three things are asserted against the real screen, with the network under
 *  this script's control:
 *
 *    1. The dialog closes at once and the row is on screen before the response,
 *       drawn in a state that reads as provisional.
 *    2. A placeholder offers no actions. It has no real id yet, and a control
 *       that acts on one acts on the wrong record.
 *    3. A refusal takes the row away again and says why, leaving the rest of
 *       the list exactly as it was.
 *
 *  Run:  node qa/optimistic-list.mjs      (needs the app running on 5180)
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const BASE = process.env.RX_BASE || "http://localhost:5180";

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const failures = [];
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

async function openForm(name) {
  await page.locator("button", { hasText: "New department" }).first().click();
  await page.waitForTimeout(400);
  await page.locator('.modal input[placeholder*="Dispensary" i]').fill(name);
}

// ---------------------------------------------------------------- the happy way
console.log("\na department the server accepts");
await page.goto(`${BASE}/stock-categories`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1800);
const before = await page.locator(".dt tbody tr").count();

// Held open for a second so the optimistic state can be observed at all. This
// is the whole point: without the delay the answer arrives too fast to see,
// and the test would pass on a screen that had no optimistic behaviour.
await page.route("**/api/stock-categories", async (route) => {
  if (route.request().method() !== "POST") return route.continue();
  await new Promise((r) => setTimeout(r, 1200));
  return route.continue();
});

const NAME = `Veterinary ${Date.now().toString().slice(-6)}`;
await openForm(NAME);
await page.locator(".modal button", { hasText: "Add it" }).click();
await page.waitForTimeout(300);

check(await page.locator(".modal").count() === 0,
      "the dialog closed at once rather than waiting on the server");
const pendingRow = page.locator(".dt tbody tr.row-creating");
check(await pendingRow.count() === 1,
      "the row is already on screen, marked as still saving");
check((await page.locator(".dt tbody tr").first().innerText()).includes(NAME),
      "and it is at the top, where what you just did belongs");
check(await pendingRow.locator(".actions button").count() === 0,
      "it offers no actions while it has no real id");

await page.waitForTimeout(2600);
check(await page.locator(".dt tbody tr.row-creating").count() === 0,
      "once confirmed it settles into an ordinary row");
const after = await page.locator(".dt tbody tr").count();
check(after === before + 1, `the list grew by one (${before} -> ${after})`);
check(await page.locator(".toast, .toasts").filter({ hasText: NAME }).count() > 0
      || (await page.content()).includes("added."),
      "and it said so");

// ------------------------------------------------------------- the refusal
console.log("\na department the server refuses");
await page.unroute("**/api/stock-categories");
await page.goto(`${BASE}/stock-categories`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1800);
const held = await page.locator(".dt tbody tr").count();

await page.route("**/api/stock-categories", async (route) => {
  if (route.request().method() !== "POST") return route.continue();
  await new Promise((r) => setTimeout(r, 600));
  return route.fulfill({
    status: 400, contentType: "application/json",
    body: JSON.stringify({ detail: "A department with that code already exists." }),
  });
});

await openForm("Doomed department");
await page.locator(".modal button", { hasText: "Add it" }).click();
await page.waitForTimeout(250);
check(await page.locator(".dt tbody tr.row-creating").count() === 1,
      "it appears optimistically, the same as any other");

await page.waitForTimeout(1800);
const rolled = await page.locator(".dt tbody tr").count();
check(rolled === held,
      `the row was taken back (${held} before, ${rolled} after)`);
check(!(await page.locator(".dt tbody").innerText()).includes("Doomed"),
      "and it is not left behind anywhere in the list");
const body = await page.content();
check(body.includes("already exists"),
      "the server's own reason is shown, not a generic failure");

await page.unroute("**/api/stock-categories");
console.log("");
if (failures.length) {
  console.log(`${failures.length} failed`);
  await browser.close();
  process.exit(1);
}
console.log("the list shows what you did, and takes it back when it must");
await browser.close();
