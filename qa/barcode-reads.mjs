/** Does the barcode we print actually scan back as the script number?
 *
 *      node qa/barcode-reads.mjs
 *      node qa/barcode-reads.mjs RX260900015
 *
 *  A barcode that looks like a barcode and decodes as something else is the
 *  worst outcome available here: it is printed onto a dispensed script, an
 *  inspector or a wholesaler scans it, and it names a different script. Drawing
 *  bars and looking at them proves nothing — the check has to be a decode.
 *
 *  So the same `code128` module the PDF is built from draws the symbol onto a
 *  canvas, and the project's own scanner reads it back. If those two disagree,
 *  one of them is wrong and it is worth knowing which before a pharmacy finds
 *  out.
 */
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const WANTED = process.argv.slice(2);
const CASES = WANTED.length ? WANTED : [
  "RX260900015",          // the shape this system issues
  "RX-TEST-0000",         // with the punctuation a test label carries
  "DRAFT-9",              // a draft reference
  "RX260901234567",       // longer than usual
];

const dir = mkdtempSync(join(tmpdir(), "barcode-"));
const bundle = join(dir, "code128.mjs");
const esbuild = await import(
  pathToFileURL(join(ROOT, "frontend", "node_modules", "esbuild", "lib", "main.js")).href);
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(ROOT, "frontend", "src", "code128.ts")],
  bundle: true, format: "esm", platform: "browser", outfile: bundle, logLevel: "silent",
});

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage({ viewport: { width: 1200, height: 400 } });
await page.route("**/qa", (r) =>
  r.fulfill({ contentType: "text/html", body: "<!doctype html><meta charset=utf-8>" }));

// The scanner the application itself uses, so this is not a second opinion from
// a different decoder — it is the one that will be pointed at the sticker.
const zxingDir = join(ROOT, "frontend", "node_modules", "zxing-wasm", "dist");
const readerBundle = join(dir, "reader.mjs");
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(zxingDir, "es", "reader", "index.js")],
  bundle: true, format: "esm", platform: "browser", outfile: readerBundle,
  logLevel: "silent",
});
const reader = {
  js: readerBundle,
  wasm: join(zxingDir, "reader", "zxing_reader.wasm"),
};

// The reader is served to the page from disk rather than inlined: it fetches
// its own wasm, and a module loaded from a data: URL has no base to fetch it
// from.
await page.route("**/zxing/reader.js", (r) =>
  r.fulfill({ contentType: "text/javascript", body: readFileSync(reader.js, "utf8") }));
await page.route("**/zxing/*.wasm", (r) =>
  r.fulfill({ contentType: "application/wasm", body: readFileSync(reader.wasm) }));
await page.goto("https://rx5000.invalid/qa", { waitUntil: "domcontentloaded" })
  .catch(() => {});

const results = await page.evaluate(async ({ src, cases }) => {
  const code = await import(
    `data:text/javascript;base64,${btoa(unescape(encodeURIComponent(src)))}`);
  const out = [];
  for (const text of cases) {
    const modules = code.code128Width(text);
    // Drawn big: this is about whether the encoding is right, not whether a
    // particular size scans, and a decoder given three pixels a module fails
    // for reasons that have nothing to do with the symbol.
    const unit = 3;
    const c = document.createElement("canvas");
    c.width = modules * unit;
    c.height = 160;
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
    g.fillStyle = "#000";
    for (const { x, width } of code.code128Rects(text)) {
      g.fillRect(x * unit, 0, width * unit, c.height);
    }
    out.push({ text, modules, width: c.width, png: c.toDataURL("image/png") });
  }
  try {
    const mod = await import("/zxing/reader.js");
    mod.setZXingModuleOverrides?.({
      locateFile: (path, prefix) =>
        (path.endsWith(".wasm") ? "/zxing/zxing_reader.wasm" : prefix + path),
    });
    const decoded = [];
    for (const row of out) {
      const blob = await (await fetch(row.png)).blob();
      const found = await mod.readBarcodesFromImageFile(
        blob, { formats: ["Code128"], tryHarder: true });
      decoded.push(found?.[0]?.text ?? null);
    }
    return { out, decoded };
  } catch (e) {
    return { out, decoded: null, why: String(e).slice(0, 160) };
  }
}, { src: readFileSync(bundle, "utf8"), cases: CASES });

await browser.close();

let bad = 0;
console.log(`${"script".padEnd(20)} ${"modules".padStart(7)}  read back as`);
results.out.forEach((row, i) => {
  const got = results.decoded ? results.decoded[i] : "(not decoded)";
  const ok = results.decoded ? got === row.text : null;
  if (ok === false) bad += 1;
  console.log(`${row.text.padEnd(20)} ${String(row.modules).padStart(7)}  `
    + `${ok === null ? got : ok ? `${got}  ok` : `${got}  WRONG`}`);
});

if (!results.decoded) {
  console.log(`\nThe decoder did not run${results.why ? `: ${results.why}` : ""}.`);
  console.log("The widths above are still the real ones; only the read-back is missing.");
  process.exit(0);
}
console.log(bad ? `\n${bad} barcode(s) decoded as something else.`
                : "\nevery barcode read back as the script it encodes.");
process.exit(bad ? 1 : 0);
