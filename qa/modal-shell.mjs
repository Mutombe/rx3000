/** Do dialogs hold together, and can their buttons be reached?
 *
 *  Written after a payment dialog was screenshotted with its currency and
 *  amount stacked into a narrow first column, "Hold this claim — do not send it
 *  now" wrapping one word per line *outside* the dialog, and a horizontal
 *  scrollbar along the bottom. The cause was a class collision: `.tender-line`
 *  was a four-column grid in the till's own panel and a bordered card in the
 *  shared Tenders component, both unscoped, so every payment modal in the
 *  product laid its rows out in four columns.
 *
 *  Three things are asserted at three widths, because all three were false:
 *
 *    1. **No dialog scrolls sideways.** A modal with a horizontal scrollbar has
 *       content off the edge of it already.
 *    2. **Nothing escapes the box.** Every element inside is measured against
 *       the dialog's own rectangle. This is what catches text hanging outside.
 *    3. **The buttons are reachable without scrolling.** The whole dialog used
 *       to scroll — title, body and actions together — so on a long form the
 *       operator scrolled past "Take payment" to read the total and back down
 *       to press it. The actions are sticky now; this proves it.
 *
 *  Run:  node qa/modal-shell.mjs        (needs the app running on 5180)
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const BASE = process.env.RX_BASE || "http://localhost:5180";
const WIDTHS = [1440, 1100, 780];

/** Each case: a page, the control that opens its dialog, and what to expect. */
const CASES = [
  { name: "New department", route: "/stock-categories", open: "New department" },
  { name: "New formulary", route: "/claiming?tab=formularies", open: "New formulary" },
  { name: "New product", route: "/stock", open: "+ New Product" },
];

const browser = await chromium.launch({ executablePath: EXE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const failures = [];
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message.slice(0, 160)));

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

/** Measure the open dialog. */
async function measure() {
  return page.evaluate(() => {
    const modal = document.querySelector(".modal");
    if (!modal) return null;
    const box = modal.getBoundingClientRect();
    const overflowing = [];
    for (const el of modal.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      // 1px of tolerance for sub-pixel rounding on borders.
      if (r.right > box.right + 1 || r.left < box.left - 1) {
        overflowing.push(
          `${el.tagName.toLowerCase()}.${(el.className || "").toString().split(" ")[0]}`
          + ` "${(el.textContent || "").trim().slice(0, 32)}"`);
      }
    }
    const actions = modal.querySelector(".modal-actions");
    const h2 = modal.querySelector("h2");
    const ar = actions?.getBoundingClientRect();
    return {
      scrollsSideways: modal.scrollWidth > modal.clientWidth + 1,
      overflowing: [...new Set(overflowing)].slice(0, 5),
      actionsInView: ar
        ? ar.bottom <= window.innerHeight + 1 && ar.top >= 0
        : null,
      actionsSticky: actions
        ? getComputedStyle(actions).position === "sticky" : null,
      headerSticky: h2 ? getComputedStyle(h2).position === "sticky" : null,
      widerThanViewport: box.right > window.innerWidth + 1 || box.left < -1,
    };
  });
}

for (const width of WIDTHS) {
  await page.setViewportSize({ width, height: 900 });
  console.log(`\n=== ${width}px ===`);
  for (const c of CASES) {
    await page.goto(`${BASE}${c.route}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    const opener = page.locator("button", { hasText: c.open }).first();
    if (!(await opener.count())) {
      check(false, `${c.name}: no "${c.open}" control on ${c.route}`);
      continue;
    }
    await opener.click();
    await page.waitForTimeout(700);
    const m = await measure();
    if (!m) { check(false, `${c.name}: the dialog did not open`); continue; }

    check(!m.scrollsSideways, `${c.name}: does not scroll sideways`);
    check(m.overflowing.length === 0,
          `${c.name}: nothing hangs outside${m.overflowing.length
            ? ` — ${m.overflowing.join("; ")}` : ""}`);
    check(m.actionsInView !== false,
          `${c.name}: its buttons are on screen without scrolling`);
    check(!m.widerThanViewport, `${c.name}: fits the viewport`);
    if (width === WIDTHS[0]) {
      check(m.headerSticky === true, `${c.name}: the title stays put`);
      check(m.actionsSticky === true, `${c.name}: the actions stay put`);
    }
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  }
}

console.log("");
if (pageErrors.length) {
  console.log(`page errors: ${[...new Set(pageErrors)].join(" | ")}`);
}
if (failures.length) {
  console.log(`${failures.length} failed`);
  await browser.close();
  process.exit(1);
}
console.log("dialogs hold together and their buttons can be reached");
await browser.close();
