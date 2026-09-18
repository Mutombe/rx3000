/** No screen may say "nothing here" before it knows.
 *
 *      node qa/no-empty-flash.mjs           # needs the dev server on :5180
 *      node qa/no-empty-flash.mjs /scripts  # one route
 *
 *  A list page that starts with an empty array and no loading flag renders its
 *  empty state on the first paint and the data a moment later. On a fast local
 *  machine that is a flicker; on a pharmacy's connection it is a screen that
 *  says "Nothing matches that" for a second, which is a screen somebody
 *  believes and acts on.
 *
 *  The flicker is invisible to a test that waits for the page to settle, which
 *  is why nobody caught it: the bug only exists while the request is in the
 *  air. So this holds every API response back for a moment and looks at the
 *  screen DURING that window. What is a 40ms flash in the office becomes a
 *  second of held state here, and either the page is showing an honest
 *  skeleton or it is lying.
 *
 *  Three things are asserted while the data is still coming:
 *    - no empty state is on screen
 *    - something is marked busy, so a reader is told rather than left guessing
 *    - the skeleton reserves roughly the room the real content will need, so
 *      nothing jumps when it arrives
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "out");
const APP = "http://localhost:5180";
/** How long every API answer is held. Long enough to look, short enough to run. */
const HOLD = 1500;
mkdirSync(OUT, { recursive: true });

/** The screens that show a list and can therefore show an empty one. */
const ROUTES = [
  ["/dispensing-history", "Dispensing history"],
  ["/scripts", "Scripts"],
  ["/patients", "Patients"],
  ["/orders", "Orders"],
  ["/reminders", "Reminders"],
  ["/remittances", "Remittances"],
  ["/fiscal", "Fiscalisation"],
  ["/payables", "Payables"],
  ["/claiming", "Claiming"],
  ["/register", "Controlled register"],
  ["/stock-take", "Stock take"],
  ["/pharmacies", "Pharmacies"],
  ["/crm-reports", "CRM reports"],
  // The audit log rather than /admin itself: the tab that opens by default is
  // the price-file import, which is a form and has nothing to fetch, so
  // "nothing says it is loading" is the right answer there.
  ["/admin?tab=audit", "Admin, audit"],
  ["/admin?tab=switch", "Admin, switch"],
  ["/deliveries", "Deliveries"],
  ["/repeats", "Repeats"],
  ["/will-call", "Will call"],
  ["/to-follows", "To follows"],
  ["/laybys", "Lay-bys"],
  ["/stock", "Stock"],
];

const only = process.argv[2];
const wanted = only ? ROUTES.filter(([p]) => p === only) : ROUTES;

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });

// ---- sign in, at full speed ------------------------------------------------
await page.goto(`${APP}/login`);
await page.waitForTimeout(1500);
const fields = await page.locator("input").all();
await fields[0].fill("admin");
await fields[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(3500);

// ---- move around the way a user does ---------------------------------------
// Not `goto`, which reloads the whole application: on a reload the app's own
// boot requests are held too, so what is on screen is the route-level fallback
// and every page looks identical. Pushing the route keeps the app up and shows
// the page's OWN loading state, which is the thing being judged.
const go = async (path) => {
  await page.evaluate((p) => {
    window.history.pushState({}, "", p);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
};

let holding = false;
await page.route("**/api/**", async (route) => {
  if (holding) await new Promise((r) => setTimeout(r, HOLD));
  await route.continue();
});

// First pass at full speed: load each page's code and measure the REAL table,
// so the skeleton can be checked against it rather than against a guess.
const real = new Map();
for (const [path, name] of wanted) {
  await go(path);
  await page.waitForTimeout(1400);
  real.set(path, await page.evaluate(() => {
    const t = [...document.querySelectorAll("table")]
      .find((x) => !x.classList.contains("sk-table"));
    const rows = t ? t.querySelectorAll("tbody tr").length : 0;
    return {
      cols: t ? t.querySelectorAll("thead th").length : 0,
      rowHeight: t && rows
        ? Math.round(t.querySelector("tbody tr").getBoundingClientRect().height) : 0,
      rows,
    };
  }));
}
holding = true;

const bad = [];
console.log(`Every API answer held for ${HOLD}ms, and the screen read while it waits.\n`);
console.log(`${"screen".padEnd(22)} ${"empty".padEnd(7)} ${"busy".padEnd(6)} `
            + `${"columns".padEnd(14)} height`);
console.log("-".repeat(74));

for (const [path, name] of wanted) {
  await go(path);
  // Long enough for the first paint and the fetch to be in flight, well short
  // of the answer arriving.
  await page.waitForTimeout(650);

  const seen = await page.evaluate(() => {
    const visible = (n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(n).visibility !== "hidden";
    };
    const empties = [...document.querySelectorAll(".empty, .empty-page")].filter(visible);
    const busy = [...document.querySelectorAll('[aria-busy="true"]')].filter(visible);
    const ghosts = [...document.querySelectorAll(".sk, .skel")].filter(visible);
    const sk = [...document.querySelectorAll("table.sk-table")].filter(visible)[0];
    return {
      empty: empties.map((n) => n.innerText.replace(/\s+/g, " ").trim().slice(0, 46)),
      busy: busy.length,
      ghosts: ghosts.length,
      cols: sk ? sk.querySelectorAll("thead th").length : 0,
      rowHeight: sk && sk.querySelector("tbody tr")
        ? Math.round(sk.querySelector("tbody tr").getBoundingClientRect().height) : 0,
      tallest: Math.round(Math.max(0, ...busy.map((n) => n.getBoundingClientRect().height))),
    };
  });

  const r = real.get(path) ?? { cols: 0, rowHeight: 0 };
  const flashed = seen.empty.length > 0;
  const quiet = seen.busy === 0 && seen.ghosts === 0;
  // The accuracy test: a ghost table with the wrong number of columns, or rows
  // of the wrong height, moves the page when the data lands. That is the one
  // thing a skeleton exists to prevent, so it is a failure and not a nit.
  const wrongCols = seen.cols > 0 && r.cols > 0 && seen.cols !== r.cols;
  const wrongHeight = seen.rowHeight > 0 && r.rowHeight > 0
    && Math.abs(seen.rowHeight - r.rowHeight) > 14;

  if (flashed || quiet || wrongCols || wrongHeight) {
    bad.push([name, path,
      flashed ? `says "${seen.empty[0]}" before it knows`
      : quiet ? "nothing on screen says it is loading"
      : wrongCols ? `ghost has ${seen.cols} columns, the table has ${r.cols}`
      : `ghost rows ${seen.rowHeight}px, real rows ${r.rowHeight}px`]);
    await page.screenshot({ path: join(OUT, `flash${path.replace(/\W+/g, "-")}.png`) });
  }
  console.log(
    `${name.padEnd(22)} ${(flashed ? "FLASH" : "no").padEnd(7)} `
    + `${(seen.busy ? "yes" : "NO").padEnd(6)} `
    + `${(seen.cols ? `${seen.cols} v ${r.cols}${wrongCols ? " <-- bug" : ""}` : "-").padEnd(14)} `
    + `${seen.rowHeight || "-"}px v ${r.rowHeight || "-"}px${wrongHeight ? "  <-- bug" : ""}`);
}

holding = false;
await browser.close();

if (bad.length) {
  console.log(`\n${bad.length} screen(s) wrong:\n`);
  for (const [name, path, why] of bad) console.log(`  ${name.padEnd(24)} ${path.padEnd(22)} ${why}`);
  process.exit(1);
}
console.log("\nall screens hold their shape while they wait.");
