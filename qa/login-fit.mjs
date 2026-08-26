/** Do all three login panels come out the same height, with nothing clipped and
 *  no scrollbar, at every screen height a till or a laptop actually has?
 *
 *  `scrollHeight > clientHeight` is the test. It is true the moment content
 *  overflows, whether or not a scrollbar is painted, so it catches the case
 *  where `overflow: hidden` would have quietly cut the last line off.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const rows = [];
for (const height of [540, 600, 660, 700, 800, 900, 1000, 1200]) {
  const page = await b.newPage({ viewport: { width: 1280, height } });
  await page.goto("http://localhost:5180/login");
  await page.waitForTimeout(1300);

  const read = async (label) => {
    const m = await page.locator(".login-card").evaluate((e) => ({
      h: Math.round(e.getBoundingClientRect().height),
      client: e.clientHeight, scroll: e.scrollHeight,
      pageScrolls: document.documentElement.scrollHeight > document.documentElement.clientHeight,
    }));
    rows.push({
      viewport: height, panel: label, card: m.h,
      pct: `${Math.round((m.h / height) * 100)}%`,
      overflows: m.scroll > m.client + 1 ? `YES by ${m.scroll - m.client}px` : "no",
      pageScrolls: m.pageScrolls,
    });
  };
  await read("signin");
  await page.locator(".link-btn", { hasText: "forgotten" }).click();
  await page.waitForTimeout(350);
  await read("reset");
  await page.locator(".link-btn", { hasText: "Back to sign in" }).click();
  await page.waitForTimeout(300);
  await page.locator(".alt-card").click();
  await page.waitForTimeout(350);
  await read("demo");
  await page.close();
}
await b.close();
console.table(rows);
const bad = rows.filter((r) => r.overflows !== "no");
console.log(bad.length ? `FAIL: ${bad.length} panels overflow` : "PASS: no panel overflows at any height");
