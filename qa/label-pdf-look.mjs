/** Build the label PDF and look at it, at the size of the sticker.
 *
 *      node qa/label-pdf-look.mjs              58 x 42mm
 *      node qa/label-pdf-look.mjs 76 51        any other roll, in mm
 *
 *  The PDF is what a label printer is actually sent now — the driver rasterises
 *  it, so what is in this file is what comes off the roll. Writing it and
 *  opening it in a browser is the only way to see that before a pharmacy does.
 *
 *  It writes the PDF and a PNG of its first page, and reports how much of the
 *  sticker the content wanted. Overflow is the failure that matters: the driver
 *  clips silently, so a label that is too tall does not look broken, it looks
 *  finished with the footer missing.
 */
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const WIDE = Number(process.argv[2] || 58);
const TALL = Number(process.argv[3] || 42);
const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const PDF = join(ROOT, "qa", "label.pdf");
const PNG = join(ROOT, "qa", "label-pdf.png");

// The long values, not the tidy ones: a sample of short fields proves nothing
// about the labels that overflow.
const LABEL = {
  patient_name: "Munanawashe Chamburuka-Matoveru",
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
  doctor_name: "Maboreke Dr",
  doctor_practice_no: "106770",
  dispensed_by: "Vanesa Tokonyai",
  dispensed_at: "2026-09-17T14:22:09",
  pharmacy_name: "CareXpress Pharmacy",
  pharmacy_address: "114 Samora Machel Avenue, Harare",
  pharmacy_phone: "0732 307 400",
  branch_code: "CX-CHI",
  branch_name: "CareXpress Chinamano",
  branch_address: "114 Samora Machel Avenue, Harare",
  branch_phone: "0732 307 400",
  item_number: 1,
  item_count: 2,
};

const dir = mkdtempSync(join(tmpdir(), "label-pdf-"));
const bundle = join(dir, "labelPdf.mjs");
const esbuild = await import(
  pathToFileURL(join(ROOT, "frontend", "node_modules", "esbuild", "lib", "main.js")).href);
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(ROOT, "frontend", "src", "labelPdf.ts")],
  bundle: true, format: "esm", platform: "browser", outfile: bundle, logLevel: "silent",
});

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage();

// Built inside the browser, because the widths are measured with a canvas and
// that is where the real font metrics are — the same place the desktop app
// builds it.
await page.goto("about:blank");
const built = await page.evaluate(async ({ src, label, wide, tall }) => {
  const mod = await import(`data:text/javascript;base64,${btoa(unescape(encodeURIComponent(src)))}`);
  const bytes = mod.labelPdf(label, { wide, tall });
  return {
    b64: btoa(String.fromCharCode(...bytes)),
    wantsMm: mod.labelHeightMm(label, { wide, tall }),
  };
}, { src: readFileSync(bundle, "utf8"), label: LABEL, wide: WIDE, tall: TALL });

writeFileSync(PDF, Buffer.from(built.b64, "base64"));

// Look at it the way the driver will. The headless shell has no PDF viewer, so
// the same placement the PDF is built from is drawn on a canvas instead —
// identical numbers, identical fonts, from `labelPlacement`, so this is not a
// separate rendering that can drift away from the file.
const px = (mm) => Math.round(mm * (96 / 25.4));
const view = await browser.newPage({
  viewport: { width: px(WIDE), height: px(TALL) }, deviceScaleFactor: 4,
});
await view.goto("about:blank");
await view.evaluate(async ({ src, label, wide, tall }) => {
  const mod = await import(`data:text/javascript;base64,${btoa(unescape(encodeURIComponent(src)))}`);
  const PTpx = 96 / 72;                       // a point, in CSS pixels
  const c = document.createElement("canvas");
  c.width = Math.round(wide * (96 / 25.4));
  c.height = Math.round(tall * (96 / 25.4));
  c.style.cssText = "position:fixed;inset:0";
  document.body.style.margin = "0";
  document.body.appendChild(c);
  const g = c.getContext("2d");
  g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#111"; g.textBaseline = "alphabetic";
  for (const line of mod.labelPlacement(label, { wide, tall })) {
    g.font = mod.cssFontFor(line.font, line.size);
    g.fillText(line.text, line.x * PTpx, line.y * PTpx);
  }
}, { src: readFileSync(bundle, "utf8"), label: LABEL, wide: WIDE, tall: TALL });
await view.waitForTimeout(200);
await view.screenshot({ path: PNG });
await browser.close();

console.log(`sticker   ${WIDE} x ${TALL}mm`);
console.log(`content   wants ${built.wantsMm.toFixed(1)}mm of ${TALL}mm`);
console.log(`pdf       ${PDF}`);
console.log(`png       ${PNG}`);
const over = built.wantsMm - TALL;
console.log(over > 0.2
  ? `\nOVERFLOW by ${over.toFixed(1)}mm — the bottom would be cut off.`
  : `\nfits, with ${(-over).toFixed(1)}mm to spare.`);
