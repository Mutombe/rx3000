/** Stock moved between two branches, from head office, and watched both ends.
 *
 *      node qa/estate-stock.mjs        # needs the dev server on :5180
 *
 *  The claim being checked is the one that was asked for: clear deductions and
 *  additions. So this does not just press the button and look for a toast. It
 *  reads what each branch holds BEFORE, reads what the screen says the move
 *  will do, sends it, and then reads both shelves again from the server to see
 *  whether the screen told the truth.
 *
 *  The gap in the middle matters too. Between despatch and arrival the stock is
 *  on neither shelf, and that is the only time a product's group total and the
 *  sum of its branches disagree. The screen has to say so rather than quietly
 *  lose twenty boxes for a day.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "out");
const APP = "http://localhost:5180";
mkdirSync(OUT, { recursive: true });

let bad = 0;
const check = (ok, label, extra = "") => {
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${label}${extra ? "   " + extra : ""}`);
};

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });

await page.goto(`${APP}/login`);
await page.waitForTimeout(1500);
const fields = await page.locator("input").all();
await fields[0].fill("admin");
await fields[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(3500);

// The assistant dock floats over the bottom right corner, which is where a
// table keeps its row actions. A person would close it; so does this.
await page.locator(".ax-dock .ax-dock-btn").last().click().catch(() => {});
await page.waitForTimeout(400);

const call = (path) => page.evaluate(async (p) => {
  const r = await fetch(p, {
    headers: { Authorization: "Bearer " + (localStorage.getItem("rx5000_token") || "") },
  });
  return r.ok ? r.json() : { error: r.status };
}, path);

// ---- a product two branches can argue about --------------------------------
const products = await call("/api/products?q=a&limit=40");
let subject = null;
for (const p of products) {
  const h = await call(`/api/branches/transfers/holdings?product_id=${p.id}`);
  if (h.branches && h.branches.length >= 2 && h.branches.some((b) => b.on_hand >= 4)) {
    subject = h;
    break;
  }
}
check(!!subject, "a product with stock and two branches to move it between",
      subject ? `${subject.product}, ${subject.branches.length} branches` : "none found");
if (!subject) { await browser.close(); process.exit(1); }

const sorted = [...subject.branches].sort((a, b) => b.on_hand - a.on_hand);
const from = sorted[0];
const to = sorted[sorted.length - 1];
const MOVE = 3;
console.log(`      ${subject.product}: ${from.branch} has ${from.on_hand}, `
          + `${to.branch} has ${to.on_hand}`);

// ---- the screen -------------------------------------------------------------
await page.goto(`${APP}/head-office?tab=stock`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);
check(await page.locator(".es").count() === 1, "head office has a stock tab");

await page.locator(".es-find input").fill(subject.product.slice(0, 12));
await page.waitForTimeout(1600);
const hit = page.locator(".es-hits button").first();
check(await hit.count() > 0, "the medicine can be found by name");
await hit.click();
await page.waitForSelector(".es-shelves tbody tr", { timeout: 15000 });

const shelves = await page.locator(".es-shelves tbody tr").count();
check(shelves >= 3, "every branch is listed with what it holds",
      `${shelves - 1} branches and a group total`);
await page.screenshot({ path: join(OUT, "estate-stock.png") });

// ---- the deduction and the addition, BEFORE anything moves -----------------
await page.locator(".es-qty input").fill(String(MOVE));
await page.waitForTimeout(500);
const shown = await page.evaluate(() => {
  const rows = [...document.querySelectorAll(".es-shelves tbody tr")];
  return rows.map((r) => ({
    branch: r.querySelector("td")?.innerText?.trim().split("\n")[0] || "",
    now: r.children[1]?.textContent?.trim() || "",
    after: r.children[2]?.textContent?.trim() || "",
    moving: r.classList.contains("is-moving"),
  })).filter((r) => r.moving);
});
check(shown.length === 2, "exactly two branches are shown changing", shown.length);
const down = shown.find((r) => r.after.includes("-"));
const up = shown.find((r) => r.after.includes("+"));
check(!!down && !!up, "one going down and one going up",
      shown.map((r) => `${r.branch} ${r.now} -> ${r.after}`).join(" | "));
await page.screenshot({ path: join(OUT, "estate-stock-preview.png") });

// ---- send it ----------------------------------------------------------------
await page.getByRole("button", { name: /send it/i }).first().click();
await page.waitForTimeout(800);
const ask = await page.locator(".cf-box").innerText().catch(() => "");
check(/goes from/i.test(ask), "it says what will happen before it does it",
      ask.replace(/\s+/g, " ").slice(0, 96));
await page.getByRole("button", { name: /^send it$/i }).last().click();
await page.waitForTimeout(3000);

// ---- did the screen tell the truth ------------------------------------------
const after = await call(`/api/branches/transfers/holdings?product_id=${subject.product_id}`);
const nowFrom = after.branches.find((b) => b.branch_id === from.branch_id);
const nowTo = after.branches.find((b) => b.branch_id === to.branch_id);
check(nowFrom.on_hand === from.on_hand - MOVE,
      "the sending branch really is lighter", `${from.on_hand} to ${nowFrom.on_hand}`);
check(nowTo.on_hand === to.on_hand,
      "and the receiving branch has NOT changed, because it has not arrived",
      `${to.on_hand} still`);

const transit = await call("/api/branches/transfers/in-transit");
const mine = transit.filter((t) => t.quantity === MOVE
  && t.from_branch === from.branch && t.to_branch === to.branch);
check(mine.length > 0, "and it is on the road", `${transit.length} in transit`);
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);
// The second card, not the second table: a reload clears the search, so the
// shelves table is not on screen and the road table is the only one there.
check(await page.locator(".es .card").nth(1).locator("tbody tr").count() > 0,
      "the on-the-road table shows it");
await page.screenshot({ path: join(OUT, "estate-stock-transit.png") });

// ---- book it in -------------------------------------------------------------
await page.getByRole("button", { name: /it has arrived/i }).first().click();
await page.waitForTimeout(800);
await page.getByRole("button", { name: /it has arrived/i }).last().click();
await page.waitForTimeout(3000);

const settled = await call(`/api/branches/transfers/holdings?product_id=${subject.product_id}`);
const endFrom = settled.branches.find((b) => b.branch_id === from.branch_id);
const endTo = settled.branches.find((b) => b.branch_id === to.branch_id);
check(endTo.on_hand === to.on_hand + MOVE,
      "the receiving branch is heavier once it is booked in",
      `${to.on_hand} to ${endTo.on_hand}`);
check(endFrom.on_hand === from.on_hand - MOVE,
      "and the sending branch did not move again");
check(settled.group_total === subject.group_total,
      "the group holds exactly what it held before",
      `${subject.group_total} then, ${settled.group_total} now`);

await browser.close();
console.log(bad ? `\n${bad} FAILED` : "\nstock moved, and both shelves agree.");
process.exit(bad ? 1 : 0);
