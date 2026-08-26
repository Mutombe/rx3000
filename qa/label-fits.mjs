/** Does the printed label actually fit on the label?
 *
 *  The sticker is 58 × 42mm and the CSS clips whatever exceeds it, so a label
 *  that is too tall does not look broken — it looks finished, with the bottom
 *  silently missing. That is the worst possible failure for a dispensing label:
 *  the part that gets cut is the audit trail, and nobody notices until an
 *  inspector asks.
 *
 *  This renders the real markup at the real size and measures. It fails on
 *  overflow rather than on appearance, because appearance is what hid it.
 */
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const b = await chromium.launch({ executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe" });
const page = await b.newPage({ viewport: { width: 900, height: 900 } });
await page.goto("http://localhost:5180/login");
await page.waitForTimeout(900);
const i = await page.locator("input").all();
await i[0].fill("admin"); await i[1].fill("admin123");
await page.keyboard.press("Enter");
await page.waitForTimeout(2400);

// Real labels off a real script, not a fixture: the長 ones are the problem and a
// fixture is always the short one somebody had to hand.
const rows = await page.evaluate(async () => {
  const token = localStorage.getItem("rx5000_token") || localStorage.getItem("rx3000_token");
  const h = { Authorization: `Bearer ${token}` };
  const scripts = await (await fetch("/api/prescriptions?limit=40", { headers: h })).json();
  const list = Array.isArray(scripts) ? scripts : scripts.items ?? [];
  const out = [];
  for (const s of list.slice(0, 25)) {
    try {
      const labels = await (await fetch(`/api/prescriptions/${s.id}/labels`, { headers: h })).json();
      out.push(...labels);
    } catch { /* a script with nothing dispensed has no labels */ }
  }
  return out;
});
console.log(`measuring ${rows.length} real labels`);

const measured = await page.evaluate(async ({ labels }) => {
  const mod = await import("/src/print.ts");
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;left:-9999px;width:400px;height:800px";
  document.body.appendChild(frame);
  const d = frame.contentDocument;
  const out = [];
  for (const l of labels) {
    d.open();
    d.write(mod.labelSheetHtml ? mod.labelSheetHtml([l]) : "");
    d.close();
    await new Promise((r) => setTimeout(r, 30));
    const el = d.querySelector(".label");
    if (!el) continue;
    out.push({
      patient: l.patient_name,
      product: l.product_name,
      sig: (l.dosage_instructions || "").length,
      warn: (l.warnings || "").length,
      needed: Math.round(el.scrollHeight),
      have: Math.round(el.clientHeight),
    });
  }
  frame.remove();
  return out;
}, { labels: rows });

const over = measured.filter((m) => m.needed > m.have + 1);
console.table(over.slice(0, 12));
console.log(`${over.length} of ${measured.length} labels overflow their sticker`);
if (over.length) {
  const worst = over.reduce((a, b) => (b.needed - b.have > a.needed - a.have ? b : a));
  console.log(`worst: needs ${worst.needed}px in ${worst.have}px — ${worst.needed - worst.have}px cut`);
}
await b.close();
