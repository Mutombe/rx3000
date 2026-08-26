/** Does a button that fires a request show that it is working?
 *
 *  Clicks a real action with the network slowed, and checks the control reports
 *  itself busy while the request is in flight. A button that looks identical
 *  before and after the press is why an operator presses it four times.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
const logs = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") logs.push(m.text().slice(0, 200)); });
page.on("pageerror", (e) => logs.push("PAGEERROR " + e.message.slice(0, 200)));
await page.goto("http://localhost:5180/login");
await page.waitForTimeout(1000);
const i = await page.locator("input").all();
await i[0].fill("admin"); await i[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2600);

// Hold the worklist request open long enough to observe the button mid-flight.
await page.route("**/api/dispensary/worklist**", async (route) => {
  await new Promise((r) => setTimeout(r, 1500));
  await route.continue();
});

await page.goto("http://localhost:5180/dispense", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3000);

const refresh = page.locator('[aria-label="Refresh the worklist"]');
const out = {
  found: await refresh.count(),
  worklistPresent: await page.locator(".wl").count(),
  worklistState: await page.locator(".wl").evaluate((e) => e.className).catch(() => null),
  heading: await page.locator("main h1").innerText().catch(() => null),
  headHtml: await page.locator(".wl-head").innerHTML().catch(() => null),
};
if (out.found) {
  await refresh.click();
  await page.waitForTimeout(400);
  out.busyDuringRequest = await refresh.getAttribute("aria-busy");
  out.spinningClass = (await refresh.getAttribute("class")).includes("is-busy");
  out.iconAnimated = await refresh.evaluate((e) => {
    const svg = e.querySelector("svg");
    return svg ? getComputedStyle(svg).animationName : null;
  });
  await page.waitForTimeout(2200);
  out.busyAfter = await refresh.getAttribute("aria-busy");
}
await b.close();
console.log(JSON.stringify({ ...out, logs: logs.slice(0, 6) }, null, 1));
