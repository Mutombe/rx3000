/** Does the theme control actually change the theme, and does it stick?
 *
 *  Checks the three states and the two things that are easy to get wrong:
 *  System resolves to the device rather than doing nothing, and the choice
 *  survives a reload without a flash of the other theme.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const EXE = "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe";
const b = await chromium.launch({ executablePath: EXE });
const out = [];

for (const device of ["dark", "light"]) {
  const ctx = await b.newContext({ colorScheme: device, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto("http://localhost:5180/login");
  await page.waitForTimeout(800);
  const inp = await page.locator("input").all();
  await inp[0].fill("admin"); await inp[1].fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2600);

  const read = () => page.evaluate(() => ({
    applied: document.documentElement.getAttribute("data-theme"),
    choice: document.documentElement.getAttribute("data-theme-choice"),
    canvas: getComputedStyle(document.body).backgroundColor,
    checked: [...document.querySelectorAll(".theme-opt")].map((e) => e.getAttribute("aria-checked")),
  }));

  out.push({ device, when: "fresh load, no choice made", ...(await read()) });

  for (const [i, name] of [[0, "Light"], [1, "Dark"], [2, "System"]]) {
    await page.locator(".theme-opt").nth(i).click();
    await page.waitForTimeout(350);
    out.push({ device, when: `clicked ${name}`, ...(await read()) });
  }

  // Pick Dark, reload, and confirm the very first paint is already dark.
  await page.locator(".theme-opt").nth(1).click();
  await page.waitForTimeout(250);
  await page.reload({ waitUntil: "commit" });
  const atFirstPaint = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  await page.waitForTimeout(1500);
  out.push({ device, when: "after reload with Dark chosen", atFirstPaint, ...(await read()) });
  await ctx.close();
}
await b.close();
console.table(out);
