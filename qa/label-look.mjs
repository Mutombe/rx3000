/** Render the dispensing label and look at it, at the size it is printed.
 *
 *  `label-fits.mjs` drives the whole application to get real labels, which
 *  means a dev server, a login and about a minute. This bundles `print.ts` on
 *  its own and calls the same function the print window calls, so the markup
 *  and the stylesheet are the real ones and nothing is transcribed by hand into
 *  a fixture — the way a fixture quietly stops matching what ships.
 *
 *      node qa/label-look.mjs                 58 x 42mm, the common roll
 *      node qa/label-look.mjs 50 30           any other sticker, in mm
 *
 *  It writes a PNG of the sticker at print size and says whether the content
 *  overflowed it. Overflow is the failure that matters: the CSS clips, so a
 *  label that is too tall does not look broken, it looks finished with the
 *  bottom missing — and the part that goes is the audit trail.
 */
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const WIDE = Number(process.argv[2] || 58);
const TALL = Number(process.argv[3] || 42);
const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "label.png");

// One sticker's worth of everything a dispensing carries, with the long values
// rather than the tidy ones: the labels that overflow are the long ones and a
// sample of short ones proves nothing.
const LABEL = {
  patient_name: "Munanawashe Chamburuka-Matoveru",
  patient_id_number: "63-1234567-A-42",
  rx_number: "RX260900015",
  product_name: "BLOCPAIN (ACECLOFENAC 100/PARACET 500MG)",
  strength: "",
  dosage_form: "Tablet",
  quantity: 30,
  dosage_instructions:
    "TAKE ONE TABLET ONCE A DAY AFTER FOOD WHEN REQUIRED FOR PAIN AND INFLAMMATION.",
  warnings: "",
  schedule: 4,
  schedule_code: "PP",
  batch_number: "OPENING",
  manufacturer: "",
  expiry_date: "2028-09-17",
  repeats_remaining: 0,
  next_repeat_date: null,
  doctor_name: "Maboreke Dr",
  doctor_practice_no: "106770",
  dispensed_by: "Vanesa Tokonyai",
  dispensed_at: "2026-09-17T14:22:09",
  pharmacy_name: "CareXpress Pharmacy",
  pharmacy_reg_no: "",
  pharmacy_address: "114 Samora Machel Avenue, Harare",
  pharmacy_phone: "0732 307 400",
  branch_code: "CX-CHI",
  branch_name: "CareXpress Chinamano",
  branch_address: "114 Samora Machel Avenue, Harare",
  branch_phone: "0732 307 400",
  branch_reg_no: "",
  item_number: 1,
  item_count: 2,
};

// Bundle print.ts with the project's own esbuild so the stylesheet and the
// markup under test are the ones that ship.
const dir = mkdtempSync(join(tmpdir(), "label-look-"));
const bundle = join(dir, "print.mjs");
const esbuild = await import(
  pathToFileURL(join(ROOT, "frontend", "node_modules", "esbuild", "lib", "main.js")).href);
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(ROOT, "frontend", "src", "print.ts")],
  bundle: true, format: "esm", platform: "browser", outfile: bundle,
  // Both reach into the running application; nothing on the label path calls
  // either, so they are stubbed below rather than dragged in.
  external: ["./components/Toast", "./api"],
  logLevel: "silent",
});
// Those two externals have to resolve to something at import time.
writeFileSync(bundle, readFileSync(bundle, "utf8")
  .replace(/^import .*Toast.*$/m, "const toast = { error(){}, ok(){} };")
  .replace(/^import .*\.\/api.*$/m, "const money = (n) => `$${Number(n).toFixed(2)}`;"));

const { labelSheetHtml } = await import(pathToFileURL(bundle).href);
const html = labelSheetHtml([LABEL], 1);

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
// A CSS millimetre is 96/25.4 px, so the page is the sticker at print scale.
const px = (mm) => Math.round(mm * (96 / 25.4));
const page = await browser.newPage({
  viewport: { width: px(WIDE), height: px(TALL) },
  deviceScaleFactor: 4,                       // legible when I look at it
});
await page.setContent(`<!doctype html><meta charset="utf-8">${html}`);
await page.waitForTimeout(150);

const fit = await page.evaluate((tall) => {
  const el = document.querySelector(".label");
  if (!el) return { found: false };
  const box = el.getBoundingClientRect();
  return {
    found: true,
    // The box is exactly the sticker and clips, so neither its height nor its
    // scrollHeight can report overflow — a clipped label measures as a label
    // that fits, which is the whole reason this failure went unseen. The
    // children are measured instead, with the box let go for the moment it
    // takes, so what is reported is the height the content actually wants.
    contentPx: (() => {
      const was = { h: el.style.height, o: el.style.overflow };
      el.style.height = "auto"; el.style.overflow = "visible";
      const wants = Math.ceil(el.getBoundingClientRect().height);
      el.style.height = was.h; el.style.overflow = was.o;
      return wants;
    })(),
    boxPx: Math.ceil(box.height),
    pagePx: tall,
    lines: [...el.querySelectorAll(".audit div")].map((d) => d.textContent.trim()),
    foot: [...el.querySelectorAll(".foot > *")].map((d) => d.textContent.trim()),
  };
}, px(TALL));

await page.screenshot({ path: OUT });
await browser.close();

console.log(`sticker   ${WIDE} x ${TALL}mm  (${px(WIDE)} x ${px(TALL)}px)`);
console.log(`content   ${fit.contentPx}px on a ${fit.pagePx}px sticker`);
console.log(`audit     ${fit.lines.join(" | ")}`);
console.log(`foot      ${fit.foot.join(" | ")}`);
const over = fit.contentPx - fit.pagePx;
console.log(over > 1
  ? `\nOVERFLOW by ${over}px — the bottom of the label is being cut off.`
  : `\nfits, with ${-over}px to spare.`);
console.log(`\nwritten to ${OUT}`);
