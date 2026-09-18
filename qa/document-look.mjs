/** Build a real statement and look at the pages that come out.
 *
 *      node qa/document-look.mjs            a statement that runs to 3 pages
 *      node qa/document-look.mjs 12         one that fits on a page
 *
 *  The statements, invoices, remittances and reports are the only RX5000 paper
 *  a browser prints rather than reportlab, and the browser is where the two
 *  things that go wrong live: the letterhead that only appears on page one, and
 *  a band positioned into the page margin that a printing engine puts somewhere
 *  else entirely. Neither is visible in the window, because the window is not
 *  paginated; both are visible on paper, which is where a wholesaler sees them.
 *
 *  So this prints it properly — chromium's own print pipeline, A4, the same
 *  path the print dialog takes — and writes a PNG of every page.
 *
 *  It writes qa/out/document-p1.png and one for each further page.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const OUT = join(ROOT, "qa", "out");
const PDF = join(OUT, "document.pdf");
const ROWS = Number(process.argv[2] || 64);

const HEAD = {
  display_name: "CareXpress Pharmacy",
  legal_name: "CareXpress Health (Private) Limited",
  address: ["114 Samora Machel Avenue", "Harare", "Zimbabwe"],
  phone: "0242 704 118",
  email: "accounts@carexpress.co.zw",
  registration_no: "12345/2019",
  vat_no: "220198765",
  bank_name: "CBZ Bank",
  bank_account: "02114 7789 0031",
  bank_branch: "Kwame Nkrumah",
  document_footer: "CareXpress Health (Private) Limited",
};

const money = (n) => n.toLocaleString("en-ZW", { minimumFractionDigits: 2,
                                                maximumFractionDigits: 2 });
const WHAT = ["Invoice", "Invoice", "Invoice", "Credit note", "Payment received",
              "Invoice", "Invoice", "Adjustment"];

let running = 4821.55;
const rows = Array.from({ length: ROWS }, (_, i) => {
  const kind = WHAT[i % WHAT.length];
  const amount = kind === "Payment received" || kind === "Credit note"
    ? -(120 + ((i * 137) % 900))
    : 80 + ((i * 211) % 1400);
  running += amount;
  const day = new Date(2026, 5 + Math.floor(i / 28), 1 + (i % 28));
  return {
    date: day.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
    ref: `${kind === "Payment received" ? "RCT" : "INV"}-${String(20481 + i)}`,
    what: kind,
    debit: amount > 0 ? money(amount) : "",
    credit: amount < 0 ? money(-amount) : "",
    balance: money(running),
  };
});

const OPTIONS = {
  kind: "Statement",
  to: ["Zimbabwe Pharmaceutical Wholesalers", "Account ZPW-0442",
       "27 Chinhoyi Street", "Harare"],
  meta: [
    { label: "Statement date", value: "18 September 2026" },
    { label: "Account", value: "ZPW-0442" },
    { label: "Terms", value: "30 days from statement" },
    { label: "Amount due", value: `USD ${money(running)}`, strong: true },
  ],
  columns: [
    { key: "date", label: "Date", width: "24mm" },
    { key: "ref", label: "Reference", width: "28mm" },
    { key: "what", label: "Detail" },
    { key: "debit", label: "Charges", numeric: true, width: "26mm" },
    { key: "credit", label: "Payments", numeric: true, width: "26mm" },
    { key: "balance", label: "Balance", numeric: true, width: "28mm" },
  ],
  opening: { date: "01 Jun 2026", ref: "", what: "Balance brought forward",
             debit: "", credit: "", balance: money(4821.55) },
  rows,
  totals: { date: "", ref: "", what: "Closing balance", debit: "", credit: "",
            balance: money(running) },
  ageing: [
    { label: "Current", value: money(running * 0.42) },
    { label: "30 days", value: money(running * 0.31) },
    { label: "60 days", value: money(running * 0.18) },
    { label: "90 days and over", value: money(running * 0.09) },
    { label: "Total due", value: money(running), strong: true },
  ],
  note: "Please quote the account number with any payment. Queries on any line "
      + "should reach us within seven days of this statement, after which the "
      + "balance is taken as agreed.",
};

mkdirSync(OUT, { recursive: true });
const dir = mkdtempSync(join(tmpdir(), "document-"));
const bundle = join(dir, "document.mjs");
const esbuild = await import(
  pathToFileURL(join(ROOT, "frontend", "node_modules", "esbuild", "lib", "main.js")).href);
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(ROOT, "frontend", "src", "document.ts")],
  bundle: true, format: "esm", platform: "browser", outfile: bundle,
  logLevel: "silent",
});
// The font is its own module so a session that never prints never loads it,
// which means it is also not in the bundle above. Rendering without it would
// be looking at the fallback stack and calling it Manrope.
const fontBundle = join(dir, "docFont.mjs");
await (esbuild.default ?? esbuild).build({
  entryPoints: [join(ROOT, "frontend", "src", "docFont.ts")],
  bundle: true, format: "esm", platform: "browser", outfile: fontBundle,
  logLevel: "silent",
});

const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228/"
    + "chrome-headless-shell-win64/chrome-headless-shell.exe",
});
const page = await browser.newPage();
await page.goto("about:blank");

const html = await page.evaluate(async ({ src, fontSrc, head, options }) => {
  const as = (s) => `data:text/javascript;base64,${btoa(unescape(encodeURIComponent(s)))}`;
  const mod = await import(as(src));
  const font = await import(as(fontSrc));
  return mod.renderDocument(head, options, font.DOC_FONT);
}, { src: readFileSync(bundle, "utf8"), fontSrc: readFileSync(fontBundle, "utf8"),
     head: HEAD, options: OPTIONS });

writeFileSync(join(OUT, "document.html"), html);
await page.setContent(html, { waitUntil: "load" });
// The @page rule carries the size and the margins. Letting playwright set them
// would be testing playwright's numbers rather than the document's.
await page.pdf({ path: PDF, preferCSSPageSize: true, printBackground: true });
await browser.close();

// One PNG a page, so the letterhead on page three can actually be looked at.
const shot = execFileSync("python", ["-c", `
import pypdfium2 as p, sys
d = p.PdfDocument(r"${PDF}")
for i in range(len(d)):
    d[i].render(scale=150/72).to_pil().save(r"${join(OUT, "document-p")}" + str(i + 1) + ".png")
print(len(d))
`], { encoding: "utf8" }).trim();

console.log(`rows      ${ROWS}`);
console.log(`pages     ${shot}`);
console.log(`pdf       ${PDF}`);
console.log(`png       ${join(OUT, "document-p1.png")} (and one per page)`);
