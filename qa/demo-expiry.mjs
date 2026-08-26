/** What a visitor sees when the four hours run out.
 *
 *  The clock is shortened in the database rather than waited out. The point is
 *  the ending, not the duration: the bar must change tone, then sign them out
 *  with a reason, rather than leaving them on a page whose next click 401s.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
import { execFileSync } from "node:child_process";

const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
await page.addInitScript(() => { try { localStorage.setItem("rx5000_theme", "dark"); } catch {} });

await page.goto("http://localhost:5180/login");
await page.waitForTimeout(1200);
await page.locator(".alt-card").click();
await page.waitForTimeout(300);
await page.locator("#dm-name").fill("Expiry Walkthrough");
await page.locator(".login-go").click();
await page.waitForTimeout(3000);

const out = { started: page.url() };

// Ninety seconds left: the bar should be in its critical tone.
execFileSync("python", ["qa/out/shorten-demo.py", "90"], { cwd: process.cwd() });
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);
out.criticalClass = await page.locator(".demo-bar").getAttribute("class");
out.criticalText = (await page.locator(".demo-bar").innerText()).replace(/\s+/g, " ");
await page.screenshot({ path: "qa/out/dark-demo-critical.png", clip: { x: 0, y: 0, width: 1440, height: 220 } });

// And now past the end.
execFileSync("python", ["qa/out/shorten-demo.py", "-60"], { cwd: process.cwd() });
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
out.endedOn = page.url();
out.notice = (await page.locator(".login-note").count())
  ? (await page.locator(".login-note").innerText()).replace(/\s+/g, " ") : null;
await page.screenshot({ path: "qa/out/dark-demo-ended.png" });
await b.close();
console.log(JSON.stringify(out, null, 1));
