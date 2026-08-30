/** Does the worklist stay put while the script is worked — and do the route
 *  tabs now scroll away as they are meant to?
 *
 *  The worklist is sticky and was pinned against the wrong thing. `main` is the
 *  scrolling element in this shell — `body` and `.shell` are `overflow: hidden`
 *  and the window never scrolls at all — so an offset written as
 *  `top: var(--topbar-h)` measured 56px from a scrollport that already begins
 *  below the top bar. The rail drifted down the page and looked as though the
 *  floating had given up.
 *
 *  The route tabs were pinned too, and are deliberately not any more: the strip
 *  ate the top of the screen on every scroll of a page that is long by nature,
 *  and the route is already stated on the card being typed into. That is a
 *  decision, so it is asserted rather than left to drift back — this file
 *  checks the tabs DO scroll away, and would fail if somebody made them sticky
 *  again without meaning to.
 *
 *  The original failure was invisible in the source: `position: sticky` is
 *  right, the offset is a plausible number, and it only misbehaves once
 *  something is long enough to scroll. So this scrolls the real container to
 *  several depths and measures.
 *
 *  Run:  node qa/dispensary-sticky.mjs      (needs the app running on 5180)
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const BASE = process.env.RX_BASE || "http://localhost:5180";

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1500, height: 850 } });
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

await page.goto(`${BASE}/dispense`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);

// A script long enough to scroll. Without one nothing moves and this passes
// against a page that has no sticky behaviour at all.
const queued = page.locator(".wl-row");
if (await queued.count()) {
  await queued.first().click();
  await page.waitForTimeout(2500);
}

const scrollable = await page.evaluate(() => {
  const m = document.querySelector("main.main");
  return m ? m.scrollHeight - m.clientHeight : 0;
});
check(scrollable > 600,
      `the page is long enough to test (${Math.round(scrollable)}px of scroll)`);
if (scrollable <= 600) {
  console.log("\n  nothing to scroll — cannot test the thing that matters");
  await browser.close();
  process.exit(1);
}

const seen = { routes: new Set(), rail: new Set() };
for (const depth of [300, 700, 1200, Math.round(scrollable)]) {
  await page.evaluate((y) => {
    document.querySelector("main.main").scrollTop = y;
  }, depth);
  await page.waitForTimeout(300);

  const m = await page.evaluate(() => {
    const bar = document.querySelector(".topbar").getBoundingClientRect().bottom;
    const r = document.querySelector(".disp-routes")?.getBoundingClientRect();
    const w = document.querySelector(".wl")?.getBoundingClientRect();
    return {
      bar: Math.round(bar),
      routes: r ? Math.round(r.top) : null,
      rail: w ? Math.round(w.top) : null,
      scrolled: Math.round(document.querySelector("main.main").scrollTop),
    };
  });

  console.log(`\nat ${m.scrolled}px`);
  // The tabs are meant to leave with the page now. Anything still sitting at
  // the top bar after scrolling a thousand pixels is pinned again.
  check(m.routes !== null && m.routes < m.bar,
        `the route tabs scroll away with the page (${m.routes} vs ${m.bar})`);
  check(m.rail === null || m.rail >= m.bar - 1,
        `the worklist stays below the top bar (${m.rail} vs ${m.bar})`);
  seen.routes.add(m.routes);
  if (m.rail !== null) seen.rail.add(m.rail);
}

console.log("");
// The inverse of the old assertion, and for the same reason: a pinned strip
// reports the same position at every depth, so one that reports a different
// position each time is travelling with the page — which is now what it is
// supposed to do.
check(seen.routes.size >= 3,
      `the route tabs travel with the page rather than pinning `
      + `(${[...seen.routes].join(", ")})`);
// Pinned means it stops somewhere. A rail that reports a different position at
// every depth is scrolling with the page, which is the bug this file exists for.
check(seen.rail.size <= 3,
      `the worklist settles rather than drifting (${[...seen.rail].join(", ")})`);

console.log("");
if (failures.length) {
  console.log(`${failures.length} failed`);
  await browser.close();
  process.exit(1);
}
console.log("the queue stays put while the script is worked, and the tabs scroll away");
await browser.close();
