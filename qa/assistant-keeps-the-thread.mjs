/** The assistant does not forget mid sentence.
 *
 *      node qa/assistant-keeps-the-thread.mjs      # needs the dev server on :5180
 *
 *  The dock in the corner and the page at /assistant are two components. The
 *  conversation is not two conversations, and it was: each held its own
 *  `useState`, so asking in the corner and then opening the full page showed an
 *  empty panel, and making the dock bigger or closing it lost the thread
 *  outright. What the answer had been was then reachable only through the
 *  history list, which is where an OLD conversation belongs, not the one being
 *  had.
 *
 *  Five things must not lose it, and each of them is something somebody does
 *  in the middle of asking: make it bigger to read a diagram, close it to see
 *  the screen behind, open the full page, reload the till.
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

const turns = () => page.locator(".ax-turn").count();

await page.locator(".ax-dock .ax-ask textarea")
  .fill("Where do I see what has been dispensed today?");
await page.keyboard.press("Enter");
await page.waitForSelector(".ax-turn", { timeout: 30000 });
await page.waitForTimeout(14000);          // let the answer finish
check(await turns() === 1, "a question asked in the dock is on screen");

await page.locator(".ax-dock-btn[aria-label='Make it bigger']").click();
await page.waitForTimeout(1200);
check(await turns() === 1, "making it bigger keeps the conversation");

await page.locator(".ax-dock-btn[aria-label='Close']").click();
await page.waitForTimeout(800);
await page.keyboard.press("Control+k");
await page.waitForTimeout(1200);
check(await turns() === 1, "closing it and opening it again keeps the conversation");

await page.locator(".ax-dock-btn[aria-label='Open the full page']").click();
await page.waitForTimeout(2500);
check(new URL(page.url()).pathname.startsWith("/assistant") && await turns() === 1,
      "the full page shows the SAME conversation, not an empty one");

await page.reload();
await page.waitForTimeout(4000);
check(await turns() === 1, "a reload keeps it: a till reloaded mid question has not changed its mind");

// And it can be put down on purpose, which is the other half of keeping it.
const fresh = page.getByRole("button", { name: /New conversation/ });
check(await fresh.count() === 1, "there is a way to start a new one");
await fresh.click();
await page.waitForTimeout(1200);
check(await turns() === 0, "and it starts a new one");

await page.screenshot({ path: join(OUT, "assistant-thread.png") });
await browser.close();
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
