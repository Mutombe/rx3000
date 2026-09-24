/** Is anything in a table cut off where nobody can read it?
 *
 *  WHAT WENT WRONG
 *
 *  The findings table on Inventory is laid out `fixed` and declared no
 *  column widths, so the browser divided the width into equal shares: five
 *  columns of 217px each on a 1366 laptop. The finding needed 491 and was
 *  cut off mid-word. The two action buttons needed 201 and the second one,
 *  "Read", lost its right half. A money figure and a date sat in 217px
 *  apiece with room to spare.
 *
 *  It looked like the table overflowing its card, and it was not: the table
 *  fitted exactly. Individual cells were clipping their own contents, which
 *  from the outside is indistinguishable from a card that is too narrow, and
 *  from the inside is a completely different bug.
 *
 *  WHY NOTHING ELSE CATCHES IT
 *
 *  No console error, no overflowing scrollbar, no failing layout. The page
 *  is valid and renders; a word is simply missing its end. The only way to
 *  know is to measure what a cell holds against the room it was given, which
 *  is what this does, on a laptop-sized window, on every screen that has a
 *  table.
 *
 *  TWO TIERS, BECAUSE TRUNCATION IS NOT ALWAYS A BUG
 *
 *  A cell that clips with `text-overflow: ellipsis` and carries a `title` is
 *  a deliberate choice: the reader sees that it is shortened and can hover
 *  for the rest. A cell that clips with neither is text that simply stops,
 *  which reads as a rendering fault rather than as a long value.
 *
 *  A clipped BUTTON OR LINK is worse than either and is reported on its own.
 *  Truncated prose is hard to read; a truncated control is one somebody
 *  cannot press.
 *
 *  Needs the app on 5180 and an API it can reach.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const WEB = process.env.RX_WEB ?? "http://localhost:5180";
const API = process.env.RX_API ?? "http://localhost:8177";

/** 1366x768 is the laptop this went wrong on, and the commonest screen in
 *  the shops this is sold to. A sweep at 1920 finds nothing. */
const WIDTH = Number(process.env.RX_WIDTH ?? 1366);
const HEIGHT = 768;

/** Every route that can be opened without inventing a record id. Tabs are
 *  named where a screen hides its tables behind one. */
const ROUTES = [
  "/", "/accounts", "/admin", "/authorisations", "/branches", "/claiming",
  "/claims-held", "/compliance", "/compounding", "/crm-reports",
  "/deliveries", "/dispensary/operations", "/dispense", "/dispensing-history",
  "/drivers", "/fiscal", "/head-office", "/helpdesk", "/laybys", "/leads",
  "/ledger", "/marketing", "/money-owed", "/orders", "/patients", "/payables",
  "/periods", "/pharmacies", "/pipeline", "/recall", "/reconciliation",
  "/reconciliation/bank", "/reconciliation/card", "/reconciliation/settlements",
  "/register", "/reminders", "/remittances", "/repeats", "/rfqs", "/samples",
  "/scorecard", "/scripts", "/seasons", "/shifts", "/stock",
  "/stock?tab=watch", "/stock?tab=bins", "/stock?tab=quarantine",
  "/stock?tab=batches", "/stock?tab=movements", "/stock-categories",
  "/stock-performance", "/stock-take", "/suppliers", "/to-follows",
  "/will-call",
];

/** Under this and it is a rounding difference rather than a missing word. */
const SLACK = 4;

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const ctx = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT } });
await ctx.addInitScript((api) => { window.__RX5000_SERVER__ = api; }, API);
const page = await ctx.newPage();

const token = await fetch(`${API}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "admin", password: "admin123" }),
}).then((r) => r.json()).then((d) => d.access_token);

await page.goto(WEB, { waitUntil: "domcontentloaded" });
await page.evaluate((t) => {
  localStorage.setItem("rx5000_token", t);
  // The assistant dock sits over the bottom corner and covers what is under it.
  localStorage.setItem("rx5000_assistant_dock_seen", "1");
}, token);

console.log(`a cell is not cut off   (at ${WIDTH}x${HEIGHT})`);
console.log();

const cut = [];
const shortened = [];
let screens = 0;
let tables = 0;

for (const route of ROUTES) {
  try {
    await page.goto(WEB + route, { waitUntil: "networkidle", timeout: 22000 });
  } catch {
    console.log(`  ?    ${route}`.padEnd(46) + "did not load");
    continue;
  }
  // WAIT FOR THE TYPEFACE, NOT JUST FOR THE DATA.
  //
  // This guard used to give a different answer on every run — clean, then two
  // screens, then four, all from the same commit. It was measuring text drawn
  // in the FALLBACK font. Inter arrives as a woff2 after first paint, and the
  // fallback has different metrics, so `scrollWidth` was being read against
  // letters that were about to be replaced by narrower ones. Half the
  // findings were real and half were the font swap, and there was no way to
  // tell which from the output.
  //
  // `document.fonts.ready` resolves once every declared face has loaded, so
  // what is measured is what a person actually sees.
  await page.evaluate(() => document.fonts.ready);
  // Rows arrive after the shell; a skeleton has nothing to clip.
  await page.waitForTimeout(1400);
  // And one more frame, so the relayout the swap caused has happened.
  await page.evaluate(() => new Promise(requestAnimationFrame));

  const found = await page.evaluate((slack) => {
    const out = { tables: 0, cut: [], shortened: [] };
    for (const table of document.querySelectorAll("table")) {
      if (!table.getBoundingClientRect().width) continue;
      out.tables += 1;
      const headers = [...table.querySelectorAll("thead th")]
        .map((h) => (h.innerText || "").trim());
      // The first few rows are enough: a column too narrow is too narrow on
      // every row, and reading all of them on a 500-row table is slow.
      const rows = [...table.querySelectorAll("tbody tr")].slice(0, 4);
      const already = new Set();
      for (const row of rows) {
        [...row.cells].forEach((cell, i) => {
          const box = cell.getBoundingClientRect();
          if (!box.width) return;
          const style = getComputedStyle(cell);
          if (style.overflow === "visible") return;   // it spills, not clips
          const over = cell.scrollWidth - Math.ceil(box.width);
          if (over <= slack) return;

          const key = `${i}`;
          if (already.has(key)) return;
          already.add(key);

          // A control that is cut cannot be pressed, which is worse than
          // prose that is cut and is worth separating.
          const control = cell.querySelector("button, a");
          let controlCut = false;
          if (control) {
            const c = control.getBoundingClientRect();
            controlCut = c.right > box.right + slack;
          }
          const ellipsis = style.textOverflow === "ellipsis";
          const titled = !!cell.getAttribute("title")
            || !!cell.querySelector("[title]");

          const entry = {
            column: headers[i] || `column ${i + 1}`,
            over, width: Math.round(box.width),
            needs: cell.scrollWidth,
            control: controlCut,
            text: (cell.innerText || "").split("\n")[0].slice(0, 38),
          };
          // Deliberate and legible: shortened with a mark and a tooltip.
          if (ellipsis && titled && !controlCut) out.shortened.push(entry);
          else out.cut.push(entry);
        });
      }
    }
    return out;
  }, SLACK);

  screens += 1;
  tables += found.tables;
  if (found.cut.length) {
    console.log(`  X    ${route}`);
    for (const c of found.cut) {
      console.log(`       ${c.control ? "a control" : "text"} in "${c.column}"`
        + ` is cut: ${c.width}px for ${c.needs}px`
        + (c.text ? `  (${c.text})` : ""));
    }
    cut.push({ route, ...found });
  }
  for (const s of found.shortened) shortened.push({ route, ...s });
}

console.log();
console.log(`  ${tables} table(s) read across ${screens} screen(s)`);
if (shortened.length) {
  console.log(`  ${shortened.length} cell(s) shortened on purpose, with an `
    + "ellipsis and a tooltip, which is not this");
}
if (!cut.length) {
  console.log();
  console.log("nothing in a table stops mid-word");
}
const controls = cut.reduce((n, r) => n + r.cut.filter((c) => c.control).length, 0);
if (cut.length) {
  console.log();
  console.log(`  ${cut.length} screen(s) cut something off`
    + (controls ? `, including ${controls} control(s) nobody can press` : ""));
  console.log("  A fixed-layout table divides its width equally unless the");
  console.log("  columns say otherwise. Declare widths for the ones that know");
  console.log("  their size and let the wordy column take what is left.");
}
await browser.close();
process.exit(cut.length ? 1 : 0);
