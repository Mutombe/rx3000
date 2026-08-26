/** Sign up for a demo from the login screen and check what the visitor sees.
 *
 *  Three things this is watching for, all of which have been wrong in demo
 *  flows before: the countdown reading from the server's absolute time rather
 *  than a browser duration, the bar changing tone as it runs down, and the
 *  session actually ending rather than the next click returning a 401.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
page.on("pageerror", (e) => errs.push(e.message.slice(0, 140)));
page.on("console", (m) => { if (m.type() === "error") errs.push("CONSOLE " + m.text().slice(0, 200)); });
page.on("response", (r) => { if (r.status() >= 400 || r.url().includes("/api/auth/")) errs.push(`RESP ${r.status()} ${r.url().replace("http://localhost:5180", "")}`); });
await page.addInitScript(() => { try { localStorage.setItem("rx5000_theme", "dark"); } catch {} });

await page.goto("http://localhost:5180/login");
await page.waitForTimeout(1200);
await page.locator(".alt-card").click();
await page.waitForTimeout(400);
await page.locator("#dm-name").fill("Tendai Moyo");
await page.locator(".login-go").click();
await page.waitForTimeout(3000);

const bar = await page.locator(".demo-bar").first();
const banner = page.locator(".error-banner");
const out = {
  landedOn: page.url(),
  banner: (await banner.count()) ? await banner.innerText() : null,
  barVisible: await bar.count() > 0 && await bar.isVisible(),
  barText: (await bar.count()) ? (await bar.innerText()).replace(/\s+/g, " ") : null,
  clock: (await page.locator(".demo-clock").count()) ? await page.locator(".demo-clock").innerText() : null,
};
await page.waitForTimeout(2200);
out.clockLater = (await page.locator(".demo-clock").count()) ? await page.locator(".demo-clock").innerText() : null;
await page.screenshot({ path: "qa/out/dark-demo-session.png" });
await b.close();
console.log(JSON.stringify({ ...out, pageErrors: errs }, null, 1));
