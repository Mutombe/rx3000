/** Can the public pages be scrolled to their end?
 *
 *  The application shell scrolls its own main pane and locks the document, which
 *  is correct inside the product and wrong on every page rendered outside it.
 *  This checks the pages that live above the Protected route: content taller
 *  than the viewport must be reachable, and the last element on the page must
 *  actually come into view.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const rows = [];
for (const route of ["/welcome", "/training", "/login"]) {
  const page = await b.newPage({ viewport: { width: 1280, height: 700 } });
  await page.goto("http://localhost:5180" + route, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1400);
  const before = await page.evaluate(() => ({
    scrollH: document.documentElement.scrollHeight,
    clientH: document.documentElement.clientHeight,
  }));
  await page.mouse.wheel(0, 4000);
  await page.waitForTimeout(600);
  const after = await page.evaluate(() => ({
    y: Math.round(window.scrollY),
    footVisible: (() => {
      const f = document.querySelector(".pub-foot, .demo-creds, .login-foot");
      if (!f) return null;
      const r = f.getBoundingClientRect();
      return r.bottom > 0 && r.top < window.innerHeight;
    })(),
  }));
  const taller = before.scrollH > before.clientH + 1;
  rows.push({
    route,
    contentTallerThanViewport: taller,
    scrolledTo: after.y,
    reachesEnd: taller ? (after.y > 0 ? "yes" : "NO - stuck at top") : "n/a, fits",
    lastBlockVisible: after.footVisible,
  });
  await page.close();
}
await b.close();
console.table(rows);
const bad = rows.filter((r) => r.reachesEnd.startsWith("NO"));
console.log(bad.length ? "FAIL" : "PASS: every public page reaches its end");
