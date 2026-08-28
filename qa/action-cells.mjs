/** No button may be cut off by the column it sits in.
 *
 *  This has now been decided three times and reversed twice. Action cells are
 *  meant to `clip`, not ellipsis: three dots at the end of a row of buttons read
 *  as a "more actions" menu, do nothing when clicked, and disguise the fact that
 *  a control has been sliced off at the cell edge. Two later stylesheet rules set
 *  `ellipsis` anyway — one of them directly beneath its own comment instructing
 *  the opposite — and the buttons went back to being unreachable.
 *
 *  A comment cannot defend a decision. This can: it measures each button against
 *  the cell it sits in and fails when one hangs outside, which is the thing that
 *  actually matters and the thing nobody can see by looking.
 *
 *      node qa/action-cells.mjs          # needs the dev server on :5180
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 1500, height: 950 } });
await page.goto("http://localhost:5180/login"); await page.waitForTimeout(1200);
const i = await page.locator("input").all();
await i[0].fill("admin"); await i[1].fill("admin123");
await page.keyboard.press("Enter"); await page.waitForTimeout(3000);
const failures = [];
const PAGES = ["/will-call","/to-follows","/repeats","/claims-held","/payables","/deliveries",
               "/laybys","/orders","/remittances?tab=advices","/recall","/shifts","/reminders"];
console.log("ACTION cells only — text-overflow, and whether a real button is clipped:\n");
for (const p of PAGES) {
  await page.goto("http://localhost:5180" + p, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3600);
  const r = await page.evaluate(() => {
    const cells = [...document.querySelectorAll("td.actions, td.lb-actions")];
    if (!cells.length) return null;
    const td = cells[0];
    const cs = getComputedStyle(td);
    const btns = [...td.querySelectorAll("button")];
    const clipped = btns.filter(x => {
      const br = x.getBoundingClientRect(), tr = td.getBoundingClientRect();
      return br.right > tr.right + 1;
    });
    return { n: cells.length, overflow: cs.overflow, to: cs.textOverflow,
             over: td.scrollWidth - td.clientWidth, btns: btns.length,
             clipped: clipped.map(x => x.textContent.trim()) };
  });
  if (!r) { console.log(`  —    ${p.padEnd(24)} no action cells`); continue; }
  const bad = r.clipped.length > 0;
  if (bad) failures.push(`${p}: ${r.clipped.join(" / ")}`);
  // An ellipsis on an action cell is the disguise itself, so it fails too —
  // even when nothing happens to be overflowing at this width today.
  if (r.to === "ellipsis") failures.push(`${p}: action cell still set to ellipsis`);
  console.log(`  ${bad ? "FAIL" : "ok  "} ${p.padEnd(24)} text-overflow:${r.to.padEnd(8)} ${String(r.over).padStart(4)}px over, ${r.btns} buttons${bad ? ", CLIPPED: " + r.clipped.join(" / ") : ""}`);
}
await b.close();
if (failures.length) {
  console.log("");
  console.log(failures.length + " failing:");
  for (const f of failures) console.log("  " + f);
} else {
  console.log("");
  console.log("no button is cut off");
}
process.exit(failures.length ? 1 : 0);
