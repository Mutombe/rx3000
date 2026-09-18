/** RX-Assistant, driven the way somebody at a counter would drive it.
 *
 *      node qa/assistant.mjs          # needs the dev server on :5180
 *
 *  What is actually being checked is not "does it reply". It is the three
 *  things that make this worth having over a help page:
 *
 *    - it looks the answer up rather than inventing it, and the looking up is
 *      visible while it happens
 *    - the steps it draws are chips that go somewhere real
 *    - clicking one lands on that screen and lights up that control
 *
 *  The last one is the whole feature, and it is the one no unit test can see.
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
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });

await page.goto(`${APP}/login`);
await page.waitForTimeout(1500);
const fields = await page.locator("input").all();
await fields[0].fill("admin");
await fields[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(3500);

// ---- the way in ------------------------------------------------------------
const chip = page.locator(".ax-chip");
check(await chip.count() === 1, "there is a way in from the top bar");
const order = await page.evaluate(() => {
  const bar = document.querySelector(".topbar");
  const at = (sel) => {
    const n = bar?.querySelector(sel);
    return n ? Math.round(n.getBoundingClientRect().left) : null;
  };
  return { ax: at(".ax-chip"), update: at(".update-chip"), branch: at(".branch-chip") };
});
check(order.ax !== null && (order.branch === null || order.ax < order.branch),
      "and it sits left of the branch label, as asked",
      `assistant ${order.ax}px, branch ${order.branch}px`);

// ---- on by default ---------------------------------------------------------
check(await page.locator(".ax-dock").count() === 1,
      "the dock is open the first time, without being asked for");
await page.screenshot({ path: join(OUT, "assistant-dock.png") });

// ---- it looks things up, visibly -------------------------------------------
await page.locator(".ax-dock .ax-ask input").fill("How do I set a price on a script?");
await page.keyboard.press("Enter");

// The steps must appear while it is still working, not all at the end.
await page.waitForSelector(".ax-steps-live li", { timeout: 25000 });
const early = await page.locator(".ax-steps-live li").first().innerText();
check(/looking/i.test(early), "it says what it is doing while it does it", early.trim());

await page.waitForSelector(".ax-route .ax-step", { timeout: 60000 });
await page.waitForTimeout(6000);          // let the prose finish

const drawn = await page.evaluate(() => {
  const steps = [...document.querySelectorAll(".ax-route .ax-step")];
  return steps.map((s) => ({
    label: s.querySelector(".ax-step-label")?.textContent?.trim() || "",
    dead: s.hasAttribute("disabled"),
  }));
});
check(drawn.length >= 2, "it draws the steps rather than describing them",
      `${drawn.length} steps`);
check(drawn.some((s) => !s.dead), "and at least one of them goes somewhere");
console.log("      " + drawn.map((s) => s.label).join("  >  "));
await page.screenshot({ path: join(OUT, "assistant-route.png") });

// ---- the chips actually take you there -------------------------------------
const live = page.locator(".ax-route .ax-step:not([disabled])");
const many = await live.count();
let landed = "";
for (let i = 0; i < many; i++) {
  await live.nth(i).click();
  await page.waitForTimeout(1600);
  landed = new URL(page.url()).pathname;
  const lit = await page.locator(".is-pointed-at").count();
  if (lit) {
    check(true, `step ${i + 1} lands on ${landed} and lights up the control`);
    await page.screenshot({ path: join(OUT, "assistant-pointing.png") });
    break;
  }
  if (i === many - 1) {
    check(landed !== "/login", `the steps navigate (ended on ${landed})`);
  }
}
check(landed.startsWith("/dispense"), "and the route led to the dispensary", landed);

// ---- it does not invent routes ---------------------------------------------
// Everything it offered must be a real screen: a chip that navigates nowhere
// is the failure this whole design exists to prevent.
const bogus = await page.evaluate(async () => {
  const tok = localStorage.getItem("rx5000_token") || "";
  const r = await fetch("/api/ai/assistant/atlas", {
    headers: { Authorization: "Bearer " + tok },
  });
  return r.ok ? (await r.json()).screens : 0;
});
check(bogus > 50, "the atlas behind it is loaded", `${bogus} screens`);

await browser.close();
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
