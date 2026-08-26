/** Does the working pane use a big monitor, or leave a grey margin on it?
 *
 *  `.main` was capped at a flat 1400px, so a 1920 screen showed 1400px of
 *  product and 320px of nothing, with the report grid stuck at four columns.
 *  This measures the pane against the space available and counts the columns a
 *  card grid actually reaches.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const rows = [];
for (const width of [1366, 1600, 1920, 2560]) {
  const page = await b.newPage({ viewport: { width, height: 1000 } });
  await page.goto("http://localhost:5180/login");
  await page.waitForTimeout(900);
  const i = await page.locator("input").all();
  await i[0].fill("admin"); await i[1].fill("admin123");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2400);
  await page.goto("http://localhost:5180/reports", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  const m = await page.evaluate(() => {
    const main = document.querySelector(".main");
    const shell = document.querySelector(".content") ?? document.body;
    // The widest group, not the first one. The first group holds three reports,
    // so measuring it reported three columns at every screen width and made a
    // working grid look broken — the count was the group's size, not the
    // layout's capacity.
    let cols = 0;
    for (const list of document.querySelectorAll(".rc-list")) {
      const cards = [...list.children];
      if (cards.length < 6) continue;          // too few to fill a wide row
      const top = Math.round(cards[0].getBoundingClientRect().top);
      const inRow = new Set(cards
        .filter((c) => Math.abs(Math.round(c.getBoundingClientRect().top) - top) < 4)
        .map((c) => Math.round(c.getBoundingClientRect().left))).size;
      cols = Math.max(cols, inRow);
    }
    const mainW = Math.round(main.getBoundingClientRect().width);
    const availW = Math.round(shell.getBoundingClientRect().width);
    return { mainW, availW, cols };
  });
  rows.push({
    screen: `${width}px`, pane: m.mainW, available: m.availW,
    unused: m.availW - m.mainW, columns: m.cols,
  });
  await page.close();
}
await b.close();
console.table(rows);
const wasted = rows.filter((r) => r.unused > 120);
console.log(wasted.length
  ? `${wasted.length} width(s) still leaving a gutter over 120px`
  : "the pane uses the screen at every width");
