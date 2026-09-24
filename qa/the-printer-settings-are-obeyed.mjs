/** What a pharmacy sets on the printer page is what the till actually does.
 *
 *  The settings are a list of documents and a printer beside each. Nothing
 *  between that page and the spooler is visible: a route that silently falls
 *  back, or a label sent in the wrong language, looks exactly like a printer
 *  fault, and the pharmacy spends its afternoon on the printer.
 *
 *  That is not hypothetical. The reprint screen ignored the setting entirely
 *  and sent receipt codes to a label printer, which accepted the job, threw it
 *  away, and let the application report success.
 *
 *  So this drives the real module with a real browser, a real localStorage and
 *  a stubbed shell that records every job, and asserts what came out:
 *
 *    - each document goes to the printer chosen for it,
 *    - a document nobody has routed follows the label roll, which is what
 *      makes one printer work for everything until somebody says otherwise,
 *    - a Zebra is sent ZPL as a raw job, not a PDF and not receipt codes,
 *    - a Zebra somebody has RENAMED is still sent ZPL, because the driver says
 *      so even when the name no longer does,
 *    - and a printer nobody recognises is NOT sent ZPL, because guessing wrong
 *      in that direction prints pages of rubbish.
 *
 *  Run by exit code. Nought is a pass.
 */
import { execFileSync } from "node:child_process";
import { chromium } from "file:///C:/Users/PC/AppData/Roaming/npm/node_modules/openclaw/node_modules/playwright-core/index.mjs";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FRONT = path.join(ROOT, "frontend");
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), "rx-route-"));

const LABEL = {
  patient_name: "Tendai Mukoma", patient_id_number: "", rx_number: "RX-2026-004417",
  product_name: "AMOXICILLIN TRIHYDRATE", strength: "500MG", dosage_form: "Capsule",
  quantity: 21, dosage_instructions: "TAKE ONE CAPSULE THREE TIMES A DAY",
  warnings: "", schedule: 4, schedule_code: "PP", batch_number: "AMX-4471",
  manufacturer: "Varichem", expiry_date: "2028-03-31", repeats_remaining: 0,
  next_repeat_date: null, doctor_name: "Dr N Chirwa", doctor_practice_no: "0412337",
  dispensed_by: "S. Adams", dispensed_at: "2026-09-24T12:00:00Z",
  pharmacy_name: "Demo", pharmacy_reg_no: "", pharmacy_address: "",
  pharmacy_phone: "", item_number: 1, item_count: 1, unit_price: 0, line_total: 0,
  branch_code: "HRE1", branch_name: "Demo Avondale",
  branch_address: "12 King George Road, Harare", branch_phone: "+263 242 335 118",
  branch_reg_no: "", dispensing_id: 1,
};

function bundle() {
  const entry = path.join(WORK, "entry.ts");
  fs.writeFileSync(entry,
    `import * as roll from ${JSON.stringify(path.join(FRONT, "src", "shellPrinter.ts"))};\n` +
    `(window as any).ROLL = roll;\n`);
  const out = path.join(WORK, "route.js");
  const exe = path.join(FRONT, "node_modules", "@esbuild",
    process.platform === "win32" ? "win32-x64/esbuild.exe" : "linux-x64/bin/esbuild");
  const here = fs.existsSync(exe);
  execFileSync(here ? exe : "npx",
    [...(here ? [] : ["esbuild"]), entry, "--bundle", `--outfile=${out}`,
     "--format=iife", "--log-level=error",
     // Vite's own globals, which esbuild does not define.
     `--define:import.meta.env={"DEV":false,"PROD":true,"MODE":"production","BASE_URL":"/"}`],
    { cwd: FRONT, stdio: ["ignore", "ignore", "inherit"], shell: !here });
  return out;
}

/** The shell, stubbed to remember what it was asked to print. */
function stub() {
  window.__SENT__ = [];
  window.__PRINTERS__ = [];
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    if (cmd === "list_printers") return window.__PRINTERS__;
    window.__SENT__.push({
      cmd, printer: args.printer, bytes: args.data.length,
      head: String.fromCharCode(...args.data.slice(0, 3)),
    });
    return args.data.length;
  } } };
}

const faults = [];
const say = (ok, what) => {
  if (ok) console.log(`  ok  ${what}`);
  else faults.push(what);
};

const script = bundle();
const browser = await chromium.launch({
  executablePath: "C:/Users/PC/AppData/Local/ms-playwright/chromium_headless_shell-1228"
    + "/chrome-headless-shell-win64/chrome-headless-shell.exe",
});
try {
  const page = await browser.newPage();
  // A real origin: the printer settings live in localStorage and about:blank
  // has none. This is the till's own storage, exactly as shipped.
  await page.route("**/*", (r) => r.fulfill({
    contentType: "text/html", body: "<!doctype html><meta charset=utf-8><body></body>" }));
  await page.goto("http://rx-till.test/");
  await page.evaluate(stub);
  await page.addScriptTag({ path: script });
  await page.evaluate(() => document.fonts.ready);

  const got = await page.evaluate(async (LABEL) => {
    const roll = window.ROLL;
    const run = async (printers, set) => {
      window.__PRINTERS__ = printers;
      window.__SENT__ = [];
      set(roll);
      await roll.listPrinterInfo();
      await roll.printLabelsDirect([LABEL]);
      return { sent: window.__SENT__, mode: roll.resolvedLabelMode() };
    };

    const ZEBRA = { name: "ZDesigner ZD421-203dpi ZPL",
                    driver: "ZDesigner ZD421-203dpi ZPL", port: "USB002" };
    const TILL = { name: "EPSON TM-T20III Receipt",
                   driver: "EPSON TM-T20III ReceiptE4", port: "USB001" };
    const LASER = { name: "HP LaserJet M404", driver: "HP LaserJet M404 PCL-6", port: "USB003" };

    // What a pharmacy does on the settings page.
    const three = await run([ZEBRA, TILL, LASER], (r) => {
      r.setLabelMode("auto");
      r.choosePrinter(ZEBRA.name, 32);
      r.routeTo("receipt", TILL.name);
      r.routeTo("claim", LASER.name);
      r.setSticker(58, 42);
    });
    const routes = Object.fromEntries(
      roll.DOC_KINDS.map((d) => [d.kind, roll.printerFor(d.kind)]));

    // The same printer, renamed to something that says nothing.
    const renamed = await run(
      [{ name: "Labels", driver: "ZDesigner ZD421-203dpi ZPL", port: "USB002" }],
      (r) => r.choosePrinter("Labels", 32));

    // A printer nobody recognises must NOT be sent ZPL.
    const unknown = await run(
      [{ name: "Brother QL-800", driver: "Brother QL-800", port: "USB004" }],
      (r) => r.choosePrinter("Brother QL-800", 32));

    return { three, routes, renamed, unknown };
  }, LABEL);

  const zebra = "ZDesigner ZD421-203dpi ZPL";
  say(got.routes.label === zebra, `the dispensing label goes to the roll it was given`);
  say(got.routes.receipt === "EPSON TM-T20III Receipt",
      `the receipt goes to the receipt printer, not the label roll`);
  say(got.routes.claim === "HP LaserJet M404", `the claim copy goes to the A4 laser`);
  say(got.routes.price === zebra && got.routes.delivery === zebra,
      `a document nobody routed follows the label roll`);

  const one = got.three.sent[0] ?? {};
  say(got.three.mode === "zpl" && one.cmd === "print_raw" && one.printer === zebra
      && one.head === "^XA",
      `a Zebra is sent ZPL as a raw job (${one.cmd}, ${one.bytes} bytes, starts ${one.head})`);

  const r = got.renamed.sent[0] ?? {};
  say(got.renamed.mode === "zpl" && r.head === "^XA" && r.printer === "Labels",
      `a Zebra renamed "Labels" is still sent ZPL, because its driver says so`);

  say(got.unknown.mode !== "zpl" && !(got.unknown.sent[0]?.head === "^XA"),
      `a printer nobody recognises is not sent ZPL on a guess`);
} finally {
  await browser.close();
  fs.rmSync(WORK, { recursive: true, force: true });
}

if (faults.length) {
  console.log("\nThe printer settings are not being obeyed.\n");
  for (const f of faults) console.log(`    not true: ${f}`);
  console.log("\n  Every route is decided by shellPrinter.ts. A screen that "
            + "prints its own way,\n  or a language chosen without reading the "
            + "driver, shows up here and\n  nowhere else, because a printer "
            + "given the wrong thing says nothing.");
  process.exit(1);
}
console.log("\nEvery document goes where the pharmacy sent it, in a language "
          + "its printer speaks.");
