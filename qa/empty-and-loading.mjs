/** Empty states and skeletons, on desktop and on a phone.
 *
 *  Two faults this measures, both of which make a working page look broken:
 *
 *  **An empty state jammed under the heading.** 34px of padding on a card that
 *  fills the viewport left the sentence floating just below the title with a
 *  field of white beneath it, which reads as a page that failed rather than one
 *  with nothing in it yet. An empty state should be centred in the room it has
 *  and keep its distance from the heading above.
 *
 *  **A page that shows nothing at all while it loads.** An empty table rendered
 *  until the answer lands says "no records" to somebody whose records are on
 *  their way — indistinguishable, on a slow connection, from an empty pharmacy.
 *  So the skeleton is asserted to actually appear, with the network held open
 *  long enough to see it. Without the delay this test would pass against a page
 *  that has no loading state at all.
 *
 *  Run:  node qa/empty-and-loading.mjs      (needs the app running on 5180)
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const BASE = process.env.RX_BASE || "http://localhost:5180";

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
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

// --------------------------------------------------------- the skeletons
console.log("\na screen that has not answered yet");
for (const [route, api] of [
  ["/scorecard", "**/api/scorecard*"],
  ["/payables", "**/api/payables/ageing*"],
]) {
  await page.route(api, async (r) => {
    await new Promise((res) => setTimeout(res, 2500));
    // The delay outlives the unroute below, and continuing a route that has
    // already been dropped throws out of a promise nobody is awaiting — which
    // takes the whole run down rather than failing a check.
    try { await r.continue(); } catch { /* the page moved on */ }
  });
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  const sk = await page.locator(".sk").count();
  check(sk > 0, `${route} ghosts its table while it waits (${sk} blocks)`);
  // Whatever it draws must not be an empty-looking table pretending to be data.
  const rows = await page.locator(".dt tbody tr").count();
  check(rows === 0 || sk > 0,
        `${route} does not show an empty table in place of the answer`);
  await page.unroute(api);
  await page.waitForTimeout(2600);
}

// ------------------------------------------------------- the empty states
console.log("\nan empty state, on a desktop and on a phone");
for (const width of [1440, 390]) {
  await page.setViewportSize({ width, height: width === 390 ? 780 : 950 });
  // A filter nothing can match, so the table is genuinely empty rather than
  // merely unloaded.
  await page.goto(`${BASE}/patients?q=zzzznotarealpatientzzzz`,
                  { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2200);
  const search = page.locator('input[type="search"]').first();
  if (await search.count()) {
    await search.fill("zzzznotarealpatientzzzz");
    await page.waitForTimeout(1800);
  }
  const empty = page.locator(".empty").first();
  if (!(await empty.count())) {
    check(false, `${width}px: no empty state appeared to measure`);
    continue;
  }
  const m = await empty.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const head = document.querySelector(".page-head");
    const hr = head?.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      top: r.top, height: r.height, width: r.width,
      right: r.right,
      gapFromHead: hr ? r.top - hr.bottom : null,
      centred: cs.alignItems === "center" && cs.justifyContent === "center",
      inViewport: r.right <= window.innerWidth + 1 && r.left >= -1,
    };
  });
  check(m.centred, `${width}px: it centres its content`);
  check(m.height >= 120,
        `${width}px: it has real height (${Math.round(m.height)}px), not a caption`);
  check(m.gapFromHead === null || m.gapFromHead > 20,
        `${width}px: it keeps its distance from the heading `
        + `(${Math.round(m.gapFromHead ?? 0)}px)`);
  check(m.inViewport, `${width}px: it does not overflow the screen`);
}

console.log("");
if (failures.length) {
  console.log(`${failures.length} failed`);
  await browser.close();
  process.exit(1);
}
console.log("screens say they are working, and say when they are empty");
await browser.close();
