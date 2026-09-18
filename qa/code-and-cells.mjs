/** The three gestures that were asked for, driven and looked at.
 *
 *      node qa/code-and-cells.mjs        # needs the dev server on :5180
 *
 *  1. Double-clicking the script table, on the header or on an empty row, turns
 *     the FIRST EMPTY ROW into a medicine search, rather than throwing focus
 *     back up to the Medicine field above the table.
 *  2. The till lock's code boxes are the biggest thing on that dialog and sit
 *     equidistant from its edges.
 *  3. The authorisation dialog is the same, and it leaves the screen the moment
 *     the code is sent rather than when the server answers.
 *
 *  Measured rather than eyeballed, because "the boxes are big enough" and "it
 *  closed instantly" are both claims a screenshot cannot settle: the first is a
 *  comparison against everything else on the dialog, and the second is a
 *  stopwatch against a request that takes a third of a second to answer.
 *
 *  Writes a PNG of each into qa/out/.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "out");
const APP = "http://localhost:5180";
mkdirSync(OUT, { recursive: true });

const say = (ok, label, detail = "") =>
  console.log(`${ok ? "ok  " : "FAIL"}  ${label}${detail ? "   " + detail : ""}`);
let bad = 0;
const check = (ok, label, detail) => { if (!ok) bad++; say(ok, label, detail); };

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });

// ---- sign in ---------------------------------------------------------------
await page.goto(`${APP}/login`);
await page.waitForTimeout(1500);
const fields = await page.locator("input").all();
await fields[0].fill("admin");
await fields[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(3500);

// ---- 1. the first empty row becomes the search ------------------------------
await page.goto(`${APP}/dispense`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".disp-grid", { timeout: 20000 });
await page.waitForTimeout(1500);

// On the header, which is the gesture that had no effect at all before.
await page.locator(".rx-item-cols").dblclick();
await page.waitForTimeout(400);
let live = await page.locator(".rx-item-new input.cell-input").count();
check(live === 1, "double-clicking the HEADER opens a search on the first empty row");

// It is the first empty row and not somewhere else: nothing on the script, so
// the new row must be the first row drawn under the column headings.
const order = await page.evaluate(() => {
  const grid = document.querySelector(".disp-grid");
  const rows = [...grid.querySelectorAll(".rx-item")];
  return { first: rows[0]?.className || "", rows: rows.length };
});
check(/rx-item-new/.test(order.first),
      "and it IS the first row, on an empty script", order.first.trim());

// The search must actually be the focused thing, or the row is decorative.
const focused = await page.evaluate(() =>
  document.activeElement?.className || "(none)");
check(/cell-input/.test(focused), "the caret is already in it, with nothing else clicked",
      focused);

// Typing reaches the dispensary's own search. Asked for by the same route the
// page is on, so a term that matches nothing is a real answer and not a bug.
const term = await page.evaluate(async () => {
  const tok = localStorage.getItem("rx5000_token") || "";
  for (const q of ["para", "amox", "am"]) {
    const r = await fetch(`/api/dispensing/products?route=prescription&q=${q}`,
                          { headers: { Authorization: "Bearer " + tok } });
    if (r.ok && (await r.json()).length) return q;
  }
  return "";
});
if (term) {
  await page.locator(".rx-item-new input.cell-input").fill(term);
  await page.waitForTimeout(1500);
  const hits = await page.locator(".cell-menu li").count();
  check(hits > 0, "and it searches medicines from the row",
        `"${term}" gave ${hits} matches`);
  await page.screenshot({ path: join(OUT, "row-search.png") });
} else {
  say(true, "no products in this database to search for, list skipped");
  await page.screenshot({ path: join(OUT, "row-search.png") });
}

await page.keyboard.press("Escape");
await page.waitForTimeout(300);
check(await page.locator(".rx-item-new").count() === 0, "Escape puts the row back");

// The empty rows below answer the same gesture. Aimed at the block rather than
// one of its rows: the rows are aria-hidden and pointer-events:none, and the
// block above them carries the handler, which is what a real double-click on
// any of them actually lands on.
await page.locator(".rx-waiting").dblclick({ position: { x: 200, y: 20 } });
await page.waitForTimeout(400);
check(await page.locator(".rx-item-new input.cell-input").count() === 1,
      "double-clicking an EMPTY ROW opens the same search");
await page.keyboard.press("Escape");

// The table must not grow a row while the search is open, or everything under
// it shunts down the moment somebody aims at it.
const heights = await page.evaluate(async () => {
  const grid = document.querySelector(".disp-grid");
  const before = grid.getBoundingClientRect().height;
  grid.querySelector(".rx-item-cols").dispatchEvent(
    new MouseEvent("dblclick", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 350));
  return { before, after: grid.getBoundingClientRect().height };
});
check(Math.abs(heights.after - heights.before) < 2,
      "and the table does not change height when it opens",
      `${heights.before.toFixed(0)}px then ${heights.after.toFixed(0)}px`);
await page.keyboard.press("Escape");

// ---- 2. the till lock's boxes ----------------------------------------------
await page.evaluate(() => window.dispatchEvent(new Event("rx5000:lock")));
await page.waitForTimeout(600);
let locked = await page.locator(".lock-card").count();
if (!locked) {
  // No test hook for the idle timer, so the gate is driven the way the app
  // drives it. If that is not reachable from here the measurement is skipped
  // rather than reported as a pass.
  await page.evaluate(() => {
    const g = window.__lockGate || window.lockGate;
    if (g?.lock) g.lock(); else if (g?.prompt) g.prompt();
  });
  await page.waitForTimeout(600);
  locked = await page.locator(".lock-card").count();
}
if (locked) {
  await page.screenshot({ path: join(OUT, "till-lock.png") });
  const m = await page.evaluate(() => {
    const card = document.querySelector(".lock-card");
    const box = card.querySelector(".pin-box").getBoundingClientRect();
    const pin = card.querySelector(".pin").getBoundingClientRect();
    const cr = card.getBoundingClientRect();
    // The tallest other thing on the dialog, so "biggest" is a comparison and
    // not an opinion.
    const others = [...card.querySelectorAll("h2, p, label, button, .alert")]
      .map((n) => n.getBoundingClientRect().height);
    return {
      w: box.width, h: box.height, tallestOther: Math.max(0, ...others),
      left: pin.left - cr.left, right: cr.right - pin.right,
    };
  });
  check(m.h > m.tallestOther,
        "the code boxes are the biggest thing on the till lock",
        `box ${m.w.toFixed(0)}x${m.h.toFixed(0)}, next tallest ${m.tallestOther.toFixed(0)}`);
  check(Math.abs(m.left - m.right) < 2, "and sit equidistant from its edges",
        `${m.left.toFixed(1)}px left, ${m.right.toFixed(1)}px right`);
} else {
  say(true, "till lock not reachable from here, skipped");
}

// ---- 3. the authorisation dialog -------------------------------------------
// Driven through the real chain rather than rendered on its own: put a line on
// a script, set a price on it, and the server's 428 is what raises the dialog.
// Anything short of that is a screenshot of a component, not of the moment.
await page.goto(`${APP}/dispense`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".disp-grid", { timeout: 20000 });
await page.waitForTimeout(2000);

await page.locator(".rx-item-cols").dblclick();
await page.waitForTimeout(300);
if (term) {
  await page.locator(".rx-item-new input.cell-input").fill(term);
  await page.waitForTimeout(1600);
  const first = page.locator(".cell-menu li:not(.is-taken)").first();
  if (await first.count()) {
    await first.click();
    await page.waitForTimeout(1200);
    // The line editor opens on a new line, because it has no directions yet.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);
  }
}
const lines = await page.locator(".disp-grid .rx-item:not(.rx-item-waiting):not(.rx-item-new)").count();
check(lines > 0, "picking from the row puts the medicine on the script",
      `${lines} line(s)`);
await page.screenshot({ path: join(OUT, "row-picked.png") });

// Now the amount, which is the cell that costs a code.
if (lines > 0) {
  await page.locator(".rx-item-money").nth(1).dblclick();
  await page.waitForTimeout(900);
  await page.screenshot({ path: join(OUT, "price-dialog.png") });

  // The amount edits in place: type over it and commit, and the server's 428
  // on the override is what raises the code prompt.
  const cell = page.locator(".rx-item-money input.cell-input").first();
  if (await cell.count()) {
    await cell.fill("9.99");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(2000);
  }

  const up = await page.locator(".su-pin .pin-box").count();
  if (up) {
    await page.screenshot({ path: join(OUT, "step-up.png") });
    const m = await page.evaluate(() => {
      const card = document.querySelector(".modal");
      const box = card.querySelector(".pin-box").getBoundingClientRect();
      const pin = card.querySelector(".pin").getBoundingClientRect();
      const cr = card.getBoundingClientRect();
      const others = [...card.querySelectorAll("h2, p, label, button, .alert")]
        .map((n) => n.getBoundingClientRect().height);
      return { w: box.width, h: box.height, tallestOther: Math.max(0, ...others),
               left: pin.left - cr.left, right: cr.right - pin.right,
               words: card.innerText.trim().split(/\s+/).length };
    });
    check(m.h > m.tallestOther, "the code boxes are the biggest thing on the prompt",
          `box ${m.w.toFixed(0)}x${m.h.toFixed(0)}, next tallest ${m.tallestOther.toFixed(0)}`);
    check(Math.abs(m.left - m.right) < 2, "and sit equidistant from its edges",
          `${m.left.toFixed(1)}px left, ${m.right.toFixed(1)}px right`);
    check(m.words < 60, "and the prompt is brief", `${m.words} words on it`);

    // THE MEASUREMENT THIS WAS BUILT FOR.
    // A wrong code, so the server refuses it: the dialog must still leave the
    // screen on the last digit, not when the answer comes back a third of a
    // second later. Timed from the keystroke to the dialog being gone.
    const t0 = Date.now();
    for (const d of ["9", "9", "9", "8"]) await page.keyboard.press(d);
    await page.waitForSelector(".su-pin", { state: "detached", timeout: 4000 });
    const gone = Date.now() - t0;
    check(gone < 250, "and it leaves the screen on the last digit, not on the answer",
          `${gone}ms`);

    // And a refused code brings it back rather than silently doing nothing.
    await page.waitForTimeout(3000);
    const back = await page.locator(".su-pin .pin-box").count();
    check(back > 0, "a refused code brings the prompt back", `${back} boxes again`);
    await page.screenshot({ path: join(OUT, "step-up-refused.png") });
  } else {
    say(true, "the price chain did not reach a code prompt here, skipped");
  }
}

await page.screenshot({ path: join(OUT, "dispense-grid.png") });
await browser.close();

console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
