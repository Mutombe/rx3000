/** The barcode ON THE LABEL, scanned back off the label.
 *
 *      node qa/label-barcode-reads.mjs
 *
 *  qa/barcode-reads.mjs proves the encoder: it draws the symbol from
 *  `code128.ts` onto a canvas and reads it back. That is a different claim from
 *  this one. This builds the real dispensing label as a PDF, rasterises it the
 *  way a printer driver would, and scans the bars out of the picture.
 *
 *  Everything between those two claims is where it can go wrong: the module
 *  width once it is fitted to the sticker, the rectangles written into the
 *  content stream, the y-flip into PDF coordinates, and whether the bars got
 *  clipped off the bottom edge by a layout that did not quite fit. None of that
 *  is visible in a picture of a barcode, which always looks like a barcode.
 *
 *  It checks a busy label as well as a quiet one, because a busy one is shrunk
 *  to fit and a shrunk label is where the bars would be squeezed out.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "out");
mkdirSync(OUT, { recursive: true });

const STICKER = { wide: 58, tall: 42 };

const QUIET = {
  product_name: "BLOCPAIN", strength: "(ACECLOFENAC 100/PARACET 500MG)",
  dosage_form: "Tablet", quantity: 30, schedule_code: "PP",
  dosage_instructions: "Take one tablet once a day after food when required for pain.",
  warnings: "", batch_number: "OPENING", expiry_date: "2028-09-17", manufacturer: "",
  patient_name: "Munanawashe Chamburuka-Matoveru",
  dispensed_at: "2026-09-17T14:22:09", dispensed_by: "Vanesa Tokonyai",
  doctor_name: "Maboreke Dr", rx_number: "RX260900015",
  item_number: 1, item_count: 2, doctor_practice_no: "106770",
  branch_code: "CX-CHI", branch_name: "CareXpress Chinamano",
  branch_address: "114 Samora Machel Avenue, Harare", branch_phone: "0732 307 400",
};
const BUSY = {
  ...QUIET,
  rx_number: "RX260901234",
  product_name: "AMOXICILLIN/CLAVULANIC ACID",
  strength: "(AUGMENTIN 875MG/125MG FILM COATED TABLETS)",
  warnings: "MAY CAUSE DROWSINESS. DO NOT DRIVE OR OPERATE MACHINERY. AVOID ALCOHOL.",
  manufacturer: "Zimbabwe Pharmaceutical Manufacturers Limited",
  dosage_instructions: "Take two tablets three times a day after food for seven "
    + "days, then one tablet twice a day until the course is finished.",
};

let bad = 0;
const check = (ok, label, extra = "") => {
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${label}${extra ? "   " + extra : ""}`);
};

// ---- build the labels, in a browser, from the real module -------------------
const dir = mkdtempSync(join(tmpdir(), "lblbc-"));
const bundle = join(dir, "labelPdf.mjs");
const esbuild = await import(pathToFileURL(
  join(ROOT, "frontend", "node_modules", "esbuild", "lib", "main.js")).href);
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(ROOT, "frontend", "src", "labelPdf.ts")],
  bundle: true, format: "esm", platform: "browser", outfile: bundle, logLevel: "silent",
});

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage();

// The scanner the application itself uses, served from disk: it fetches its own
// wasm, and a module loaded from a data: URL has no base to fetch it from.
const zxingDir = join(ROOT, "frontend", "node_modules", "zxing-wasm", "dist");
const readerBundle = join(dir, "reader.mjs");
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(zxingDir, "es", "reader", "index.js")],
  bundle: true, format: "esm", platform: "browser", outfile: readerBundle,
  logLevel: "silent",
});
await page.route("**/qa", (r) =>
  r.fulfill({ contentType: "text/html", body: "<!doctype html><meta charset=utf-8>" }));
await page.route("**/zxing/reader.js", (r) =>
  r.fulfill({ contentType: "text/javascript", body: readFileSync(readerBundle, "utf8") }));
await page.route("**/zxing/*.wasm", (r) =>
  r.fulfill({ contentType: "application/wasm",
              body: readFileSync(join(zxingDir, "reader", "zxing_reader.wasm")) }));
await page.route("**/shot/*.png", (r) =>
  r.fulfill({ contentType: "image/png",
              body: readFileSync(join(OUT, r.request().url().split("/").pop())) }));
await page.goto("https://rx5000.invalid/qa", { waitUntil: "domcontentloaded" }).catch(() => {});

const built = await page.evaluate(async ({ src, cases, sticker }) => {
  const m = await import(`data:text/javascript;base64,${btoa(unescape(encodeURIComponent(src)))}`);
  const out = {};
  for (const [name, label] of Object.entries(cases)) {
    const bytes = m.labelPdf(label, sticker);
    const bars = m.labelBarcode(label, sticker);
    out[name] = {
      b64: btoa(String.fromCharCode(...bytes)),
      mm: +m.labelHeightMm(label, sticker).toFixed(2),
      scale: +m.labelFitScale(label, sticker).toFixed(3),
      moduleMm: bars ? +bars.moduleMm.toFixed(3) : 0,
      rects: bars ? bars.rects.length : 0,
      wants: label.rx_number,
    };
  }
  return out;
}, { src: readFileSync(bundle, "utf8"), cases: { quiet: QUIET, busy: BUSY }, sticker: STICKER });

for (const [name, r] of Object.entries(built)) {
  writeFileSync(join(OUT, `label-${name}.pdf`), Buffer.from(r.b64, "base64"));
  check(r.mm <= STICKER.tall, `the ${name} label fits the sticker`,
        `${r.mm}mm of ${STICKER.tall}, at ${Math.round(r.scale * 100)}% size`);
  check(r.rects > 0, `and carries bars`, `${r.rects} of them`);
  // Below about 0.19mm a module stops being readable by an ordinary handheld.
  check(r.moduleMm >= 0.19, `wide enough to scan`, `${r.moduleMm}mm a module`);
}

// ---- rasterise the way a driver would, and scan it --------------------------
const png = execFileSync("python", ["-c", `
import pypdfium2 as p
for name in ("quiet", "busy"):
    d = p.PdfDocument(r"${join(OUT, "label-")}" + name + ".pdf")
    d[0].render(scale=600/72).to_pil().save(r"${join(OUT, "label-")}" + name + ".png")
print("rendered")
`], { encoding: "utf8" }).trim();
console.log(`      ${png} at 600dpi, the way a driver rasterises`);

for (const [name, r] of Object.entries(built)) {
  const read = await page.evaluate(async (file) => {
    const mod = await import("/zxing/reader.js");
    mod.setZXingModuleOverrides?.({
      locateFile: (path, prefix) =>
        (path.endsWith(".wasm") ? "/zxing/zxing_reader.wasm" : prefix + path),
    });
    const blob = await (await fetch(file)).blob();
    const found = await mod.readBarcodesFromImageFile(
      blob, { formats: ["Code128"], tryHarder: true });
    return (found || []).map((f) => f.text);
  }, `/shot/label-${name}.png`);
  check(read.includes(r.wants),
        `the ${name} label scans back as its own script number`,
        read.length ? read.join(", ") : "nothing read");
}

await browser.close();
console.log(bad ? `\n${bad} FAILED` : "\nthe barcode on the label reads back as the script.");
process.exit(bad ? 1 : 0);
